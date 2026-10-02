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
        self.assertEqual(pl["ci_b"], [round(1 - pl["ci_a"][1], 4), round(1 - pl["ci_a"][0], 4)])

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


class AvisosYGraficos(unittest.TestCase):
    def _serializar(self, info_a=None, info_b=None, **extra):
        metodo = {"KO/TKO": 0.35, "Submission": 0.10, "Decision": 0.55}
        sim = monte_carlo(0.62, metodo, A, B)
        consenso = {"a": A, "b": B, "sim": sim, "method": metodo, "pocos": [],
                    "info_a": info_a or {}, "info_b": info_b or {}, **extra}
        datos, _ = E._serializar({"rows": [{"A": A, "B": B}], "consenso": [consenso]}, Path("test.csv"))
        return datos["peleas"][0]

    def test_uno_o_dos_debutantes_se_identifican_con_nombre_completo(self):
        debut = {"debut_ufc_confirmado": True, "n_peleas_ufc": 0, "historial_ufc_confirmado": True}
        veterano = {"n_peleas_ufc": 8, "historial_ufc_confirmado": True}
        for info_a, info_b, nombres in ((debut, veterano, [A]), (veterano, debut, [B]),
                                        (debut, debut, [A, B]), (veterano, veterano, [])):
            with self.subTest(nombres=nombres):
                pelea = self._serializar(info_a, info_b)
                self.assertEqual(pelea["debutantes"], nombres)
                self.assertEqual(pelea["debut_cantidad"], len(nombres))

    def test_cero_local_o_historial_ausente_no_disparan_el_aviso_de_debut(self):
        pelea = self._serializar({"n_peleas_hist": 0}, {"n_peleas_hist": None, "historial_disponible": False})
        self.assertEqual(pelea["debutantes"], [])
        self.assertEqual(pelea["debut_cantidad"], 0)
        self.assertIsNone(pelea["metodo_hist_a"])
        self.assertIsNone(pelea["probabilidades_metodo"])

    def test_donut_intervalos_y_metodos_historicos_conservan_los_datos_originales(self):
        historial = {"KO/TKO": 0.2, "Submission": 0.3, "Decision": 0.5}
        pelea = self._serializar({"metodo_victorias": historial,
                                  "metodo_victorias_fuente": "carrera profesional (Sherdog)"})
        self.assertEqual(pelea["metodo_hist_a"], historial)
        self.assertEqual(pelea["metodo_hist_fuente_a"], "carrera profesional (Sherdog)")
        self.assertIsNone(pelea["metodo_hist_b"])
        self.assertEqual(pelea["p_decision"], 0.55)
        self.assertEqual(pelea["ci_b"], [round(1 - pelea["ci_a"][1], 4), round(1 - pelea["ci_a"][0], 4)])

    def test_probabilidades_de_cada_peleador_estan_disponibles_sin_cuotas_de_metodo(self):
        p6 = {"A_KO": 0.31, "A_SUB": 0.07, "A_DEC": 0.22,
              "B_KO": 0.15, "B_SUB": 0.05, "B_DEC": 0.20}
        pelea = self._serializar(probabilidades_metodo=p6)
        self.assertEqual(pelea["probabilidades_metodo"], p6)
        self.assertNotIn("metodo6", pelea)

    def test_demo_anterior_recupera_modelo_de_metodo_y_no_confunde_probabilidad_calibrada(self):
        p6 = {"A_KO": 0.31, "A_SUB": 0.07, "A_DEC": 0.22,
              "B_KO": 0.15, "B_SUB": 0.05, "B_DEC": 0.20}
        pelea = self._serializar(metodo6=[{"clase": clase, "p_modelo": p, "p_final": 1 / 6,
                                          "cuota_decimal": 5.0}
                                         for clase, p in p6.items()])
        self.assertEqual(pelea["probabilidades_metodo"], p6)

    def test_tasas_invalidas_o_incompletas_se_mantienen_desconocidas(self):
        for tasas in ({"KO/TKO": float("nan"), "Submission": 0.2, "Decision": 0.4},
                      {"KO/TKO": 0.7, "Submission": 0.4, "Decision": 0.4},
                      {"KO/TKO": 0.7}):
            with self.subTest(tasas=tasas):
                pelea = self._serializar({"metodo_victorias": tasas})
                self.assertIsNone(pelea["metodo_hist_a"])


if __name__ == "__main__":
    unittest.main()
