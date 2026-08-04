"""
ufcstats_ingest.py
Construye el dataset de ENTRENAMIENTO desde los datos propios de UFCStats,
reemplazando a kaggle_ingest.py.

Diferencia clave con Kaggle: acá tenemos cada pelea por separado con su fecha,
así que los promedios de cada peleador se calculan SOLO con sus peleas
ANTERIORES. El data leakage se elimina por construcción, no con parches.

Métricas que Kaggle no permitía y ahora sí:
  * ctrl_per_min   -> tiempo de control por minuto: la señal del grappling
                      dominante (Khabib/Ankalaev ganan controlando, no golpeando)
  * ground_share   -> % de golpes conectados desde el suelo (estilo de lucha)
  * kd_per15       -> knockdowns por 15 min: poder real, no volumen
  * str_def / td_def REALES: como cada pelea trae los números del rival, la
    defensa se calcula de verdad (antes era una constante y el modelo nunca
    aprendió que servía).

Uso:
    python -m src.ufcstats_ingest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src.features import EloSystem, differential_features

STATS_CSV = C.DATA_PROCESSED / "ufcstats_fight_stats.csv"
MIN_PELEAS = 1          # mínimo de peleas previas para incluir a un peleador


def _dur_min(row) -> float:
    """Duración de la pelea en minutos, desde round + tiempo del último asalto."""
    try:
        rnd = int(float(row.get("round") or 0))
    except (ValueError, TypeError):
        rnd = 0
    t = str(row.get("time") or "")
    m = re.match(r"(\d{1,2}):(\d{2})", t)
    seg = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
    if rnd <= 0:
        return 15.0 if seg == 0 else seg / 60.0      # fallback razonable
    return (rnd - 1) * 5.0 + (seg / 60.0 if seg else 5.0)


def cargar() -> pd.DataFrame:
    if not STATS_CSV.exists():
        raise SystemExit(
            "Falta el dataset de estadísticas. Corre primero:\n"
            "    python -m src.ufcstats_events\n"
            "    python -m src.ufcstats_fightstats")
    df = pd.read_csv(STATS_CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "fighter", "fight_url"]).sort_values("date")

    # duración: viene del CSV de eventos si está, si no se estima
    ev = C.DATA_PROCESSED / "ufcstats_fights.csv"
    if ev.exists():
        e = pd.read_csv(ev)
        if "fight_url" in e.columns:
            cols = [c for c in ("fight_url", "round", "time") if c in e.columns]
            df = df.merge(e[cols].drop_duplicates("fight_url"), on="fight_url", how="left")
    df["dur_min"] = df.apply(_dur_min, axis=1).clip(0.5, 25.0)
    print(f"[ingest] {len(df)} filas peleador-pelea | {df.fight_url.nunique()} peleas | "
          f"{df.fighter.nunique()} peleadores")
    return df


def _emparejar(df: pd.DataFrame) -> pd.DataFrame:
    """Cruza cada fila con la de su rival en la misma pelea (para calcular defensa)."""
    df = df.copy()
    df["_i"] = df.groupby("fight_url").cumcount()
    a = df[df._i == 0].set_index("fight_url")
    b = df[df._i == 1].set_index("fight_url")
    opp_cols = ["sig_landed", "sig_att", "td_landed", "td_att", "ctrl_sec"]
    ren = {c: f"opp_{c}" for c in opp_cols}
    juntos = pd.concat([
        a.join(b[opp_cols].rename(columns=ren), how="inner"),
        b.join(a[opp_cols].rename(columns=ren), how="inner"),
    ])
    return juntos.reset_index()


def _acumulado(hist: pd.DataFrame) -> dict:
    """Promedios de un peleador a partir de sus peleas PREVIAS (formato Fighter)."""
    mins = max(hist["dur_min"].sum(), 1.0)
    sig_att = max(hist["sig_att"].sum(), 1.0)
    td_att = max(hist["td_att"].sum(), 1.0)
    opp_sig_att = max(hist["opp_sig_att"].sum(), 1.0)
    opp_td_att = max(hist["opp_td_att"].sum(), 1.0)
    n = len(hist)
    wins = int(hist["won"].sum())

    # racha: recorre de la más reciente hacia atrás
    seq = hist.sort_values("date", ascending=False)["won"].tolist()
    streak = 0
    if seq:
        primero = seq[0]
        for w in seq:
            if w == primero:
                streak += 1
            else:
                break
        streak = streak if primero == 1 else -streak

    ganadas = hist[hist["won"] == 1]
    perdidas = hist[hist["won"] == 0]

    def tasa(sub, metodos):
        return float(sub["method"].isin(metodos).mean()) if len(sub) else 0.0

    return {
        "name": "",
        # --- golpeo ---
        "slpm": hist["sig_landed"].sum() / mins,
        "str_acc": hist["sig_landed"].sum() / sig_att,
        "sapm": hist["opp_sig_landed"].sum() / mins,
        "str_def": 1.0 - (hist["opp_sig_landed"].sum() / opp_sig_att),
        # --- lucha ---
        "td_avg": hist["td_landed"].sum() / mins * 15.0,
        "td_acc": hist["td_landed"].sum() / td_att,
        "td_def": 1.0 - (hist["opp_td_landed"].sum() / opp_td_att),
        "sub_avg": hist["sub_att"].sum() / mins * 15.0,
        # --- NUEVAS: grappling y poder ---
        "ctrl_per_min": hist["ctrl_sec"].sum() / mins / 60.0,
        "opp_ctrl_per_min": hist["opp_ctrl_sec"].sum() / mins / 60.0,
        "ground_share": (hist["ground_landed"].sum() / max(hist["sig_landed"].sum(), 1.0)
                         if "ground_landed" in hist else 0.0),
        "kd_per15": hist["kd"].sum() / mins * 15.0,
        # --- historial ---
        "wins": wins, "losses": n - wins, "streak": streak,
        "days_since_last_fight": 0.0,
        "win_ko_rate": tasa(ganadas, ["KO/TKO"]),
        "win_sub_rate": tasa(ganadas, ["Submission"]),
        "win_dec_rate": tasa(ganadas, ["Decision"]),
        "lost_by_finish_rate": 1.0 - tasa(perdidas, ["Decision"]) if len(perdidas) else 0.0,
        # biometría: no está en las estadísticas de pelea (se rellena en predicción)
        "age": 0.0, "height_cm": 0.0, "reach_cm": 0.0, "stance": "Orthodox",
    }


def _cargar_bio() -> dict:
    """
    Biometría por peleador (fecha de nacimiento, altura, alcance, postura).
    Sin esto, age_diff/reach_diff/height_diff quedan en CERO — y age_diff es la
    variable más importante del modelo, así que su ausencia cuesta ~0.07 de AUC.
    """
    bio_csv = C.DATA_PROCESSED / "ufcstats_bio.csv"
    if not bio_csv.exists():
        print("[!] falta ufcstats_bio.csv -> edad/alcance/altura irán en 0. "
              "Corre: python -m src.ufcstats_fighters")
        return {}
    b = pd.read_csv(bio_csv)
    b["dob"] = pd.to_datetime(b["dob"], errors="coerce")
    out = {}
    for r in b.itertuples():
        nombre = str(getattr(r, "name", "")).strip()
        if nombre:
            out[nombre.lower()] = {
                "dob": r.dob, "height_cm": float(getattr(r, "height_cm", 0) or 0),
                "reach_cm": float(getattr(r, "reach_cm", 0) or 0),
                "stance": str(getattr(r, "stance", "Orthodox") or "Orthodox"),
            }
    print(f"[ingest] biometría cargada para {len(out)} peleadores")
    return out


def _aplicar_bio(d: dict, nombre: str, bio: dict, fecha) -> None:
    """Rellena edad (a la FECHA de la pelea), altura, alcance y postura."""
    b = bio.get(str(nombre).lower())
    if not b:
        return
    d["height_cm"] = b["height_cm"]
    d["reach_cm"] = b["reach_cm"]
    d["stance"] = b["stance"]
    if pd.notna(b["dob"]):
        d["age"] = round((fecha - b["dob"]).days / 365.25, 1)


def features_pelea(a: dict, b: dict, elo_a: float, elo_b: float) -> dict:
    """
    Vector de features de un duelo. Se usa TANTO al entrenar como al predecir,
    para que ambos lados no se desincronicen (si el entrenamiento usa 16
    columnas y la predicción manda 12, XGBoost falla).
    """
    base = differential_features(a, b, elo_a, elo_b)
    extra = {
        "ctrl_diff": a.get("ctrl_per_min", 0) - b.get("ctrl_per_min", 0),
        "ctrl_vs_def_diff": (a.get("ctrl_per_min", 0) - b.get("opp_ctrl_per_min", 0))
                            - (b.get("ctrl_per_min", 0) - a.get("opp_ctrl_per_min", 0)),
        "ground_share_diff": a.get("ground_share", 0) - b.get("ground_share", 0),
        "kd_rate_diff": a.get("kd_per15", 0) - b.get("kd_per15", 0),
    }
    return {**base, **extra}


# --------------------------------------------------------------------------- #
# Stats ACTUALES de un peleador (para predecir peleas futuras)
# --------------------------------------------------------------------------- #
_CACHE_HIST: pd.DataFrame | None = None


def _historial() -> pd.DataFrame:
    global _CACHE_HIST
    if _CACHE_HIST is None:
        _CACHE_HIST = _emparejar(cargar()).sort_values("date")
    return _CACHE_HIST


def stats_actuales(nombre: str) -> dict | None:
    """
    Stats de un peleador HOY, calculadas desde TODAS sus peleas registradas.
    Mismo cálculo que en el entrenamiento -> las features son comparables.
    Devuelve None si el peleador no tiene historial (debutante).
    """
    h = _historial()
    sub = h[h["fighter"].str.lower() == str(nombre).lower()]
    if sub.empty:
        sub = h[h["fighter"].str.lower().str.contains(str(nombre).lower(), na=False)]
    if sub.empty:
        return None

    d = _acumulado(sub)
    d["name"] = sub["fighter"].iloc[-1]
    ult = sub["date"].max()
    d["days_since_last_fight"] = float((pd.Timestamp.today() - ult).days)

    bio = _cargar_bio().get(d["name"].lower())
    if bio:
        d["height_cm"] = bio["height_cm"]
        d["reach_cm"] = bio["reach_cm"]
        d["stance"] = bio["stance"]
        if pd.notna(bio["dob"]):
            d["age"] = round((pd.Timestamp.today() - bio["dob"]).days / 365.25, 1)
    return d


def build(min_peleas: int = MIN_PELEAS, desde: str | None = None,
          guardar: bool = True) -> pd.DataFrame:
    """
    min_peleas : peleas previas exigidas para incluir un combate. Con 1, un
                 peleador entra con promedios sacados de UNA pelea = puro ruido.
    desde      : fecha mínima ('2010-01-01'). El UFC de los 90 es otro deporte
                 (sin categorías de peso reales, sin rounds) y puede ensuciar.
    """
    df = _emparejar(cargar())
    df = df.sort_values("date")
    bio = _cargar_bio()
    corte = pd.Timestamp(desde) if desde else None

    elo = EloSystem()
    hist: dict[str, list] = {}
    ultima: dict[str, pd.Timestamp] = {}
    filas = []

    for fu, pelea in df.groupby("fight_url", sort=False):
        if len(pelea) != 2:
            continue
        r1, r2 = pelea.iloc[0], pelea.iloc[1]
        n1, n2 = r1["fighter"], r2["fighter"]
        wc = r1.get("weight_class", "Unknown")
        fecha = r1["date"]

        h1, h2 = hist.get(n1, []), hist.get(n2, [])
        en_rango = corte is None or fecha >= corte
        if en_rango and len(h1) >= min_peleas and len(h2) >= min_peleas:
            a = _acumulado(pd.DataFrame(h1)); a["name"] = n1
            b = _acumulado(pd.DataFrame(h2)); b["name"] = n2
            a["days_since_last_fight"] = (fecha - ultima[n1]).days if n1 in ultima else 0.0
            b["days_since_last_fight"] = (fecha - ultima[n2]).days if n2 in ultima else 0.0
            # edad AL DÍA DE LA PELEA (no la actual): sin mirar el futuro
            _aplicar_bio(a, n1, bio, fecha)
            _aplicar_bio(b, n2, bio, fecha)

            ea, eb = elo.get(n1, wc), elo.get(n2, wc)     # ELO PRE-pelea
            y = 1 if r1["won"] == 1 else 0
            metodo = r1.get("method", "Decision")

            filas.append({**features_pelea(a, b, ea, eb),
                          "date": fecha, "y": y, "method": metodo})
            filas.append({**features_pelea(b, a, eb, ea),
                          "date": fecha, "y": 1 - y, "method": metodo})

        # recién ahora se actualizan historial y ELO (para las próximas peleas)
        for r in (r1, r2):
            hist.setdefault(r["fighter"], []).append(r.to_dict())
            ultima[r["fighter"]] = fecha
        gan = n1 if r1["won"] == 1 else (n2 if r2["won"] == 1 else None)
        if gan:
            per = n2 if gan == n1 else n1
            elo.update(gan, per, wc, r1.get("method") in ("KO/TKO", "Submission"))

    feats = pd.DataFrame(filas)
    if feats.empty:
        raise SystemExit("No se generaron features (¿pocas peleas descargadas?).")
    if guardar:
        feats.to_csv(C.FEATURES_CSV, index=False)
        elo.to_frame().to_csv(C.ELO_TABLE, index=False)
    print(f"[ok] features.csv -> {feats.shape[0]} filas, {feats.shape[1]} columnas")
    print(f"[ok] elo_ratings.csv -> {C.ELO_TABLE}")
    print(f"     rango: {feats.date.min():%Y-%m-%d} a {feats.date.max():%Y-%m-%d}")
    return feats


if __name__ == "__main__":
    build()
