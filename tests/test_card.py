"""Pruebas de src/card.py: lectura del CSV de cartelera."""
import unittest
from unittest import mock

from tests.util import card_aislado, peleador, predecir
from tests.util import aislar_base

# Base propia del módulo: nunca abrir data/ufc.db (ver tests/util.aislar_base).
setUpModule, tearDownModule = aislar_base()


class CortoAviso(unittest.TestCase):
    """Columnas corto_a / corto_b: el usuario las llena a mano, a veces a medias."""

    def _csv(self, tmp, filas):
        ruta = tmp / "cartelera.csv"
        ruta.write_text("fighter_a,fighter_b,segment,corto_a,corto_b\n" + "\n".join(filas),
                        encoding="utf-8")
        return ruta

    def test_celdas_vacias_no_revientan(self):
        # BUG: int(nan or 0) -> ValueError. NaN es truthy, así que `or 0` no lo limpiaba.
        with card_aislado() as env:
            ruta = self._csv(env["tmp"], ["Uno Uno,Dos Dos,,1,", "Tres Tres,Cuatro Cuatro,,,"])
            res = predecir(env["card"], ruta)
        self.assertEqual(len(res["rows"]), 2)

    def test_el_csv_manda_y_lo_vacio_cae_a_wikipedia(self):
        # Celda llena -> se usa tal cual. Celda vacía -> "no lo sé", igual que si la
        # columna no existiera: se consulta el caché de Wikipedia.
        with card_aislado(flag_wikipedia=1) as env:
            ruta = self._csv(env["tmp"], ["Uno Uno,Dos Dos,,0,"])
            res = predecir(env["card"], ruta)
        fila = res["rows"][0]
        self.assertEqual(fila["corto_a"], 0)           # lo dijo el CSV
        self.assertEqual(fila["corto_b"], 1)           # vacío -> Wikipedia
        self.assertEqual(env["consultas_wiki"], ["Dos Dos"])


class AvancePorPelea(unittest.TestCase):
    def test_informa_cada_ficha_antes_de_consultarla_y_cuenta_las_omitidas(self):
        eventos = []
        with card_aislado() as env:
            ruta = env["tmp"] / "c.csv"
            ruta.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\nTres Tres,Cuatro Cuatro\n",
                            encoding="utf-8")

            def ficha(nombre):
                self.assertIn(nombre, eventos[-1]["detalle"])
                self.assertEqual(eventos[-1]["etapa"], "prediccion")
                return (None, "NO_ENCONTRADO") if nombre == "Tres Tres" else (peleador(nombre), "ufcstats")

            with mock.patch.object(env["card"], "get_stats", side_effect=ficha):
                res = predecir(env["card"], ruta, progreso=eventos.append)
        self.assertEqual(len(res["rows"]), 1)
        avances = [e for e in eventos if e["etapa"] == "prediccion"]
        self.assertEqual(avances[-1]["completadas"], 2)
        self.assertEqual(avances[-1]["total"], 2)
        self.assertIn("omitida", avances[-1]["detalle"])
        self.assertEqual(eventos[-1]["etapa"], "informes")
        self.assertEqual(res["rows"][0]["orden_cartelera"], 0)
        self.assertEqual(res["consenso"][0]["total_cartelera"], 2)

    def test_omitir_una_principal_conserva_el_orden_de_fuente_en_json(self):
        from webui import engine as E
        with card_aislado() as env:
            ruta = env["tmp"] / "c.csv"
            ruta.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\nTres Tres,Cuatro Cuatro\nCinco Cinco,Seis Seis\n",
                            encoding="utf-8")
            with mock.patch.object(env["card"], "get_stats", side_effect=lambda nombre:
                    (None, "NO_ENCONTRADO") if nombre == "Tres Tres" else (peleador(nombre), "ufcstats")):
                res = predecir(env["card"], ruta)
            datos, _ = E._serializar(res, ruta)
        self.assertEqual([p["orden_cartelera"] for p in datos["peleas"]], [0, 2])
        self.assertEqual([p["total_cartelera"] for p in datos["peleas"]], [3, 3])


class IdentidadYHistorial(unittest.TestCase):
    def test_ultimas_peleas_viajan_en_info_con_el_mismo_corte_de_las_features(self):
        from webui import engine as E
        ultimas = [{"resultado": "W", "metodo": "U-DEC", "rival": "Rival Real", "fecha": "2024-01-01"},
                   {"resultado": "NC", "metodo": "CNC", "rival": "Otro Rival", "fecha": "2023-01-01"}]
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"].oposicion, "features", wraps=env["card"].oposicion.features) as features, \
                    mock.patch.object(env["card"].oposicion, "ultimas_peleas",
                                      side_effect=lambda nombre, hasta: ultimas if nombre == "Uno Uno" else []) as recientes:
                res = predecir(env["card"], csv)
                datos, _ = E._serializar(res, csv)
            corte_features = features.call_args.args[2]
            self.assertTrue(all(call.args[1] == corte_features for call in recientes.call_args_list))
        self.assertEqual(datos["peleas"][0]["info_a"]["ultimas_peleas"], ultimas)
        self.assertEqual(datos["peleas"][0]["info_b"]["ultimas_peleas"], [])

    def test_metodos_del_historial_se_exportan_y_el_debut_sin_victorias_no_inventa_tasas(self):
        from src import value
        from webui import engine as E
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"], "get_stats", side_effect=lambda nombre: (
                    peleador(nombre, wins=0 if nombre == "Dos Dos" else 10), "ufcstats")), \
                    mock.patch.object(value, "cargar_modelo_metodo", return_value=(None, None)):
                res = predecir(env["card"], csv)
                datos, _ = E._serializar(res, csv)
        pelea = datos["peleas"][0]
        self.assertEqual(pelea["metodo_hist_a"], {"KO/TKO": 0.35, "Submission": 0.15, "Decision": 0.50})
        self.assertIsNone(pelea["metodo_hist_b"])

    def test_modelo_de_seis_resultados_funciona_sin_mercados_ni_cuotas(self):
        import numpy as np
        from src import value
        from webui import engine as E
        p6 = np.array([0.31, 0.07, 0.22, 0.15, 0.05, 0.20])
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            modelo = object()
            with mock.patch.object(value, "cargar_modelo_metodo", return_value=(modelo, ["streak_diff"])), \
                    mock.patch.object(value, "_p6_simetrica", return_value=p6) as predecir6:
                res = predecir(env["card"], csv)
                datos, _ = E._serializar(res, csv)
            predecir6.assert_called_once()
            self.assertIs(predecir6.call_args.args[0], modelo)
        self.assertFalse(datos["con_cuotas"])
        self.assertEqual(datos["peleas"][0]["probabilidades_metodo"], dict(zip(value.CLASES_METODO, p6)))

    def test_bobby_green_usa_la_fila_vigente_de_king_green(self):
        import config as C
        with card_aislado() as env:
            csv = env["tmp"] / "fighters.csv"
            csv.write_text("name,n_peleas_hist\nBobby Green,0\nKing Green,28\n", encoding="utf-8")
            with mock.patch.object(C, "FIGHTERS_CSV", csv):
                ficha = env["card"]._from_fighters_csv("Bobby Green")
        self.assertEqual(ficha["name"], "King Green")
        self.assertEqual(ficha["n_peleas_hist"], 28)

    def test_historial_ausente_admite_none_y_conserva_advertencia_sin_declarar_cero(self):
        from webui import engine as E
        for conteo in (None, 28):
            with self.subTest(conteo=conteo), card_aislado() as env:
                csv = env["tmp"] / "c.csv"
                csv.write_text("fighter_a,fighter_b\nKing Green,Dos Dos\n", encoding="utf-8")

                def ficha(nombre):
                    cambios = {"n_peleas_hist": conteo, "historial_disponible": False} \
                        if nombre == "King Green" else {}
                    return peleador(nombre, **cambios), "ufcstats"

                with mock.patch.object(env["card"], "get_stats", side_effect=ficha):
                    consenso = predecir(env["card"], csv)["consenso"][0]
            self.assertIn("Green", consenso["pocos"])
            self.assertEqual(consenso["info_a"]["n_peleas_hist"], conteo)
            self.assertFalse(consenso["info_a"]["debut_ufc_confirmado"])
            texto = E._por_que_confianza(0.7, consenso["pocos"], {"King Green": consenso["info_a"]})
            self.assertIn("no está disponible", texto)
            self.assertNotIn("ninguna pelea", texto)

    def test_cero_confirmado_mantiene_la_explicacion_de_debut(self):
        from webui import engine as E
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"], "get_stats", side_effect=lambda nombre: (
                    peleador(nombre, n_peleas_hist=0 if nombre == "Uno Uno" else 8,
                             historial_disponible=True,
                             n_peleas_ufc=0 if nombre == "Uno Uno" else 8,
                             historial_ufc_confirmado=True), "ufcstats")):
                consenso = predecir(env["card"], csv)["consenso"][0]
        texto = E._por_que_confianza(0.7, consenso["pocos"], {"Uno Uno": consenso["info_a"]})
        self.assertIn("ninguna pelea", texto)
        self.assertTrue(consenso["info_a"]["debut_ufc_confirmado"])
        self.assertFalse(consenso["info_b"]["debut_ufc_confirmado"])

    def test_cero_local_sin_evidencia_ufc_no_equivale_a_debut(self):
        from webui import engine as E
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"], "get_stats", side_effect=lambda nombre: (
                    peleador(nombre, n_peleas_hist=0, historial_disponible=True), "kaggle")):
                consenso = predecir(env["card"], csv)["consenso"][0]
        self.assertFalse(consenso["info_a"]["debut_ufc_confirmado"])
        self.assertIsNone(consenso["info_a"]["n_peleas_ufc"])
        texto = E._por_que_confianza(0.7, consenso["pocos"], {"Uno Uno": consenso["info_a"]})
        self.assertIn("no confirma un debut", texto)
        self.assertNotIn("ninguna pelea en UFC", texto)

    def test_debut_ufc_no_depende_del_total_de_otras_organizaciones(self):
        from webui import engine as E
        with card_aislado() as env:
            csv = env["tmp"] / "c.csv"
            csv.write_text("fighter_a,fighter_b\nUno Uno,Dos Dos\n", encoding="utf-8")
            with mock.patch.object(env["card"], "get_stats", side_effect=lambda nombre: (
                    peleador(nombre, n_peleas_hist=5, n_peleas_ufc=0,
                             historial_ufc_confirmado=True), "ufcstats")):
                res = predecir(env["card"], csv)
                consenso = res["consenso"][0]
                datos, _ = E._serializar(res, csv)
        self.assertTrue(consenso["info_a"]["debut_ufc_confirmado"])
        self.assertTrue(consenso["info_b"]["debut_ufc_confirmado"])
        self.assertEqual(datos["peleas"][0]["debutantes"], ["Uno Uno", "Dos Dos"])
        self.assertEqual(datos["peleas"][0]["confianza"], "NO FIABLE")

    def test_fallback_kaggle_tambien_enriquece_historial(self):
        from src import card
        from src import control_stats as CS
        with mock.patch.object(card.ufcstats, "get_fighter", return_value=None), \
                mock.patch.object(card, "_from_fighters_csv", return_value=peleador("King Green")), \
                mock.patch.object(CS, "stats_previas", return_value={**CS.NEUTRO, "historial_disponible": False}):
            ficha, fuente = card.get_stats("Bobby Green")
        self.assertEqual(fuente, "kaggle")
        self.assertIsNone(ficha["n_peleas_hist"])
        self.assertFalse(ficha["historial_disponible"])


class _ModeloConSesgo:
    """Un XGBoost no es perfectamente antisimétrico; este exagera el defecto:
    le da +0,4 de logit a quien esté en la columna A."""

    def predict_proba(self, X):
        import numpy as np
        z = 0.4 + 0.5 * X["streak_diff"].to_numpy(dtype=float)
        p = 1 / (1 + np.exp(-z))
        return np.column_stack([1 - p, p])


class SimetriaDelGanador(unittest.TestCase):

    def test_invertir_el_csv_no_cambia_la_probabilidad(self):
        # BUG: se predecía en UNA orientación. Medido en 25 peleas reales: dar
        # vuelta A y B movía el modelo 3,8 pts de media (máx 8,7) y cambiaba el
        # pick en 2. Los calibradores ya se ajustaban con la p simetrizada.
        def corrida(filas):
            with card_aislado(modelo=_ModeloConSesgo()) as env:
                ruta = env["tmp"] / "c.csv"
                ruta.write_text("fighter_a,fighter_b,odds_a,odds_b\n" + "\n".join(filas), encoding="utf-8")
                with mock.patch.object(env["card"], "get_stats", lambda n: (peleador(n, streak=3 if n == "Uno Uno" else 0), "ufcstats")):
                    return predecir(env["card"], ruta)["consenso"][0]["v"].p_modelo_a
        p_ab = corrida(["Uno Uno,Dos Dos,1.80,2.10"])
        p_ba = corrida(["Dos Dos,Uno Uno,2.10,1.80"])
        self.assertAlmostEqual(p_ab, 1 - p_ba, places=9)


class EloPorDivision(unittest.TestCase):

    def test_usa_la_division_de_su_ultima_pelea(self):
        # BUG: se tomaba la PRIMERA fila del nombre en elo_ratings.csv, cuyo orden
        # depende de en qué categoría apareció primero CUALQUIER peleador. A 438
        # peleadores les daba el ELO de otra división (Volkanovski: 1498 de peso
        # ligero en vez de 1655 de peso pluma). Acá, con nombres de prueba.
        import tempfile
        from pathlib import Path
        import pandas as pd
        import config as C
        from src import card
        with tempfile.TemporaryDirectory() as tmp:
            tabla = Path(tmp) / "elo.csv"
            pd.DataFrame({"weight_class": ["Welterweight", "Lightweight"],
                          "fighter": ["Islam Makhachev", "Islam Makhachev"],
                          "elo": [1517.0, 1686.0]}).to_csv(tabla, index=False)
            with mock.patch.object(C, "ELO_TABLE", tabla), \
                    mock.patch.object(card.oposicion, "ultima_division", lambda n, hasta=None: "Lightweight"):
                self.assertEqual(card._elo({"name": "Islam Makhachev"}), 1686.0)
            with mock.patch.object(C, "ELO_TABLE", tabla), \
                    mock.patch.object(card.oposicion, "ultima_division", lambda n, hasta=None: None):
                self.assertEqual(card._elo({"name": "Islam Makhachev"}), 1517.0)   # sin dato: como antes

    def test_ultima_division_respeta_la_fecha(self):
        import tempfile
        from pathlib import Path
        import pandas as pd
        from src import oposicion
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "fights.csv"
            pd.DataFrame({"date": ["2024-01-01", "2025-06-01"], "event": ["e1", "e2"],
                          "fighter_a": ["Ana Uno", "Ana Uno"], "fighter_b": ["Bea Dos", "Cris Tres"],
                          "winner": ["Ana Uno", "Ana Uno"], "method": ["Decision", "KO/TKO"],
                          "weight_class": ["Lightweight", "Welterweight"]}).to_csv(csv, index=False)
            with mock.patch.object(oposicion, "FIGHTS_CSV", csv), mock.patch.object(oposicion, "_IDX", None), \
                    mock.patch("builtins.print"):
                self.assertEqual(oposicion.ultima_division("Ana Uno"), "Welterweight")
                self.assertEqual(oposicion.ultima_division("Ana Uno", "2025-06-01"), "Lightweight")
                self.assertIsNone(oposicion.ultima_division("Ana Uno", "2024-01-01"))
                self.assertIsNone(oposicion.ultima_division("Nadie"))


class ResumenDeApuestas(unittest.TestCase):
    """La decisión es la misma apuesta en el mercado de 7 y de 5 vías."""

    def _consenso(self, metodo6=None, metodo5=None):
        from src import value as V
        from src.simulate import monte_carlo
        met = {"KO/TKO": 0.3, "Submission": 0.15, "Decision": 0.55}
        v = V.analizar(0.55, 1.80, 2.10, cal={"intercepto": 0.0, "peso_mercado": 1.0,
                                              "peso_modelo": 0.0, "n": 1})
        return [{"a": "Juliana Miller", "b": "Ravena Oliveira Morais", "method": met,
                 "sim": monte_carlo(0.55, met, "Juliana Miller", "Ravena Oliveira Morais"),
                 "v": v, "pocos": [], "metodo6": metodo6, "metodo5": metodo5}]

    def test_la_decision_de_5_vias_tambien_es_apuesta_probada(self):
        # BUG: solo se miraba metodo6. Una decisión de 5 vías con EV >= 0 (la misma
        # apuesta, con el mismo respaldo) no aparecía en "Qué apostar".
        import contextlib, io
        from src import card
        ops5 = [{"clase": "A_DEC", "apostar": True, "ev": 0.06, "cuota_decimal": 3.0,
                 "kelly": 0.01, "p_final": 0.36, "sospechoso": False},
                {"clase": "A_FIN", "apostar": True, "ev": 0.20, "cuota_decimal": 2.2,
                 "kelly": 0.02, "p_final": 0.55, "sospechoso": False}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            card._imprimir_consenso(self._consenso(metodo5=ops5), con_cuotas=True)
        salida = buf.getvalue()
        self.assertIn("QUÉ APOSTAR (1", salida)
        self.assertIn("Miller x decisión", salida)

    def test_la_ui_recibe_el_mercado_de_5_vias(self):
        from webui import engine as E
        ops5 = [{"clase": "A_DEC", "apostar": True, "ev": 0.06, "cuota_decimal": 3.0,
                 "kelly": 0.01, "p_final": 0.36, "p_modelo": 0.35, "p_mercado": 0.33,
                 "sobrerredondeo": 1.21, "sospechoso": False, "aproximado": True}]
        consenso = self._consenso(metodo5=ops5)
        datos, _ = E._serializar({"rows": [], "consenso": consenso}, __import__("pathlib").Path("x.csv"))
        self.assertEqual(datos["peleas"][0]["metodo5"][0]["clase"], "A_DEC")


if __name__ == "__main__":
    unittest.main()
