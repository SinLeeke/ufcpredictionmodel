"""País de la esquina, identidad individual y persistencia sin red."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd
from src import storage as DB, ufc_oficial as U
from webui import paises as P


EVENTO = '''<div class="country">United Arab Emirates</div>
<div class="c-listing-fight">
<div class="c-listing-fight__corner-name--red"><a href="/athlete/alexander-volkanovski">Alexander Volkanovski</a></div>
<div class="c-listing-fight__corner-name--blue"><a href="https://www.ufcespanol.com/athlete/movsar-evloev">Movsar Evloev</a></div>
<div class="c-listing-fight__class-text">Featherweight Title Bout</div>
<div class="c-listing-fight__country--red"><img src="https://ufc.com/images/flags/AU.PNG"><div class="c-listing-fight__country-text">Australia</div></div>
<div class="c-listing-fight__country--blue"><img src="https://ufc.com/images/flags/RU.PNG"><div class="c-listing-fight__country-text">Rusia</div></div></div>'''


class Paises(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'UFC_DB': str(Path(self.tmp.name) / 'countries.db')})
        self.env.start()
        DB.to_csv(pd.DataFrame([
            {'name': 'Alexander Volkanovski', 'fighter_url': 'http://ufcstats.com/fighter-details/1111111111111111'},
            {'name': 'Jean Silva', 'fighter_url': 'http://ufcstats.com/fighter-details/52ef95b5860fb28c'},
            {'name': 'Jean Silva', 'fighter_url': 'http://ufcstats.com/fighter-details/9211aae062b799d6'},
        ]), P.BIO, index=False)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def evento(self, nombre='Jean Silva'):
        return {'url': 'https://www.ufc.com/event/ufc-333', 'pais': 'United Arab Emirates',
                'peleas': [{'a': nombre, 'b': 'Sin país', 'perfil_a': 'https://www.ufcespanol.com/athlete/jean-silva',
                            'pais_a': {'codigo': 'BR', 'nombre': 'Brasil'}}]}

    def test_parser_no_confunde_pais_del_recinto(self):
        fila = U.parsear_evento(EVENTO)[0]
        self.assertEqual(fila['pais_a'], {'codigo': 'AU', 'nombre': 'Australia'})
        self.assertEqual(fila['pais_b'], {'codigo': 'RU', 'nombre': 'Rusia'})
        self.assertEqual(fila['perfil_a'], 'https://www.ufc.com/athlete/alexander-volkanovski')
        sin_paises = EVENTO.replace('c-listing-fight__country--', 'otro--')
        self.assertIsNone(U.parsear_evento(sin_paises)[0]['pais_a'])

    def test_bandera_inglesa_no_se_presenta_como_codigo_iso_inexistente(self):
        html = EVENTO.replace('/AU.PNG', '/EN.PNG').replace('Australia</div>', 'England</div>')
        e = {'url': 'https://www.ufc.com/event/ufc-333', 'peleas': U.parsear_evento(html)}
        self.assertEqual(e['peleas'][0]['pais_a'], {'codigo': 'GB', 'nombre': 'England', 'bandera': 'EN'})
        P.guardar_eventos([e])
        pais = P.lookup('Alexander Volkanovski')
        self.assertEqual((pais['codigo'], pais['bandera']), ('GB', 'EN'))

    def test_northern_ireland_no_utiliza_bandera_de_nicaragua(self):
        html = EVENTO.replace('/AU.PNG', '/NI.PNG').replace('Australia</div>', 'Northern Ireland</div>')
        e = {'url': 'https://www.ufc.com/event/ufc-333', 'peleas': U.parsear_evento(html)}
        P.guardar_eventos([e])
        pais = P.lookup('Alexander Volkanovski')
        self.assertEqual(pais['codigo'], 'GB')
        self.assertNotEqual(pais.get('bandera'), 'NI')

    def test_persiste_y_reabre_con_red_bloqueada(self):
        e = {'url': 'https://www.ufc.com/event/ufc-333', 'peleas': U.parsear_evento(EVENTO)}
        P.guardar_eventos([e])
        importlib.reload(P)
        with mock.patch('requests.get', side_effect=AssertionError('No se consulta la red')):
            p = P.lookup('Alexander Volkanovski', '1111111111111111')
            self.assertEqual(p['codigo'], 'AU')
            self.assertEqual(p['fuente'], e['url'])
        self.assertFalse(P.CACHE.exists())  # recurso SQLite, no JSON operativo nuevo

    def test_homonimos_exigen_vinculo_individual(self):
        P.guardar_eventos([self.evento()])
        self.assertIsNone(P.lookup('Jean Silva'))
        self.assertIsNone(P.lookup('Jean Silva', '52ef95b5860fb28c'))
        self.assertIsNone(P.lookup('Jean Silva', '9211aae062b799d6'))
        P.asociar('52ef95b5860fb28c', 'https://www.ufc.com/athlete/jean-silva')
        self.assertEqual(P.lookup('Jean Silva', '52ef95b5860fb28c')['codigo'], 'BR')
        self.assertIsNone(P.lookup('Jean Silva', '9211aae062b799d6'))
        self.assertEqual(P.lookup('Jean Silva', 'https://www.ufc.com/athlete/jean-silva')['codigo'], 'BR')

    def test_identidad_nombre_y_fuente_son_exactos(self):
        P.guardar_eventos([self.evento()])
        self.assertIsNone(P.lookup('JEAN SILVA', 'https://www.ufc.com/athlete/jean-silva'))
        self.assertIsNone(P.lookup('Sin país', 'https://www.ufc.com/athlete/jean-silva'))
        self.assertIsNone(P.lookup('Jean Silva', 'https://malicioso.test/athlete/jean-silva'))
        e = self.evento(); e['url'] = 'https://otro.test/event/x'
        P.guardar_eventos([e])
        self.assertIsNone(P.lookup('Sin país'))

    def test_cache_eventos_persiste_paises_sin_otra_peticion(self):
        DB.write_text(P.EVENTOS, json.dumps({'eventos': {'proximos': [self.evento()]}}))
        self.assertEqual(P.lookup('Jean Silva', 'https://www.ufc.com/athlete/jean-silva')['codigo'], 'BR')

    def test_codigo_invalido_y_pais_evento_no_generan_bandera(self):
        e = self.evento(); e['peleas'][0]['pais_a'] = {'codigo': 'ZZ', 'nombre': 'Inventado'}
        P.guardar_eventos([e])
        self.assertIsNone(P.lookup('Jean Silva', 'https://www.ufc.com/athlete/jean-silva'))
        e['peleas'][0].pop('pais_a')
        P.guardar_eventos([e])
        self.assertIsNone(P.lookup('Jean Silva', 'https://www.ufc.com/athlete/jean-silva'))

    def test_country_wikidata_individual_no_transfiere_ranking_o_pais_al_homonimo(self):
        P.guardar_ficha('52ef95b5860fb28c', 'Jean Silva', 'BR', 'Brasil',
            'https://www.wikidata.org/wiki/Q127429178', {'comparacion': 'identificadores verificados'})
        P.asociar('52ef95b5860fb28c', 'https://www.ufc.com/athlete/jean-silva')
        self.assertEqual(P.lookup('Jean Silva', '52ef95b5860fb28c')['codigo'], 'BR')
        self.assertEqual(P.lookup('Jean Silva', 'https://www.ufc.com/athlete/jean-silva')['codigo'], 'BR')
        self.assertIsNone(P.lookup('Jean Silva', '9211aae062b799d6'))
        self.assertIsNone(P.lookup('Jean Silva'))
        self.assertEqual(P.identidad_ufc('52ef95b5860fb28c'), 'https://www.ufc.com/athlete/jean-silva')
        self.assertIsNone(P.identidad_ufc('9211aae062b799d6'))


if __name__ == '__main__':
    unittest.main()
