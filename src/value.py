"""
value.py
Motor de VALOR: compara la probabilidad del modelo contra la del mercado y
decide si hay apuesta.

La idea completa en tres pasos:

  1. La cuota se traduce a probabilidad. Una cuota 2.50 dice "esto pasa 40% de
     las veces". Pero las cuotas de las dos esquinas suman más de 100% (ese
     exceso es la comisión de la casa, el "vig" o "juice"). Se normaliza para
     que sumen 100: eso deja la OPINIÓN LIMPIA del mercado.

  2. Se resta la opinión del modelo menos la del mercado. Eso es la
     DISCREPANCIA. Si el modelo dice 62% y el mercado 48%, hay 14 puntos de
     desacuerdo.

  3. Discrepar no basta: hay que ver si el PAGO compensa. Ahí entra el EV
     (valor esperado). Apostar 1 unidad a cuota 2.10 creyendo que gana 55%:
        EV = 0.55 * 1.10 - 0.45 * 1 = +0.155  -> +15.5% por unidad.
     EV positivo = a la larga gana dinero SI la probabilidad del modelo es
     honesta. Esa última condición es la que valida backtest_valor.py.

Aviso importante que conviene tener presente: el mercado de UFC es eficiente.
El favorito del mercado gana ~65% de las veces y las líneas incorporan
lesiones, cortes de peso y dinero informado que el modelo no ve. Que el modelo
discrepe suele significar que el modelo está mal, no la casa. Por eso este
módulo no decide nada solo: el umbral de discrepancia lo fija el backtest
sobre peleas reales fuera de muestra.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import pickle

import numpy as np

import config as C
from src.odds import prob_bruta, prob_sin_vig, pago_por_unidad

CALIBRADOR = C.MODELS / "calibrador_mercado.pkl"


# --------------------------------------------------------------------------- #
# Entrada de cuotas: acepta formato americano y decimal (europeo)
# --------------------------------------------------------------------------- #
def a_americana(cuota) -> float:
    """
    Normaliza una cuota a formato AMERICANO, detectando el formato solo.

      * americano  : -150, +130   (|valor| >= 100)
      * decimal    : 1.67, 2.30   (1.01 <= valor <= 51)
      * fraccional : no soportado (nadie lo usa para MMA online)

    Se detecta por rango porque los dos formatos no se solapan: una cuota
    decimal nunca llega a 100 (sería un pago de 99 a 1) y una americana nunca
    baja de 100 en valor absoluto. Las casas chilenas y europeas dan decimal,
    las gringas americana; así el usuario copia y pega lo que tenga.
    """
    if cuota is None:
        return np.nan
    try:
        c = float(cuota)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(c):
        return np.nan
    if abs(c) >= 100:
        return c
    if 1.0 < c <= 51:
        # decimal -> americana
        return (c - 1.0) * 100.0 if c >= 2.0 else -100.0 / (c - 1.0)
    return np.nan


def a_decimal(cuota) -> float:
    """Cuota (en cualquier formato) -> decimal. 2.50 = pagan 2.5 por cada 1."""
    us = a_americana(cuota)
    if not np.isfinite(us):
        return np.nan
    return 1.0 + pago_por_unidad(us)


# --------------------------------------------------------------------------- #
# Métricas de una apuesta
# --------------------------------------------------------------------------- #
def ev_unidad(p: float, cuota) -> float:
    """
    Valor esperado por unidad apostada. +0.08 = ganas 8 centavos por peso a la
    larga. Negativo = donación a la casa.
    """
    us = a_americana(cuota)
    if not np.isfinite(us) or not np.isfinite(p):
        return np.nan
    b = pago_por_unidad(us)
    return p * b - (1.0 - p)


def kelly(p: float, cuota, fraccion: float = 0.25, tope: float = 0.05) -> float:
    """
    Fracción del bankroll a apostar según Kelly, recortada.

    Kelly puro (f = (p*b - q)/b) maximiza el crecimiento a largo plazo PERO
    asume que `p` es exacta. Con un modelo de 66% de acierto, `p` tiene error,
    y Kelly puro sobreapuesta brutalmente: una racha mala te funde. La práctica
    estándar es Kelly fraccionado (1/4) y además un tope duro por apuesta.

      fraccion=0.25 -> apuesta un cuarto de lo que diría Kelly
      tope=0.05     -> nunca más del 5% del bankroll en una sola pelea
    """
    us = a_americana(cuota)
    if not np.isfinite(us) or not np.isfinite(p):
        return 0.0
    b = pago_por_unidad(us)
    f = (p * b - (1.0 - p)) / b
    return float(np.clip(f * fraccion, 0.0, tope))


def vig(cuota_a, cuota_b) -> float:
    """Comisión de la casa en esta pelea. 0.05 = 5%. Sobre 7% es cara."""
    ua, ub = a_americana(cuota_a), a_americana(cuota_b)
    if not (np.isfinite(ua) and np.isfinite(ub)):
        return np.nan
    return prob_bruta(ua) + prob_bruta(ub) - 1.0


# --------------------------------------------------------------------------- #
# Calibrador: cómo combinar la opinión del modelo con la del mercado
# --------------------------------------------------------------------------- #
# POR QUÉ EXISTE ESTO (medido, no teórico — ver backtest_valor.py):
#
# Apostar la discrepancia CRUDA del modelo pierde -8% de ROI sobre 2.533
# apuestas reales. El motivo no es que el modelo no sirva, es que discrepa
# demasiado: acierta 60% contra el 67% del mercado, así que cuando se separa
# de la línea normalmente se está equivocando él.
#
# Pero al ajustar  y ~ logit(mercado) + logit(modelo)  sobre 4.700 peleas, el
# coeficiente del modelo sale +0.17 con t=3.1: el modelo SÍ aporta información
# que la línea no tiene. Solo que vale ~1/6 de lo que vale el mercado.
#
# El calibrador aplica exactamente ese peso. El resultado es una probabilidad
# que le gana al mercado en log-loss (0.6033 vs 0.6051) y que convierte el
# -8% de ROI en +1.6%. Las discrepancias que sobreviven son pocas y chicas,
# pero son las únicas que históricamente no perdieron plata.
def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoide(z):
    return 1.0 / (1.0 + np.exp(-z))


def ajustar_calibrador(p_mercado, p_modelo, y, guardar: bool = True) -> dict:
    """
    Ajusta los pesos de la mezcla mercado/modelo por regresión logística.

    IMPORTANTE: `p_modelo` tiene que venir de predicciones FUERA DE MUESTRA
    (las del walk-forward). Si se ajusta con predicciones del propio train, el
    modelo parece mucho mejor de lo que es y el calibrador le da un peso
    inflado que en vivo pierde dinero.
    """
    from sklearn.linear_model import LogisticRegression

    X = np.column_stack([_logit(p_mercado), _logit(p_modelo)])
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(X, np.asarray(y))
    cal = {"intercepto": float(lr.intercept_[0]),
           "peso_mercado": float(lr.coef_[0][0]),
           "peso_modelo": float(lr.coef_[0][1]),
           "n": int(len(y))}
    if guardar:
        C.MODELS.mkdir(parents=True, exist_ok=True)
        with open(CALIBRADOR, "wb") as fh:
            pickle.dump(cal, fh)
    return cal


def cargar_calibrador() -> dict | None:
    """Devuelve los pesos guardados, o None si nunca se corrió el backtest."""
    if not Path(CALIBRADOR).exists():
        return None
    try:
        with open(CALIBRADOR, "rb") as fh:
            return pickle.load(fh)
    except Exception:
        return None


def combinar(p_modelo: float, p_mercado: float, cal: dict | None = None) -> float:
    """
    Mezcla las dos opiniones con los pesos calibrados.

    Sin calibrador entrenado devuelve el modelo puro, y entonces las
    discrepancias que reporte NO están validadas (el backtest dice que esa
    versión pierde). Corre `python backtest_valor.py` para generarlo.
    """
    if cal is None:
        cal = cargar_calibrador()
    if cal is None:
        return float(p_modelo)
    z = (cal["intercepto"] + cal["peso_mercado"] * _logit(p_mercado)
         + cal["peso_modelo"] * _logit(p_modelo))
    return float(_sigmoide(z))


# --------------------------------------------------------------------------- #
# Análisis completo de una pelea
# --------------------------------------------------------------------------- #
@dataclass
class Valor:
    """Resultado de comparar modelo vs mercado en UNA pelea."""
    p_modelo_a: float          # prob. CRUDA del modelo de que gane A
    p_mercado_a: float         # prob. del mercado (sin vig) de que gane A
    p_final_a: float           # prob. CALIBRADA (la que se usa para decidir)
    discrepancia_cruda: float  # p_modelo_a - p_mercado_a   (con signo)
    discrepancia: float        # p_final_a  - p_mercado_a   (con signo)
    lado: str                  # "A", "B" o "" si no hay apuesta
    p_lado: float              # prob. calibrada del lado apostado
    cuota_lado: float          # cuota (americana) del lado apostado
    cuota_decimal: float       # la misma, en decimal (para leer rápido)
    ev: float                  # valor esperado por unidad de ese lado
    kelly: float               # fracción de bankroll sugerida
    vig: float                 # comisión de la casa
    veredicto: str             # texto corto para humanos

    def dict(self) -> dict:
        return asdict(self)


# Umbrales por defecto. NO son a ojo, pero tampoco son una garantía: salen del
# barrido de backtest_valor.py sobre 3.821 peleas fuera de muestra. La verdad
# incómoda que muestra ese barrido es que NINGÚN umbral es rentable de forma
# estadísticamente significativa; estos son simplemente los que no pierden.
# Se aplican sobre la probabilidad CALIBRADA, no sobre la cruda.
MIN_DISCREPANCIA = 0.02   # 2 puntos sobre la línea, ya calibrado
MIN_EV = 0.03             # +3% de valor esperado


def analizar(p_modelo_a: float, cuota_a, cuota_b,
             min_discrepancia: float = MIN_DISCREPANCIA,
             min_ev: float = MIN_EV, cal: dict | None = None) -> Valor:
    """
    Compara el modelo con el mercado y devuelve el diagnóstico de la pelea.

    OJO CON QUÉ DISCREPANCIA SE MIRA. Hay dos y no son lo mismo:

      discrepancia_cruda -> lo que separa al modelo de la línea. Es la que
          llama la atención (suele ser 10-25 puntos) y es la que NO hay que
          apostar: filtrando por ella el backtest pierde -8% de ROI.
      discrepancia -> lo que separa a la probabilidad CALIBRADA de la línea.
          Es chica (2-5 puntos) porque el calibrador ya le descontó al modelo
          su exceso de confianza. Es la única accionable.

    Se exigen las dos condiciones a la vez: desacuerdo mínimo Y que la cuota
    pague. En un pick parejo discrepar poco ya da EV; en un favoritazo la
    cuota paga tan poco que el mismo desacuerdo no alcanza.
    """
    ua, ub = a_americana(cuota_a), a_americana(cuota_b)
    if not (np.isfinite(ua) and np.isfinite(ub)):
        return Valor(p_modelo_a, np.nan, float(p_modelo_a), np.nan, np.nan, "",
                     np.nan, np.nan, np.nan, np.nan, 0.0, np.nan, "sin cuotas")

    pm_a, _ = prob_sin_vig(ua, ub)
    if cal is None:
        cal = cargar_calibrador()
    p_final = combinar(p_modelo_a, pm_a, cal)
    disc = p_final - pm_a

    # El lado candidato es aquel donde el modelo ve MÁS probabilidad que el
    # mercado. Solo hay un lado posible: si el modelo sobrevalora a A,
    # automáticamente infravalora a B.
    if disc >= 0:
        lado, p_lado, cuota, disc_lado = "A", p_final, ua, disc
    else:
        lado, p_lado, cuota, disc_lado = "B", 1.0 - p_final, ub, -disc

    ev = ev_unidad(p_lado, cuota)
    k = kelly(p_lado, cuota)

    if cal is None:
        veredicto = "SIN CALIBRAR (corre backtest_valor.py)"
    elif disc_lado >= min_discrepancia and ev >= min_ev:
        veredicto = "VALOR"
    elif disc_lado >= min_discrepancia:
        veredicto = "discrepa pero la cuota no paga"
    elif ev >= min_ev:
        veredicto = "algo de valor, desacuerdo chico"
    else:
        veredicto = "de acuerdo con el mercado"

    if veredicto != "VALOR":
        k = 0.0

    return Valor(
        p_modelo_a=float(p_modelo_a), p_mercado_a=float(pm_a),
        p_final_a=float(p_final),
        discrepancia_cruda=float(p_modelo_a - pm_a), discrepancia=float(disc),
        lado=lado if veredicto == "VALOR" else "",
        p_lado=float(p_lado), cuota_lado=float(cuota),
        cuota_decimal=float(a_decimal(cuota)), ev=float(ev), kelly=float(k),
        vig=float(vig(ua, ub)), veredicto=veredicto,
    )


# --------------------------------------------------------------------------- #
# Mercado de MÉTODO (6 vías: lado x KO/SUB/DEC)
# --------------------------------------------------------------------------- #
# Es un mercado distinto y con una grieta distinta. Resumen de backtest_metodo.py
# sobre 3.367 peleas fuera de muestra:
#
#   * Cobra 22% de comisión (el de ganador cobra 4%). Es un mercado recreativo.
#   * El público paga de más por las finalizaciones: el mercado le asigna 9.5%
#     a "B gana por sumisión" y ocurre el 6.8%. Apostar siempre a sumisiones
#     pierde -40% a -50%.
#   * Y al revés, INFRAVALORA las decisiones: les asigna 23.8% y ocurren 29.5%.
#     Apostar "decisión del favorito" a ciegas ya da +3.8% de ROI, sin modelo.
#   * Con el modelo filtrando, las decisiones con EV>=0 dieron +16.5% de ROI
#     (t=3.1) en el periodo con datos homogéneos.
#
# Esa es la única ventaja del proyecto que aguanta el test estadístico. Ver la
# advertencia sobre límites de apuesta en el veredicto de backtest_metodo.py.
CLASES_METODO = ["A_KO", "A_SUB", "A_DEC", "B_KO", "B_SUB", "B_DEC"]
CALIBRADOR_METODO = C.MODELS / "calibrador_metodo.pkl"
MODELO_METODO = C.MODELS / "metodo6_xgb.pkl"
MIN_SOBRERREDONDEO = 1.05   # guarda anti-datos-corruptos, ver backtest_metodo

# Banda de SOSPECHA (no de rechazo). Un mercado de método real cobra ~22% de
# comisión, así que sus 6 probabilidades implícitas suman 1,20-1,24. Entre 1,05
# y este umbral las cuotas no son literalmente imposibles, pero son más
# generosas que las de cualquier casa real: casi siempre significa que las
# cuotas del CSV están inventadas, tecleadas a ojo o mezcladas entre fuentes.
#
# Importa porque el EV se calcula con el PAGO de esas cuotas: si el pago está
# inflado, el EV sale inflado y la cartelera entera se llena de "valor" falso.
# Caso real que motivó esto: un CSV con cuotas de método puestas a mano sumaba
# 1,05-1,16 y generaba 9 apuestas de 9 peleas con EV de hasta +52%.
SOBRERREDONDEO_SOSPECHOSO = 1.18


def cargar_modelo_metodo():
    """(modelo, columnas) del clasificador de 6 clases, o (None, None)."""
    if not Path(MODELO_METODO).exists():
        return None, None
    try:
        with open(MODELO_METODO, "rb") as fh:
            d = pickle.load(fh)
        return d["modelo"], d["cols"]
    except Exception:
        return None, None


def cargar_calibrador_metodo() -> dict | None:
    if not Path(CALIBRADOR_METODO).exists():
        return None
    try:
        with open(CALIBRADOR_METODO, "rb") as fh:
            return pickle.load(fh)
    except Exception:
        return None


def mercado_metodo(cuotas6) -> tuple[np.ndarray, float]:
    """
    6 cuotas -> (probabilidades sin comisión, sobrerredondeo).

    El sobrerredondeo se devuelve para poder rechazar datos imposibles: si las
    6 probabilidades suman menos de ~1.05, esas cuotas no son de un mercado
    real (una casa no regala arbitraje) y hay que descartarlas.
    """
    us = np.array([a_americana(c) for c in cuotas6], dtype=float)
    if not np.isfinite(us).all():
        return np.full(6, np.nan), np.nan
    bruta = np.where(us < 0, -us / (-us + 100.0), 100.0 / (us + 100.0))
    s = float(bruta.sum())
    return bruta / s, s


def analizar_metodo(feat_df, cuotas6, min_ev: float = 0.0) -> list[dict]:
    """
    Devuelve las 6 opciones de una pelea ordenadas por valor esperado.

    `feat_df` es el DataFrame de una fila con las features de la pelea (el mismo
    que usa card.py para el ganador). Cada opción trae la probabilidad del
    modelo, la del mercado, la combinada, el EV y si califica como apuesta.
    """
    modelo, cols = cargar_modelo_metodo()
    cal = cargar_calibrador_metodo()
    q, sobre = mercado_metodo(cuotas6)
    if modelo is None or cal is None or not np.isfinite(sobre):
        return []
    if sobre < MIN_SOBRERREDONDEO:
        return [{"error": f"cuotas imposibles (suman {sobre:.3f})"}]

    p = modelo.predict_proba(feat_df[cols])[0]
    z = (cal["peso_mercado"] * np.log(np.clip(q, 1e-9, 1))
         + cal["peso_modelo"] * np.log(np.clip(p, 1e-9, 1)))
    z -= z.max()
    combo = np.exp(z)
    combo /= combo.sum()

    us = np.array([a_americana(c) for c in cuotas6], dtype=float)
    pago = np.where(us < 0, 100.0 / -us, us / 100.0)
    ev = combo * pago - (1 - combo)

    # Cuotas más generosas que las de una casa real -> el EV que salga de ellas
    # no es valor, es el síntoma de un dato malo (ver SOBRERREDONDEO_SOSPECHOSO).
    sospechoso = sobre < SOBRERREDONDEO_SOSPECHOSO

    out = []
    for i, c in enumerate(CLASES_METODO):
        out.append({
            "clase": c, "p_modelo": float(p[i]), "p_mercado": float(q[i]),
            "p_final": float(combo[i]), "cuota_decimal": float(1 + pago[i]),
            "ev": float(ev[i]), "kelly": kelly(float(combo[i]), us[i]),
            # Una cuota sospechosa NO se convierte en apuesta: el EV está
            # construido sobre un pago que ninguna casa ofrece.
            "apostar": bool(ev[i] >= min_ev and not sospechoso),
            "sobrerredondeo": sobre, "sospechoso": sospechoso,
        })
    return sorted(out, key=lambda r: -r["ev"])


# --------------------------------------------------------------------------- #
# Versión vectorizada (para el backtest, que corre sobre miles de peleas)
# --------------------------------------------------------------------------- #
def analizar_lote(p_modelo_a: np.ndarray, cuota_a: np.ndarray,
                  cuota_b: np.ndarray) -> dict[str, np.ndarray]:
    """
    Igual que analizar() pero sobre arrays. Devuelve un dict de arrays con
    p_mercado_a, discrepancia (con signo), y para el lado candidato:
    apuesta_a (bool), p_lado, cuota_lado, ev.
    """
    ua = np.array([a_americana(c) for c in cuota_a], dtype=float)
    ub = np.array([a_americana(c) for c in cuota_b], dtype=float)
    p = np.asarray(p_modelo_a, dtype=float)

    # np.where evalúa las DOS ramas, así que la rama muerta puede dividir por
    # cero (cuota -100 => ua+100 = 0). Se silencia: el resultado se descarta.
    with np.errstate(divide="ignore", invalid="ignore"):
        bruta_a = np.where(ua < 0, -ua / (-ua + 100.0), 100.0 / (ua + 100.0))
        bruta_b = np.where(ub < 0, -ub / (-ub + 100.0), 100.0 / (ub + 100.0))
    s = bruta_a + bruta_b
    pm_a = np.where(s > 0, bruta_a / s, 0.5)

    disc = p - pm_a
    apuesta_a = disc >= 0
    p_lado = np.where(apuesta_a, p, 1.0 - p)
    cuota_lado = np.where(apuesta_a, ua, ub)
    pago = np.where(cuota_lado < 0, 100.0 / -cuota_lado, cuota_lado / 100.0)
    ev = p_lado * pago - (1.0 - p_lado)

    return {"p_mercado_a": pm_a, "discrepancia": disc, "apuesta_a": apuesta_a,
            "p_lado": p_lado, "cuota_lado": cuota_lado, "pago": pago, "ev": ev,
            "disc_lado": np.abs(disc)}
