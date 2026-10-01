"""
Pruebas de webui/fotos.py con respuestas simuladas: la nube no deja salir a
Wikipedia ni a Sherdog, y aunque dejara, una prueba no debe depender de la red.
La verificación con la red real se hace en el PC del dueño.
"""
import json
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


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p_carpeta = mock.patch.object(fotos, "CARPETA", Path(self.tmp.name))
        self.p_carpeta.start()
        fotos._fallo_red.clear()
        # sherdog.DELAY es un sleep de cortesía: en pruebas no hace falta esperar.
        self.p_delay = mock.patch.object(fotos.sherdog, "DELAY", 0)
        self.p_delay.start()

    def tearDown(self):
        self.p_delay.stop()
        self.p_carpeta.stop()
        self.tmp.cleanup()


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
