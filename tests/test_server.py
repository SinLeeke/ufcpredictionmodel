"""Pruebas de webui/server.py: rutas de archivos y subida de CSV."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import config as C
from webui import engine, server


class _Subida:
    def __init__(self, nombre, contenido=b"fighter_a,fighter_b\n"):
        self.filename, self._c = nombre, contenido

    async def read(self):
        return self._c


class Rutas(unittest.TestCase):

    def test_no_se_sale_de_cards_por_una_carpeta_hermana(self):
        # El chequeo era str(ruta).startswith(str(cards)): "cards_x" también empieza
        # con "cards", así que "../cards_x/a.csv" pasaba.
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "cards").mkdir()
            (raiz / "cards_x").mkdir()
            (raiz / "cards_x" / "a.csv").write_text("x")
            cargas = []
            with mock.patch.object(C, "ROOT", raiz), \
                    mock.patch.object(engine, "cargar", lambda *a, **k: cargas.append(a)):
                with self.assertRaises(HTTPException) as e:
                    server.cargar_csv(server.CargaCSV(nombre="../cards_x/a.csv"))
            self.assertEqual(e.exception.status_code, 404)
            self.assertEqual(cargas, [])


class Subida(unittest.TestCase):

    def test_con_una_carga_en_curso_no_se_pisa_el_archivo(self):
        # Se escribía el CSV y DESPUÉS se miraba si había una carga corriendo: el
        # usuario recibía "ya hay una carga en curso" con su archivo ya pisado.
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "cards").mkdir()
            (raiz / "cards" / "evento.csv").write_text("original")
            estado = engine.Estado()
            estado.cargando = True
            with mock.patch.object(C, "ROOT", raiz), mock.patch.object(engine, "ESTADO", estado):
                with self.assertRaises(HTTPException) as e:
                    asyncio.run(server.subir_csv(_Subida("evento.csv", b"nuevo")))
            self.assertEqual(e.exception.status_code, 409)
            self.assertEqual((raiz / "cards" / "evento.csv").read_text(), "original")


if __name__ == "__main__":
    unittest.main()
