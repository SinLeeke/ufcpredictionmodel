"""Insignias descriptivas: identidad, fecha y probabilidades permanecen separadas."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd

import config as C
from src import storage as DB
from webui import catalogo as K, identidad_visual as I, paises as P


class IdentidadVisual(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = mock.patch.dict(os.environ, {"UFC_DB": str(Path(temp.name) / "ui.db")})
        env.start()
        self.addCleanup(env.stop)
        self.ids = {"Alpha": "0000000000000001", "Beta": "0000000000000002"}
        nombres = ["Alpha", "Beta", "Jean Silva", "Jean Silva", "Sin ranking"]
        DB.to_csv(pd.DataFrame([{"fighter_url": f"http://ufcstats.com/fighter-details/{i:016x}",
            "name": n} for i, n in enumerate(nombres, 1)]), K.BIO, index=False)
        self.divisiones = [{"nombre": "Peso pluma", "peleadores": [
            {"nombre": "Alpha", "puesto": 0, "perfil_ufc": "https://www.ufc.com/athlete/alpha"},
            {"nombre": "Beta", "puesto": 5, "perfil_ufc": "https://www.ufc.com/athlete/beta"},
            {"nombre": "Jean Silva", "puesto": 6, "perfil_ufc": "https://www.ufc.com/athlete/jean-silva"}]}]
        self._rankings()
        red = mock.patch("requests.get", side_effect=AssertionError("La identidad visual no consulta la red"))
        self.get = red.start()
        self.addCleanup(red.stop)

    def _rankings(self, fecha="2026-10-03"):
        DB.write_text(I.RANKINGS, json.dumps({"fecha": fecha, "divisiones": self.divisiones}))
        I._rankings.cache_clear()
        I._invalidar()

    def test_insignias_explicitas_y_no_inferir_cinturon_por_titulo(self):
        for valor, esperado in (("C", "C"), ("ic", "IC"), ("#7", "7"), (7, "7"),
                                (7.0, "7"), (0, None), (True, None), (float("nan"), None)):
            self.assertEqual(I.insignia(valor), esperado)
        estado = {"datos": {"peleas": [{"a": "Sin ranking", "b": "No clasificado", "es_titulo": True,
            "p_a": .623, "p_b": .377}]}}
        d = I.decorar_estado(estado)
        self.assertIsNone(d["datos"]["peleas"][0]["identidad_a"]["rango"])
        self.assertIsNone(d["datos"]["peleas"][0]["identidad_b"]["rango"])
        self.get.assert_not_called()

    def test_campeon_interino_debe_estar_marcado_en_fuente(self):
        p = self.divisiones[0]["peleadores"][1]
        p["tipo"] = "IC"
        self._rankings()
        self.assertEqual(I.metadatos("Alpha", peso="Featherweight")["rango"], "C")
        self.assertEqual(I.metadatos("Beta", peso="Featherweight")["rango"], "IC")
        self.assertEqual(I.metadatos("Sin ranking", referencia={"rango": "IC"})["rango"], "IC")

    def test_repeticion_no_recibe_ranking_posterior_al_corte(self):
        d = I.metadatos("Alpha", peso="Featherweight", corte="2020-06-06")
        self.assertIsNone(d["rango"])
        self.assertEqual(d["rankings"], [])
        futuro = I.metadatos("Alpha", corte="2020-06-06", referencia={"rango": "C", "fecha": "2026-10-03"})
        self.assertIsNone(futuro["rango"])
        self._rankings("2020-06-05")
        pasado = I.metadatos("Alpha", peso="Featherweight", corte="2020-06-06")
        self.assertEqual((pasado["rango"], pasado["ranking_fecha"]), ("C", "2020-06-05"))

    def test_homonimo_requiere_vinculo_individual_verificado(self):
        viejo, actual = "0000000000000003", "0000000000000004"
        self.assertIsNone(I.metadatos("Jean Silva", actual)["rango"])
        P.asociar(actual, "https://www.ufc.com/athlete/jean-silva")
        self.assertEqual(I.metadatos("Jean Silva", actual)["rango"], "6")
        self.assertIsNone(I.metadatos("Jean Silva", viejo)["rango"])
        P.asociar(viejo, "https://www.ufc.com/athlete/otro-jean-silva")
        self.assertIsNone(I.metadatos("Jean Silva", viejo)["rango"])
        self.get.assert_not_called()

    def test_match_exacto_y_rango_de_la_division_correcta(self):
        self.divisiones.append({"nombre": "Peso ligero", "peleadores": [
            {"nombre": "Alpha", "puesto": 8, "perfil_ufc": "https://www.ufc.com/athlete/alpha"}]})
        self._rankings()
        self.assertEqual(I.metadatos("Alpha", peso="Lightweight")["rango"], "8")
        self.assertEqual(I.metadatos("Alpha", peso="Featherweight")["rango"], "C")
        self.assertIsNone(I.metadatos("Alpha", peso="Heavyweight")["rango"])
        self.assertIsNone(I.metadatos("alpha", peso="Featherweight")["rango"])
        self.assertIsNone(I.metadatos("Beta", peso="Lightweight")["rango"])

    def test_decorar_copia_orienta_esquinas_y_no_toca_predicciones_ni_csv(self):
        ruta = C.DATA_PROCESSED / "test_identidad_visual.csv"
        DB.to_csv(pd.DataFrame([{"fighter_a": "Beta", "fighter_b": "Alpha",
            "rango_a": "3", "rango_b": "IC", "weight_class": "Featherweight",
            "perfil_a": "https://www.ufc.com/athlete/beta", "perfil_b": "https://www.ufc.com/athlete/alpha"}]), ruta, index=False)
        estado = {"corte": None, "datos": {"peleas": [{"a": "Alpha", "b": "Beta", "p_a": .623,
            "p_b": .377, "metodo": {"ko": .35, "sub": .22, "dec": .43}, "es_titulo": True}]}}
        original = copy.deepcopy(estado)
        entrada = DB.read_text(ruta)
        d = I.decorar_estado(estado, ruta)
        pelea = d["datos"]["peleas"][0]
        self.assertEqual(estado, original)
        self.assertIsNot(d, estado)
        self.assertIsNot(d["datos"], estado["datos"])
        self.assertIsNot(pelea, estado["datos"]["peleas"][0])
        self.assertEqual((pelea["identidad_a"]["rango"], pelea["identidad_b"]["rango"]), ("IC", "3"))
        self.assertEqual({k: v for k, v in pelea.items() if not k.startswith("identidad_")}, original["datos"]["peleas"][0])
        self.assertEqual(DB.read_text(ruta), entrada)
        self.get.assert_not_called()

    def test_rango_numerico_de_csv_no_se_pierde_al_leer_pandas(self):
        ruta = C.DATA_PROCESSED / "test_rango_numerico.csv"
        DB.to_csv(pd.DataFrame([{"fighter_a": "Sin ranking", "fighter_b": "No clasificado", "rango_a": 7,
            "rango_b": 12}]), ruta, index=False)
        d = I.decorar_estado({"datos": {"peleas": [{"a": "Sin ranking", "b": "No clasificado", "p_a": .5}]}}, ruta)
        p = d["datos"]["peleas"][0]
        self.assertEqual((p["identidad_a"]["rango"], p["identidad_b"]["rango"]), ("7", "12"))

    def test_cache_detecta_actualizacion_y_cambio_de_base(self):
        I._invalidar()
        with mock.patch.object(I.time, "monotonic", return_value=10.):
            primero = I._documento()
        self.divisiones[0]["peleadores"][1]["puesto"] = 7
        DB.write_text(I.RANKINGS, json.dumps({"fecha": "2026-10-04", "divisiones": self.divisiones}))
        with mock.patch.object(I.time, "monotonic", return_value=10.1):
            self.assertEqual(I._documento()["fecha"], primero["fecha"])
        with mock.patch.object(I.time, "monotonic", return_value=10.3):
            self.assertEqual(I._documento()["fecha"], "2026-10-04")
        otro = Path(DB.db_path()).with_name("otra.db")
        with mock.patch.dict(os.environ, {"UFC_DB": str(otro)}), mock.patch.object(I.time, "monotonic", return_value=10.31):
            self.assertEqual(I._documento()["divisiones"], [])

    def test_cargando_devuelve_progreso_sin_consultar_sqlite_ni_metadatos(self):
        estado = {"cargando": True, "carga": {"detalle": "Analizando pelea 4/9", "porcentaje": 44},
            "datos": {"peleas": [{"a": "Alpha", "b": "Beta", "p_a": .62}]}}
        with mock.patch.object(I.DB, "exists") as existe, mock.patch.object(I.DB, "read_csv") as leer, \
                mock.patch.object(I, "metadatos") as metadatos:
            resultado = I.decorar_estado(estado, C.DATA_PROCESSED / "cartelera_anterior.csv")
        self.assertIs(resultado, estado)
        existe.assert_not_called()
        leer.assert_not_called()
        metadatos.assert_not_called()

    def _kavanagh(self, duplicado=False):
        bio = DB.read_csv(K.BIO)
        filas = [{"fighter_url": f"http://ufcstats.com/fighter-details/{i:016x}", "name": "Lone'er Kavanagh"}
                 for i in range(6, 8 if duplicado else 7)]
        DB.to_csv(pd.concat([bio, pd.DataFrame(filas)], ignore_index=True), K.BIO, index=False)
        P.guardar_eventos([{"url": "https://www.ufc.com/event/ufc-333", "peleas": [{
            "a": "Lone’er Kavanagh", "b": "Beta", "perfil_a": "https://www.ufc.com/athlete/loneer-kavanagh",
            "perfil_b": "https://www.ufc.com/athlete/beta", "pais_a": {"codigo": "GB", "nombre": "England", "bandera": "EN"},
            "pais_b": {"codigo": "US", "nombre": "United States"}}]}])

    def test_nombre_literal_de_pareja_oficial_recupera_bandera_sin_fuzzy(self):
        self._kavanagh()
        fuente = {"nombre": "Lone’er Kavanagh"}
        d = I.metadatos("Lone'er Kavanagh", referencia=fuente)
        self.assertEqual((d["pais"]["codigo"], d["pais"]["bandera"]), ("GB", "EN"))
        self.assertIsNone(I.metadatos("Lone'er Kavanagh", referencia={"nombre": "Beta"})["pais"])
        self.assertIsNone(I.metadatos("Lone'er Kavanagh", "0000000000000006", referencia=fuente)["pais"])
        ruta = C.DATA_PROCESSED / "test_apostrofe.csv"
        DB.to_csv(pd.DataFrame([{"fighter_a": "Lone’er Kavanagh", "fighter_b": "Beta"}]), ruta, index=False)
        estado = {"datos": {"peleas": [{"a": "Lone'er Kavanagh", "b": "Beta", "p_a": .54}]}}
        salida = I.decorar_estado(estado, ruta)
        self.assertEqual(salida["datos"]["peleas"][0]["identidad_a"]["pais"]["bandera"], "EN")
        self.assertEqual(estado["datos"]["peleas"][0], {"a": "Lone'er Kavanagh", "b": "Beta", "p_a": .54})
        self.get.assert_not_called()

    def test_nombre_fuente_no_resuelve_homonimos_sin_identidad(self):
        self._kavanagh(duplicado=True)
        self.assertIsNone(I.metadatos("Lone'er Kavanagh", referencia={"nombre": "Lone’er Kavanagh"})["pais"])
        self.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
