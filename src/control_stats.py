"""
control_stats.py
Aporta las métricas de CONTROL/grappling que solo existen en los datos propios
de UFCStats, para inyectarlas en el pipeline de Kaggle (que da mejores métricas
globales pero es ciego al grappling).

La idea del modelo combinado:
  * base  -> dataset de Kaggle (golpeo, récord, biometría). Ya validado: AUC ~0.72.
  * extra -> control, defensa de derribo real y knockdowns, desde UFCStats.

Clave anti-leakage: para una pelea del 2019 se usan SOLO las peleas anteriores a
esa fecha. Se resuelve con sumas acumuladas por peleador + búsqueda binaria, así
que las ~12.000 consultas del entrenamiento son instantáneas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src.fighter_names import canonical_key

STATS_CSV = C.DATA_PROCESSED / "ufcstats_fight_stats.csv"

_IDX: dict[str, dict] | None = None

# Con menos de estas peleas, las tasas de control se consideran poco fiables
# y se atenúan hacia el promedio de la liga (ver stats_previas).
MIN_PELEAS_FIABLE = 3

# Promedios de la liga: es lo que se asume de un peleador del que no se sabe nada.
# Mucho más razonable que asumir CERO (que el modelo leía como "no controla").
PROMEDIO_LIGA = {
    "ctrl_per_min": 0.14, "opp_ctrl_per_min": 0.14,
    "ground_share": 0.16, "kd_per15": 0.35,
}

# Valores neutros cuando no hay NINGÚN historial (debutante absoluto).
NEUTRO = {
    "n_peleas": 0,
    **PROMEDIO_LIGA,
    "td_def_real": np.nan, "str_def_real": np.nan,
}


def _normalizar(s: str) -> str:
    return canonical_key(s)


def _construir_indice() -> dict[str, dict]:
    """Por peleador: fechas ordenadas + sumas acumuladas de cada métrica."""
    if not STATS_CSV.exists():
        print("[control] falta ufcstats_fight_stats.csv -> sin métricas de control")
        return {}
    df = pd.read_csv(STATS_CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "fighter", "fight_url"])
    # Un cambio de nombre no crea una segunda carrera. También protege de
    # exportaciones donde la misma pelea figura bajo las dos variantes.
    df["fighter"] = df["fighter"].map(_normalizar)
    df = df.drop_duplicates(subset=["fight_url", "fighter"])

    # cruzar con el rival de la misma pelea (para defensa y control recibido)
    df["_i"] = df.groupby("fight_url").cumcount()
    a = df[df._i == 0].set_index("fight_url")
    b = df[df._i == 1].set_index("fight_url")
    opp = ["sig_landed", "sig_att", "td_landed", "td_att", "ctrl_sec"]
    ren = {c: f"opp_{c}" for c in opp}
    par = pd.concat([a.join(b[opp].rename(columns=ren), how="inner"),
                     b.join(a[opp].rename(columns=ren), how="inner")]).reset_index()

    # duración aproximada por pelea (para las tasas por minuto)
    ev = C.DATA_PROCESSED / "ufcstats_fights.csv"
    if ev.exists():
        e = pd.read_csv(ev)
        cols = [c for c in ("fight_url", "round", "time") if c in e.columns]
        if "fight_url" in cols:
            par = par.merge(e[cols].drop_duplicates("fight_url"), on="fight_url", how="left")

    def dur(r):
        try:
            rnd = int(float(r.get("round") or 0))
        except (TypeError, ValueError):
            rnd = 0
        import re as _re
        m = _re.match(r"(\d{1,2}):(\d{2})", str(r.get("time") or ""))
        seg = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
        if rnd <= 0:
            return 15.0
        return (rnd - 1) * 5.0 + (seg / 60.0 if seg else 5.0)

    par["dur_min"] = par.apply(dur, axis=1).clip(0.5, 25.0)
    par["ground_landed"] = par.get("ground_landed", pd.Series(0, index=par.index)).fillna(0)
    par = par.sort_values("date")

    idx = {}
    for nombre, g in par.groupby("fighter"):
        g = g.sort_values("date")
        idx[_normalizar(nombre)] = {
            "fechas": g["date"].values,
            "cum": {c: np.concatenate([[0.0], g[c].fillna(0).cumsum().values])
                    for c in ("dur_min", "ctrl_sec", "opp_ctrl_sec", "ground_landed",
                              "sig_landed", "kd", "opp_sig_landed", "opp_sig_att",
                              "opp_td_landed", "opp_td_att")},
        }
    print(f"[control] índice de grappling para {len(idx)} peleadores")
    return idx


def indice() -> dict[str, dict]:
    global _IDX
    if _IDX is None:
        _IDX = _construir_indice()
    return _IDX


def stats_previas(nombre: str, fecha=None) -> dict:
    """
    Métricas de control de un peleador usando SOLO sus peleas anteriores a 'fecha'
    (si fecha es None, usa todo su historial = stats actuales).
    """
    d = indice().get(_normalizar(nombre))
    if not d:
        return {**NEUTRO, "historial_disponible": False}
    n = (int(np.searchsorted(d["fechas"], np.datetime64(pd.Timestamp(fecha)), side="left"))
         if fecha is not None else len(d["fechas"]))
    if n <= 0:
        return {**NEUTRO, "historial_disponible": True}

    c = d["cum"]
    mins = max(c["dur_min"][n], 1.0)
    sig = max(c["sig_landed"][n], 1.0)
    opp_sig_att = c["opp_sig_att"][n]
    opp_td_att = c["opp_td_att"][n]
    out = {
        "n_peleas": n,
        "historial_disponible": True,
        "ctrl_per_min": c["ctrl_sec"][n] / mins / 60.0,
        "opp_ctrl_per_min": c["opp_ctrl_sec"][n] / mins / 60.0,
        "ground_share": c["ground_landed"][n] / sig,
        "kd_per15": c["kd"][n] / mins * 15.0,
        # defensa REAL (lo que el rival logró contra él); NaN si no hay intentos
        "td_def_real": (1.0 - c["opp_td_landed"][n] / opp_td_att) if opp_td_att >= 3 else np.nan,
        "str_def_real": (1.0 - c["opp_sig_landed"][n] / opp_sig_att) if opp_sig_att >= 20 else np.nan,
    }

    # MUESTRA CHICA: con 1-2 peleas el control no es una medida, es ruido.
    # Caso real: Vagaev tenía ctrl=0.000 (1 sola pelea) y el modelo lo leyó como
    # "no controla nada" -> lo hizo underdog pese a tener 194 puntos más de ELO.
    # Ganó Vagaev. Con pocas peleas se atenúa hacia el promedio de la liga.
    if n < MIN_PELEAS_FIABLE:
        peso = n / MIN_PELEAS_FIABLE
        for k, prom in PROMEDIO_LIGA.items():
            out[k] = out[k] * peso + prom * (1 - peso)
    return out


def enriquecer(stats: dict, fecha=None) -> dict:
    """
    Agrega las métricas de control a un dict de peleador y, si hay dato real,
    reemplaza str_def/td_def (que en el dataset de Kaggle venían por defecto).
    """
    extra = stats_previas(stats.get("name", ""), fecha)
    out = {**stats, **{k: v for k, v in extra.items() if not k.endswith("_real")}}
    if extra["historial_disponible"]:
        out["n_peleas_hist"] = int(extra["n_peleas"])
    else:
        # No encontrar la identidad en la descarga local no demuestra que
        # debutó. Conserva un conteo explícito de la ficha si está disponible.
        out["n_peleas_hist"] = stats.get("n_peleas_ufc") if fecha is None else None
    if not pd.isna(extra["td_def_real"]):
        out["td_def"] = float(extra["td_def_real"])
    if not pd.isna(extra["str_def_real"]):
        out["str_def"] = float(extra["str_def_real"])
    return out
