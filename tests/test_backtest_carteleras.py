"""
Pruebas de modelado/backtest_carteleras.py: que el backtest no vea el resultado.

Medido antes del arreglo, en 203 peleas con cuota (jun-2025 a mar-2026): el
modelo "acertaba" 76-78% cuando fuera de muestra acierta 67%. Tres fugas:
UFCStats pone al GANADOR primero y la probabilidad salía orientada a él; se
usaba la tabla de ELO FINAL (que ya incluye la pelea evaluada: el ganador tenía
más ELO el 72% de las veces contra 58% con el ELO pre-pelea); y se evaluaba con
el modelo de producción, que ya había entrenado con esas peleas.
"""
import unittest

import pandas as pd

import config as C
from modelado import backtest_carteleras as BT
from src import kaggle_ingest as KI


def _kaggle(*peleas):
    """DataFrame con el formato mínimo de kaggle_ufc.csv."""
    return pd.DataFrame([{"date": pd.Timestamp(f), "R_fighter": r, "B_fighter": b, "Winner": w,
                          "weight_class": "Lightweight", "finish": m}
                         for f, r, b, w, m in peleas])


class EloALaFecha(unittest.TestCase):

    def test_solo_cuentan_las_peleas_estrictamente_anteriores(self):
        df = _kaggle(("2024-01-01", "Ana", "Bea", "Red", "KO/TKO"),
                     ("2024-06-01", "Ana", "Cris", "Blue", "U-DEC"))
        antes = KI.tabla_elo(hasta="2024-01-01", df=df)
        self.assertTrue(antes.empty)                              # ni la del mismo día
        medio = KI.tabla_elo(hasta="2024-06-01", df=df).set_index("fighter")["elo"]
        self.assertGreater(medio["Ana"], C.ELO_BASE)
        self.assertNotIn("Cris", medio)
        final = KI.tabla_elo(df=df).set_index("fighter")["elo"]
        self.assertLess(final["Ana"], medio["Ana"])

    @unittest.skipUnless((C.DATA_RAW / "kaggle_ufc.csv").exists() and C.ELO_TABLE.exists(),
                         "hace falta la base construida")
    def test_sin_corte_reproduce_la_tabla_de_produccion(self):
        # Misma regla que kaggle_ingest.build_all: si alguien cambia una y no la
        # otra, el backtest dejaría de medir el ELO que se usa al predecir.
        nueva = KI.tabla_elo().set_index(["weight_class", "fighter"])["elo"]
        prod = pd.read_csv(C.ELO_TABLE).set_index(["weight_class", "fighter"])["elo"]
        self.assertEqual(len(nueva), len(prod))
        self.assertLess((nueva - prod.reindex(nueva.index)).abs().max(), 1e-6)


class Orientacion(unittest.TestCase):

    def test_el_ganador_no_va_siempre_primero(self):
        r = pd.Series({"fighter_a": "Zed Zulu", "fighter_b": "Abe Alpha", "winner": "Zed Zulu"})
        self.assertEqual(BT._orientar(r, rojo=None), ("Abe Alpha", "Zed Zulu"))
        self.assertEqual(BT._orientar(r, rojo="abe alpha"), ("Abe Alpha", "Zed Zulu"))
        self.assertEqual(BT._orientar(r, rojo="zed zulu"), ("Zed Zulu", "Abe Alpha"))


class ModeloFueraDeMuestra(unittest.TestCase):

    def test_cada_evento_con_un_modelo_que_no_lo_vio(self):
        fin_prod = pd.Timestamp("2026-03-28")
        self.assertEqual(BT._modelo_para(pd.Timestamp("2026-05-01"), fin_prod), "produccion")
        self.assertEqual(BT._modelo_para(pd.Timestamp("2025-06-01"), fin_prod), "medicion")
        self.assertIsNone(BT._modelo_para(pd.Timestamp("2024-06-01"), fin_prod))


if __name__ == "__main__":
    unittest.main()
