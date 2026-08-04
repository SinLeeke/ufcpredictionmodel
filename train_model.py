"""
train_model.py
Entrena DOS modelos XGBoost desde data/processed/features.csv y los guarda en models/:

  1) models/winner_xgb.pkl  -> predice al GANADOR   (columna binaria `y`, 1 = gana A)
  2) models/method_xgb.pkl  -> predice el MÉTODO     (columna `method`: KO/TKO, Submission, Decision)

Por qué XGBoost en vez del heurístico manual:
  * El heurístico `_heuristic_probability` de predict.py es una combinación lineal con
    pesos puestos a mano (sobrevalora el historial de KO, casi ignora el nivel del rival
    vía ELO). XGBoost descubre SOLO los pesos y las INTERACCIONES no lineales reales
    (p. ej. cómo el diferencial de ELO modula la efectividad de golpeo).
  * `.predict_proba()` de XGBoost entrega probabilidades reales y razonablemente
    calibradas -> la simulación Monte Carlo pasa a tener validez estadística, en vez
    de partir de una estimación a ojo.

IMPORTANTE — el split NO es aleatorio, es CRONOLÓGICO (temporal). Motivo:
  * features.csv duplica cada pelea (fila A-vs-B y su espejo B-vs-A). Un split aleatorio
    pondría una fila en train y su espejo en test = la MISMA pelea en ambos lados -> leakage.
  * Además, un split aleatorio mezcla años y mete peleas futuras en el entrenamiento.
  El split temporal (train <= 2024, test >= 2025) evita ambos problemas. Las dos filas
  espejo de una pelea comparten fecha, así que siempre caen del mismo lado.

Uso:
    python train_model.py
    # requiere que exista features.csv:  python -m src.scraper   (lo genera)
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score, brier_score_loss

from xgboost import XGBClassifier

import config as C
from src.features import FEATURE_COLUMNS, columnas_disponibles, probabilidades_metodo


# --------------------------------------------------------------------------- #
# Carga y split temporal
# --------------------------------------------------------------------------- #
def load_features() -> pd.DataFrame:
    if not C.FEATURES_CSV.exists():
        raise SystemExit(
            f"No existe {C.FEATURES_CSV}.\n"
            "Genera las features primero:  python -m src.scraper"
        )
    df = pd.read_csv(C.FEATURES_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _ventana(df: pd.DataFrame, hasta) -> pd.DataFrame:
    """Recorta a los últimos C.TRAIN_WINDOW_YEARS años antes de `hasta`."""
    hasta = pd.Timestamp(hasta)
    sub = df[df["date"] <= hasta]
    if C.TRAIN_WINDOW_YEARS:
        desde = hasta - pd.DateOffset(years=C.TRAIN_WINDOW_YEARS)
        sub = sub[sub["date"] >= desde]
    return sub


def temporal_split(df: pd.DataFrame):
    """Train <= TRAIN_END_DATE (recortado a la ventana), Test >= TEST_START_DATE."""
    train = _ventana(df, C.TRAIN_END_DATE)
    test = df[df["date"] >= C.TEST_START_DATE]
    v = f", ventana {C.TRAIN_WINDOW_YEARS} años" if C.TRAIN_WINDOW_YEARS else ""
    print(f"[split temporal] train={len(train)}  test={len(test)}  "
          f"(corte {C.TRAIN_END_DATE} / {C.TEST_START_DATE}{v})")
    if len(test) == 0:
        print("[!] test vacío: el dataset no llega al periodo de test. "
              "Ajusta TRAIN_END_DATE/TEST_START_DATE en config.py.")
    return train, test


# --------------------------------------------------------------------------- #
# 1) Modelo de GANADOR (binario)
# --------------------------------------------------------------------------- #
def train_winner(train: pd.DataFrame, test: pd.DataFrame) -> XGBClassifier:
    cols = columnas_disponibles(train)      # amplía si el dataset trae grappling
    X_tr, y_tr = train[cols], train["y"]
    X_te, y_te = test[cols], test["y"]
    print(f"  features usadas: {len(cols)}")

    model = XGBClassifier(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        eval_metric="logloss",
        random_state=C.RANDOM_STATE,
    )
    model.fit(X_tr, y_tr)

    print("\n=== GANADOR (XGBoost binario) ===")
    if len(X_te):
        proba = model.predict_proba(X_te)[:, 1]
        pred = (proba >= 0.5).astype(int)
        print(f"  Accuracy : {accuracy_score(y_te, pred):.3f}")
        print(f"  Log loss : {log_loss(y_te, proba):.3f}")
        # Extras útiles para calibración (no pedidos, pero baratos):
        if y_te.nunique() > 1:
            print(f"  AUC-ROC  : {roc_auc_score(y_te, proba):.3f}")
            print(f"  Brier    : {brier_score_loss(y_te, proba):.3f}")
        print(f"  (n test = {len(y_te)})")
    else:
        print("  (sin test set para evaluar)")

    with open(C.WINNER_MODEL, "wb") as fh:
        pickle.dump(model, fh)
    print(f"  -> guardado en {C.WINNER_MODEL}")
    return model


# --------------------------------------------------------------------------- #
# 2) Modelo de MÉTODO (multiclase)
# --------------------------------------------------------------------------- #
def train_method(train: pd.DataFrame, test: pd.DataFrame) -> XGBClassifier | None:
    cls_to_idx = {c: i for i, c in enumerate(C.METHOD_CLASSES)}  # KO/TKO=0, Sub=1, Dec=2

    # El método (KO/Sub/Dec) es una propiedad de la pelea, INVARIANTE a la orientación
    # A/B. Entrenamos con TODAS las filas (ambas orientaciones): así el modelo es robusto
    # a que en producción 'A' sea un peleador cualquiera (no necesariamente el favorito).
    # Sin las features de oposición (medido: le empeoran el KO-vs-sub, ver
    # features.columnas_disponibles) y sin corto aviso: que un peleador entre de
    # reemplazo cambia SI gana, no CÓMO termina la pelea, y no está validado ahí.
    cols = columnas_disponibles(train, con_oposicion=False, con_corto=False)

    def prep(df):
        d = df[df["method"].isin(cls_to_idx)]
        return d[cols], d["method"].map(cls_to_idx)

    X_tr, y_tr = prep(train)
    X_te, y_te = prep(test)

    if y_tr.nunique() < 2:
        print("\n[!] menos de 2 clases de método en train -> se omite el modelo de método.")
        return None

    model = XGBClassifier(
        objective="multi:softprob",
        num_class=len(C.METHOD_CLASSES),
        n_estimators=300,
        max_depth=3,
        learning_rate=0.04,
        subsample=0.85,
        colsample_bytree=0.85,
        eval_metric="mlogloss",
        random_state=C.RANDOM_STATE,
    )
    # SIN BALANCEO DE CLASES — y esto NO es un descuido, es el arreglo de un bug.
    #
    # Antes se pesaba cada ejemplo por el inverso de la frecuencia de su clase
    # para que las finalizaciones "contaran tanto" como las decisiones. Eso
    # mejora el recall de KO/sumisión, pero DESTRUYE la probabilidad, que es lo
    # único que este modelo produce (alimenta el Monte Carlo y la tabla de
    # método). Medido en el test 2025+ (1.256 peleas):
    #
    #                          balanceado      sin balancear     realidad
    #   dice "Submission"          32,0%            17,8%          16,4%
    #   dice "Decision"            34,1%            51,1%          50,6%
    #   log loss                   1,033            0,950
    #   accuracy                   0,488            0,527
    #
    # O sea: el balanceado anunciaba el DOBLE de sumisiones de las que ocurren,
    # y su log loss (1,033) era PEOR que no mirar nada y cantar las tasas base
    # (1,008). Por eso "el predictor de método no acertaba": no le faltaba
    # información, reportaba mal la que tenía.
    #
    # Lo que se pierde al quitar el balanceo es solo el argmax repartido: ahora
    # "Decisión" gana casi siempre, que es sencillamente la verdad (51% de las
    # peleas). La señal para detectar peleas finalizables NO se pierde y se
    # muestra como LIFT sobre la tasa base en card.py. Discriminación medida,
    # prácticamente idéntica entre ambos: AUC finalización-vs-decisión 0,635 vs
    # 0,639; AUC KO-vs-sumisión (dado que finaliza) 0,753 vs 0,749.
    model.fit(X_tr, y_tr)

    print("\n=== MÉTODO (XGBoost multiclase: KO/TKO, Submission, Decision) ===")
    if len(X_te):
        # Simetrizada: el método no depende de quién esté en la columna A.
        proba = probabilidades_metodo(model, X_te, cols)
        pred = proba.argmax(axis=1)
        print(f"  Accuracy : {accuracy_score(y_te, pred):.3f}")
        print(f"  Log loss : {log_loss(y_te, proba, labels=list(range(len(C.METHOD_CLASSES)))):.3f}")
        # El log loss de cantar las tasas base del train. Si el modelo no le gana
        # a ESTO, no está aportando nada aunque su accuracy se vea decente.
        frec = y_tr.value_counts(normalize=True).sort_index()
        base = np.tile(frec.values, (len(y_te), 1))
        ll_base = log_loss(y_te, base, labels=list(range(len(C.METHOD_CLASSES))))
        print(f"  Log loss de la tasa base (a batir): {ll_base:.3f}")
        print(f"  Calibración (lo que dice vs lo que pasa):")
        for i, c in enumerate(C.METHOD_CLASSES):
            print(f"    {c:12} dice {proba[:, i].mean()*100:5.1f}%  "
                  f"ocurre {(y_te == i).mean()*100:5.1f}%")
        print(f"  (n test = {len(y_te)})")
    else:
        print("  (sin test set para evaluar)")

    with open(C.METHOD_MODEL, "wb") as fh:
        pickle.dump(model, fh)
    print(f"  -> guardado en {C.METHOD_MODEL}")
    return model


# --------------------------------------------------------------------------- #
# 3) Modelos de PRODUCCIÓN (los que realmente predicen)
# --------------------------------------------------------------------------- #
def entrenar_produccion(df: pd.DataFrame) -> None:
    """
    Reentrena con TODO lo disponible hasta hoy y pisa los .pkl.

    Por qué existe: los modelos de arriba se entrenan hasta TRAIN_END_DATE para
    dejar 2025+ como test y poder MEDIR honestamente. Pero guardar ESE modelo
    para predecir tira a la basura las peleas más recientes, que son justo las
    más informativas — eran 628 peleas desperdiciadas.

    La práctica correcta es separar las dos cosas: se mide con el split (arriba)
    y se predice con un modelo entrenado con todo (acá). El número que reporta
    el split sigue siendo el honesto; este modelo solo puede ser mejor, porque
    ve más datos recientes.

    Se aplica la MISMA ventana temporal (C.TRAIN_WINDOW_YEARS): validado en 5
    períodos, quedarse con los últimos 5 años le gana a usar todo el historial
    en 4 de 5 (+0,0117 de AUC de media).
    """
    fin = df["date"].max()
    full = _ventana(df, fin)
    cols_w = columnas_disponibles(full)
    cols_m = columnas_disponibles(full, con_oposicion=False, con_corto=False)

    print("\n=== MODELOS DE PRODUCCIÓN (entrenados con TODO hasta hoy) ===")
    print(f"  {len(full)} filas  ({full.date.min():%Y-%m-%d} a {full.date.max():%Y-%m-%d})")
    print(f"  +{len(full) - len(_ventana(df, C.TRAIN_END_DATE))} filas más que el modelo de medición")

    w = XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.85,
        colsample_bytree=0.85, reg_lambda=1.5, eval_metric="logloss",
        random_state=C.RANDOM_STATE,
    ).fit(full[cols_w], full["y"])
    with open(C.WINNER_MODEL, "wb") as fh:
        pickle.dump(w, fh)

    cls_to_idx = {c: i for i, c in enumerate(C.METHOD_CLASSES)}
    d = full[full["method"].isin(cls_to_idx)]
    m = XGBClassifier(
        objective="multi:softprob", num_class=len(C.METHOD_CLASSES),
        n_estimators=300, max_depth=3, learning_rate=0.04, subsample=0.85,
        colsample_bytree=0.85, eval_metric="mlogloss", random_state=C.RANDOM_STATE,
    ).fit(d[cols_m], d["method"].map(cls_to_idx))
    with open(C.METHOD_MODEL, "wb") as fh:
        pickle.dump(m, fh)

    print(f"  -> {C.WINNER_MODEL.name} y {C.METHOD_MODEL.name} reescritos")
    print("     (las métricas de arriba siguen siendo las válidas para juzgarlos)")


def main():
    df = load_features()
    train, test = temporal_split(df)
    train_winner(train, test)
    train_method(train, test)
    # Los .pkl finales son los de producción, no los de medición.
    entrenar_produccion(df)
    print("\n[ok] Listo. card.py cargará estos .pkl automáticamente (load_models).")


if __name__ == "__main__":
    main()
