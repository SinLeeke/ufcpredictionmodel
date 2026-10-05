"""Comprueba el lanzador de mercado en vivo simulado."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


RAIZ = Path(__file__).resolve().parents[1]
BAT = RAIZ / "scripts" / "simular_en_vivo.bat"


class TestLanzadorSimulado(unittest.TestCase):
    def test_lanzador_activa_simulacion_solo_en_su_proceso(self):
        contenido = BAT.read_bytes()
        texto = contenido.decode("ascii")
        self.assertIn(b"\r\n", contenido)
        self.assertNotIn(b"\n", contenido.replace(b"\r\n", b""))
        self.assertIn("setlocal", texto.lower())
        self.assertIn('cd /d "%~dp0.."', texto)
        self.assertRegex(texto, r'(?im)^set\s+"?UFC_MERCADO_SIMULADO=1"?\s*$')
        self.assertIn('"%~dp0ejecutar_python.bat" -m webui.server --puerto 8010 %*', texto)
        self.assertNotIn("setx", texto.lower())

    def test_config_lee_la_variable_de_entorno(self):
        entorno = os.environ.copy()
        entorno["UFC_MERCADO_SIMULADO"] = "1"
        resultado = subprocess.run(
            [sys.executable, "-c", "import config; print(int(config.MERCADO_SIMULADO))"],
            cwd=RAIZ, env=entorno, capture_output=True, text=True, check=True,
        )
        self.assertEqual(resultado.stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
