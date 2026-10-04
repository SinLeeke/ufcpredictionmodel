"""Conversiones de cuota, validación de la Cotización y consenso (src/cuotas)."""
import unittest

from src.cuotas import consenso as K
from src.cuotas.conversion import (CuotaInvalida, americana_a_decimal, cotizacion,
                                   decimal_a_americana, prob_a_americana)


class Conversiones(unittest.TestCase):

    def test_probabilidad_a_americana_del_contrato(self):
        self.assertEqual(prob_a_americana(0.65), -186)
        self.assertEqual(prob_a_americana(0.35), 186)
        self.assertEqual(prob_a_americana(0.5), -100)
        self.assertEqual(prob_a_americana(0.6), -150)
        self.assertEqual(prob_a_americana(0.25), 300)

    def test_probabilidad_imposible(self):
        for p in (0, 1, -0.1, 1.2, float("nan")):
            with self.assertRaises(CuotaInvalida):
                prob_a_americana(p)

    def test_decimal_y_americana_ida_y_vuelta(self):
        self.assertEqual(decimal_a_americana(1.667), -150)
        self.assertEqual(decimal_a_americana(2.25), 125)
        self.assertEqual(decimal_a_americana(2.0), 100)
        for am in (-1000, -186, -110, 100, 125, 186, 750):
            self.assertEqual(decimal_a_americana(americana_a_decimal(am)), am)
        self.assertAlmostEqual(americana_a_decimal(-150), 1.6667, places=4)
        self.assertAlmostEqual(americana_a_decimal(125), 2.25)

    def test_cuotas_imposibles(self):
        for d in (1.0, 0.5, float("inf")):
            with self.assertRaises(CuotaInvalida):
                decimal_a_americana(d)
        with self.assertRaises(CuotaInvalida):
            americana_a_decimal(50)          # entre −100 y +100 no existe


class Cotizacion(unittest.TestCase):

    def test_casa_del_contrato(self):
        c = cotizacion("odds_api", "casa", "DraftKings", "alex pereira|magomed ankalaev",
                       "2026-10-03T22:15:00+00:00", a_americana=-150, b_americana=125)
        self.assertEqual(c["a"], {"americana": -150, "decimal": 1.667, "prob_implicita": 0.6})
        self.assertEqual(c["b"], {"americana": 125, "decimal": 2.25, "prob_implicita": 0.4444})
        self.assertAlmostEqual(c["margen"], 0.0444, places=4)
        self.assertAlmostEqual(c["prob_sin_margen"]["a"], 0.5745, places=3)
        self.assertGreater(c["a"]["prob_implicita"] + c["b"]["prob_implicita"], 1)

    def test_casa_que_suma_1_o_menos_se_rechaza(self):
        for a, b in ((150, 150), (100, 100), (200, -150)):
            with self.assertRaises(CuotaInvalida):
                cotizacion("x", "casa", "X", "a|b", "2026-10-03T00:00:00+00:00", a_americana=a, b_americana=b)

    def test_mercado_de_prediccion(self):
        c = cotizacion("polymarket", "mercado_prediccion", "Polymarket", "a|b",
                       "2026-10-03T00:00:00+00:00", a_prob=0.65, b_prob=0.35)
        self.assertEqual((c["a"]["americana"], c["b"]["americana"]), (-186, 186))
        self.assertEqual(c["a"]["prob_implicita"], 0.65)
        self.assertEqual(c["margen"], 0.0)
        with self.assertRaises(CuotaInvalida):     # tokens cruzados: no suman ≈ 1
            cotizacion("polymarket", "mercado_prediccion", "Polymarket", "a|b",
                       "2026-10-03T00:00:00+00:00", a_prob=0.65, b_prob=0.65)


def _cot(casa, a, b, ts="2026-10-03T00:00:00+00:00", fuente="bfo", tipo="casa"):
    if tipo == "casa":
        return cotizacion(fuente, tipo, casa, "a|b", ts, a_americana=a, b_americana=b)
    return cotizacion(fuente, tipo, casa, "a|b", ts, a_prob=a, b_prob=b)


class Consenso(unittest.TestCase):

    def test_promedio_sin_margen(self):
        c = K.consenso([_cot("A", -150, 125), _cot("B", -200, 170)])
        pa = (0.6 / (0.6 + 1 / 2.25) + (2 / 3) / (2 / 3 + 1 / 2.7)) / 2
        self.assertAlmostEqual(c["a"]["prob"], round(pa, 4), places=3)
        self.assertEqual((c["a"]["etiqueta"], c["b"]["etiqueta"], c["pareja"]), ("Favorito", "Underdog", False))
        self.assertEqual(c["n_cotizaciones"], 2)

    def test_pareja_entre_menos_115_y_mas_115(self):
        c = K.consenso([_cot("A", -110, -110)])
        self.assertEqual((c["a"]["etiqueta"], c["b"]["etiqueta"], c["pareja"]), ("Pareja", "Pareja", True))
        self.assertEqual(K.etiquetas(-115, 115, 0.535, 0.465), ("Pareja", "Pareja", True))
        self.assertEqual(K.etiquetas(-116, 116, 0.537, 0.463), ("Favorito", "Underdog", False))
        self.assertEqual(K.etiquetas(130, -130, 0.43, 0.57), ("Underdog", "Favorito", False))

    def test_una_por_casa_la_mas_reciente(self):
        vieja = _cot("DraftKings", -300, 240, ts="2026-10-01T00:00:00+00:00")
        nueva = _cot("draftkings", -150, 125, ts="2026-10-02T00:00:00+00:00", fuente="odds_api")
        c = K.consenso([vieja, nueva])
        self.assertEqual(c["n_cotizaciones"], 1)
        self.assertAlmostEqual(c["a"]["prob"], nueva["prob_sin_margen"]["a"], places=3)

    def test_sin_cotizaciones_es_null(self):
        self.assertIsNone(K.consenso([]))
        self.assertIsNone(K.mejor([]))

    def test_mejor_cuota_solo_entre_casas(self):
        cots = [_cot("A", -150, 125), _cot("B", -130, 110),
                _cot("Polymarket", 0.4, 0.6, fuente="polymarket", tipo="mercado_prediccion")]
        m = K.mejor(cots)
        self.assertEqual((m["a"]["casa"], m["a"]["americana"]), ("B", -130))
        self.assertEqual((m["b"]["casa"], m["b"]["americana"]), ("A", 125))
        self.assertIsNone(K.mejor(cots[2:]))

    def test_invertir(self):
        p = {"pelea_id": "a|b", "a": "A", "b": "B", "a_id": "1", "b_id": None,
             "cotizaciones": [_cot("A", -150, 125)]}
        p["consenso"], p["mejor"] = K.consenso(p["cotizaciones"]), K.mejor(p["cotizaciones"])
        q = K.invertir(p)
        self.assertEqual((q["a"], q["a_id"], q["b_id"]), ("B", None, "1"))
        self.assertEqual(q["cotizaciones"][0]["a"]["americana"], 125)
        self.assertEqual(q["consenso"]["a"]["etiqueta"], "Underdog")
        self.assertEqual(q["mejor"]["a"]["americana"], 125)
        self.assertEqual(p["cotizaciones"][0]["a"]["americana"], -150)   # el original no cambia


if __name__ == "__main__":
    unittest.main()
