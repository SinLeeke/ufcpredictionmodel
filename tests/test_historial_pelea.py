"""/api/peleadores/{id}/pelea: una pelea del historial como se veía ESE día.

Lo que no se puede romper es lo mismo que la repetición: nada posterior a la
pelea entra a sus estadísticas, las esquinas no dicen quién ganó y el
resultado viaja aparte. Base sintética en un UFC_DB temporal, sin red.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from fastapi.testclient import TestClient

from src import corte as CT, storage as DB
from webui import catalogo as K

NOMBRES = ["Ana Arco", "Bia Bravo", "Caro Cruz"]
ID = {n: f"{i:016x}" for i, n in enumerate(NOMBRES, 1)}
# Como en UFCStats: el ganador SIEMPRE en fighter_a.
PELEAS = [
    ("f1", "2024-01-20", "UFC 300", "Ana Arco", "Caro Cruz", "Ana Arco", "KO/TKO", "KO/TKO", 1, "2:00"),
    ("f2", "2024-06-15", "UFC 305: Arco vs. Bravo", "Bia Bravo", "Ana Arco", "Bia Bravo", "Decision", "U-DEC", 3, "5:00"),
    # Posteriores a la pelea pedida: no pueden aparecer en sus estadísticas.
    ("f3", "2025-02-01", "UFC 315", "Ana Arco", "Caro Cruz", "Ana Arco", "Submission", "SUB", 2, "3:10"),
    ("f4", "2025-03-01", "UFC 316", "Bia Bravo", "Caro Cruz", "Bia Bravo", "KO/TKO", "KO/TKO", 1, "0:40"),
]


def _stats(url, fecha, peleador, gano, metodo, golpes):
    return {"fight_url": url, "date": fecha, "fighter": peleador, "won": int(gano), "method": metodo,
            "sig_landed": golpes, "sig_att": golpes * 2, "td_landed": 1, "td_att": 3, "sub_att": 0,
            "ctrl_sec": 60, "kd": 0, "head_landed": golpes // 2, "body_landed": golpes // 4,
            "leg_landed": golpes // 4, "distance_landed": golpes, "clinch_landed": 0, "ground_landed": 0}


class PeleaDelHistorial(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for parche in (mock.patch.dict(os.environ, {"UFC_DB": str(Path(tmp.name) / "historial.db")}),
                       mock.patch("requests.get", side_effect=AssertionError("el detalle no consulta la red")),
                       mock.patch("src.card._resolver_titulos_oficiales",
                                  lambda filas, fecha_evento=None: [{"es_titulo": None, "titulo_fuente": ""} for _ in filas]),
                       mock.patch("src.sherdog.completar", lambda d, hasta=None: d),
                       mock.patch.object(CT, "_KAGGLE", {}), mock.patch.object(CT, "_FIRMA", None),
                       mock.patch.object(CT, "_ELO_POR_FECHA", {})):
            parche.start()
            self.addCleanup(parche.stop)
        DB.to_csv(pd.DataFrame([{"fighter_url": f"http://ufcstats.com/fighter-details/{ID[n]}", "name": n,
                                 "height_cm": 170.0, "reach_cm": 175.0, "stance": "Orthodox", "dob": "1995-01-01"}
                                for n in NOMBRES]), K.BIO, index=False)
        DB.to_csv(pd.DataFrame([{"fight_url": u, "date": d, "event": e, "fighter_a": a, "fighter_b": b, "winner": w,
                                 "method": m, "method_detail": md, "round": r, "time": t, "weight_class": "Flyweight"}
                                for u, d, e, a, b, w, m, md, r, t in PELEAS]), K.FIGHTS, index=False)
        filas = []
        for u, d, _, a, b, w, m, *_ in PELEAS:
            filas += [_stats(u, d, a, w == a, m, 40), _stats(u, d, b, w == b, m, 30)]
        DB.to_csv(pd.DataFrame(filas), K.STATS, index=False)
        # Si algo escribiera en outputs/, quedaría aquí y la prueba lo vería.
        self.salidas = Path(tmp.name) / "outputs"
        parche = mock.patch.object(__import__("config"), "OUTPUTS", self.salidas)
        parche.start()
        self.addCleanup(parche.stop)
        self.client = TestClient(__import__("webui.server", fromlist=["app"]).app)

    def pedir(self, nombre="Ana Arco", fecha="2024-06-15", rival="Bia Bravo"):
        return self.client.get(f"/api/peleadores/{ID[nombre]}/pelea", params={"fecha": fecha, "rival": rival})

    def test_las_estadisticas_no_ven_nada_desde_el_dia_de_la_pelea(self):
        r = self.pedir()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        p = d["pelea"]
        # Orden alfabético sin Kaggle: UFCStats traía a la ganadora primero.
        self.assertEqual((p["a"], p["b"]), ("Ana Arco", "Bia Bravo"))
        ana, bia = p["info_a"], p["info_b"]
        # Ana: solo la victoria por KO de enero; la sumisión de 2025 no existe aún.
        self.assertEqual((ana["wins"], ana["losses"]), (1, 0))
        self.assertEqual(p["metodo_hist_a"], {"KO/TKO": 1.0, "Submission": 0.0, "Decision": 0.0})
        self.assertEqual([x.get("rival") for x in ana["ultimas_peleas"]], ["Caro Cruz"])
        # Bia no tenía peleas antes: ni la de ese día ni el KO de 2025.
        self.assertEqual((bia["wins"], bia["losses"]), (0, 0))
        self.assertIsNone(p["metodo_hist_b"])
        self.assertEqual(bia["ultimas_peleas"], [])
        self.assertEqual(d["corte"]["fecha"], "2024-06-15")
        self.assertEqual(d["lado_perfil"], "a")
        self.assertFalse(self.salidas.exists(), "el detalle no deja tablas en outputs/")

    def test_el_resultado_viaja_aparte_y_sin_modelo_no_hay_probabilidades_inventadas(self):
        d = self.pedir().json()
        self.assertNotIn("resultado", d["pelea"])
        self.assertEqual((d["resultado"]["ganador"], d["resultado"]["lado"]), ("Bia Bravo", "b"))
        # Sin un modelo ciego a esa fecha no se entrena en el clic: la
        # heurística de predict_card no se muestra como si fuera el modelo.
        for campo in ("p_a", "p_b", "ci_a", "metodo", "probabilidades_metodo", "ganador", "confianza"):
            self.assertIsNone(d["pelea"][campo], campo)
        self.assertIsNone(d["resultado"]["acierto"])
        self.assertIsNone(d["corte"]["modelo"])
        self.assertIn("modelo", d["corte"]["motivo"])

    def test_con_modelo_guardado_lo_usa_sin_entrenar(self):
        modelos = {"ganador": object(), "metodo": None, "metodo6": None, "origen": "reentrenado",
                   "entrenado_hasta": "2024-06-14", "peleas": 2100}
        with mock.patch.object(CT, "modelos_a_fecha", return_value=modelos) as m, \
                mock.patch("src.card.probabilidad_ganador", return_value=[0.61]):
            d = self.pedir().json()
        self.assertEqual(m.call_args.kwargs.get("entrenar"), False)
        self.assertAlmostEqual(d["pelea"]["p_a"] + d["pelea"]["p_b"], 1.0, places=6)
        self.assertEqual(d["corte"]["modelo"], "reentrenado")
        self.assertIn(d["resultado"]["acierto"], (True, False))

    def test_desde_el_otro_lado_la_esquina_del_perfil_es_b(self):
        d = self.pedir("Bia Bravo", rival="Ana Arco").json()
        self.assertEqual((d["pelea"]["a"], d["lado_perfil"]), ("Ana Arco", "b"))

    def test_solo_peleas_del_historial_de_esa_ficha(self):
        self.assertEqual(self.pedir(rival="Caro Cruz").status_code, 404)      # esa fecha fue con Bia
        self.assertEqual(self.pedir(fecha="2024-06-16").status_code, 404)
        self.assertEqual(self.pedir(fecha="15/06/2024").status_code, 400)
        self.assertEqual(self.client.get("/api/peleadores/ffffffffffffffff/pelea",
                                         params={"fecha": "2024-06-15", "rival": "Bia Bravo"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
