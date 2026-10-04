"""Cancelar una carga: se detiene en el próximo paso y la app queda exactamente como estaba.

Sin red ni modelos: el scraper y la predicción son dobles que escriben como lo
harían los de verdad (cachés por storage, el CSV de cards/ y los informes de
outputs/). Todo en una carpeta temporal; nunca data/ufc.db.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import config as C
from src import storage as DB
from webui import engine as E


class _HiloInmediato:
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


class CancelarCarga(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.estado = E.Estado()
        self.previos = {"peleas": [{"id": "anterior"}]}
        self.estado.datos, self.estado.titulo = self.previos, "Cartelera anterior"
        self.estado.error, self.estado.log, self.estado.proximo_auto = "", ["log anterior"], 4242.0
        self.carga_previa = self.estado.carga
        for parche in (mock.patch.object(E, "ESTADO", self.estado),
                       mock.patch.object(E.threading, "Thread", _HiloInmediato),
                       mock.patch.object(C, "ROOT", self.root),
                       mock.patch.object(C, "OUTPUTS", self.root / "outputs"),
                       # DATA_RAW se calcula al importar config: hay que moverlo también,
                       # o la copia del CSV de Betano iría a data/raw de verdad.
                       mock.patch.object(C, "DATA_RAW", self.root / "data/raw"),
                       mock.patch.object(C, "DATA_PROCESSED", self.root / "data/processed"),
                       mock.patch.dict(os.environ, {"UFC_DB": str(self.root / "cancelar.db")})):
            parche.start()
            self.addCleanup(parche.stop)
        self.cache = self.root / "data/raw/ufcstats_cache.json"
        DB.write_text(self.cache, json.dumps({"Ana Arco": {"slpm": 4.0}}))
        self.informes = self.root / "outputs/betano_2026_10_10_a_vs_b"
        self.informes.mkdir(parents=True)
        (self.informes / "ana_vs_bia.html").write_text("informe anterior")
        self.csv = self.root / "cards/betano_2026-10-10_a_vs_b.csv"

    def quedo_como_estaba(self):
        self.assertIs(self.estado.datos, self.previos)
        self.assertEqual(self.estado.titulo, "Cartelera anterior")
        self.assertEqual((self.estado.error, self.estado.log, self.estado.proximo_auto), ("", ["log anterior"], 4242.0))
        self.assertIs(self.estado.carga, self.carga_previa)
        self.assertFalse(self.estado.cargando)
        self.assertIsNotNone(self.estado.snapshot()["cancelada"])
        self.assertEqual(DB.read_json(self.cache), {"Ana Arco": {"slpm": 4.0}})
        self.assertEqual(sorted(p.name for p in self.informes.iterdir()), ["ana_vs_bia.html"])
        self.assertEqual((self.informes / "ana_vs_bia.html").read_text(), "informe anterior")

    def scraper(self, cancelar_en_cuotas=False):
        def scrape_card(query, salida, fecha=None, progreso=None):
            progreso({"etapa": "cuotas", "detalle": "Bajando cuotas…", "titulo": "UFC Fight Night"})
            if cancelar_en_cuotas:
                self.assertEqual(E.cancelar_carga(), "")
            progreso({"etapa": "cuotas", "detalle": "Peleas encontradas"})
            self.csv.parent.mkdir(parents=True, exist_ok=True)
            DB.to_csv(__import__("pandas").DataFrame([{"fighter_a": "Ana Arco", "fighter_b": "Bia Bravo",
                                                       "odds_a": 1.5, "odds_b": 2.6}]), self.csv, index=False)
            return str(self.csv)
        return scrape_card

    def test_antes_del_modelo_se_detiene_sin_guardar_cuotas_ni_tocar_nada(self):
        from src import betano_scraper as B, cuotas_fuentes as Q
        with mock.patch.object(B, "scrape_card", side_effect=self.scraper(cancelar_en_cuotas=True)), \
                mock.patch.object(Q, "_guardar") as guardar, \
                mock.patch.object(E, "_entregar_a_capa") as capa, \
                mock.patch.object(E, "_predecir_sync") as predecir:
            E.cargar("betano", "UFC")
        predecir.assert_not_called()
        guardar.assert_not_called()
        capa.assert_not_called()
        self.assertFalse(self.csv.exists())
        self.quedo_como_estaba()

    def test_en_la_etapa_del_modelo_se_revierten_cachés_cartelera_e_informes(self):
        from src import betano_scraper as B, cuotas_fuentes as Q, cartelera_completa as F

        def predecir(ruta, progreso):
            progreso({"etapa": "prediccion", "detalle": "Consultando Ana…", "completadas": 0, "total": 1})
            # Lo que haría predict_card: una ficha nueva en la caché y un informe por pelea.
            DB.write_text(self.cache, json.dumps({"Ana Arco": {"slpm": 4.0}, "Bia Bravo": {"slpm": 3.1}}))
            (self.informes / "ana_vs_bia.html").write_text("a medias")
            (self.informes / "otra.html").write_text("a medias")
            E.cancelar_carga()
            progreso({"etapa": "prediccion", "detalle": "Consultando Bia…", "completadas": 0, "total": 1})
            raise AssertionError("tenía que detenerse en el aviso anterior")

        with mock.patch.object(B, "scrape_card", side_effect=self.scraper()), \
                mock.patch.object(F, "completar_betano", side_effect=lambda df, q, f: df), \
                mock.patch.object(Q, "_guardar") as guardar, \
                mock.patch.object(E, "_entregar_a_capa") as capa, \
                mock.patch.object(E, "_predecir_sync", side_effect=predecir):
            E.cargar("betano", "UFC")
        guardar.assert_not_called()
        capa.assert_not_called()
        self.assertFalse(self.csv.exists())
        with DB.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM _resources WHERE path LIKE 'data/raw/cuotas_betano_%'").fetchone()[0], 0)
        self.quedo_como_estaba()

    def test_una_carga_que_termina_bien_guarda_lo_diferido_y_publica(self):
        from src import betano_scraper as B, cuotas_fuentes as Q, cartelera_completa as F
        nuevos = {"peleas": [{"id": "nueva"}]}
        with mock.patch.object(B, "scrape_card", side_effect=self.scraper()), \
                mock.patch.object(F, "completar_betano", side_effect=lambda df, q, f: df), \
                mock.patch.object(Q, "_guardar") as guardar, \
                mock.patch.object(E, "_entregar_a_capa") as capa, \
                mock.patch.object(E, "_predecir_sync", return_value={"rows": [{}]}), \
                mock.patch.object(E, "_serializar", return_value=(nuevos, [])):
            E.cargar("betano", "UFC")
        guardar.assert_called_once()
        capa.assert_called_once()
        self.assertTrue(self.csv.exists())
        self.assertIs(self.estado.datos, nuevos)
        self.assertIsNone(self.estado.snapshot()["cancelada"])
        with DB.connect() as con:      # la copia original del CSV de Betano, en la base temporal
            self.assertEqual(con.execute("SELECT count(*) FROM _resources WHERE path LIKE 'data/raw/cuotas_betano_%'").fetchone()[0], 1)

    def test_la_cancelacion_no_se_la_traga_un_except_exception(self):
        def predecir(ruta, progreso):
            E.cancelar_carga()
            try:
                progreso({"etapa": "prediccion", "detalle": "Sherdog…"})
            except Exception:                                  # noqa: BLE001
                pass                                            # como los respaldos de card.py
            raise AssertionError("no debía llegar aquí")
        with mock.patch.object(E, "_predecir_sync", side_effect=predecir):
            E.cargar("csv", "a.csv", Path("a.csv"))
        self.assertIs(self.estado.datos, self.previos)
        self.assertEqual(self.estado.error, "")

    def test_sin_carga_no_hay_nada_que_cancelar(self):
        self.assertIn("No hay", E.cancelar_carga())
        from fastapi import HTTPException
        from webui import server
        # Directo y no por TestClient: aquí threading.Thread está reemplazado.
        with self.assertRaises(HTTPException) as e:
            server.cancelar_carga()
        self.assertEqual(e.exception.status_code, 409)

    def test_mientras_se_cancela_la_ui_lo_sabe(self):
        vistos = []

        def predecir(ruta, progreso):
            E.cancelar_carga()
            vistos.append(self.estado.snapshot()["carga"]["cancelando"])
            progreso({"etapa": "prediccion", "detalle": "x"})
        with mock.patch.object(E, "_predecir_sync", side_effect=predecir):
            E.cargar("csv", "a.csv", Path("a.csv"))
        self.assertEqual(vistos, [True])
        self.assertFalse(self.estado.snapshot()["carga"]["cancelando"])


if __name__ == "__main__":
    unittest.main()
