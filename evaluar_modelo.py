"""
evaluar_modelo.py
Prueba el modelo contra peleas REALES que nunca vio, para saber si sirve.

Cómo funciona: el modelo se entrena solo con peleas hasta 2024 y aquí se le
piden predicciones de 2025-2026. Como esos resultados ya ocurrieron, se puede
contar cuántas acertó de verdad.

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
    # features.csv duplica cada pelea (A-vs-B y su espejo B-vs-A). Para contar
    # peleas de verdad se toma una sola orientación: una fila de cada par.
    df = df.iloc[::2].reset_index(drop=True)
    test = df[df["date"] >= C.TEST_START_DATE].copy()
    if test.empty:
        raise SystemExit("No hay peleas en el periodo de prueba. Revisa config.TEST_START_DATE.")
    with open(C.WINNER_MODEL, "rb") as fh:
        modelo = pickle.load(fh)
    return test, modelo


def main():
    test, modelo = cargar()
    cols = columnas_disponibles(test)
    p = modelo.predict_proba(test[cols])[:, 1]
    y = test["y"].values

    # El modelo predice P(gana A). La "apuesta" es al favorito de cada pelea.
    prob_fav = np.where(p >= 0.5, p, 1 - p)
    acerto = np.where(p >= 0.5, y == 1, y == 0)

    print("=" * 62)
    print(f"  PRUEBA SOBRE PELEAS REALES ({test.date.min():%b-%Y} a {test.date.max():%b-%Y})")
    print("=" * 62)
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
    print("  Nota: acertar 60-65% en MMA ya es bueno. Nadie predice este deporte")
    print("  con 80% — una finalización cambia todo en 3 segundos.")


if __name__ == "__main__":
    main()
