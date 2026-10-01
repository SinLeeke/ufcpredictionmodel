"""Pruebas de src/value.py: mercados de método."""
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src import value as V
from src.features import espejo

COLS = ["streak_diff", "fight_finish_potential"]
CAL = {"peso_mercado": 0.95, "peso_modelo": 0.45, "n": 1}
CUOTAS6 = [10.0, 6.2, 4.0, 3.5, 5.5, 4.5]          # A_KO, A_SUB, A_DEC, B_KO, B_SUB, B_DEC


class _ModeloConSesgo:
    """6 clases; favorece a la columna A más allá de lo que dicen las features."""

    def predict_proba(self, X):
        s = X["streak_diff"].to_numpy(dtype=float)
        base = np.array([0.20, 0.08, 0.30, 0.12, 0.06, 0.24])
        filas = []
        for v in s:
            w = base * np.exp(np.array([1, 1, 1, -1, -1, -1]) * 0.3 * v)
            filas.append(w / w.sum())
        return np.array(filas)


def _analizar(feat, cuotas, fn=V.analizar_metodo):
    with mock.patch.object(V, "cargar_modelo_metodo", lambda: (_ModeloConSesgo(), COLS)), \
            mock.patch.object(V, "cargar_calibrador_metodo", lambda: CAL):
        return {o["clase"]: o for o in fn(feat, cuotas)}


class SimetriaDelMetodo(unittest.TestCase):

    def test_6_vias_invariante_al_orden(self):
        # BUG: se predecía en una sola orientación aunque el calibrador de método
        # se ajustó con la predicción simetrizada (backtest_metodo, ESPEJO).
        feat = pd.DataFrame([{"streak_diff": 2.0, "fight_finish_potential": 0.2}])
        ab = _analizar(feat, CUOTAS6)
        ba = _analizar(espejo(feat, COLS), CUOTAS6[3:] + CUOTAS6[:3])
        lado = {"A": "B", "B": "A"}
        for clase, o in ab.items():
            otra = ba[lado[clase[0]] + clase[1:]]
            self.assertAlmostEqual(o["p_modelo"], otra["p_modelo"], places=9, msg=clase)
            self.assertAlmostEqual(o["p_final"], otra["p_final"], places=9, msg=clase)

    def test_5_vias_invariante_al_orden(self):
        feat = pd.DataFrame([{"streak_diff": 2.0, "fight_finish_potential": 0.2}])
        c4 = [2.2, 3.0, 2.9, 8.0]                          # A_FIN, A_DEC, B_FIN, B_DEC
        ab = _analizar(feat, c4, V.analizar_metodo5)
        ba = _analizar(espejo(feat, COLS), c4[2:] + c4[:2], V.analizar_metodo5)
        self.assertAlmostEqual(ab["A_DEC"]["p_final"], ba["B_DEC"]["p_final"], places=9)
        self.assertAlmostEqual(ab["A_FIN"]["p_modelo"], ba["B_FIN"]["p_modelo"], places=9)


class CalibradorDeGanador(unittest.TestCase):

    def test_la_mezcla_no_favorece_a_la_columna_a(self):
        # BUG: el intercepto (+0,076) aprendía que en el dataset la esquina roja
        # gana más de lo que dice el mercado. Al predecir, ese +1,9 pts se lo
        # llevaba quien estuviera en la columna A del CSV, sea o no la roja.
        rng = np.random.default_rng(0)
        pm = rng.uniform(0.2, 0.8, 4000)
        pmod = np.clip(pm + rng.normal(0, 0.08, 4000), 0.05, 0.95)
        y = (rng.uniform(size=4000) < np.clip(pm + 0.03, 0, 1)).astype(int)   # "esquina roja"
        cal = V.ajustar_calibrador(pm, pmod, y, guardar=False)
        for a, b in ((0.5, 0.5), (0.62, 0.55), (0.30, 0.40)):
            self.assertAlmostEqual(V.combinar(a, b, cal), 1 - V.combinar(1 - a, 1 - b, cal), places=9)


if __name__ == "__main__":
    unittest.main()
