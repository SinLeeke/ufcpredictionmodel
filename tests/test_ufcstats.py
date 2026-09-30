"""Pruebas de src/ufcstats.py: parseo de la ficha y caché."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bs4 import BeautifulSoup

from src import ufcstats as U


def _fila(res, rival, evento, metodo, detalle, fecha):
    """Una fila de la tabla de historial con la estructura real de UFCStats:
    W/L | Fighter | Kd | Str | Td | Sub | Event | Method | Round | Time."""
    p = lambda *xs: "".join(f'<p class="b-fight-details__table-text">{x}</p>' for x in xs)
    celdas = [
        f'<p class="b-fight-details__table-text"><a class="b-flag"><i class="b-flag__text">{res}</i></a></p>',
        p("<a>Peleador Prueba</a>", f"<a>{rival}</a>"), p(0, 0), p(50, 30), p(2, 0), p(1, 0),
        p(f"<a>{evento}</a>", fecha), p(metodo, detalle), p(3), p("5:00"),
    ]
    tds = "".join(f'<td class="b-fight-details__table-col">{c}</td>' for c in celdas)
    return f'<tr class="b-fight-details__table-row">{tds}</tr>'


def _soup(*filas):
    return BeautifulSoup("<table><tbody>" + "".join(filas) + "</tbody></table>", "html.parser")


class MetodoDelHistorial(unittest.TestCase):

    def test_nombres_con_ko_no_convierten_decisiones_en_ko(self):
        # BUG: se buscaba "KO" en el texto de TODA la fila, que incluye el nombre del
        # rival y el del evento. Kopylov, Volkov, Shevchenko... convertían cada
        # decisión en KO. Medido: 3,7% de los resultados y el 23% de los activos.
        h = U._parse_history(_soup(
            _fila("win", "Roman Kopylov", "UFC 300: Pereira vs. Hill", "U-DEC", "", "Apr. 13, 2024"),
            _fila("win", "John Doe", "UFC Fight Night: Volkov vs. Rozenstruik", "S-DEC", "", "Jun. 03, 2023"),
            _fila("win", "Jim Smith", "UFC 290: Volkanovski vs. Rodriguez", "U-DEC", "", "Jul. 08, 2023"),
            _fila("loss", "Valentina Shevchenko", "UFC 280: Oliveira vs. Makhachev", "U-DEC", "", "Oct. 22, 2022"),
        ))
        self.assertEqual(h["win_ko_rate"], 0.0)
        self.assertEqual(h["win_dec_rate"], 1.0)
        self.assertEqual(h["lost_by_finish_rate"], 0.0)

    def test_finalizaciones_reales_se_siguen_leyendo(self):
        h = U._parse_history(_soup(
            _fila("win", "A B", "UFC 1", "KO/TKO", "Punches", "Jan. 01, 2024"),
            _fila("win", "C D", "UFC 2", "SUB", "Rear Naked Choke", "Jan. 01, 2023"),
            _fila("loss", "E F", "UFC 3", "KO/TKO", "Kick", "Jan. 01, 2022"),
            _fila("loss", "G H", "UFC 4", "U-DEC", "", "Jan. 01, 2021"),
        ))
        self.assertEqual(h["win_ko_rate"], 0.5)
        self.assertEqual(h["win_sub_rate"], 0.5)
        self.assertEqual(h["lost_by_finish_rate"], 0.5)
        self.assertEqual((h["wins"], h["losses"], h["streak"]), (2, 2, 2))


class CacheDeFichas(unittest.TestCase):
    """Las fichas cacheadas con el parser viejo traen las tasas mal: no se reusan."""

    def test_ficha_de_version_vieja_se_vuelve_a_bajar(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text(json.dumps({"peleador prueba": {"name": "Peleador Prueba",
                                                             "win_ko_rate": 0.9}}))
            html = _soup(_fila("win", "Roman Kopylov", "UFC 300", "U-DEC", "", "Apr. 13, 2024"))
            with mock.patch.object(U, "CACHE_PATH", cache), \
                    mock.patch.object(U, "find_fighter_url", lambda n: "http://x/ficha"), \
                    mock.patch.object(U, "_get", lambda url: html):
                d = U.get_fighter("Peleador Prueba")
            self.assertEqual(d["win_ko_rate"], 0.0)
            self.assertEqual(json.loads(cache.read_text())["peleador prueba"]["_parser"], U.VERSION_PARSER)

    def test_sin_red_se_usa_la_ficha_vieja_antes_que_nada(self):
        # Perder al peleador (pelea omitida) es peor que usar su ficha anterior.
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            cache.write_text(json.dumps({"peleador prueba": {"name": "Peleador Prueba"}}))
            with mock.patch.object(U, "CACHE_PATH", cache), \
                    mock.patch.object(U, "find_fighter_url", lambda n: None), \
                    contextlib.redirect_stdout(io.StringIO()):
                d = U.get_fighter("Peleador Prueba")
            self.assertEqual(d["name"], "Peleador Prueba")


if __name__ == "__main__":
    unittest.main()
