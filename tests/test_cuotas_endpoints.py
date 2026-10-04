"""Calendario del mercado y endpoints /api/mercado/* (sin red, base temporal)."""
from __future__ import annotations

import time
import unittest
from unittest import mock

from fastapi import HTTPException

import config as C
from src.cuotas import calendario, capa as capa_mod
from src.cuotas.capa import Capa
from tests.test_cuotas_capa import BaseCuotas, Falsa, cruda


def _evento(early, estelar, peleas=None, nombre="UFC 999"):
    return {"id": "e1", "nombre": nombre, "titular": "A vs B",
            "inicio": {"early": early, "preliminares": None, "estelar": estelar},
            "peleas": peleas or []}


class Calendario(BaseCuotas):

    def test_en_vivo_desde_la_primera_parte_hasta_6h_despues_de_la_estelar(self):
        t = time.time()
        self.oficial([_evento(t - 3600, t + 3600)])
        ev = calendario.evento_en_vivo()
        self.assertEqual((ev["nombre"], ev["simulado"]), ("UFC 999", False))
        self.assertTrue(ev["inicio"] < ev["estelar"] < ev["fin"])
        self.assertIsNotNone(calendario.evento_en_vivo(t + 3600 + 5.9 * 3600))
        self.assertIsNone(calendario.evento_en_vivo(t + 3600 + 6.1 * 3600))
        self.assertIsNone(calendario.evento_en_vivo(t - 2 * 3600))   # todavía no empieza

    def test_sin_early_cuenta_desde_las_preliminares_o_la_estelar(self):
        t = time.time()
        self.oficial([{"id": "e", "nombre": "UFC X", "inicio": {"estelar": t + 600}, "peleas": []}])
        self.assertIsNone(calendario.evento_en_vivo())
        self.assertIsNotNone(calendario.evento_en_vivo(t + 700))

    def test_sin_cache_no_hay_evento(self):
        self.assertIsNone(calendario.evento_en_vivo())

    def test_modo_simulado(self):
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            ev = calendario.evento_en_vivo()
        self.assertTrue(ev["simulado"])
        self.assertEqual(len(ev["peleas"]), 4)


class Endpoints(BaseCuotas):

    def setUp(self):
        super().setUp()
        from webui import server
        self.server = server
        self.capa = Capa([Falsa("bfo")])
        p = mock.patch.object(capa_mod, "_CAPA", self.capa)
        p.start()
        self.addCleanup(p.stop)

    def test_servidor_importa_sin_odds_api_key(self):
        # En un proceso aparte, con la clave vacía: importar no puede fallar ni pedir red.
        import os
        import subprocess
        import sys
        env = {**os.environ, "ODDS_API_KEY": "", "THE_ODDS_API_KEY": ""}
        r = subprocess.run([sys.executable, "-c",
                            "import webui.server as s, config as C; "
                            "from src.cuotas import registro; "
                            "o = [f for f in registro.fuentes() if f.clave == 'odds_api'][0]; "
                            "print(bool(C.ODDS_API_KEY), o.activa(), s.configuracion_cuotas()['odds_api_configurada'])"],
                           cwd=str(C.ROOT), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.split()[-3:], ["False", "False", "False"])

    def test_estado_sin_cuotas(self):
        d = self.server.mercado_estado()
        self.assertEqual((d["hay_cuotas"], d["en_vivo"]), (False, False))
        self.assertEqual(d["fuentes"][0]["clave"], "bfo")
        self.assertEqual(d["no_calzados"]["total"], 0)

    def test_peleas_y_historial(self):
        self.capa.ingerir(self.capa.fuentes[0], [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        d = self.server.mercado_peleas(evento="UFC 999")
        self.assertEqual(len(d["peleas"]), 1)
        self.assertIsNotNone(d["actualizado"])
        h = self.server.mercado_historial(pelea_id=d["peleas"][0]["pelea_id"])
        self.assertEqual(len(h["series"]), 1)
        with self.assertRaises(HTTPException) as e:
            self.server.mercado_historial(pelea_id="x|y", desde="ayer")
        self.assertEqual(e.exception.status_code, 400)
        self.assertTrue(self.server.mercado_estado()["hay_cuotas"])

    def test_cartelera_usa_los_nombres_literales_de_estado(self):
        from webui import engine
        self.capa.ingerir(self.capa.fuentes[0], [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        estado = engine.Estado()
        estado.datos = {"peleas": [{"a": "Magomed Ankalaev", "b": "Alex Pereira"},
                                   {"a": "Islam Makhachev", "b": "Arman Tsarukyan"}]}
        with mock.patch.object(engine, "ESTADO", estado):
            d = self.server.mercado_cartelera()
        self.assertEqual(set(d["peleas"]), {"Magomed Ankalaev|Alex Pereira", "Islam Makhachev|Arman Tsarukyan"})
        self.assertEqual(d["peleas"]["Magomed Ankalaev|Alex Pereira"]["a"], "Magomed Ankalaev")
        self.assertIsNone(d["peleas"]["Islam Makhachev|Arman Tsarukyan"])
        with mock.patch.object(engine, "ESTADO", engine.Estado()):
            self.assertEqual(self.server.mercado_cartelera(), {"peleas": {}})

    def test_los_endpoints_no_esperan_a_la_red(self):
        # La red está bloqueada en setUp: si un endpoint pidiera algo, reventaría.
        inicio = time.monotonic()
        self.server.mercado_estado()
        self.server.mercado_peleas()
        self.server.mercado_historial(pelea_id="a|b")
        self.assertLess(time.monotonic() - inicio, 5)


if __name__ == "__main__":
    unittest.main()
