"""Pruebas de src/simulate.py."""
import unittest

from scipy.stats import beta

from src.simulate import monte_carlo

METODO = {"KO/TKO": 0.31, "Submission": 0.17, "Decision": 0.52}


class MonteCarlo(unittest.TestCase):

    def test_la_probabilidad_puntual_es_la_exacta(self):
        # BUG: p_a era la FRECUENCIA de victorias en los sorteos, que solo recupera
        # la p con ruido (medido: hasta 0,9 pts). Ese ruido llegaba al EV de las
        # patas del parlay, que no coincidía con el de "Qué apostar".
        for p in (0.52, 0.6123, 0.80):
            with self.subTest(p=p):
                sim = monte_carlo(p, METODO, "A", "B")
                self.assertAlmostEqual(sim.p_a, round(p, 4), places=6)
                self.assertAlmostEqual(sim.p_a + sim.p_b, 1.0, places=6)

    def test_metodo_exacto_y_finalizacion(self):
        sim = monte_carlo(0.6, METODO, "A", "B")
        self.assertEqual(sim.method_dist, METODO)
        self.assertAlmostEqual(sim.p_finish, 0.48, places=6)

    def test_intervalo_de_la_beta(self):
        sim = monte_carlo(0.65, METODO, "A", "B", concentration=40.0)
        lo, hi = beta.ppf([0.025, 0.975], 0.65 * 40, 0.35 * 40)
        self.assertAlmostEqual(sim.ci_a[0], lo, delta=0.01)
        self.assertAlmostEqual(sim.ci_a[1], hi, delta=0.01)

    def test_ganador(self):
        self.assertEqual(monte_carlo(0.49, METODO, "A", "B").winner, "B")
        self.assertEqual(monte_carlo(0.51, METODO, "A", "B").winner, "A")


if __name__ == "__main__":
    unittest.main()
