"""Pruebas de src/card.py: lectura del CSV de cartelera."""
import unittest

from tests.util import card_aislado, predecir


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


if __name__ == "__main__":
    unittest.main()
