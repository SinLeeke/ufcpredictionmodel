"""/api/rankings: bandera por ficha UFC, campeones del P4P y forma del contrato, sin red."""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd

import config as C
from src import storage as DB, rankings as R, ufc_oficial as U
from webui import catalogo as K, identidad_visual as I, paises as P

EVENTO = 'https://www.ufc.com/event/ufc-330'


def fila(puesto, nombre, slug=None):
    return {'puesto': puesto, 'nombre': nombre,
            'perfil_ufc': 'https://www.ufc.com/athlete/' + (slug or nombre.lower().replace(' ', '-'))}


def pelea(a, b, pa, pb, slug_a=None, slug_b=None, bandera_a=None):
    perfil = lambda n, s: 'https://www.ufcespanol.com/athlete/' + (s or n.lower().replace(' ', '-'))
    pais_a = {'codigo': pa[0], 'nombre': pa[1]}
    if bandera_a:
        pais_a['bandera'] = bandera_a
    return {'a': a, 'b': b, 'perfil_a': perfil(a, slug_a), 'perfil_b': perfil(b, slug_b),
            'pais_a': pais_a, 'pais_b': {'codigo': pb[0], 'nombre': pb[1]}}


class RankingsApi(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = mock.patch.dict(os.environ, {'UFC_DB': str(Path(temp.name) / 'rankings.db')})
        env.start()
        self.addCleanup(env.stop)
        red = mock.patch('requests.get', side_effect=AssertionError('/api/rankings no consulta la red'))
        red.start()
        self.addCleanup(red.stop)
        # BIO: «Benoit Saint Denis» sin tilde, como en UFCStats, y dos
        # «Jean Silva»: el país no puede depender del ID ni del nombre.
        nombres = ['Islam Makhachev', 'Justin Gaethje', 'Ilia Topuria', 'Alex Pereira', 'Arnold Allen',
                   'Benoit Saint Denis', 'Jean Silva', 'Jean Silva', 'Valentina Shevchenko',
                   'Kayla Harrison', 'Zhang Weili', 'Mackenzie Dern']
        DB.to_csv(pd.DataFrame([{'fighter_url': f'http://ufcstats.com/fighter-details/{i:016x}', 'name': n}
                                for i, n in enumerate(nombres, 1)]), K.BIO, index=False)
        self.ranking = {'fecha': '2026-10-03', 'fuente': 'https://www.ufc.com/rankings', 'divisiones': [
            {'nombre': "Men's Pound-for-Pound", 'peleadores': [
                fila(1, 'Islam Makhachev'), fila(2, 'Ilia Topuria'), fila(3, 'Alex Pereira'),
                fila(4, 'Justin Gaethje'), fila(5, 'Jean Silva')]},
            {'nombre': 'Peso pluma', 'peleadores': [
                fila(0, 'Arnold Allen'), fila(1, 'Jean Silva'), fila(2, 'Ilia Topuria')]},
            {'nombre': 'Ligero', 'peleadores': [
                fila(0, 'Justin Gaethje'), fila(1, 'Benoît Saint Denis', 'benoit-saint-denis'),
                fila(2, 'Ilia Topuria')]},
            {'nombre': 'Peso welter', 'peleadores': [fila(0, 'Islam Makhachev'), fila(1, 'Chidi Njokuani')]},
            {'nombre': "Women's Pound-for-Pound", 'peleadores': [
                fila(1, 'Valentina Shevchenko'), fila(2, 'Zhang Weili'), fila(3, 'Kayla Harrison')]},
            {'nombre': 'Peso de la mujer', 'peleadores': [fila(0, 'Mackenzie Dern'), fila(1, 'Zhang Weili')]},
            {'nombre': "Women's Flyweight", 'peleadores': [fila(0, 'Valentina Shevchenko')]},
            {'nombre': 'Gallo de las mujeres', 'peleadores': [fila(0, 'Kayla Harrison')]},
        ]}
        DB.write_text(K.RANKINGS, json.dumps(self.ranking, ensure_ascii=False))
        I._rankings.cache_clear()
        I._invalidar()
        P.guardar_eventos([{'url': EVENTO, 'peleas': [
            pelea('Islam Makhachev', 'Ilia Topuria', ('RU', 'Rusia'), ('ES', 'España')),
            pelea('Alex Pereira', 'Justin Gaethje', ('BR', 'Brasil'), ('US', 'Estados Unidos')),
            pelea('Arnold Allen', 'Benoît Saint Denis', ('GB', 'England'), ('FR', 'Francia'),
                  slug_b='benoit-saint-denis', bandera_a='EN'),
            pelea('Jean Silva', 'Valentina Shevchenko', ('BR', 'Brasil'), ('PE', 'Perú')),
            pelea('Kayla Harrison', 'Zhang Weili', ('US', 'Estados Unidos'), ('CN', 'China')),
            # UFC enlaza a veces una esquina con la ficha de otro: no se acepta.
            pelea('Mackenzie Dern', 'Bruno Korea', ('BR', 'Brasil'), ('BR', 'Brasil'), slug_b='chidi-njokuani'),
        ]}])

    def rankings(self):
        return K.rankings()

    def division(self, d, nombre):
        return next(x for x in d['divisiones'] if x['nombre'] == nombre)

    def test_todas_las_filas_tienen_bandera_por_url_aunque_el_id_sea_ambiguo(self):
        d = self.rankings()
        sin_pais = [(x['nombre'], r['nombre']) for x in d['divisiones'] for r in x['peleadores'] if r['pais'] is None]
        # Única excepción justificada: la cartelera nombra esa ficha como otra persona.
        self.assertEqual(sin_pais, [('Peso welter', 'Chidi Njokuani')])
        self.assertIn({'nombre': 'Chidi Njokuani', 'perfil_ufc': 'https://www.ufc.com/athlete/chidi-njokuani',
                       'motivo': 'sin país en el registro'}, K.NO_CALZAN)
        p4p = self.division(d, "Men's Pound-for-Pound")['peleadores']
        silva = p4p[4]
        self.assertIsNone(silva['id'])                         # dos fichas UFCStats: sin atribuir
        self.assertEqual(silva['pais']['codigo'], 'BR')        # pero la URL identifica a la persona
        self.assertEqual({r['nombre']: r['pais']['bandera'] for r in p4p[:4]},
                         {'Islam Makhachev': 'RU', 'Ilia Topuria': 'ES', 'Alex Pereira': 'BR', 'Justin Gaethje': 'US'})
        # La UI de hoy pinta desde identidad_visual: la misma bandera en ambos.
        self.assertEqual(p4p[0]['identidad_visual']['pais'], p4p[0]['pais'])

    def test_inglaterra_conserva_codigo_gb_y_bandera_en(self):
        # UFC en español deja «England» sin traducir; el contrato pide español.
        allen = self.division(self.rankings(), 'Peso pluma')['peleadores'][0]
        self.assertEqual((allen['pais']['codigo'], allen['pais']['bandera'], allen['pais']['nombre']),
                         ('GB', 'EN', 'Inglaterra'))

    def test_nombre_con_tilde_calza_normalizado_con_ufcstats(self):
        bsd = self.division(self.rankings(), 'Ligero')['peleadores'][1]
        self.assertEqual(bsd['pais']['codigo'], 'FR')
        self.assertEqual(bsd['id'], f'{6:016x}')
        self.assertTrue(any(x.get('nombre') == 'Benoît Saint Denis' and x['ufcstats'] == ['Benoit Saint Denis']
                            for x in K.NO_CALZAN))

    def test_campeones_del_p4p_por_url_y_nombre(self):
        d = self.rankings()
        p4p = {r['nombre']: r['campeon'] for r in self.division(d, "Men's Pound-for-Pound")['peleadores']}
        self.assertEqual(p4p['Islam Makhachev'], {'division': 'Peso welter', 'clave': 'Welterweight', 'interino': False})
        self.assertEqual(p4p['Justin Gaethje'], {'division': 'Ligero', 'clave': 'Lightweight', 'interino': False})
        self.assertIsNone(p4p['Ilia Topuria'])
        self.assertIsNone(p4p['Alex Pereira'])
        self.assertIsNone(p4p['Jean Silva'])
        f = {r['nombre']: r['campeon'] for r in self.division(d, "Women's Pound-for-Pound")['peleadores']}
        self.assertEqual(f['Valentina Shevchenko']['clave'], "Women's Flyweight")
        self.assertEqual(f['Kayla Harrison']['clave'], "Women's Bantamweight")
        self.assertIsNone(f['Zhang Weili'])
        # En una división, sólo el puesto 0 lleva campeon.
        pluma = self.division(d, 'Peso pluma')['peleadores']
        self.assertEqual(pluma[0]['campeon'], {'division': 'Peso pluma', 'clave': 'Featherweight', 'interino': False})
        self.assertEqual([r['campeon'] for r in pluma[1:]], [None, None])

    def test_homonimo_con_otra_ficha_no_hereda_el_cinturon(self):
        # Otro «Justin Gaethje» con otra ficha en el P4P: el nombre exacto no basta.
        self.ranking['divisiones'][0]['peleadores'][3]['perfil_ufc'] = 'https://www.ufc.com/athlete/justin-gaethje-0'
        DB.write_text(K.RANKINGS, json.dumps(self.ranking, ensure_ascii=False))
        p4p = self.division(self.rankings(), "Men's Pound-for-Pound")['peleadores']
        self.assertIsNone(p4p[3]['campeon'])
        self.assertIsNone(p4p[3]['pais'])

    def test_p4p_muestra_division_tambien_sin_ser_campeon(self):
        d = self.rankings()
        hombres = {r['nombre']: r for r in self.division(d, "Men's Pound-for-Pound")['peleadores']}
        mujeres = {r['nombre']: r for r in self.division(d, "Women's Pound-for-Pound")['peleadores']}
        self.assertIsNone(hombres['Jean Silva']['campeon'])
        self.assertEqual(hombres['Jean Silva']['division'],
                         {'clave': 'Featherweight', 'nombre': 'Peso pluma', 'fuente': 'ranking', 'fecha': '2026-10-03'})
        self.assertIsNone(mujeres['Zhang Weili']['campeon'])
        self.assertEqual(mujeres['Zhang Weili']['division']['clave'], "Women's Strawweight")
        self.assertEqual(hombres['Islam Makhachev']['division']['clave'], 'Welterweight')

    def test_dos_categorias_se_conservan_sin_elegir_por_orden(self):
        d = self.rankings()
        topuria = self.division(d, "Men's Pound-for-Pound")['peleadores'][1]
        self.assertIsNone(topuria['division'])
        self.assertEqual([c['clave'] for c in topuria['divisiones']], ['Featherweight', 'Lightweight'])

    def test_division_no_se_atribuye_a_un_homonimo_con_otra_ficha(self):
        self.ranking['divisiones'][0]['peleadores'][4]['perfil_ufc'] = 'https://www.ufc.com/athlete/otro-jean-silva'
        DB.write_text(K.RANKINGS, json.dumps(self.ranking))
        jean = self.division(self.rankings(), "Men's Pound-for-Pound")['peleadores'][4]
        self.assertIsNone(jean['division'])
        self.assertEqual(jean['divisiones'], [])

    def test_p4p_sin_division_en_la_captura_no_inventa_un_peso(self):
        alex = self.division(self.rankings(), "Men's Pound-for-Pound")['peleadores'][2]
        self.assertIsNone(alex['division'])
        self.assertEqual(alex['divisiones'], [])

    def test_campeon_interino_marcado_en_la_fuente(self):
        self.ranking['divisiones'][2]['peleadores'][0]['tipo'] = 'IC'
        DB.write_text(K.RANKINGS, json.dumps(self.ranking, ensure_ascii=False))
        p4p = self.division(self.rankings(), "Men's Pound-for-Pound")['peleadores']
        self.assertTrue(p4p[3]['campeon']['interino'])

    def test_forma_del_contrato_y_sin_nan(self):
        d = self.rankings()
        json.dumps(d, allow_nan=False)
        self.assertEqual((d['fecha'], d['fuente']), ('2026-10-03', 'https://www.ufc.com/rankings'))
        self.assertEqual([x['clave'] for x in d['divisiones']], [
            "Men's Pound-for-Pound", 'Featherweight', 'Lightweight', 'Welterweight', "Women's Pound-for-Pound",
            "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight"])
        self.assertEqual([x['genero'] for x in d['divisiones']], list('MMMMFFFF'))
        self.assertEqual([x['p4p'] for x in d['divisiones']], [True, False, False, False, True, False, False, False])
        self.assertEqual(d['grupos'], [{'titulo': 'Hombres', 'divisiones': [0, 1, 2, 3]},
                                       {'titulo': 'Mujeres', 'divisiones': [4, 5, 6, 7]}])
        for x in d['divisiones']:
            self.assertEqual(x['nombre'], self.ranking['divisiones'][d['divisiones'].index(x)]['nombre'])
            for r in x['peleadores']:
                self.assertTrue({'nombre', 'id', 'perfil_ufc', 'pais', 'campeon', 'foto', 'puesto',
                                 'identidad_visual'} <= set(r))
                self.assertIsInstance(r['puesto'], int)
                if r['pais'] is not None:
                    self.assertRegex(r['pais']['codigo'], r'^[A-Z]{2}$')
                    self.assertRegex(r['pais']['bandera'], r'^([A-Z]{2})$')
                    self.assertTrue(r['pais']['nombre'])
        self.assertEqual(self.division(d, 'Ligero')['peleadores'][1]['foto'], '/api/foto/Beno%C3%AEt%20Saint%20Denis')
        self.assertEqual(d['divisiones'][0]['peleadores'][0]['foto'], '/api/foto/Islam%20Makhachev')

    def test_nan_en_el_registro_no_llega_a_la_ui(self):
        doc = DB.read_json(P.CACHE)
        doc['atletas']['https://www.ufc.com/athlete/ilia-topuria']['nombre'] = float('nan')
        doc['atletas']['https://www.ufc.com/athlete/alex-pereira']['bandera'] = float('nan')
        DB.write_text(P.CACHE, json.dumps(doc))         # escribe NaN literal, como pandas
        P._invalidar()
        d = self.rankings()
        texto = json.dumps(d, allow_nan=False)
        self.assertNotIn('NaN', texto)
        p4p = self.division(d, "Men's Pound-for-Pound")['peleadores']
        self.assertEqual(p4p[1]['pais']['nombre'], 'ES')      # cae al código, nunca a NaN
        self.assertEqual(p4p[2]['pais']['bandera'], 'BR')

    def test_ranking_ausente_responde_vacio(self):
        DB.unlink(K.RANKINGS)
        d = self.rankings()
        self.assertEqual((d['divisiones'], d['grupos']), ([], []))
        json.dumps(d, allow_nan=False)


class CompletarPaises(unittest.TestCase):
    """El pase de red, con ufc.com simulado: incremental y sin pisar lo más nuevo."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = mock.patch.dict(os.environ, {'UFC_DB': str(Path(temp.name) / 'completar.db')})
        env.start()
        self.addCleanup(env.stop)
        DB.write_text(C.DATA_RAW / 'rankings_oficiales.json', json.dumps({'fecha': '2026-10-03', 'divisiones': [
            {'nombre': 'Ligero', 'peleadores': [fila(0, 'Justin Gaethje'), fila(1, 'Arman Tsarukyan')]}]}))
        tarjeta = lambda a, b, slug_a, slug_b, ca, cb: f'''<div class="c-listing-fight">
<div class="c-listing-fight__corner-name--red"><a href="/athlete/{slug_a}">{a}</a></div>
<div class="c-listing-fight__corner-name--blue"><a href="/athlete/{slug_b}">{b}</a></div>
<div class="c-listing-fight__class-text">Lightweight Bout</div>
<div class="c-listing-fight__country--red"><img src="https://ufc.com/images/flags/{ca}.PNG"><div class="c-listing-fight__country-text">{ca}</div></div>
<div class="c-listing-fight__country--blue"><img src="https://ufc.com/images/flags/{cb}.PNG"><div class="c-listing-fight__country-text">{cb}</div></div></div>'''
        self.paginas = {
            'https://www.ufc.com/athlete/justin-gaethje':
                '<a href="https://www.ufcespanol.com/event/ufc-330#1">x</a><a href="/event/ufc-300">y</a>',
            'https://www.ufc.com/athlete/arman-tsarukyan': '<a href="/event/ufc-300#9">z</a>',
            'https://www.ufc.com/event/ufc-330': tarjeta('Justin Gaethje', 'Otro', 'justin-gaethje', 'otro', 'US', 'MX'),
            # Cartelera vieja con otra bandera: no pisa la más reciente.
            'https://www.ufc.com/event/ufc-300': tarjeta('Arman Tsarukyan', 'Justin Gaethje', 'arman-tsarukyan',
                                                         'justin-gaethje', 'AM', 'CA'),
        }
        self.pedidas = []

        def get(url):
            self.pedidas.append(url)
            html = self.paginas.get(url)
            return mock.Mock(text=html) if html is not None else None
        p = mock.patch.object(U, '_get', side_effect=get)
        p.start()
        self.addCleanup(p.stop)

    def test_completa_incremental_y_sin_pisar_lo_reciente(self):
        r = R.completar_paises(pausa=0, log=lambda *_: None, ahora=1_800_000_000)
        self.assertEqual(r['sin_pais'], {})
        self.assertEqual(P.pais_perfil('Justin Gaethje', 'https://www.ufc.com/athlete/justin-gaethje')['codigo'], 'US')
        self.assertEqual(P.pais_perfil('Arman Tsarukyan', 'https://www.ufc.com/athlete/arman-tsarukyan')['codigo'], 'AM')
        self.assertEqual(self.pedidas, ['https://www.ufc.com/athlete/justin-gaethje', 'https://www.ufc.com/event/ufc-330',
                                        'https://www.ufc.com/athlete/arman-tsarukyan', 'https://www.ufc.com/event/ufc-300'])
        self.pedidas.clear()
        r = R.completar_paises(pausa=0, log=lambda *_: None, ahora=1_800_000_100)
        self.assertEqual((r['peticiones'], self.pedidas), (0, []))

    def test_sin_respuesta_queda_registrado_con_su_motivo(self):
        del self.paginas['https://www.ufc.com/athlete/arman-tsarukyan']
        r = R.completar_paises(pausa=0, log=lambda *_: None, ahora=1_800_000_000)
        self.assertEqual(list(r['sin_pais']), ['https://www.ufc.com/athlete/arman-tsarukyan'])
        self.assertIn('no consultada', r['sin_pais']['https://www.ufc.com/athlete/arman-tsarukyan']['motivo'])
        self.assertEqual(r['fallos'], ['https://www.ufc.com/athlete/arman-tsarukyan'])

    def test_enlaces_de_ficha_se_normalizan_y_no_salen_de_ufc(self):
        html = ('<a href="https://www.ufcespanol.com/event/ufc-311#11894">a</a><a href="/events">b</a>'
                '<a href="https://malicioso.test/event/ufc-1">c</a><a href="/event/ufc-311">d</a>')
        self.assertEqual(R.eventos_de_ficha(html), ['https://www.ufc.com/event/ufc-311'])


class RankingReal(unittest.TestCase):
    """Sobre la base local si existe (data/ no se versiona): nadie sin bandera sin motivo."""

    # Atletas del ranking real sin país, cada uno con su motivo comprobado.
    JUSTIFICADOS = {
        # Comprobado el 2026-10-03: UFC deja vacía su bandera en sus tres
        # carteleras (UFC 329, Fight Night 07-02-2026, UFC 320) y Wikidata
        # (Q123849055, nombre y nacimiento 1997-08-02 iguales a su ficha BIO)
        # declara dos nacionalidades, Afganistán y Reino Unido, con el mismo
        # rango y sin referencias: no hay desempate explícito, así que null.
        'https://www.ufc.com/athlete/farid-basharat': 'doble nacionalidad sin desempate; UFC no la declara',
    }

    @unittest.skipUnless((C.ROOT / 'data' / 'ufc.db').exists() and 'UFC_DB' not in os.environ,
                         'sin base local de datos')
    def test_ranking_real_con_bandera(self):
        d = K.rankings()
        json.dumps(d, allow_nan=False)
        if not d['divisiones']:
            self.skipTest('sin captura de rankings')
        sin_pais = {r['perfil_ufc'] for x in d['divisiones'] for r in x['peleadores'] if r['pais'] is None}
        self.assertEqual(sin_pais - set(self.JUSTIFICADOS), set())
        for x in d['divisiones']:
            if x['p4p']:
                campeones = [r['nombre'] for r in x['peleadores'] if r['campeon']]
                titulares = {r['perfil_ufc'] for y in d['divisiones'] if not y['p4p'] and y['genero'] == x['genero']
                             for r in y['peleadores'] if r['puesto'] == 0}
                self.assertEqual({r['perfil_ufc'] for r in x['peleadores'] if r['campeon']},
                                 {r['perfil_ufc'] for r in x['peleadores'] if r['perfil_ufc'] in titulares}, campeones)


if __name__ == '__main__':
    unittest.main()
