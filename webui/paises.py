"""País atribuido al atleta por UFC o Wikidata, con identidad y procedencia.

Las consultas de la UI sólo leen SQLite. El país del recinto o de Kaggle no
es una nacionalidad. Un homónimo requiere un vínculo individual verificado;
la ausencia de datos deja al atleta sin bandera, sin elegir otra persona.
La fuente pública no constituye por sí misma una licencia de reutilización.
"""
from __future__ import annotations

from collections import Counter
import json
import re
import threading
import time
from urllib.parse import urlsplit

import config as C
from src import storage as DB

CACHE = C.DATA_RAW / 'paises_peleadores.json'
EVENTOS = C.DATA_RAW / 'ufc_oficial.json'
BIO = C.DATA_PROCESSED / 'ufcstats_bio.csv'
ISO2 = set(('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ '
    'CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR '
    'GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP '
    'KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS '
    'MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS '
    'RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW '
    'TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW').split())
NACIONES_GB = {'EN': 'Inglaterra', 'SC': 'Escocia', 'WA': 'Gales'}
NOMBRES_ES = {
    'England': 'Inglaterra', 'Scotland': 'Escocia', 'Wales': 'Gales', 'Northern Ireland': 'Irlanda del Norte',
    'United Kingdom': 'Reino Unido', 'Palestine': 'Palestina', 'United States': 'Estados Unidos',
    'Brazil': 'Brasil', 'Russia': 'Rusia', 'Mexico': 'México', 'France': 'Francia', 'Canada': 'Canadá',
    'Japan': 'Japón', 'New Zealand': 'Nueva Zelanda', 'Poland': 'Polonia', 'Germany': 'Alemania',
    'Spain': 'España', 'Ireland': 'Irlanda', 'Kyrgyzstan': 'Kirguistán', 'Kazakhstan': 'Kazajistán',
    'Uzbekistan': 'Uzbekistán', 'Tajikistan': 'Tayikistán', 'Azerbaijan': 'Azerbaiyán', 'Ukraine': 'Ucrania',
    'Czech Republic': 'Chequia', 'Czechia': 'Chequia', 'Croatia': 'Croacia', 'Moldova': 'Moldavia',
    'South Africa': 'Sudáfrica', 'Morocco': 'Marruecos', 'Iraq': 'Irak', 'United Arab Emirates': 'Emiratos Árabes Unidos',
    'Dominican Republic': 'República Dominicana', 'Panama': 'Panamá', 'Peru': 'Perú', 'Turkey': 'Turquía',
    'Türkiye': 'Turquía', 'Sweden': 'Suecia', 'Netherlands': 'Países Bajos', 'Italy': 'Italia',
    'Belgium': 'Bélgica', 'Switzerland': 'Suiza', 'Norway': 'Noruega', 'Denmark': 'Dinamarca',
    'Philippines': 'Filipinas', 'South Korea': 'Corea del Sur', 'Cameroon': 'Camerún', 'Afghanistan': 'Afganistán',
}
_lock = threading.RLock()
_firma = None
_datos = None
_comprobado = 0.0


def _invalidar():
    global _firma, _comprobado
    _firma, _comprobado = None, 0.0


def _ufc(url):
    """La misma ficha en ufc.com y ufcespanol.com tiene una sola identidad."""
    p = urlsplit(str(url or ''))
    if p.scheme != 'https' or p.hostname not in ('ufc.com', 'www.ufc.com', 'ufcespanol.com', 'www.ufcespanol.com'):
        return None
    if not re.fullmatch(r'/athlete/[a-z0-9-]+/?', p.path):
        return None
    return 'https://www.ufc.com' + p.path.rstrip('/')


def _documento():
    if DB.exists(CACHE):
        d = DB.read_json(CACHE)
        if isinstance(d, dict):
            return d
    return {'version': 1, 'atletas': {}, 'vinculos': {}}


def _registros(eventos):
    for evento in eventos:
        fuente = str(evento.get('url', ''))
        p = urlsplit(fuente)
        if p.scheme != 'https' or p.hostname not in ('ufc.com', 'www.ufc.com', 'ufcespanol.com', 'www.ufcespanol.com'):
            continue
        for pelea in evento.get('peleas', []):
            for lado in ('a', 'b'):
                pais = pelea.get('pais_' + lado)
                identidad = _ufc(pelea.get('perfil_' + lado))
                if not identidad or not isinstance(pais, dict) or pais.get('codigo') not in ISO2 or not pais.get('nombre'):
                    continue
                registro = {'codigo': pais['codigo'], 'nombre': pais['nombre'],
                    'fuente': fuente, 'identidad': identidad, 'atleta': pelea[lado]}
                if pais.get('bandera') in ('EN', 'SC', 'WA') and pais['codigo'] == 'GB':
                    registro['bandera'] = pais['bandera']
                yield identidad, registro


def guardar_eventos(eventos, sobrescribir=True):
    """Conserva países identificados al importar/refrescar un evento conocido.

    No realiza peticiones y no altera el archivo original de la importación.
    sobrescribir=False sirve al completar desde carteleras antiguas: se recorren
    de la más nueva a la más vieja, así que la primera bandera que aparece es la
    más reciente que UFC le atribuye y una pelea de 2019 no la pisa.
    """
    with _lock:
        d = _documento()
        atletas = d.setdefault('atletas', {})
        for identidad, registro in _registros(eventos):
            if sobrescribir or identidad not in atletas:
                atletas[identidad] = registro
        DB.write_text(CACHE, json.dumps(d, ensure_ascii=False), encoding='utf-8')
        _invalidar()


def consultas_ufc():
    """Páginas de ufc.com ya consultadas para completar países (descarga incremental)."""
    c = _documento().get('consultas_ufc', {})
    return {'atletas': dict(c.get('atletas', {})), 'eventos': dict(c.get('eventos', {}))}


def anotar_consulta(tipo, url, datos):
    """Deja constancia de una página consultada para no volver a pedirla."""
    if tipo not in ('atletas', 'eventos'):
        raise ValueError('Tipo de consulta no válido.')
    with _lock:
        d = _documento()
        d.setdefault('consultas_ufc', {}).setdefault(tipo, {})[url] = datos
        DB.write_text(CACHE, json.dumps(d, ensure_ascii=False), encoding='utf-8')
        _invalidar()


def asociar(ufcstats_id, perfil_ufc):
    """Vínculo manual comprobado de una ficha concreta, necesario con homónimos."""
    identidad = _ufc(perfil_ufc)
    if not re.fullmatch(r'[a-f0-9]{16}', str(ufcstats_id)) or not identidad:
        raise ValueError('Identidades de atleta no válidas.')
    if ufcstats_id not in _leer()[3]:
        raise ValueError('No existe esa ficha individual en BIO.')
    with _lock:
        d = _documento()
        d.setdefault('vinculos', {})[ufcstats_id] = identidad
        DB.write_text(CACHE, json.dumps(d, ensure_ascii=False), encoding='utf-8')
        _invalidar()


def identidad_ufc(ufcstats_id):
    """Vínculo individual comprobado, aunque la nacionalidad aún no se conozca."""
    _, _, vinculos, fichas, _, _ = _leer()
    return _ufc(vinculos.get(ufcstats_id)) if ufcstats_id in fichas else None


def guardar_ficha(ufcstats_id, nombre, codigo, nombre_pais, fuente, evidencia):
    """País verificado manualmente por ficha en Wikidata (P27, datos CC0).

    La evidencia conserva identificadores y comprobaciones concretas; esta
    función no busca candidatos ni asocia nombres compartidos por sí sola.
    """
    if not re.fullmatch(r'[a-f0-9]{16}', str(ufcstats_id)) or codigo not in ISO2:
        raise ValueError('Ficha o país no válido.')
    if not re.fullmatch(r'https://www.wikidata.org/wiki/Q[1-9][0-9]*', fuente):
        raise ValueError('Fuente Wikidata no válida.')
    if _leer()[3].get(ufcstats_id) != nombre:
        raise ValueError('El nombre no coincide exactamente con esa ficha BIO.')
    with _lock:
        d = _documento()
        d.setdefault('fichas', {})[ufcstats_id] = {
            'codigo': codigo, 'nombre': nombre_pais, 'atleta': nombre,
            'fuente': fuente, 'identidad': 'http://ufcstats.com/fighter-details/' + ufcstats_id,
            'evidencia': evidencia}
        DB.write_text(CACHE, json.dumps(d, ensure_ascii=False), encoding='utf-8')
        _invalidar()


def _leer():
    global _firma, _datos, _comprobado
    paths = (CACHE, EVENTOS, BIO)
    with _lock:
        base, ahora = str(DB.db_path()), time.monotonic()
        # Una lista de cuarenta fichas no necesita abrir SQLite tres veces por
        # cada fila. Las escrituras propias invalidan inmediatamente; cambios
        # de otro proceso se comprueban de nuevo dentro de 250 milisegundos.
        if _firma is not None and _firma[0] == base and ahora - _comprobado < .25:
            return _datos
        firma = (base, tuple(DB.stat(p).st_mtime_ns if DB.exists(p) else None for p in paths))
        _comprobado = ahora
        if firma == _firma:
            return _datos
        d = _documento()
        atletas = dict(d.get('atletas', {}))
        if DB.exists(EVENTOS):
            eventos = DB.read_json(EVENTOS).get('eventos', {})
            atletas.update(dict(_registros(eventos.get('recientes', []) + eventos.get('proximos', []))))
        for id_stats, perfil in d.get('vinculos', {}).items():
            url_ufc = _ufc(perfil)
            pais = d.get('fichas', {}).get(id_stats)
            if url_ufc and pais and pais.get('codigo') in ISO2 and url_ufc not in atletas:
                atletas[url_ufc] = {**pais, 'identidad': url_ufc, 'ficha_ufcstats': id_stats}
        por_nombre = {}
        for identidad, pais in atletas.items():
            if _ufc(identidad) == identidad and pais.get('codigo') in ISO2:
                por_nombre.setdefault(pais.get('atleta'), []).append(pais)
        bio = DB.read_csv(BIO) if DB.exists(BIO) else None
        fichas = {}
        if bio is not None:
            for fila in bio.to_dict('records'):
                m = re.fullmatch(r'https?://ufcstats.com/fighter-details/([a-f0-9]{16})', str(fila.get('fighter_url')))
                if m:
                    fichas[m[1]] = fila.get('name')
        _datos = atletas, por_nombre, d.get('vinculos', {}), fichas, Counter(fichas.values()), d.get('fichas', {})
        _firma = firma
        return _datos


def lookup(nombre, identidad=None):
    """País comprobado o None; identidad acepta URL UFC, URL UFCStats o su ID.

    La unión por nombre es exacta y sólo sirve para nombres no compartidos.
    No se consulta la red, ni se toma el primer candidato del buscador.
    """
    atletas, por_nombre, vinculos, fichas, cuenta, paises_fichas = _leer()
    if identidad:
        url_ufc = _ufc(identidad)
        if url_ufc:
            p = atletas.get(url_ufc)
            return dict(p) if p and p.get('atleta') == nombre else None
        id_stats = re.sub(r'^https?://ufcstats.com/fighter-details/', '', str(identidad))
        if fichas.get(id_stats) != nombre:
            return None
        directo = paises_fichas.get(id_stats)
        if directo and directo.get('atleta') == nombre and directo.get('codigo') in ISO2:
            return dict(directo)
        if id_stats in vinculos:
            p = atletas.get(vinculos[id_stats])
            return dict(p) if p and p.get('atleta') == nombre else None
    if cuenta.get(nombre, 0) > 1:
        return None
    candidatos = por_nombre.get(nombre, [])
    return dict(candidatos[0]) if len(candidatos) == 1 else None


def pais_perfil(nombre, perfil_ufc):
    """País por la URL de la ficha UFC: la URL es la identidad, no el nombre.

    El nombre sólo se usa como control, normalizado (tildes, apóstrofes y
    mayúsculas) y luego exacto: UFC a veces enlaza una esquina a la ficha de
    otra persona (en UFC 330 «Chidi Njokuani» apunta a /athlete/bruno-korea-0),
    y ahí es mejor quedarse sin bandera que ponerle la de otro. A diferencia
    de lookup(), no exige el literal idéntico: el ranking y la cartelera son
    dos páginas de UFC que a veces escriben distinto el mismo apóstrofe.
    """
    from src.fighter_names import normalize_name
    url = _ufc(perfil_ufc)
    if not url or not isinstance(nombre, str) or not nombre:
        return None
    p = _leer()[0].get(url)
    if not p or p.get('codigo') not in ISO2 or not isinstance(p.get('atleta'), str):
        return None
    return dict(p) if normalize_name(p['atleta']) == normalize_name(nombre) else None


def contrato(pais):
    """Forma pública del país (docs/contrato-datos.md, sección 1), o None.

    bandera es lo que se pide a /api/bandera: el ISO2 o EN/SC/WA, que UFC usa
    para Inglaterra, Escocia y Gales mientras el código ISO sigue siendo GB.
    Un nombre vacío o NaN (que es truthy) no llega a la UI: se cae al código.
    """
    if not isinstance(pais, dict) or pais.get('codigo') not in ISO2:
        return None
    nombre = pais.get('nombre')
    if not isinstance(nombre, str) or not nombre.strip():
        nombre = pais['codigo']
    bandera = pais.get('bandera')
    if not (pais['codigo'] == 'GB' and bandera in ('EN', 'SC', 'WA')):
        bandera = pais['codigo']
    # ufcespanol.com deja algunos países sin traducir («England», «Palestine»)
    # y www.ufc.com los da todos en inglés. El contrato pide español.
    nombre = NACIONES_GB.get(bandera) or NOMBRES_ES.get(nombre.strip(), nombre)
    fuente = pais.get('fuente')
    return {'codigo': pais['codigo'], 'nombre': nombre.strip(), 'bandera': bandera,
            'fuente': fuente if isinstance(fuente, str) else None}
