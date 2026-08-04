"""
evaluar_modelo.py
Prueba el modelo contra peleas REALES que nunca vio, para saber si sirve.

Cómo funciona: carga models/winner_xgb_split.pkl — el modelo del split temporal,
entrenado SOLO con peleas hasta 2024 — y le pide predicciones de 2025-2026. Como
esos resultados ya ocurrieron y el modelo no los vio, se puede contar cuántas
acertó de verdad.

  * OJO con el otro .pkl: models/winner_xgb.pkl es el de PRODUCCIÓN y se reentrena
    con todo el historial, 2025-2026 incluidos. Evaluarlo acá daría ~80% de
    acierto, pero sería preguntarle por peleas que ya tenía estudiadas. Por eso
    este script usa el otro. Ambos los deja train_model.py.

Tres cosas que responde:

  1. ACIERTO      -> de cada 100 peleas, cuántas acertó.
  2. CALIBRACIÓN  -> cuando dice "70%", ¿gana el 70% de las veces? Esto es lo
                     que importa para apostar: un modelo puede acertar poco pero
                     tener probabilidades honestas, o acertar y ser mentiroso.
  3. POR CONFIANZA-> ¿acierta más cuando está seguro? Si sus favoritos claros
                     (>70%) aciertan mucho más que los parejos, conviene apostar
                     solo esos.

Uso:
    python evaluar_modelo.py
    # requiere haber corrido antes:  python train_model.py
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

import config as C
from src.features import columnas_disponibles


def cargar():
    df = pd.read_csv(C.FEATURES_CSV)
    df["date"] = pd.to_datetime(df["date"])
    filas = df[df["date"] >= C.TEST_START_DATE].reset_index(drop=True)
    if filas.empty:
        raise SystemExit("No hay peleas en el periodo de prueba. Revisa config.TEST_START_DATE.")

    # features.csv duplica cada pelea: fila A-vs-B y su espejo B-vs-A, siempre
    # adyacentes. Acá se usan LAS DOS y se promedian (ver main), así que hay que
    # comprobar que el emparejamiento es el que se cree.
    a, b = filas["fighter_a"].values, filas["fighter_b"].values
    if len(filas) % 2 or not ((a[::2] == b[1::2]).all() and (b[::2] == a[1::2]).all()):
        raise SystemExit(
            "Las filas de features.csv no vienen en pares espejo adyacentes.\n"
            "Regenera el dataset:  python -m src.scraper"
        )

    if not C.WINNER_MODEL_SPLIT.exists():
        raise SystemExit(
            f"No existe {C.WINNER_MODEL_SPLIT}.\n"
            "Es el modelo de medición (entrenado solo hasta "
            f"{C.TRAIN_END_DATE}). Genéralo:  python train_model.py"
        )
    with open(C.WINNER_MODEL_SPLIT, "rb") as fh:
        modelo = pickle.load(fh)
    return filas, modelo


def main():
    filas, modelo = cargar()
    cols = columnas_disponibles(filas)
    p_filas = modelo.predict_proba(filas[cols])[:, 1]

    # Una fila por PELEA, no por orientación. XGBoost no es perfectamente
    # antisimétrico (predecir "A vs B" y "B vs A" no da exactamente
    # probabilidades complementarias), así que se promedian las dos: es la
    # estimación más estable y ninguna métrica de acá depende ya de qué peleador
    # quedó como 'A' en el CSV. Importa porque el dataset no lista al azar: en la
    # orientación directa gana A el ~56% de las veces, no el 50%, y quedarse solo
    # con esas filas movía el acierto 1,3 puntos según qué mitad se tomara
    # (66,2% directa vs 67,5% espejo; simetrizado 67,0%).
    test = filas.iloc[::2].reset_index(drop=True)
    p = (p_filas[::2] + (1.0 - p_filas[1::2])) / 2.0
    y = test["y"].values

    # El modelo predice P(gana A). La "apuesta" es al favorito de cada pelea.
    prob_fav = np.where(p >= 0.5, p, 1 - p)
    acerto = np.where(p >= 0.5, y == 1, y == 0)

    print("=" * 62)
    print(f"  PRUEBA SOBRE PELEAS REALES ({test.date.min():%b-%Y} a {test.date.max():%b-%Y})")
    print("=" * 62)
    print(f"  Modelo           : {C.WINNER_MODEL_SPLIT.name} (entrenado hasta {C.TRAIN_END_DATE})")
    print(f"  Peleas evaluadas : {len(test)}")
    print(f"  Acertadas        : {acerto.sum()}  ({acerto.mean()*100:.1f}%)")
    print(f"  Falladas         : {(~acerto).sum()}")
    print(f"  Referencia: acertar al azar = 50%")
    print()

    # --- Calibración: ¿el 70% gana el 70%? ---
    print("  CALIBRACIÓN — ¿son honestas las probabilidades?")
    print(f"  {'cuando dice':16}{'peleas':>8}{'ganó de verdad':>17}{'veredicto':>14}")
    print("  " + "-" * 56)
    for lo, hi in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65),
                   (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)]:
        m = (prob_fav >= lo) & (prob_fav < hi)
        if m.sum() < 5:
            continue
        real = acerto[m].mean()
        esperado = prob_fav[m].mean()
        dif = real - esperado
        v = "realista" if abs(dif) < 0.06 else ("optimista" if dif < 0 else "conservador")
        print(f"  {lo*100:.0f}-{hi*100:.0f}%{'':9}{m.sum():>8}{real*100:>15.0f}%{v:>14}")
    print()

    # --- ¿Conviene apostar solo a los favoritos claros? ---
    print("  SI SOLO APUESTAS CUANDO EL MODELO ESTÁ SEGURO")
    print(f"  {'umbral':14}{'peleas':>8}{'acierto':>10}")
    print("  " + "-" * 32)
    for u in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
        m = prob_fav >= u
        if m.sum() < 5:
            continue
        print(f"  desde {u*100:.0f}%{'':6}{m.sum():>8}{acerto[m].mean()*100:>9.0f}%")
    print()

    brier = float(np.mean((p - y) ** 2))
    print(f"  Brier Score: {brier:.3f}   (más bajo = mejor; 0.25 = tirar una moneda)")
    print("=" * 62)
    print("  Nota: acertar 60-65% en MMA ya es bueno, y esto es fuera de muestra:")
    print("  el modelo cerró en 2024 y estas peleas son posteriores. Si alguna vez")
    print("  ves 80% acá, es que se evaluó un modelo que ya había visto estas")
    print("  peleas — nadie predice este deporte así: una finalización cambia todo")
    print("  en 3 segundos.")


if __name__ == "__main__":
    main()
