"""Corre al final de la suite (orden alfabético): data/ufc.db quedó como estaba.

Una prueba puede leer la base real a propósito (RankingReal, si existe), pero
ninguna puede crearla ni escribir en ella. tests/__init__.py anota su huella
al empezar la corrida.
"""
import unittest

import tests


class BaseReal(unittest.TestCase):
    def test_ninguna_prueba_creo_ni_modifico_la_base_real(self):
        self.assertEqual(tests.huella_base_real(), tests.HUELLA_INICIAL,
                         f"{tests.BASE_REAL} cambió durante las pruebas")


if __name__ == "__main__":
    unittest.main()
