"""«Comparar cuotas» con Betano y Polymarket: salen de la capa, sin red."""
from __future__ import annotations

from datetime import date
import unittest
from unittest import mock

from fastapi import HTTPException

from src import cuotas_fuentes as F
from src import storage as DB
from src.cuotas import capa as capa_mod
from src.cuotas.capa import Capa
from src.cuotas.tiempo import ahora_iso
from tests.test_cuotas_capa import BaseCuotas
from tests.util import aislar_base

setUpModule, tearDownModule = aislar_base()


def _crudas(clave, a, b, **cuotas):
    return {"fuente": clave, "casa": "Betano" if clave == "betano" else "Polymarket",
            "evento": "UFC 999", "fecha": date.today().isoformat(), "a_texto": a, "b_texto": b,
            "timestamp": ahora_iso(), **cuotas}


class Comparar(BaseCuotas):

    def setUp(self):
        super().setUp()
        from webui import server
        self.server = server
        self.capa = Capa()
        p = mock.patch.object(capa_mod, "_CAPA", self.capa)
        p.start()
        self.addCleanup(p.stop)
        por = {f.clave: f for f in self.capa.fuentes}
        # La capa orienta a/b sola; los tests comparan por nombre.
        self.capa.ingerir(por["betano"], [_crudas("betano", "Alex Pereira", "Magomed Ankalaev",
                                                 a_americana=-150, b_americana=+125)])
        self.capa.ingerir(por["polymarket"], [_crudas("polymarket", "Alex Pereira", "Magomed Ankalaev",
                                                     a_prob=0.60, b_prob=0.40)])
        self.capa.ingerir(por["bfo"], [_crudas("bfo", "Islam Makhachev", "Arman Tsarukyan",
                                              a_americana=-200, b_americana=+170)])

    def sin_red(self):
        """Cualquier petición HTTP falla: este camino solo puede leer SQLite."""
        import requests
        def _falla(*a, **k):
            raise AssertionError("petición de red en Comparar cuotas")
        for obj, nombre in ((requests, "get"), (requests, "post"), (requests.Session, "request")):
            p = mock.patch.object(obj, nombre, _falla)
            p.start()
            self.addCleanup(p.stop)

    def filas(self):
        with DB.connect() as con:
            F._tablas(con)
            return con.execute("SELECT COUNT(*) FROM cuotas_snapshots").fetchone()[0]

    def pelea(self, d):
        self.assertEqual(len(d["eventos"]), 1)
        self.assertEqual(len(d["eventos"][0]["peleas"]), 1)
        return d["eventos"][0]["peleas"][0]

    def decimales(self, p, casa):
        c = p["casas"][casa]
        return (c["a"], c["b"]) if p["a"] == "Alex Pereira" else (c["b"], c["a"])

    def test_estado_trae_las_cuatro_fuentes(self):
        e = self.server.mercado_estado()
        por = {f["clave"]: f for f in e["fuentes"]}
        self.assertTrue({"betano", "bfo", "odds_api", "polymarket"} <= set(por))
        for f in por.values():
            for k in ("clave", "nombre", "tipo", "activa", "motivo", "ultimo_ok"):
                self.assertIn(k, f)
        self.assertEqual(por["polymarket"]["tipo"], "mercado_prediccion")
        self.assertEqual(por["betano"]["tipo"], "casa")
        self.assertFalse(por["odds_api"]["activa"])
        self.assertTrue(por["odds_api"]["motivo"])

    def test_betano_decimal_sin_red(self):
        self.sin_red()
        d = self.server.consultar_cuotas("betano")
        self.assertEqual((d["proveedor"], d["tipo"], d["carteleras"]), ("betano", "casa", []))
        self.assertIsNotNone(d["actualizado"])
        p = self.pelea(d)
        self.assertEqual(list(p["casas"]), ["betano"])
        self.assertEqual(p["casas"]["betano"]["casa"], "Betano")
        a, b = self.decimales(p, "betano")
        self.assertAlmostEqual(a, 1 + 100 / 150, places=3)
        self.assertAlmostEqual(b, 2.25, places=3)
        self.assertEqual(d["eventos"][0]["titulo"], "UFC 999")
        self.assertFalse(d["desactualizado"])

    def test_polymarket_probabilidad_a_decimal(self):
        self.sin_red()
        d = self.server.consultar_cuotas("polymarket")
        self.assertEqual((d["proveedor"], d["tipo"]), ("polymarket", "mercado_prediccion"))
        p = self.pelea(d)
        self.assertEqual(list(p["casas"]), ["polymarket"])
        a, b = self.decimales(p, "polymarket")
        self.assertAlmostEqual(a, 1 / 0.6, places=2)
        self.assertAlmostEqual(b, 2.5, places=2)

    def test_no_mezcla_fuentes(self):
        # La pelea de bfo no aparece ni en betano ni en polymarket.
        for k in ("betano", "polymarket"):
            nombres = {p["a"] for e in self.server.consultar_cuotas(k)["eventos"] for p in e["peleas"]}
            self.assertNotIn("Islam Makhachev", nombres)

    def test_sin_cuotas_de_la_fuente_es_200_vacio(self):
        with mock.patch.object(self.capa, "peleas", return_value={"peleas": [], "actualizado": None}):
            d = self.server.consultar_cuotas("betano")
        self.assertEqual(d["eventos"], [])

    def test_dos_get_no_duplican_capturas(self):
        d1 = self.server.consultar_cuotas("betano")
        n = self.filas()
        d2 = self.server.consultar_cuotas("betano")
        self.assertEqual(self.filas(), n)
        self.assertEqual(d1["snapshot"], d2["snapshot"])
        self.server.consultar_cuotas("polymarket")
        self.assertEqual(self.filas(), n + 1)

    def test_captura_se_carga_y_se_abre(self):
        self.sin_red()
        d = self.server.consultar_cuotas("polymarket")
        e = d["eventos"][0]
        ruta, titulo, meta = F.cartelera(d["snapshot"], e["id"], "polymarket")
        self.assertTrue(DB.exists(ruta))
        self.assertEqual((titulo, meta["proveedor"], meta["casa"]), ("UFC 999", "polymarket", "Polymarket"))
        abierta = self.server.captura_cuotas(d["snapshot"])
        self.assertEqual(abierta["proveedor"], "polymarket")
        self.assertEqual(len(abierta["eventos"]), 1)
        h = self.server.historial_cuotas("polymarket")["capturas"]
        self.assertEqual([c["snapshot"] for c in h], [d["snapshot"]])

    def test_desconocido_400_y_alias_legado(self):
        with self.assertRaises(HTTPException) as cm:
            self.server.consultar_cuotas("nada")
        self.assertEqual(cm.exception.status_code, 400)
        # odds-api sin clave: el camino legado sigue (502 por falta de clave, no 400).
        for alias in ("odds-api", "odds_api"):
            with self.assertRaises(HTTPException) as cm:
                self.server.consultar_cuotas(alias)
            self.assertEqual(cm.exception.status_code, 502)

    def test_odds_api_normaliza_proveedor(self):
        eventos = [{"id": "x", "titulo": "A vs B", "fecha": None, "fuente": "u",
                    "peleas": [{"id": "x", "a": "A", "b": "B", "casas": {"dk": {"casa": "DK", "a": 1.5, "b": 2.5}}}]}]
        falsa = {"snapshot": "s", "capturado": "2026-01-01T00:00:00+00:00", "eventos": eventos,
                 "proveedor": "odds-api", "cache": True, "desactualizado": False, "fecha_fuente": None}
        with mock.patch.object(F, "consultar", return_value=falsa) as m:
            d = self.server.consultar_cuotas("odds-api")
        m.assert_called_once_with("odds-api")
        self.assertEqual((d["proveedor"], d["tipo"], d["actualizado"]),
                         ("odds_api", "casa", "2026-01-01T00:00:00+00:00"))

    def test_polymarket_extremo_no_llega_ambiguo_al_predictor(self):
        # p=0,01 → decimal 100 (se leería como americana +100) y p=0,015 → 66,67
        # (se descartaría en silencio): se dejan fuera con el motivo a la vista.
        por = {f.clave: f for f in self.capa.fuentes}
        for a, b, pa, pb in (("Ppez Uno", "Pez Dos", 0.01, 0.99), ("Pez Tres", "Pez Cuatro", 0.015, 0.985)):
            self.capa.ingerir(por["polymarket"], [_crudas("polymarket", a, b, a_prob=pa, b_prob=pb)])
        d = self.server.consultar_cuotas("polymarket")
        nombres = {p["a"] for e in d["eventos"] for p in e["peleas"]}
        self.assertFalse(nombres & {"Pez Uno", "Pez Dos", "Pez Tres", "Pez Cuatro"})
        self.assertEqual(len(d["descartadas"]), 2)
        self.assertIn("ambiguo", d["descartadas"][0]["motivo"])
        # Todo lo que sale es decimal inequívoco (1 < d <= 50).
        for e in d["eventos"]:
            for p in e["peleas"]:
                for c in p["casas"].values():
                    self.assertTrue(1 < c["a"] <= 50 and 1 < c["b"] <= 50)

    def test_dos_hilos_no_duplican_la_captura(self):
        import threading
        from src.cuotas import comparar
        eventos, _ = comparar._eventos(self.capa.peleas()["peleas"], "betano")
        ids, errores = [], []
        barrera = threading.Barrier(6)

        def corre():
            try:
                barrera.wait()
                ids.append(comparar._guardar("betano", eventos)[0])
            except Exception as e:           # noqa: BLE001
                errores.append(e)
        hilos = [threading.Thread(target=corre) for _ in range(6)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(errores, [])
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.filas(), 1)

    def test_captura_de_betano_se_predice_sin_red_con_sus_precios(self):
        from fastapi.testclient import TestClient
        from webui import engine
        self.sin_red()
        d = self.server.consultar_cuotas("betano")
        e = d["eventos"][0]
        vistos = {}

        def predecir(ruta, progreso=None, **k):
            import pandas as pd
            vistos["csv"] = DB.read_csv(ruta)
            return {}

        def baja(*a, **k):
            raise AssertionError("bajar_cuotas: no debe pedir nada a Betano")
        estado = engine.Estado()
        with mock.patch.object(engine, "ESTADO", estado),                 mock.patch.object(engine, "bajar_cuotas", baja),                 mock.patch.object(engine, "_predecir_sync", predecir),                 mock.patch.object(engine, "_serializar", lambda r, ruta: ({"peleas": []}, [])),                 mock.patch.object(engine, "_respaldar_informes", lambda r: None):
            r = TestClient(self.server.app).post("/api/cartelera/cuotas", json={
                "snapshot": d["snapshot"], "evento": e["id"], "casa": "betano", "oficial": False})
            self.assertEqual(r.status_code, 200)
            import time
            fin = time.time() + 20
            while estado.cargando and time.time() < fin:
                time.sleep(0.05)
        self.assertEqual(estado.error, "")
        fila = vistos["csv"].iloc[0]
        self.assertEqual({fila.fighter_a, fila.fighter_b}, {"Alex Pereira", "Magomed Ankalaev"})
        self.assertNotEqual(estado.origen, "betano")
        # Los precios que llegan al predictor son los de la captura, con su orientacion:
        # Pereira -150 (1,667) y Ankalaev +125 (2,25), sin importar quien quede en A.
        csv = vistos["csv"]
        self.assertEqual(len(csv), 1)
        por_nombre = {fila.fighter_a: fila.odds_a, fila.fighter_b: fila.odds_b}
        self.assertAlmostEqual(float(por_nombre["Alex Pereira"]), 1 + 100 / 150, places=2)
        self.assertAlmostEqual(float(por_nombre["Magomed Ankalaev"]), 2.25, places=2)
        self.assertEqual(self.decimales(self.pelea(d), "betano") and
                         {"Alex Pereira": float(por_nombre["Alex Pereira"]),
                          "Magomed Ankalaev": float(por_nombre["Magomed Ankalaev"])},
                         {"Alex Pereira": float(por_nombre["Alex Pereira"]),
                          "Magomed Ankalaev": float(por_nombre["Magomed Ankalaev"])})


if __name__ == "__main__":
    unittest.main()
