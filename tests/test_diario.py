"""storage.Diario: lo que escribe una carga cancelada vuelve exactamente a como estaba."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import pandas as pd

import config as C
from src import storage as DB


class Diario(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for parche in (mock.patch.object(C, "ROOT", self.root), mock.patch.dict(os.environ, {}, clear=False)):
            parche.start()
            self.addCleanup(parche.stop)
        os.environ.pop("UFC_DB", None)
        self.csv = self.root / "data/processed/tabla.csv"
        self.json = self.root / "data/raw/cache.json"
        self.archivo = self.root / "cards/betano_2026-10-10_a_vs_b.csv"
        self.archivo.parent.mkdir(parents=True)

    def test_la_base_sigue_en_la_carpeta_temporal(self):
        self.assertTrue(str(DB.db_path()).startswith(str(self.root)))

    def test_revierte_lo_creado_y_lo_modificado_en_la_base_y_en_disco(self):
        DB.to_csv(pd.DataFrame({"a": [1, 2]}), self.csv, index=False)
        DB.write_text(self.json, json.dumps({"x": 1}))
        DB.put_json_entry(self.json, "y", 2)                 # queda pendiente de materializar
        antes_csv, antes_json = DB.read_bytes(self.csv), DB.read_json(self.json)
        with DB.Diario() as d:
            DB.to_csv(pd.DataFrame({"a": [9]}), self.csv, index=False)
            DB.put_json_entry(self.json, "z", 3)
            DB.write_text(self.json, json.dumps({"otra": True}))
            DB.to_csv(pd.DataFrame({"f": [1]}), self.archivo, index=False)
            DB.write_bytes(self.root / "data/raw/nueva.json", b"{}")
        self.assertEqual(d.revertir(), [])
        self.assertEqual(DB.read_bytes(self.csv), antes_csv)
        self.assertEqual(DB.read_json(self.json), antes_json)
        self.assertFalse(self.archivo.exists())
        self.assertFalse(DB.exists(self.root / "data/raw/nueva.json"))

    def test_sin_diario_y_en_otro_hilo_no_se_anota_nada(self):
        with DB.Diario() as d:
            hilo = threading.Thread(target=lambda: DB.write_text(self.json, "{}"))
            hilo.start(); hilo.join()
        self.assertEqual(d.previos, {})
        DB.write_text(self.json, json.dumps({"a": 1}))       # fuera del diario: no cuenta
        self.assertEqual(d.revertir(), [])
        self.assertEqual(DB.read_json(self.json), {"a": 1})

    def test_lo_que_otro_hilo_escribio_despues_no_se_pisa(self):
        DB.write_text(self.json, json.dumps({"v": 1}))
        with DB.Diario() as d:
            DB.write_text(self.json, json.dumps({"v": 2}))
        hilo = threading.Thread(target=lambda: DB.write_text(self.json, json.dumps({"v": 3})))
        hilo.start(); hilo.join()
        self.assertEqual(d.revertir(), [str(self.json)])
        self.assertEqual(DB.read_json(self.json), {"v": 3})

    def test_archivos_abiertos_para_escribir_tambien_vuelven(self):
        self.archivo.write_text("original")
        with DB.Diario() as d:
            with DB.open_file(self.archivo, "w") as f:
                f.write("pisado")
        d.revertir()
        self.assertEqual(self.archivo.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
