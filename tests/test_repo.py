"""Pruebas de lo que viene en el repo: que funcione en un clon limpio."""
import subprocess
import unittest

import pandas as pd

import config as C
from src import card, value as V

EJEMPLO = C.ROOT / "cards" / "ejemplo_con_cuotas.csv"


def _versionados() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=C.ROOT, capture_output=True, text=True, check=True)
    return set(out.stdout.split())


class Ejemplo(unittest.TestCase):

    def test_el_ejemplo_no_trae_cuotas_que_el_sistema_rechaza(self):
        # BUG: sus cuotas de método sumaban 0,92-1,11. 8 de 12 peleas salían como
        # "cuotas imposibles" y las otras 4 como "sospechosas": el ejemplo del
        # formato enseñaba exactamente lo que el MANUAL dice que no hay que hacer.
        d = pd.read_csv(EJEMPLO)
        cols = [c for c in card.COL_METODO if c in d.columns]
        for i, fila in d.iterrows():
            if not cols or fila[cols].isna().all():
                continue
            _, suma = V.mercado_metodo(fila[card.COL_METODO].tolist())
            self.assertGreaterEqual(suma, V.SOBRERREDONDEO_SOSPECHOSO, f"fila {i}: suma {suma:.3f}")


if __name__ == "__main__":
    unittest.main()
