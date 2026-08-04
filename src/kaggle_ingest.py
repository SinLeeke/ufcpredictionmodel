"""
kaggle_ingest.py
Ingesta REAL del dataset 'rajeevw/ufcdata' (formato: 1 fila por pelea con
columnas prefijadas R_ / B_). Reemplaza al stub _fighters_from_kaggle().

Produce dos salidas:
  * features.csv  -> matriz diferencial A-B con aumento antisimétrico (para model.py)
  * fighters.csv  -> stats más recientes por peleador (1 fila c/u, para predict.py)

Diseñado para ser DEFENSIVO frente a variaciones de esquema: resuelve columnas
por nombre y, si falta un concepto, lo rellena con un default y avisa, en vez de
morir en silencio con 0 filas.

Notas de mapeo (UFCStats vs Kaggle):
  - El dataset trae promedios POR PELEA, no "por minuto". Los usamos como proxy
    directo; la lógica diferencial se mantiene válida.
  - str_def se aproxima como 1 - (precisión de golpeo del rival)  = 1 - opp_SIG_STR_pct
  - td_def  se aproxima como 1 - (precisión de derribo del rival) = 1 - opp_TD_pct
  - lost_by_finish_rate no existe en data.csv -> default neutral (documentado).
  - days_since_last_fight SÍ se calcula reconstruyendo el historial por fecha.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C
from src.features import (differential_features, EloSystem, _normalize_method,
                          valor_resultado)
from src.control_stats import enriquecer as _enriquecer_control
from src.ufcstats_ingest import features_pelea

DEFAULT_LOST_BY_FINISH = 0.35  # sin fuente en data.csv; neutral e igual para todos

# concepto -> sufijo(s) candidato(s) tras el prefijo R_/B_
STAT_SUFFIX = {
    "slpm":        ["avg_SIG_STR_landed"],
    "str_acc":     ["avg_SIG_STR_pct"],
    "sapm":        ["avg_opp_SIG_STR_landed"],
    "opp_str_pct": ["avg_opp_SIG_STR_pct"],
    "td_avg":      ["avg_TD_landed"],
    "td_acc":      ["avg_TD_pct"],
    "opp_td_pct":  ["avg_opp_TD_pct"],
    "sub_avg":     ["avg_SUB_ATT"],
    "age":         ["age"],
    "height_cm":   ["Height_cms"],
    "reach_cm":    ["Reach_cms"],
    "stance":      ["Stance"],
    "win_streak":  ["current_win_streak"],
    "lose_streak": ["current_lose_streak"],
    "wins":        ["wins"],
    "win_ko":      ["win_by_KO/TKO"],
    "win_sub":     ["win_by_Submission"],
    "win_dec_maj": ["win_by_Decision_Majority"],
    "win_dec_spl": ["win_by_Decision_Split"],
    "win_dec_uni": ["win_by_Decision_Unanimous"],
}

METHOD_CANDIDATES = ["Finish", "finish", "Method", "method", "win_by", "Win_by"]


def _resolve(df: pd.DataFrame, side: str) -> dict[str, str | None]:
    """Devuelve {concepto: nombre_real_de_columna | None} para el lado R o B."""
    cols = set(df.columns)
    out = {}
    for concept, suffixes in STAT_SUFFIX.items():
        found = None
        for suf in suffixes:
            cand = f"{side}_{suf}"
            if cand in cols:
                found = cand
                break
        out[concept] = found
    return out


def _norm_pct(v: float) -> float:
    """Acepta 0.55 o 55 y devuelve 0.55; clamp a [0,1]."""
    if pd.isna(v):
        return 0.0
    v = float(v)
    if v > 1.5:      # venía en 0-100
        v /= 100.0
    return min(max(v, 0.0), 1.0)


def _side_stats(row, cmap: dict[str, str | None], name: str) -> dict:
    """Construye un dict estilo Fighter para un lado de la pelea."""
    def g(c, default=0.0):
        col = cmap.get(c)
        if col is None or col not in row or pd.isna(row[col]):
            return default
        return row[col]

    wins = max(float(g("wins", 1)), 1.0)
    ko = float(g("win_ko")); sub = float(g("win_sub"))
    dec = float(g("win_dec_maj")) + float(g("win_dec_spl")) + float(g("win_dec_uni"))
    streak = float(g("win_streak")) - float(g("lose_streak"))

    return {
        "name": name,
        "slpm": float(g("slpm")),
        "str_acc": _norm_pct(g("str_acc")),
        "sapm": float(g("sapm")),
        "str_def": round(1.0 - _norm_pct(g("opp_str_pct")), 4),
        "td_avg": float(g("td_avg")),
        "td_acc": _norm_pct(g("td_acc")),
        "td_def": round(1.0 - _norm_pct(g("opp_td_pct")), 4),
        "sub_avg": float(g("sub_avg")),
        "age": float(g("age")),
        "height_cm": float(g("height_cm")),
        "reach_cm": float(g("reach_cm")),
        "stance": str(g("stance", "Orthodox")) or "Orthodox",
        "weight_class": row.get("weight_class", "Lightweight"),
        "streak": streak,
        "days_since_last_fight": 0.0,   # se rellena luego con el historial
        "win_ko_rate": min(ko / wins, 1.0),
        "win_sub_rate": min(sub / wins, 1.0),
        "win_dec_rate": min(dec / wins, 1.0),
        "lost_by_finish_rate": DEFAULT_LOST_BY_FINISH,
    }


def _find_method_col(df: pd.DataFrame) -> str | None:
    for c in METHOD_CANDIDATES:
        if c in df.columns:
            return c
    return None


# --------------------------------------------------------------------------- #
# Stats DEFENSIVOS reales (Str.Def, TD.Def) desde el dataset rajeevw/ufcdata.
# mdabbert no trae los golpes/derribos ABSORBIDOS por el rival, así que sin esto
# Str.Def y TD.Def quedan constantes en el entrenamiento y el modelo NUNCA aprende
# que la defensa (sobre todo la de derribo) gana peleas. rajeevw sí trae
# avg_opp_SIG_STR_pct y avg_opp_TD_pct (ratios 0-1, misma definición que UFCStats),
# así que los inyectamos por nombre de peleador. Cobertura: peleadores activos
# hasta 2021 (la mayoría del histórico); los no cubiertos usan el default.
# --------------------------------------------------------------------------- #
DEFENSE_TABLE = C.DATA_PROCESSED / "defense_stats.csv"


def build_defense_lookup() -> dict[str, dict]:
    """{nombre_lower: {'str_def':.., 'td_def':..}} desde rajeevw. Cachea a CSV."""
    if DEFENSE_TABLE.exists():
        d = pd.read_csv(DEFENSE_TABLE)
        return {r["name"].lower(): {"str_def": r["str_def"], "td_def": r["td_def"]}
                for _, r in d.iterrows()}
    try:
        import kagglehub
        from pathlib import Path
        path = kagglehub.dataset_download("rajeevw/ufcdata")
        raj = pd.read_csv(next(Path(path).glob("data.csv")), low_memory=False)
    except Exception as e:
        print(f"[!] no pude cargar rajeevw para stats defensivos ({e}); uso defaults.")
        return {}

    raj["date"] = pd.to_datetime(raj["date"], errors="coerce")

    def side(pref):
        return raj[[f"{pref}_fighter", "date",
                    f"{pref}_avg_opp_SIG_STR_pct", f"{pref}_avg_opp_TD_pct"]].rename(
            columns={f"{pref}_fighter": "name",
                     f"{pref}_avg_opp_SIG_STR_pct": "osp",
                     f"{pref}_avg_opp_TD_pct": "otp"})

    long = pd.concat([side("R"), side("B")], ignore_index=True)
    long = long.dropna(subset=["osp", "otp"], how="all").sort_values("date")
    latest = long.groupby("name").last()
    latest["str_def"] = (1.0 - latest["osp"]).clip(0, 1).round(4)
    latest["td_def"] = (1.0 - latest["otp"]).clip(0, 1).round(4)
    out = latest[["str_def", "td_def"]].reset_index()
    out.to_csv(DEFENSE_TABLE, index=False)
    print(f"[ok] defense_stats.csv -> {len(out)} peleadores con Str.Def/TD.Def reales")
    return {r["name"].lower(): {"str_def": r["str_def"], "td_def": r["td_def"]}
            for _, r in out.iterrows()}


def load() -> pd.DataFrame:
    df = pd.read_csv(C.DATA_RAW / "kaggle_ufc.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "R_fighter", "B_fighter", "Winner"])
    print(f"[ingest] {len(df)} peleas válidas | columnas: {len(df.columns)}")
    return df


def _days_since_lookup(df: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], float]:
    """Reconstruye el gap (días desde la pelea anterior) por (peleador, fecha)."""
    long = pd.concat([
        df[["R_fighter", "date"]].rename(columns={"R_fighter": "fighter"}),
        df[["B_fighter", "date"]].rename(columns={"B_fighter": "fighter"}),
    ]).dropna().sort_values(["fighter", "date"])
    long["gap"] = long.groupby("fighter")["date"].diff().dt.days.fillna(0.0)
    return {(r.fighter, r.date): float(r.gap) for r in long.itertuples()}


def build_all():
    df = load()
    # CRÍTICO: orden cronológico. El ELO de cada pelea debe reflejar SOLO las
    # peleas anteriores (rating pre-pelea). Sin esto habría data leakage.
    df = df.sort_values("date").reset_index(drop=True)
    rmap = _resolve(df, "R")
    bmap = _resolve(df, "B")

    # aviso de columnas no encontradas (una sola vez, para diagnóstico)
    missing = sorted({k for k, v in {**rmap, **bmap}.items()
                      if (rmap[k] is None or bmap[k] is None)})
    if missing:
        print(f"[!] conceptos sin columna directa (usarán default): {missing}")

    method_col = _find_method_col(df)
    if method_col:
        print(f"[ingest] método por pelea detectado en '{method_col}'")
    else:
        print("[!] sin columna de método por pelea -> el modelo de método se omitirá. "
              "Para entrenarlo usa un dataset con 'Finish' (p.ej. mdabbert/ultimate-ufc-dataset).")

    gap = _days_since_lookup(df)
    defense = build_defense_lookup()   # Str.Def / TD.Def reales por peleador (rajeevw)
    n_def = 0

    # ---- PASE CRONOLÓGICO ÚNICO: ELO pre-pelea + features, sin mirar el futuro ----
    elo = EloSystem()
    rows, fighter_rows = [], []
    for _, row in df.iterrows():
        if row["Winner"] not in ("Red", "Blue"):
            continue  # descarta draws/NC
        a = _side_stats(row, rmap, row["R_fighter"])
        b = _side_stats(row, bmap, row["B_fighter"])
        a["days_since_last_fight"] = gap.get((row["R_fighter"], row["date"]), 0.0)
        b["days_since_last_fight"] = gap.get((row["B_fighter"], row["date"]), 0.0)
        # Inyecta defensa real (si el peleador está en la tabla); si no, deja el default.
        for f in (a, b):
            dd = defense.get(f["name"].lower())
            if dd:
                f["str_def"], f["td_def"] = dd["str_def"], dd["td_def"]
                n_def += 1
        # MODELO COMBINADO: suma control/grappling desde UFCStats, usando solo
        # peleas ANTERIORES a esta fecha (sin leakage). Si hay defensa real
        # medida, pisa la aproximada de rajeevw.
        a = _enriquecer_control(a, row["date"])
        b = _enriquecer_control(b, row["date"])
        wc = row.get("weight_class", "Lightweight")

        # ELO tal como estaba ANTES de esta pelea (información disponible ex-ante).
        ea = elo.get(a["name"], wc)
        eb = elo.get(b["name"], wc)

        y = 1 if row["Winner"] == "Red" else 0
        method = _normalize_method(row[method_col]) if method_col else ""

        # features con antisimetría (A vs B, y espejo B vs A)
        # feature de MERCADO (antisimétrica): P(mercado, gana A) - 0.5.
        # NaN si no hay cuotas: XGBoost maneja NaN nativamente.
        from src.odds import market_edge
        oa, ob = row.get("R_odds"), row.get("B_odds")
        edge = market_edge(oa, ob)
        # odds_a/odds_b y los nombres NO son features (columnas_disponibles usa
        # una lista blanca): viajan para poder calcular ROI real en el backtest
        # de valor. market_edge ya está sin vig y normalizado -> perdió el PAGO,
        # y sin el pago no se puede saber si una apuesta gana dinero.
        #
        # Las 6 cuotas de MÉTODO ({lado} x {KO, SUB, DEC}) son un mercado aparte
        # y mucho más caro (20% de comisión vs 4% del moneyline), pero con un
        # sesgo explotable: el público paga de más por las finalizaciones.
        # Cobertura: 79% de las peleas, desde 2012.
        met = {f"odds_a_{k}": row.get(f"r_{k}_odds") for k in ("ko", "sub", "dec")}
        met |= {f"odds_b_{k}": row.get(f"b_{k}_odds") for k in ("ko", "sub", "dec")}
        met_espejo = {f"odds_a_{k}": met[f"odds_b_{k}"] for k in ("ko", "sub", "dec")}
        met_espejo |= {f"odds_b_{k}": met[f"odds_a_{k}"] for k in ("ko", "sub", "dec")}
        meta = {"date": row["date"], "odds_a": oa, "odds_b": ob,
                "fighter_a": a["name"], "fighter_b": b["name"], **met}
        rows.append({**features_pelea(a, b, ea, eb), "market_edge": edge,
                     **meta, "y": y, "method": method})
        rows.append({**features_pelea(b, a, eb, ea),
                     "market_edge": (-edge if edge == edge else edge),
                     **{**meta, "odds_a": ob, "odds_b": oa,
                        "fighter_a": b["name"], "fighter_b": a["name"],
                        **met_espejo},
                     "y": 1 - y, "method": method})

        fighter_rows += [({**a, "date": row["date"]}), ({**b, "date": row["date"]})]

        # SOLO AHORA actualizamos el ELO con el resultado, para las próximas peleas.
        winner_name = a["name"] if y == 1 else b["name"]
        loser_name = b["name"] if y == 1 else a["name"]
        by_finish = method in ("KO/TKO", "Submission") if method else False
        # Nota graduada según CÓMO ganó (S-DEC vale casi lo mismo que un empate).
        # Usa el texto FINO del dataset, no el normalizado a 3 clases.
        valor = valor_resultado(row[method_col]) if method_col else None
        elo.update(winner_name, loser_name, wc, by_finish, valor=valor)

    # ratings FINALES -> para el fallback de predicción en vivo (card.py._elo).
    # Ahí sí queremos la fuerza ACTUAL del peleador, no la pre-pelea histórica.
    elo.to_frame().to_csv(C.ELO_TABLE, index=False)
    print(f"[ok] elo_ratings.csv -> {C.ELO_TABLE}")

    n_slots = len(rows)  # ~2 lados por pelea contada
    print(f"[ok] defensa real inyectada en {n_def} de {n_slots} slots de peleador "
          f"({100*n_def/max(n_slots,1):.0f}%)")

    feats = pd.DataFrame(rows)

    # ---- calidad de la oposición reciente (últimas 5 peleas de cada uno) ----
    # Se calcula al final, sobre el DataFrame ya armado, porque sale de OTRA
    # fuente (el historial propio de UFCStats, que llega a 1994 y es más profundo
    # que Kaggle). Es leak-free por construcción: oposicion.features() solo mira
    # peleas con fecha ESTRICTAMENTE anterior a la del combate.
    from src import oposicion
    ext = pd.DataFrame([
        oposicion.features(r.fighter_a, r.fighter_b, r.date)
        for r in feats.itertuples(index=False)
    ])
    for c in oposicion.COLUMNAS:
        feats[c] = ext[c].values
    cubiertas = int((feats["opp_elo_diff"] != 0).sum())
    print(f"[ok] calidad de oposición en {cubiertas}/{len(feats)} filas "
          f"({100*cubiertas/max(len(feats),1):.0f}%)")

    # ---- corto aviso (quién entró de reemplazo) ----
    # Sale de Wikipedia (ver src/reemplazos.py). Es info pública ANTES de la
    # pelea, así que no hay leakage.
    from src import reemplazos
    feats["reemplazo_diff"] = [
        reemplazos.flag(r.fighter_a, r.date) - reemplazos.flag(r.fighter_b, r.date)
        for r in feats.itertuples(index=False)
    ]
    n_corto = int((feats["reemplazo_diff"] != 0).sum())
    print(f"[ok] corto aviso marcado en {n_corto}/{len(feats)} filas "
          f"({100*n_corto/max(len(feats),1):.1f}%)")

    feats.to_csv(C.FEATURES_CSV, index=False)
    print(f"[ok] features.csv -> {feats.shape[0]} filas ({feats.shape[1]} cols)")

    # ---- fighters.csv: stats más recientes por peleador ----
    fdf = pd.DataFrame(fighter_rows).sort_values("date")
    latest = fdf.groupby("name", as_index=False).last().drop(columns=["date"])
    latest.to_csv(C.FIGHTERS_CSV, index=False)
    print(f"[ok] fighters.csv -> {len(latest)} peleadores")

    return feats, latest


if __name__ == "__main__":
    build_all()
