"""Pruebas de src/scraper.py: refrescar el dataset de Kaggle sin perder la copia local."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config as C
from src import scraper


class RefrescoDeKaggle(unittest.TestCase):

    def _correr(self, raw_existe: bool, descarga_ok: bool):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            csv = raw / "kaggle_ufc.csv"
            if raw_existe:
                csv.write_text("copia local", encoding="utf-8")

            def descarga():
                if not descarga_ok:
                    raise RuntimeError("sin credenciales")
                csv.write_text("copia nueva", encoding="utf-8")

            construidas = []
            with mock.patch.object(C, "DATA_RAW", raw), \
                    mock.patch.object(scraper, "load_from_kaggle", descarga), \
                    mock.patch("src.kaggle_ingest.build_all", lambda: construidas.append(1) or (None, "ok")), \
                    contextlib.redirect_stdout(io.StringIO()):
                scraper.build_fighters_table(refrescar=True)
            return csv.read_text(encoding="utf-8"), construidas

    def test_si_la_descarga_falla_se_conserva_la_copia_local(self):
        # BUG: actualizar_bd.bat BORRABA kaggle_ufc.csv antes de intentar bajarlo.
        # Sin kaggle.json (o sin internet) la descarga falla y la base quedaba sin
        # su única fuente de cuotas históricas.
        contenido, construidas = self._correr(raw_existe=True, descarga_ok=False)
        self.assertEqual(contenido, "copia local")
        self.assertEqual(construidas, [1])

    def test_si_la_descarga_funciona_se_usa_la_nueva(self):
        contenido, construidas = self._correr(raw_existe=True, descarga_ok=True)
        self.assertEqual(contenido, "copia nueva")
        self.assertEqual(construidas, [1])

    def test_sin_copia_local_y_sin_descarga_avisa_en_vez_de_seguir(self):
        with self.assertRaises(RuntimeError):
            self._correr(raw_existe=False, descarga_ok=False)


class RecetaMensual(unittest.TestCase):

    def test_la_actualizacion_de_la_ui_refresca_kaggle_y_las_stats_por_pelea(self):
        # La receta de la UI nunca bajaba Kaggle nuevo (el .bat sí, borrando
        # antes), y ninguna de las dos actualizaba las stats por pelea, de donde
        # sale el control y la defensa real de cada peleador al predecir.
        from webui.jobs import RECETAS
        pasos = [" ".join(p[1:]) for p in RECETAS["actualizar_bd"].pasos]
        self.assertIn("-m src.scraper --refrescar-kaggle", pasos)
        self.assertIn("-m src.ufcstats_fightstats", pasos)


if __name__ == "__main__":
    unittest.main()
