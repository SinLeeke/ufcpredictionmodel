"""Avances de carga y estimaciones medidos, sin red ni modelos."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from webui import engine as E


class ProgresoMedido(unittest.TestCase):
    def setUp(self):
        self.ahora = 0.0
        self.reloj = mock.patch.object(E.time, "monotonic", lambda: self.ahora)
        self.reloj.start()
        self.addCleanup(self.reloj.stop)
        self.carga = E.ProgresoCarga()
        self.carga.iniciar()

    def _avance(self, segundos, completadas, detalle="Procesando una pelea…", etapa="prediccion", total=4):
        self.ahora = segundos
        self.carga.actualizar({"etapa": etapa, "detalle": detalle,
                               "completadas": completadas, "total": total})

    def test_estima_con_unidades_completadas_y_no_con_mensajes(self):
        self._avance(5, 0)
        self.assertIsNone(self.carga.snapshot()["restante_seg"])
        self._avance(15, 0, "Consultando la ficha del segundo peleador…")
        self.assertIsNone(self.carga.snapshot()["restante_seg"])
        self._avance(25, 1, "Una pelea lista.")
        self.assertEqual(self.carga.snapshot()["restante_seg"], 60)
        self.ahora = 30
        self.assertEqual(self.carga.snapshot()["restante_seg"], 55)
        self.assertEqual(self.carga.snapshot()["transcurrido_seg"], 30)
        self.assertEqual(self.carga.snapshot()["sin_avance_seg"], 5)

    def test_si_la_estimacion_se_excede_no_promete_cero_segundos(self):
        self._avance(5, 0)
        self._avance(25, 1)
        self.ahora = 90
        self.assertIsNone(self.carga.snapshot()["restante_seg"])
        self._avance(100, 2)
        self.assertEqual(self.carga.snapshot()["restante_seg"], 95)

    def test_cambiar_etapa_no_reutiliza_el_tiempo_de_cuotas_para_fichas(self):
        self._avance(5, 0, etapa="cuotas")
        self._avance(10, 1, etapa="cuotas")
        self.assertIsNotNone(self.carga.snapshot()["restante_seg"])
        self._avance(11, 0, etapa="prediccion")
        self.assertIsNone(self.carga.snapshot()["restante_seg"])

    def test_cien_solo_despues_de_publicar_y_reloj_se_congela(self):
        self._avance(5, 0)
        self._avance(25, 4)
        self.assertLess(self.carga.snapshot()["porcentaje"], 100)
        self._avance(26, 0, etapa="serializando", total=None)
        self.assertIsNone(self.carga.snapshot()["porcentaje"])
        self.ahora = 27
        self.carga.terminar()
        self.ahora = 100
        snap = self.carga.snapshot()
        self.assertEqual(snap["porcentaje"], 100)
        self.assertEqual(snap["transcurrido_seg"], 27)
        self.assertTrue(snap["finalizada"])


class _HiloInmediato:
    """Ejecuta el trabajo determinísticamente, con el mismo manejo de errores."""
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


class CargaConAvances(unittest.TestCase):
    def setUp(self):
        self.estado = E.Estado()
        self.previos = {"peleas": [{"id": "anterior"}]}
        self.estado.datos = self.previos
        self.estado.titulo = "Cartelera anterior"
        self.estado.cuotas_en = 123
        self.parches = [mock.patch.object(E, "ESTADO", self.estado),
                        mock.patch.object(E.threading, "Thread", _HiloInmediato)]
        for parche in self.parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_system_exit_del_scraper_es_error_visible_y_conserva_cartelera(self):
        with mock.patch.object(E, "bajar_cuotas", side_effect=SystemExit(1)):
            E.cargar("betano", "UFC")
        snap = self.estado.snapshot()
        self.assertFalse(snap["cargando"])
        self.assertIn("Betano", snap["error"])
        self.assertEqual(snap["carga"]["estado"], "error")
        self.assertNotEqual(snap["carga"]["porcentaje"], 100)
        self.assertIs(self.estado.datos, self.previos)
        self.assertEqual(self.estado.titulo, "Cartelera anterior")
        self.assertEqual(self.estado.cuotas_en, 123)

    def test_no_publica_cien_ni_cambia_resultados_antes_de_serializar(self):
        nuevos = {"peleas": [{"id": "nueva"}]}

        def predecir(ruta, progreso):
            progreso({"etapa": "prediccion", "detalle": "Consultando Uno…",
                      "completadas": 0, "total": 1})
            self.assertEqual(self.estado.snapshot()["carga"]["detalle"], "Consultando Uno…")
            progreso({"etapa": "prediccion", "detalle": "Una pelea lista.",
                      "completadas": 1, "total": 1})
            return {"rows": [{}]}

        def serializar(res, ruta):
            self.assertIs(self.estado.datos, self.previos)
            snap = self.estado.snapshot()["carga"]
            self.assertEqual(snap["etapa"], "serializando")
            self.assertNotEqual(snap["porcentaje"], 100)
            return nuevos, []

        with mock.patch.object(E, "_predecir_sync", side_effect=predecir), \
                mock.patch.object(E, "_serializar", side_effect=serializar):
            E.cargar("csv", "nueva.csv", Path("nueva.csv"))
        self.assertIs(self.estado.datos, nuevos)
        self.assertEqual(self.estado.snapshot()["carga"]["porcentaje"], 100)
        self.assertEqual(self.estado.titulo, "nueva")
        self.assertEqual(self.estado.error, "")

    def test_nueva_carga_y_limpiar_reinician_metricas(self):
        self.estado.carga.iniciar()
        self.estado.carga.actualizar({"etapa": "prediccion", "detalle": "Anterior",
                                     "completadas": 3, "total": 4})
        vieja = self.estado.carga
        with mock.patch.object(E, "_predecir_sync", side_effect=RuntimeError("Sin conexión")):
            E.cargar("csv", "otra.csv", Path("otra.csv"))
        self.assertIsNot(self.estado.carga, vieja)
        self.assertEqual(self.estado.carga.completadas, 0)
        E.limpiar()
        snap = self.estado.snapshot()["carga"]
        self.assertEqual(snap["estado"], "inactiva")
        self.assertEqual(snap["transcurrido_seg"], 0)
        self.assertIsNone(snap["porcentaje"])

    def test_bajar_cuotas_reutiliza_el_titulo_del_scraper_sin_repetir_busqueda(self):
        from src import betano_scraper as B
        eventos = []

        def scrapear(query, salida, fecha, progreso):
            progreso({"etapa": "buscando", "detalle": "Peleas encontradas",
                      "titulo": "UFC Fight Night"})
            return Path("cuotas.csv")

        with mock.patch.object(B, "scrape_card", side_effect=scrapear), \
                mock.patch.object(B, "find_card") as buscar:
            ruta, titulo = E.bajar_cuotas("UFC", progreso=eventos.append)
        buscar.assert_not_called()
        self.assertEqual((ruta, titulo), (Path("cuotas.csv"), "UFC Fight Night"))
        self.assertEqual(len(eventos), 1)

    def test_predecir_sync_entrega_el_callback_al_motor_sin_esperar_stdout(self):
        eventos = []
        resultado = {"rows": [{}]}
        aviso = {"etapa": "prediccion", "detalle": "Consultando Uno…",
                 "completadas": 0, "total": 1}

        def predecir(ruta, reports, detalle, devolver_todo, progreso):
            progreso(aviso)
            self.assertEqual(eventos, [aviso])
            return resultado

        with mock.patch.dict("sys.modules", {"src.card": SimpleNamespace(predict_card=predecir)}):
            res = E._predecir_sync(Path("una.csv"), progreso=eventos.append)
        self.assertIs(res, resultado)


if __name__ == "__main__":
    unittest.main()
