"""Mercado en vivo: contrato, estados y lecturas locales con SQLite aislado.

La red y el polling se bloquean, y la ruta temporal se comprueba antes de
sembrar. La simulación debe conservar todas las tablas reales byte a byte.
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
from fastapi.testclient import TestClient

import config as C
from src import storage as DB
from src.cuotas import calendario, capa as capa_mod, cruce, historial as H, simulado
from src.cuotas.capa import Capa
from src.cuotas.conversion import cotizacion
from src.cuotas.fuentes.base import Fuente
from src.cuotas.tiempo import a_iso
from webui import vivo


def guardar_json(ruta, datos):
    DB.write_text(ruta, json.dumps(datos, ensure_ascii=False, allow_nan=False))


class FuenteLocal(Fuente):
    """Fuente sintética cuya consulta sería un error en un endpoint de lectura."""

    def __init__(self, clave="local", activa=True):
        super().__init__()
        self.clave, self.nombre = clave, clave.title()
        self._activa = activa

    def activa(self):
        return self._activa

    def intervalo(self, en_vivo):
        return 120 if en_vivo else 3600

    def obtener(self):
        raise AssertionError("El endpoint no debe consultar fuentes")


class BaseVivo(unittest.TestCase):

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta_db = (Path(temporal.name) / "vivo.db").resolve()
        self.ahora = int(time.time())
        self.red = mock.Mock(side_effect=AssertionError("red bloqueada en mercado vivo"))
        for parche in (
            mock.patch.dict(os.environ, {"UFC_DB": str(self.ruta_db)}),
            mock.patch.object(C, "MERCADO_SIMULADO", False),
            mock.patch("requests.sessions.Session.request", self.red),
            mock.patch.object(simulado, "_INICIO", self.ahora - 45 * 60),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        self.assertEqual(DB.db_path().resolve(), self.ruta_db)
        nombres = sorted({n for a, b, _ in simulado.PELEAS for n in (a, b)})
        DB.to_csv(pd.DataFrame({"name": nombres,
            "fighter_url": [f"http://ufcstats.com/fighter-details/{i:016x}" for i in range(len(nombres))]}),
            C.DATA_PROCESSED / "ufcstats_bio.csv", index=False)
        guardar_json(C.DATA_RAW / "ufc_oficial.json", {
            "version": 1, "eventos": {"proximos": [], "recientes": [], "consultado": self.ahora}})
        self.fuente = FuenteLocal()
        self.capa = Capa([self.fuente])
        parche = mock.patch.object(capa_mod, "_CAPA", self.capa)
        parche.start()
        self.addCleanup(parche.stop)
        for olvidar in (cruce.invalidar, calendario.olvidar, simulado.olvidar, vivo.olvidar):
            olvidar()
            self.addCleanup(olvidar)
        self.addCleanup(self.red.assert_not_called)

    def evento_real(self, peleas=None):
        guardar_json(C.DATA_RAW / "ufc_oficial.json", {
            "version": 1, "eventos": {"proximos": [{"id": "real", "nombre": "UFC prueba",
                "inicio": {"early": self.ahora - 600, "estelar": self.ahora - 300},
                "peleas": peleas if peleas is not None else [{"a": "Alex Pereira", "b": "Magomed Ankalaev",
                    "seccion": "estelar"}]}], "recientes": [], "consultado": self.ahora}})
        calendario.olvidar()
        vivo.olvidar()

    def ingerir(self, a="Alex Pereira", b="Magomed Ankalaev", am_a=-150, am_b=125):
        self.capa.ingerir(self.fuente, [{"fuente": self.fuente.clave, "casa": "Casa prueba",
            "evento": "UFC prueba", "a_texto": a, "b_texto": b,
            "a_americana": am_a, "b_americana": am_b, "timestamp": a_iso(self.ahora)}])
        self.fuente.marcar_ok(self.ahora)

    def simular(self, ahora=None, **consulta):
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            return vivo.vivo(ahora=self.ahora if ahora is None else ahora, **consulta)

    def foto_base(self):
        # El dump compara valores, orden, metadatos y cachés; no solo un contador.
        with DB.connect() as con:
            return "\n".join(con.iterdump())


class EstadosVivo(unittest.TestCase):

    def test_senal_directa_y_orden_terminan_las_anteriores(self):
        orden = [{"pelea_id": p, "inicio_parte": 10} for p in ("primera", "segunda", "tercera")]
        for motivo in ("resultado", "mercado_cerrado", "mercado_simulado"):
            with self.subTest(motivo=motivo):
                self.assertEqual(vivo.estados(orden, {"segunda": motivo}, 20), {
                    "primera": ("terminada", "orden"), "segunda": ("terminada", motivo),
                    "tercera": ("en_curso", "estimado")})

    def test_horario_impide_dar_en_curso_una_parte_futura(self):
        orden = [{"pelea_id": "early", "inicio_parte": 10},
                 {"pelea_id": "estelar", "inicio_parte": 30}]
        self.assertEqual(vivo.estados(orden, {}, 20), {
            "early": ("en_curso", "estimado"), "estelar": ("por_pelear", "horario")})

    def test_solo_la_primera_sin_senal_es_estimada(self):
        orden = [{"pelea_id": p, "inicio_parte": 20} for p in ("primera", "segunda")]
        self.assertEqual(vivo.estados(orden, {}, 20), {
            "primera": ("en_curso", "estimado"), "segunda": ("por_pelear", "siguiente")})
        self.assertIn("Estimado", vivo.MOTIVOS["estimado"])

    def test_antes_del_evento_y_despues_de_todos_los_resultados_no_hay_en_curso(self):
        orden = [{"pelea_id": "unica", "inicio_parte": 20}]
        self.assertEqual(vivo.estados(orden, {}, 19), {"unica": ("por_pelear", "horario")})
        self.assertEqual(vivo.estados(orden, {"unica": "resultado"}, 30),
                         {"unica": ("terminada", "resultado")})
        self.assertEqual(vivo.estados([], {}, 30), {})


class ContratoVivo(BaseVivo):

    def test_sin_evento_devuelve_solo_activo_false(self):
        self.assertEqual(vivo.vivo(ahora=self.ahora), {"activo": False})

    def test_simulado_cumple_contrato_y_numeros_validos(self):
        d = self.simular()
        json.dumps(d, allow_nan=False)
        self.assertTrue(d["activo"] and d["simulado"])
        self.assertEqual(d["evento"]["nombre"], "Evento simulado")
        self.assertEqual(len(d["peleas"]), 4)
        self.assertEqual([p["estado"] for p in d["peleas"]],
                         ["terminada", "terminada", "en_curso", "por_pelear"])
        actual = d["actual"]
        self.assertEqual(actual["motivo_clave"], "estimado")
        self.assertIn("Estimado", actual["motivo"])
        self.assertFalse(actual["incremental"])
        for lado in ("a", "b"):
            self.assertEqual(set(actual[lado]), {"nombre", "id", "perfil_ufc", "pais", "campeon", "foto"})
            self.assertTrue(actual[lado]["foto"].startswith("/api/foto/"))
        self.assertTrue(d["mercado"]["hay_cuotas"])
        self.assertEqual(len(actual["cotizaciones"]), 4)
        self.assertEqual(len(actual["series"]), 4)
        self.assertIn("No son una recomendación", d["nota"])
        for serie in actual["series"]:
            self.assertIn("sim.", serie["etiqueta"])
            self.assertTrue(serie["hasta"])
            tiempos = [p["t"] for p in serie["puntos"]]
            self.assertEqual(tiempos, sorted(set(tiempos)))
            for punto in serie["puntos"]:
                self.assertEqual(set(punto), {"t", "a", "b", "pa", "pb"})
                self.assertAlmostEqual(punto["pa"] + punto["pb"], 1)
                self.assertTrue(0 < punto["pa"] < 1)
                self.assertGreaterEqual(abs(punto["a"]), 100)

    def test_incremental_solo_incluye_puntos_posteriores_y_cambio_de_pelea_recarga(self):
        primera = self.simular()["actual"]
        ultimo = max(p["t"] for s in primera["series"] for p in s["puntos"])
        segunda = self.simular(ahora=self.ahora + 120, desde=ultimo, pelea_id=primera["pelea_id"])["actual"]
        self.assertTrue(segunda["incremental"])
        nuevos = [p for s in segunda["series"] for p in s["puntos"]]
        self.assertTrue(nuevos)
        self.assertTrue(all(p["t"] > ultimo for p in nuevos))
        tercera = self.simular(ahora=self.ahora + simulado.SLOT, desde=ultimo,
                              pelea_id=primera["pelea_id"])["actual"]
        self.assertNotEqual(tercera["pelea_id"], primera["pelea_id"])
        self.assertFalse(tercera["incremental"])
        self.assertTrue(any(p["t"] <= ultimo for s in tercera["series"] for p in s["puntos"]))

    def test_cursor_invalido_recarga_la_serie_completa(self):
        completa = self.simular()["actual"]
        invalida = self.simular(desde="ayer", pelea_id=completa["pelea_id"])["actual"]
        self.assertFalse(invalida["incremental"])
        self.assertEqual(invalida["series"], completa["series"])

    def test_generador_simulado_sano_no_depende_del_ultimo_ok_del_hilo(self):
        fuente = simulado.FuenteSimulada()
        self.capa.fuentes.append(fuente)
        self.assertIsNone(fuente.estado()["ultimo_ok"])
        d = self.simular()
        self.assertTrue(d["mercado"]["hay_cuotas"])
        self.assertTrue(d["actual"]["series"])
        self.assertFalse(d["mercado"]["todas_caidas"])
        self.assertEqual(d["mercado"]["con_error"], [])
        self.assertEqual(d["mercado"]["fuentes"], [{"clave": "simulada", "nombre": "Simulada",
                         "tipo": "casa", "ok": True, "motivo": None}])

    def test_marca_manual_avanza_actual_sin_escribir_y_desmarcar_recupera(self):
        original = self.simular()
        pid = original["actual"]["pelea_id"]
        antes = self.foto_base()
        marcada = self.simular(terminadas=[pid], evento_id="simulado", desde=original["consultado"], pelea_id=pid)
        anterior = next(p for p in marcada["peleas"] if p["pelea_id"] == pid)
        self.assertEqual((anterior["estado"], anterior["motivo_clave"]), ("terminada", "manual"))
        self.assertEqual(anterior["motivo"], "Marcada por ti en este navegador.")
        self.assertIsNone(anterior["resolucion"])
        self.assertNotEqual(marcada["actual"]["pelea_id"], pid)
        self.assertFalse(marcada["actual"]["incremental"])
        self.assertTrue(marcada["actual"]["series"])
        self.assertEqual(self.foto_base(), antes)
        self.assertEqual(self.simular(), original)

    def test_marca_manual_exige_evento_e_id_exactos(self):
        original = self.simular()
        pid = original["actual"]["pelea_id"]
        self.assertEqual(self.simular(terminadas=[pid], evento_id="otra_noche"), original)
        self.assertEqual(self.simular(terminadas=[pid.upper(), "pareja|ajena"], evento_id="simulado"), original)

    def test_marca_manual_no_contamina_la_memoria_compartida_entre_pestanas(self):
        with mock.patch.object(C, "MERCADO_SIMULADO", True), \
                mock.patch.object(vivo, "_base", wraps=vivo._base) as armar:
            original = vivo.vivo()
            pid = original["actual"]["pelea_id"]
            marcada = vivo.vivo(terminadas=[pid], evento_id="simulado")
            otra_pestana = vivo.vivo()
        self.assertEqual(armar.call_count, 1)
        self.assertNotEqual(marcada["actual"]["pelea_id"], pid)
        self.assertEqual(otra_pestana["actual"]["pelea_id"], pid)
        self.assertEqual(otra_pestana["peleas"], original["peleas"])

    def test_simulacion_no_escribe_ni_contamina_parejas_reales(self):
        self.ingerir()
        antes = self.foto_base()
        reales = self.capa.peleas()
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            fuente = simulado.FuenteSimulada()
            self.assertEqual(fuente.obtener(), [])
            self.capa.ingerir(fuente, [])
            vivo.vivo(ahora=self.ahora)
            vivo.vivo(ahora=self.ahora + 120)
            self.assertEqual(self.capa.peleas(), reales)
        self.assertEqual(self.foto_base(), antes)
        self.assertEqual(self.capa.peleas(), reales)
        self.assertEqual(vivo.vivo(ahora=self.ahora), {"activo": False})

    def test_reorienta_series_y_cotizaciones_hacia_la_esquina_oficial(self):
        self.evento_real([{"a": "Magomed Ankalaev", "b": "Alex Pereira", "seccion": "estelar"}])
        self.ingerir()
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            actual = vivo.vivo(ahora=self.ahora)["actual"]
        self.assertEqual(actual["a"]["nombre"], "Magomed Ankalaev")
        self.assertEqual(actual["cotizaciones"][0]["a"]["americana"], 125)
        self.assertEqual(actual["series"][0]["puntos"][0]["a"], 125)
        self.assertEqual(actual["consenso"]["a"]["etiqueta"], "Underdog")

    def test_sin_orden_oficial_no_inventa_pelea_en_curso(self):
        self.evento_real([])
        self.ingerir()
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            actual = vivo.vivo(ahora=self.ahora)["actual"]
        self.assertEqual((actual["estado"], actual["motivo_clave"]), ("por_pelear", "sin_orden"))

    def test_resultado_directo_prevalece_y_todas_terminadas_conserva_estelar(self):
        self.evento_real()
        self.ingerir()
        pid = cruce.pelea_id("Alex Pereira", "Magomed Ankalaev")
        with mock.patch.object(vivo, "_resultados_base", return_value={pid}):
            actual = vivo.vivo(ahora=self.ahora)["actual"]
        self.assertEqual((actual["estado"], actual["motivo_clave"]), ("terminada", "resultado"))

    def test_sin_cuotas_y_fuente_caida_responde_con_aviso(self):
        self.evento_real()
        self.fuente.marcar_error("Sin conexión")
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            d = vivo.vivo(ahora=self.ahora)
        self.assertTrue(d["activo"])
        self.assertFalse(d["mercado"]["hay_cuotas"])
        self.assertTrue(d["mercado"]["todas_caidas"])
        self.assertEqual(d["mercado"]["con_error"], ["Local"])
        self.assertEqual(d["actual"]["cotizaciones"], [])
        self.assertEqual(d["actual"]["series"], [])

    def test_una_fuente_caida_conserva_cuotas_de_la_buena(self):
        self.evento_real()
        self.ingerir()
        caida = FuenteLocal("caida")
        caida.marcar_error("HTTP 403")
        ausente = FuenteLocal("sin_clave", activa=False)
        self.capa.fuentes.extend((caida, ausente))
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            d = vivo.vivo(ahora=self.ahora)
        self.assertTrue(d["mercado"]["hay_cuotas"])
        self.assertFalse(d["mercado"]["todas_caidas"])
        self.assertEqual(d["mercado"]["con_error"], ["Caida"])
        self.assertEqual({f["clave"] for f in d["mercado"]["fuentes"]}, {"local", "caida"})

    def test_evento_sin_peleas_ni_fuentes_no_rompe(self):
        self.evento_real([])
        self.capa.fuentes.clear()
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            d = vivo.vivo(ahora=self.ahora)
        self.assertIsNone(d["actual"])
        self.assertEqual(d["peleas"], [])
        self.assertFalse(d["mercado"]["hay_cuotas"])

    def test_endpoint_http_lee_cache_y_no_arranca_polling_ni_espera(self):
        from webui import server
        # Sin contexto de lifespan: se prueba el endpoint, no los hilos.
        # Eliminar esperas e intentos de red prueba la causa de su rapidez,
        # sin depender de un límite de segundos sensible al equipo.
        cliente = TestClient(server.app)
        self.addCleanup(cliente.close)
        with mock.patch.object(C, "MERCADO_SIMULADO", True), \
                mock.patch.object(vivo, "_base", wraps=vivo._base) as armar, \
                mock.patch.object(Capa, "arrancar") as arrancar, \
                mock.patch.object(Capa, "consultar_todas") as consultar, \
                mock.patch.object(simulado.FuenteSimulada, "obtener") as obtener, \
                mock.patch("time.sleep", side_effect=AssertionError("el endpoint no espera")):
            primera = cliente.get("/api/mercado/vivo")
            self.assertEqual(primera.status_code, 200)
            actual = primera.json()["actual"]
            ultima = max(p["t"] for s in actual["series"] for p in s["puntos"])
            segunda = cliente.get("/api/mercado/vivo", params={"desde": ultima, "pelea_id": actual["pelea_id"]})
            self.assertEqual(segunda.status_code, 200)
            self.assertTrue(segunda.json()["actual"]["incremental"])
            self.assertEqual(armar.call_count, 1)
            arrancar.assert_not_called()
            consultar.assert_not_called()
            obtener.assert_not_called()

    def test_endpoint_http_marcas_estrictas_y_evento_coincidente(self):
        from webui import server
        cliente = TestClient(server.app)
        self.addCleanup(cliente.close)
        with mock.patch.object(C, "MERCADO_SIMULADO", True):
            original = cliente.get("/api/mercado/vivo").json()
            pid = original["actual"]["pelea_id"]
            marcada = cliente.get("/api/mercado/vivo", params={
                "terminadas": json.dumps([pid]), "evento_id": "simulado"})
            self.assertEqual(marcada.status_code, 200)
            self.assertNotEqual(marcada.json()["actual"]["pelea_id"], pid)
            otra = cliente.get("/api/mercado/vivo", params={
                "terminadas": json.dumps([pid]), "evento_id": "otra_noche"})
            self.assertEqual(otra.json()["actual"]["pelea_id"], pid)
            for entrada in ("ayer", "{}", '[null]', '[1]', '[""]', json.dumps(["x"] * 51),
                            json.dumps(["x" * 301]), "x" * 10001):
                with self.subTest(entrada=entrada[:40]):
                    self.assertEqual(cliente.get("/api/mercado/vivo", params={
                        "terminadas": entrada, "evento_id": "simulado"}).status_code, 400)
            self.assertEqual(cliente.get("/api/mercado/vivo", params={"evento_id": "x" * 301}).status_code, 400)


class SeriesVivo(BaseVivo):

    def test_mejor_cuota_empates_y_polymarket_fuera_de_mejor(self):
        def cuota(casa, am_a=-150, am_b=125):
            return cotizacion("local", "casa", casa, "a|b", a_iso(self.ahora),
                              a_americana=am_a, b_americana=am_b)
        cots = [cuota("A"), cuota("B"), cuota("C", -160, 130),
                cotizacion("polymarket", "mercado_prediccion", "Polymarket", "a|b", a_iso(self.ahora),
                           a_prob=0.5, b_prob=0.5)]
        filas = vivo._filas(cots, {"local": "Local", "polymarket": "Polymarket"})
        self.assertEqual({f["casa"] for f in filas if f["mejor_a"]}, {"A", "B"})
        self.assertEqual({f["casa"] for f in filas if f["mejor_b"]}, {"C"})
        self.assertEqual(filas[-1]["tipo"], "mercado_prediccion")
        self.assertFalse(filas[-1]["mejor_a"] or filas[-1]["mejor_b"])

    def test_recorte_ancla_casa_sin_movimientos_y_conserva_extremos(self):
        punto = lambda i: {"t": a_iso(self.ahora + i), "a": -150, "b": 125, "pa": .57, "pb": .43}
        serie = {"fuente": "local", "casa": "A", "tipo": "casa", "puntos": [punto(-200), punto(-100)]}
        borde = a_iso(self.ahora)
        recortada = vivo._recortar([serie], borde)[0]
        self.assertEqual(recortada["puntos"], [{**punto(-100), "t": borde}])
        serie["puntos"] = [punto(i) for i in range(1000)]
        recortada = vivo._recortar([serie], borde)[0]
        self.assertEqual(len(recortada["puntos"]), vivo.MAX_PUNTOS)
        self.assertEqual((recortada["puntos"][0], recortada["puntos"][-1]), (punto(0), punto(999)))

    def test_deduplica_casa_entre_fuentes_y_polymarket_con_nombre_propio(self):
        series = [{"fuente": f, "casa": c, "tipo": t, "puntos": [dict(t=a_iso(self.ahora + i)) for i in range(n)]}
                  for f, c, t, n in (("bfo", "DraftKings", "casa", 1),
                                      ("odds_api", "Draft Kings", "casa", 2),
                                      ("polymarket", "Mercado X", "mercado_prediccion", 1))]
        unidas = vivo._unir_series(series, {("odds_api", "Draft Kings"): a_iso(self.ahora)}, {})
        self.assertEqual(len(unidas), 2)
        self.assertEqual(unidas[0]["fuente"], "odds_api")
        self.assertEqual(unidas[0]["hasta"], a_iso(self.ahora))
        self.assertEqual(unidas[1]["etiqueta"], "Polymarket")

    def test_desaparicion_de_polymarket_no_confirma_resultado(self):
        pid = cruce.pelea_id("Alex Pereira", "Magomed Ankalaev")
        H.escribir_cache("polymarket", {"consultado": self.ahora - 60, "mercados": []})
        self.assertEqual(vivo._polymarket_resueltos({pid}, calendario.evento_en_vivo(self.ahora) or {}), {})

    def resuelto(self, **extra):
        return {"a": "Alex Pereira", "b": "Magomed Ankalaev", "inicio": a_iso(self.ahora),
                "closed": True, "umaResolutionStatus": "resolved",
                "outcomes": ["Alex Pereira", "Magomed Ankalaev"], "outcomePrices": ["1", "0"], **extra}

    def test_resolucion_final_orienta_100_por_ciento_sin_inventar_resultado_oficial(self):
        self.evento_real([{"a": "Magomed Ankalaev", "b": "Alex Pereira", "seccion": "estelar"}])
        self.ingerir()
        H.escribir_cache("polymarket", {"resueltos": [self.resuelto()]})
        with mock.patch.object(vivo, "_resultados_base", return_value=set()):
            d = vivo.vivo(ahora=self.ahora)
        self.assertEqual(d["actual"]["motivo_clave"], "mercado_resuelto")
        self.assertEqual(d["actual"]["estado"], "terminada")
        self.assertEqual(d["actual"]["resolucion"], {"fuente": "polymarket", "ganador": "Alex Pereira",
            "a": 0, "b": 1, "oficial": False, "etiqueta": "Mercado resuelto"})
        self.assertEqual(d["actual"]["consenso"]["a"]["etiqueta"], "Underdog")

    def test_revancha_vieja_nombre_parcial_o_datos_incompletos_no_cierran(self):
        self.evento_real()
        pid = cruce.pelea_id("Alex Pereira", "Magomed Ankalaev")
        ev = calendario.evento_en_vivo(self.ahora)
        for mala in (self.resuelto(inicio=a_iso(self.ahora - 40 * 86400)),
                     self.resuelto(a="Pereira"), self.resuelto(inicio=None),
                     self.resuelto(outcomes=["Otro Pereira", "Magomed Ankalaev"]), {}):
            with self.subTest(mala=mala):
                H.escribir_cache("polymarket", {"resueltos": [mala, None]})
                self.assertEqual(vivo._polymarket_resueltos({pid}, ev), {})


if __name__ == "__main__":
    unittest.main()
