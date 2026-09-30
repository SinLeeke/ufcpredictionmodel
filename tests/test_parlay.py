"""Pruebas de webui/parlay.py: matemática de la combinada y sugerencia."""
import math
import unittest

from webui import parlay as P


def pata(fid, tier, p, cuota, mercado=None, clase=None, avisos=None):
    mercado = mercado or ("ganador" if tier == "B" else "metodo7")
    clase = clase or ("A" if mercado == "ganador" else "A_DEC")
    return P.Pata(id=f"{fid}:{mercado}:{clase}", fight_id=str(fid), pelea=f"X{fid} vs Y{fid}",
                  mercado=mercado, seleccion=f"sel {fid}", clase=clase, p=p, cuota=cuota,
                  tier=tier, avisos=avisos or [])


class Matematica(unittest.TestCase):

    def test_ev_y_error_tolerable(self):
        patas = [pata(i, "A", 1.05 / 2.0, 2.0) for i in range(13)]
        r = P.evaluar(patas)
        self.assertAlmostEqual(r["ev"], 1.05 ** 13 - 1, places=9)             # +88,6%
        self.assertAlmostEqual(r["error_tolerable"], 1 - 1 / 1.05, places=9)   # 4,76%
        self.assertAlmostEqual((1 - r["error_tolerable"]) ** 13 * (1 + r["ev"]), 1.0, places=9)
        self.assertAlmostEqual(r["umbral_fragil"], 0.04 * math.sqrt(13 / 4), places=9)

    def test_excluyentes_y_similares(self):
        gA = pata(0, "B", .6, 1.8, "ganador", "A")
        gB = pata(0, "B", .4, 2.2, "ganador", "B")
        dA = pata(0, "A", .3, 4.0, "metodo7", "A_DEC")
        fA = pata(0, "C", .3, 3.0, "metodo5", "A_FIN")
        kA = pata(0, "C", .2, 5.0, "metodo7", "A_KO")
        self.assertEqual(P.conflicto(gA, gB), "excluyente")
        self.assertEqual(P.conflicto(gA, dA), "similar")
        self.assertEqual(P.conflicto(fA, kA), "similar")
        self.assertEqual(P.conflicto(fA, dA), "excluyente")
        self.assertIsNone(P.conflicto(gA, pata(1, "B", .6, 1.8)))


class Sugerencia(unittest.TestCase):

    def test_no_sugiere_lo_que_la_propia_ui_marca_como_no(self):
        # BUG: sugerir() usaba `apostable` (EV > 0) y la UI marca "No conviene" a
        # las de ganador con EV entre 0 y 3%. En mkv.csv sugería 4 patas y las 4
        # decían "No conviene"; con 12 peleas armaba 12 patas "flojas".
        patas = [pata(i, "B", 0.52 + 0.001 * i, 1.95) for i in range(12)]
        self.assertTrue(all(0 < p.ev < 0.036 for p in patas))
        sug = P.sugerir(patas)
        por_id = {p.id: p for p in patas}
        self.assertFalse([i for i in sug if por_id[i].veredicto() == "no"])

    def test_nunca_una_combinada_que_su_evaluador_califica_de_floja(self):
        # Solo apuestas al ganador, aunque todas "se puedan": el evaluador dice
        # "flojo". Sugerirla sería contradecirse.
        patas = [pata(i, "B", 0.56, 1.95) for i in range(6)]      # EV +9,2%: "quizas"
        self.assertEqual({p.veredicto() for p in patas}, {"quizas"})
        self.assertEqual(P.sugerir(patas), [])

    def test_combinada_corta_y_con_respaldo(self):
        patas = ([pata(i, "A", 0.36, 3.0) for i in range(5)]             # decisiones, EV +8%
                 + [pata(10 + i, "B", 0.56, 1.95) for i in range(4)])    # ganador, EV +9%
        sug = P.sugerir(patas)
        elegidas = [p for p in patas if p.id in sug]
        self.assertTrue(2 <= len(elegidas) <= P.MAX_SUGERIDAS)
        self.assertTrue(all(p.veredicto() in ("si", "quizas") for p in elegidas))
        self.assertNotIn(P.evaluar(elegidas)["nivel"], ("flojo", "malo"))
        self.assertEqual(len({p.fight_id for p in elegidas}), len(elegidas))


if __name__ == "__main__":
    unittest.main()
