"""Exactitud, originales intactos y checkpoints SQLite tras una interrupción."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd
from pandas.testing import assert_frame_equal

import config as C
from src import migrate_sqlite as M, storage as DB


class SQLite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.object(C, "ROOT", self.root)
        self.patch.start()
        self.csv = self.root / "data/processed/features.csv"
        self.csv.parent.mkdir(parents=True)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_normalizacion_csv_dtypes_y_orden_exactos(self):
        frame = pd.DataFrame({"fighter": ["Mike Davis", "MIKE DAVIS", "Mike Davis"],
                              "float": [1.2345678901234567, float("nan"), -0.12345678901234567],
                              "flag": [True, False, True], "number": [3, 1, 2]})
        serialized = frame.to_csv(index=False).encode("utf-8")
        reference = pd.read_csv(io.BytesIO(serialized))
        DB.to_csv(frame, self.csv, index=False)
        assert_frame_equal(reference, DB.read_csv(self.csv), check_exact=True)
        assert_frame_equal(reference[["float"]], DB.read_csv(self.csv, usecols=["float"]), check_exact=True)
        self.assertEqual(DB.read_bytes(self.csv), serialized)
        with DB.connect() as con:
            count = con.execute(f'SELECT COUNT(*) FROM "{DB._table_name(self.csv)}" WHERE fighter=?', ("Mike Davis",)).fetchone()[0]
        self.assertEqual(count, 2)  # BINARY: nada de homónimos ni NOCASE.

    def test_nunca_lee_el_csv_original_ni_lo_sobrescribe(self):
        self.csv.write_bytes(b"x\r\n7\r\n")
        DB.write_csv_bytes(self.csv, self.csv.read_bytes())
        before = self.csv.read_bytes()
        DB.to_csv(pd.DataFrame({"x": [11]}), self.csv, index=False)
        self.assertEqual(self.csv.read_bytes(), before)
        self.csv.rename(self.csv.with_suffix(".original"))
        self.assertEqual(DB.read_csv(self.csv).x.tolist(), [11])

    def test_actualiza_solo_filas_distintas_y_borra_el_sobrante(self):
        DB.to_csv(pd.DataFrame({"x": [10, 20, 30]}), self.csv, index=False)
        with DB.connect() as con:
            con.execute("CREATE TABLE cambios(n INTEGER)")
            con.execute(f'CREATE TRIGGER cuenta AFTER UPDATE ON "{DB._table_name(self.csv)}" BEGIN INSERT INTO cambios VALUES(1); END')
        DB.to_csv(pd.DataFrame({"x": [10, 21]}), self.csv, index=False)
        with DB.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM cambios").fetchone()[0], 1)
        self.assertEqual(DB.read_csv(self.csv).x.tolist(), [10, 21])

    def test_checkpoint_json_sobrevive_sin_guardado_final(self):
        path = self.root / "data/raw/ufcstats_events.json"
        DB.put_json_entry(path, "evento B", [{"name": "Uno"}])
        DB.put_json_entry(path, "evento A", [])
        DB.put_json_entry(path, "evento B", [{"name": "Dos"}])
        # Conexiones nuevas: simula reanudar tras perder todo el estado Python.
        with DB.connect() as con:
            self.assertEqual(con.execute("SELECT kind FROM _resources").fetchone()[0], "json_pending")
            self.assertEqual(con.execute("SELECT content FROM _resources").fetchone()[0], b"{}")
        value = json.loads(DB.read_text(path))
        self.assertEqual(list(value), ["evento B", "evento A"])
        self.assertEqual(value["evento B"][0]["name"], "Dos")
        self.assertEqual(DB.signature(path), hashlib.sha256(DB.read_bytes(path)).hexdigest())

    def test_migracion_retoma_tras_transaccion_sin_manifiesto(self):
        self.csv.write_bytes(b"x\r\n7\r\n")
        source_hash = M.digest(self.csv)
        # La primera corrida confirmó SQLite y se interrumpió antes del manifiesto.
        DB.write_csv_bytes(self.csv, self.csv.read_bytes(), self.csv.stat().st_mtime_ns)
        with mock.patch("builtins.print"):
            M.migrate()
            M.migrate()
        manifest = json.loads((self.root / "data/originales/manifiesto.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1)
        self.assertEqual(M.digest(self.csv), source_hash)
        DB.to_csv(pd.DataFrame({"x": [99]}), self.csv, index=False)
        with mock.patch("builtins.print"):
            M.migrate()
        self.assertEqual(DB.read_csv(self.csv).x.tolist(), [99])
        self.assertEqual(M.digest(self.csv), source_hash)

    def test_ui_y_migracion_excluyentes_y_liberacion_al_fallar(self):
        with DB.lease("ui"):
            with self.assertRaises(RuntimeError):
                M.migrate()
        with self.assertRaisesRegex(ValueError, "interrupcion"):
            with DB.lease("migration"):
                with self.assertRaises(RuntimeError):
                    with DB.lease("ui"):
                        pass
                raise ValueError("interrupcion")
        with DB.lease("ui"):
            pass

    def test_falta_en_sqlite_aunque_haya_original(self):
        self.csv.write_bytes(b"x\n7\n")
        self.assertFalse(DB.exists(self.csv))
        with self.assertRaises(FileNotFoundError):
            DB.read_csv(self.csv)

    def test_cache_de_tablas_reutiliza_sin_compartir_mutaciones(self):
        DB.to_csv(pd.DataFrame({"x": [7]}), self.csv, index=False)
        with mock.patch.object(pd, "read_sql_query", wraps=pd.read_sql_query) as sql:
            first = DB.read_csv(self.csv)
            first.loc[0, "x"] = 999
            self.assertEqual(DB.read_csv(self.csv).x.tolist(), [7])
            self.assertEqual(sql.call_count, 1)
            DB.to_csv(pd.DataFrame({"x": [11]}), self.csv, index=False)
            self.assertEqual(DB.read_csv(self.csv).x.tolist(), [11])
            self.assertEqual(sql.call_count, 2)

    def test_foto_persistida_se_reutiliza_con_indice_sqlite_sin_red(self):
        from webui import fotos as F
        folder = self.root / "data/raw/fotos"
        folder.mkdir(parents=True)
        response = mock.Mock(status_code=200, content=b"retrato PNG",
                             headers={"content-type": "image/png"})
        with mock.patch.object(F, "CARPETA", folder), \
                mock.patch.object(F, "url_espn", return_value="https://a.espncdn.com/i/headshots/mma/players/full/123.png"), \
                mock.patch.object(F.requests, "get", return_value=response) as network:
            first = F.foto("Ilia Topuria")
            self.assertEqual(network.call_count, 1)
            self.assertEqual(first.read_bytes(), b"retrato PNG")
        # Pierde la caché Python y simula abrir otra sesión completamente offline.
        DB._MEMO.clear()
        with mock.patch.object(F, "CARPETA", folder), \
                mock.patch.object(F, "_fallo_red", {}), \
                mock.patch.object(F.requests, "get", side_effect=AssertionError("No debe consultar la red")) as network:
            self.assertEqual(F.foto("Ilia Topuria"), first)
            self.assertTrue(DB.exists(folder / "indice.json"))
            self.assertFalse((folder / "indice.json").exists())
            network.assert_not_called()

    def test_mantenimiento_vacia_sqlite_y_conserva_el_json_original(self):
        from webui.jobs import RECETAS
        raw = self.root / "data/raw"
        raw.mkdir(parents=True)
        path = raw / "ufcstats_cache.json"
        path.write_bytes(b'{"peleador":{}}')
        before = path.read_bytes()
        DB.write_text(path, before.decode("utf-8"))
        with mock.patch.object(C, "DATA_RAW", raw), mock.patch("builtins.print"):
            exec(RECETAS["limpiar_cache"].pasos[0][2], {})
        self.assertFalse(DB.exists(path))
        self.assertEqual(path.read_bytes(), before)

    def test_scraper_confirma_cada_pagina_antes_de_una_interrupcion(self):
        from src import ufcstats_events as U
        cache = self.root / "data/raw/ufcstats_events.json"
        fight = {"date": "2026-01-01", "winner": "Uno", "method": "Decision", "method_detail": "U-DEC"}
        event = {"url": "https://ufcstats.com/event-details/test", "name": "Evento", "date": "2026-01-01"}

        def fetch(urls, callback, **kwargs):
            callback(urls[0], object())
            raise RuntimeError("interrumpido")

        with mock.patch.object(U, "EVENTS_CACHE", cache), \
                mock.patch.object(U, "FIGHTS_CSV", self.csv), \
                mock.patch.object(U, "list_events", return_value=[event]), \
                mock.patch.object(U, "parse_event_soup", return_value=[fight]), \
                mock.patch("src.fast_fetch.fetch_many", side_effect=fetch), \
                mock.patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "interrumpido"):
                U.build()
        self.assertEqual(DB.read_json(cache)[event["url"]], [fight])
        # Retoma con conexión nueva y no pide la página ya confirmada.
        with mock.patch.object(U, "EVENTS_CACHE", cache), \
                mock.patch.object(U, "FIGHTS_CSV", self.csv), \
                mock.patch.object(U, "list_events", return_value=[event]), \
                mock.patch("src.fast_fetch.fetch_many") as download, \
                mock.patch("builtins.print"):
            U.build()
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
