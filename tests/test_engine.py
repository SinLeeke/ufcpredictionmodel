"""Pruebas de webui/engine.py: el refresco EN VIVO de la línea de ganador."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config as C
from src import storage as DB
from src import value as V
from src.cuotas import calendario, capa as capa_mod, cruce
from src.cuotas.capa import Capa
from src.cuotas.fuentes.betano import Betano
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


class BaseEngine(unittest.TestCase):
    """Cada prueba conserva la ingesta real, pero solo en su SQLite temporal."""

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        ruta_db = (Path(temporal.name) / "engine.db").resolve()
        for parche in (
            mock.patch.dict(os.environ, {"UFC_DB": str(ruta_db)}),
            mock.patch.object(C, "MERCADO_SIMULADO", False),
            mock.patch("requests.sessions.Session.request",
                       side_effect=AssertionError("red bloqueada en tests de engine")),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        self.assertEqual(DB.db_path().resolve(), ruta_db)
        # Reutilizar el singleton de otra prueba mezclaba sus fuentes y sus
        # memorias; Betano pasiva permite probar la misma entrega sin polling.
        parche = mock.patch.object(capa_mod, "_CAPA", Capa([Betano()]))
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(cruce.invalidar)
        self.addCleanup(calendario.olvidar)
        cruce.invalidar()
        calendario.olvidar()


class RefrescoEnVivo(BaseEngine):

    def setUp(self):
        super().setUp()
        self.estado = E.Estado()
        datos, patas = _datos_cargados()
        self.estado.origen, self.estado.consulta = "betano", "UFC"
        self.estado.datos, self.estado.patas = datos, patas
        self.parches = [mock.patch.object(E, "ESTADO", self.estado),
                        mock.patch.object(E, "_archivar_linea"),
                        mock.patch.object(V, "cargar_calibrador", lambda: CAL)]
        for p in self.parches:
            p.start()
            self.addCleanup(p.stop)

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

    def test_un_apellido_compartido_no_mueve_la_cuota(self):
        self._refrescar({"1": ("Otro Rakic", "Otro Tybura", 2.05, 1.80)})
        m = self.estado.datos["peleas"][0]["mercado"]
        self.assertEqual((m["cuota_a"], m["cuota_b"]), (1.26, 3.80))
        from src.cuotas import historial
        # Antes estas filas de diagnóstico terminaban en data/ufc.db.
        no_calzados = historial.resumen_no_calzados()
        self.assertEqual({n["texto"] for n in no_calzados["recientes"]},
                         {"Otro Rakic", "Otro Tybura"})

    def test_movimiento_de_los_dos_lados(self):
        self._refrescar({"1": (A, B, 2.05, 1.80)})
        mov = self.estado.movimiento
        self.assertEqual(mov["0:ML:A"], {"antes": 1.26, "ahora": 2.05})
        self.assertEqual(mov["0:ML:B"], {"antes": 3.80, "ahora": 1.80})


class AvisosYGraficos(BaseEngine):
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


class ResultadosRecientes(BaseEngine):
    """La portada: las últimas carteleras repetidas, calculadas aparte y guardadas."""

    def _pelea(self, a, b, ganador, metodo_real, segmento=""):
        lado = "a" if ganador == a else "b"
        return {"a": a, "b": b, "ganador": a, "p_a": 0.7, "p_b": 0.3, "confianza": "buena",
                "segmento": segmento, "es_titulo": False,
                "metodo": {"KO/TKO": 0.2, "Submission": 0.1, "Decision": 0.7},
                "resultado": {"ganador": ganador, "lado": lado, "metodo": metodo_real,
                              "como": "decisión", "acierto": ganador == a}}

    def test_resume_ganador_y_metodo_con_la_estelar_primero(self):
        datos = {"con_cuotas": True, "peleas": [
            self._pelea("X Uno", "Y Dos", "X Uno", "KO/TKO"),
            self._pelea("Z Tres", "W Cuatro", "Z Tres", "Decision", segmento="Estelar")]}
        with mock.patch("src.corte.cartelera_de_evento", lambda e, f: Path("c.csv")), \
                mock.patch.object(E, "_predecir_sync", lambda *a, **k: {}), \
                mock.patch.object(E, "_serializar", lambda res, ruta: (datos, [])):
            c = E._resultado_evento("UFC 1: Tres vs. Cuatro", "2026-01-01")
        self.assertEqual([p["a"] for p in c["peleas"]], ["Z Tres", "X Uno"])
        self.assertEqual((c["aciertos"], c["resueltas"]), (2, 2))
        self.assertEqual((c["aciertos_metodo"], c["metodos"]), (1, 2))
        self.assertTrue(c["peleas"][0]["acierto_metodo"])
        self.assertFalse(c["peleas"][1]["acierto_metodo"])

    def test_sin_base_no_calcula_nada(self):
        with mock.patch.object(E, "_ultimos_eventos", side_effect=FileNotFoundError()):
            self.assertEqual(E.resultados_recientes(),
                             {"carteleras": [], "sin_base": True, "calculando": False})

    def test_calcula_en_otro_hilo_y_guarda(self):
        import tempfile
        import time
        eventos = [{"evento": "UFC 2", "fecha": "2026-02-01"}]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(E, "RESULTADOS_JSON", Path(d) / "r.json"), \
                mock.patch.object(E, "_ultimos_eventos", lambda n: eventos), \
                mock.patch.object(E, "_firma_resultados", lambda: "f1"), \
                mock.patch.object(E, "_resultado_evento",
                                  lambda e, f: {"evento": e, "fecha": f, "peleas": []}):
            primera = E.resultados_recientes()
            self.assertTrue(primera["carteleras"][0].get("pendiente"))
            for _ in range(50):
                if not E._RESULTADOS_LOCK.locked():
                    break
                time.sleep(0.05)
            lista = E.resultados_recientes()
            self.assertFalse(lista["calculando"])
            self.assertEqual(lista["carteleras"][0]["peleas"], [])
