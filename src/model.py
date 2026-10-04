"""
model.py
FASE 3 — Arquitectura del modelo y entrenamiento.

Dos modelos:
  * winner_model  -> clasificación binaria (¿gana A?). Baseline: Regresión
    Logística. Principal: XGBoost (captura interacciones no lineales de estilos).
  * method_model  -> clasificación multiclase (KO/TKO, Submission, Decision).

Validación: TIME-BASED SPLIT. Entrenamos con peleas <= TRAIN_END_DATE y
testeamos con >= TEST_START_DATE. Nunca un split aleatorio: mezclaría el futuro
con el pasado y produciría data leakage (métricas infladas e irreales).

Métricas:
  * Accuracy      -> % de aciertos del ganador.
  * AUC-ROC       -> capacidad de ranking de las probabilidades.
  * Brier Score   -> CALIBRACIÓN. Es lo que más importa si vas a usar las
    probabilidades para comparar contra cuotas: mide si un "70%" gana de verdad
    ~70% de las veces. Más bajo = mejor.
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C
from src import storage as DB
from src.features import FEATURE_COLUMNS


# --------------------------------------------------------------------------- #
# Split temporal
# --------------------------------------------------------------------------- #
def time_based_split(df: pd.DataFrame):
    """Devuelve (train, test) usando las fechas de corte de config.py."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    train = df[df["date"] <= C.TRAIN_END_DATE]
    test = df[df["date"] >= C.TEST_START_DATE]
    print(f"[split] train={len(train)}  test={len(test)}  "
          f"(corte {C.TRAIN_END_DATE} / {C.TEST_START_DATE})")
    return train, test


# --------------------------------------------------------------------------- #
# Modelo de ganador
# --------------------------------------------------------------------------- #
def train_winner_model(df: pd.DataFrame):
    """Entrena baseline logístico y XGBoost; reporta métricas; guarda el mejor."""
    train, test = time_based_split(df)
    X_tr, y_tr = train[FEATURE_COLUMNS], train["y"]
    X_te, y_te = test[FEATURE_COLUMNS], test["y"]

    # ---- Baseline: Regresión Logística (con estandarizado) ----
    baseline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=C.RANDOM_STATE)),
    ]).fit(X_tr, y_tr)
    _report("LogReg (baseline)", baseline, X_te, y_te)

    # ---- Principal: XGBoost ----
    if HAS_XGB:
        xgb = XGBClassifier(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.03,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.5,
            eval_metric="logloss",
            random_state=C.RANDOM_STATE,
        ).fit(X_tr, y_tr)
        _report("XGBoost (principal)", xgb, X_te, y_te)
        best = xgb
    else:
        print("[!] xgboost no instalado -> uso el baseline como modelo final.")
        best = baseline

    with DB.open_file(C.WINNER_MODEL, "wb") as fh:
        pickle.dump(best, fh)
    print(f"[ok] modelo de ganador -> {C.WINNER_MODEL}")
    return best


def _report(name: str, model, X_te, y_te):
    """Imprime Accuracy, AUC-ROC y Brier Score sobre el set de test."""
    if len(X_te) == 0:
        print(f"[{name}] set de test vacío (ajusta las fechas de corte).")
        return
    proba = model.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    acc = accuracy_score(y_te, pred)
    auc = roc_auc_score(y_te, proba) if y_te.nunique() > 1 else float("nan")
    brier = brier_score_loss(y_te, proba)
    print(f"[{name:22}] Acc={acc:.3f}  AUC={auc:.3f}  Brier={brier:.3f}  (n={len(y_te)})")


# --------------------------------------------------------------------------- #
# Modelo de método de victoria (multiclase)
# --------------------------------------------------------------------------- #
def train_method_model(df: pd.DataFrame):
    """
    Predice CÓMO termina la pelea (KO/TKO, Submission, Decision) condicionado a
    las features del duelo. Se entrena solo con las filas 'directas' donde y=1
    (perspectiva del ganador) para que 'method' sea coherente.
    """
    winners = df[df["y"] == 1].copy()
    winners = winners[winners["method"].astype(str).str.len() > 0]
    if winners["method"].nunique() < 2:
        print("[!] el dataset no tiene método por pelea (o una sola clase) -> "
              "se omite el modelo de método. predict.py usará el fallback.")
        return None
    winners["date"] = pd.to_datetime(winners["date"])
    train = winners[winners["date"] <= C.TRAIN_END_DATE]
    test = winners[winners["date"] >= C.TEST_START_DATE]

    cls_to_idx = {c: i for i, c in enumerate(C.METHOD_CLASSES)}
    y_tr = train["method"].map(cls_to_idx)
    y_te = test["method"].map(cls_to_idx)

    if not HAS_XGB:
        print("[!] xgboost no instalado -> se omite el modelo de método.")
        return None

    method_model = XGBClassifier(
        objective="multi:softprob",
        num_class=len(C.METHOD_CLASSES),
        n_estimators=300,
        max_depth=3,
        learning_rate=0.04,
        subsample=0.85,
        eval_metric="mlogloss",
        random_state=C.RANDOM_STATE,
    ).fit(train[FEATURE_COLUMNS], y_tr)

    if len(test) > 0:
        ll = log_loss(y_te, method_model.predict_proba(test[FEATURE_COLUMNS]),
                      labels=list(range(len(C.METHOD_CLASSES))))
        print(f"[method model] log-loss (test) = {ll:.3f}")

    with DB.open_file(C.METHOD_MODEL, "wb") as fh:
        pickle.dump(method_model, fh)
    print(f"[ok] modelo de método -> {C.METHOD_MODEL}")
    return method_model


def load_models():
    """Carga (winner, method) desde disco. method puede ser None."""
    with DB.open_file(C.WINNER_MODEL, "rb") as fh:
        winner = pickle.load(fh)
    method = None
    if DB.exists(C.METHOD_MODEL):
        with DB.open_file(C.METHOD_MODEL, "rb") as fh:
            method = pickle.load(fh)
    return winner, method


if __name__ == "__main__":
    if not DB.exists(C.FEATURES_CSV):
        raise SystemExit(
            "No existe features.csv. Primero corre la ingesta:\n"
            "    python -m src.kaggle_ingest\n"
            "(genera data/processed/features.csv y fighters.csv)"
        )
    feats = DB.read_csv(C.FEATURES_CSV)
    train_winner_model(feats)
    train_method_model(feats)
