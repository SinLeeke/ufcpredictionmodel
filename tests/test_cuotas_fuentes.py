"""Fuentes de la capa de cuotas: Polymarket, The Odds API, BFO y Betano (sin red)."""
from __future__ import annotations

import json
import time
import unittest
from datetime import date
from unittest import mock

import requests

import config as C
from src.cuotas import historial as H
from src.cuotas.capa import Capa
from src.cuotas.fuentes import base as B
from src.cuotas.fuentes.betano import Betano
from src.cuotas.fuentes.bfo import BFO, evento_bfo, fecha_bfo
from src.cuotas.fuentes.odds_api import OddsAPI
from src.cuotas.fuentes.polymarket import (Polymarket, mercados_de_eventos,
                                         resultado_de_mercado, resueltos_de_eventos)
from src.cuotas.tiempo import a_iso
from tests.test_cuotas_capa import BaseCuotas

CLAVE_SECRETA = "CLAVE-SECRETA-123"


class _Resp:
    def __init__(self, status=200, datos=None, headers=None):
        self.status_code, self._datos, self.headers = status, datos, headers or {}

    def json(self):
        if isinstance(self._datos, Exception):
            raise self._datos
        return self._datos


def _evento_pm(a="Alex Pereira", b="Magomed Ankalaev", closed=False, tipo="moneyline"):
    """Recorte real de Gamma /events (3-oct-2026): outcomes y tokens vienen como texto JSON.
    La pelea es dentro de 3 días, para que la prueba no dependa de la fecha en que corre."""
    inicio = a_iso(time.time() + 3 * 86400)
    return {"id": "1", "title": f"UFC 999: {a} vs. {b} (Light Heavyweight, Main Card)",
            "slug": "ufc-x", "eventDate": inicio[:10], "startTime": inicio,
            "closed": closed, "markets": [
                {"sportsMarketType": "ufc_go_the_distance", "outcomes": '["Yes", "No"]',
                 "clobTokenIds": '["t9", "t10"]', "outcomePrices": '["0.3", "0.7"]'},
                {"sportsMarketType": tipo, "outcomes": json.dumps([a, b]),
                 "clobTokenIds": '["ta", "tb"]', "outcomePrices": '["0.6", "0.4"]',
                 "gameStartTime": inicio.replace("T", " "), "closed": False}]}


class PolymarketPrueba(BaseCuotas):

    def test_resultado_exige_cierre_final_y_precios_exactos(self):
        mercado = {"closed": True, "umaResolutionStatus": "resolved",
                   "outcomes": '["Alex Pereira", "Magomed Ankalaev"]',
                   "outcomePrices": '["1", "0"]'}
        self.assertEqual(resultado_de_mercado(mercado), "Alex Pereira")
        self.assertEqual(resultado_de_mercado({**mercado, "outcomePrices": '["0", "1"]'}), "Magomed Ankalaev")
        for cambio in ({"closed": False}, {"closed": "true"},
                       {"umaResolutionStatus": "proposed"}, {"umaResolutionStatus": "disputed"},
                       {"umaResolutionStatus": None}, {"outcomePrices": '["0.999", "0.001"]'},
                       {"outcomePrices": '["0.999999999999999999999", "0.000000000000000000001"]'},
                       {"outcomePrices": '["0.5", "0.5"]'}, {"outcomePrices": '["1", "1"]'},
                       {"outcomePrices": '["NaN", "0"]'}, {"outcomePrices": '["sNaN", "0"]'},
                       {"outcomes": '["Alex Pereira", "Alex Pereira"]'}):
            with self.subTest(cambio=cambio):
                self.assertIsNone(resultado_de_mercado({**mercado, **cambio}))

    def test_descubre_futuros_y_cierres_en_una_peticion_sin_mezclar_consenso(self):
        cerrado = _evento_pm(closed=True)
        cerrado["markets"][1].update({"closed": True, "umaResolutionStatus": "resolved", "outcomePrices": '["1", "0"]'})
        futuro = _evento_pm(a="Islam Makhachev", b="Arman Tsarukyan")
        self.assertEqual(len(mercados_de_eventos([cerrado, futuro])), 1)
        self.assertEqual(resueltos_de_eventos([cerrado, futuro])[0]["ganador"], "Alex Pereira")

        def resp(ruta, kw):
            if ruta == "events":
                self.assertEqual(kw["params"]["tag_id"], 279)
                self.assertIn("end_date_min", kw["params"])
                self.assertNotIn("closed", kw["params"])
                self.assertNotIn("active", kw["params"])
            return {"events": _Resp(datos=[cerrado, futuro]),
                    "midpoints": _Resp(datos={"ta": "0.65", "tb": "0.35"}),
                    "spreads": _Resp(datos={"ta": "0.02", "tb": "0.02"}),
                    "prices-history": _Resp(datos={"history": []})}[ruta]
        llamadas = []
        with self._rutas(resp, llamadas), mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0):
            fuente = Polymarket()
            crudas = fuente.obtener()
        self.assertEqual([ruta for _, ruta in llamadas].count("events"), 1)
        self.assertEqual(len(crudas), 1)
        self.assertEqual(crudas[0]["a_texto"], "Islam Makhachev")
        self.assertEqual(H.leer_cache("polymarket")["resueltos"][0]["ganador"], "Alex Pereira")
        capa = Capa([])
        capa.ingerir(fuente, crudas)
        self.assertEqual(len(capa.peleas()["peleas"]), 1)
        self.assertEqual(capa.peleas()["peleas"][0]["a"], "Arman Tsarukyan")

    def test_cierre_sin_resolucion_no_publica_ganador_y_final_se_conserva_en_cache(self):
        cerrado = _evento_pm(closed=True)
        cerrado["markets"][1].update({"closed": True, "umaResolutionStatus": "proposed", "outcomePrices": '["1", "0"]'})
        self.assertEqual(resueltos_de_eventos([cerrado]), [])
        llamadas = []
        with self._rutas(lambda ruta, kw: _Resp(datos=[cerrado]), llamadas), \
                mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0):
            self.assertEqual(Polymarket().obtener(), [])
        self.assertEqual(llamadas, [("GET", "events")])
        self.assertEqual(H.leer_cache("polymarket")["resueltos"], [])
        cerrado["markets"][1]["umaResolutionStatus"] = "resolved"
        H.escribir_cache("polymarket", {})
        with self._rutas(lambda ruta, kw: _Resp(datos=[cerrado]), []):
            self.assertEqual(Polymarket().obtener(), [])
        self.assertEqual(H.leer_cache("polymarket")["resueltos"][0]["ganador"], "Alex Pereira")

    def test_descubre_solo_el_moneyline_de_cada_pelea(self):
        inactivo = {**_evento_pm(), "active": False}
        ms = mercados_de_eventos([_evento_pm(), _evento_pm(closed=True), _evento_pm(tipo="totals"), inactivo])
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertEqual((m["evento"], m["a"], m["b"], m["tokens"]),
                         ("UFC 999", "Alex Pereira", "Magomed Ankalaev", ["ta", "tb"]))
        self.assertEqual(m["fecha"], m["inicio"][:10])
        self.assertTrue(m["inicio"].endswith("+00:00"))

    def _rutas(self, respuestas, llamadas):
        def request(self_s, metodo, url, **kw):
            llamadas.append((metodo, url.rsplit("/", 1)[-1]))
            r = respuestas(url.rsplit("/", 1)[-1], kw)
            return r
        return mock.patch("requests.sessions.Session.request", request)

    def test_precio_con_la_regla_del_spread_y_americana(self):
        def resp(ruta, kw):
            return {"events": _Resp(datos=[_evento_pm()]),
                    "midpoints": _Resp(datos={"ta": "0.65", "tb": "0.35"}),
                    "spreads": _Resp(datos={"ta": "0.02", "tb": "0.02"}),
                    "prices-history": _Resp(datos={"history": [{"t": 1790474425, "p": 0.6}]})}[ruta]
        llamadas = []
        with self._rutas(resp, llamadas), mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0), \
                mock.patch("src.cuotas.fuentes.polymarket.time.time",
                           return_value=1791400000.0):     # 2026-10-08: la pelea está cerca
            crudas = Polymarket().obtener()
        self.assertEqual(len(crudas), 1)
        c = crudas[0]
        self.assertEqual((c["a_prob"], c["b_prob"], c["casa"], c["evento"]), (0.65, 0.35, "Polymarket", "UFC 999"))
        self.assertEqual(len(c["historial"]), 1)
        self.assertNotIn("last-trades-prices", [r for _, r in llamadas])
        capa = Capa([])
        capa.ingerir(Polymarket(), crudas)
        cot = capa.peleas()["peleas"][0]["cotizaciones"][0]
        self.assertEqual((cot["a"]["americana"], cot["b"]["americana"], cot["tipo"]), (-186, 186, "mercado_prediccion"))

    def test_libro_vacio_usa_ultimo_transado_o_nada(self):
        # Compra a 0,01 y venta a 0,99 da un punto medio 0,50 que nadie transó.
        def resp(ruta, kw):
            return {"events": _Resp(datos=[_evento_pm()]),
                    "midpoints": _Resp(datos={"ta": "0.5", "tb": "0.5"}),
                    "spreads": _Resp(datos={"ta": "0.98", "tb": "0.98"}),
                    "last-trades-prices": _Resp(datos=[{"token_id": "ta", "price": "0.58"}]),
                    "prices-history": _Resp(datos={"history": []})}[ruta]
        with self._rutas(resp, []), mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0):
            c = Polymarket().obtener()[0]
        self.assertEqual((c["a_prob"], c["b_prob"]), (0.58, 0.42))

        def sin_transacciones(ruta, kw):
            r = resp(ruta, kw)
            return _Resp(datos=[]) if ruta == "last-trades-prices" else r
        H.escribir_cache("polymarket", {})
        with self._rutas(sin_transacciones, []), mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0):
            self.assertEqual(Polymarket().obtener(), [])

    def test_429_aplica_backoff_exponencial(self):
        def resp(ruta, kw):
            return _Resp(429)
        f = Polymarket()
        with self._rutas(resp, []):
            self.assertIsNone(f.ejecutar())
            e1 = f.espera(True)
            self.assertIsNone(f.ejecutar())
            e2 = f.espera(True)
        self.assertAlmostEqual(e1, B.BACKOFF_BASE_SEG, delta=2)
        self.assertAlmostEqual(e2, 2 * B.BACKOFF_BASE_SEG, delta=2)
        self.assertIn("429", f.estado(True)["motivo"])
        # Un OK reinicia el backoff: vuelve al intervalo normal de 30 s en vivo.
        ok = lambda ruta, kw: _Resp(datos=[]) if ruta == "events" else _Resp(datos={})  # noqa: E731
        H.escribir_cache("polymarket", {})
        with self._rutas(ok, []):
            self.assertEqual(f.ejecutar(), [])
        self.assertAlmostEqual(f.espera(True), 30, delta=2)
        self.assertIsNone(f.estado(True)["motivo"])

    def test_descubrimiento_en_cache(self):
        llamadas = []

        def resp(ruta, kw):
            return {"events": _Resp(datos=[_evento_pm()]),
                    "midpoints": _Resp(datos={"ta": "0.6", "tb": "0.4"}),
                    "spreads": _Resp(datos={"ta": "0.01", "tb": "0.01"}),
                    "prices-history": _Resp(datos={"history": []})}[ruta]
        with self._rutas(resp, llamadas), mock.patch("src.cuotas.fuentes.polymarket.PAUSA", 0):
            f = Polymarket()
            f.intervalo(True)
            f.obtener()
            f.obtener()
        self.assertEqual([r for _, r in llamadas].count("events"), 1)
        self.assertEqual([r for _, r in llamadas].count("midpoints"), 2)


class OddsAPIPrueba(BaseCuotas):

    def _respuesta(self, restantes="431", usados="69"):
        datos = [{"id": "e1", "sport_key": "mma_mixed_martial_arts", "commence_time": "2026-10-11T03:00:00Z",
                  "home_team": "Alex Pereira", "away_team": "Magomed Ankalaev",
                  "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": [
                      {"key": "h2h", "last_update": "2026-10-03T20:00:00Z", "outcomes": [
                          {"name": "Alex Pereira", "price": -150}, {"name": "Magomed Ankalaev", "price": 125}]}]}]}]
        return _Resp(datos=datos, headers={"x-requests-remaining": restantes, "x-requests-used": usados})

    def test_sin_key_queda_desactivada_y_no_llama(self):
        f = OddsAPI()
        self.assertFalse(f.activa())
        est = f.estado()
        self.assertFalse(est["activa"])
        self.assertIn("ODDS_API_KEY", est["motivo"])
        self.assertIsNone(f.espera(True))
        capa = Capa([f])
        self.assertEqual(capa.consultar_todas(), {})

    def test_una_llamada_trae_todo_y_lee_creditos(self):
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                mock.patch("src.cuotas.fuentes.odds_api.requests.get", return_value=self._respuesta()) as get:
            f = OddsAPI()
            crudas = f.ejecutar()
        self.assertEqual(get.call_count, 1)
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["markets"], params["oddsFormat"], params["regions"]), ("h2h", "american", "us"))
        self.assertEqual(len(crudas), 1)
        self.assertEqual((crudas[0]["a_americana"], crudas[0]["b_americana"], crudas[0]["casa"]), (-150, 125, "DraftKings"))
        self.assertEqual(f.creditos(), {"restantes": 431, "usados": 69, "bajos": False})
        self.assertEqual((f.intervalo(True), f.intervalo(False)), (120, 12 * 3600))
        # Sobrevive a un reinicio: no vuelve a llamar al tiro.
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA):
            g = OddsAPI()
            self.assertEqual(g.creditos()["restantes"], 431)
            self.assertGreater(g.espera(False), 3600)

    def test_pocos_creditos_bajan_la_frecuencia(self):
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                mock.patch("src.cuotas.fuentes.odds_api.requests.get", return_value=self._respuesta("50", "450")):
            f = OddsAPI()
            f.ejecutar()
            self.assertTrue(f.estado(True)["creditos"]["bajos"])
            self.assertEqual((f.intervalo(True), f.intervalo(False)), (600, 24 * 3600))
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                mock.patch("src.cuotas.fuentes.odds_api.requests.get", return_value=self._respuesta("2", "498")):
            f = OddsAPI()
            self.assertIsNotNone(f.ejecutar())
            self.assertEqual(f.intervalo(True), 24 * 3600)
            self.assertIn("agotados", f.estado(True)["motivo"])

    def test_la_clave_nunca_aparece_en_errores(self):
        url = f"https://api.the-odds-api.com/v4/sports/x/odds?apiKey={CLAVE_SECRETA}"
        casos = [requests.ConnectionError(f"Max retries exceeded with url: {url}"),
                 requests.HTTPError(f"401 Client Error for url: {url}")]
        for exc in casos:
            with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                    mock.patch("src.cuotas.fuentes.odds_api.requests.get", side_effect=exc):
                f = OddsAPI()
                self.assertIsNone(f.ejecutar())
                self.assertNotIn(CLAVE_SECRETA, json.dumps(f.estado()))
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                mock.patch("src.cuotas.fuentes.odds_api.requests.get", return_value=_Resp(401)):
            f = OddsAPI()
            self.assertIsNone(f.ejecutar())
            self.assertIn("401", f.estado()["motivo"])
            self.assertNotIn(CLAVE_SECRETA, json.dumps(f.estado()))

    def test_429_backoff(self):
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA), \
                mock.patch("src.cuotas.fuentes.odds_api.requests.get",
                           return_value=_Resp(429, headers={"Retry-After": "90"})):
            f = OddsAPI()
            self.assertIsNone(f.ejecutar())
            self.assertAlmostEqual(f.espera(True), 90, delta=2)

    def test_cuotas_fuentes_usa_config(self):
        # El endpoint viejo /api/cuotas?proveedor=odds-api toma la clave de config (.env).
        from src import cuotas_fuentes
        with mock.patch.object(C, "ODDS_API_KEY", CLAVE_SECRETA),                 mock.patch.object(C, "ODDS_API_REGION", "uk"),                 mock.patch("src.cuotas_fuentes.requests.get", return_value=_Resp(500)) as get:
            with self.assertRaises(ValueError) as e:
                cuotas_fuentes.consultar("odds-api", forzar=True)
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["apiKey"], params["regions"]), (CLAVE_SECRETA, "uk"))
        self.assertNotIn(CLAVE_SECRETA, str(e.exception))


class BFOPrueba(BaseCuotas):

    def test_fecha_y_evento(self):
        self.assertEqual(fecha_bfo("October 4th", date(2026, 10, 3)), "2026-10-04")
        self.assertEqual(fecha_bfo("January 10th", date(2026, 12, 20)), "2027-01-10")
        self.assertIsNone(fecha_bfo("Mañana"))
        self.assertEqual(evento_bfo("UFC 332 Odds"), "UFC 332")

    def test_envuelve_consultar_bfo_tal_cual(self):
        captura = {"capturado": "2026-10-03T20:00:00+00:00", "cache": False, "desactualizado": False,
                   "eventos": [{"titulo": "UFC 999 Odds", "fecha": "October 10th", "peleas": [
                       {"a": "Alex Pereira", "b": "Magomed Ankalaev", "casas": {
                           "24": {"casa": "Caesars", "a": 1 + 100 / 150, "b": 2.25},
                           "21": {"casa": "FanDuel", "a": 1 + 100 / 145, "b": 2.20}}}]}]}
        with mock.patch("src.cuotas_fuentes.consultar", return_value=captura) as consultar:
            f = BFO()
            crudas = f.ejecutar()
        consultar.assert_called_once_with("bfo")
        self.assertEqual(f.intervalo(True), 1800)       # el TTL de siempre, también en vivo
        self.assertEqual(sorted((c["casa"], c["a_americana"], c["b_americana"]) for c in crudas),
                         [("Caesars", -150, 125), ("FanDuel", -145, 120)])
        self.assertEqual(crudas[0]["timestamp"], "2026-10-03T20:00:00+00:00")
        self.assertEqual(crudas[0]["evento"], "UFC 999")

    def test_captura_vieja_sirve_pero_avisa(self):
        captura = {"capturado": "2026-10-03T20:00:00+00:00", "desactualizado": True, "eventos": [
            {"titulo": "UFC 999 Odds", "fecha": "October 10th", "peleas": [
                {"a": "Alex Pereira", "b": "Magomed Ankalaev", "casas": {"1": {"casa": "X", "a": 1.6, "b": 2.4}}}]}]}
        with mock.patch("src.cuotas_fuentes.consultar", return_value=captura):
            f = BFO()
            crudas = f.ejecutar()
        self.assertEqual(len(crudas), 1)
        self.assertIn("última captura", f.estado()["motivo"])

    def test_bfo_caido_sin_captura(self):
        with mock.patch("src.cuotas_fuentes.consultar", side_effect=ValueError("No pude consultar la fuente.")):
            f = BFO()
            self.assertIsNone(f.ejecutar())
        self.assertEqual(f.estado()["motivo"], "No pude consultar la fuente.")


class BetanoPasiva(BaseCuotas):

    def test_recibir_no_hace_ninguna_peticion(self):
        with mock.patch("requests.sessions.Session.request") as req:
            capa = Capa([Betano()])
            stats = capa.recibir_betano([("Alex Pereira", "Magomed Ankalaev", 1.667, 2.25)], "UFC 999")
            capa.consultar_todas()           # Betano es pasiva: no se consulta
            capa.estado()
            capa.peleas()
        self.assertEqual(req.call_count, 0)
        self.assertEqual(stats["guardadas"], 1)
        est = capa.estado()["fuentes"][0]
        self.assertIsNone(est["intervalo_seg"])
        self.assertIsNotNone(est["ultimo_ok"])
        cot = capa.peleas()["peleas"][0]["cotizaciones"][0]
        self.assertEqual((cot["fuente"], cot["a"]["americana"], cot["b"]["americana"]), ("betano", -150, 125))

    def test_la_capa_no_arranca_hilo_para_betano(self):
        capa = Capa([Betano()])
        capa.arrancar()
        self.assertEqual(capa._hilos, {})
        capa.detener()

    def test_refrescar_linea_sigue_con_una_peticion_y_entrega_a_la_capa(self):
        from webui import engine
        estado = engine.Estado()
        estado.origen, estado.consulta = "betano", "UFC 999"
        estado.datos = {"peleas": [], "patas": []}
        frescas = {"1": ("Alex Pereira", "Magomed Ankalaev", 1.667, 2.25)}
        entregas = []
        with mock.patch.object(engine, "ESTADO", estado), \
                mock.patch("src.betano_scraper.find_card", return_value={"url": "/x"}) as find, \
                mock.patch("src.betano_scraper.cuotas_rapidas", return_value=frescas) as rapidas, \
                mock.patch.object(engine, "_archivar_linea"), \
                mock.patch("src.value.cargar_calibrador", return_value=None), \
                mock.patch("src.cuotas.capa.recibir_betano",
                           side_effect=lambda c, e=None, f=None: entregas.append((list(c), e))):
            engine.refrescar_linea()
        self.assertEqual(rapidas.call_count, 1)
        self.assertEqual(find.call_count, 1)
        self.assertEqual(entregas, [([("Alex Pereira", "Magomed Ankalaev", 1.667, 2.25)], "UFC 999")])

    def test_si_la_capa_falla_el_ciclo_de_betano_sigue(self):
        from webui import engine
        with mock.patch("src.cuotas.capa.recibir_betano", side_effect=RuntimeError("x")):
            engine._entregar_a_capa([("A", "B", 1.5, 2.5)], "UFC")      # no lanza


if __name__ == "__main__":
    unittest.main()
