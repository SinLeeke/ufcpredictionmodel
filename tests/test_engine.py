"""Pruebas de webui/engine.py: el refresco EN VIVO de la línea de ganador."""
import unittest
from pathlib import Path
from unittest import mock

from src import value as V
from src.simulate import monte_carlo
from webui import engine as E, parlay as P

# Calibrador fijo para no depender de models/ (no se versiona).
CAL = {"intercepto": 0.0, "peso_mercado": 1.0, "peso_modelo": 0.2, "n": 1}
A, B = "Aleksandar Rakic", "Marcin Tybura"


def _datos_cargados(p_modelo=0.61, cuota_a=1.26, cuota_b=3.80):
    """Lo que deja una carga normal: predict_card -> _serializar."""
    v = V.analizar(p_modelo, cuota_a, cuota_b, cal=CAL)
    metodo = {"KO/TKO": 0.35, "Submission": 0.10, "Decision": 0.55}
    sim = monte_carlo(v.p_final_a, metodo, A, B)
    fila = {"A": A, "B": B, "cuota_a": cuota_a, "cuota_b": cuota_b, "segmento": "",
            "aviso": "", "fuente": "ufc/ufc", "corto_a": 0, "corto_b": 0,
            "p_sin_corto_A": p_modelo, "p_con_corto_A": p_modelo}
    consenso = [{"a": A, "b": B, "sim": sim, "method": metodo, "pocos": [], "v": v,
                 "metodo6": None, "metodo5": None, "info_a": {}, "info_b": {}}]
    res = {"rows": [fila], "consenso": consenso, "con_cuotas": True, "calibrador": True}
    return E._serializar(res, Path("prueba.csv"))


class RefrescoEnVivo(unittest.TestCase):

    def setUp(self):
        self.estado = E.Estado()
        datos, patas = _datos_cargados()
        self.estado.origen, self.estado.consulta = "betano", "UFC"
        self.estado.datos, self.estado.patas = datos, patas
        self.parches = [mock.patch.object(E, "ESTADO", self.estado),
                        mock.patch.object(V, "cargar_calibrador", lambda: CAL)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def _refrescar(self, frescas):
        import src.betano_scraper as BS
        with mock.patch.object(BS, "find_card", lambda q: {"url": "/x"}), \
                mock.patch.object(BS, "cuotas_rapidas", lambda url: frescas):
            return E.refrescar_linea()

    def test_la_linea_se_da_vuelta_y_todo_lo_que_depende_de_ella_se_recalcula(self):
        # BUG: solo se actualizaba el bloque "mercado". La tarjeta seguía mostrando
        # "Rakic 79%, fuerte" y la pata del parlay mezclaba la p VIEJA con la cuota
        # NUEVA: EV +62,5% cuando el real era +2,9%.
        self._refrescar({"1": (A, B, 2.05, 1.80)})
        pl = self.estado.datos["peleas"][0]
        m = pl["mercado"]
        self.assertEqual((m["cuota_a"], m["cuota_b"]), (2.05, 1.80))
        self.assertAlmostEqual(pl["p_a"], m["p_final_a"], places=4)
        self.assertAlmostEqual(pl["p_a"] + pl["p_b"], 1.0, places=6)
        self.assertEqual(pl["ganador"], A if pl["p_a"] >= 0.5 else B)
        self.assertEqual(pl["confianza"], E._confianza(max(pl["p_a"], pl["p_b"]), []))

        patas = {p.id: p for p in self.estado.patas}
        pa, pb = patas["0:ML:A"], patas["0:ML:B"]
        self.assertEqual((pa.cuota, pb.cuota), (2.05, 1.80))
        self.assertAlmostEqual(pa.p, m["p_final_a"], places=4)
        self.assertAlmostEqual(pb.p, 1 - m["p_final_a"], places=4)
        # (la p de la pata va redondeada a 4 decimales, como toda la salida de simulate)
        self.assertAlmostEqual(pa.ev, V.ev_unidad(m["p_final_a"], 2.05), delta=5e-4)
        self.assertEqual(self.estado.datos["sugerencia"], P.sugerir(self.estado.patas))

    def test_las_cuotas_se_orientan_por_nombre(self):
        # Betano puede listar la pelea al revés que el CSV: la cuota de cada uno
        # tiene que ir a su peleador, no a la columna.
        self._refrescar({"1": (B, A, 1.80, 2.05)})
        m = self.estado.datos["peleas"][0]["mercado"]
        self.assertEqual((m["cuota_a"], m["cuota_b"]), (2.05, 1.80))

    def test_movimiento_de_los_dos_lados(self):
        self._refrescar({"1": (A, B, 2.05, 1.80)})
        mov = self.estado.movimiento
        self.assertEqual(mov["0:ML:A"], {"antes": 1.26, "ahora": 2.05})
        self.assertEqual(mov["0:ML:B"], {"antes": 3.80, "ahora": 1.80})


if __name__ == "__main__":
    unittest.main()
