"""Persistencia de la capa de cuotas en SQLite (la misma base que src/storage).

Tablas propias, todas con prefijo `cuotas_`:

- `cuotas_historial`: una fila por fuente × casa × pelea cada vez que la cuota
  CAMBIA. Una cuota que sigue igual no agrega fila: actualiza `visto` de la
  última, así el gráfico sabe hasta cuándo siguió vigente sin inflar la tabla
  (Polymarket se consulta cada 30 s durante un evento).
- `cuotas_peleas`: los datos de cada pelea consolidada (nombres de la base,
  evento, fecha), para que los endpoints no tengan que volver a cruzar nombres.
- `cuotas_no_calzados`: los nombres que no calzaron exacto con la base. Se
  registran en vez de descartarse en silencio (los dos bugs más caros del
  proyecto fueron cruces de nombres).
- `cuotas_cache`: estado chico de cada fuente que tiene que sobrevivir a un
  reinicio (créditos y última llamada de The Odds API, mercados descubiertos
  de Polymarket). Sin esto, reiniciar la UI gastaría créditos de nuevo.

Los endpoints leen de acá y nunca esperan a la red.
"""
from __future__ import annotations

import json
import threading

from src import storage as DB
from src.cuotas.tiempo import a_epoch, ahora_iso

_lock = threading.RLock()


def _tablas(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS cuotas_historial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pelea_id TEXT NOT NULL, fuente TEXT NOT NULL, tipo TEXT NOT NULL,
        casa TEXT NOT NULL, timestamp TEXT NOT NULL, visto TEXT NOT NULL,
        a_americana INTEGER NOT NULL, b_americana INTEGER NOT NULL,
        a_prob REAL NOT NULL, b_prob REAL NOT NULL,
        pa REAL NOT NULL, pb REAL NOT NULL,
        contenido TEXT NOT NULL)""")
    # Única por instante: reimportar el historial remoto de Polymarket no duplica.
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS cuotas_historial_serie
        ON cuotas_historial(pelea_id, fuente, casa, timestamp)""")
    con.execute("CREATE INDEX IF NOT EXISTS cuotas_historial_visto ON cuotas_historial(visto)")
    con.execute("""CREATE TABLE IF NOT EXISTS cuotas_peleas (
        pelea_id TEXT PRIMARY KEY, a TEXT NOT NULL, b TEXT NOT NULL,
        a_id TEXT, b_id TEXT, evento TEXT, fecha TEXT, inicio TEXT,
        oficial INTEGER NOT NULL DEFAULT 0, actualizado TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS cuotas_no_calzados (
        fuente TEXT NOT NULL, texto TEXT NOT NULL, motivo TEXT NOT NULL,
        evento TEXT, primera_vez TEXT NOT NULL, ultima_vez TEXT NOT NULL,
        veces INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(fuente, texto, motivo))""")
    con.execute("""CREATE TABLE IF NOT EXISTS cuotas_cache (
        clave TEXT PRIMARY KEY, contenido TEXT NOT NULL, actualizado TEXT NOT NULL)""")


class _con:
    """Conexión de src/storage con las tablas de la capa aseguradas.

    CREATE TABLE IF NOT EXISTS en cada conexión cuesta microsegundos y evita
    recordar qué base ya se preparó (los tests cambian UFC_DB a cada rato).
    """
    def __enter__(self):
        self._ctx = DB.connect()
        con = self._ctx.__enter__()
        _tablas(con)
        return con

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


# --------------------------------------------------------------------------- #
# Historial de cotizaciones
# --------------------------------------------------------------------------- #
def guardar(cot: dict) -> bool:
    """Guarda una Cotización 2.2. True si agregó fila, False si era igual a la última.

    "Igual" compara las cuotas Y la probabilidad implícita: en Polymarket dos
    precios distintos (0,652 y 0,655) pueden redondear a la misma americana.
    """
    fila = (cot["a"]["americana"], cot["b"]["americana"],
            round(cot["a"]["prob_implicita"], 4), round(cot["b"]["prob_implicita"], 4))
    with _lock, _con() as con:
        ultima = con.execute(
            """SELECT id, a_americana, b_americana, a_prob, b_prob, timestamp, visto
               FROM cuotas_historial WHERE pelea_id=? AND fuente=? AND casa=?
               ORDER BY timestamp DESC LIMIT 1""",
            (cot["pelea_id"], cot["fuente"], cot["casa"])).fetchone()
        if ultima and (ultima[1], ultima[2], round(ultima[3], 4), round(ultima[4], 4)) == fila:
            # Misma cuota: solo se extiende su vigencia (nunca hacia atrás: BFO
            # reentrega la misma captura con su hora original).
            if cot["timestamp"] > ultima[6]:
                con.execute("UPDATE cuotas_historial SET visto=? WHERE id=?", (cot["timestamp"], ultima[0]))
            return False
        if ultima and cot["timestamp"] <= ultima[5]:
            # Una captura más vieja que la última guardada no reescribe el presente.
            return False
        con.execute(
            """INSERT OR IGNORE INTO cuotas_historial
               (pelea_id, fuente, tipo, casa, timestamp, visto, a_americana, b_americana,
                a_prob, b_prob, pa, pb, contenido) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cot["pelea_id"], cot["fuente"], cot["tipo"], cot["casa"], cot["timestamp"],
             cot["timestamp"], *fila, cot["prob_sin_margen"]["a"], cot["prob_sin_margen"]["b"],
             json.dumps(cot, ensure_ascii=False, allow_nan=False)))
        return True


def importar_serie(cots: list[dict]) -> int:
    """Puntos de un historial remoto (Polymarket /prices-history), ya validados.

    Se insertan tal cual con su propio instante (INSERT OR IGNORE por la clave
    única), saltando los consecutivos idénticos para no inflar la tabla.
    """
    n = 0
    previo = None
    with _lock, _con() as con:
        for cot in sorted(cots, key=lambda c: c["timestamp"]):
            clave = (cot["a"]["americana"], round(cot["a"]["prob_implicita"], 4))
            if clave == previo:
                continue
            previo = clave
            cur = con.execute(
                """INSERT OR IGNORE INTO cuotas_historial
                   (pelea_id, fuente, tipo, casa, timestamp, visto, a_americana, b_americana,
                    a_prob, b_prob, pa, pb, contenido) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cot["pelea_id"], cot["fuente"], cot["tipo"], cot["casa"], cot["timestamp"],
                 cot["timestamp"], cot["a"]["americana"], cot["b"]["americana"],
                 round(cot["a"]["prob_implicita"], 4), round(cot["b"]["prob_implicita"], 4),
                 cot["prob_sin_margen"]["a"], cot["prob_sin_margen"]["b"],
                 json.dumps(cot, ensure_ascii=False, allow_nan=False)))
            n += cur.rowcount
    return n


def ultimas(desde_visto: str, excluir: tuple[str, ...] = ()) -> list[dict]:
    """La última cotización de cada fuente × casa × pelea vista desde `desde_visto`."""
    marcas = ",".join("?" for _ in excluir) or "''"
    with _con() as con:
        filas = con.execute(
            f"""SELECT h.contenido, h.visto FROM cuotas_historial h
                JOIN (SELECT pelea_id, fuente, casa, MAX(timestamp) AS ts
                      FROM cuotas_historial WHERE fuente NOT IN ({marcas})
                      GROUP BY pelea_id, fuente, casa) u
                  ON h.pelea_id=u.pelea_id AND h.fuente=u.fuente AND h.casa=u.casa AND h.timestamp=u.ts
                WHERE h.visto >= ?""", (*excluir, desde_visto)).fetchall()
    salida = []
    for contenido, visto in filas:
        c = json.loads(contenido)
        c["visto"] = visto
        salida.append(c)
    return salida


def serie(pelea_id: str, desde: str | None = None, excluir: tuple[str, ...] = (),
          limite: int = 20000) -> list[tuple]:
    """(fuente, casa, tipo, timestamp, a, b, pa, pb) en orden cronológico."""
    marcas = ",".join("?" for _ in excluir) or "''"
    with _con() as con:
        filas = con.execute(
            f"""SELECT fuente, casa, tipo, timestamp, a_americana, b_americana, pa, pb
                FROM cuotas_historial WHERE pelea_id=? AND timestamp >= ? AND fuente NOT IN ({marcas})
                ORDER BY timestamp DESC LIMIT ?""",
            (pelea_id, desde or "", *excluir, limite)).fetchall()
    return list(reversed(filas))


def borrar_fuente(fuente: str) -> None:
    with _lock, _con() as con:
        con.execute("DELETE FROM cuotas_historial WHERE fuente=?", (fuente,))


# --------------------------------------------------------------------------- #
# Peleas consolidadas
# --------------------------------------------------------------------------- #
def guardar_pelea(pelea_id: str, a: str, b: str, a_id, b_id, evento, fecha, inicio,
                  oficial: bool) -> None:
    """Lo oficial (cartelera de UFC.com) pisa lo que diga cada fuente; si no,
    se conserva lo primero que se supo y se completan los huecos."""
    with _lock, _con() as con:
        con.execute(
            """INSERT INTO cuotas_peleas (pelea_id, a, b, a_id, b_id, evento, fecha, inicio, oficial, actualizado)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(pelea_id) DO UPDATE SET
                 a=excluded.a, b=excluded.b,
                 a_id=COALESCE(excluded.a_id, cuotas_peleas.a_id),
                 b_id=COALESCE(excluded.b_id, cuotas_peleas.b_id),
                 evento=CASE WHEN excluded.oficial=1 OR cuotas_peleas.evento IS NULL
                             THEN COALESCE(excluded.evento, cuotas_peleas.evento) ELSE cuotas_peleas.evento END,
                 fecha=CASE WHEN excluded.oficial=1 OR cuotas_peleas.fecha IS NULL
                            THEN COALESCE(excluded.fecha, cuotas_peleas.fecha) ELSE cuotas_peleas.fecha END,
                 inicio=COALESCE(excluded.inicio, cuotas_peleas.inicio),
                 oficial=MAX(excluded.oficial, cuotas_peleas.oficial),
                 actualizado=excluded.actualizado""",
            (pelea_id, a, b, a_id, b_id, evento, fecha, inicio, int(bool(oficial)), ahora_iso()))


def peleas(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    salida = {}
    with _con() as con:
        for i in range(0, len(ids), 500):
            lote = ids[i:i + 500]
            for r in con.execute(
                    f"""SELECT pelea_id, a, b, a_id, b_id, evento, fecha, inicio, oficial
                        FROM cuotas_peleas WHERE pelea_id IN ({",".join("?" for _ in lote)})""", lote):
                salida[r[0]] = {"pelea_id": r[0], "a": r[1], "b": r[2], "a_id": r[3], "b_id": r[4],
                                "evento": r[5], "fecha": r[6], "inicio": r[7], "oficial": bool(r[8])}
    return salida


# --------------------------------------------------------------------------- #
# Nombres que no calzaron
# --------------------------------------------------------------------------- #
def registrar_no_calzado(fuente: str, texto: str, motivo: str, evento: str | None = None) -> None:
    ahora = ahora_iso()
    with _lock, _con() as con:
        con.execute(
            """INSERT INTO cuotas_no_calzados (fuente, texto, motivo, evento, primera_vez, ultima_vez, veces)
               VALUES (?,?,?,?,?,?,1)
               ON CONFLICT(fuente, texto, motivo) DO UPDATE SET
                 ultima_vez=excluded.ultima_vez, veces=cuotas_no_calzados.veces+1,
                 evento=COALESCE(excluded.evento, cuotas_no_calzados.evento)""",
            (fuente, texto, motivo, evento, ahora, ahora))


def resumen_no_calzados(limite: int = 30, excluir: tuple[str, ...] = ()) -> dict:
    marcas = ",".join("?" for _ in excluir) or "''"
    with _con() as con:
        total = con.execute(f"SELECT COUNT(*) FROM cuotas_no_calzados WHERE fuente NOT IN ({marcas})",
                            excluir).fetchone()[0]
        por_motivo = dict(con.execute(
            f"SELECT motivo, COUNT(*) FROM cuotas_no_calzados WHERE fuente NOT IN ({marcas}) GROUP BY motivo",
            excluir).fetchall())
        filas = con.execute(
            f"""SELECT fuente, texto, motivo, evento, primera_vez, ultima_vez, veces
                FROM cuotas_no_calzados WHERE fuente NOT IN ({marcas})
                ORDER BY ultima_vez DESC, texto LIMIT ?""", (*excluir, limite)).fetchall()
    return {"total": total, "por_motivo": por_motivo,
            "recientes": [{"fuente": f, "texto": t, "motivo": m, "evento": e,
                           "primera_vez": p, "ultima_vez": u, "veces": v}
                          for f, t, m, e, p, u, v in filas]}


def borrar_no_calzados(fuente: str) -> None:
    with _lock, _con() as con:
        con.execute("DELETE FROM cuotas_no_calzados WHERE fuente=?", (fuente,))


# --------------------------------------------------------------------------- #
# Caché chica de cada fuente
# --------------------------------------------------------------------------- #
def leer_cache(clave: str) -> dict | None:
    with _con() as con:
        r = con.execute("SELECT contenido FROM cuotas_cache WHERE clave=?", (clave,)).fetchone()
    try:
        return json.loads(r[0]) if r else None
    except ValueError:
        return None


def escribir_cache(clave: str, contenido: dict) -> None:
    with _lock, _con() as con:
        con.execute("""INSERT INTO cuotas_cache (clave, contenido, actualizado) VALUES (?,?,?)
                       ON CONFLICT(clave) DO UPDATE SET contenido=excluded.contenido,
                       actualizado=excluded.actualizado""",
                    (clave, json.dumps(contenido, ensure_ascii=False, allow_nan=False), ahora_iso()))


def antiguedad(iso: str | None, ahora: float) -> float:
    """Segundos desde un timestamp ISO; infinito si no hay."""
    return float("inf") if not iso else ahora - a_epoch(iso)
