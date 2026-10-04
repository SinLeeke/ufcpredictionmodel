"""Un cinturón requiere metadata explícita, nunca la fama o cinco rounds."""
import unittest
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

from src import card
from tests.util import card_aislado, predecir
from webui import engine
from tests.util import aislar_base

# Base propia del módulo: nunca abrir data/ufc.db (ver tests/util.aislar_base).
setUpModule, tearDownModule = aislar_base()


class TituloCSV(unittest.TestCase):
    def test_interpreta_booleanos_y_celdas_vacias_sin_usar_truthiness(self):
        for dato, esperado in ((True, True), (False, False), (1, True), (0.0, False),
                               ("sí", True), ("false", False), ("no", False),
                               ("", None), (float("nan"), None), (None, None),
                               ("Estelar 5R", None), (2, None)):
            with self.subTest(dato=dato):
                self.assertIs(card.bandera_titulo({"title_bout": dato}), esperado)

    def test_columnas_contradictorias_no_confirman_titulo(self):
        self.assertIsNone(card.bandera_titulo({"es_titulo": True, "title_bout": False}))

    def test_bandera_viaja_del_csv_a_la_ui_incluso_con_segmento_vacio(self):
        for columna in ("es_titulo", "title_bout"):
            with self.subTest(columna=columna), card_aislado() as env:
                csv = env["tmp"] / "c.csv"
                csv.write_text(f"fighter_a,fighter_b,segment,{columna}\n"
                               "Uno Uno,Dos Dos,,true\nTres Tres,Cuatro Cuatro,Estelar 5R,false\n"
                               "Cinco Cinco,Seis Seis,Estelar 5R,\n", encoding="utf-8")
                res = predecir(env["card"], csv)
                datos, _ = engine._serializar(res, csv)
            self.assertEqual([p["es_titulo"] for p in datos["peleas"]], [True, False, None])
            self.assertEqual([p["titulo_fuente"] for p in datos["peleas"]], ["CSV", "CSV", ""])

    def test_demo_antigua_no_inventa_titulo_y_alias_explicito_si_se_conserva(self):
        for extra, esperado in (({}, None), ({"title_bout": True}, True),
                                ({"es_titulo": "false"}, False)):
            pelea = {"a": "Nombre Famoso", "b": "Otro Campeon", "segmento": "Estelar 5R", **extra}
            engine._ampliar_pelea(pelea)
            self.assertIs(pelea["es_titulo"], esperado)

    def test_fuente_oficial_csv_se_conserva_en_payload(self):
        fuente = "https://www.ufc.com/event/ufc-334"
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b,es_titulo,titulo_fuente\n"
                           f"Uno Uno,Dos Dos,true,{fuente}\n", encoding="utf-8")
            res = predecir(env["card"], csv)
            datos, _ = engine._serializar(res, csv)
        self.assertTrue(datos["peleas"][0]["es_titulo"])
        self.assertEqual(datos["peleas"][0]["titulo_fuente"], fuente)
        self.assertFalse(datos["peleas"][0]["titulo_automatico"])


class ResolucionAutomaticaCSV(unittest.TestCase):
    fuente = "https://www.ufc.com/event/ufc-335"

    def test_csv_real_cong_wang_coincide_con_title_bout_wang_cong_oficial(self):
        from src import title_bouts as T
        from tests.test_title_bouts_resolver import _evento, _listado, _pelea, _Respuesta
        fuente = T.BASE + "/event/ufc-332"
        fecha = "2026-10-04T02:00:00"
        df = pd.DataFrame([{"fighter_a": "Natalia Silva", "fighter_b": "Cong Wang"}])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(T, "CACHE", Path(tmp) / "cache.json"), \
                mock.patch.dict(T._fallos, {}, clear=True), \
                mock.patch.object(T.requests, "get", side_effect=[
                    _Respuesta(_listado([(fuente, fecha)])),
                    _Respuesta(_evento(_pelea("Natalia Silva", "Wang Cong", ("Flyweight Title Bout",)), fecha))]):
            card.completar_titulos(df, "betano_2026-10-03_silva_vs_wang.csv")
        self.assertIs(df.loc[0, "es_titulo"], True)
        self.assertEqual(df.loc[0, "titulo_fuente"], fuente)
        self.assertTrue(df.loc[0, "titulo_automatico"])

    def test_desconocidos_se_resuelven_en_un_lote_y_manual_con_url_oficial_manda(self):
        df = pd.DataFrame([
            {"fighter_a": "Uno Uno", "fighter_b": "Dos Dos", "es_titulo": True, "titulo_fuente": self.fuente},
            {"fighter_a": "Tres Tres", "fighter_b": "Cuatro Cuatro", "es_titulo": False},
            {"fighter_a": "Cinco Cinco", "fighter_b": "Seis Seis"},
            {"fighter_a": "Siete Siete", "fighter_b": "Ocho Ocho"},
        ])
        with mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[
                {"es_titulo": True, "titulo_fuente": self.fuente},
                {"es_titulo": False, "titulo_fuente": self.fuente}]) as resolver:
            card.completar_titulos(df, "betano_2026-10-24_siete_vs_ocho.csv")
        resolver.assert_called_once()
        self.assertEqual([r["fighter_a"] for r in resolver.call_args.args[0]], ["Cinco Cinco", "Siete Siete"])
        self.assertEqual(resolver.call_args.kwargs["fecha_evento"], "2026-10-24")
        self.assertEqual(df["es_titulo"].tolist(), [True, False, True, False])
        self.assertEqual(df["titulo_automatico"].tolist(), [False, False, True, True])
        self.assertEqual(df.loc[0, "titulo_fuente"], self.fuente)

    def test_titulo_automatico_se_revalida_y_no_persiste_si_se_cancela_o_queda_desconocido(self):
        for actualizado in (False, None):
            with self.subTest(actualizado=actualizado):
                df = pd.DataFrame([{"fighter_a": "Uno Uno", "fighter_b": "Dos Dos", "es_titulo": True,
                                    "titulo_fuente": self.fuente, "titulo_automatico": True}])
                with mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[
                        {"es_titulo": actualizado, "titulo_fuente": self.fuente}]):
                    card.completar_titulos(df)
                self.assertIs(df.loc[0, "es_titulo"], actualizado)
                self.assertTrue(df.loc[0, "titulo_automatico"])
                self.assertEqual(df.loc[0, "titulo_fuente"], self.fuente if actualizado is not None else "")

    def test_nombre_de_archivo_debe_contener_fecha_betano_valida(self):
        for nombre in ("otro_2026-10-24.csv", "betano_2026-13-99_cruce.csv", "betano_2026-1-2_cruce.csv"):
            with self.subTest(nombre=nombre):
                df = pd.DataFrame([{"fighter_a": "Uno Uno", "fighter_b": "Dos Dos"}])
                with mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[
                        {"es_titulo": None, "titulo_fuente": ""}]) as resolver:
                    card.completar_titulos(df, nombre)
                self.assertIsNone(resolver.call_args.kwargs["fecha_evento"])

    def test_prediccion_serializa_resolucion_automatica_y_conserva_la_manual(self):
        with card_aislado() as env:
            csv = env["tmp"] / "betano_2026-10-24_tres_vs_cuatro.csv"
            csv.write_text("fighter_a,fighter_b,es_titulo,titulo_fuente\n"
                           f"Uno Uno,Dos Dos,true,{self.fuente}\nTres Tres,Cuatro Cuatro,,\n", encoding="utf-8")
            with mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[
                    {"es_titulo": True, "titulo_fuente": self.fuente}]):
                datos, _ = engine._serializar(predecir(env["card"], csv), csv)
        self.assertEqual([p["es_titulo"] for p in datos["peleas"]], [True, True])
        self.assertEqual([p["titulo_automatico"] for p in datos["peleas"]], [False, True])
        self.assertTrue(all(p["titulo_fuente"] == self.fuente for p in datos["peleas"]))

    def test_fallo_del_resolver_no_impide_cargar_y_no_arrastra_titulo_automatico(self):
        df = pd.DataFrame([{"fighter_a": "Uno Uno", "fighter_b": "Dos Dos", "es_titulo": True,
                            "titulo_fuente": self.fuente, "titulo_automatico": True}])
        with mock.patch.object(card, "_resolver_titulos_oficiales", side_effect=OSError("sin red")):
            card.completar_titulos(df)
        self.assertIsNone(df.loc[0, "es_titulo"])
        self.assertEqual(df.loc[0, "titulo_fuente"], "")

    def test_alias_automatico_previo_no_conflictua_ni_reintroduce_titulo_obsoleto(self):
        for previo, actualizado in ((False, True), (True, False), (True, None)):
            with self.subTest(previo=previo, actualizado=actualizado):
                df = pd.DataFrame([{"fighter_a": "Uno Uno", "fighter_b": "Dos Dos",
                                    "es_titulo": not previo, "title_bout": previo, "titulo_automatico": True}])
                with mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[
                        {"es_titulo": actualizado, "titulo_fuente": self.fuente}]):
                    card.completar_titulos(df)
                self.assertIs(card.bandera_titulo(df.iloc[0]), actualizado)
                self.assertIsNone(df.loc[0, "title_bout"])

    def test_columnas_manuales_contradictorias_quedan_sin_confirmar_y_no_consultan(self):
        df = pd.DataFrame([{"fighter_a": "Uno Uno", "fighter_b": "Dos Dos",
                            "es_titulo": True, "title_bout": False, "titulo_fuente": self.fuente}])
        with mock.patch.object(card, "_resolver_titulos_oficiales") as resolver:
            card.completar_titulos(df)
        resolver.assert_not_called()
        self.assertIsNone(card.bandera_titulo(df.iloc[0]))
        self.assertFalse(df.loc[0, "titulo_automatico"])


class PersistenciaTituloBetano(unittest.TestCase):
    fuente = "https://www.ufc.com/event/ufc-334"

    def _anterior(self, carpeta):
        ruta = Path(carpeta) / "c.csv"
        pd.DataFrame([{"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit",
                       "es_titulo": True, "titulo_fuente": self.fuente,
                       "fecha_evento_utc": "2026-11-15"}]).to_csv(ruta, index=False)
        return ruta

    def test_re_descarga_conserva_titulo_y_fuente_solo_en_misma_pareja_y_fecha(self):
        from src import betano_scraper as B
        filas = [
            {"fighter_a": "Josh Hokit", "fighter_b": "Ciryl Gane", "fecha_evento_utc": "2026-11-15"},
            {"fighter_a": "Ciryl Gane", "fighter_b": "Otro Rival", "fecha_evento_utc": "2026-11-15"},
            {"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "fecha_evento_utc": "2027-01-15"}]
        df = pd.DataFrame(filas, columns=B.COLUMNS)
        with tempfile.TemporaryDirectory() as tmp:
            B._conservar_titulos(df, self._anterior(tmp))
        self.assertIs(df.iloc[0]["es_titulo"], True)
        self.assertEqual(df.iloc[0]["titulo_fuente"], self.fuente)
        self.assertTrue(pd.isna(df.iloc[1]["es_titulo"]))
        self.assertTrue(pd.isna(df.iloc[2]["es_titulo"]))

    def test_override_explicito_actual_y_fecha_ausente_no_arrastran_bandera(self):
        from src import betano_scraper as B
        df = pd.DataFrame([
            {"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "fecha_evento_utc": "2026-11-15", "es_titulo": False},
            {"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit"}], columns=B.COLUMNS)
        with tempfile.TemporaryDirectory() as tmp:
            B._conservar_titulos(df, self._anterior(tmp))
        self.assertIs(df.iloc[0]["es_titulo"], False)
        self.assertTrue(pd.isna(df.iloc[1]["es_titulo"]))

    def test_scrape_fecha_utc_conserva_metadata_oficial(self):
        import datetime as dt
        from src import betano_scraper as B
        pelea = {"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "id": "1",
                 "start_ms": int(dt.datetime(2026, 11, 15, 2, tzinfo=dt.timezone.utc).timestamp() * 1000)}
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._anterior(tmp)
            with mock.patch.object(B, "find_card", return_value={"name": "UFC 334", "url": "/ufc334"}), \
                    mock.patch.object(B, "list_fights", return_value=[pelea]), \
                    mock.patch.object(B, "get_fight_odds", return_value={"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "odds_a": 1.5, "odds_b": 2.0}), \
                    mock.patch("builtins.print"):
                B.scrape_card("UFC 334", str(ruta))
            guardado = pd.read_csv(ruta).iloc[0]
        self.assertTrue(guardado["es_titulo"])
        self.assertEqual(guardado["titulo_fuente"], self.fuente)
        self.assertEqual(guardado["fecha_evento_utc"], "2026-11-15")

    def test_scrape_revalida_procedencia_automatica_en_la_misma_pareja_y_fecha(self):
        import datetime as dt
        from src import betano_scraper as B
        pelea = {"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "id": "1",
                 "start_ms": int(dt.datetime(2026, 11, 15, 2, tzinfo=dt.timezone.utc).timestamp() * 1000)}
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._anterior(tmp)
            anterior = pd.read_csv(ruta)
            anterior["titulo_automatico"] = True
            anterior.to_csv(ruta, index=False)
            with mock.patch.object(B, "find_card", return_value={"name": "UFC 334", "url": "/ufc334"}), \
                    mock.patch.object(B, "list_fights", return_value=[pelea]), \
                    mock.patch.object(B, "get_fight_odds", return_value={"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit", "odds_a": 1.5, "odds_b": 2.0}), \
                    mock.patch.object(card, "_resolver_titulos_oficiales", return_value=[{"es_titulo": False, "titulo_fuente": self.fuente}]) as resolver, \
                    mock.patch("builtins.print"):
                B.scrape_card("UFC 334", str(ruta))
            guardado = pd.read_csv(ruta).iloc[0]
        resolver.assert_called_once()
        self.assertFalse(guardado["es_titulo"])
        self.assertTrue(guardado["titulo_automatico"])
        self.assertEqual(guardado["fecha_evento_utc"], "2026-11-15")


if __name__ == "__main__":
    unittest.main()
