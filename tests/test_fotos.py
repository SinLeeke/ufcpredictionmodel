"""
Pruebas de webui/fotos.py con fixtures y respuestas simuladas, siempre sin red.
La verificación con la red real se hace en el PC del dueño.
"""
import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
from webui import fotos, server


class _Resp:
    def __init__(self, status=200, js=None, text="", content=b"", tipo="application/json"):
        self.status_code, self._js, self.text, self.content = status, js, text, content
        self.headers = {"content-type": tipo}

    def json(self):
        return self._js


def _wiki(*paginas):
    return _Resp(js={"query": {"pages": list(paginas)}})


def _pag(titulo, descripcion="American mixed martial artist", foto="https://upload.wikimedia.org/x.jpg"):
    p = {"title": titulo, "description": descripcion}
    if foto:
        p["thumbnail"] = {"source": foto}
    return p


JPG = _Resp(content=b"\xff\xd8jpeg", tipo="image/jpeg")
PNG = _Resp(content=b"\x89PNG\r\n\x1a\nretrato", tipo="image/png")
ESPN_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "espn_fotos.json")
                         .read_text(encoding="utf-8"))["players"]


def _espn(*jugadores, total=None):
    cantidad = total if total is not None else len(jugadores)
    return _Resp(js={"resultTypes": [{"type": "player", "totalFound": cantidad}],
                     "results": [{"type": "player", "totalFound": cantidad,
                                  "contents": list(jugadores)}]})


class _Base(unittest.TestCase):
    consultar_espn = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p_carpeta = mock.patch.object(fotos, "CARPETA", Path(self.tmp.name))
        self.p_carpeta.start()
        fotos._fallo_red.clear()
        # sherdog.DELAY es un sleep de cortesía: en pruebas no hace falta esperar.
        self.p_delay = mock.patch.object(fotos.sherdog, "DELAY", 0)
        self.p_delay.start()
        # Las pruebas de respaldos aíslan ESPN; su consulta se verifica aparte.
        self.p_espn = None if self.consultar_espn else mock.patch.object(fotos, "url_espn", return_value=None)
        if self.p_espn:
            self.p_espn.start()

    def tearDown(self):
        if self.p_espn:
            self.p_espn.stop()
        self.p_delay.stop()
        self.p_carpeta.stop()
        self.tmp.cleanup()


class ESPN(_Base):
    consultar_espn = True

    def _url(self, nombre, *jugadores, total=None):
        with mock.patch.object(fotos.requests, "get", return_value=_espn(*jugadores, total=total)):
            return fotos.url_espn(nombre)

    def test_retrato_oficial_se_guarda_como_png_y_se_reutiliza(self):
        jugador = ESPN_FIXTURE["topuria"]
        with mock.patch.object(fotos.requests, "get", side_effect=[_espn(jugador), PNG]) as get, \
                mock.patch.object(fotos, "url_wikipedia") as wiki, \
                mock.patch.object(fotos, "url_sherdog") as sherdog:
            ruta = fotos.foto("Ilia Topuria")
            self.assertEqual(fotos.foto("Ilia Topuria"), ruta)
        self.assertEqual(ruta.suffix, ".png")
        self.assertEqual(ruta.read_bytes(), PNG.content)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[1].args[0], jugador["image"]["default"])
        wiki.assert_not_called()
        sherdog.assert_not_called()
        self.assertEqual(fotos._indice()["ilia topuria"]["fuente"], "espn")

    def test_filtra_el_homonimo_de_nfl_y_las_noticias(self):
        self.assertEqual(self._url("Mike Davis", ESPN_FIXTURE["mike_nfl"], ESPN_FIXTURE["mike_mma"]),
                         ESPN_FIXTURE["mike_mma"]["image"]["default"])
        noticia = {**ESPN_FIXTURE["topuria"], "type": "article"}
        self.assertIsNone(self._url("Ilia Topuria", noticia))

    def test_bobby_green_e_ian_garry_usan_aliases_completos_verificados(self):
        for nombre, llave, consulta in (("Bobby Green", "king", "King Green"),
                                       ("Ian Garry", "garry", "Ian Machado Garry")):
            with self.subTest(nombre=nombre), \
                    mock.patch.object(fotos.requests, "get", return_value=_espn(ESPN_FIXTURE[llave])) as get:
                self.assertEqual(fotos.url_espn(nombre), ESPN_FIXTURE[llave]["image"]["default"])
                self.assertEqual(get.call_args.kwargs["params"]["query"], consulta)
        self.assertIsNone(self._url("Bobby King", ESPN_FIXTURE["king"]))
        otro_king = copy.deepcopy(ESPN_FIXTURE["king"])
        otro_king["uid"] = "s:3301~a:999"
        otro_king["link"]["web"] = "https://www.espn.com/mma/fighter/_/id/999/king-green"
        otro_king["image"]["default"] = "https://a.espncdn.com/i/headshots/mma/players/full/999.png"
        self.assertIsNone(self._url("Bobby Green", otro_king))

    def test_acentos_no_impiden_el_match_pero_otro_nombre_si(self):
        self.assertEqual(self._url("Uros Medic", ESPN_FIXTURE["medic"]),
                         ESPN_FIXTURE["medic"]["image"]["default"])
        self.assertIsNone(self._url("Ilia Perez", ESPN_FIXTURE["topuria"]))

    def test_dos_ids_mma_exactos_son_ambiguos_y_no_usan_respaldos(self):
        otra = copy.deepcopy(ESPN_FIXTURE["mike_mma"])
        otra["uid"] = "s:3301~a:999"
        otra["link"]["web"] = "https://www.espn.com/mma/fighter/_/id/999/mike-davis"
        otra["image"]["default"] = "https://a.espncdn.com/i/headshots/mma/players/full/999.png"
        with mock.patch.object(fotos.requests, "get", return_value=_espn(ESPN_FIXTURE["mike_mma"], otra)), \
                mock.patch.object(fotos, "url_wikipedia") as wiki, \
                mock.patch.object(fotos, "url_sherdog") as sherdog:
            self.assertIsNone(fotos.foto("Mike Davis"))
        wiki.assert_not_called()
        sherdog.assert_not_called()
        # El duplicado del MISMO ID no crea un segundo candidato.
        self.assertTrue(self._url("Mike Davis", ESPN_FIXTURE["mike_mma"], ESPN_FIXTURE["mike_mma"]))

    def test_rechaza_una_imagen_de_otro_id_y_un_placeholder(self):
        for src in (ESPN_FIXTURE["king"]["image"]["default"],
                    "https://a.espncdn.com/i/headshots/mma/players/full/default.png",
                    "https://otro.example/4350812.png"):
            with self.subTest(src=src):
                jugador = copy.deepcopy(ESPN_FIXTURE["topuria"])
                jugador["image"]["default"] = src
                self.assertIsNone(self._url("Ilia Topuria", jugador))

    def test_el_id_de_la_ficha_debe_coincidir_con_el_uid(self):
        jugador = copy.deepcopy(ESPN_FIXTURE["topuria"])
        jugador["link"]["web"] = ESPN_FIXTURE["king"]["link"]["web"]
        self.assertIsNone(self._url("Ilia Topuria", jugador))

    def test_no_se_elige_un_resultado_de_una_lista_truncada(self):
        self.assertEqual(self._url("Mike Davis", ESPN_FIXTURE["mike_mma"], total=101), fotos.AMBIGUO)

    def test_la_foto_antigua_se_actualiza_a_espn_sin_borrar_el_cache(self):
        anterior = fotos.CARPETA / "ilia_topuria.jpg"
        anterior.write_bytes(JPG.content)
        fotos._guardar_indice({"ilia topuria": {"nombre": "Ilia Topuria", "archivo": anterior.name,
                                               "fuente": "wikipedia", "consultado": 0}})
        with mock.patch.object(fotos.requests, "get", side_effect=[_espn(ESPN_FIXTURE["topuria"]), PNG]):
            nueva = fotos.foto("Ilia Topuria")
        self.assertEqual(nueva.suffix, ".png")
        self.assertTrue(anterior.exists())
        self.assertTrue(fotos._indice()["ilia topuria"]["espn_revisado"])

    def test_un_no_hay_foto_antiguo_tambien_se_revisa(self):
        fotos._guardar_indice({"ilia topuria": {"nombre": "Ilia Topuria", "archivo": None,
                                               "consultado": fotos.time.time()}})
        with mock.patch.object(fotos.requests, "get", side_effect=[_espn(ESPN_FIXTURE["topuria"]), PNG]):
            self.assertIsNotNone(fotos.foto("Ilia Topuria"))

    def test_espn_caido_conserva_la_foto_local_y_limita_los_reintentos(self):
        anterior = fotos.CARPETA / "ilia_topuria.jpg"
        anterior.write_bytes(JPG.content)
        fotos._guardar_indice({"ilia topuria": {"archivo": anterior.name, "fuente": "wikipedia"}})
        with mock.patch.object(fotos.requests, "get", side_effect=requests.ConnectionError("sin red")) as get:
            self.assertEqual(fotos.foto("Ilia Topuria"), anterior)
            self.assertEqual(fotos.foto("Ilia Topuria"), anterior)
        self.assertEqual(get.call_count, 1)
        self.assertFalse(fotos._indice()["ilia topuria"]["espn_revisado"])

    def test_espn_caido_aun_permite_un_respaldo_y_no_reintenta_de_inmediato(self):
        with mock.patch.object(fotos, "url_espn", side_effect=fotos.SinRed("sin red")) as espn, \
                mock.patch.object(fotos, "url_wikipedia", return_value="https://upload.wikimedia.org/x.jpg"), \
                mock.patch.object(fotos.requests, "get", return_value=JPG):
            ruta = fotos.foto("Ilia Topuria")
            self.assertEqual(fotos.foto("Ilia Topuria"), ruta)
        self.assertIsNotNone(ruta)
        self.assertEqual(espn.call_count, 1)

    def test_png_no_disponible_usa_el_respaldo(self):
        with mock.patch.object(fotos.requests, "get", side_effect=[_espn(ESPN_FIXTURE["topuria"]),
                                                                  _Resp(status=404), JPG]), \
                mock.patch.object(fotos, "url_wikipedia", return_value="https://upload.wikimedia.org/x.jpg"):
            ruta = fotos.foto("Ilia Topuria")
        self.assertEqual(ruta.suffix, ".jpg")
        self.assertEqual(fotos._indice()["ilia topuria"]["fuente"], "wikipedia")

    def test_respuesta_html_no_se_guarda_como_no_hay_foto(self):
        with mock.patch.object(fotos.requests, "get", return_value=_Resp(js=None)), \
                mock.patch.object(fotos, "url_wikipedia", side_effect=fotos.SinRed("sin red")), \
                mock.patch.object(fotos, "url_sherdog", return_value=None):
            self.assertIsNone(fotos.foto("Ilia Topuria"))
        self.assertNotIn("ilia topuria", fotos._indice())


class Wikipedia(_Base):

    def test_match_exacto_de_un_peleador_baja_la_foto_una_sola_vez(self):
        llamadas = []

        def get(url, **kw):
            llamadas.append(url)
            return _wiki(_pag("Steven Asplund")) if "api.php" in url else JPG

        with mock.patch.object(fotos.requests, "get", get):
            ruta = fotos.foto("Steven Asplund")
            otra = fotos.foto("Steven Asplund")
        self.assertIsNotNone(ruta)
        self.assertEqual(ruta.read_bytes(), b"\xff\xd8jpeg")
        self.assertEqual(ruta, otra)
        self.assertEqual(len(llamadas), 2, "la segunda vez sale del caché, sin red")

    def test_un_homonimo_de_otro_deporte_no_es_el_peleador(self):
        # Mike Davis, el futbolista, no es Mike Davis, el peleador.
        with mock.patch.object(fotos.requests, "get",
                               lambda url, **kw: _wiki(_pag("Mike Davis", "American football player"))):
            self.assertIsNone(fotos.url_wikipedia("Mike Davis"))

    def test_dos_peleadores_con_el_mismo_nombre_dan_silueta_y_no_se_pregunta_a_sherdog(self):
        dos = _wiki(_pag("Mike Davis (fighter)"), _pag("Mike Davis (mixed martial artist)"))
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: dos), \
                mock.patch.object(fotos, "url_sherdog") as sherdog:
            self.assertIsNone(fotos.foto("Mike Davis"))
        sherdog.assert_not_called()

    def test_una_redireccion_hacia_otro_nombre_no_vale(self):
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("Alex Pereira"))):
            self.assertIsNone(fotos.url_wikipedia("Alex Perez"))

    def test_los_acentos_y_el_segundo_apellido_no_impiden_el_match(self):
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("José Aldo"))):
            self.assertTrue(fotos.url_wikipedia("Jose Aldo"))
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("Ian Machado Garry"))):
            self.assertTrue(fotos.url_wikipedia("Ian Garry"))

    def test_sin_red_no_se_anota_que_no_tiene_foto(self):
        def falla(url, **kw):
            raise requests.ConnectionError("proxy")

        with mock.patch.object(fotos.requests, "get", falla):
            self.assertIsNone(fotos.foto("Steven Asplund"))
        self.assertNotIn("steven asplund", fotos._indice())
        # Pasada la espera, se vuelve a intentar y ahí sí la encuentra.
        fotos._fallo_red.clear()
        with mock.patch.object(fotos.requests, "get",
                               lambda url, **kw: _wiki(_pag("Steven Asplund")) if "api.php" in url else JPG):
            self.assertIsNotNone(fotos.foto("Steven Asplund"))

    def test_sin_foto_se_recuerda_y_no_se_pregunta_en_cada_repintado(self):
        llamadas = []

        def get(url, **kw):
            llamadas.append(url)
            return _wiki({"title": "Ty Cole Miller", "missing": True})

        with mock.patch.object(fotos.requests, "get", get), \
                mock.patch.object(fotos, "url_sherdog", lambda n: None):
            self.assertIsNone(fotos.foto("Ty Cole Miller"))
            self.assertIsNone(fotos.foto("Ty Cole Miller"))
        self.assertEqual(len(llamadas), 1)
        self.assertIsNone(fotos._indice()["ty cole miller"]["archivo"])


class Sherdog(_Base):

    def _buscador(self, *hrefs):
        return "".join(f'<a href="{h}">x</a>' for h in hrefs)

    def test_dos_fichas_que_calzan_dan_silueta(self):
        html = self._buscador("/fighter/Mike-Davis-1", "/fighter/Mike-Davis-2")
        with mock.patch.object(fotos.sherdog._sesion, "get", lambda url, **kw: _Resp(text=html)):
            self.assertIsNone(fotos.url_sherdog("Mike Davis"))

    def test_una_ficha_exacta_entrega_su_og_image(self):
        buscador = self._buscador("/fighter/Yadier-Delvalle-123", "/fighter/Yadier-Del-Valle-Perez-9")
        ficha = '<meta property="og:image" content="https://www.sherdog.com/image_crop/200/300/_images/fighter/y.jpg">'

        def get(url, **kw):
            return _Resp(text=buscador if "fightfinder" in url else ficha)

        with mock.patch.object(fotos.sherdog._sesion, "get", get):
            self.assertTrue(fotos.url_sherdog("Yadier Delvalle").endswith("/y.jpg"))

    def test_el_logo_de_sherdog_no_es_una_foto(self):
        buscador = self._buscador("/fighter/Ty-Cole-Miller-55")
        ficha = '<meta property="og:image" content="https://www.sherdog.com/img/sherdog-logo.png">'

        def get(url, **kw):
            return _Resp(text=buscador if "fightfinder" in url else ficha)

        with mock.patch.object(fotos.sherdog._sesion, "get", get):
            self.assertIsNone(fotos.url_sherdog("Ty Cole Miller"))


class Endpoint(_Base):

    def test_sin_foto_responde_204_para_que_la_ui_ponga_la_silueta(self):
        # 204 y no 404: "no hay foto" es lo normal para un debutante, y un 404
        # queda anotado como error en la consola del navegador.
        with mock.patch.object(fotos, "foto", lambda n: None):
            r = server.foto_peleador("Guilherme Pat")
        self.assertEqual(r.status_code, 204)

    def test_un_nombre_que_intenta_salir_de_la_carpeta_no_se_consulta(self):
        with mock.patch.object(fotos.requests, "get") as get:
            self.assertIsNone(fotos.foto("../../config"))
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
