"""El fondo dorado del listado y del perfil sale solo del puesto C con identidad exacta."""
import unittest
from unittest import mock

from webui import catalogo as K


def _division(nombre, filas, p4p=False):
    return {"nombre": nombre, "p4p": p4p, "peleadores": filas}


class CampeonesPorId(unittest.TestCase):
    def setUp(self):
        K._campeones_cache = (None, {})

    def test_solo_el_puesto_c_con_id_y_nunca_el_libra_por_libra(self):
        oro = {"division": "Peso welter", "clave": "Welterweight", "interino": False}
        datos = {"divisiones": [
            _division("Men's Pound-for-Pound", [{"puesto": 1, "id": "p4p1", "campeon": oro}], p4p=True),
            _division("Peso welter", [{"puesto": 0, "id": "aaa", "campeon": oro},
                                      {"puesto": 1, "id": "bbb", "campeon": None}]),
            # Un campeón que no se pudo identificar (homónimo sin ficha) no marca a nadie.
            _division("Peso medio", [{"puesto": 0, "id": None, "campeon": {"clave": "Middleweight"}}]),
        ]}
        with mock.patch.object(K, "rankings", return_value=datos):
            mapa = K.campeones_por_id()
        self.assertEqual(mapa, {"aaa": oro})

    def test_se_reutiliza_mientras_no_cambie_la_captura(self):
        datos = {"divisiones": []}
        with mock.patch.object(K, "rankings", return_value=datos) as r:
            K.campeones_por_id()
            K.campeones_por_id()
        self.assertEqual(r.call_count, 1)


if __name__ == "__main__":
    unittest.main()
