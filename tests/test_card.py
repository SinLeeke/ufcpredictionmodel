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
