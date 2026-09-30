"""Pruebas de src/betano_scraper.py: qué columnas del CSV llena cada mercado."""
import unittest
from unittest import mock

from src import betano_scraper as B

PELEA = {"fighter_a": "Juliana Miller", "fighter_b": "Ravena Oliveira Morais", "path": "/x/1/"}


def _respuesta(*mercados):
    return {"data": {"event": {"markets": [
        {"type": "H2HT", "name": "Ganador", "selections": [
            {"name": "Juliana Miller", "price": 1.29, "columnIndex": 0},
            {"name": "Ravena Oliveira Morais", "price": 3.55, "columnIndex": 1}]},
        *mercados]}}}


def _metodo5(nombre_fin):
    return {"name": "Método de victoria (5-way)", "selections": [
        {"name": f"Juliana Miller {nombre_fin}", "price": 2.20},
        {"name": "Juliana Miller por Decisión", "price": 3.00},
        {"name": f"Ravena Oliveira Morais {nombre_fin}", "price": 6.50},
        {"name": "Ravena Oliveira Morais por Decisión", "price": 8.00},
        {"name": "Empate", "price": 51.0}]}


class Metodo5Vias(unittest.TestCase):

    def _fila(self, respuesta):
        with mock.patch.object(B, "_get_json", lambda *a, **k: respuesta):
            return B.get_fight_odds(PELEA)

    def test_guarda_la_cuota_de_finalizacion(self):
        # BUG: la selección combinada se llama "...KO/TKO/DQ/Sumisión"; _metodo()
        # ve "sumision" antes que "ko", devuelve "sub", y la rama de 5 vías solo
        # guardaba "ko". odds_*_fin quedaba vacía SIEMPRE y analizar_metodo5, que
        # exige las 4 cuotas, descartaba la pelea entera (decisión incluida).
        for nombre in ("por KO/TKO/DQ/Sumisión", "por finalización", "por KO/TKO/DQ"):
            with self.subTest(nombre=nombre):
                fila = self._fila(_respuesta(_metodo5(nombre)))
                self.assertEqual((fila["odds_a_fin"], fila["odds_b_fin"]), (2.20, 6.50))
                self.assertEqual((fila["odds_a_dec"], fila["odds_b_dec"]), (3.00, 8.00))
                # sin número real de "solo KO" / "solo sumisión": vacías, no inventadas
                self.assertEqual((fila["odds_a_ko"], fila["odds_a_sub"]), ("", ""))

    def test_7_vias_no_cambia(self):
        m7 = {"name": "Método de victoria (7-way)", "selections": [
            {"name": "Juliana Miller por KO/TKO/DQ", "price": 3.0},
            {"name": "Juliana Miller por Sumisión", "price": 5.0},
            {"name": "Juliana Miller por Decisión", "price": 3.2},
            {"name": "Ravena Oliveira Morais por KO/TKO/DQ", "price": 12.0},
            {"name": "Ravena Oliveira Morais por Sumisión", "price": 15.0},
            {"name": "Ravena Oliveira Morais por Decisión", "price": 9.0},
            {"name": "Empate", "price": 51.0}]}
        fila = self._fila(_respuesta(m7))
        self.assertEqual([fila[f"odds_a_{k}"] for k in ("ko", "sub", "dec")], [3.0, 5.0, 3.2])
        self.assertEqual([fila[f"odds_b_{k}"] for k in ("ko", "sub", "dec")], [12.0, 15.0, 9.0])
        self.assertEqual((fila["odds_a_fin"], fila["odds_b_fin"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
