"""
modelado/backtest_valor.py
¿Apostar donde el modelo y el mercado discrepan fuerte da plata de verdad?

Esta es la pregunta cara. Un modelo puede acertar 66% y AUN ASÍ perder dinero
apostando, porque la casa te cobra comisión y porque acertar favoritos baratos
no paga. Lo único que importa es el ROI sobre apuestas que el modelo eligió
SIN haber visto el resultado ni la cuota.

MÉTODO — validación walk-forward (año a año)
--------------------------------------------
Probar solo con 2025+ deja ~600 peleas: con esa muestra el ROI tiene un margen
de error de ±8 puntos y no se puede concluir nada. Así que se reentrena el
modelo una vez por año:

    entrena con TODO lo anterior a 2016  ->  apuesta las peleas de 2016
    entrena con TODO lo anterior a 2017  ->  apuesta las peleas de 2017
    ... y así hasta 2026

Cada pelea se apuesta con un modelo que solo vio el pasado. Eso da ~5.500
peleas fuera de muestra en vez de 600, y encima muestra si la ventaja se
mantiene en el tiempo o se murió cuando el mercado se puso eficiente.

El modelo NO usa `market_edge` como feature (columnas_disponibles lo excluye
por defecto): si lo usara, copiaría al mercado y nunca discreparía.

Uso:
    python -m modelado.backtest_valor                  # barrido completo
    python -m modelado.backtest_valor --desde 2019     # solo años recientes
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

import config as C
from src.features import columnas_disponibles
from src.value import (analizar_lote, vig, ajustar_calibrador, combinar,
                       MIN_DISCREPANCIA, MIN_EV)

PRIMER_ANIO = 2016          # antes hay poca data de entrenamiento
COMISION_UNIDAD = 1.0       # apuesta plana de 1 unidad (flat betting)
CACHE = C.DATA_PROCESSED / "walkforward_valor.csv"   # predicciones ya calculadas


# --------------------------------------------------------------------------- #
# Datos y predicciones fuera de muestra
# --------------------------------------------------------------------------- #
def cargar() -> pd.DataFrame:
    df = pd.read_csv(C.FEATURES_CSV)
    df["date"] = pd.to_datetime(df["date"])
    if "odds_a" not in df.columns:
        raise SystemExit(
            "features.csv no trae las cuotas (odds_a/odds_b).\n"
            "Regenera el dataset:  python -m src.kaggle_ingest"
        )
    return df


def _modelo():
    """Mismos hiperparámetros que train_model.py, para que el backtest mida
    el modelo que el usuario realmente usa."""
    return XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.03,
        subsample=0.85, colsample_bytree=0.85, reg_lambda=1.5,
        eval_metric="logloss", random_state=C.RANDOM_STATE,
    )


def predicciones_walk_forward(df: pd.DataFrame, primer_anio: int) -> pd.DataFrame:
    """
    Devuelve 1 fila por pelea (no por orientación) con la probabilidad que el
    modelo le habría dado ANTES de que ocurriera.

    Detalle fino: XGBoost no es perfectamente antisimétrico — predecir "A vs B"
    y "B vs A" no da exactamente probabilidades complementarias. Se promedian
    las dos orientaciones, que es la estimación más estable y evita que el
    resultado dependa de qué peleador quedó como 'A' en el dataset.
    """
    cols = columnas_disponibles(df)          # SIN market_edge, a propósito
    df = df.reset_index(drop=True)
    anios = sorted(a for a in df["date"].dt.year.unique() if a >= primer_anio)

    salida = []
    for anio in anios:
        train = df[df["date"].dt.year < anio]
        test = df[df["date"].dt.year == anio]
        if len(train) < 500 or test.empty:
            continue
        m = _modelo()
        m.fit(train[cols], train["y"])
        p = m.predict_proba(test[cols])[:, 1]

        # test conserva el orden original -> las filas van en pares (i, i+1)
        directa = test.iloc[::2].copy()
        p_dir, p_esp = p[::2], p[1::2]
        directa["p_modelo"] = (p_dir + (1.0 - p_esp)) / 2.0
        directa["anio"] = anio
        salida.append(directa)
        print(f"  {anio}: entrena {len(train):>6} filas -> predice {len(directa):>4} peleas")

    if not salida:
        raise SystemExit("No hubo años con suficiente historial para el walk-forward.")
    return pd.concat(salida, ignore_index=True)


# --------------------------------------------------------------------------- #
# Calibración walk-forward: los pesos del blend también se estiman con el pasado
# --------------------------------------------------------------------------- #
def agregar_calibrado(d: pd.DataFrame, min_hist: int = 800) -> pd.DataFrame:
    """
    Añade p_mercado y p_calibrado a cada pelea.

    El calibrador de cada año se ajusta SOLO con peleas de años anteriores. Si
    se ajustara con todo el historial, los pesos ya habrían visto los
    resultados que después se apuestan y el ROI saldría inflado.
    """
    v = analizar_lote(d["p_modelo"].values, d["odds_a"].values, d["odds_b"].values)
    d = d.copy()
    d["p_mercado"] = v["p_mercado_a"]
    d["p_calibrado"] = np.nan

    for anio in sorted(d["anio"].unique()):
        prev = d[(d["anio"] < anio) & d["p_mercado"].notna()]
        if len(prev) < min_hist:
            continue
        cal = ajustar_calibrador(prev["p_mercado"], prev["p_modelo"], prev["y"],
                                 guardar=False)
        cur = d["anio"] == anio
        d.loc[cur, "p_calibrado"] = [
            combinar(pm, pk, cal)
            for pm, pk in zip(d.loc[cur, "p_modelo"], d.loc[cur, "p_mercado"])
        ]
    return d


# --------------------------------------------------------------------------- #
# Simulación de apuestas
# --------------------------------------------------------------------------- #
def simular(d: pd.DataFrame, min_disc: float, min_ev: float,
            col: str = "p_modelo") -> dict:
    """
    Apuesta 1 unidad plana en cada pelea que pase los filtros.

    `col` elige con qué probabilidad se decide: "p_modelo" (cruda, la idea
    original) o "p_calibrado" (mezclada con el mercado). La diferencia entre
    esas dos columnas es la diferencia entre perder y no perder.
    """
    p = d[col].values
    ok0 = np.isfinite(p)
    v = analizar_lote(np.where(ok0, p, 0.5), d["odds_a"].values, d["odds_b"].values)

    ok = ok0 & np.isfinite(v["cuota_lado"])
    sel = ok & (v["disc_lado"] >= min_disc) & (v["ev"] >= min_ev)
    n = int(sel.sum())
    if n == 0:
        return {"n": 0, "acierto": np.nan, "roi": np.nan, "profit": 0.0,
                "ee": np.nan, "t": np.nan, "cuota_media": np.nan}

    gana_a = d["y"].values == 1
    acerto = np.where(v["apuesta_a"], gana_a, ~gana_a)[sel]
    pago = v["pago"][sel]
    # retorno por unidad apostada: +pago si acierta, -1 si falla
    ret = np.where(acerto, pago, -1.0) * COMISION_UNIDAD

    roi = ret.mean()
    ee = ret.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {
        "n": n,
        "acierto": float(acerto.mean()),
        "roi": float(roi),
        "profit": float(ret.sum()),
        "ee": float(ee),
        "t": float(roi / ee) if ee and np.isfinite(ee) and ee > 0 else np.nan,
        "cuota_media": float((1 + pago).mean()),
        "ret": ret,
        "sel": sel,
    }


def _linea(etq: str, r: dict) -> str:
    if r["n"] == 0:
        return f"  {etq:22}{'—':>8}{'sin apuestas':>36}"
    signo = "+" if r["roi"] >= 0 else ""
    return (f"  {etq:22}{r['n']:>8}{r['acierto']*100:>9.1f}%"
            f"{signo + format(r['roi']*100, '.1f') + '%':>11}"
            f"{r['profit']:>+10.1f}u{r['cuota_media']:>9.2f}"
            f"{(format(r['t'], '.1f') if np.isfinite(r['t']) else '—'):>7}")


CAB = (f"  {'filtro':22}{'apuestas':>8}{'acierto':>10}{'ROI':>11}"
       f"{'ganancia':>11}{'cuota':>9}{'t':>7}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=PRIMER_ANIO,
                    help="primer año a apostar (default 2016)")
    ap.add_argument("--refit", action="store_true",
                    help="reentrena aunque exista caché de predicciones")
    args = ap.parse_args()

    print("=" * 78)
    print("  BACKTEST DE VALOR — apostar donde el modelo discrepa del mercado")
    print("=" * 78)

    # Los 11 reentrenamientos tardan ~2 min; las predicciones no cambian salvo
    # que cambien el dataset o el modelo. Se cachean para poder probar umbrales
    # al instante (usa --refit para forzar el recálculo).
    if CACHE.exists() and not args.refit:
        d = pd.read_csv(CACHE, parse_dates=["date"])
        d = d[d["anio"] >= args.desde].reset_index(drop=True)
        print(f"\n  Usando predicciones cacheadas ({CACHE.name}). --refit para recalcular.")
    else:
        df = cargar()
        print("\n  Reentrenando año a año (cada pelea la predice un modelo que solo vio el pasado):")
        d = predicciones_walk_forward(df, args.desde)
        d.to_csv(CACHE, index=False)
        print(f"  [ok] predicciones cacheadas -> {CACHE}")

    con_cuota = d[d["odds_a"].notna() & d["odds_b"].notna()].reset_index(drop=True)
    con_cuota = agregar_calibrado(con_cuota)
    print(f"\n  Peleas fuera de muestra: {len(d)}  |  con cuotas: {len(con_cuota)}")
    print(f"  Periodo: {con_cuota.date.min():%Y-%m} a {con_cuota.date.max():%Y-%m}")

    # --- ¿quién predice mejor? ---
    y = con_cuota["y"].values
    cal_ok = con_cuota["p_calibrado"].notna().values
    def _acc(p):
        return np.mean(np.where(p >= 0.5, y == 1, y == 0))
    def _ll(p, m=None):
        m = np.ones(len(y), bool) if m is None else m
        pp = np.clip(p[m], 1e-9, 1 - 1e-9)
        return -np.mean(y[m] * np.log(pp) + (1 - y[m]) * np.log(1 - pp))

    print(f"\n  {'':22}{'acierto':>10}{'log-loss':>11}")
    print(f"  {'MODELO solo':22}{_acc(con_cuota.p_modelo.values)*100:>9.1f}%"
          f"{_ll(con_cuota.p_modelo.values, cal_ok):>11.4f}")
    print(f"  {'MERCADO solo':22}{_acc(con_cuota.p_mercado.values)*100:>9.1f}%"
          f"{_ll(con_cuota.p_mercado.values, cal_ok):>11.4f}   <- a quien hay que ganarle")
    print(f"  {'MODELO + MERCADO':22}"
          f"{_acc(con_cuota.p_calibrado.fillna(0.5).values)*100:>9.1f}%"
          f"{_ll(con_cuota.p_calibrado.fillna(0.5).values, cal_ok):>11.4f}   <- calibrado")
    comision = np.nanmean([vig(a, b) for a, b in
                           zip(con_cuota["odds_a"], con_cuota["odds_b"])])
    print(f"\n  Comisión media de la casa: {comision*100:.1f}%  "
          f"<- el peaje que hay que superar para ganar algo")

    # --- referencias ---
    print("\n" + "-" * 78)
    print("  REFERENCIAS")
    print("-" * 78)
    print(CAB)
    print("  " + "-" * 74)
    print(_linea("todo el desacuerdo", simular(con_cuota, -1.0, -99.0)))
    fav = con_cuota.copy()
    fav["p_modelo"] = np.where(con_cuota["p_mercado"].values >= 0.5, 1.0, 0.0)
    print(_linea("siempre al favorito", simular(fav, -1.0, -99.0)))

    # --- LA IDEA ORIGINAL: discrepancia cruda ---
    print("\n" + "-" * 78)
    print("  A) DISCREPANCIA CRUDA — apostar donde el modelo se separa de la línea")
    print("-" * 78)
    print(CAB)
    print("  " + "-" * 74)
    for disc in (0.05, 0.10, 0.15, 0.20, 0.25):
        print(_linea(f"discrepa >= {disc*100:.0f} pts", simular(con_cuota, disc, -99.0)))
    for ev in (0.05, 0.20):
        print(_linea(f"disc>=10 y EV>=+{ev*100:.0f}%", simular(con_cuota, 0.10, ev)))

    # --- LA VERSIÓN CALIBRADA ---
    print("\n" + "-" * 78)
    print("  B) DISCREPANCIA CALIBRADA — misma idea, pero descontando el exceso")
    print("     de confianza del modelo (mezcla con el mercado)")
    print("-" * 78)
    print(CAB)
    print("  " + "-" * 74)
    for disc, ev in ((0.0, 0.0), (0.02, 0.0), (0.02, 0.03), (0.03, 0.03),
                     (0.04, 0.05), (0.05, 0.05)):
        print(_linea(f"disc>={disc*100:.0f}pts y EV>=+{ev*100:.0f}%",
                     simular(con_cuota, disc, ev, col="p_calibrado")))

    # --- dónde vive la ventaja (si vive en alguna parte) ---
    print("\n" + "-" * 78)
    print("  C) POR SUBCONJUNTO (calibrado, EV>=0) — ¿hay algún nicho?")
    print("-" * 78)
    print(CAB)
    print("  " + "-" * 74)
    subs = {
        "favoritos del mercado": con_cuota["p_mercado"] >= 0.5,
        "underdogs del mercado": con_cuota["p_mercado"] < 0.5,
        "peleas parejas 40-60": con_cuota["p_mercado"].between(0.40, 0.60),
        "desde 2022": con_cuota["anio"] >= 2022,
        "hasta 2021": con_cuota["anio"] < 2022,
    }
    for etq, m in subs.items():
        print(_linea(etq, simular(con_cuota[m.values].reset_index(drop=True),
                                  0.0, 0.0, col="p_calibrado")))

    # --- estabilidad año a año ---
    print("\n" + "-" * 78)
    print(f"  D) AÑO A AÑO (calibrado, disc>={MIN_DISCREPANCIA*100:.0f}pts y "
          f"EV>=+{MIN_EV*100:.0f}%)")
    print("-" * 78)
    print(f"  {'año':8}{'apuestas':>10}{'acierto':>10}{'ROI':>11}{'ganancia':>11}")
    print("  " + "-" * 48)
    for anio, g in con_cuota.groupby("anio"):
        r = simular(g.reset_index(drop=True), MIN_DISCREPANCIA, MIN_EV,
                    col="p_calibrado")
        if r["n"] == 0:
            print(f"  {anio:<8}{0:>10}{'—':>10}{'—':>11}{'—':>11}")
            continue
        print(f"  {anio:<8}{r['n']:>10}{r['acierto']*100:>9.1f}%"
              f"{r['roi']*100:>+10.1f}%{r['profit']:>+10.1f}u")

    # --- guardar el calibrador para usarlo en vivo ---
    ok = con_cuota["p_mercado"].notna()
    cal = ajustar_calibrador(con_cuota.loc[ok, "p_mercado"],
                             con_cuota.loc[ok, "p_modelo"],
                             con_cuota.loc[ok, "y"])
    print(f"\n  [ok] calibrador guardado (peso mercado {cal['peso_mercado']:.2f}, "
          f"peso modelo {cal['peso_modelo']:.2f}, n={cal['n']})")
    print("       card.py lo usará automáticamente cuando le pases cuotas.")

    # --- veredicto ---
    cruda = simular(con_cuota, 0.10, 0.05)
    calib = simular(con_cuota, MIN_DISCREPANCIA, MIN_EV, col="p_calibrado")
    print("\n" + "=" * 78)
    print("  VEREDICTO")
    print("=" * 78)
    print("  ROI = ganancia por unidad apostada. +5% = por cada $1.000 apostados")
    print("        vuelven $1.050. Los profesionales viven con +3% a +8%.")
    print("  t   = cuántos errores estándar mide el ROI. Con |t| < 2 el resultado")
    print("        es indistinguible de suerte, por lindo que se vea.")
    print()
    for etq, r in (("Discrepancia CRUDA (disc>=10pts, EV>=+5%)", cruda),
                   (f"Discrepancia CALIBRADA (disc>={MIN_DISCREPANCIA*100:.0f}pts, "
                    f"EV>=+{MIN_EV*100:.0f}%)", calib)):
        if not r["n"] or not np.isfinite(r["t"]):
            continue
        ic = 1.96 * r["ee"] * 100
        print(f"  {etq}")
        print(f"     {r['n']} apuestas | ROI {r['roi']*100:+.1f}% ± {ic:.1f} (95% conf.) "
              f"| t={r['t']:+.1f}")
        if r["t"] >= 2:
            print("     -> ventaja real: aguanta el test estadístico.")
        elif r["t"] <= -2:
            print("     -> PIERDE PLATA de forma significativa. No usar.")
        elif r["roi"] > 0:
            print("     -> empate técnico con la casa. No está probado que gane.")
        else:
            print("     -> empate técnico tirando a perder.")
        print()
    print("=" * 78)


if __name__ == "__main__":
    main()
