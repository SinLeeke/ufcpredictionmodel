"""
Pruebas de src/corte.py: la repetición de una cartelera que ya pasó.

Lo que no se puede romper es lo mismo que rompió el backtest de carteleras
cuando "acertaba" 92%: nada posterior al corte puede entrar a la predicción.
Ni las stats, ni el ELO, ni el modelo, ni el orden de las esquinas (UFCStats
pone al ganador primero). El resultado real se lee después y solo se muestra.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from fastapi import HTTPException

import config as C
from src import corte as CT
from tests.util import card_aislado, peleador, predecir
from tests.util import aislar_base

# Base propia del módulo: nunca abrir data/ufc.db (ver tests/util.aislar_base).
setUpModule, tearDownModule = aislar_base()

# Como en UFCStats: el ganador SIEMPRE en fighter_a.
PELEAS = pd.DataFrame([
    {"event": "UFC 300: Alpha vs. Zulu", "date": "2024-04-13", "fighter_a": "Zed Zulu",
     "fighter_b": "Abe Alpha", "winner": "Zed Zulu", "method": "Decision",
     "method_detail": "U-DEC", "round": 5, "time": "5:00", "weight_class": "Lightweight",
     "fight_url": "u1"},
    {"event": "UFC 300: Alpha vs. Zulu", "date": "2024-04-13", "fighter_a": "Cid Campo",
     "fighter_b": "Bea Bravo", "winner": "Cid Campo", "method": "KO/TKO",
     "method_detail": "KO/TKO", "round": 1, "time": "0:30", "weight_class": "Flyweight",
     "fight_url": "u2"},
    {"event": "UFC 301: Bravo vs. Delta", "date": "2024-05-04", "fighter_a": "Dan Delta",
     "fighter_b": "Bea Bravo", "winner": "", "method": "Other",
     "method_detail": "CNC", "round": 2, "time": "1:00", "weight_class": "Flyweight",
     "fight_url": "u3"},
])


class _BaseLocal(unittest.TestCase):
    """corte.py con una base sintética y sin tocar data/."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        ruta = self.tmp / "ufcstats_fights.csv"
        PELEAS.to_csv(ruta, index=False)
        for parche in (mock.patch.object(CT, "PELEAS_CSV", ruta),
                       mock.patch.object(CT, "_al_dia", lambda: None),
                       mock.patch.object(CT, "_PELEAS", None),
                       mock.patch.object(CT, "_KAGGLE", {})):
            parche.start()
            self.addCleanup(parche.stop)


class Fecha(unittest.TestCase):

    def test_vacia_es_sin_corte(self):
        self.assertIsNone(CT.a_fecha(None))
        self.assertIsNone(CT.a_fecha("  "))

    def test_rechaza_lo_que_no_sirve_como_corte(self):
        for mala in ("15/11/2025", "2999-01-01", "2010-06-01"):
            with self.subTest(mala=mala), self.assertRaises(ValueError):
                CT.a_fecha(mala)
        self.assertEqual(CT.a_fecha("2024-04-13"), pd.Timestamp("2024-04-13"))


class Orientacion(_BaseLocal):

    def test_sin_esquina_conocida_no_pone_al_ganador_primero(self):
        # UFCStats trae "Zed Zulu" (el ganador) primero; el orden alfabético no.
        self.assertEqual(CT.orientar("Zed Zulu", "Abe Alpha", "2024-04-13", kaggle={}),
                         ("Abe Alpha", "Zed Zulu"))

    def test_la_esquina_roja_de_kaggle_va_primero(self):
        kaggle = {(pd.Timestamp("2024-04-13"), CT._clave_par("Zed Zulu", "Abe Alpha")):
                  {"R_fighter": "Zed Zulu", "B_fighter": "Abe Alpha"}}
        self.assertEqual(CT.orientar("Abe Alpha", "Zed Zulu", "2024-04-13", kaggle=kaggle),
                         ("Zed Zulu", "Abe Alpha"))

    def test_la_lista_tampoco_dice_quien_gano(self):
        with mock.patch.object(CT, "FECHA_MINIMA", pd.Timestamp("2020-01-01")):
            lista = CT.peleas_anteriores("")
        estelar = next(p for p in lista["peleas"] if p["evento"].startswith("UFC 300"))
        self.assertEqual((estelar["a"], estelar["b"]), ("Abe Alpha", "Zed Zulu"))
        self.assertTrue(estelar["estelar"])
        self.assertNotIn("winner", estelar)
        self.assertNotIn("ganador", estelar)

    def test_la_busqueda_pone_primero_las_peleas_del_peleador(self):
        with mock.patch.object(CT, "FECHA_MINIMA", pd.Timestamp("2020-01-01")):
            lista = CT.peleas_anteriores("bravo")
        # "Bravo" está en el nombre de un evento y en dos peleas de Bea Bravo.
        self.assertTrue(all("Bea Bravo" in (p["a"], p["b"]) for p in lista["peleas"][:2]))


class ResultadoReal(_BaseLocal):

    def test_lee_la_pelea_desde_el_corte_y_compara_con_el_pronostico(self):
        r = CT.resultado_real("Abe Alpha", "Zed Zulu", "2024-04-13", pronostico="Zed Zulu")
        self.assertEqual((r["ganador"], r["lado"], r["acierto"]), ("Zed Zulu", "b", True))
        self.assertEqual((r["como"], r["asalto"]), ("decisión unánime", 5))
        r = CT.resultado_real("Abe Alpha", "Zed Zulu", "2024-04-13", pronostico="Abe Alpha")
        self.assertIs(r["acierto"], False)

    def test_una_pelea_anterior_al_corte_no_es_su_resultado(self):
        self.assertIsNone(CT.resultado_real("Abe Alpha", "Zed Zulu", "2024-04-14"))

    def test_sin_ganador_no_hay_acierto_ni_fallo(self):
        r = CT.resultado_real("Bea Bravo", "Dan Delta", "2024-05-04", pronostico="Bea Bravo")
        self.assertEqual((r["ganador"], r["lado"], r["acierto"], r["como"]),
                         ("", None, None, "sin resultado"))

    def test_si_la_pelea_cae_dias_antes_del_corte_se_corta_en_su_fecha(self):
        # Betano fecha en hora de Chile y UFCStats en la del evento: cortar en
        # la fecha del archivo dejaba la pelea misma DENTRO de los datos.
        par = [("Abe Alpha", "Zed Zulu")]
        self.assertEqual(CT.corte_efectivo(par, "2024-04-14"), pd.Timestamp("2024-04-13"))
        self.assertEqual(CT.corte_efectivo(par, "2024-04-20"), pd.Timestamp("2024-04-20"))


class EventoComoCartelera(_BaseLocal):

    def test_arma_el_csv_sin_resultado_y_con_la_estelar_al_final(self):
        with mock.patch.object(C, "ROOT", self.tmp):
            ruta = CT.cartelera_de_evento("UFC 300: Alpha vs. Zulu", "2024-04-13")
        df = pd.read_csv(ruta)
        self.assertTrue(ruta.name.startswith("historico_2024-04-13_"))
        self.assertEqual(list(df["fighter_a"]), ["Bea Bravo", "Abe Alpha"])
        self.assertEqual(df["segment"].fillna("").tolist(), ["", "Estelar"])
        self.assertFalse({"winner", "method", "ganador"} & set(df.columns))

    def test_las_cuotas_americanas_pasan_a_decimales(self):
        kaggle = {(pd.Timestamp("2024-04-13"), CT._clave_par("Zed Zulu", "Abe Alpha")):
                  {"R_fighter": "Zed Zulu", "B_fighter": "Abe Alpha", "R_odds": -200, "B_odds": 170}}
        with mock.patch.object(C, "ROOT", self.tmp), mock.patch.object(CT, "_KAGGLE", kaggle):
            df = pd.read_csv(CT.cartelera_de_evento("UFC 300: Alpha vs. Zulu", "2024-04-13"))
        estelar = df[df["segment"] == "Estelar"].iloc[0]
        self.assertEqual((estelar["fighter_a"], estelar["odds_a"], estelar["odds_b"]),
                         ("Zed Zulu", 1.5, 2.7))


class StatsALaFecha(unittest.TestCase):

    def test_solo_cuentan_las_peleas_estrictamente_anteriores(self):
        hist = pd.DataFrame({
            "fighter": ["Ana Uno"] * 3, "date": pd.to_datetime(["2023-01-01", "2023-06-01", "2024-01-01"]),
            "won": [1, 1, 0], "method": ["KO/TKO", "Decision", "Decision"], "dur_min": [5.0, 15.0, 15.0],
            "sig_landed": [10, 30, 40], "sig_att": [20, 60, 80], "opp_sig_landed": [5, 20, 60],
            "opp_sig_att": [20, 60, 90], "td_landed": [0, 1, 0], "td_att": [1, 2, 3], "opp_td_landed": [0, 0, 2],
            "opp_td_att": [0, 1, 3], "sub_att": [0, 0, 0], "ctrl_sec": [0, 60, 0], "opp_ctrl_sec": [0, 0, 120],
            "ground_landed": [0, 3, 0], "kd": [1, 0, 0]})
        with mock.patch.object(CT, "_historial", lambda: hist), \
                mock.patch.object(CT, "_completar", lambda d, nombre, fecha: d):
            d = CT.stats_a_fecha("Ana Uno", "2024-01-01")       # la de ese día NO
            self.assertEqual((d["wins"], d["losses"], d["streak"]), (2, 0, 2))
            self.assertEqual(d["days_since_last_fight"], float((pd.Timestamp("2024-01-01")
                                                                 - pd.Timestamp("2023-06-01")).days))
            self.assertIsNone(CT.stats_a_fecha("Ana Uno", "2023-01-01"))


class ModelosALaFecha(unittest.TestCase):

    def _features(self, ruta: Path):
        fechas = pd.date_range("2018-01-01", "2024-01-01", freq="7D")
        pd.DataFrame({"date": fechas, "y": np.arange(len(fechas)) % 2,
                      "method": "Decision"}).to_csv(ruta, index=False)

    def test_si_el_corte_es_posterior_al_entrenamiento_usa_produccion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "features.csv"
            self._features(ruta)
            with mock.patch.object(C, "FEATURES_CSV", ruta), \
                    mock.patch.object(CT, "_modelos_produccion", lambda fin: {"origen": "produccion", "fin": fin}):
                m = CT.modelos_a_fecha("2024-06-01")
        self.assertEqual(m["origen"], "produccion")

    def test_si_no_entrena_solo_con_lo_anterior_y_lo_guarda(self):
        from modelado import backtest_metodo as BM
        from modelado import train_model as TM
        vistos = []

        def ajustar(full):
            vistos.append(full["date"].max())
            return "ganador", "metodo"

        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "features.csv"
            self._features(ruta)
            with mock.patch.object(C, "FEATURES_CSV", ruta), \
                    mock.patch.object(CT, "CARPETA_MODELOS", Path(tmp) / "corte"), \
                    mock.patch.object(CT, "MIN_FILAS_ENTRENAMIENTO", 10), \
                    mock.patch.object(TM, "ajustar_modelos", side_effect=ajustar), \
                    mock.patch.object(BM, "entrenar_modelo6", lambda df: ("m6", ["c"], len(df))):
                m = CT.modelos_a_fecha("2022-03-03")
                CT.modelos_a_fecha("2022-03-03")               # segunda vez: del disco
        self.assertEqual(m["origen"], "reentrenado")
        self.assertEqual(len(vistos), 1)
        self.assertLess(vistos[0], pd.Timestamp("2022-03-03"))
        self.assertEqual(m["metodo6"], ("m6", ["c"]))


class CarteleraConCorte(unittest.TestCase):

    def _repetir(self, env, csv, **extra):
        resultado = {"ganador": "Dos Dos", "lado": "b", "acierto": True, "como": "KO/TKO",
                     "asalto": 1, "tiempo": "0:30", "fecha": "2024-04-13", "metodo": "KO/TKO", "evento": "E"}
        modelos = {"ganador": None, "metodo": None, "metodo6": None, "origen": "reentrenado",
                   "entrenado_hasta": "2024-04-06", "peleas": 1234}
        with mock.patch.object(env["card"], "get_stats", side_effect=AssertionError("ficha de hoy")), \
                mock.patch.object(CT, "corte_efectivo", lambda pares, f: pd.Timestamp(f)), \
                mock.patch.object(CT, "modelos_a_fecha", lambda f, avisar=None: modelos), \
                mock.patch.object(CT, "base_hasta", lambda: pd.Timestamp("2024-08-01")), \
                mock.patch.object(CT, "ficha_a_fecha", lambda n, f: (peleador(n), "historial")), \
                mock.patch.object(CT, "elo_a_fecha", lambda n, f: C.ELO_BASE), \
                mock.patch.object(CT, "resultado_real", lambda a, b, f, p: dict(resultado)):
            return predecir(env["card"], csv, corte="2024-04-13", **extra)

    def test_no_consulta_la_ficha_de_hoy_y_todo_usa_la_fecha_del_corte(self):
        with card_aislado() as env:
            csv = env["tmp"] / "historico_2024-04-13_e.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"].oposicion, "features",
                                   wraps=env["card"].oposicion.features) as features:
                res = self._repetir(env, csv)
            self.assertEqual(features.call_args.args[2], pd.Timestamp("2024-04-13"))
        self.assertEqual(res["repeticion"]["fecha"], "2024-04-13")
        self.assertEqual(res["repeticion"]["modelo"], "reentrenado")
        self.assertTrue(res["consenso"][0]["resultado"]["acierto"])
        self.assertEqual(res["consenso"][0]["info_a"]["fuente"], "historial")

    def test_sin_modelo_de_seis_propio_no_cae_al_de_produccion(self):
        from src import value
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b,odds_a,odds_b,odds_a_ko,odds_a_sub,odds_a_dec,"
                           "odds_b_ko,odds_b_sub,odds_b_dec\n"
                           "Uno Uno,Dos Dos,1.5,2.7,5,8,3,4,9,3.5\n", encoding="utf-8")
            with mock.patch.object(value, "analizar_metodo") as metodo:
                self._repetir(env, csv)
        metodo.assert_not_called()

    def test_la_ui_recibe_el_resultado_y_la_repeticion(self):
        from webui import engine as E
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            res = self._repetir(env, csv)
            datos, _ = E._serializar(res, csv)
        self.assertEqual(datos["repeticion"]["fecha"], "2024-04-13")
        self.assertEqual(datos["peleas"][0]["resultado"]["ganador"], "Dos Dos")


class ServidorYMotor(unittest.TestCase):

    def test_un_corte_mal_escrito_es_400_y_no_carga_nada(self):
        from webui import engine, server
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "cards").mkdir()
            (raiz / "cards" / "a.csv").write_text("fighter_a,fighter_b\n")
            cargas = []
            with mock.patch.object(C, "ROOT", raiz), \
                    mock.patch.object(engine, "cargar", lambda *a, **k: cargas.append(k)):
                with self.assertRaises(HTTPException) as e:
                    server.cargar_csv(server.CargaCSV(nombre="a.csv", corte="15/11/2025"))
                self.assertEqual(e.exception.status_code, 400)
                server.cargar_csv(server.CargaCSV(nombre="a.csv", corte="2024-04-13"))
        self.assertEqual(cargas, [{"corte": "2024-04-13"}])

    def test_refrescar_una_repeticion_no_la_convierte_en_una_de_hoy(self):
        from webui import engine
        estado = engine.Estado()
        estado.origen, estado.consulta, estado.corte = "csv", "a.csv", "2024-04-13"
        estado.csv_path = Path("a.csv")
        llamadas = []
        with mock.patch.object(engine, "ESTADO", estado), \
                mock.patch.object(engine, "cargar", lambda *a, **k: llamadas.append(k)):
            self.assertEqual(engine.refrescar(), "")
        self.assertEqual(llamadas, [{"corte": "2024-04-13"}])


if __name__ == "__main__":
    unittest.main()
