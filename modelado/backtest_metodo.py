"""
modelado/backtest_metodo.py
El mercado de MÉTODO (¿gana quién, y cómo?) contra el modelo.

POR QUÉ ESTE MERCADO Y NO EL DE GANADOR
---------------------------------------
El de ganador está muy vigilado: la casa cobra 4% y acierta 67%. Ahí no hay
grieta (lo midió backtest_valor.py: la mejor estrategia queda en empate).

El de método es otra cosa. Son 6 opciones — {peleador A, peleador B} x {KO,
sumisión, decisión} — y tiene dos propiedades opuestas:

  * EN CONTRA: la comisión es del 20%, cinco veces la del moneyline. Ese es el
    peaje que hay que superar y es enorme.
  * A FAVOR: el público paga de más por las finalizaciones. Medido sobre 5.470
    peleas, el mercado le asigna 9.3% a "B gana por sumisión" y ocurre el 6.8%;
    le asigna 24.5% a "A gana por decisión" y ocurre el 28.7%. Es el "sesgo del
    apostador": nadie va a la casa a apostar que la pelea será aburrida.

La pregunta de este script es si el segundo efecto alcanza para pagar el
primero. La respuesta la da el ROI, no la intuición.

MÉTODO
------
Idéntico a backtest_valor.py: walk-forward, un modelo por año entrenado solo
con el pasado. El modelo es de 6 clases (lado x método) en vez de 2, para poder
comparar contra las 6 cuotas. Se mezcla con el mercado por "log-opinion pool"
(el equivalente multiclase del calibrador del otro backtest).

Uso:
    python -m modelado.backtest_metodo
    python -m modelado.backtest_metodo --refit      # recalcula (tarda ~3 min)
"""
from __future__ import annotations

import argparse
import pickle

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from xgboost import XGBClassifier

import config as C
from src.features import columnas_disponibles

CACHE = C.DATA_PROCESSED / "walkforward_metodo.csv"
CALIBRADOR = C.MODELS / "calibrador_metodo.pkl"
MODELO6 = C.MODELS / "metodo6_xgb.pkl"     # el que usa card.py en vivo
PRIMER_ANIO = 2016

# Las 6 salidas posibles de una pelea, en orden fijo.
CLASES = ["A_KO", "A_SUB", "A_DEC", "B_KO", "B_SUB", "B_DEC"]
COL_ODDS = ["odds_a_ko", "odds_a_sub", "odds_a_dec",
            "odds_b_ko", "odds_b_sub", "odds_b_dec"]
# permutación que intercambia los lados (para promediar las dos orientaciones)
ESPEJO = [3, 4, 5, 0, 1, 2]
IDX_METODO = {"KO/TKO": 0, "Submission": 1, "Decision": 2}


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #
def cargar() -> pd.DataFrame:
    df = pd.read_csv(C.FEATURES_CSV)
    df["date"] = pd.to_datetime(df["date"])
    if "odds_a_ko" not in df.columns:
        raise SystemExit(
            "features.csv no trae las cuotas de método.\n"
            "Regenera el dataset:  python -m src.kaggle_ingest"
        )
    # etiqueta de 6 clases: lado ganador x método
    idx = df["method"].map(IDX_METODO)
    df = df[idx.notna()].copy()
    df["y6"] = np.where(df["y"] == 1, 0, 3) + idx[idx.notna()].astype(int)
    return df


def sobrerredondeo(d: pd.DataFrame) -> np.ndarray:
    """
    Suma de las 6 probabilidades implícitas SIN normalizar.

    En un mercado real esto siempre pasa de 1: el exceso es la comisión. Es la
    prueba de sanidad más barata que existe sobre datos de cuotas.
    """
    P = []
    for c in COL_ODDS:
        v = d[c].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            P.append(np.where(v < 0, -v / (-v + 100.0), 100.0 / (v + 100.0)))
    return np.column_stack(P).sum(axis=1)


# Mínimo de comisión creíble para aceptar una fila. Los años sanos de este
# dataset están en 1.20-1.24; las filas descartadas están en 0.94-1.01.
#
# POR QUÉ EXISTE ESTA GUARDA (y no se saca): las cuotas de método de mdabbert
# desde 2025 están en otra base — suman 1.005 y 0.940, o sea una casa regalando
# arbitraje. Con esas filas dentro, este backtest daba +63% de ROI y hasta
# +183% en finalizaciones. Apostar a las 6 opciones de cada pelea de 2025 daba
# +26%, lo cual es imposible por definición y delata el dato, no la estrategia.
# El moneyline (odds_a/odds_b) NO tiene el problema: su vig es 2-4.5% todos los
# años y apostar a los dos lados siempre pierde. Solo el mercado de método.
MIN_SOBRERREDONDEO = 1.05


def prob_mercado(d: pd.DataFrame) -> np.ndarray:
    """
    Las 6 cuotas -> 6 probabilidades que suman 1 (quitando el 20% de comisión).

    Se normaliza proporcionalmente. Es la forma estándar y la que se usó para
    medir el sesgo; métodos más finos (Shin, potencia) cambian poco cuando el
    margen se reparte parejo entre opciones.
    """
    P = []
    for c in COL_ODDS:
        v = d[c].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            P.append(np.where(v < 0, -v / (-v + 100.0), 100.0 / (v + 100.0)))
    P = np.column_stack(P)
    s = P.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        Q = P / s
    return Q


def pagos(d: pd.DataFrame) -> np.ndarray:
    """Ganancia neta por unidad de cada una de las 6 opciones."""
    out = []
    for c in COL_ODDS:
        v = d[c].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            out.append(np.where(v < 0, 100.0 / -v, v / 100.0))
    return np.column_stack(out)


# --------------------------------------------------------------------------- #
# Modelo de 6 clases, walk-forward
# --------------------------------------------------------------------------- #
def _modelo():
    return XGBClassifier(
        objective="multi:softprob", num_class=6,
        n_estimators=300, max_depth=3, learning_rate=0.04,
        subsample=0.85, colsample_bytree=0.85,
        eval_metric="mlogloss", random_state=C.RANDOM_STATE,
    )


def predicciones_walk_forward(df: pd.DataFrame, primer_anio: int) -> pd.DataFrame:
    """1 fila por pelea con las 6 probabilidades que el modelo daba ex-ante."""
    # Sin market_edge (igual que el otro) y sin las features de oposición:
    # medido, al método le empeoran el KO-vs-sumisión (ver columnas_disponibles).
    cols = columnas_disponibles(df, con_oposicion=False)
    df = df.reset_index(drop=True)
    salida = []
    for anio in sorted(a for a in df["date"].dt.year.unique() if a >= primer_anio):
        # TODO el historial, a propósito (ver entrenar_modelo6): con la ventana
        # de 5 años el log loss del modelo mejora, pero el ROI de las decisiones
        # se cae, y en este mercado la métrica que importa es el ROI.
        train = df[df["date"].dt.year < anio]
        test = df[df["date"].dt.year == anio]
        if len(train) < 500 or test.empty:
            continue
        m = _modelo()
        # Sin balancear: la frecuencia base SÍ importa, porque se compara contra
        # un mercado que también cotiza probabilidades absolutas. (method_xgb.pkl
        # tampoco se balancea ya: balancearlo destruía la calibración y lo dejaba
        # peor que cantar las tasas base — ver train_model.train_method.)
        m.fit(train[cols], train["y6"])
        P = m.predict_proba(test[cols])

        directa = test.iloc[::2].copy()
        P_dir, P_esp = P[::2], P[1::2][:, ESPEJO]
        P_media = (P_dir + P_esp) / 2.0
        P_media /= P_media.sum(axis=1, keepdims=True)
        for i, c in enumerate(CLASES):
            directa[f"p_{c}"] = P_media[:, i]
        directa["anio"] = anio
        salida.append(directa)
        print(f"  {anio}: entrena {len(train):>6} filas -> predice {len(directa):>4} peleas")
    if not salida:
        raise SystemExit("No hubo años con suficiente historial.")
    return pd.concat(salida, ignore_index=True)


def entrenar_modelo6(full: pd.DataFrame):
    """
    (modelo, columnas, filas) del modelo de 6 clases que usa card.py.

    Entrena con TODO el historial, no con la ventana de 5 años del modelo de
    ganador, Y ESO ESTÁ MEDIDO — no "arreglarlo" sin leer esto:

    La ventana parecía obvia: el dataset de Kaggle cambió de escala en 2019
    (golpes por pelea hasta 2018, por minuto desde 2020) y con 5 años el log
    loss del modelo de 6 clases mejora en 5/6 años (2021-2026, -0,0144). Se
    implementó y se midió el ROI de lo que de verdad se apuesta, con los
    mismos datos: decisiones con EV >= 0 en 2018-2024,
        todo el historial  1.145 apuestas  +15,4%  t=3,0  (7/7 años positivos)
        ventana 5 años     1.049 apuestas   +7,0%  t=1,3  (5/7)
    y año a año el historial completo gana en 8 de 9. Mejor log loss no es
    mejor apuesta: en este mercado manda el ROI, así que se revirtió.
    """
    cols = columnas_disponibles(full, con_oposicion=False)
    return _modelo().fit(full[cols], full["y6"]), cols, len(full)


# --------------------------------------------------------------------------- #
# Mezcla modelo + mercado (log-opinion pool)
# --------------------------------------------------------------------------- #
def ajustar_pool(Q: np.ndarray, P: np.ndarray, y6: np.ndarray) -> dict:
    """
    Busca los pesos de  combo ∝ mercado^w_mkt * modelo^w_mod.

    Es la versión multiclase del calibrador de backtest_valor.py: allá se
    mezclaban dos logits, acá se mezclan dos vectores de log-probabilidad y se
    renormaliza. Dos parámetros nada más, así que no hay riesgo de sobreajuste.
    """
    lq, lp = np.log(np.clip(Q, 1e-9, 1)), np.log(np.clip(P, 1e-9, 1))
    n = len(y6)

    def perdida(w):
        z = w[0] * lq + w[1] * lp
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return -np.mean(np.log(e[np.arange(n), y6] / e.sum(axis=1)))

    r = minimize(perdida, x0=np.array([1.0, 0.3]), method="Nelder-Mead")
    return {"peso_mercado": float(r.x[0]), "peso_modelo": float(r.x[1]),
            "n": int(n)}


def aplicar_pool(Q: np.ndarray, P: np.ndarray, cal: dict) -> np.ndarray:
    z = (cal["peso_mercado"] * np.log(np.clip(Q, 1e-9, 1))
         + cal["peso_modelo"] * np.log(np.clip(P, 1e-9, 1)))
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


# --------------------------------------------------------------------------- #
# Simulación de apuestas
# --------------------------------------------------------------------------- #
def apostar(prob: np.ndarray, pago: np.ndarray, y6: np.ndarray,
            min_ev: float, clases=None) -> dict:
    """
    Apuesta 1 unidad a cada una de las 6 opciones cuyo EV supere el umbral.
    `clases` restringe a ciertas columnas (p.ej. solo decisiones).
    """
    ev = prob * pago - (1 - prob)
    sel = np.isfinite(ev) & (ev >= min_ev)
    if clases is not None:
        m = np.zeros(6, bool)
        m[list(clases)] = True
        sel &= m[None, :]
    n = int(sel.sum())
    if n == 0:
        return {"n": 0}
    gano = (np.arange(6)[None, :] == y6[:, None])
    ret = np.where(gano, pago, -1.0)[sel]
    acerto = gano[sel]
    ee = ret.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {"n": n, "acierto": float(acerto.mean()), "roi": float(ret.mean()),
            "profit": float(ret.sum()), "ee": float(ee),
            "t": float(ret.mean() / ee) if ee and ee > 0 else np.nan,
            "cuota": float((1 + pago[sel]).mean())}


def _linea(etq: str, r: dict) -> str:
    if not r.get("n"):
        return f"  {etq:26}{'—':>8}{'sin apuestas':>34}"
    return (f"  {etq:26}{r['n']:>8}{r['acierto']*100:>9.1f}%"
            f"{r['roi']*100:>+10.1f}%{r['profit']:>+10.1f}u{r['cuota']:>8.2f}"
            f"{r['t']:>7.1f}")


CAB = (f"  {'estrategia':26}{'apuestas':>8}{'acierto':>10}{'ROI':>11}"
       f"{'ganancia':>11}{'cuota':>8}{'t':>7}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--desde", type=int, default=PRIMER_ANIO)
    args = ap.parse_args()

    print("=" * 84)
    print("  BACKTEST DEL MERCADO DE MÉTODO — ¿gana quién, y cómo?")
    print("=" * 84)

    if CACHE.exists() and not args.refit:
        d = pd.read_csv(CACHE, parse_dates=["date"])
        print(f"\n  Usando predicciones cacheadas ({CACHE.name}). --refit para recalcular.")
    else:
        print("\n  Reentrenando año a año (modelo de 6 clases):")
        d = predicciones_walk_forward(cargar(), args.desde)
        d.to_csv(CACHE, index=False)
        print(f"  [ok] cacheado -> {CACHE}")

    d = d[d[COL_ODDS].notna().all(axis=1)].reset_index(drop=True)

    # GUARDA DE SANIDAD (ver MIN_SOBRERREDONDEO): fuera las peleas cuyo mercado
    # es imposible. Sin esto el backtest reporta ganancias fantasma.
    s = sobrerredondeo(d)
    sano = s >= MIN_SOBRERREDONDEO
    if (~sano).any():
        malos = d.loc[~sano].groupby("anio").size()
        print(f"\n  [!] {(~sano).sum()} peleas descartadas: sus 6 cuotas suman "
              f"{s[~sano].mean():.3f} (imposible, la casa perdería dinero).")
        print(f"      Por año: {malos.to_dict()}")
        print("      Es un problema del dataset, no de la estrategia. Ver "
              "MIN_SOBRERREDONDEO en este archivo.")
    d = d[sano].reset_index(drop=True)

    Q = prob_mercado(d)                          # mercado sin vig
    P = d[[f"p_{c}" for c in CLASES]].to_numpy()  # modelo
    pago = pagos(d)
    y6 = d["y6"].to_numpy()
    anios = d["anio"].to_numpy()

    # comisión real de este mercado
    Praw = []
    for c in COL_ODDS:
        v = d[c].to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            Praw.append(np.where(v < 0, -v / (-v + 100.0), 100.0 / (v + 100.0)))
    comision = np.column_stack(Praw).sum(axis=1).mean() - 1

    print(f"\n  Peleas fuera de muestra con las 6 cuotas: {len(d)}")
    print(f"  Periodo: {d.date.min():%Y-%m} a {d.date.max():%Y-%m}")
    print(f"  COMISIÓN de este mercado: {comision*100:.1f}%  "
          f"(el de ganador cobra 4.0%)")

    # --- mezcla walk-forward ---
    Pool = np.full_like(P, np.nan)
    for anio in sorted(set(anios)):
        prev = anios < anio
        if prev.sum() < 800:
            continue
        cal = ajustar_pool(Q[prev], P[prev], y6[prev])
        cur = anios == anio
        Pool[cur] = aplicar_pool(Q[cur], P[cur], cal)
    hay = np.isfinite(Pool).all(axis=1)

    ll = lambda M, m: -np.mean(np.log(np.clip(M[m][np.arange(m.sum()), y6[m]], 1e-9, 1)))
    print(f"\n  {'':22}{'acierto':>10}{'log-loss':>11}")
    print(f"  {'MODELO solo':22}{(P.argmax(1)==y6).mean()*100:>9.1f}%{ll(P, hay):>11.4f}")
    print(f"  {'MERCADO solo':22}{(Q.argmax(1)==y6).mean()*100:>9.1f}%{ll(Q, hay):>11.4f}"
          f"   <- a quien hay que ganarle")
    print(f"  {'MODELO + MERCADO':22}{(Pool[hay].argmax(1)==y6[hay]).mean()*100:>9.1f}%"
          f"{ll(Pool, hay):>11.4f}   <- calibrado")

    # --- el sesgo, clase por clase ---
    print("\n" + "-" * 84)
    print("  EL SESGO DEL MERCADO (por qué podría haber grieta)")
    print("-" * 84)
    print(f"  {'resultado':12}{'ocurre':>9}{'mercado dice':>15}{'sesgo':>9}"
          f"{'ROI si apuestas siempre':>26}")
    print("  " + "-" * 80)
    for i, c in enumerate(CLASES):
        real, dice = np.mean(y6 == i), Q[:, i].mean()
        r = apostar(np.ones((len(d), 6)), pago, y6, -99, clases=[i])
        marca = "  <- infravalorado" if real > dice else ""
        print(f"  {c:12}{real*100:>8.1f}%{dice*100:>14.1f}%{(dice-real)*100:>+9.1f}"
              f"{r['roi']*100:>+17.1f}%{marca}")

    # --- apostar con el modelo calibrado ---
    print("\n" + "-" * 84)
    print("  APOSTAR CON EL MODELO CALIBRADO (todas las clases)")
    print("-" * 84)
    print(CAB)
    print("  " + "-" * 80)
    for ev in (0.0, 0.05, 0.10, 0.20, 0.35, 0.50):
        print(_linea(f"EV >= +{ev*100:.0f}%",
                     apostar(Pool[hay], pago[hay], y6[hay], ev)))

    print("\n" + "-" * 84)
    print("  SOLO DECISIONES (la clase que el público desprecia)")
    print("-" * 84)
    print(CAB)
    print("  " + "-" * 80)
    for ev in (-99, 0.0, 0.05, 0.10, 0.20):
        etq = "todas las decisiones" if ev < -1 else f"decisión con EV >= +{ev*100:.0f}%"
        print(_linea(etq, apostar(Pool[hay], pago[hay], y6[hay], ev, clases=[2, 5])))

    print("\n" + "-" * 84)
    print("  SOLO FINALIZACIONES (donde el público paga de más)")
    print("-" * 84)
    print(CAB)
    print("  " + "-" * 80)
    for ev in (-99, 0.0, 0.20):
        etq = "todas las finaliz." if ev < -1 else f"finaliz. con EV >= +{ev*100:.0f}%"
        print(_linea(etq, apostar(Pool[hay], pago[hay], y6[hay], ev, clases=[0, 1, 3, 4])))

    # --- cuánto de la ventaja es del MERCADO y cuánto del MODELO ---
    # Sin esta comparación es imposible saber si el modelo aporta algo: buena
    # parte del ROI sale gratis del sesgo anti-decisión, sin modelo ninguno.
    print("\n" + "-" * 84)
    print("  ¿CUÁNTO APORTA EL MODELO? (referencias sin modelo)")
    print("-" * 84)
    print(CAB)
    print("  " + "-" * 80)
    gano_m = (np.arange(6)[None, :] == y6[:, None])

    def _fija(sel: np.ndarray) -> dict:
        sel = sel & hay[:, None]
        ret = np.where(gano_m, pago, -1.0)[sel]
        ee = ret.std(ddof=1) / np.sqrt(len(ret))
        return {"n": len(ret), "acierto": gano_m[sel].mean(), "roi": ret.mean(),
                "profit": ret.sum(), "ee": ee, "t": ret.mean() / ee,
                "cuota": (1 + pago[sel]).mean()}

    solo_a_dec = np.zeros((len(d), 6), bool)
    solo_a_dec[:, 2] = True
    print(_linea("siempre A_DEC", _fija(solo_a_dec)))

    # decisión del lado que el mercado considera favorito
    dec_fav = np.zeros((len(d), 6), bool)
    dec_fav[np.arange(len(d)), np.where(Q[:, 2] >= Q[:, 5], 2, 5)] = True
    print(_linea("decisión del favorito", _fija(dec_fav)))
    print("\n  Estas dos NO usan el modelo: es el sesgo del mercado tal cual. Lo que")
    print("  el modelo aporta es la diferencia contra la tabla de arriba.")

    # --- estabilidad ---
    mejor_ev = 0.0
    print("\n" + "-" * 84)
    print(f"  AÑO A AÑO (decisiones con EV >= +{mejor_ev*100:.0f}%)")
    print("-" * 84)
    print(f"  {'año':8}{'apuestas':>10}{'acierto':>10}{'ROI':>11}{'ganancia':>11}")
    print("  " + "-" * 48)
    for anio in sorted(set(anios[hay])):
        m = hay & (anios == anio)
        r = apostar(Pool[m], pago[m], y6[m], mejor_ev, clases=[2, 5])
        if not r.get("n"):
            print(f"  {anio:<8}{0:>10}{'—':>10}{'—':>11}{'—':>11}")
            continue
        print(f"  {anio:<8}{r['n']:>10}{r['acierto']*100:>9.1f}%"
              f"{r['roi']*100:>+10.1f}%{r['profit']:>+10.1f}u")

    # --- guardar calibrador ---
    cal = ajustar_pool(Q[hay], P[hay], y6[hay])
    with open(CALIBRADOR, "wb") as fh:
        pickle.dump(cal, fh)
    print(f"\n  [ok] calibrador de método guardado (mercado {cal['peso_mercado']:.2f}, "
          f"modelo {cal['peso_modelo']:.2f}, n={cal['n']})")

    # Modelo final de 6 clases para predecir carteleras futuras. El
    # walk-forward de arriba mide; este predice.
    try:
        m, cols, n = entrenar_modelo6(cargar())
        with open(MODELO6, "wb") as fh:
            pickle.dump({"modelo": m, "cols": cols}, fh)
        print(f"  [ok] modelo de 6 clases guardado -> {MODELO6.name} "
              f"({n} filas, todo el historial)")
        print("       card.py lo usará si el CSV trae las 6 cuotas de método.")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  [!] no pude guardar el modelo de 6 clases: {e}")

    # --- veredicto ---
    # Se reporta por separado el periodo LIMPIO. Las filas de 2025+ que pasaron
    # la guarda igual tienen un sobrerredondeo distinto (1.15 vs 1.22 de los
    # años previos), señal de que vienen de otra fuente. Inflan el ROI a +40%,
    # así que el número que hay que creer es el del periodo homogéneo.
    limpio = hay & (anios <= 2024)
    dec = apostar(Pool[hay], pago[hay], y6[hay], 0.0, clases=[2, 5])
    dec_limpio = apostar(Pool[limpio], pago[limpio], y6[limpio], 0.0, clases=[2, 5])
    todo = apostar(Pool[hay], pago[hay], y6[hay], 0.0)
    print("\n" + "=" * 84)
    print("  VEREDICTO")
    print("=" * 84)
    for etq, r in (("Todas las clases, EV>=0", todo),
                   ("Solo decisiones, EV>=0 (todo el periodo)", dec),
                   ("Solo decisiones, EV>=0 (2018-2024, dato homogéneo)", dec_limpio)):
        if not r.get("n"):
            continue
        ic = 1.96 * r["ee"] * 100
        print(f"  {etq}\n     {r['n']} apuestas | ROI {r['roi']*100:+.1f}% ± {ic:.1f} "
              f"| t={r['t']:+.1f}")
        if r["t"] >= 2:
            print("     -> ventaja real: aguanta el test estadístico.")
        elif r["t"] <= -2:
            print("     -> pierde plata de forma significativa. No usar.")
        else:
            print("     -> empate técnico: no está probado que gane.")
    print()
    print("  LÉELO ASÍ: la grieta existe y está en el sesgo anti-decisión, no en")
    print("  'discrepar fuerte'. Pero antes de apostarla, dos advertencias reales:")
    print("   1. Una comisión del 22% significa que este mercado es RECREATIVO.")
    print("      Las casas lo saben: los límites son bajos y te cortan rápido si")
    print("      ganas. El ROI del backtest no dice cuánto volumen te aceptan.")
    print("   2. Estas cuotas son de un dataset, no de tu casa. Verifica que las")
    print("      tuyas paguen parecido antes de creerle al número.")
    print("=" * 84)


if __name__ == "__main__":
    main()
