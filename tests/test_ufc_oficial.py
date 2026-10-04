"""
Pruebas de src/ufc_oficial.py (la portada) y del filtro de ligas de Betano.

Sin red: los parsers reciben HTML/XML mínimo con la forma del de UFC, y la
portada se prueba con la caché.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import config as C
from src import ufc_oficial as U
from tests.util import aislar_base

# Base propia del módulo: nunca abrir data/ufc.db (ver tests/util.aislar_base).
setUpModule, tearDownModule = aislar_base()

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>
<item><title>UFC 332: Resultados Pesaje</title>
  <link>https://www.ufcespanol.com/news/ufc-332-resultados-pesaje</link>
  <pubDate>Vie, 2 Oct 2026 15:24:25 GMT</pubDate>
  <dc:creator>By Juanma Ibarra / IG: @juanma</dc:creator><dc:date>2026-10-02T12:24:25Z</dc:date></item>
<item><title>Fuera de UFC</title><link>https://ejemplo.com/nota</link><dc:date>2026-10-02T12:24:25Z</dc:date></item>
<item><title>Sin fecha</title><link>https://www.ufcespanol.com/news/x</link></item>
</channel></rss>"""

LISTADO = """<div>
<article class="c-card-event--result"><a href="/event/ufc-332">logo</a>
  <h3 class="c-card-event--result__headline"><a href="/event/ufc-332">Silva vs Wang</a></h3>
  <div class="c-card-event--result__date" data-main-card-timestamp="1791072000"
       data-prelims-card-timestamp="1791064800" data-early-card-timestamp=""></div>
  <div class="c-card-event--result__location"><h5>Delta Center</h5>
    <p class="address"><span class="locality">Salt Lake City</span>, <span class="administrative-area">UT</span>
    <span class="country">United States</span></p></div></article>
<article class="c-card-event--result"><a href="/event/ufc-fight-night-october-10-2026">x</a>
  <h3 class="c-card-event--result__headline">Allen vs Duncan</h3>
  <div class="c-card-event--result__date" data-main-card-timestamp="1791676800"></div></article>
<article class="c-card-event--result"><a href="https://otro.com/event/x">x</a>
  <div class="c-card-event--result__date" data-main-card-timestamp="1791676800"></div></article>
</div>"""


def _combate(rojo, azul, clase, estado=""):
    nombre = lambda n: (f'<span class="c-listing-fight__corner-given-name">{n.split()[0]}</span> '
                        f'<span class="c-listing-fight__corner-family-name">{n.split()[1]}</span>')
    return f"""<div class="c-listing-fight" data-status="{estado}">
      <div class="c-listing-fight__class c-listing-fight__class--desktop">
        <div class="c-listing-fight__corner-rank"><span>#1</span></div>
        <div class="c-listing-fight__class-text">{clase}</div>
        <div class="c-listing-fight__corner-rank"><span>#8</span></div></div>
      <div class="c-listing-fight__corner-name c-listing-fight__corner-name--red">{nombre(rojo)}</div>
      <div class="c-listing-fight__corner-name c-listing-fight__corner-name--blue">{nombre(azul)}</div></div>"""


EVENTO = f"""<div class="main-card">{_combate("Natalia Silva", "Wang Cong", "Women's Flyweight Title Bout")}
  {_combate("Deiveson Figueiredo", "Payton Talbott", "Peso gallo Bout")}</div>
<div class="fight-card-prelims">{_combate("Imanol Rodriguez", "Alden Coria", "Peso mosca Bout")}
  {_combate("Uno Cancelado", "Dos Cancelado", "Peso mosca Bout", estado="cancelled")}</div>
<div class="fight-card-prelims-early">{_combate("Court McGee", "Eric Nolan", "Peso welter Bout")}</div>"""


class Parsers(unittest.TestCase):

    def test_rss_toma_la_fecha_iso_y_descarta_lo_que_no_es_de_ufc(self):
        notas = U.parsear_rss(RSS)
        self.assertEqual(len(notas), 1)
        self.assertEqual(notas[0]["fecha"], "2026-10-02T12:24:25Z")      # dc:date, no el pubDate
        self.assertEqual(notas[0]["autor"], "Juanma Ibarra")
        self.assertRegex(notas[0]["id"], r"^[0-9a-f]{16}$")

    def test_listado_trae_horas_lugar_y_solo_eventos_de_ufc(self):
        eventos = U.parsear_listado(LISTADO)
        self.assertEqual([e["nombre"] for e in eventos], ["UFC 332", "UFC Fight Night"])
        e = eventos[0]
        self.assertEqual(e["inicio"], {"estelar": 1791072000, "preliminares": 1791064800, "early": None})
        self.assertEqual((e["titular"], e["ciudad"], e["pais"]), ("Silva vs Wang", "Salt Lake City", "United States"))

    def test_evento_trae_las_peleas_en_orden_con_seccion_y_titulo(self):
        peleas = U.parsear_evento(EVENTO)
        self.assertEqual([p["a"] for p in peleas], ["Natalia Silva", "Deiveson Figueiredo", "Imanol Rodriguez", "Court McGee"])
        self.assertEqual([p["seccion"] for p in peleas], ["estelar", "estelar", "preliminares", "early"])
        self.assertEqual([p["titulo"] for p in peleas], [True, False, False, False])
        self.assertEqual((peleas[0]["peso"], peleas[0]["rango_a"], peleas[0]["rango_b"]), ("Women's Flyweight", "#1", "#8"))

    def test_nombres_de_evento(self):
        self.assertEqual(U.nombre_evento("ufc-332"), "UFC 332")
        self.assertEqual(U.nombre_evento("cryptocom-ufc-331"), "UFC 331")
        self.assertEqual(U.nombre_evento("ufc-fight-night-october-10-2026"), "UFC Fight Night")
        self.assertEqual(U.nombre_evento("road-to-ufc-season-5-semifinals"), "Road to UFC")


class CacheYArchivos(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for parche in (mock.patch.object(U, "CACHE", self.tmp / "ufc.json"),
                       mock.patch.object(U, "IMAGENES", self.tmp / "img"),
                       mock.patch.object(C, "ROOT", self.tmp)):
            parche.start()
            self.addCleanup(parche.stop)

    def _cache(self, **datos):
        U.CACHE.write_text(json.dumps({"version": U.VERSION, **datos}), encoding="utf-8")

    def test_la_imagen_solo_se_baja_por_un_id_conocido(self):
        self._cache(noticias={"consultado": time.time(), "notas": [
            {"id": "0123456789abcdef", "imagen": "https://evil.com/x.jpg"}]})
        with mock.patch.object(U.requests, "get") as get:
            self.assertIsNone(U.imagen("../../etc/passwd"))
            self.assertIsNone(U.imagen("ffffffffffffffff"))            # no está en la caché
            self.assertIsNone(U.imagen("0123456789abcdef"))            # URL fuera de UFC
        get.assert_not_called()

    def test_sin_red_sirve_lo_guardado_marcado_como_desactualizado(self):
        self._cache(noticias={"consultado": 0, "notas": [{"id": "a", "titulo": "Vieja"}]})
        with mock.patch.object(U, "_get", return_value=None), mock.patch.object(U, "_fallos", {}):
            n = U.noticias()
        self.assertTrue(n["desactualizado"])
        self.assertEqual(n["notas"][0]["titulo"], "Vieja")

    def test_la_cartelera_confirmada_sale_con_estelar_al_final_y_titulo_explicito(self):
        evento = {"id": "e1", "nombre": "UFC 332", "titular": "Silva vs Wang",
                  "inicio": {"estelar": 1791072000}, "peleas": U.parsear_evento(EVENTO)}
        with mock.patch.object(U, "evento", lambda i: evento if i == "e1" else None):
            ruta = U.cartelera_csv("e1")
            with self.assertRaises(ValueError):
                U.cartelera_csv("otro")
        df = pd.read_csv(ruta)
        self.assertTrue(ruta.name.startswith("ufc_") and "ufc_332_silva_vs_wang" in ruta.name)
        self.assertEqual(df.iloc[-1]["fighter_a"], "Natalia Silva")
        self.assertEqual(df.iloc[-1]["segment"], "Estelar")
        self.assertEqual(df.iloc[-2]["segment"], "Co-estelar")
        self.assertEqual(df["es_titulo"].tolist().count(True), 1)
        self.assertTrue((df["titulo_fuente"] == "UFC.com").all())


class SoloUFCEnBetano(unittest.TestCase):

    def test_una_liga_con_nombre_ufc_pasa_sin_consultar_nada(self):
        from webui import engine as E
        self.assertTrue(E.es_ufc("UFC 332 - Silva vs Wang", [], set()))

    def test_encuentros_pasa_solo_si_sus_peleas_estan_confirmadas_por_ufc(self):
        from webui import engine as E
        confirmadas = {"|".join(sorted(("natalia silva", "wang cong")))}
        ufc = [{"fighter_a": "Natalia Silva", "fighter_b": "Cong Wang"}]          # alias verificado
        otra = [{"fighter_a": "Yoshinori Horie", "fighter_b": "Sho Patrick Usami"}]
        self.assertTrue(E.es_ufc("Encuentros", ufc, confirmadas))
        self.assertFalse(E.es_ufc("Encuentros", otra, confirmadas))
        self.assertFalse(E.es_ufc("Encuentros", ufc, set()))                     # sin dato, fuera

    def test_el_listado_dice_cuantas_ligas_se_ocultaron(self):
        from src import betano_scraper as bs
        from webui import engine as E
        ligas = [{"id": "1", "name": "UFC 332", "url": "/u"}, {"id": "2", "name": "Encuentros", "url": "/e"}]
        peleas = {"/u": [{"fighter_a": "Natalia Silva", "fighter_b": "Wang Cong", "start_ms": 1791072000000}],
                  "/e": [{"fighter_a": "Yoshinori Horie", "fighter_b": "Sho Patrick Usami", "start_ms": 1791072000000}]}
        with mock.patch.object(bs, "list_cards", lambda: ligas), \
                mock.patch.object(bs, "list_fights", lambda url: peleas[url]), \
                mock.patch.object(U, "pares_confirmados", lambda: set()):
            r = E.listar_carteleras()
        self.assertEqual([c["name"] for c in r["carteleras"]], ["UFC 332"])
        self.assertEqual(r["ocultas"], 1)


class Portada(unittest.TestCase):

    def test_responde_con_lo_guardado_y_refresca_aparte_si_vencio(self):
        from webui import engine as E
        guardado = ({"consultado": 0, "notas": [{"id": "a"}]}, {"consultado": 0, "proximos": [], "recientes": []}, True)
        hilos = []
        with mock.patch.object(U, "guardado", return_value=guardado), \
                mock.patch.object(U, "noticias", side_effect=AssertionError("no debe esperar a UFC")), \
                mock.patch.object(E.threading, "Thread", lambda target, daemon: hilos.append(target) or mock.Mock()):
            d = E.portada()
            E._REFRESCO_PORTADA.release()
        self.assertEqual(d["noticias"], [{"id": "a"}])
        self.assertTrue(d["actualizando"])
        self.assertEqual(len(hilos), 1)


if __name__ == "__main__":
    unittest.main()
