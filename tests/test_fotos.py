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


def _ufc(nombre="Josh Hokit", imagen="https://ufc.com/images/2026-06/HOKIT_JOSH_06-14.png"):
    return _Resp(text=f'<meta property="og:image" content="{imagen}">'
                      f'<h1 class="hero-profile__name">{nombre}</h1>')


class _Base(unittest.TestCase):
    consultar_espn = False
    consultar_ufc = False
    consultar_sherdog = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p_carpeta = mock.patch.object(fotos, "CARPETA", Path(self.tmp.name))
        self.p_carpeta.start()
        fotos._fallo_red.clear()
        # sherdog.DELAY es un sleep de cortesía: en pruebas no hace falta esperar.
        self.p_delay = mock.patch.object(fotos.sherdog, "DELAY", 0)
        self.p_delay.start()
        # La cortesía con UFC (DEMORA_UFC_SEG) se prueba aparte, sin esperar.
        self.p_demora = mock.patch.object(fotos, "DEMORA_UFC_SEG", 0)
        self.p_demora.start()
        self.addCleanup(self.p_demora.stop)
        # Las pruebas de respaldos aíslan ESPN; su consulta se verifica aparte.
        self.p_espn = None if self.consultar_espn else mock.patch.object(fotos, "url_espn", return_value=None)
        if self.p_espn:
            self.p_espn.start()
        self.p_ufc = None if self.consultar_ufc else mock.patch.object(fotos, "url_ufc", return_value=None)
        self.p_sherdog = None if self.consultar_sherdog else mock.patch.object(fotos, "url_sherdog", return_value=None)
        for parche in (self.p_ufc, self.p_sherdog):
            if parche:
                parche.start()

    def tearDown(self):
        if self.p_espn:
            self.p_espn.stop()
        for parche in (self.p_ufc, self.p_sherdog):
            if parche:
                parche.stop()
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

    def test_la_foto_verificada_sigue_disponible_sin_red(self):
        anterior = fotos.CARPETA / "ilia_topuria.png"
        anterior.write_bytes(PNG.content)
        fotos._guardar_indice({"ilia topuria": {"archivo": anterior.name, "fuente": "espn",
                                               "url": ESPN_FIXTURE["topuria"]["image"]["default"]}})
        with mock.patch.object(fotos.requests, "get", side_effect=requests.ConnectionError("sin red")) as get:
            self.assertEqual(fotos.foto("Ilia Topuria"), anterior)
            self.assertEqual(fotos.foto("Ilia Topuria"), anterior)
        get.assert_not_called()

    def test_espn_caido_aun_permite_un_respaldo_y_no_reintenta_de_inmediato(self):
        with mock.patch.object(fotos, "url_espn", side_effect=fotos.SinRed("sin red")) as espn, \
                mock.patch.object(fotos, "url_sherdog", return_value="https://www.sherdog.com/_images/fighter/topuria.jpg"), \
                mock.patch.object(fotos.requests, "get", return_value=JPG):
            ruta = fotos.foto("Ilia Topuria")
            self.assertEqual(fotos.foto("Ilia Topuria"), ruta)
        self.assertIsNotNone(ruta)
        self.assertEqual(espn.call_count, 1)

    def test_png_no_disponible_usa_el_respaldo(self):
        with mock.patch.object(fotos.requests, "get", side_effect=[_espn(ESPN_FIXTURE["topuria"]),
                                                                  _Resp(status=404), JPG]), \
                mock.patch.object(fotos, "url_sherdog", return_value="https://www.sherdog.com/_images/fighter/topuria.jpg"):
            ruta = fotos.foto("Ilia Topuria")
        self.assertEqual(ruta.suffix, ".jpg")
        self.assertEqual(fotos._indice()["ilia topuria"]["fuente"], "sherdog")

    def test_respuesta_html_no_se_guarda_como_no_hay_foto(self):
        with mock.patch.object(fotos.requests, "get", return_value=_Resp(js=None)), \
                mock.patch.object(fotos, "url_wikipedia", side_effect=fotos.SinRed("sin red")), \
                mock.patch.object(fotos, "url_sherdog", return_value=None):
            self.assertIsNone(fotos.foto("Ilia Topuria"))
        self.assertNotIn("ilia topuria", fotos._indice())


class UFC(_Base):
    def test_ficha_verificada_reintenta_negativo_y_reutiliza_sin_red(self):
        fotos._guardar_indice({"jean silva": {"archivo": None, "fuente": None,
            "consultado": fotos.time.time(), "version_retratos": fotos.VERSION_RETRATOS,
            "prioridad_revisada": True}})
        url = "https://ufc.com/images/2026-09/SILVA_JEAN_09-12.png"
        with mock.patch.object(fotos, "url_ufc", return_value=url) as ufc, \
                mock.patch.object(fotos, "url_espn", return_value=fotos.AMBIGUO) as espn, \
                mock.patch.object(fotos.requests, "get", return_value=PNG):
            ruta = fotos.foto("Jean Silva")
            self.assertIsNotNone(ruta)
            self.assertEqual(ruta.read_bytes(), PNG.content)
        ufc.assert_called_once_with("Jean Silva")
        espn.assert_not_called()
        with mock.patch.object(fotos.requests, "get", side_effect=AssertionError("red")), \
                mock.patch.object(fotos, "url_ufc", side_effect=AssertionError("red")):
            self.assertEqual(fotos.foto("Jean Silva"), ruta)

    def test_nuevo_negativo_verificado_conserva_el_plazo(self):
        with mock.patch.object(fotos, "url_ufc", return_value=None) as ufc:
            self.assertIsNone(fotos.foto("Jean Silva"))
            self.assertIsNone(fotos.foto("Jean Silva"))
        ufc.assert_called_once()

    def test_delgado_verifica_su_nombre_oficial_completo(self):
        url = "https://ufc.com/images/2026-09/DELGADO_JOSE_MIGUEL_09-12.png"
        with mock.patch.object(fotos.requests, "get", return_value=_ufc("Jose Miguel Delgado", url)) as get:
            self.assertEqual(fotos.url_ufc("Jose Delgado"), url)
        self.assertTrue(get.call_args.args[0].endswith("/athlete/jose-miguel-delgado"))
        with mock.patch.object(fotos.requests, "get", return_value=_ufc("Jose Delgado", url)):
            self.assertIsNone(fotos.url_ufc("Jose Delgado"))

    consultar_ufc = True

    def test_josh_tiene_retrato_oficial_y_reemplaza_la_foto_de_prensa(self):
        anterior = fotos.CARPETA / "josh_hokit.jpg"
        anterior.write_bytes(JPG.content)
        fotos._guardar_indice({"josh hokit": {"archivo": anterior.name, "fuente": "wikipedia",
                                             "espn_revisado": True}})
        with mock.patch.object(fotos.requests, "get", side_effect=[_ufc(), PNG]) as get, \
                mock.patch.object(fotos, "url_espn") as espn:
            ruta = fotos.foto("Josh Hokit")
            self.assertEqual(fotos.foto("Josh Hokit"), ruta)
        self.assertEqual(ruta.suffix, ".png")
        self.assertEqual(get.call_count, 2)
        self.assertTrue(anterior.exists(), "la migración no borra los archivos antiguos")
        self.assertEqual(fotos._indice()["josh hokit"]["fuente"], "ufc")
        espn.assert_not_called()

    def test_wang_resuelve_el_nombre_invertido_y_el_negativo_antiguo(self):
        fotos._guardar_indice({"wang cong": {"archivo": None, "espn_revisado": True,
                                             "consultado": fotos.time.time()}})
        imagen = "https://ufc.com/images/2026-10/CONG_WANG_10-03.png"
        with mock.patch.object(fotos.requests, "get", side_effect=[_ufc("Wang Cong", imagen), PNG]) as get, \
                mock.patch.object(fotos, "url_espn", return_value=fotos.AMBIGUO) as espn:
            self.assertIsNotNone(fotos.foto("Wang Cong"))
        espn.assert_not_called()
        self.assertEqual(get.call_args_list[0].args[0], "https://www.ufc.com/athlete/wang-cong")
        with mock.patch.object(fotos.requests, "get", return_value=_ufc("Wang Cong", imagen)) as get:
            self.assertEqual(fotos.url_ufc("Cong Wang"), imagen)
        self.assertEqual(get.call_args.args[0], "https://www.ufc.com/athlete/wang-cong")

    def test_rechaza_otra_identidad_y_fotos_de_eventos_logos_y_otros_dominios(self):
        with mock.patch.object(fotos.requests, "get", return_value=_ufc("Derrick Lewis")):
            self.assertIsNone(fotos.url_ufc("Josh Hokit"))
        for imagen in ("https://ufc.com/images/2026-06/press-conference.jpg",
                       "https://ufc.com/images/2026-06/LEWIS_DERRICK_06-14.png",
                       "https://ufc.com/images/logo.png",
                       "https://otro.example/images/HOKIT_JOSH_06-14.png"):
            with self.subTest(imagen=imagen), \
                    mock.patch.object(fotos.requests, "get", return_value=_ufc(imagen=imagen)):
                self.assertIsNone(fotos.url_ufc("Josh Hokit"))

    def test_headshot_exige_alt_y_nombre_de_archivo(self):
        src = "https://ufc.com/images/styles/event_results_athlete_headshot/s3/2026-06/HOKIT_JOSH_06-14.png?itok=x"
        cuerpo = '<h1 class="hero-profile__name">Josh Hokit</h1>'
        for alt, esperado in (("Josh Hokit", src), ("Derrick Lewis", None)):
            html = cuerpo + f'<img class="image-style-event-results-athlete-headshot" alt="{alt}" src="{src}">'
            with self.subTest(alt=alt), mock.patch.object(fotos.requests, "get", return_value=_Resp(text=html)):
                self.assertEqual(fotos.url_ufc("Josh Hokit"), esperado)

    def test_sin_red_no_muestra_la_foto_editorial_antigua_ni_insiste(self):
        anterior = fotos.CARPETA / "josh_hokit.jpg"
        anterior.write_bytes(JPG.content)
        fotos._guardar_indice({"josh hokit": {"archivo": anterior.name, "fuente": "wikipedia",
                                             "espn_revisado": True}})
        with mock.patch.object(fotos.requests, "get", side_effect=requests.ConnectionError("sin red")) as get:
            self.assertIsNone(fotos.foto("Josh Hokit"))
            self.assertIsNone(fotos.foto("Josh Hokit"))
        self.assertEqual(get.call_count, 1)
        self.assertTrue(anterior.exists())

    def test_404_no_es_un_fallo_de_red_pero_un_503_si(self):
        with mock.patch.object(fotos.requests, "get", return_value=_Resp(status=404)):
            self.assertIsNone(fotos.url_ufc("Ty Cole Miller"))
        with mock.patch.object(fotos.requests, "get", return_value=_Resp(status=503)):
            with self.assertRaises(fotos.SinRed):
                fotos.url_ufc("Josh Hokit")

    def test_un_logo_previamente_cacheado_no_se_reutiliza(self):
        anterior = fotos.CARPETA / "lucas_armand.png"
        anterior.write_bytes(PNG.content)
        fotos._guardar_indice({"lucas armand": {"archivo": anterior.name, "fuente": "sherdog",
                                               "url": "https://www2-cdn.sherdog.com/apple-touch-icon.png",
                                               "espn_revisado": True}})
        with mock.patch.object(fotos, "url_ufc", return_value=None), \
                mock.patch.object(fotos, "url_wikipedia") as wiki:
            self.assertIsNone(fotos.foto("Lucas Armand"))
        wiki.assert_not_called()
        self.assertTrue(anterior.exists())


class Wikipedia(_Base):

    def test_el_resolver_editorial_verifica_el_nombre_del_articulo(self):
        with mock.patch.object(fotos.requests, "get", return_value=_wiki(_pag("Steven Asplund"))):
            self.assertEqual(fotos.url_wikipedia("Steven Asplund"), "https://upload.wikimedia.org/x.jpg")

    def test_un_homonimo_de_otro_deporte_no_es_el_peleador(self):
        # Mike Davis, el futbolista, no es Mike Davis, el peleador.
        with mock.patch.object(fotos.requests, "get",
                               lambda url, **kw: _wiki(_pag("Mike Davis", "American football player"))):
            self.assertIsNone(fotos.url_wikipedia("Mike Davis"))

    def test_dos_peleadores_con_el_mismo_nombre_son_ambiguos(self):
        dos = _wiki(_pag("Mike Davis (fighter)"), _pag("Mike Davis (mixed martial artist)"))
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: dos):
            self.assertEqual(fotos.url_wikipedia("Mike Davis"), fotos.AMBIGUO)

    def test_una_redireccion_hacia_otro_nombre_no_vale(self):
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("Alex Pereira"))):
            self.assertIsNone(fotos.url_wikipedia("Alex Perez"))

    def test_los_acentos_y_el_segundo_apellido_no_impiden_el_match(self):
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("José Aldo"))):
            self.assertTrue(fotos.url_wikipedia("Jose Aldo"))
        with mock.patch.object(fotos.requests, "get", lambda url, **kw: _wiki(_pag("Ian Machado Garry"))):
            self.assertTrue(fotos.url_wikipedia("Ian Garry"))

    def test_sin_red_no_se_anota_que_no_tiene_foto(self):
        with mock.patch.object(fotos, "url_ufc", side_effect=fotos.SinRed("sin red")):
            self.assertIsNone(fotos.foto("Steven Asplund"))
        self.assertNotIn("steven asplund", fotos._indice())
        # Pasada la espera, se vuelve a intentar y ahí sí la encuentra.
        fotos._fallo_red.clear()
        with mock.patch.object(fotos, "url_sherdog", return_value="https://www.sherdog.com/_images/fighter/asplund.jpg"), \
                mock.patch.object(fotos.requests, "get", return_value=JPG):
            self.assertIsNotNone(fotos.foto("Steven Asplund"))

    def test_sin_foto_se_recuerda_y_no_se_pregunta_en_cada_repintado(self):
        with mock.patch.object(fotos, "url_ufc", return_value=None) as ufc:
            self.assertIsNone(fotos.foto("Ty Cole Miller"))
            self.assertIsNone(fotos.foto("Ty Cole Miller"))
        self.assertEqual(ufc.call_count, 1)
        self.assertIsNone(fotos._indice()["ty cole miller"]["archivo"])


class Sherdog(_Base):
    consultar_sherdog = True

    def _buscador(self, *hrefs):
        return "".join(f'<a href="{h}">x</a>' for h in hrefs)

    def test_dos_fichas_que_calzan_dan_silueta(self):
        html = self._buscador("/fighter/Mike-Davis-1", "/fighter/Mike-Davis-2")
        with mock.patch.object(fotos.sherdog._sesion, "get", lambda url, **kw: _Resp(text=html)):
            self.assertEqual(fotos.url_sherdog("Mike Davis"), fotos.AMBIGUO)

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

    def test_favicon_y_fotos_de_otros_dominios_no_son_retratos(self):
        buscador = self._buscador("/fighter/Lucas-Armand-55")
        for src in ("https://www2-cdn.sherdog.com/apple-touch-icon.png",
                    "https://www.sherdog.com/_images/news/fight.jpg",
                    "https://otro.example/_images/fighter/lucas.jpg"):
            ficha = f'<meta property="og:image" content="{src}">'
            with self.subTest(src=src), mock.patch.object(fotos.sherdog._sesion, "get",
                     lambda url, **kw: _Resp(text=buscador if "fightfinder" in url else ficha)):
                self.assertIsNone(fotos.url_sherdog("Lucas Armand"))


def _png(tipo_color=6, trns=False):
    """Cabecera PNG mínima: firma, IHDR (con su tipo de color) y opcional tRNS."""
    ihdr = (13).to_bytes(4, "big") + b"IHDR" + (8).to_bytes(4, "big") * 2 + bytes([8, tipo_color, 0, 0, 0]) + b"\0" * 4
    extra = (2).to_bytes(4, "big") + b"tRNS" + b"\0\0" + b"\0" * 4 if trns else b""
    return b"\x89PNG\r\n\x1a\n" + ihdr + extra + (0).to_bytes(4, "big") + b"IDAT" + b"\0" * 4


ESTILO = "https://ufc.com/images/styles/event_results_athlete_headshot/s3/2025-01/MAKHACHEV_ISLAM_L_BELT_01-18.png?itok=a1"
ORIGINAL = "https://ufc.com/images/2025-01/MAKHACHEV_ISLAM_L_BELT_01-18.png"


class AltaResolucion(_Base):
    """Retrato de estudio de UFC a resolución completa para perfil, listado y Rankings."""

    def setUp(self):
        super().setUp()
        # Estas pruebas cubren el respaldo del headshot: sin cuerpo entero en la ficha.
        p = mock.patch.object(fotos, "url_ufc_cuerpo", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_original_sin_estilo_y_marcas_de_estudio_tras_el_nombre_completo(self):
        self.assertEqual(fotos.original_ufc(ESTILO), ORIGINAL)
        self.assertTrue(fotos._retrato_ufc(ORIGINAL, "Islam Makhachev"))
        self.assertTrue(fotos._retrato_ufc(ESTILO, "Islam Makhachev"))
        # Las marcas no reemplazan una palabra del nombre ni lo completan.
        self.assertFalse(fotos._retrato_ufc("https://ufc.com/images/2025-01/MAKHACHEV_L_BELT_01-18.png", "Islam Makhachev"))
        self.assertFalse(fotos._retrato_ufc("https://ufc.com/images/2025-01/MAKHACHEV_BELT_ISLAM_01-18.png", "Islam Makhachev"))
        self.assertFalse(fotos._retrato_ufc(ORIGINAL, "Islam Makhachev Jr"))

    def test_baja_el_original_con_el_user_agent_propio_y_despues_no_vuelve_a_pedirlo(self):
        alta = _Resp(content=_png(6), tipo="image/png")
        with mock.patch.object(fotos, "url_ufc", return_value=ESTILO) as ufc, \
                mock.patch.object(fotos.requests, "get", return_value=alta) as get:
            ruta = fotos.foto_alta("Islam Makhachev")
            self.assertEqual(fotos.foto_alta("Islam Makhachev"), ruta)
        self.assertEqual(ruta.name, "alta_islam_makhachev.png")
        urls = [c.args[0] for c in get.call_args_list]
        self.assertEqual(urls.count(ORIGINAL), 1)
        self.assertTrue(all(c.kwargs["headers"]["User-Agent"] == "UFCFightPredictor/1.0"
                            for c in get.call_args_list if c.args[0] == ORIGINAL))
        self.assertEqual(fotos.fondo(ruta), "transparente")
        self.assertLessEqual(ufc.call_count, 2)      # foto() y foto_alta(), nunca por repintado

    def test_si_foto_ya_eligio_un_retrato_de_ufc_no_pide_otra_vez_la_ficha(self):
        with mock.patch.object(fotos, "url_ufc", return_value=ESTILO) as ufc, \
                mock.patch.object(fotos.requests, "get", return_value=_Resp(content=_png(6), tipo="image/png")):
            fotos.foto("Islam Makhachev")
            self.assertEqual(fotos._indice()["islam makhachev"]["fuente"], "ufc")
            fotos.foto_alta("Islam Makhachev")
        self.assertEqual(ufc.call_count, 1)

    def test_un_nombre_ambiguo_queda_en_silueta_y_no_consulta_ufc(self):
        with mock.patch.object(fotos, "url_espn", return_value=fotos.AMBIGUO), \
                mock.patch.object(fotos, "url_ufc", side_effect=AssertionError("no se consulta")), \
                mock.patch.object(fotos.requests, "get", side_effect=AssertionError("red")):
            self.assertIsNone(fotos.foto_alta("Mike Davis"))
            self.assertIsNone(fotos.foto_alta("Mike Davis"))

    def test_sin_original_usa_el_derivado_y_sin_ficha_el_retrato_normal(self):
        with mock.patch.object(fotos, "url_ufc", return_value=ESTILO), \
                mock.patch.object(fotos.requests, "get",
                                  side_effect=lambda url, **k: _Resp(status=404) if url == ORIGINAL
                                  else _Resp(content=_png(2), tipo="image/png")):
            ruta = fotos.foto_alta("Islam Makhachev")
        self.assertEqual(fotos._indice()["alta:islam makhachev"]["url"], ESTILO)
        self.assertEqual(fotos.fondo(ruta), "opaco")
        with mock.patch.object(fotos, "url_ufc", return_value=None), \
                mock.patch.object(fotos, "url_sherdog", return_value="https://www.sherdog.com/_images/fighter/x.jpg"), \
                mock.patch.object(fotos.requests, "get", return_value=JPG):
            ruta = fotos.foto_alta("Uros Medic")
        self.assertEqual(ruta.suffix, ".jpg")        # el retrato normal, que el navegador disimula
        self.assertEqual(fotos.fondo(ruta), "opaco")

    def test_red_caida_devuelve_el_retrato_normal_y_no_insiste(self):
        with mock.patch.object(fotos, "url_ufc", side_effect=fotos.SinRed("sin red")) as ufc:
            self.assertIsNone(fotos.foto_alta("Islam Makhachev"))
            self.assertIsNone(fotos.foto_alta("Islam Makhachev"))
        self.assertLessEqual(ufc.call_count, 2)
        self.assertNotIn("alta:islam makhachev", fotos._indice())

    def test_transparencia_por_la_cabecera(self):
        self.assertTrue(fotos.transparente(_png(6)))
        self.assertTrue(fotos.transparente(_png(4)))
        self.assertTrue(fotos.transparente(_png(2, trns=True)))
        self.assertFalse(fotos.transparente(_png(2)))
        self.assertFalse(fotos.transparente(JPG.content))
        self.assertFalse(fotos.transparente(b""))

    def test_cortesia_entre_peticiones_a_ufc(self):
        esperas = []
        with mock.patch.object(fotos, "DEMORA_UFC_SEG", 1.5), \
                mock.patch.object(fotos, "_ultima_ufc", 0.0), \
                mock.patch.object(fotos.time, "monotonic", side_effect=[100.0, 100.2, 100.4, 100.6]), \
                mock.patch.object(fotos.time, "sleep", side_effect=esperas.append), \
                mock.patch.object(fotos.requests, "get", return_value=PNG):
            fotos._get_ufc("https://www.ufc.com/athlete/a")
            fotos._get_ufc("https://www.ufc.com/athlete/b")
        self.assertEqual(len(esperas), 1)
        self.assertAlmostEqual(esperas[0], 1.3, places=6)


class Endpoint(_Base):

    def test_sin_foto_responde_204_para_que_la_ui_ponga_la_silueta(self):
        # 204 y no 404: "no hay foto" es lo normal para un debutante, y un 404
        # queda anotado como error en la consola del navegador.
        with mock.patch.object(fotos, "foto", lambda n: None):
            r = server.foto_peleador("Guilherme Pat")
        self.assertEqual(r.status_code, 204)

    def test_x_fondo_dice_si_el_retrato_es_transparente_y_alta_pide_foto_alta(self):
        recorte, opaca = fotos.CARPETA / "a.png", fotos.CARPETA / "b.jpg"
        recorte.write_bytes(_png(6))
        opaca.write_bytes(JPG.content)
        with mock.patch.object(fotos, "foto_alta", lambda n: recorte), mock.patch.object(fotos, "foto", lambda n: opaca):
            self.assertEqual(server.foto_peleador("Islam Makhachev", calidad="alta").headers["X-Fondo"], "transparente")
            self.assertEqual(server.foto_peleador("Islam Makhachev").headers["X-Fondo"], "opaco")

    def test_un_nombre_que_intenta_salir_de_la_carpeta_no_se_consulta(self):
        with mock.patch.object(fotos.requests, "get") as get:
            self.assertIsNone(fotos.foto("../../config"))
        get.assert_not_called()




CUERPO = "https://ufc.com/images/styles/athlete_bio_full_body/s3/2025-03/PEREIRA_ALEX_L.png?itok=zz"
CUERPO_ORIG = "https://ufc.com/images/2025-03/PEREIRA_ALEX_L.png"
HEAD = "https://ufc.com/images/2025-10/PEREIRA_ALEX_10-04.png"


def _ficha(nombre="Alex Pereira", *imgs):
    cuerpo = "".join(f'<img class="image-style-athlete-bio-full-body" src="{u}">' for u in imgs)
    return _Resp(text=f'<h1 class="hero-profile__name">{nombre}</h1>{cuerpo}')


class AltaCuerpoEntero(_Base):
    """foto_alta prefiere el cuerpo entero de la ficha y cae al headshot."""
    consultar_ufc = True

    def test_url_ufc_cuerpo_elige_el_full_body_y_valida_el_nombre(self):
        with mock.patch.object(fotos.requests, "get", return_value=_ficha("Alex Pereira", CUERPO)):
            self.assertEqual(fotos.url_ufc_cuerpo("Alex Pereira"), CUERPO)
        self.assertEqual(fotos.original_ufc(CUERPO), CUERPO_ORIG)
        # el archivo es de otro peleador: no se acepta
        otro = "https://ufc.com/images/styles/athlete_bio_full_body/s3/2025-03/ANKALAEV_MAGOMED_L.png?itok=1"
        with mock.patch.object(fotos.requests, "get", return_value=_ficha("Alex Pereira", otro)):
            self.assertIsNone(fotos.url_ufc_cuerpo("Alex Pereira"))
        # el h1 de la ficha es de otro (homónimo): tampoco
        with mock.patch.object(fotos.requests, "get", return_value=_ficha("Alex Perez", CUERPO)):
            self.assertIsNone(fotos.url_ufc_cuerpo("Alex Pereira"))
        # sin estilo full body en la ficha
        with mock.patch.object(fotos.requests, "get", return_value=_ficha("Alex Pereira", HEAD)):
            self.assertIsNone(fotos.url_ufc_cuerpo("Alex Pereira"))

    def test_foto_alta_baja_el_original_del_cuerpo_entero(self):
        # foto() (el retrato base) baja el headshot por su cuenta: se anula para medir
        # solo lo que pide foto_alta.
        with mock.patch.object(fotos, "foto", return_value=None),                 mock.patch.object(fotos, "url_ufc_cuerpo", return_value=CUERPO),                 mock.patch.object(fotos, "url_ufc", return_value=HEAD),                 mock.patch.object(fotos.requests, "get", return_value=_Resp(content=_png(6), tipo="image/png")) as get:
            ruta = fotos.foto_alta("Alex Pereira")
        self.assertEqual(fotos._indice()["alta:alex pereira"]["url"], CUERPO_ORIG)
        self.assertIn(CUERPO_ORIG, [c.args[0] for c in get.call_args_list])
        # con cuerpo entero no se debe pedir el headshot (ni su original) a la red
        pedidas = [c.args[0] for c in get.call_args_list]
        self.assertNotIn(HEAD, pedidas)
        self.assertNotIn(fotos.original_ufc(HEAD), pedidas)
        self.assertTrue(ruta.name.startswith("alta_"))

    def test_sin_cuerpo_entero_cae_al_headshot(self):
        with mock.patch.object(fotos, "url_ufc_cuerpo", return_value=None),                 mock.patch.object(fotos, "url_ufc", return_value=HEAD),                 mock.patch.object(fotos.requests, "get", return_value=_Resp(content=_png(6), tipo="image/png")):
            fotos.foto_alta("Alex Pereira")
        self.assertEqual(fotos._indice()["alta:alex pereira"]["url"], HEAD)

    def test_version_alta_invalida_entradas_viejas(self):
        self.assertGreaterEqual(fotos.VERSION_ALTA, 2)
        with mock.patch.object(fotos, "url_ufc_cuerpo", return_value=CUERPO) as cuerpo,                 mock.patch.object(fotos, "url_ufc", return_value=HEAD),                 mock.patch.object(fotos.requests, "get", return_value=_Resp(content=_png(6), tipo="image/png")):
            fotos.foto_alta("Alex Pereira")
            idx = fotos._indice()
            idx["alta:alex pereira"]["version"] = 1
            idx["alta:alex pereira"]["url"] = HEAD
            fotos._guardar_indice(idx)
            fotos.foto_alta("Alex Pereira")
        self.assertEqual(cuerpo.call_count, 2)
        self.assertEqual(fotos._indice()["alta:alex pereira"]["url"], CUERPO_ORIG)


if __name__ == "__main__":
    unittest.main()
