"""Capa común de cuotas (src/cuotas): cruce, validación, historial, consenso y robustez.

Ninguna prueba toca la red: setUp bloquea requests entero y cada prueba que
necesita una respuesta la simula. La base es un SQLite temporal (UFC_DB).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import requests

import config as C
from src import storage as DB
from src.cuotas import calendario, cruce, historial as H
from src.cuotas.capa import Capa
from src.cuotas.fuentes.base import Fuente, FuenteError
from src.cuotas.tiempo import ahora_iso

FICHAS = [
    ("Alex Pereira", "e5549c82bfb5582d"),
    ("Magomed Ankalaev", "0123456789abcdef"),
    ("Ian Machado Garry", "442c9011034ae1fd"),
    ("Jiri Prochazka", "1111111111111111"),
    ("Mike Davis", "2222222222222222"),
    ("Mike Davis", "3333333333333333"),
    ("Islam Makhachev", "4444444444444444"),
    ("Arman Tsarukyan", "5555555555555555"),
    ("Carlos Ulberg", "6666666666666666"),
]


class _SinRed(Exception):
    pass


class BaseCuotas(unittest.TestCase):
    """SQLite temporal con fichas sintéticas y la red bloqueada."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta_db = (Path(self.tmp.name) / "cuotas.db").resolve()
        self.parches = [
            mock.patch.dict(os.environ, {"UFC_DB": str(self.ruta_db)}),
            mock.patch.object(C, "MERCADO_SIMULADO", False),
            mock.patch.object(C, "ODDS_API_KEY", ""),
            # Cualquier petición real revienta la prueba: requests.get/post y las
            # sesiones pasan todas por Session.request.
            mock.patch("requests.sessions.Session.request", side_effect=_SinRed("red bloqueada en tests")),
        ]
        for p in self.parches:
            p.start()
            self.addCleanup(p.stop)
        # Fallar antes de la primera escritura si la configuración no se aisló.
        self.assertEqual(DB.db_path().resolve(), self.ruta_db)
        self.addCleanup(cruce.invalidar)
        self.addCleanup(calendario.olvidar)
        DB.to_csv(pd.DataFrame({
            "fighter_url": [f"http://ufcstats.com/fighter-details/{i}" for _, i in FICHAS],
            "name": [n for n, _ in FICHAS]}), C.DATA_PROCESSED / "ufcstats_bio.csv", index=False)
        cruce.invalidar()
        calendario.olvidar()

    def oficial(self, proximos):
        DB.write_text(C.DATA_RAW / "ufc_oficial.json", json.dumps(
            {"version": 1, "eventos": {"proximos": proximos, "recientes": [], "consultado": time.time()}}))
        calendario.olvidar()


class Falsa(Fuente):
    tipo = "casa"

    def __init__(self, clave="falsa", crudas=None, error=None, tipo="casa", solo_ufc=True):
        super().__init__()
        self.clave, self.nombre = clave, clave.title()
        self.tipo, self.solo_ufc = tipo, solo_ufc
        self.crudas, self.error = crudas or [], error

    def intervalo(self, en_vivo):
        return 60

    def obtener(self):
        if self.error:
            raise self.error
        return self.crudas


def cruda(a, b, am_a, am_b, fuente="falsa", casa="CasaX", **extra):
    return {"fuente": fuente, "casa": casa, "evento": "UFC 999", "a_texto": a, "b_texto": b,
            "a_americana": am_a, "b_americana": am_b, "timestamp": ahora_iso(), **extra}


class Cruce(BaseCuotas):

    def test_match_exacto_con_tildes_mayusculas_y_espacios(self):
        r = cruce.resolver("  JIŘÍ   Procházka ")
        self.assertEqual((r.nombre, r.id, r.motivo), ("Jiri Prochazka", "1111111111111111", None))

    def test_alias_auditado(self):
        # src/fighter_names: "Ian Garry" es la misma ficha que "Ian Machado Garry".
        self.assertEqual(cruce.resolver("Ian Garry").id, "442c9011034ae1fd")
        self.assertEqual(cruce.resolver("Machado Garry").id, "442c9011034ae1fd")

    def test_nada_de_fuzzy(self):
        r = cruce.resolver("Alex Perreira")
        self.assertIsNone(r.nombre)
        self.assertEqual(r.motivo, "no_calza")

    def test_homonimo_sin_desempate_no_elige_ficha(self):
        r = cruce.resolver("Mike Davis", "Alex Pereira")
        self.assertEqual((r.nombre, r.id, r.motivo), ("Mike Davis", None, "homonimo"))

    def test_homonimo_con_desempate_manual_explicito(self):
        clave = (cruce.clave("Mike Davis"), cruce.clave("Carlos Ulberg"))
        with mock.patch.dict(cruce.DESEMPATE_MANUAL, {clave: "3333333333333333"}):
            r = cruce.resolver("Mike Davis", "Carlos Ulberg")
            self.assertEqual((r.id, r.motivo), ("3333333333333333", None))
            # Con otro rival el desempate no aplica.
            self.assertIsNone(cruce.resolver("Mike Davis", "Alex Pereira").id)

    def test_pelea_id_no_depende_del_orden(self):
        self.assertEqual(cruce.pelea_id("Magomed Ankalaev", "Alex Pereira"),
                         cruce.pelea_id("ALEX PEREIRA", "magomed ankalaev"))
        self.assertEqual(cruce.pelea_id("Alex Pereira", "Magomed Ankalaev"), "alex pereira|magomed ankalaev")


class Ingesta(BaseCuotas):

    def test_no_calzados_quedan_registrados_y_la_pelea_entra(self):
        capa, f = Capa([]), Falsa(crudas=[cruda("Alex Pereira", "Debutante Nuevo", -300, 240)])
        stats = capa.ingerir(f, f.crudas)
        self.assertEqual(stats["guardadas"], 1)
        nc = H.resumen_no_calzados()
        self.assertEqual(nc["total"], 1)
        self.assertEqual((nc["recientes"][0]["fuente"], nc["recientes"][0]["texto"],
                          nc["recientes"][0]["motivo"]), ("falsa", "Debutante Nuevo", "no_calza"))
        self.assertTrue(nc["recientes"][0]["ultima_vez"])
        p = capa.peleas()["peleas"][0]
        self.assertEqual((p["a"], p["b"], p["a_id"], p["b_id"]),
                         ("Alex Pereira", "Debutante Nuevo", "e5549c82bfb5582d", None))

    def test_homonimo_se_registra(self):
        capa, f = Capa([]), Falsa(crudas=[cruda("Mike Davis", "Carlos Ulberg", 150, -180)])
        capa.ingerir(f, f.crudas)
        self.assertEqual(H.resumen_no_calzados()["por_motivo"], {"homonimo": 1})

    def test_casa_con_probabilidades_que_suman_menos_de_1_se_rechaza(self):
        # +150 / +150 suman 0,8: imposible en una casa (pasó con las cuotas de 2025).
        capa, f = Capa([]), Falsa(crudas=[cruda("Alex Pereira", "Magomed Ankalaev", 150, 150)])
        stats = capa.ingerir(f, f.crudas)
        self.assertEqual(stats["rechazadas"], 1)
        self.assertEqual(f.rechazadas, 1)
        self.assertEqual(capa.peleas()["peleas"], [])

    def test_toda_casa_guardada_suma_mas_de_1(self):
        capa = Capa([])
        f = Falsa(crudas=[cruda("Alex Pereira", "Magomed Ankalaev", -150, 125, casa="A"),
                          cruda("Islam Makhachev", "Arman Tsarukyan", -300, 240, casa="B"),
                          cruda("Jiri Prochazka", "Carlos Ulberg", -105, -105, casa="C"),
                          cruda("Ian Garry", "Carlos Ulberg", 100, 100, casa="D")])   # suma 1,0: fuera
        capa.ingerir(f, f.crudas)
        peleas = capa.peleas()["peleas"]
        self.assertEqual(len(peleas), 3)
        for p in peleas:
            for c in p["cotizaciones"]:
                if c["tipo"] == "casa":
                    self.assertGreater(c["a"]["prob_implicita"] + c["b"]["prob_implicita"], 1)

    def test_orientacion_por_pelea_id(self):
        # La fuente lista a Ankalaev primero: la cotización se guarda con a = Pereira.
        capa, f = Capa([]), Falsa(crudas=[cruda("Magomed Ankalaev", "Alex Pereira", 125, -150)])
        capa.ingerir(f, f.crudas)
        p = capa.peleas()["peleas"][0]
        self.assertEqual((p["a"], p["cotizaciones"][0]["a"]["americana"]), ("Alex Pereira", -150))

    def test_fuente_de_todo_mma_descarta_peleas_ajenas(self):
        capa = Capa([])
        f = Falsa("odds_api", solo_ufc=False, crudas=[
            cruda("Fulano PFL", "Mengano PFL", -200, 170),           # PFL: fuera
            cruda("Alex Pereira", "Debutante Nuevo", -400, 300),     # uno solo en la base: fuera
            cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])   # entra
        stats = capa.ingerir(f, f.crudas)
        self.assertEqual((stats["guardadas"], stats["descartadas"]), (1, 2))
        # Igual quedan anotados: nada se descarta en silencio.
        self.assertEqual(H.resumen_no_calzados()["total"], 3)

    def test_cartelera_oficial_salva_al_debutante_de_todo_mma(self):
        self.oficial([{"id": "e1", "nombre": "UFC 999", "inicio": {"estelar": time.time() + 86400},
                       "peleas": [{"a": "Alex Pereira", "b": "Debutante Nuevo", "seccion": "estelar"}]}])
        capa = Capa([])
        f = Falsa("odds_api", solo_ufc=False, crudas=[cruda("Alex Pereira", "Debutante Nuevo", -400, 300)])
        self.assertEqual(capa.ingerir(f, f.crudas)["guardadas"], 1)
        p = capa.peleas()["peleas"][0]
        self.assertTrue(p["oficial"])
        self.assertEqual(p["evento"], "UFC 999")


class Historial(BaseCuotas):

    def test_no_duplica_filas_identicas_consecutivas(self):
        capa = Capa([])
        f = Falsa()
        for i, am in enumerate((-150, -150, -160, -160, -150)):
            capa.ingerir(f, [cruda("Alex Pereira", "Magomed Ankalaev", am, 125,
                                   timestamp=f"2026-10-03T10:00:0{i}+00:00")])
        with DB.connect() as con:
            n = con.execute("SELECT COUNT(*) FROM cuotas_historial").fetchone()[0]
        self.assertEqual(n, 3)    # −150, −160, −150
        serie = capa.historial("alex pereira|magomed ankalaev")["series"][0]
        self.assertEqual([p["a"] for p in serie["puntos"]], [-150, -160, -150])
        self.assertEqual((serie["fuente"], serie["casa"], serie["tipo"]), ("falsa", "CasaX", "casa"))

    def test_historial_orientado_y_filtrado_por_desde(self):
        capa, f = Capa([]), Falsa()
        capa.ingerir(f, [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        h = capa.historial("alex pereira|magomed ankalaev", a="Magomed Ankalaev")
        self.assertTrue(h["invertida"])
        self.assertEqual(h["series"][0]["puntos"][0]["a"], 125)
        self.assertEqual(capa.historial("alex pereira|magomed ankalaev", desde=time.time() + 60)["series"], [])
        with self.assertRaises(ValueError):
            capa.historial("alex pereira|magomed ankalaev", desde="ayer")

    def test_serie_remota_se_mezcla_con_la_propia(self):
        capa = Capa([])
        pm = Falsa("polymarket", tipo="mercado_prediccion")
        cr = {"fuente": "polymarket", "casa": "Polymarket", "evento": "UFC 999",
              "a_texto": "Alex Pereira", "b_texto": "Magomed Ankalaev",
              "a_prob": 0.6, "b_prob": 0.4, "timestamp": ahora_iso(),
              "historial": [{"timestamp": "2026-09-01T00:00:00+00:00", "a_prob": 0.5, "b_prob": 0.5},
                            {"timestamp": "2026-09-01T01:00:00+00:00", "a_prob": 0.5, "b_prob": 0.5},
                            {"timestamp": "2026-09-01T02:00:00+00:00", "a_prob": 0.55, "b_prob": 0.45}]}
        capa.ingerir(pm, [cr])
        capa.ingerir(pm, [cr])                                  # reimportar no duplica
        puntos = capa.historial("alex pereira|magomed ankalaev")["series"][0]["puntos"]
        self.assertEqual([p["pa"] for p in puntos], [0.5, 0.55, 0.6])
        self.assertEqual(puntos[-1]["a"], -150)


class Consolidado(BaseCuotas):

    def test_consenso_quita_margen_y_cuenta_una_vez_por_casa(self):
        capa = Capa([])
        capa.ingerir(Falsa("bfo"), [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125, casa="DraftKings")])
        capa.ingerir(Falsa("odds_api", solo_ufc=False),
                     [cruda("Alex Pereira", "Magomed Ankalaev", -140, 120, casa="DraftKings")])
        capa.ingerir(Falsa("bfo"), [cruda("Alex Pereira", "Magomed Ankalaev", -130, 110, casa="FanDuel")])
        p = capa.peleas()["peleas"][0]
        self.assertEqual(len(p["cotizaciones"]), 3)
        self.assertEqual(p["consenso"]["n_cotizaciones"], 2)       # DraftKings cuenta una vez
        self.assertEqual(p["consenso"]["a"]["etiqueta"], "Favorito")
        self.assertEqual(p["consenso"]["b"]["etiqueta"], "Underdog")
        self.assertAlmostEqual(p["consenso"]["a"]["prob"] + p["consenso"]["b"]["prob"], 1, places=6)
        self.assertEqual(p["mejor"]["b"]["americana"], 125)

    def test_sin_cotizaciones_no_hay_pelea(self):
        self.assertEqual(Capa([]).peleas(), {"peleas": [], "actualizado": None})

    def test_filtro_por_evento(self):
        capa = Capa([])
        capa.ingerir(Falsa(), [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        self.assertEqual(len(capa.peleas("ufc 999")["peleas"]), 1)
        self.assertEqual(capa.peleas("UFC 1")["peleas"], [])

    def test_cartelera_orienta_como_la_cartelera(self):
        capa = Capa([])
        capa.ingerir(Falsa(), [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        out = capa.cartelera([("Magomed Ankalaev", "Alex Pereira"), ("Islam Makhachev", "Arman Tsarukyan")])
        p = out["peleas"]["Magomed Ankalaev|Alex Pereira"]
        self.assertTrue(p["invertida"])
        self.assertEqual((p["a"], p["cotizaciones"][0]["a"]["americana"]), ("Magomed Ankalaev", 125))
        self.assertEqual(p["consenso"]["a"]["etiqueta"], "Underdog")
        self.assertIsNone(out["peleas"]["Islam Makhachev|Arman Tsarukyan"])


class Robustez(BaseCuotas):

    def test_una_fuente_caida_no_tumba_a_las_demas(self):
        caida = Falsa("caida", error=requests.ConnectionError("boom"))
        rara = Falsa("rara", error=KeyError("x"))
        buena = Falsa("buena", crudas=[cruda("Alex Pereira", "Magomed Ankalaev", -150, 125, fuente="buena")])
        capa = Capa([caida, rara, buena])
        res = capa.consultar_todas()
        self.assertIsNone(res["caida"])
        self.assertIsNone(res["rara"])
        self.assertEqual(res["buena"]["guardadas"], 1)
        est = {e["clave"]: e for e in capa.estado()["fuentes"]}
        self.assertIn("Sin conexión", est["caida"]["motivo"])
        self.assertTrue(est["caida"]["activa"])
        self.assertIsNone(est["buena"]["motivo"])
        self.assertTrue(capa.estado()["hay_cuotas"])

    def test_si_fallan_todas_los_endpoints_responden_igual(self):
        capa = Capa([Falsa("a", error=FuenteError("HTTP 403 desde Chile")),
                     Falsa("b", error=requests.Timeout("lento"))])
        capa.consultar_todas()
        est = capa.estado()
        self.assertFalse(est["hay_cuotas"])
        self.assertEqual(capa.peleas()["peleas"], [])
        self.assertEqual(capa.cartelera([("Alex Pereira", "Magomed Ankalaev")]),
                         {"peleas": {"Alex Pereira|Magomed Ankalaev": None}})
        self.assertEqual(est["fuentes"][0]["motivo"], "HTTP 403 desde Chile")

    def test_hilos_arrancan_y_se_detienen(self):
        llamadas = []
        f = Falsa("lenta")
        f.obtener = lambda: llamadas.append(1) or []
        capa = Capa([f])
        capa.arrancar()
        for _ in range(50):
            if llamadas:
                break
            time.sleep(0.05)
        capa.detener()
        self.assertEqual(len(llamadas), 1)        # intervalo 60 s: una sola vuelta


class Simulado(BaseCuotas):

    def test_evento_simulado_no_informa_cadencia_viva_a_fuentes_reales(self):
        real = Falsa("odds_api")
        real.intervalo = lambda en_vivo: 120 if en_vivo else 43200
        from src.cuotas.simulado import FuenteSimulada
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            capa = Capa([real, FuenteSimulada()])
            est = capa.estado()
        self.assertTrue(est["en_vivo"] and est["evento"]["simulado"])
        self.assertEqual({f["clave"]: f["intervalo_seg"] for f in est["fuentes"]},
                         {"odds_api": 43200, "simulada": 10})

    def test_evento_real_si_informa_cadencia_viva_incluso_con_simulacion(self):
        t = time.time()
        self.oficial([{"id": "real", "nombre": "UFC real",
                       "inicio": {"estelar": t - 600}, "peleas": []}])
        real = Falsa("odds_api")
        real.intervalo = lambda en_vivo: 120 if en_vivo else 43200
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            est = Capa([real]).estado()
        self.assertTrue(est["evento"]["simulado"])
        self.assertEqual(est["fuentes"][0]["intervalo_seg"], 120)

    def test_apagado_no_deja_rastro(self):
        capa = Capa([])
        capa.ingerir(Falsa("simulada"), [cruda("Alex Pereira", "Magomed Ankalaev", -150, 125)])
        self.assertEqual(capa.peleas()["peleas"], [])            # filtrada al leer
        Capa([])                                                  # y borrada al arrancar
        with DB.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM cuotas_historial").fetchone()[0], 0)
        from src.cuotas import registro
        self.assertNotIn("simulada", [f.clave for f in registro.fuentes()])
        self.assertIsNone(calendario.evento_en_vivo())

    def test_encendido_agrega_fuente_y_evento(self):
        from src.cuotas import registro
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            self.assertIn("simulada", [f.clave for f in registro.fuentes()])
            ev = calendario.evento_en_vivo()
            self.assertTrue(ev["simulado"])
            capa = Capa()
            sim = next(f for f in capa.fuentes if f.clave == "simulada")
            # Bloque 4: lo simulado vive en memoria (src/cuotas/simulado.datos) y
            # nunca entra al historial real, porque usa parejas reales y se
            # mezclaba con sus cuotas. La fuente sigue visible en el estado.
            self.assertEqual(sim.obtener(), [])
            est = capa.estado()
            self.assertTrue(est["en_vivo"] and est["simulado"])
            self.assertEqual(capa.peleas()["peleas"], [])
            from src.cuotas import simulado
            self.assertEqual(len(simulado.datos()), 4)


if __name__ == "__main__":
    unittest.main()
