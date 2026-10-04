"""Cartelera completa, capturas persistentes e identidades sin red ni modelos."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd
import requests
from pandas.testing import assert_frame_equal

import config as C
from src import cartelera_completa as F, cuotas_fuentes as Q, rankings as R, storage as DB
from webui import catalogo as K, engine as E


class Explorar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"UFC_DB": str(Path(self.tmp.name) / "ufc.db")})
        p.start()
        self.addCleanup(p.stop)
        self.evento = {"id": "ufc-333", "nombre": "UFC 333", "titular": "Alpha vs Beta",
            "url": "https://www.ufc.com/event/ufc-333", "inicio": {"estelar": 1792281600},
            "peleas": [{"a": "Alpha", "b": "Beta", "seccion": "estelar", "titulo": True},
                {"a": "Gamma", "b": "Delta", "seccion": "estelar"}] +
                [{"a": f"Rojo {i}", "b": f"Azul {i}", "seccion": "preliminar"} for i in range(7)]}
        DB.write_text(C.DATA_RAW / "ufc_oficial.json", json.dumps({"eventos": {
            "proximos": [self.evento], "consultado": 1}}))

    def test_nueve_peleas_dos_con_cuotas_y_mercados_orientados(self):
        q = pd.DataFrame([{"fighter_a": "Beta", "fighter_b": "Alpha", "odds_a": 2.4,
            "odds_b": 1.7, "odds_a_ko": 5.0, "odds_b_sub": 4.0, "bookmaker": "Casa"},
            {"fighter_a": "Gamma", "fighter_b": "Delta", "odds_a": 2.0, "odds_b": 1.9}])
        d, n = F.fusionar(self.evento, q)
        self.assertEqual((len(d), n), (9, 2))
        self.assertEqual(d.fighter_a.tolist(), [r["fighter_a"] for r in F.filas_oficiales(self.evento)])
        self.assertEqual(d.odds_a.isna().sum(), 7)
        p = d.iloc[-1]
        self.assertEqual((p.odds_a, p.odds_b, p.odds_b_ko, p.odds_a_sub), (1.7, 2.4, 5.0, 4.0))
        self.assertTrue(p.es_titulo)
        self.assertEqual(p.segment, "Estelar")

    def test_cuota_ambigua_no_elimina_pelea_ni_elige_primera(self):
        q = pd.DataFrame([{"fighter_a": "Alpha", "fighter_b": "Beta", "odds_a": 1.7, "odds_b": b}
                          for b in (2.3, 2.4)])
        d, n = F.fusionar(self.evento, q)
        self.assertEqual((len(d), n), (9, 0))
        self.assertTrue(d.odds_a.isna().all())

    def _eventos(self):
        return [{"id": "event1", "titulo": "UFC 333", "fecha": "2026-10-18", "peleas": [
            {"a": "Alpha", "b": "Beta", "casas": {"book": {"casa": "Casa", "a": 1.7, "b": 2.4}}},
            {"a": "Gamma", "b": "Delta", "casas": {"book": {"casa": "Casa", "a": 2., "b": 1.9}}}]}]

    def test_snapshot_completo_reutilizable_y_modelo_sin_cuotas(self):
        s = Q._guardar("bfo", self._eventos())
        ruta, _, meta = F.desde_snapshot(s["snapshot"], "ufc-333", "book")
        primero = DB.read_csv(ruta)
        self.assertEqual((len(primero), meta["peleas_con_cuota"], meta["peleas_sin_cuota"]), (9, 2, 7))
        ruta2, _, _ = F.desde_snapshot(s["snapshot"], "ufc-333", "book")
        assert_frame_equal(primero, DB.read_csv(ruta2), check_exact=True)
        vacia, _, meta = F.desde_snapshot(s["snapshot"], "ufc-333", "")
        self.assertEqual(meta["peleas_sin_cuota"], 9)
        self.assertTrue(DB.read_csv(vacia).odds_a.isna().all())

    def test_precios_repetidos_discrepantes_quedan_sin_cuota(self):
        eventos = self._eventos()
        segundo = copy.deepcopy(eventos[0])
        segundo["id"] = "event2"
        segundo["peleas"][0]["casas"]["book"]["a"] = 1.8
        eventos.append(segundo)
        s = Q._guardar("bfo", eventos)
        resumen = F.resumen(s)["carteleras"][0]
        self.assertFalse(resumen["peleas"][0]["casas"])
        ruta, _, meta = F.desde_snapshot(s["snapshot"], "ufc-333", "book")
        self.assertEqual(meta["peleas_con_cuota"], 1)
        self.assertTrue(pd.isna(DB.read_csv(ruta).iloc[-1].odds_a))

    def test_historial_no_pisa_captura_actual_y_no_se_borra(self):
        actual = Q._guardar("odds-api", self._eventos())
        historico = Q._guardar("odds-api", [], "2020-06-06T00:00:00Z")
        self.assertEqual(Q.guardado("odds-api")["snapshot"], actual["snapshot"])
        with DB.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM cuotas_snapshots").fetchone()[0], 2)
        with self.assertRaises(ValueError):
            F.desde_snapshot(historico["snapshot"], "ufc-333", "book")

    def test_cache_persistente_no_consulta_red(self):
        s = Q._guardar("bfo", self._eventos())
        with mock.patch.object(Q.requests, "get") as get:
            d = Q.consultar("bfo")
        get.assert_not_called()
        self.assertEqual(d["snapshot"], s["snapshot"])
        self.assertTrue(d["cache"])

    def test_cartelera_archivada_sobrevive_cambio_del_calendario(self):
        s = Q._guardar("bfo", self._eventos())
        DB.write_text(C.DATA_RAW / "ufc_oficial.json", '{"eventos":{"proximos":[],"consultado":2}}')
        capturada = Q.captura(s["snapshot"])
        self.assertEqual(len(F.resumen(capturada)["carteleras"][0]["peleas"]), 9)
        ruta, _, _ = F.desde_snapshot(s["snapshot"], "ufc-333", "book")
        self.assertEqual(len(DB.read_csv(ruta)), 9)
        self.assertEqual(Q.historial()[0]["snapshot"], s["snapshot"])

    def test_captura_antigua_fija_el_corte(self):
        self.assertEqual(Q.corte_captura("2020-06-06T12:00:00+00:00"), "2020-06-06")

    def test_linea_en_vivo_archiva_solo_cambios_sin_mas_peticiones(self):
        cuotas = {"1": ("Alpha", "Beta", 1.7, 2.4)}
        with mock.patch.object(Q.requests, "get") as get:
            E._archivar_linea(cuotas, "UFC 333", "https://www.betanosports.com/ufc")
            E._archivar_linea(cuotas, "UFC 333", "https://www.betanosports.com/ufc")
            E._archivar_linea({"1": ("Alpha", "Beta", 1.8, 2.3)}, "UFC 333", "https://www.betanosports.com/ufc")
        get.assert_not_called()
        self.assertEqual(len(Q.historial("betano")), 2)

    def test_fallo_formato_no_sustituye_historial(self):
        s = Q._guardar("bfo", self._eventos())
        respuesta = mock.Mock(status_code=200, text="<h1>Service unavailable</h1>")
        with mock.patch.object(Q.requests, "get", return_value=respuesta):
            d = Q.consultar("bfo", forzar=True)
        self.assertTrue(d["desactualizado"])
        self.assertEqual(d["snapshot"], s["snapshot"])

    def test_odds_api_una_peticion_y_clave_no_filtrada(self):
        with mock.patch.dict(os.environ, {"THE_ODDS_API_KEY": "SECRETO"}), \
                mock.patch.object(Q.requests, "get", side_effect=requests.RequestException("apiKey=SECRETO")) as get:
            with self.assertRaises(ValueError) as e:
                Q.consultar("odds-api", forzar=True)
        self.assertNotIn("SECRETO", str(e.exception))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["params"]["markets"], "h2h")

    def test_no_mezcla_casas_ni_nombre_parecido_odds_api(self):
        base = {"id": "x", "sport_key": "mma_mixed_martial_arts", "home_team": "Alpha", "away_team": "Beta",
            "bookmakers": [{"key": "a", "title": "A", "markets": [{"key": "h2h", "outcomes": [{"name": "Alpha", "price": 1.7}]}]},
                {"key": "b", "title": "B", "markets": [{"key": "h2h", "outcomes": [{"name": "Beta", "price": 2.4}]}]}]}
        self.assertEqual(Q.parsear_odds_api([base]), [])
        base["bookmakers"][0]["markets"][0]["outcomes"].append({"name": "BETA", "price": 2.4})
        self.assertEqual(Q.parsear_odds_api([base]), [])

    @staticmethod
    def _html_bfo():
        return '''<div class="table-div" id="event333"><div class="table-header">
        <h2><a href="/events/ufc-333">UFC 333</a></h2><span class="table-header-date">October 18th</span></div>
        <div class="table-scroller"><table class="odds-table"><thead><tr><th>Fighter</th>
        <th data-b="casa"><a>Casa</a></th><th data-b="otra"><a>Otra</a></th>
        <th data-b="poly"><a>Polymarket</a></th></tr></thead><tbody>
        <tr><th><a href="/fighters/alpha-1">Alpha</a></th>
        <td><span id="oID1">−135</span></td><td></td><td><span id="oID3">+110</span></td></tr>
        <tr><th><a href="/fighters/beta-2">Beta</a></th>
        <td><span id="oID2">+115</span></td><td><span id="oID4">+120</span></td>
        <td><span id="oID5">−130</span></td></tr></tbody></table></div></div>'''

    def test_bfo_estructura_y_pareja_completa_de_una_casa(self):
        d = Q.parsear_bfo(self._html_bfo())
        self.assertEqual(len(d), 1)
        p = d[0]["peleas"][0]
        self.assertEqual(set(p["casas"]), {"casa"})
        self.assertEqual((p["a"], p["b"]), ("Alpha", "Beta"))
        self.assertEqual(p["casas"]["casa"]["a"], 1 + 100 / 135)
        self.assertEqual(p["casas"]["casa"]["b"], 2.15)
        self.assertEqual(d[0]["fuente"], "https://www.bestfightodds.com/events/ufc-333")

    def test_sha_cubre_roster_y_guardar_rechaza_json_no_finito(self):
        primero = Q._guardar("bfo", self._eventos())
        cambio = copy.deepcopy(self.evento)
        cambio["peleas"].pop()
        DB.write_text(C.DATA_RAW / "ufc_oficial.json", json.dumps({"eventos": {"proximos": [cambio], "consultado": 2}}))
        segundo = Q._guardar("bfo", self._eventos())
        with DB.connect() as con:
            hashes = [r[0] for r in con.execute("SELECT sha256 FROM cuotas_snapshots ORDER BY capturado")]
        self.assertNotEqual(*hashes)
        self.assertEqual(len(Q.captura(primero["snapshot"])["carteleras_guardadas"]["eventos"][0]["peleas"]), 9)
        self.assertEqual(len(Q.captura(segundo["snapshot"])["carteleras_guardadas"]["eventos"][0]["peleas"]), 8)
        malas = self._eventos()
        malas[0]["peleas"][0]["casas"]["book"]["a"] = float("nan")
        with self.assertRaises(ValueError):
            Q._guardar("bfo", malas)
        cambio["inicio"]["estelar"] = float("inf")
        DB.write_text(C.DATA_RAW / "ufc_oficial.json", json.dumps({"eventos": {"proximos": [cambio]}}))
        with self.assertRaises(ValueError):
            Q._guardar("bfo", self._eventos())
        self.assertEqual(len(Q.historial()), 2)

    def _guardar_legacy(self):
        from datetime import datetime, timezone
        with DB.connect() as con:
            Q._tablas(con)
            con.execute("INSERT INTO cuotas_snapshots(id,proveedor,capturado,contenido,sha256) VALUES(?,?,?,?,?)",
                ("legacy", "bfo", datetime.now(timezone.utc).isoformat(), json.dumps(self._eventos()), "old-sha"))

    def test_captura_legacy_no_toma_roster_actual_y_consulta_lo_renueva(self):
        self._guardar_legacy()
        viejo = F.resumen(Q.captura("legacy"))
        self.assertEqual(viejo["carteleras"], [])
        self.assertFalse(viejo["cartelera_conservada"])
        with self.assertRaises(ValueError):
            F.desde_snapshot("legacy", "ufc-333", "book")
        respuesta = mock.Mock(status_code=200, text=self._html_bfo())
        with mock.patch.object(Q.requests, "get", return_value=respuesta) as get:
            nuevo = Q.consultar("bfo")
            repetido = Q.consultar("bfo")
        self.assertEqual(get.call_count, 1)
        self.assertIn("carteleras_guardadas", nuevo)
        self.assertEqual(nuevo["snapshot"], repetido["snapshot"])
        self.assertEqual(len(Q.historial()), 2)

    def test_api_historica_no_toma_roster_actual_ni_capturas_futuras(self):
        historico = Q._guardar("odds-api", self._eventos(), "2020-06-06T00:00:00Z")
        self.assertEqual(F.resumen(historico)["carteleras"], [])
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"timestamp": "2020-06-06T01:00:00Z", "data": []}
        with mock.patch.dict(os.environ, {"THE_ODDS_API_KEY": "SECRETO"}), \
                mock.patch.object(Q.requests, "get", return_value=respuesta) as get:
            with self.assertRaises(ValueError):
                Q.consultar("odds-api", historico="2020-06-06T00:00:00Z", forzar=True)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(Q.historial()), 1)

    def test_api_sin_clave_no_llama_y_formato_invalido_no_es_vacio(self):
        with mock.patch.dict(os.environ, {"THE_ODDS_API_KEY": ""}), mock.patch.object(Q.requests, "get") as get:
            with self.assertRaises(ValueError):
                Q.consultar("odds-api", forzar=True)
        get.assert_not_called()
        for payload in ({"error": "bad"}, ["not-event"], None):
            with self.assertRaises(ValueError):
                Q.parsear_odds_api(payload)
        self.assertEqual(Q.parsear_odds_api([]), [])

    def test_metadatos_visuales_conservan_lados_sin_inferir_campeon(self):
        e = copy.deepcopy(self.evento)
        e["peleas"][0].update({"rango_a": "IC", "rango_b": "2", "peso": "Featherweight",
            "pais_a": {"codigo": "AU", "nombre": "Australia"}, "pais_b": None,
            "perfil_a": "https://www.ufc.com/athlete/alpha"})
        q = pd.DataFrame([{"fighter_a": "Beta", "fighter_b": "Alpha", "odds_a": 2.4, "odds_b": 1.7}])
        d, _ = F.fusionar(e, q)
        p = d.iloc[-1]
        self.assertEqual((p.rango_a, p.rango_b, p.pais_codigo_a, p.weight_class), ("IC", "2", "AU", "Featherweight"))
        self.assertEqual((p.odds_a, p.odds_b), (1.7, 2.4))
        self.assertNotIn("rango_a", F.filas_oficiales(self.evento)[-1])

    def _bio(self, nombres):
        DB.to_csv(pd.DataFrame([{"fighter_url": f"http://ufcstats.com/fighter-details/{i:016x}",
            "name": nombre, "dob": "1990-01-01", "height_cm": 180., "reach_cm": 185., "stance": "Orthodox"}
            for i, nombre in enumerate(nombres, 1)]), K.BIO, index=False)

    def test_homonimos_no_reciben_historial_ni_ficha_ajena(self):
        self._bio(["Jean Silva", "Jean Silva"])
        DB.to_csv(pd.DataFrame([{"fighter_a": "Jean Silva", "fighter_b": "Rival", "date": "2026-01-01"}]), K.FIGHTS, index=False)
        DB.write_text(K.CAREER, json.dumps({"Jean Silva": {"ufcstats_url": "http://ufcstats.com/fighter-details/0000000000000002", "slpm": 9}}))
        d = K.perfil("0000000000000001")
        self.assertTrue(d["homonimo"])
        self.assertEqual((d["historial"], d["metricas"], d["record"]), ([], {}, None))
        self.assertEqual(K.perfil("0000000000000002")["metricas"]["slpm"], 9)
        self.assertEqual(K.buscar("jean")["total"], 2)

    def test_historial_match_exacto_y_metricas_por_duracion(self):
        self._bio(["Alpha", "alpha", "Beta"])
        DB.to_csv(pd.DataFrame([{"fighter_a": "Alpha", "fighter_b": "Beta", "date": "2026-01-01",
            "winner": "Alpha", "method": "KO/TKO", "method_detail": "KO", "round": 2, "time": "0:00",
            "weight_class": "Lightweight", "event": "UFC", "fight_url": "pelea1"}]), K.FIGHTS, index=False)
        DB.to_csv(pd.DataFrame([{"fighter": "Alpha", "fight_url": "pelea1", "sig_landed": 20, "sig_att": 40,
            "td_landed": 2, "td_att": 4, "ctrl_sec": 60, "sub_att": 1, "kd": 1},
            {"fighter": "Beta", "fight_url": "pelea1", "sig_landed": 10, "sig_att": 30,
             "td_landed": 0, "td_att": 2}]), K.STATS, index=False)
        p = K.perfil("0000000000000001")
        self.assertEqual(p["muestra"], 1)
        self.assertEqual(p["metricas"]["slpm"], 4)
        self.assertEqual(p["metricas"]["td_avg"], 6)
        self.assertEqual(p["metricas"]["str_acc"], .5)
        self.assertEqual(p["historial"][0]["rival_id"], "0000000000000003")
        self.assertEqual(K.perfil("0000000000000002")["historial"], [])

    def test_refrescar_conserva_fecha_casa_y_proveedor(self):
        estado = E.Estado()
        estado.origen, estado.consulta, estado.titulo = "bfo", "UFC 333", "UFC 333"
        meta = {"capturado": "2026-10-03T00:00:00Z", "casa": "Casa", "proveedor": "bfo"}
        estado.datos = {"fuente_cuotas": meta}
        with mock.patch.object(E, "ESTADO", estado), mock.patch.object(E, "cargar") as cargar:
            self.assertEqual(E.refrescar(), "")
        self.assertEqual(cargar.call_args.kwargs["fuente_cuotas"], meta)

    def test_rankings_incompletos_no_reemplazan_snapshot(self):
        DB.write_text(K.RANKINGS, '{"divisiones":[],"fecha":"2026-01-01"}')
        with self.assertRaises(ValueError):
            R.parsear("<html>Sin rankings</html>")
        self.assertEqual(DB.read_json(K.RANKINGS)["fecha"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
