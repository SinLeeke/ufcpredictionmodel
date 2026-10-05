"""Tramos por apellido con fichas sembradas en una base temporal."""
import unittest
import unicodedata
from unittest import mock

import pandas as pd
from fastapi.testclient import TestClient
from src import storage as DB
from tests.util import aislar_base
from webui import catalogo as K, identidad_visual as I
from webui.server import app

setUpModule, tearDownModule = aislar_base()


class CatalogoTramos(unittest.TestCase):
    def setUp(self):
        self.nombres = ['Alex Pereira', 'Khalil Rountree Jr.', 'Ian Machado Garry',
            'Ángel Ábalos', 'Israel Adesanya', 'Conor McGregor', 'Zhang Weili']
        self.sembrar(self.nombres)
        parche = mock.patch.object(I, 'metadatos', return_value={})
        parche.start()
        self.addCleanup(parche.stop)
        self.cliente = TestClient(app)

    def sembrar(self, nombres):
        DB.to_csv(pd.DataFrame([{'name': nombre, 'dob': '1990-01-01',
            'fighter_url': f'http://ufcstats.com/fighter-details/{i:016x}'}
            for i, nombre in enumerate(nombres, 1)]), K.BIO, index=False)
        # La siembra debe invalidar el TTL para no reutilizar la prueba anterior.
        K._firma = None

    def consultar(self, **params):
        respuesta = self.cliente.get('/api/peleadores', params=params)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def test_cuatro_tramos_usan_ultima_palabra_sin_sufijo(self):
        for tramo, esperado in {
            'A-F': ['Ángel Ábalos', 'Israel Adesanya'],
            'G-L': ['Ian Machado Garry'],
            'M-R': ['Conor McGregor', 'Alex Pereira', 'Khalil Rountree Jr.'],
            'S-Z': ['Zhang Weili'],
        }.items():
            with self.subTest(tramo=tramo):
                datos = self.consultar(tramo=tramo)
                self.assertEqual([p['nombre'] for p in datos['peleadores']], esperado)
                self.assertEqual(datos['total'], len(esperado))

    def test_total_y_paginacion_cuentan_solo_filtrados(self):
        datos = self.consultar(tramo='M-R', limite=1, offset=1)
        self.assertEqual((datos['total'], datos['offset']), (3, 1))
        self.assertEqual([p['nombre'] for p in datos['peleadores']], ['Alex Pereira'])
        self.assertEqual(self.consultar(tramo='M-R', offset=3)['peleadores'], [])

    def test_apellido_primero_se_clasifica_por_la_ultima_palabra(self):
        # No se infiere el orden cultural: Wang cae en S-Z, pero Cong en A-F.
        self.sembrar(['Wang Cong'])
        self.assertEqual([p['nombre'] for p in self.consultar(tramo='A-F')['peleadores']],
            ['Wang Cong'])
        for tramo in ('G-L', 'M-R', 'S-Z'):
            with self.subTest(tramo=tramo):
                self.assertEqual(self.consultar(tramo=tramo)['total'], 0)

    def test_texto_y_tramo_se_combinan_sin_tildes(self):
        self.assertEqual(self.consultar(q='ángel', tramo='A-F')['total'], 1)
        self.assertEqual(self.consultar(q='pereira', tramo='A-F')['total'], 0)
        self.assertEqual(self.consultar(q='machado', tramo='G-L')['total'], 1)

    def test_tramo_invalido_devuelve_400(self):
        for tramo in ('A-Z', 'a-f', ' ', 'A–F'):
            with self.subTest(tramo=tramo):
                self.assertEqual(self.cliente.get('/api/peleadores', params={'tramo': tramo}).status_code, 400)

    def test_todos_conserva_orden_y_acepta_tramo_vacio(self):
        esperado = ['Alex Pereira', 'Ángel Ábalos', 'Conor McGregor', 'Ian Machado Garry',
            'Israel Adesanya', 'Khalil Rountree Jr.', 'Zhang Weili']
        self.assertEqual([p['nombre'] for p in self.consultar()['peleadores']], esperado)
        self.assertEqual(self.consultar(), self.consultar(tramo=''))

    def test_sufijos_enie_iniciales_no_latinas_y_desempate(self):
        nombres = ['Zeta Ñúñez Jr', 'Alfa Nunez Sr.', 'Beta Ortiz II',
            'Gamma Pérez III', 'Delta Ruiz IV', 'Uno ЖAbalos', 'Dos 3Garcia', 'Tres 李']
        self.sembrar(nombres)
        self.assertEqual([p['nombre'] for p in self.consultar(tramo='M-R')['peleadores']],
            ['Alfa Nunez Sr.', 'Zeta Ñúñez Jr', 'Beta Ortiz II', 'Gamma Pérez III', 'Delta Ruiz IV'])
        self.assertEqual(sum(self.consultar(tramo=t)['total'] for t in ('A-F', 'G-L', 'M-R', 'S-Z')), 5)
        self.assertEqual(self.consultar()['total'], 8)

    def test_clave_de_apellido_se_calcula_solo_al_crear_indice(self):
        # _leer importa este módulo localmente; el normalizador de búsqueda
        # conserva el real. La espía no altera unicodedata globalmente.
        unicode_indice = mock.Mock(wraps=unicodedata)
        with mock.patch.dict('sys.modules', {'unicodedata': unicode_indice}), \
                mock.patch.object(K, 'time') as reloj, \
                mock.patch.object(K, 'campeones_por_id', return_value={}):
            reloj.monotonic.return_value = 100
            self.assertEqual(K.buscar(tramo='A-F')['total'], 2)
            esperado = [mock.call('NFD', apellido) for apellido in
                ('Pereira', 'Rountree', 'Garry', 'Ábalos', 'Adesanya', 'McGregor', 'Weili')]
            self.assertEqual(unicode_indice.normalize.call_args_list, esperado)
            indice = K._busqueda
            for instante in (100, 101):
                # Ejercita tanto el TTL como la firma sin cambios tras vencerlo.
                reloj.monotonic.return_value = instante
                self.assertEqual(K.buscar(tramo='A-F')['total'], 2)
                self.assertEqual(K.buscar(q='pereira', tramo='M-R')['total'], 1)
                self.assertIs(K._busqueda, indice)
                self.assertEqual(unicode_indice.normalize.call_args_list, esperado)
            self.sembrar(self.nombres + ['Wang Cong'])
            self.assertEqual(K.buscar(tramo='A-F')['total'], 3)
            self.assertEqual(unicode_indice.normalize.call_args_list,
                esperado + esperado + [mock.call('NFD', 'Cong')])
