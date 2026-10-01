"""Pruebas del modo demo de la UI (python -m webui.server --demo)."""
import unittest
from unittest import mock

from webui import engine as E, parlay as P

DEMO = E.ROOT / "webui" / "demo"


class ModoDemo(unittest.TestCase):

    def test_cada_cartelera_de_ejemplo_carga_y_la_combinada_funciona(self):
        # El modo demo existe para trabajar la interfaz SIN data/ ni models/ (que
        # no se versionan): en una sesión en la nube o en un clon limpio.
        archivos = sorted(DEMO.glob("*.json"))
        self.assertGreaterEqual(len(archivos), 1)
        for ruta in archivos:
            with self.subTest(demo=ruta.name):
                estado = E.Estado()
                with mock.patch.object(E, "ESTADO", estado):
                    E.cargar_demo(ruta)
                    self.assertTrue(estado.datos["peleas"])
                    self.assertEqual(len(estado.patas), len(estado.datos["patas"]))
                    self.assertEqual(E.refrescar(), "Modo demo: no hay cuotas que refrescar.")
                ids = [p.id for p in estado.patas]
                distintas = [i for i in ids if not any(j.split(":")[0] == i.split(":")[0]
                                                        for j in ids[:ids.index(i)])][:2]
                r = P.evaluar([p for p in estado.patas if p.id in distintas])
                self.assertTrue(r["ok"])

    def test_elegir_una_demo_por_nombre(self):
        self.assertEqual(E.ruta_demo("medic").name, "betano_medic_rodriguez.json")
        self.assertIsNone(E.ruta_demo("no-existe"))


if __name__ == "__main__":
    unittest.main()
