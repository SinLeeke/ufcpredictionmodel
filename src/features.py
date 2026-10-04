"""
features.py
FASE 2 — Ingeniería de características diferencial.

En un deporte 1v1 el modelo NO debe ver stats absolutos, sino la DIFERENCIA
directa entre el peleador A y el B  ->  X_diff = X_A - X_B.
Dos consecuencias de diseño importantes:

  1) ANTISIMETRÍA. Si intercambias A<->B, cada feature diferencial debe cambiar
     de signo y la etiqueta pasar de 1 a 0. Aprovechamos esto para AUMENTAR el
     dataset: cada pelea genera 2 filas (A vs B, y = 1) y (B vs A, y = 0).
     Esto obliga al modelo a aprender una frontera antisimétrica y elimina el
     sesgo de "esquina roja gana más".

  2) NADA DE MIRAR EL FUTURO. El ELO y las rachas deben calcularse SOLO con
     peleas anteriores a la fecha del combate (se resuelve en model.py con el
     split temporal, pero el ELO ya se actualiza cronológicamente aquí).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C
from src import storage as DB


# --------------------------------------------------------------------------- #
# Sistema ELO dinámico por categoría de peso
# --------------------------------------------------------------------------- #
class EloSystem:
    """
    ELO clásico con dos ajustes propios del MMA:
      * rating independiente por categoría de peso,
      * bonus de K cuando la victoria es por finalización (una finalización es
        una señal más fuerte de superioridad que una decisión dividida).
    """

    def __init__(self, base=C.ELO_BASE, k=C.ELO_K, finish_bonus=C.ELO_FINISH_BONUS):
        self.base = base
        self.k = k
        self.finish_bonus = finish_bonus
        # {weight_class: {fighter: rating}}
        self.ratings: dict[str, dict[str, float]] = {}

    def get(self, fighter: str, weight_class: str) -> float:
        wc = self.ratings.setdefault(weight_class, {})
        return wc.setdefault(fighter, self.base)

    @staticmethod
    def _expected(r_a: float, r_b: float) -> float:
        """Probabilidad esperada de que A gane según ELO."""
        return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))

    def update(self, winner: str, loser: str, weight_class: str, by_finish: bool,
               valor: float | None = None):
        """
        Actualiza los ratings tras una pelea. Llamar en orden cronológico.

        `valor` es el "score" del ganador en la escala de ELO (1.0 = victoria
        total, 0.5 = empate). Si va None se usa 1.0 y el bonus clásico de K por
        finalización. Con VALOR_POR_RESULTADO se le pasa una nota graduada según
        CÓMO ganó: ganar por decisión dividida no demuestra lo mismo que un KO.
        """
        r_w = self.get(winner, weight_class)
        r_l = self.get(loser, weight_class)
        exp_w = self._expected(r_w, r_l)
        if valor is None:
            k = self.k * (self.finish_bonus if by_finish else 1.0)
            s = 1.0
        else:
            k, s = self.k, float(valor)
        delta = k * (s - exp_w)            # el ganador esperaba exp_w, obtuvo s
        self.ratings[weight_class][winner] = r_w + delta
        self.ratings[weight_class][loser] = r_l - delta

    def to_frame(self) -> pd.DataFrame:
        rows = [(wc, f, r) for wc, d in self.ratings.items() for f, r in d.items()]
        return pd.DataFrame(rows, columns=["weight_class", "fighter", "elo"])


def build_elo_table(fights: pd.DataFrame) -> tuple[EloSystem, pd.DataFrame]:
    """
    Recorre TODAS las peleas en orden cronológico y construye el ELO final.
    'fights' debe tener columnas: date, winner, loser, weight_class, by_finish (bool).
    Devuelve el sistema (para consultar) y un DataFrame de ratings finales.
    """
    elo = EloSystem()
    fights_sorted = fights.sort_values("date")
    for _, row in fights_sorted.iterrows():
        elo.update(row["winner"], row["loser"], row["weight_class"], bool(row["by_finish"]))
    table = elo.to_frame()
    DB.to_csv(table, C.ELO_TABLE, index=False)
    return elo, table


# --------------------------------------------------------------------------- #
# Biometría faltante (train/serve skew)
# --------------------------------------------------------------------------- #
# UFCStats deja la ficha en 0 cuando no conoce el dato: `_reach_cm("")` -> 0.0.
# Al restar, un peleador sin alcance producía reach_diff = -190 cm, un valor que
# el modelo JAMÁS vio entrenando (el dataset de Kaggle viene completo: rango real
# -33 a +33 en altura, -17 a +17 en edad).
#
# El daño no era cosmético: en la cartelera de Ankalaev, "alcance +182.9" salió
# como 2º factor del pick de Aliev sobre Davis según SHAP.
#
# DOS ADVERTENCIAS PARA EL QUE VENGA A TOCAR ESTO:
#
# 1. "El 44% de las fichas no trae alcance" es un dato REAL pero ENGAÑOSO: de
#    esos 2.003 peleadores, solo 3 han peleado desde 2024. Son fichas viejas que
#    casi nunca entran en una cartelera. El caso que de verdad dolía no era este,
#    era un homónimo mal resuelto (ver find_fighter_url en ufcstats.py).
#
# 2. La tentación es "usar NaN porque XGBoost lo maneja". NO: el entrenamiento
#    no tiene ni un NaN en estas columnas, así que el modelo nunca aprendió una
#    dirección para ellos y los mandaría por la rama por defecto, que es
#    arbitraria. Se midieron las dos variantes contra backtest_carteleras y
#    dieron idéntico (26/37 y 64/95), así que se eligió "neutro" por ser el
#    valor que el modelo sí conoce: reach_diff=0 aparece en 1.780 filas de
#    entrenamiento. Ese backtest NO puede resolver diferencias chicas — cambiar
#    solo la semilla del modelo lo mueve entre 62 y 66 de 95.
MODO_BIO_FALTANTE = "neutro"     # "neutro" = diferencia 0 | "nan" = deja NaN


def _bio_valido(v) -> float | None:
    """Valor biométrico, o None si la ficha no lo traía (UFCStats pone 0)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) and x > 0 else None


def _diff_bio(va, vb) -> float:
    """
    Diferencia A-B que NO inventa datos.

    Si a cualquiera de los dos le falta el valor, no hay diferencia que medir.
    Con "neutro" se devuelve 0, que el modelo lee como "ninguno saca ventaja"
    y es un valor abundante en el entrenamiento (1.780 filas tienen reach_diff
    exactamente 0), así que cae en territorio conocido.
    """
    x, y = _bio_valido(va), _bio_valido(vb)
    if x is None or y is None:
        return np.nan if MODO_BIO_FALTANTE == "nan" else 0.0
    return x - y


# --------------------------------------------------------------------------- #
# Features diferenciales entre dos peleadores
# --------------------------------------------------------------------------- #
def differential_features(a: dict, b: dict,
                          elo_a: float = C.ELO_BASE,
                          elo_b: float = C.ELO_BASE) -> dict:
    """
    Recibe dos dicts de stats (formato Fighter) y devuelve el vector diferencial
    A - B que consume el modelo. Todas las variables son ANTISIMÉTRICAS.
    """
    f = {}

    # --- Diferencial físico y momentum ---
    # Biometría: ver _diff_bio. Un 0 en la ficha significa "no lo sé", no "mide 0".
    f["age_diff"] = _diff_bio(a["age"], b["age"])
    f["reach_diff"] = _diff_bio(a["reach_cm"], b["reach_cm"])
    f["height_diff"] = _diff_bio(a["height_cm"], b["height_cm"])
    f["streak_diff"] = a["streak"] - b["streak"]
    f["days_since_last_fight_diff"] = a["days_since_last_fight"] - b["days_since_last_fight"]
    f["elo_diff"] = elo_a - elo_b

    # --- Matchup estilístico: ataque de A vs defensa de B, y viceversa ---
    # Golpeo efectivo de A = su volumen conectado (SLpM*Acc) DAMPEADO por la defensa de B:
    # la fracción que atraviesa la guardia de B es (1 - Str.Def_B).
    # (Antes usaba SApM_B, pero en los datasets SApM no está por-minuto de forma fiable;
    #  Str.Def sí es un ratio 0-1 consistente entre UFCStats y el entrenamiento -> sin sesgo.)
    striking_a = a["slpm"] * a["str_acc"] * (1.0 - b["str_def"])
    striking_b = b["slpm"] * b["str_acc"] * (1.0 - a["str_def"])
    f["striking_efficiency_diff"] = striking_a - striking_b

    # Grappling efectivo esperado de A = derribos que logra A  -  defensa de derribo de B
    grappling_a = (a["td_avg"] * a["td_acc"]) - b["td_def"]
    grappling_b = (b["td_avg"] * b["td_acc"]) - a["td_def"]
    f["grappling_efficiency_diff"] = grappling_a - grappling_b

    # Amenaza de sumisión neta
    f["sub_threat_diff"] = a["sub_avg"] - b["sub_avg"]

    # --- Índice de finalización vs vulnerabilidad (cruce histórico) ---
    # Prob. "estilística" de que A finalice a B = tasa de finalización de A * tasa de
    # B de ser finalizado. Se compara contra el cruce inverso.
    a_finishes_b = (a["win_ko_rate"] + a["win_sub_rate"]) * b["lost_by_finish_rate"]
    b_finishes_a = (b["win_ko_rate"] + b["win_sub_rate"]) * a["lost_by_finish_rate"]
    f["finish_index_diff"] = a_finishes_b - b_finishes_a

    # Guardamos también un "índice de que la pelea NO llegue a tarjetas", útil para
    # el modelo de método y para la simulación (no es diferencial: es propiedad del duelo).
    f["fight_finish_potential"] = round((a_finishes_b + b_finishes_a) / 2.0, 4)

    # --- Stance matchup (orthodox vs southpaw suele favorecer al zurdo) ---
    f["stance_southpaw_edge"] = int(a["stance"] == "Southpaw") - int(b["stance"] == "Southpaw")

    return f


def make_training_matrix(fights: pd.DataFrame, fighters: pd.DataFrame,
                         elo: EloSystem | None = None) -> pd.DataFrame:
    """
    Construye el dataset diferencial de ENTRENAMIENTO con aumento antisimétrico.

    'fights' : columnas date, fighter_a, fighter_b, winner, weight_class, method
    'fighters': tabla 1-fila-por-peleador (salida de scraper.build_fighters_table)

    Devuelve X + columnas 'date', 'y' (1 si gana A) y 'method' para el modelo de método.
    """
    fmap = fighters.set_index("name").to_dict("index")
    rows = []
    for _, fight in fights.iterrows():
        a, b = fight["fighter_a"], fight["fighter_b"]
        if a not in fmap or b not in fmap:
            continue
        wc = fight["weight_class"]
        elo_a = elo.get(a, wc) if elo else C.ELO_BASE
        elo_b = elo.get(b, wc) if elo else C.ELO_BASE

        y = 1 if fight["winner"] == a else 0
        method = _normalize_method(fight.get("method", "Decision"))

        # Fila directa A vs B
        base = differential_features(fmap[a], fmap[b], elo_a, elo_b)
        rows.append({**base, "date": fight["date"], "y": y, "method": method})

        # Fila espejo B vs A (antisimetría) -> negamos features diferenciales, y = 1-y
        mirror = differential_features(fmap[b], fmap[a], elo_b, elo_a)
        rows.append({**mirror, "date": fight["date"], "y": 1 - y, "method": method})

    df = pd.DataFrame(rows)
    DB.to_csv(df, C.FEATURES_CSV, index=False)
    print(f"[ok] matriz de features: {df.shape[0]} filas -> {C.FEATURES_CSV}")
    return df


def _normalize_method(raw: str) -> str:
    """Colapsa el texto libre de método a las 3 clases de config.METHOD_CLASSES."""
    r = str(raw).lower()
    if "sub" in r:
        return "Submission"
    if "ko" in r or "tko" in r or "knockout" in r:
        return "KO/TKO"
    return "Decision"


# --------------------------------------------------------------------------- #
# Valor graduado de la victoria para el ELO
# --------------------------------------------------------------------------- #
# Idea tomada de FightMatrix, que ajustó un Glicko sobre las peleas 2010-2019 y
# encontró que el ELO clásico exagera lo que demuestra una victoria por tarjetas:
# una DECISIÓN DIVIDIDA es casi un empate (los jueces no se pusieron de acuerdo),
# y una unánime tampoco es lo mismo que un KO.
#
# En vez del "bonus de K por finalización" que usaba este proyecto, se le pasa al
# ELO una NOTA distinta según cómo ganó. Es más fino: el bonus de K acelera el
# ajuste sin cambiar hacia dónde va, mientras que la nota cambia el destino.
#
# Fuente: https://www.fightmatrix.com/2019/09/18/tuning-glicko-what-i-learned-confirmed/
VALOR_POR_RESULTADO = {
    "S-DEC": 0.55,     # decisión dividida  -> apenas por encima del empate
    "M-DEC": 0.61,     # decisión mayoritaria
    "U-DEC": 0.91,     # decisión unánime
    "KO/TKO": 1.00,
    "SUB": 1.00,
}


def valor_resultado(raw: str) -> float | None:
    """
    Nota del ganador (escala ELO) según el texto crudo de método del dataset.
    Devuelve None si no se reconoce -> el llamador cae al comportamiento clásico.

    Ojo: necesita el texto FINO ('S-DEC', 'U-DEC'), no el normalizado a 3 clases.
    La columna `finish` de mdabbert lo trae; el scraper propio de UFCStats lo
    aplasta a 'Decision' (ver ufcstats_events._norm_method), así que ahí no
    hay con qué graduar.
    """
    r = str(raw).strip().upper()
    if r in VALOR_POR_RESULTADO:
        return VALOR_POR_RESULTADO[r]
    if "SUB" in r:
        return 1.00
    if "KO" in r or "TKO" in r:
        return 1.00
    # Una decisión sin especificar tipo: se asume unánime, que es el 78% de ellas.
    if "DEC" in r:
        return VALOR_POR_RESULTADO["U-DEC"]
    return None


FEATURE_COLUMNS = [
    "age_diff", "reach_diff", "height_diff", "streak_diff",
    "days_since_last_fight_diff", "elo_diff",
    "striking_efficiency_diff", "grappling_efficiency_diff", "sub_threat_diff",
    "finish_index_diff", "fight_finish_potential", "stance_southpaw_edge",
]

# Features extra que solo existen con el dataset propio de UFCStats
# (ufcstats_ingest.py). Miden CONTROL y poder, que es lo que el dataset de
# Kaggle no permitía ver y hacía que el modelo subestimara a los luchadores.
FEATURE_COLUMNS_UFCSTATS = FEATURE_COLUMNS + [
    "ctrl_diff",            # tiempo de control por minuto (A - B)
    "ctrl_vs_def_diff",     # control propio vs. control que concede el rival
    "ground_share_diff",    # % de golpes desde el suelo
    "kd_rate_diff",         # knockdowns por 15 min
]


# Calidad de la oposición reciente (src/oposicion.py): contra QUIÉN peleó en sus
# últimas 5 y cómo le fue. Solo las usa el modelo de GANADOR — ver más abajo.
FEATURE_COLUMNS_OPOSICION = [
    "opp_elo_diff",        # ELO promedio de los rivales recientes
    "opp_elo_max_diff",    # el mejor rival al que le GANÓ (techo demostrado)
    "ko_infl_diff",        # victorias recientes por KO/TKO
    "sub_infl_diff",       # victorias recientes por sumisión
    "ko_recibido_diff",    # veces que LO finalizaron (durabilidad / declive)
    "momentum_diff",       # resultados ponderados por calidad del rival y antigüedad
]


# Corto aviso (src/reemplazos.py): +1 si SOLO A entró de reemplazo, -1 si solo B.
# Un reemplazo no hizo campamento completo; medido sobre nuestras carteleras
# gana apenas el 34,9%. Va aparte de las de oposición para poder mostrar la
# predicción CON y SIN este dato (las tablas 1 y 3 del reporte).
FEATURE_COLUMNS_CORTO = ["reemplazo_diff"]


def columnas_disponibles(df, con_mercado: bool = False,
                         con_oposicion: bool = True,
                         con_corto: bool = True) -> list[str]:
    """
    Usa las features ampliadas si el dataset las trae; si no, las básicas.
    con_mercado=True añade la cuota del mercado (para el modelo con cuotas).

    con_oposicion=False deja fuera la calidad de oposición. Lo usa el modelo de
    MÉTODO, y no es capricho: medido sobre 5 semillas, esas features le suben el
    log loss apenas (-0,0022) pero le EMPEORAN la discriminación KO-vs-sumisión
    (AUC 0,752 -> 0,749). Tiene sentido: cómo termina una pelea depende del
    estilo de los dos peleadores, que el modelo ya ve en sus propias tasas de
    finalización; contra quién pelearon antes no agrega nada.
    Al modelo de GANADOR, en cambio, sí le sirven (AUC 0,704 -> 0,714 y Brier
    0,2216 -> 0,2165, mejor en las 5 semillas).
    """
    cols = ([c for c in FEATURE_COLUMNS_UFCSTATS if c in df.columns]
            if "ctrl_diff" in df.columns else list(FEATURE_COLUMNS))
    if con_oposicion:
        cols = cols + [c for c in FEATURE_COLUMNS_OPOSICION if c in df.columns]
    if con_corto:
        cols = cols + [c for c in FEATURE_COLUMNS_CORTO if c in df.columns]
    if con_mercado and "market_edge" in df.columns:
        cols = cols + ["market_edge"]
    return cols


# --------------------------------------------------------------------------- #
# Simetría A/B (importa para el modelo de MÉTODO)
# --------------------------------------------------------------------------- #
# Todas las features son ANTISIMÉTRICAS (X_A - X_B): al intercambiar A y B
# cambian de signo. La única excepción es 'fight_finish_potential', que es el
# PROMEDIO de los dos cruces de finalización y por lo tanto no cambia.
#
# Para el modelo de GANADOR eso es exactamente lo que se quiere (la etiqueta
# también se invierte). Pero el MÉTODO de una pelea es el mismo se mire desde
# donde se mire: "termina por KO" no depende de a quién pusiste en la columna A.
# El modelo no lo sabe, así que daba respuestas distintas para la misma pelea
# según el orden (medido: en 25,8% de las peleas del test cambiaba el método
# predicho con solo dar vuelta el CSV). `probabilidades_metodo()` lo arregla
# promediando la predicción con la de la pelea espejo.
COLUMNAS_SIMETRICAS = {"fight_finish_potential"}


def espejo(X: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    """La misma pelea con A y B intercambiados: niega las features antisimétricas."""
    cols = cols or list(X.columns)
    Xm = X.copy()
    for c in cols:
        if c not in COLUMNAS_SIMETRICAS:
            Xm[c] = -Xm[c]
    return Xm


def probabilidad_ganador(model, X: pd.DataFrame, cols: list[str] | None = None):
    """
    P(gana A) INVARIANTE al orden de los peleadores: promedia la predicción de
    la pelea con 1 - la de su espejo.

    XGBoost entrena con las dos orientaciones pero no sale perfectamente
    antisimétrico. Antes se predecía en una sola, y medido en 25 peleas reales
    dar vuelta el CSV movía la p del modelo 3,8 pts de media (máx 8,7) y
    cambiaba el pick en 2. Además los dos calibradores se ajustan con esta p
    simetrizada (backtest_valor), así que predecir en una orientación les
    pasaba una entrada distinta a la que conocían.

    Medido en walk-forward 2021-2026 (6 años, ventana de 5): log loss mejor que
    la orientación del dataset en 5/6 (-0,0014) y AUC en 4/6 (+0,0018);
    empata con la orientación invertida (4/6, -0,0001).
    """
    cols = cols or list(X.columns)
    p = model.predict_proba(X[cols])[:, 1]
    p_esp = model.predict_proba(espejo(X[cols], cols))[:, 1]
    return (p + (1.0 - p_esp)) / 2.0


def probabilidades_metodo(model, X: pd.DataFrame, cols: list[str] | None = None):
    """
    Probabilidades de método (KO/TKO, Submission, Decision) INVARIANTES al orden
    de los peleadores: promedia la predicción de la pelea y la de su espejo.

    Además de ser lo correcto conceptualmente, mide (test 2025+) un pelo mejor
    que la predicción cruda: log loss 0,9504 vs 0,9507.
    """
    cols = cols or list(X.columns)
    p = model.predict_proba(X[cols])
    p_esp = model.predict_proba(espejo(X[cols], cols))
    return (p + p_esp) / 2.0
