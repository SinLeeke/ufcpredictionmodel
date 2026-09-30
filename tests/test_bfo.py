"""Pruebas de src/bfo_odds.py: cruce de fechas y caché incremental."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from src import bfo_odds as BFO


class Cruce(unittest.TestCase):

    def test_un_dia_de_diferencia_por_zona_horaria_es_la_misma_pelea(self):
        # BestFightOdds fecha en hora de EE.UU.; los eventos en Abu Dhabi o
        # Australia caen un día antes o después en UFCStats. Medido: 18 de las 36
        # peleas del hueco sin cuota eran este caso.
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "bfo.json"
            cache.write_text(json.dumps({"juan perez": [
                {"rival": "pedro soto", "fecha": "2026-04-11", "cuota_propia": -150.0, "cuota_rival": 130.0}]}))
            with mock.patch.object(BFO, "CACHE", cache):
                self.assertEqual(BFO.cuotas_de("Juan Perez", "Pedro Soto", "2026-04-12"), (-150.0, 130.0))
                self.assertEqual(BFO.cuotas_de("Pedro Soto", "Juan Perez", "2026-04-10"), (130.0, -150.0))
                self.assertIsNone(BFO.cuotas_de("Juan Perez", "Pedro Soto", "2026-04-14"))


class CacheIncremental(unittest.TestCase):

    def test_quien_volvio_a_pelear_se_vuelve_a_bajar(self):
        # El caché se indexa por peleador: una vez guardado, no se volvía a pedir
        # nunca, así que su pelea SIGUIENTE dentro del hueco se quedaba sin cuota.
        gap = pd.DataFrame({"fighter_a": ["Juan Perez", "Ana Diaz"],
                            "fighter_b": ["Pedro Soto", "Eva Ruiz"],
                            "date": pd.to_datetime(["2026-07-20", "2026-07-20"])})
        cache = {"juan perez": [{"rival": "x", "fecha": "2026-04-11", "cuota_propia": 1, "cuota_rival": 1}],
                 "pedro soto": [{"rival": "juan perez", "fecha": "2026-07-20", "cuota_propia": 1, "cuota_rival": 1}],
                 "ana diaz": []}
        pend = BFO._pendientes(gap, cache)
        self.assertIn("Juan Perez", pend)          # ficha vieja: su última pelea no está
        self.assertIn("Eva Ruiz", pend)            # nunca bajado
        self.assertNotIn("Pedro Soto", pend)       # al día
        self.assertNotIn("Ana Diaz", pend)         # BFO no la tiene: no insistir


if __name__ == "__main__":
    unittest.main()
