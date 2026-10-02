"""Regresiones de identidad y calidad del historial; fixtures aisladas, sin red."""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from bs4 import BeautifulSoup

from src import control_stats as CS, fighter_names as N, oposicion as O
from src import reemplazos as R, sherdog as S, ufcstats as U
from src.ufc_history import confirmed_ufc_debut, is_ufc_event
from tests.test_ufcstats import _fila, _soup


def _lista(*nombres):
    filas = []
    for nombre, url, peleas in nombres:
        primero, apellido = nombre.split(" ", 1)
        filas.append(
            '<tr class="b-statistics__table-row">'
            f'<td><a class="b-link" href="{url}">{primero}</a></td>'
            f'<td><a class="b-link" href="{url}">{apellido}</a></td>'
            f'<td></td><td>5\'10"</td><td>155 lbs.</td><td>71"</td>'
            f'<td>Orthodox</td><td>{peleas}</td><td>0</td><td>0</td></tr>')
    return BeautifulSoup("<table>" + "".join(filas) + "</table>", "html.parser")


class IdentidadesVerificadas(unittest.TestCase):
    def test_alias_verificados_no_mezclan_otros_green_ni_homonimos(self):
        self.assertTrue(N.same_fighter("Bobby Green", "King Green"))
        self.assertTrue(N.same_fighter("Ian Garry", "Ian Machado Garry"))
        self.assertFalse(N.same_fighter("Bobby Green", "Gabe Green"))
        self.assertFalse(N.same_fighter("Bobby Green", "Desmond Green"))
        self.assertFalse(N.same_fighter("Mike Davis", "Mike Davi"))
        self.assertEqual(N.canonical_key(" Jan Błachowicz "), "jan blachowicz")
        self.assertFalse(N.same_fighter("Derrick", "Derrick Lewis"))
        self.assertFalse(N.same_fighter("Derrick", "Derrick Krantz"))
        self.assertFalse(N.same_fighter("Mizuki Inoue", "Naoki Inoue"))
        self.assertFalse(N.same_fighter("Minotauro Nogueira", "Antonio Rogerio Nogueira"))

    def test_variantes_del_cruce_de_peleas_recuperan_su_historial(self):
        # Evidencia independiente de los CSV auditados, versionada como fixture.
        # Si un alias apunta a otro peleador, esta búsqueda no recupera la ficha.
        fixtures = json.loads((Path(__file__).parent / "fixtures/fighter_aliases.json").read_text(encoding="utf-8"))
        indice = {N.normalize_name(f["reference"]): {**CS.NEUTRO, "n_peleas": f["fights"],
                                                    "historial_disponible": True} for f in fixtures}
        with mock.patch.object(CS, "stats_previas", side_effect=lambda name, fecha=None:
                indice.get(N.canonical_key(name), {**CS.NEUTRO, "historial_disponible": False})):
            for f in fixtures:
                with self.subTest(alias=f["alias"]):
                    out = CS.enriquecer({"name": f["alias"]})
                    self.assertEqual(out["n_peleas_hist"], f["fights"])
                    self.assertTrue(out["historial_disponible"])

    def test_nombres_diferentes_no_colisionan_al_normalizar_aliases(self):
        grupos = {}
        for group in N._GROUPS:
            for name in group:
                norm = N.normalize_name(name)
                self.assertIn(grupos.get(norm, group), (group,))
                grupos[norm] = group

    def test_busqueda_bobby_devuelve_ficha_king_sin_elegir_otro_green(self):
        html = _lista(("Gabe Green", "/gabe", 20), ("King Green", "/king", 31))
        with mock.patch.object(U, "_get", return_value=html):
            self.assertEqual(U.find_fighter_url("Bobby Green"), "/king")

    def test_ian_con_apellido_compuesto_se_resuelve_exactamente(self):
        html = _lista(("Ian Machado Garry", "/ian", 10), ("John Garry", "/otro", 40))
        with mock.patch.object(U, "_get", return_value=html):
            self.assertEqual(U.find_fighter_url("Ian Garry"), "/ian")

    def test_orden_cong_wang_se_unifica_sin_confundir_otros_wang(self):
        self.assertTrue(N.same_fighter("Cong Wang", "Wang Cong"))
        self.assertEqual(N.preferred_name("Cong Wang"), "Wang Cong")
        self.assertFalse(N.same_fighter("Cong Wang", "Anying Wang"))
        self.assertFalse(N.same_fighter("Cong Wang", "Wang"))
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text(json.dumps({"cong wang": {"name": "Wang Cong",
                               "slpm": 6.82, "_parser": U.VERSION_PARSER}}), encoding="utf-8")
            with mock.patch.object(U, "CACHE_PATH", cache), \
                    mock.patch.object(U, "find_fighter_url", side_effect=AssertionError("no red")):
                self.assertEqual(U.get_fighter("Wang Cong")["slpm"], 6.82)
                self.assertEqual(U.get_fighter("Cong Wang")["slpm"], 6.82)

    def test_homonimos_siguen_desempatandose_por_ficha_completa(self):
        html = _lista(("Mike Davis", "/viejo", 2), ("Mike Davis", "/activo", 16))
        with mock.patch.object(U, "_get", return_value=html), mock.patch("builtins.print"):
            self.assertEqual(U.find_fighter_url("Mike Davis"), "/activo")

    def test_cache_de_nombre_anterior_se_reutiliza_sin_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text(json.dumps({"bobby green": {"name": "Bobby Green",
                               "slpm": 6.38, "_parser": U.VERSION_PARSER}}), encoding="utf-8")
            with mock.patch.object(U, "CACHE_PATH", cache), \
                    mock.patch.object(U, "find_fighter_url", side_effect=AssertionError("no red")):
                self.assertEqual(U.get_fighter("King Green")["slpm"], 6.38)


class ConteoDeFicha(unittest.TestCase):
    def test_conteo_incluye_nc_y_empate_y_excluye_pelea_futura(self):
        ficha = _soup(
            _fila("next", "A A", "UFC futura", "", "", "Jan. 01, 2030"),
            _fila("win", "B B", "UFC 1", "U-DEC", "", "Jan. 01, 2024"),
            _fila("draw", "C C", "UFC 2", "U-DEC", "", "Jan. 01, 2023"),
            _fila("nc", "D D", "UFC 3", "CNC", "", "Jan. 01, 2022"))
        self.assertEqual(U._parse_history(ficha)["n_peleas_ufc"], 3)

    def test_tabla_ausente_no_demuestra_cero_peleas(self):
        ausente = U._parse_history(_soup())
        self.assertIsNone(ausente["n_peleas_ufc"])
        self.assertFalse(confirmed_ufc_debut(ausente))
        debutante = _soup(_fila("next", "A A", "UFC futura", "", "", "Jan. 01, 2030"))
        hist = U._parse_history(debutante)
        self.assertEqual(hist["n_peleas_ufc"], 0)
        self.assertTrue(confirmed_ufc_debut(hist))

    def test_historial_de_otras_ligas_no_impide_debut_ufc_y_no_cambia_tasas(self):
        ficha = _soup(
            _fila("next", "A A", "UFC 330", "", "", "Jan. 01, 2030"),
            _fila("win", "B B", "WEC 53", "KO/TKO", "Punch", "Jan. 01, 2024"),
            _fila("loss", "C C", "Strikeforce: Finale", "SUB", "Choke", "Jan. 01, 2023"),
            _fila("win", "D D", "PRIDE 1", "U-DEC", "", "Jan. 01, 2022"))
        hist = U._parse_history(ficha)
        self.assertTrue(confirmed_ufc_debut(hist))
        self.assertEqual(hist["n_peleas_ufc"], 0)
        self.assertEqual(hist["wins"], 2)
        self.assertEqual(hist["losses"], 1)
        self.assertEqual(hist["win_ko_rate"], 0.5)

    def test_finale_ufc_y_no_contest_impiden_etiqueta_debut(self):
        for event in ("The Ultimate Fighter: Team GSP vs Team Koscheck Finale", "Noche UFC: Silva vs. Delgado",
                      "Ortiz vs Shamrock 3: The Final Chapter"):
            with self.subTest(event=event):
                hist = U._parse_history(_soup(_fila("nc", "B B", event, "CNC", "", "Jan. 01, 2024")))
                self.assertEqual(hist["n_peleas_ufc"], 1)
                self.assertFalse(confirmed_ufc_debut(hist))

    def test_evento_ambiguo_o_fila_incompleta_no_demuestran_debut(self):
        for event in ("Liga desconocida", "The Ultimate Fighter: Season 20", ""):
            with self.subTest(event=event):
                hist = U._parse_history(_soup(_fila("win", "B B", event, "U-DEC", "", "Jan. 01, 2024")))
                self.assertIsNone(hist["n_peleas_ufc"])
                self.assertFalse(confirmed_ufc_debut(hist))
        incompleta = _soup('<tr class="b-fight-details__table-row"><td class="b-fight-details__table-col">'
                          '<i class="b-flag__text">next</i></td></tr>')
        self.assertFalse(confirmed_ufc_debut(U._parse_history(incompleta)))

    def test_cache_cero_antiguo_refresca_solo_metadata_por_url_conocida(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            vieja = {"name": "Debutante", "wins": 0, "losses": 0, "slpm": 3.21,
                     "ufcstats_url": "http://fixture/fighter", "_parser": U.VERSION_PARSER}
            cache.write_text(json.dumps({"debutante": vieja}), encoding="utf-8")
            html = _soup(_fila("next", "A A", "UFC 330", "", "", "Jan. 01, 2030"))
            with mock.patch.object(U, "CACHE_PATH", cache), mock.patch.object(U, "_get", return_value=html) as get, \
                    mock.patch.object(U, "find_fighter_url", side_effect=AssertionError("no buscar")):
                ficha = U.get_fighter("Debutante")
                self.assertTrue(confirmed_ufc_debut(ficha))
                self.assertEqual(ficha["slpm"], 3.21)
                U.get_fighter("Debutante")
                get.assert_called_once_with("http://fixture/fighter")

    def test_cache_cero_sin_red_permanece_desconocido(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            vieja = {"name": "Debutante", "wins": 0, "losses": 0,
                     "ufcstats_url": "http://fixture/fighter", "_parser": U.VERSION_PARSER}
            cache.write_text(json.dumps({"debutante": vieja}), encoding="utf-8")
            with mock.patch.object(U, "CACHE_PATH", cache), mock.patch.object(U, "_get", return_value=None):
                self.assertFalse(confirmed_ufc_debut(U.get_fighter("Debutante")))

    def test_cache_con_record_de_otras_ligas_clasifica_debut_una_vez_y_conserva_estadisticas(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            vieja = {"name": "Debutante", "wins": 10, "losses": 2, "slpm": 4.72,
                     "win_ko_rate": 0.8, "win_sub_rate": 0.1, "win_dec_rate": 0.1,
                     "reach_cm": 193.0, "n_peleas_hist": 12,
                     "ufcstats_url": "http://fixture/fighter", "_parser": U.VERSION_PARSER}
            cache.write_text(json.dumps({"debutante": vieja}), encoding="utf-8")
            html = _soup(_fila("next", "A A", "UFC 330", "", "", "Jan. 01, 2030"),
                         _fila("win", "B B", "WEC 53", "KO/TKO", "Punch", "Jan. 01, 2024"),
                         _fila("loss", "C C", "Strikeforce: Finale", "SUB", "Choke", "Jan. 01, 2023"))
            with mock.patch.object(U, "CACHE_PATH", cache), mock.patch.object(U, "_get", return_value=html) as get, \
                    mock.patch.object(U, "find_fighter_url", side_effect=AssertionError("no buscar")):
                ficha = U.get_fighter("Debutante")
                self.assertTrue(confirmed_ufc_debut(ficha))
                self.assertEqual(ficha["n_peleas_ufc"], 0)
                self.assertEqual({campo: ficha[campo] for campo in vieja}, vieja)
                self.assertEqual(U.get_fighter("Debutante"), ficha)
                get.assert_called_once_with("http://fixture/fighter")

    def test_cache_con_record_clasifica_veterano_o_historial_ambiguo_sin_repetir_migracion(self):
        for evento, n_ufc in (("UFC 330", 1), ("Liga desconocida", None)):
            with self.subTest(evento=evento), tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "cache.json"
                vieja = {"name": "Veterano", "wins": 10, "losses": 2, "slpm": 4.72,
                         "ufcstats_url": "http://fixture/fighter", "_parser": U.VERSION_PARSER}
                cache.write_text(json.dumps({"veterano": vieja}), encoding="utf-8")
                html = _soup(_fila("win", "B B", evento, "U-DEC", "", "Jan. 01, 2024"))
                with mock.patch.object(U, "CACHE_PATH", cache), mock.patch.object(U, "_get", return_value=html) as get:
                    ficha = U.get_fighter("Veterano")
                    self.assertFalse(confirmed_ufc_debut(ficha))
                    self.assertEqual(ficha["n_peleas_ufc"], n_ufc)
                    self.assertEqual({campo: ficha[campo] for campo in vieja}, vieja)
                    self.assertEqual(U.get_fighter("Veterano"), ficha)
                    get.assert_called_once_with("http://fixture/fighter")

    def test_cache_con_record_sin_red_o_url_conserva_ficha_y_debut_desconocido(self):
        for url in ("http://fixture/fighter", None):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "cache.json"
                vieja = {"name": "Veterano", "wins": 10, "losses": 2,
                         "ufcstats_url": url, "_parser": U.VERSION_PARSER}
                cache.write_text(json.dumps({"veterano": vieja}), encoding="utf-8")
                with mock.patch.object(U, "CACHE_PATH", cache), mock.patch.object(U, "_get", return_value=None) as get, \
                        mock.patch.object(U, "find_fighter_url", side_effect=AssertionError("no buscar")):
                    ficha = U.get_fighter("Veterano")
                    self.assertEqual(ficha, vieja)
                    self.assertFalse(confirmed_ufc_debut(ficha))
                    if url:
                        get.assert_called_once_with(url)
                    else:
                        get.assert_not_called()


class LimiteAntiBot(unittest.TestCase):
    def test_challenge_resoluble_envia_prueba_y_mantiene_la_sesion(self):
        html = 'nonce="abc"; target=new Array(1+1).join(\'0\')'
        respuesta = mock.Mock(status_code=204)
        with mock.patch.object(U.time, "monotonic", return_value=0), \
                mock.patch.object(U._SESSION, "post", return_value=respuesta) as post:
            self.assertTrue(U._solve_challenge(html))
        datos = post.call_args.kwargs["data"]
        self.assertTrue(hashlib.sha256(f"abc:{datos['n']}".encode()).hexdigest().startswith("0"))
        self.assertEqual(post.call_args.kwargs["timeout"], U.C.REQUEST_TIMEOUT_SEC)

    def test_challenge_imposible_agota_limite_y_get_devuelve_fallo(self):
        html = 'Checking your browser; nonce="abc"; target=new Array(64+1).join(\'0\')'
        respuesta = mock.Mock(status_code=200, text=html)
        with mock.patch.object(U.time, "monotonic", side_effect=[0, U.C.REQUEST_TIMEOUT_SEC]), \
                mock.patch.object(U.time, "sleep"), \
                mock.patch.object(U._SESSION, "get", return_value=respuesta), \
                mock.patch.object(U._SESSION, "post", side_effect=AssertionError("no POST")), \
                mock.patch("builtins.print"):
            self.assertIsNone(U._get("http://fixture/fighter"))

    def test_dificultad_fuera_de_sha256_o_malformada_se_rechaza_sin_hash(self):
        for dificultad in ("0", "65", "999999999999999999999999", "-1", "oops"):
            with self.subTest(dificultad=dificultad), \
                    mock.patch.object(U.hashlib, "sha256", side_effect=AssertionError("no hash")), \
                    mock.patch.object(U._SESSION, "post", side_effect=AssertionError("no POST")), \
                    mock.patch("builtins.print"):
                html = f'nonce="abc"; target=new Array({dificultad}+1).join(\'0\')'
                self.assertFalse(U._solve_challenge(html))


class HistorialDeControl(unittest.TestCase):
    def _archivos(self, carpeta):
        stats = carpeta / "stats.csv"
        eventos = carpeta / "ufcstats_fights.csv"
        filas, fights = [], []
        # La misma identidad figura con su nombre anterior y vigente.
        for i, (nombre, fecha) in enumerate((('Bobby Green', '2020-01-01'),
                                             ('King Green', '2024-01-01'))):
            url = f"fight-{i}"
            rival = f"Rival {i}"
            for peleador in (nombre, rival):
                filas.append(dict(fight_url=url, fighter=peleador, date=fecha,
                                  sig_landed=40, sig_att=80, td_landed=1, td_att=4,
                                  ctrl_sec=120, ground_landed=10, kd=1))
            fights.append(dict(fight_url=url, date=fecha, round=3, time="5:00",
                               event=f"UFC {i}", fighter_a=nombre, fighter_b=rival,
                               winner=nombre, method="Decision", weight_class="Lightweight"))
        # Duplicado de la primera pelea bajo el nombre nuevo: no contar dos veces.
        filas.append({**filas[0], "fighter": "King Green"})
        pd.DataFrame(filas).to_csv(stats, index=False)
        pd.DataFrame(fights).to_csv(eventos, index=False)
        return stats, eventos

    def test_cambio_de_nombre_conserva_historial_y_corte_temporal(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            stats, eventos = self._archivos(carpeta)
            with mock.patch.object(CS, "STATS_CSV", stats), \
                    mock.patch.object(CS.C, "DATA_PROCESSED", carpeta), \
                    mock.patch.object(CS, "_IDX", None), mock.patch("builtins.print"):
                bobby = CS.stats_previas("Bobby Green")
                king = CS.stats_previas("King Green")
                self.assertEqual(bobby, king)
                self.assertEqual(bobby["n_peleas"], 2)
                self.assertEqual(CS.stats_previas("King Green", "2024-01-01")["n_peleas"], 1)
                antes = CS.enriquecer({"name": "Bobby Green"}, "2020-01-01")
                self.assertEqual(antes["n_peleas_hist"], 0)
                self.assertTrue(antes["historial_disponible"])
            with mock.patch.object(O, "FIGHTS_CSV", eventos), \
                    mock.patch.object(O, "_IDX", None), mock.patch("builtins.print"):
                self.assertEqual(O.resumen("Bobby Green", "2025-01-01")["n"], 2)
                self.assertEqual(O.resumen("King Green", "2024-01-01")["n"], 1)
                self.assertEqual(O.ultima_division("Bobby Green"), "Lightweight")

    def test_falta_de_descarga_local_no_se_convierte_en_debut(self):
        with mock.patch.object(CS, "_IDX", {}):
            desconocido = CS.enriquecer({"name": "Veterano"})
            self.assertIsNone(desconocido["n_peleas_hist"])
            self.assertFalse(desconocido["historial_disponible"])
            self.assertEqual(desconocido["ctrl_per_min"], CS.PROMEDIO_LIGA["ctrl_per_min"])
            con_ficha = CS.enriquecer({"name": "Veterano", "n_peleas_ufc": 12})
            self.assertEqual(con_ficha["n_peleas_hist"], 12)
            self.assertFalse(con_ficha["historial_disponible"])
            # El total actual no puede filtrarse al pasado de un backtest.
            self.assertIsNone(CS.enriquecer({"name": "Veterano", "n_peleas_ufc": 12},
                                           "2020-01-01")["n_peleas_hist"])

    def test_historial_desconocido_no_dispara_respaldo_sherdog(self):
        stats = {"name": "Veterano", "n_peleas_hist": None}
        with mock.patch.object(S, "historial", side_effect=AssertionError("no red")):
            self.assertIs(S.completar(stats), stats)

    def test_reemplazo_cacheado_bajo_alias_anterior_sigue_reconociendose(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "reemplazos.json"
            cache.write_text(json.dumps({"UFC 1": ["bobby green"]}), encoding="utf-8")
            with mock.patch.object(R, "CACHE", cache), mock.patch.object(R, "_IDX", None):
                self.assertEqual(R.es_reemplazo("King Green", "UFC 1"), 1)
                self.assertEqual(R.es_reemplazo("Gabe Green", "UFC 1"), 0)


class UltimosResultadosVisibles(unittest.TestCase):
    def test_alias_corte_y_cinco_resultados_con_metodos_y_neutros_reales(self):
        peleas = [
            ("2023-01-01", "Bobby Green", "Rival Uno", "Bobby Green", "KO/TKO", "KO/TKO", "1"),
            ("2023-06-01", "Bobby Green", "Rival Dos", "Rival Dos", "Submission", "SUB", "2"),
            ("2024-01-01", "King Green", "Rival Tres", "", "Decision", "M-DEC", "3"),
            ("2024-04-01", "King Green", "Rival Cuatro", "", "Other", "CNC", "4"),
            ("2024-06-01", "Bobby Green", "Rival Cinco", "King Green", "Other", "DQ", "5"),
            ("2024-09-01", "King Green", "Rival Seis", "King Green", "Decision", "S-DEC", "6"),
            # Misma pelea descargada también bajo su alias: un solo cuadro.
            ("2024-09-01", "Bobby Green", "Rival Seis", "Bobby Green", "Decision", "S-DEC", "6"),
            # Fila ambigua: no convertirla en una derrota ni un empate.
            ("2024-11-01", "King Green", "Rival Desconocido", "", "Other", "", "7"),
            # El mismo día del corte y el futuro no entran.
            ("2025-01-01", "King Green", "Rival Siete", "King Green", "Decision", "U-DEC", "8"),
            ("2026-01-01", "King Green", "Rival Ocho", "King Green", "Decision", "U-DEC", "9"),
        ]
        filas = [{"date": fecha, "fighter_a": a, "fighter_b": b, "winner": winner,
                  "method": metodo, "method_detail": detalle, "fight_url": url}
                 for fecha, a, b, winner, metodo, detalle, url in peleas]
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "fights.csv"
            pd.DataFrame(filas).to_csv(csv, index=False)
            with mock.patch.object(O, "FIGHTS_CSV", csv), mock.patch.object(O, "_IDX", None), \
                    mock.patch("builtins.print"):
                bobby = O.ultimas_peleas("Bobby Green", "2025-01-01")
                self.assertEqual(bobby, O.ultimas_peleas("King Green", "2025-01-01"))
                self.assertEqual(len(bobby), 5)
                self.assertEqual([p["resultado"] for p in bobby], ["W", "W", "NC", "D", "L"])
                self.assertEqual([p["metodo"] for p in bobby], ["S-DEC", "DQ", "CNC", "M-DEC", "SUB"])
                self.assertEqual([p["rival"] for p in bobby], ["Rival Seis", "Rival Cinco", "Rival Cuatro",
                                                             "Rival Tres", "Rival Dos"])
                self.assertEqual([p["fecha"] for p in bobby], ["2024-09-01", "2024-06-01", "2024-04-01",
                                                             "2024-01-01", "2023-06-01"])
                self.assertEqual(O.ultimas_peleas("Bobby Green", "2023-01-01"), [])
                self.assertEqual(O.ultimas_peleas("Rival Dos", "2025-01-01"),
                                 [{"fecha": "2023-06-01", "rival": "Bobby Green", "resultado": "W", "metodo": "SUB"}])

    def test_historial_ausente_no_inventa_cuadros(self):
        with mock.patch.object(O, "_IDX", {}):
            self.assertEqual(O.ultimas_peleas("Desconocido", "2025-01-01"), [])


if __name__ == "__main__":
    unittest.main()
