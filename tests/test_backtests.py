"""
Pruebas de los walk-forward que generan los calibradores y el modelo de 6 vías:
que entrenen con la misma ventana de 5 años que el modelo de producción.

Medido (2021-2026): con la ventana, el modelo de 6 clases mejora el log loss en
5/6 (-0,0144) y el de ganador del walk-forward en 4/6 (-0,0045). Además el
dataset de Kaggle cambió de escala en 2019 (golpes POR PELEA hasta 2018, POR
MINUTO desde 2020): entrenar con todo mezclaba las dos.
"""
import unittest
from unittest import mock

import numpy as np
import pandas as pd

import config as C
from modelado import backtest_metodo as BM, backtest_valor as BV
from src.features import columnas_disponibles

COLS = columnas_disponibles(pd.DataFrame(columns=[
    "ctrl_diff", "age_diff", "reach_diff", "height_diff", "streak_diff", "days_since_last_fight_diff",
    "elo_diff", "striking_efficiency_diff", "grappling_efficiency_diff", "sub_threat_diff",
    "finish_index_diff", "fight_finish_potential", "stance_southpaw_edge"]))


def _dataset(desde=2010, hasta=2022):
    filas = []
    for anio in range(desde, hasta + 1):
        # 60 peleas por año en pares espejo: con la ventana de 5 años quedan más
        # de las 500 filas que los walk-forward exigen para entrenar.
        for k in range(60):
            fecha = pd.Timestamp(f"{anio}-03-01") + pd.Timedelta(days=k * 4)
            for y in (1, 0):
                filas.append({**{c: 0.0 for c in COLS}, "date": fecha, "y": y,
                              "method": "Decision", "odds_a": -150, "odds_b": 130,
                              **{f"odds_{l}_{m}": 500 for l in "ab" for m in ("ko", "sub", "dec")}})
    df = pd.DataFrame(filas)
    df["y6"] = np.where(df.y == 1, 2, 5)
    return df


class _Grabadora:
    def __init__(self, k):
        self.k, self.vistos = k, []

    def fit(self, X, y):
        self.vistos.append(X.index)
        return self

    def predict_proba(self, X):
        return np.full((len(X), self.k), 1.0 / self.k)


class Ventana(unittest.TestCase):

    def _min_fecha_entrenada(self, modulo, k, df, **kw):
        grab = _Grabadora(k)
        with mock.patch.object(modulo, "_modelo", lambda: grab), \
                mock.patch("builtins.print"):
            modulo.predicciones_walk_forward(df, 2022, **kw)
        return df.loc[grab.vistos[-1], "date"].min()

    def test_walk_forward_de_ganador_usa_la_ventana(self):
        df = _dataset()
        self.assertGreaterEqual(self._min_fecha_entrenada(BV, 2, df),
                                pd.Timestamp("2021-12-31") - pd.DateOffset(years=C.TRAIN_WINDOW_YEARS))

    def test_walk_forward_de_metodo_usa_la_ventana(self):
        df = _dataset()
        self.assertGreaterEqual(self._min_fecha_entrenada(BM, 6, df),
                                pd.Timestamp("2021-12-31") - pd.DateOffset(years=C.TRAIN_WINDOW_YEARS))

    def test_modelo_final_de_6_vias_usa_la_ventana(self):
        df = _dataset()
        grab = _Grabadora(6)
        with mock.patch.object(BM, "_modelo", lambda: grab):
            BM.entrenar_modelo6(df)
        self.assertGreaterEqual(df.loc[grab.vistos[-1], "date"].min(),
                                df.date.max() - pd.DateOffset(years=C.TRAIN_WINDOW_YEARS))


if __name__ == "__main__":
    unittest.main()
