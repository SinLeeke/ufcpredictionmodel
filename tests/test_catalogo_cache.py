"""Índice reutilizable sin mezclar bases, nombres ni fichas individuales."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd
from pandas.testing import assert_frame_equal
from src import storage as DB
from webui import catalogo as K, identidad_visual as I, paises as P


class CacheCatalogo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {'UFC_DB': str(Path(self.tmp.name) / 'uno.db')})
        env.start(); self.addCleanup(env.stop)
        self.sembrar(['Jean Silva', 'Jean Silva', 'Álex Pérez'])

    @staticmethod
    def sembrar(nombres):
        DB.to_csv(pd.DataFrame([{'name': n, 'dob': '1996-01-01',
            'fighter_url': f'http://ufcstats.com/fighter-details/{i:016x}'}
            for i, n in enumerate(nombres, 1)]), K.BIO, index=False)

    def test_firma_caliente_no_reabre_sqlite_cada_fila(self):
        with mock.patch.object(K.time, 'monotonic', return_value=100.):
            original = K._leer()
            with mock.patch.object(DB, 'stat', side_effect=AssertionError('Firma repetida')):
                for _ in range(40):
                    self.assertIs(K._leer(), original)

    def test_agrupacion_preserva_orden_valores_exactos_y_omite_url_nula(self):
        frame = pd.DataFrame({'fight_url': ['b', 'a', 'b', None], 'fighter': ['Uno', 'Dos', 'Tres', 'Desconocido'],
            'valor': [1.2345678901234567, float('nan'), .3333333333333333, 8.], 'won': [True, False, False, True]})
        esperado = {u: g.to_dict('records') for u, g in frame.groupby('fight_url', sort=False)}
        actual = K._agrupar_estadisticas(frame)
        self.assertEqual(list(actual), ['b', 'a'])
        for url in esperado:
            assert_frame_equal(pd.DataFrame(actual[url]), pd.DataFrame(esperado[url]), check_exact=True)

    def test_actualizacion_externa_se_detecta_al_vencer_250ms(self):
        with mock.patch.object(K.time, 'monotonic', return_value=100.):
            anterior = K._leer()
            self.sembrar(['Otra ficha'])
            self.assertIs(K._leer(), anterior)
        with mock.patch.object(K.time, 'monotonic', return_value=100.25):
            actual = K._leer()
            self.assertEqual(actual[0]['0000000000000001']['name'], 'Otra ficha')

    def test_cambio_de_base_es_inmediato_dentro_del_ttl(self):
        with mock.patch.object(K.time, 'monotonic', return_value=100.):
            K._leer()
            with mock.patch.dict(os.environ, {'UFC_DB': str(Path(self.tmp.name) / 'dos.db')}):
                self.sembrar(['Otra base'])
                self.assertEqual(K._leer()[0]['0000000000000001']['name'], 'Otra base')

    def test_busqueda_acentos_orden_paginacion_y_copias_independientes(self):
        with mock.patch.object(I, 'metadatos', return_value={'pais': None}):
            todos = K.buscar('', limite=3)
            self.assertEqual([p['nombre'] for p in todos['peleadores']], ['Álex Pérez', 'Jean Silva', 'Jean Silva'])
            self.assertEqual(K.buscar('JÉAN')['total'], 2)
            self.assertEqual(K.buscar('alex')['total'], 1)
            self.assertEqual(K.buscar('', limite=1, offset=2)['peleadores'][0]['id'], '0000000000000002')
            todos['peleadores'][0]['nombre'] = 'Modificado por cliente'
            self.assertEqual(K.buscar('alex')['peleadores'][0]['nombre'], 'Álex Pérez')

    def test_ranking_homonimo_solo_resuelve_vinculo_individual(self):
        DB.write_text(K.RANKINGS, json.dumps({'divisiones': [{'nombre': 'Featherweight', 'peleadores': [
            {'nombre': 'Jean Silva', 'puesto': 4, 'perfil_ufc': 'https://www.ufcespanol.com/athlete/jean-silva'}]}],
            'fecha': '2026-10-03'}))
        with mock.patch.object(I, 'metadatos', return_value={}):
            self.assertIsNone(K.rankings()['divisiones'][0]['peleadores'][0]['id'])
            P.asociar('0000000000000001', 'https://www.ufc.com/athlete/jean-silva')
            self.assertEqual(K.rankings()['divisiones'][0]['peleadores'][0]['id'], '0000000000000001')
            P.asociar('0000000000000002', 'https://www.ufc.com/athlete/jean-silva')
            self.assertIsNone(K.rankings()['divisiones'][0]['peleadores'][0]['id'])


if __name__ == '__main__':
    unittest.main()
