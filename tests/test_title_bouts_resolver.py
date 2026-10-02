"""Resolución general de cinturones: HTML oficial simulado, siempre sin red."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from src import title_bouts as T


def _timestamp(fecha):
    return int(dt.datetime.fromisoformat(fecha).replace(tzinfo=dt.timezone.utc).timestamp())


def _listado(eventos, siguiente=None):
    html = "".join(f'<article class="c-card-event--result"><a href="{url}">Cartelera</a>'
                   f'<div data-main-card-timestamp="{_timestamp(fecha)}"></div></article>'
                   for url, fecha in eventos)
    return html + (f'<nav class="pager"><a href="{siguiente}">Más</a></nav>' if siguiente else "")


def _pelea(a="Ciryl Gane", b="Josh Hokit", etiquetas=("Heavyweight Title Bout",), estado=""):
    return (f'<div class="c-listing-fight" data-status="{estado}">'
            '<span class="c-listing-fight__corner-rank--champion">C</span>'
            f'<div class="c-listing-fight__corner-name--red">{a}</div>'
            f'<div class="c-listing-fight__corner-name--blue">{b}</div>'
            + "".join(f'<div class="c-listing-fight__class-text">{etiqueta}</div>' for etiqueta in etiquetas)
            + '<div>5 rounds</div></div>')


def _evento(peleas=None, fecha="2026-11-15T02:00:00"):
    return (f'<div class="c-hero__headline-suffix" data-timestamp="{_timestamp(fecha)}"></div>'
            + (peleas if peleas is not None else _pelea()))


class _Respuesta:
    def __init__(self, texto, status=200, url=""):
        self.text, self.status_code, self.url = texto, status, url


class Resolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_patch = mock.patch.object(T, "CACHE", Path(self.tmp.name) / "cache.json")
        self.cache_patch.start()
        self.reloj = mock.patch.object(T.time, "time", return_value=2_000_000_000.0)
        self.reloj.start()
        T._fallos.clear()
        self.url = T.BASE + "/event/ufc-334"
        self.listado = _Respuesta(_listado([(self.url, "2026-11-15T02:00:00")]))
        self.filas = [{"fighter_a": "Ciryl Gane", "fighter_b": "Josh Hokit"}]

    def tearDown(self):
        self.reloj.stop()
        self.cache_patch.stop()
        self.tmp.cleanup()

    def resolver(self, respuesta=None, fecha="2026-11-15"):
        with mock.patch.object(T.requests, "get", side_effect=[self.listado, respuesta or _Respuesta(_evento())]):
            return T.resolver_cartelera(self.filas, fecha)

    def test_title_bout_confirmado_y_fuente_de_pagina(self):
        self.assertEqual(self.resolver(), [{"es_titulo": True, "titulo_fuente": self.url}])

    def test_bout_normal_no_es_titulo_aunque_campeon_y_cinco_rounds(self):
        evento = _Respuesta(_evento(_pelea(etiquetas=("Heavyweight Bout",))))
        self.assertEqual(self.resolver(evento)[0]["es_titulo"], False)

    def test_etiqueta_ausente_desconocida_o_contradictoria_no_confirma(self):
        for etiquetas in ((), ("Heavyweight",), ("Bout",), ("Heavyweight Title Bout", "Heavyweight Bout")):
            T._fallos.clear()
            if T.CACHE.exists():
                T.CACHE.unlink()
            with self.subTest(etiquetas=etiquetas):
                self.assertIsNone(self.resolver(_Respuesta(_evento(_pelea(etiquetas=etiquetas))))[0]["es_titulo"])

    def test_pareja_invertida_y_alias_completo_son_la_misma_identidad(self):
        self.filas = [{"fighter_a": "Ian Garry", "fighter_b": "Islam Makhachev"}]
        evento = _Respuesta(_evento(_pelea("Islam Makhachev", "Ian Machado Garry")))
        self.assertTrue(self.resolver(evento)[0]["es_titulo"])

    def test_otro_rival_otra_fecha_o_nombres_parciales_no_reciben_titulo(self):
        for filas, fecha in (([{"fighter_a": "Ciryl Gane", "fighter_b": "Otro Rival"}], "2026-11-15"),
                             ([{"fighter_a": "Gane", "fighter_b": "Hokit"}], "2026-11-15"),
                             (self.filas, "2026-11-17")):
            self.filas = filas
            with self.subTest(fecha=fecha, filas=filas), mock.patch.object(T.requests, "get", side_effect=[self.listado, _Respuesta(_evento())]):
                self.assertIsNone(T.resolver_cartelera(filas, fecha)[0]["es_titulo"])

    def test_sabado_local_y_domingo_utc_coinciden(self):
        self.assertTrue(self.resolver(fecha="2026-11-14")[0]["es_titulo"])

    def test_fecha_individual_prevalece_y_sin_fecha_no_consulta_red(self):
        self.filas[0]["fecha_evento_utc"] = "2026-11-15"
        self.assertTrue(self.resolver(fecha="2027-01-01")[0]["es_titulo"])
        with mock.patch.object(T.requests, "get") as get:
            for fecha in (None, "2026-02-30", "hoy"):
                self.assertIsNone(T.resolver_cartelera([{"fighter_a": "Gane", "fighter_b": "Hokit"}], fecha)[0]["es_titulo"])
        get.assert_not_called()

    def test_duplicado_conflictivo_y_cancelacion_no_se_eligen(self):
        evento = _Respuesta(_evento(_pelea() + _pelea(etiquetas=("Heavyweight Bout",))))
        self.assertIsNone(self.resolver(evento)[0]["es_titulo"])
        T.CACHE.unlink()
        self.assertIsNone(self.resolver(_Respuesta(_evento(_pelea(estado="Cancelled"))))[0]["es_titulo"])

    def test_fecha_listado_y_pagina_distintas_no_se_mezclan(self):
        evento = _Respuesta(_evento(fecha="2026-11-14T02:00:00"))
        self.assertIsNone(self.resolver(evento)[0]["es_titulo"])

    def test_cache_fresco_no_repite_consultas(self):
        with mock.patch.object(T.requests, "get", side_effect=[self.listado, _Respuesta(_evento())]) as get:
            primera = T.resolver_cartelera(self.filas, "2026-11-15")
            self.assertEqual(T.resolver_cartelera(self.filas, "2026-11-15"), primera)
        self.assertEqual(get.call_count, 2)

    def test_cache_vencido_revalida_cambio_de_marcador(self):
        self.assertTrue(self.resolver()[0]["es_titulo"])
        with mock.patch.object(T.time, "time", return_value=2_000_000_000 + T.TTL_SEG + 1):
            self.assertFalse(self.resolver(_Respuesta(_evento(_pelea(etiquetas=("Heavyweight Bout",)))))[0]["es_titulo"])

    def test_cache_vencido_y_red_caida_no_resucitan_un_titulo(self):
        self.assertTrue(self.resolver()[0]["es_titulo"])
        with mock.patch.object(T.time, "time", return_value=2_000_000_000 + T.TTL_SEG + 1), \
                mock.patch.object(T.requests, "get", side_effect=requests.ConnectionError("sin red")) as get:
            self.assertIsNone(T.resolver_cartelera(self.filas, "2026-11-15")[0]["es_titulo"])
            self.assertIsNone(T.resolver_cartelera(self.filas, "2026-11-15")[0]["es_titulo"])
        self.assertEqual(get.call_count, 1)

    def test_challenge_o_html_sin_fecha_no_se_cachea_como_negativo(self):
        for respuesta in (_Respuesta("Checking your browser"), _Respuesta(_pelea())):
            T._fallos.clear()
            if T.CACHE.exists():
                T.CACHE.unlink()
            with mock.patch.object(T.requests, "get", side_effect=[self.listado, respuesta]):
                self.assertIsNone(T.resolver_cartelera(self.filas, "2026-11-15")[0]["es_titulo"])
            cache = json.loads(T.CACHE.read_text(encoding="utf-8"))
            self.assertNotIn(self.url, cache["paginas"])

    def test_paginacion_del_listado_encuentra_carteleras_anteriores(self):
        primera = _Respuesta(_listado([(self.url, "2026-11-15T02:00:00")], "?page=1"))
        segunda_url = T.BASE + "/event/ufc-330"
        segunda = _Respuesta(_listado([(segunda_url, "2026-08-16T01:00:00")]))
        evento = _Respuesta(_evento(fecha="2026-08-16T01:00:00"))
        with mock.patch.object(T.requests, "get", side_effect=[primera, segunda, evento]) as get:
            resultado = T.resolver_cartelera(self.filas, "2026-08-15")
        self.assertTrue(resultado[0]["es_titulo"])
        self.assertEqual(resultado[0]["titulo_fuente"], segunda_url)
        self.assertEqual(get.call_args_list[1].args[0], T.LISTADO + "?page=1")

    def test_redireccion_fuera_de_ufc_y_http_no_validan_titulo(self):
        for respuesta in (_Respuesta(_evento(), url="https://otro.example/event/ufc-334"),
                          _Respuesta(_evento(), status=403)):
            T._fallos.clear()
            if T.CACHE.exists():
                T.CACHE.unlink()
            self.assertIsNone(self.resolver(respuesta)[0]["es_titulo"])

    def test_solo_links_evento_oficiales_sin_query_o_fragmento(self):
        for url in ("https://otro.example/event/ufc-334", "/event/ufc-334?fake=1", "/event/ufc-334#fake"):
            with self.subTest(url=url):
                self.assertIsNone(T.parsear_listado(_listado([(url, "2026-11-15T02:00:00")])))

    def test_cache_json_danado_no_interrumpe_la_prediccion(self):
        T.CACHE.write_text("{incompleto", encoding="utf-8")
        self.assertTrue(self.resolver()[0]["es_titulo"])

    def test_cache_semanticamente_invalido_se_reconsulta(self):
        for datos in ({}, {"eventos": "parcial"}, {"eventos": [{"url": 1, "fecha": "2026-11-15"}]},
                      {"eventos": [{"url": "https://[roto", "fecha": "2026-11-15"}]}):
            T.CACHE.write_text(json.dumps({"version": T.VERSION, "paginas": {
                T.LISTADO: {"consultado": T.time.time(), "datos": datos}}}), encoding="utf-8")
            with self.subTest(datos=datos):
                self.assertTrue(self.resolver()[0]["es_titulo"])

    def test_pagina_con_anterior_y_siguiente_no_retrocede_ni_corta_por_fecha_cercana(self):
        primera = _Respuesta(_listado([(T.BASE + "/event/otro", "2026-11-14T02:00:00")], "?page=1"))
        segunda_html = _listado([(T.BASE + "/event/otro-dos", "2026-08-20T02:00:00")])
        segunda_html += '<nav class="pager"><a href="?page=0">Anterior</a><li class="pager__item--next"><a href="?page=2">Siguiente</a></li></nav>'
        tercera = _Respuesta(_listado([(self.url, "2026-11-15T02:00:00")]))
        otro_evento = _Respuesta(_evento(_pelea("Otro Nombre", "Otro Rival"), "2026-11-14T02:00:00"))
        with mock.patch.object(T.requests, "get", side_effect=[primera, _Respuesta(segunda_html), tercera, otro_evento, _Respuesta(_evento())]) as get:
            res = T.resolver_cartelera(self.filas, "2026-11-15")
        self.assertTrue(res[0]["es_titulo"])
        self.assertEqual(get.call_args_list[2].args[0], T.LISTADO + "?page=2")

    def test_pager_numerico_sin_rel_next_no_salta_paginas_intermedias(self):
        html = _listado([(self.url, "2026-11-15T02:00:00")])
        html += '<nav class="pager">' + ''.join(
            f'<a href="?page={n}">{n}</a>' for n in (0, 1, 2, 3, 30)) + '</nav>'
        self.assertEqual(T.parsear_listado(html, T.LISTADO + "?page=1")["siguiente"], T.LISTADO + "?page=2")


if __name__ == "__main__":
    unittest.main()
