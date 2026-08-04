"""
engine.py
Puente entre la UI y el motor que ya existe.

Regla de este archivo: **no re-implementar nada**. La predicción la sigue
haciendo `card.predict_card()` — la misma función que usa la consola, con el
mismo bucle, las mismas features y los mismos avisos. Acá solo se la invoca en
un hilo aparte y se traduce su salida a JSON.

Si algún día la UI y la consola dieran números distintos, sería un bug de este
archivo, no un modelo alternativo: no hay modelo alternativo.
"""
from __future__ import annotations

import io
import contextlib
import re
import sys
import threading
import time
import unicodedata
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as C                                    # noqa: E402
from webui import parlay as P                          # noqa: E402

CARDS_DIR = C.ROOT / "cards"
INTERVALO_AUTO_SEG = 600        # 10 minutos, lo que pidió el usuario


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "cartelera"


# --------------------------------------------------------------------------- #
# Estado compartido
# --------------------------------------------------------------------------- #
class Estado:
    """
    Todo lo que la UI necesita saber de la cartelera activa. Un solo objeto,
    protegido por un lock, porque lo tocan tres hilos: el que responde HTTP, el
    que predice y el del auto-refresh de cuotas.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cargando = False
        self.progreso = ""
        self.error = ""
        self.log: list[str] = []

        self.origen = ""          # "betano" | "csv"
        self.consulta = ""        # query de Betano o nombre del archivo
        self.csv_path: Path | None = None
        self.titulo = ""

        self.predicho_en: float | None = None
        self.cuotas_en: float | None = None
        self.datos: dict | None = None      # payload JSON de la cartelera
        self.patas: list[P.Pata] = []

        # Movimiento de línea: {clave_pata: {"antes": x, "ahora": y}}
        self.movimiento: dict[str, dict] = {}
        self._cuotas_previas: dict[str, float] = {}

        self.auto = True
        self.proximo_auto: float | None = None

    # -- lectura para la UI ------------------------------------------------ #
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "cargando": self.cargando,
                "progreso": self.progreso,
                "error": self.error,
                "log": self.log[-40:],
                "origen": self.origen,
                "consulta": self.consulta,
                "titulo": self.titulo,
                "csv": self.csv_path.name if self.csv_path else "",
                "predicho_en": self.predicho_en,
                "cuotas_en": self.cuotas_en,
                "auto": self.auto,
                "proximo_auto": self.proximo_auto,
                "intervalo_seg": INTERVALO_AUTO_SEG,
                "movimiento": self.movimiento,
                "datos": self.datos,
            }

    def _log(self, txt: str) -> None:
        self.log.append(txt)
        self.progreso = txt


ESTADO = Estado()


# --------------------------------------------------------------------------- #
# Serialización
# --------------------------------------------------------------------------- #
def _num(x):
    """Convierte a float o devuelve None. Los CSV traen '' y NaN sueltos."""
    try:
        f = float(x)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _txt(x) -> str:
    """
    Texto seguro para JSON. OJO con el atajo `x or ""`: pandas lee una celda
    vacía como NaN y **NaN es truthy en Python**, así que `nan or ""` devuelve
    nan, no "". Eso metía un NaN en `segmento` y tumbaba la respuesta entera
    con "Out of range float values are not JSON compliant" — la UI quedaba en
    blanco con cualquier CSV del scraper de Betano, que deja `segment` vacío.
    """
    if x is None:
        return ""
    if isinstance(x, float) and x != x:
        return ""
    return str(x)


def _serializar(res: dict, csv_path: Path) -> tuple[dict, list[P.Pata]]:
    """Traduce la salida de predict_card(devolver_todo=True) a JSON plano."""
    rows = res["rows"]
    consenso = res["consenso"]

    peleas = []
    for i, c in enumerate(consenso):
        sim = c["sim"]
        v = c.get("v")
        fila = next((r for r in rows if r["A"] == c["a"] and r["B"] == c["b"]), {})
        pelea = {
            "id": str(i),
            "a": c["a"], "b": c["b"],
            "segmento": _txt(fila.get("segmento")),
            "ganador": sim.winner,
            "p_a": sim.p_a, "p_b": sim.p_b,
            "ci_a": list(sim.ci_a),
            "metodo": sim.method_dist,
            "p_finish": sim.p_finish,
            "pocos": c.get("pocos") or [],
            "aviso": _txt(fila.get("aviso")),
            "fuente": _txt(fila.get("fuente")),
            "corto_a": fila.get("corto_a", 0), "corto_b": fila.get("corto_b", 0),
            "p_sin_corto_a": _num(fila.get("p_sin_corto_A")),
            "p_con_corto_a": _num(fila.get("p_con_corto_A")),
            "tendencia": _tendencia(sim.method_dist),
            "confianza": _confianza(max(sim.p_a, sim.p_b), c.get("pocos") or []),
            "info_a": c.get("info_a", {}), "info_b": c.get("info_b", {}),
            "por_que_confianza": _por_que_confianza(
                max(sim.p_a, sim.p_b), c.get("pocos") or [],
                {c["a"]: c.get("info_a", {}), c["b"]: c.get("info_b", {})}),
        }
        if v is not None:
            # TODO numérico pasa por _num(): value.analizar() devuelve NaN cuando
            # la pelea no trae cuotas, y un NaN suelto rompe la respuesta entera
            # con "Out of range float values are not JSON compliant" — o sea que
            # una sola pelea sin cuotas dejaba la UI en blanco.
            pelea["mercado"] = {
                "cuota_a": _num(fila.get("cuota_a")), "cuota_b": _num(fila.get("cuota_b")),
                "p_mercado_a": _num(v.p_mercado_a),
                "p_modelo_a": _num(v.p_modelo_a),
                "p_final_a": _num(v.p_final_a),
                "disc": _num(v.discrepancia), "disc_cruda": _num(v.discrepancia_cruda),
                "vig": _num(v.vig),
                "lado": v.lado, "cuota": _num(v.cuota_decimal),
                "ev": _num(v.ev), "kelly": _num(v.kelly), "veredicto": v.veredicto,
            }
        if c.get("metodo6"):
            pelea["metodo6"] = [
                {k: (_num(o[k]) if k in ("p_modelo", "p_mercado", "p_final",
                                         "cuota_decimal", "ev", "kelly", "sobrerredondeo")
                     else o[k])
                 for k in o}
                for o in c["metodo6"] if "error" not in o
            ]
        peleas.append(pelea)

    patas = P.patas_de_cartelera(consenso)
    datos = {
        "titulo": csv_path.stem,
        "peleas": peleas,
        "patas": [p.dict() for p in patas],
        "sugerencia": P.sugerir(patas),
        "missing": res.get("missing", []),
        "con_cuotas": res.get("con_cuotas", False),
        "con_metodo": res.get("con_metodo", False),
        "calibrador": res.get("calibrador", False),
        "modelo_real": res.get("modelo_real", True),
        "hay_corto": res.get("hay_corto", False),
        "tiers": P.TIERS,
        # Las secciones en que la interfaz agrupa las patas. Van desde acá y no
        # hardcodeadas en el JS para que agregar un mercado nuevo (rounds,
        # distancia…) sea tocar UN diccionario en parlay.py.
        "mercados": P.MERCADOS,
    }
    return datos, patas


def _tendencia(m: dict) -> str:
    """Lo mismo que muestra la consola: lift sobre la tasa base, no el argmax."""
    base = C.METHOD_BASE_RATES
    lifts = {k: (m.get(k, 0) / base[k]) for k in base if base[k] > 0}
    k, lift = max(lifts.items(), key=lambda kv: kv[1])
    if lift < 1.15:
        return "pelea promedio"
    corto = {"KO/TKO": "KO", "Submission": "Sub", "Decision": "Dec"}[k]
    return f"{corto} x{lift:.1f} vs base"


def _confianza(p: float, pocos: list) -> str:
    if pocos:
        return "NO FIABLE"
    if p >= 0.75:
        return "fuerte"
    if p >= 0.65:
        return "buena"
    if p >= 0.60:
        return "justa"
    return "moneda"


def _por_que_confianza(p: float, pocos: list, infos: dict) -> str:
    """
    La frase que explica la etiqueta. Existe porque "NO FIABLE" a secas no dice
    NADA: el usuario ve un 80% marcado en rojo y no sabe si el modelo se
    equivocó o si le falta un dato. Acá se nombra el motivo exacto.
    """
    if pocos:
        causas = []
        for nombre, i in infos.items():
            if not i:
                continue
            n = i.get("n_peleas_hist", 99)
            apellido = nombre.split()[-1]
            if n < 3:
                peleas = "ninguna pelea" if n == 0 else f"{n} pelea" + ("s" if n > 1 else "")
                extra = ""
                if i.get("sherdog"):
                    extra = (f" Fuera de UFC tiene récord {i.get('wins',0)}-{i.get('losses',0)}, "
                             f"pero de esas peleas no existen estadísticas de golpeo ni de "
                             f"lucha: eso solo se publica de UFC.")
                elif float(i.get("slpm") or 0) == 0:
                    extra = " Y su ficha no tiene ni una estadística de golpeo."
                causas.append(f"<b>{apellido}</b> tiene {peleas} en UFC.{extra}")
            elif float(i.get("slpm") or 0) == 0:
                causas.append(f"<b>{apellido}</b> tiene la ficha vacía: cero golpes registrados.")
        detalle = " ".join(causas) or "A algún peleador le faltan datos en UFCStats."
        return (f"{detalle} El modelo predice igual, pero ese "
                f"{p*100:.0f}% se apoya en muy poca información, así que "
                f"<b>no se apuesta</b> por más alto que se vea.")

    if p >= 0.75:
        return ("Favorito claro. En las peleas donde el sistema dice 75% o más, acertó "
                "cerca del 85% de las veces. Son pocas por cartelera.")
    if p >= 0.65:
        return ("Favorito sólido. Este tramo acertó ~73% de las veces. Es el mínimo "
                "desde el que tiene sentido apostar.")
    if p >= 0.60:
        return ("Favorito leve. Acertó ~70%, pero el margen es corto: conviene mirar "
                "también si la cuota paga lo suficiente.")
    return ("Pelea pareja. Por debajo de 60% el acierto real ronda el 50%, o sea "
            "una moneda al aire. Mejor ignorarla.")


# --------------------------------------------------------------------------- #
# Cuotas de Betano
# --------------------------------------------------------------------------- #
def listar_carteleras() -> list[dict]:
    from src import betano_scraper as bs
    return bs.list_cards()


def bajar_cuotas(query: str, destino: Path | None = None) -> tuple[Path, str]:
    """
    Baja las cuotas de una cartelera de Betano y las deja en un CSV.
    Devuelve (ruta, titulo). Reutiliza `scrape_card`, que ya resuelve el lío de
    los eventos mezclados bajo la misma liga "UFC Fight Night".
    """
    from src import betano_scraper as bs
    card = bs.find_card(query)
    titulo = card["name"] if card else query
    ruta = bs.scrape_card(query, str(destino) if destino else None)
    return Path(ruta), titulo


def _claves_cuotas(datos: dict) -> dict[str, float]:
    """Aplana las cuotas actuales para poder compararlas en el próximo refresh."""
    out: dict[str, float] = {}
    for pl in datos["peleas"]:
        m = pl.get("mercado") or {}
        for lado in ("a", "b"):
            c = m.get(f"cuota_{lado}")
            if c:
                out[f"{pl['id']}:ML:{lado.upper()}"] = c
        for op in pl.get("metodo6", []):
            out[f"{pl['id']}:MET:{op['clase']}"] = op["cuota_decimal"]
    return out


# --------------------------------------------------------------------------- #
# Predicción (en hilo aparte)
# --------------------------------------------------------------------------- #
def _predecir_sync(csv_path: Path) -> dict:
    """Corre predict_card capturando su stdout para poder mostrarlo en la UI."""
    from src.card import predict_card
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = predict_card(csv_path, reports=True, detalle=False, devolver_todo=True)
    salida = buf.getvalue()
    if not res or not res.get("rows"):
        raise RuntimeError(
            "No se pudo predecir ninguna pelea. Revisa los nombres del CSV.\n\n" + salida[-1500:])
    return res


def cargar(origen: str, consulta: str = "", csv_path: Path | None = None,
           refrescar_cuotas: bool = True) -> None:
    """
    Arranca la carga de una cartelera en segundo plano. La UI hace polling a
    /api/estado mientras tanto.
    """
    with ESTADO.lock:
        if ESTADO.cargando:
            return
        ESTADO.cargando = True
        ESTADO.error = ""
        ESTADO.log = []
        ESTADO.progreso = "empezando…"

    def _run() -> None:
        try:
            ruta = csv_path
            if origen == "betano":
                ESTADO._log(f"Bajando cuotas de Betano: {consulta}…")
                ruta, titulo = bajar_cuotas(consulta)
                with ESTADO.lock:
                    ESTADO.titulo = titulo
                    ESTADO.cuotas_en = time.time()
            elif refrescar_cuotas and ESTADO.origen == "betano" and ESTADO.consulta:
                pass

            if ruta is None:
                raise RuntimeError("No hay cartelera que cargar.")

            ESTADO._log(f"Prediciendo {ruta.name}… (la primera vez baja las fichas "
                        f"de cada peleador de UFCStats, puede tardar)")
            res = _predecir_sync(ruta)
            datos, patas = _serializar(res, ruta)

            with ESTADO.lock:
                # Movimiento de línea contra el snapshot anterior
                nuevas = _claves_cuotas(datos)
                mov = {}
                for k, ahora in nuevas.items():
                    antes = ESTADO._cuotas_previas.get(k)
                    if antes and abs(antes - ahora) > 1e-9:
                        mov[k] = {"antes": antes, "ahora": ahora}
                ESTADO.movimiento = mov
                ESTADO._cuotas_previas = nuevas

                ESTADO.origen = origen or ESTADO.origen
                ESTADO.consulta = consulta or ESTADO.consulta
                ESTADO.csv_path = ruta
                ESTADO.titulo = ESTADO.titulo or ruta.stem
                ESTADO.datos = datos
                ESTADO.patas = patas
                ESTADO.predicho_en = time.time()
                if origen == "csv":
                    ESTADO.cuotas_en = None
                ESTADO.progreso = f"{len(datos['peleas'])} peleas listas"
                if mov:
                    ESTADO.log.append(f"[i] {len(mov)} cuotas se movieron desde el refresh anterior")
        except Exception as e:                       # noqa: BLE001
            with ESTADO.lock:
                ESTADO.error = str(e)
                ESTADO.progreso = "falló"
        finally:
            with ESTADO.lock:
                ESTADO.cargando = False
                ESTADO.proximo_auto = (time.time() + INTERVALO_AUTO_SEG) if ESTADO.auto else None

    threading.Thread(target=_run, daemon=True).start()


def refrescar() -> str:
    """Refresh manual: vuelve a bajar cuotas (si el origen es Betano) y repredice."""
    with ESTADO.lock:
        if ESTADO.cargando:
            return "Ya hay una carga en curso."
        origen, consulta, ruta = ESTADO.origen, ESTADO.consulta, ESTADO.csv_path
    if not origen:
        return "No hay ninguna cartelera cargada todavía."
    cargar(origen, consulta, ruta)
    return ""


# --------------------------------------------------------------------------- #
# Auto-refresh cada 10 minutos
# --------------------------------------------------------------------------- #
def _bucle_auto() -> None:
    """
    Solo refresca la cartelera ACTIVA, no todo Betano: son ~22 peticiones con
    1,5 s de pausa entre medio (config.REQUEST_DELAY_SEC). Cada 10 minutos eso
    es scraping educado; barrer el sitio entero no lo sería.
    """
    while True:
        time.sleep(15)
        with ESTADO.lock:
            listo = (ESTADO.auto and not ESTADO.cargando and ESTADO.origen == "betano"
                     and ESTADO.proximo_auto and time.time() >= ESTADO.proximo_auto)
        if listo:
            refrescar()


def arrancar_auto() -> None:
    threading.Thread(target=_bucle_auto, daemon=True).start()
