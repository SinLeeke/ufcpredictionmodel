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
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as C
from src import storage as DB                                    # noqa: E402
from webui import parlay as P                          # noqa: E402

CARDS_DIR = C.ROOT / "cards"
# Dos ritmos distintos, y la diferencia importa:
#
#   COMPLETO  -> vuelve a bajar TODO (cuotas de método incluidas, que necesitan
#                una petición por pelea) y RE-PREDICE. Son 1+N peticiones y
#                varios segundos de modelo. Va espaciado.
#   EN VIVO   -> UNA sola petición a la página de la cartelera, que ya trae el
#                mercado de ganador de todas las peleas. No re-predice: la
#                probabilidad del MODELO no cambia porque se mueva la cuota,
#                solo cambian la mezcla con el mercado y el EV, que se
#                recalculan en memoria. Por eso puede ir a segundos.
INTERVALO_AUTO_SEG = 600        # refresco COMPLETO
INTERVALO_VIVO_SEG = 10         # refresco de la LÍNEA de ganador


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "cartelera"


# --------------------------------------------------------------------------- #
# Estado compartido
# --------------------------------------------------------------------------- #
class ProgresoCarga:
    """Métricas de una carga, leídas/escritas bajo Estado.lock.

    Porcentaje y tiempo restante son de la etapa actual. La estimación usa
    únicamente el tiempo real de unidades terminadas de esa misma etapa; no
    extrapola el tiempo de bajar cuotas al de consultar fichas. 100% queda
    reservado para cuando la cartelera ya se serializó y publicó.
    """

    def __init__(self) -> None:
        self.estado = "inactiva"
        self.etapa = ""
        self.detalle = ""
        self.completadas = 0
        self.total: int | None = None
        self._inicio: float | None = None
        self._fin: float | None = None
        self._ultimo_avance: float | None = None
        self._ultima_unidad: float | None = None
        self._seg_unidades = 0.0
        self._unidades_medidas = 0

    def iniciar(self) -> None:
        ahora = time.monotonic()
        self.estado = "cargando"
        self._inicio = ahora
        self._ultimo_avance = ahora
        self.actualizar({"etapa": "preparando", "detalle": "Empezando la carga…"})

    def actualizar(self, avance: dict) -> None:
        ahora = time.monotonic()
        etapa = avance.get("etapa", self.etapa)
        detalle = avance.get("detalle", self.detalle)
        total = avance.get("total")
        total = max(0, int(total)) if total is not None else None
        completadas = max(0, int(avance.get("completadas", 0)))
        if total is not None:
            completadas = min(completadas, total)
        if etapa != self.etapa:
            self._ultima_unidad = ahora
            self._seg_unidades = 0.0
            self._unidades_medidas = 0
            self.completadas = 0
        if completadas > self.completadas:
            self._seg_unidades += max(0.0, ahora - self._ultima_unidad)
            self._unidades_medidas += completadas - self.completadas
            self._ultima_unidad = ahora
        if etapa != self.etapa or detalle != self.detalle or completadas != self.completadas:
            self._ultimo_avance = ahora
        self.etapa, self.detalle = etapa, detalle
        self.completadas, self.total = completadas, total

    def terminar(self, error: str = "") -> None:
        self._fin = time.monotonic()
        self.estado = "error" if error else "completada"
        if error:
            self.detalle = error
        else:
            self.etapa = "lista"

    def snapshot(self) -> dict:
        ahora = self._fin if self._fin is not None else time.monotonic()
        porcentaje = None
        if self.estado == "completada":
            porcentaje = 100
        elif self.total:
            porcentaje = min(99, round(self.completadas * 100 / self.total, 1))
        restante = None
        if (self.estado == "cargando" and self.total and self._unidades_medidas
                and self.completadas < self.total):
            media = self._seg_unidades / self._unidades_medidas
            estimado = media * (self.total - self.completadas)
            pendiente = estimado - max(0.0, ahora - self._ultima_unidad)
            # Cuando se excedió la muestra, vuelve a estimar al siguiente
            # avance: mostrar "0 s" mientras una petición sigue esperando
            # daría una promesa falsa.
            if pendiente > 0:
                restante = max(0.1, round(pendiente, 1))
        return {
            "estado": self.estado, "etapa": self.etapa, "detalle": self.detalle,
            "completadas": self.completadas, "total": self.total,
            "porcentaje": porcentaje, "alcance": "etapa",
            "transcurrido_seg": round(max(0.0, ahora - self._inicio), 1)
                if self._inicio is not None else 0,
            "restante_seg": restante,
            "sin_avance_seg": round(max(0.0, ahora - self._ultimo_avance), 1)
                if self._ultimo_avance is not None else 0,
            "finalizada": self.estado in ("completada", "error"),
        }


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
        self.carga = ProgresoCarga()
        self.error = ""
        self.log: list[str] = []

        self.origen = ""          # "betano" | "csv"
        self.consulta = ""        # query de Betano o nombre del archivo
        self.csv_path: Path | None = None
        self.titulo = ""
        # Repetición: la fecha de corte pedida ('AAAA-MM-DD') o None. La
        # cartelera se predijo con lo que se sabía antes de ese día.
        self.corte: str | None = None

        self.predicho_en: float | None = None
        self.cuotas_en: float | None = None
        self.datos: dict | None = None      # payload JSON de la cartelera
        self.patas: list[P.Pata] = []

        # Movimiento de línea: {clave_pata: {"antes": x, "ahora": y}}
        self.movimiento: dict[str, dict] = {}
        self._cuotas_previas: dict[str, float] = {}

        self.auto = True
        self.proximo_auto: float | None = None
        # Modo "en vivo": refresca solo la línea de ganador cada pocos segundos.
        # Arranca apagado a propósito — son ~6 peticiones por minuto a Betano y
        # eso solo tiene sentido cuando estás mirando la cartelera en pantalla.
        self.vivo = False
        self.vivo_en: float | None = None

    # -- lectura para la UI ------------------------------------------------ #
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "cargando": self.cargando,
                "progreso": self.progreso,
                "carga": self.carga.snapshot(),
                "error": self.error,
                "log": self.log[-40:],
                "origen": self.origen,
                "consulta": self.consulta,
                "titulo": self.titulo,
                "csv": self.csv_path.name if self.csv_path else "",
                "corte": self.corte,
                "predicho_en": self.predicho_en,
                "cuotas_en": self.cuotas_en,
                "auto": self.auto,
                "proximo_auto": self.proximo_auto,
                "intervalo_seg": INTERVALO_AUTO_SEG,
                "intervalo_vivo_seg": INTERVALO_VIVO_SEG,
                "vivo": self.vivo,
                "vivo_en": self.vivo_en,
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


def _ampliar_pelea(pelea: dict, probabilidades_metodo: dict | None = None) -> None:
    """Metadatos para avisos y gráficos, también compatibles con demos antiguas.

    Un historial local vacío no demuestra un debut. Las tasas históricas y
    los seis resultados se mantienen como desconocidos si no hay evidencia;
    nunca se rellenan con los promedios neutros del modelo.
    """
    from src.ufc_history import confirmed_ufc_debut

    # Las demos antiguas no contienen información del cinturón. Un nombre o
    # segmento estelar no confirma un título; la UI solo puede destacarlo con
    # una bandera explícita, y nunca por la verdad lógica de "false" o NaN.
    from src.card import bandera_titulo
    pelea["es_titulo"] = bandera_titulo(pelea)
    pelea["titulo_automatico"] = bandera_titulo({"es_titulo": pelea.get("titulo_automatico")}) is True
    pelea.setdefault("titulo_fuente", "")

    debutantes = []
    for lado in ("a", "b"):
        info = pelea.get(f"info_{lado}") or {}
        pelea[f"info_{lado}"] = info
        # Una demo antigua no tiene estos metadatos: conserva la ausencia de
        # historial, sin añadir resultados actuales a una predicción pasada.
        info.setdefault("ultimas_peleas", [])
        if info.get("debut_ufc_confirmado") is True or confirmed_ufc_debut(info):
            debutantes.append(pelea[lado])
        historial = info.get("metodo_victorias")
        tasas = {metodo: _num(historial.get(metodo)) for metodo in C.METHOD_CLASSES} \
            if isinstance(historial, dict) else {}
        if not tasas or any(t is None or not 0 <= t <= 1 for t in tasas.values()) \
                or not 0 < sum(tasas.values()) <= 1.001:
            tasas = None
        pelea[f"metodo_hist_{lado}"] = tasas
        pelea[f"metodo_hist_fuente_{lado}"] = _txt(info.get("metodo_victorias_fuente")) if tasas else ""
    pelea["debutantes"] = debutantes
    pelea["debut_cantidad"] = len(debutantes)

    ci = pelea.get("ci_a") or []
    pelea["ci_b"] = [round(1 - float(ci[1]), 4), round(1 - float(ci[0]), 4)] if len(ci) == 2 else None
    pelea["p_decision"] = _num((pelea.get("metodo") or {}).get("Decision"))

    # Los resultados conjuntos provienen del modelo entrenado de seis clases.
    # Las demos previas pueden conservarlos dentro del análisis de cuotas.
    clases = ("A_KO", "A_SUB", "A_DEC", "B_KO", "B_SUB", "B_DEC")
    candidatos = probabilidades_metodo or pelea.get("probabilidades_metodo")
    if not isinstance(candidatos, dict):
        candidatos = {op.get("clase"): op.get("p_modelo")
                      for op in pelea.get("metodo6") or [] if "error" not in op}
    probs = {clase: _num(candidatos.get(clase)) for clase in clases}
    if any(p is None or not 0 <= p <= 1 for p in probs.values()) or not 0.999 <= sum(probs.values()) <= 1.001:
        probs = None
    pelea["probabilidades_metodo"] = probs


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
            "es_titulo": c.get("es_titulo", fila.get("es_titulo")),
            "titulo_fuente": _txt(c.get("titulo_fuente", fila.get("titulo_fuente"))),
            "titulo_automatico": c.get("titulo_automatico", fila.get("titulo_automatico", False)),
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
        # El scraper ordena preliminares -> estelar. Preserva el índice de la
        # fuente aunque una pelea se omita por falta de datos; la UI no debe
        # promover otra pelea a estelar ni coestelar en ese caso.
        for campo in ("orden_cartelera", "total_cartelera"):
            dato = c.get(campo, fila.get(campo))
            if isinstance(dato, int) and not isinstance(dato, bool):
                pelea[campo] = dato
        if res.get("repeticion") is not None:
            # Solo en una repetición, y leído después de predecir. La clave va
            # aunque sea None ("la base todavía no la tiene"): la UI distingue
            # así una repetición de una cartelera normal pelea por pelea.
            pelea["resultado"] = c.get("resultado")
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
        # Los dos mercados de método viajan igual: la decisión es la misma apuesta
        # en los dos y "Qué apostar" tiene que verla venga de donde venga.
        for mercado in ("metodo6", "metodo5"):
            if c.get(mercado):
                pelea[mercado] = [
                    {k: (_num(o[k]) if k in ("p_modelo", "p_mercado", "p_final",
                                             "cuota_decimal", "ev", "kelly", "sobrerredondeo")
                         else o[k])
                     for k in o}
                    for o in c[mercado] if "error" not in o
                ]
        _ampliar_pelea(pelea, c.get("probabilidades_metodo") or getattr(sim, "p_method6", None))
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
        "repeticion": res.get("repeticion"),
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
            n = _num(i.get("n_peleas_hist"))
            apellido = nombre.split()[-1]
            if i.get("debut_ufc_confirmado") is True:
                causas.append(f"<b>{apellido}</b> todavía no tiene ninguna pelea en UFC confirmada en su historial.")
                if float(i.get("slpm") or 0) == 0:
                    causas.append("Su ficha tampoco tiene estadísticas de golpeo.")
            elif n is None:
                causas.append(f"El historial de <b>{apellido}</b> no está disponible en los datos consultados.")
            elif n < 3:
                n = int(n)
                if n == 0:
                    causas.append(f"No hay peleas con estadísticas detalladas de <b>{apellido}</b> "
                                  "en los datos consultados; eso no confirma un debut en UFC.")
                    continue
                peleas = f"{n} pelea" + ("s" if n > 1 else "")
                extra = ""
                if i.get("sherdog"):
                    extra = (f" Fuera de UFC tiene récord {i.get('wins',0)}-{i.get('losses',0)}, "
                             f"pero de esas peleas no existen estadísticas de golpeo ni de "
                             f"lucha: eso solo se publica de UFC.")
                elif float(i.get("slpm") or 0) == 0:
                    extra = " Y su ficha no tiene ni una estadística de golpeo."
                causas.append(f"<b>{apellido}</b> tiene {peleas} con estadísticas detalladas en la base local.{extra}")
            elif not i.get("historial_disponible", True):
                causas.append(f"El historial detallado de <b>{apellido}</b> no está disponible en la base local.")
            elif i.get("identidad_ambigua"):
                causas.append(f"Hay dos peleadores llamados <b>{nombre}</b> en UFCStats y la base local "
                              "no separa sus peleas: sus estadísticas podrían ser de los dos.")
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
def _par(a: str, b: str) -> str:
    from src.fighter_names import canonical_key
    return "|".join(sorted((canonical_key(a), canonical_key(b))))


def es_ufc(nombre_liga: str, peleas: list[dict], confirmadas: set | None = None) -> bool:
    """
    ¿Esta cartelera de Betano es de UFC? El modelo solo conoce UFC: una de
    otra liga sale con los dos peleadores "no encontrados" o, peor, con un
    homónimo de UFC.

    Betano la nombra ("UFC 332", "UFC Fight Night") o la mete en ligas
    genéricas como "Encuentros", donde también van RIZIN, PFL o eventos
    regionales. En ese caso pasa solo si al menos la mitad de sus peleas está
    en una cartelera confirmada por UFC (ufc_oficial): parejas por identidad,
    nunca por apellido.
    """
    import re
    if re.search(r"\bUFC\b", nombre_liga or "", re.I):
        return True
    if not peleas:
        return False
    if confirmadas is None:
        try:
            from src import ufc_oficial
            confirmadas = ufc_oficial.pares_confirmados()
        except Exception:                                   # noqa: BLE001
            confirmadas = set()
    from src.fighter_names import canonical_key
    pares = ["|".join(sorted((canonical_key(f["fighter_a"]), canonical_key(f["fighter_b"]))))
             for f in peleas]
    return sum(par in confirmadas for par in pares) * 2 >= len(pares)


def listar_carteleras() -> dict:
    """
    Carteleras de UFC abiertas en Betano, con fecha y número de peleas, y
    cuántas de otras ligas se dejaron fuera (ver es_ufc).

    `list_cards()` solo devuelve nombre y url — con eso la lista de la UI era
    una fila de nombres sin contexto. Acá se añade una petición por cartelera
    (la página del evento, que ya trae todas sus peleas) para poder mostrar
    CUÁNDO es y CUÁNTAS peleas tiene, que es lo que decide cuál abrir.

    Betano agrupa varios eventos bajo la misma liga "UFC Fight Night", así que
    una entrada puede rendir DOS carteleras de fines de semana distintos: se
    devuelven separadas, con su fecha, y cada una sabe pedirse por `--fecha`.
    """
    import datetime as _dt
    from src import betano_scraper as bs

    salida: list[dict] = []
    ocultas = 0
    confirmadas = None            # se pide a UFC solo si aparece una liga sin nombre UFC
    titulos = None                # las estelares que UFC marca "Title Bout"
    for c in bs.list_cards():
        try:
            grupos = bs._por_fecha(bs.list_fights(c["url"]))
        except Exception:                                   # noqa: BLE001
            grupos = None
        if not grupos:
            # Sin peleas a la vista no se puede comprobar qué liga es: solo
            # pasa si Betano la llama UFC.
            if es_ufc(c["name"], [], set()):
                salida.append({**c, "fecha": None, "peleas": None, "estelar": ""})
            else:
                ocultas += 1
            continue
        for dia, peleas in grupos.items():
            if titulos is None:
                try:
                    from src import ufc_oficial
                    titulos = ufc_oficial.pares_confirmados(solo_titulos=True)
                except Exception:                           # noqa: BLE001
                    titulos = set()
            if confirmadas is None and not es_ufc(c["name"], [], set()):
                try:
                    from src import ufc_oficial
                    confirmadas = ufc_oficial.pares_confirmados()
                except Exception:                           # noqa: BLE001
                    confirmadas = set()
            if not es_ufc(c["name"], peleas, confirmadas or set()):
                ocultas += 1
                continue
            est = peleas[-1]
            salida.append({
                "id": c["id"], "url": c["url"],
                # Con varios eventos bajo la misma liga, el nombre suelto no
                # distingue: se muestra el estelar, que sí.
                "name": c["name"],
                "fecha": dia.isoformat(),
                "dias": (dia - _dt.date.today()).days,
                "peleas": len(peleas),
                "estelar": f"{est['fighter_a']} vs {est['fighter_b']}",
                "titulo": _par(est["fighter_a"], est["fighter_b"]) in titulos,
                # lo que hay que mandarle a /api/cartelera/betano
                "query": c["name"],
            })
    salida.sort(key=lambda x: (x["fecha"] or "9999"))
    return {"carteleras": salida, "ocultas": ocultas}


def bajar_cuotas(query: str, destino: Path | None = None,
                 fecha: str | None = None,
                 progreso: Callable[[dict], None] | None = None) -> tuple[Path, str]:
    """
    Baja las cuotas de una cartelera de Betano y las deja en un CSV.
    Devuelve (ruta, titulo). Reutiliza `scrape_card`, que ya resuelve el lío de
    los eventos mezclados bajo la misma liga "UFC Fight Night".
    """
    from src import betano_scraper as bs
    titulo = query

    def avance(evento):
        nonlocal titulo
        titulo = evento.get("titulo", titulo)
        if progreso is not None:
            progreso(evento)
    # `fecha` distingue los eventos que Betano mete bajo la misma liga
    # ("UFC Fight Night" puede ser dos fines de semana distintos).
    ruta = bs.scrape_card(query, str(destino) if destino else None, fecha=fecha,
                          progreso=avance)
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
def _predecir_sync(csv_path: Path, progreso: Callable[[dict], None] | None = None,
                   corte: str | None = None, reports: bool = True) -> dict:
    """Usa callbacks para el avance; conserva stdout para el diagnóstico final."""
    from src.card import predict_card
    # Sin corte, la llamada queda idéntica a la de siempre.
    extra = {"corte": corte} if corte else {}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = predict_card(csv_path, reports=reports, detalle=False, devolver_todo=True,
                           progreso=progreso, **extra)
    salida = buf.getvalue()
    if not res or not res.get("rows"):
        raise RuntimeError(
            "No se pudo predecir ninguna pelea. Revisa los nombres del CSV.\n\n" + salida[-1500:])
    return res


def cargar(origen: str, consulta: str = "", csv_path: Path | None = None,
           refrescar_cuotas: bool = True, fecha: str | None = None,
           corte: str | None = None) -> None:
    """
    Arranca la carga de una cartelera en segundo plano. La UI hace polling a
    /api/estado mientras tanto.

    corte='AAAA-MM-DD' la predice como repetición (ver src/corte.py). Se valida
    antes de llamar: acá ya se asume una fecha bien formada.
    """
    with ESTADO.lock:
        if ESTADO.cargando:
            return
        ESTADO.cargando = True
        ESTADO.error = ""
        ESTADO.log = []
        ESTADO.progreso = "empezando…"
        ESTADO.carga = ProgresoCarga()
        ESTADO.carga.iniciar()

    def avance(evento: dict) -> None:
        with ESTADO.lock:
            ESTADO.carga.actualizar(evento)
            ESTADO._log(evento["detalle"])

    def _run() -> None:
        try:
            ruta = csv_path
            titulo = ruta.stem if ruta is not None else ""
            cuotas_en = None
            if origen == "betano":
                ruta, titulo = bajar_cuotas(consulta, destino=ruta, fecha=fecha, progreso=avance)
                cuotas_en = time.time()
            elif refrescar_cuotas and ESTADO.origen == "betano" and ESTADO.consulta:
                pass

            if ruta is None:
                raise RuntimeError("No hay cartelera que cargar.")

            avance({"etapa": "preparando", "detalle": f"Cargando modelos para {ruta.name}…"})
            res = _predecir_sync(ruta, progreso=avance, **({"corte": corte} if corte else {}))
            avance({"etapa": "serializando", "detalle": "Preparando los resultados para mostrarlos…"})
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
                ESTADO.titulo = titulo or ruta.stem
                ESTADO.corte = corte
                ESTADO.datos = datos
                ESTADO.patas = patas
                ESTADO.predicho_en = time.time()
                ESTADO.cuotas_en = cuotas_en
                cantidad = len(datos["peleas"])
                ESTADO.progreso = f"{cantidad} pelea{'s' if cantidad != 1 else ''} lista{'s' if cantidad != 1 else ''}"
                ESTADO.carga.detalle = ESTADO.progreso
                ESTADO.carga.terminar()
                if mov:
                    ESTADO.log.append(f"[i] {len(mov)} cuotas se movieron desde el refresh anterior")
        except (Exception, SystemExit) as e:         # noqa: BLE001
            with ESTADO.lock:
                mensaje = str(e) or f"No se pudo completar la carga ({type(e).__name__})."
                if isinstance(e, SystemExit) and (not mensaje or mensaje.isdigit()):
                    mensaje = "No se pudo cargar la cartelera de Betano. Revisa el evento y la conexión."
                ESTADO.error = mensaje
                ESTADO.progreso = "falló"
                ESTADO.carga.terminar(mensaje)
        finally:
            with ESTADO.lock:
                ESTADO.cargando = False
                ESTADO.proximo_auto = (time.time() + INTERVALO_AUTO_SEG) if ESTADO.auto else None

    threading.Thread(target=_run, daemon=True).start()


def limpiar() -> None:
    """
    Suelta la cartelera activa y deja la UI como recién abierta.

    Apaga también el modo en vivo y borra el histórico de movimiento de línea:
    si no, al cargar la siguiente cartelera se quedaba refrescando cuotas de
    una que ya no está en pantalla, y las flechas de movimiento mostraban
    cambios de la anterior.
    """
    with ESTADO.lock:
        ESTADO.datos = None
        ESTADO.patas = []
        ESTADO.origen = ""
        ESTADO.consulta = ""
        ESTADO.csv_path = None
        ESTADO.titulo = ""
        ESTADO.corte = None
        ESTADO.predicho_en = None
        ESTADO.cuotas_en = None
        ESTADO.proximo_auto = None
        ESTADO.vivo = False
        ESTADO.vivo_en = None
        ESTADO.movimiento = {}
        ESTADO._cuotas_previas = {}
        ESTADO.progreso = ""
        ESTADO.error = ""
        ESTADO.log = []
        ESTADO.carga = ProgresoCarga()


def refrescar() -> str:
    """Refresh manual: vuelve a bajar cuotas (si el origen es Betano) y repredice."""
    with ESTADO.lock:
        if ESTADO.cargando:
            return "Ya hay una carga en curso."
        origen, consulta, ruta, corte = ESTADO.origen, ESTADO.consulta, ESTADO.csv_path, ESTADO.corte
    if not origen:
        return "No hay ninguna cartelera cargada todavía."
    if origen == "demo":
        return "Modo demo: no hay cuotas que refrescar."
    # Una repetición se vuelve a predecir con el MISMO corte: refrescar no
    # puede convertirla en una predicción de hoy.
    cargar(origen, consulta, ruta, corte=corte)
    return ""


def refrescar_linea() -> str:
    """
    Refresco EN VIVO: baja solo el mercado de ganador (1 petición) y recalcula
    lo que depende de la cuota, SIN volver a predecir.

    Qué cambia y qué no, que es la parte que importa entender:
      * `p_modelo_a` NO cambia. Es lo que el modelo saca de los stats; que Betano
        mueva la línea no altera el historial de nadie.
      * SÍ cambia TODO lo que se calcula con la cuota: `p_mercado_a`, la mezcla
        `p_final_a`, el EV y Kelly, y como la mezcla es la probabilidad que
        manda, también el porcentaje de la tarjeta, el ganador, la etiqueta de
        confianza y la p de las patas de ganador del parlay.
    Por eso este refresco es barato: una petición y aritmética en memoria.

    BUG QUE ESTO ARREGLA: antes solo se actualizaba el bloque "mercado". Si la
    línea se daba vuelta (Rakic 1,26 -> 2,05), la tarjeta seguía diciendo
    "Rakic 79%, fuerte" y la pata del parlay multiplicaba la p VIEJA por la
    cuota NUEVA: mostraba EV +62,5% cuando el real era +2,9%.

    Las cuotas de MÉTODO no se tocan acá — viven en otra API, una llamada por
    pelea. Las refresca el ciclo completo.
    """
    with ESTADO.lock:
        if ESTADO.cargando or ESTADO.origen != "betano" or not ESTADO.datos:
            return "no aplica"
        consulta = ESTADO.consulta
        datos = ESTADO.datos

    try:
        from src import betano_scraper as B
        from src import value
        from src.simulate import monte_carlo
        card = B.find_card(consulta)
        if card is None:
            return "no encontré la cartelera"
        frescas = B.cuotas_rapidas(card["url"])
        if not frescas:
            return "sin respuesta de Betano"

        # Índice por apellidos: el id de pelea de Betano no viaja en `datos`.
        def apellido(nombre: str) -> str:
            return _slug(nombre.split()[-1])

        def clave(a: str, b: str) -> frozenset:
            return frozenset({apellido(a), apellido(b)})

        por_par = {clave(a, b): (a, ca, cb) for (a, b, ca, cb) in frescas.values()}
        cal = value.cargar_calibrador()

        movidas = 0
        with ESTADO.lock:
            for pl in datos["peleas"]:
                m = pl.get("mercado")
                if not m:
                    continue
                par = por_par.get(clave(pl["a"], pl["b"]))
                if not par:
                    continue
                primero, ca, cb = par
                # El conjunto de apellidos no dice quién es quién: si Betano lista
                # la pelea al revés que el CSV, cada cuota iría al peleador
                # equivocado. Se orienta por el nombre que acompaña a la cuota.
                if apellido(primero) == apellido(pl["b"]) != apellido(pl["a"]):
                    ca, cb = cb, ca
                if m.get("cuota_a") == ca and m.get("cuota_b") == cb:
                    continue

                antes = {"A": m.get("cuota_a"), "B": m.get("cuota_b")}
                v = value.analizar(m["p_modelo_a"], ca, cb, cal=cal)
                m.update({
                    "cuota_a": ca, "cuota_b": cb,
                    "p_mercado_a": _num(v.p_mercado_a),
                    "p_final_a": _num(v.p_final_a),
                    "disc": _num(v.discrepancia), "disc_cruda": _num(v.discrepancia_cruda),
                    "vig": _num(v.vig), "lado": v.lado,
                    "cuota": _num(v.cuota_decimal), "ev": _num(v.ev),
                    "kelly": _num(v.kelly), "veredicto": v.veredicto,
                })
                for lado, ahora in (("A", ca), ("B", cb)):
                    if antes[lado]:
                        ESTADO.movimiento[f"{pl['id']}:ML:{lado}"] = {"antes": antes[lado],
                                                                       "ahora": ahora}

                # La probabilidad que manda es la mezcla, igual que en card.py.
                p_a = v.p_final_a if (cal is not None and v.p_final_a == v.p_final_a) \
                    else m["p_modelo_a"]
                sim = monte_carlo(p_a, pl["metodo"], pl["a"], pl["b"])
                prob, pocos = max(sim.p_a, sim.p_b), pl.get("pocos") or []
                pl.update({
                    "p_a": sim.p_a, "p_b": sim.p_b, "ci_a": list(sim.ci_a),
                    "ci_b": [round(1 - sim.ci_a[1], 4), round(1 - sim.ci_a[0], 4)],
                    "ganador": sim.winner,
                    "confianza": _confianza(prob, pocos),
                    "por_que_confianza": _por_que_confianza(
                        prob, pocos, {pl["a"]: pl.get("info_a", {}), pl["b"]: pl.get("info_b", {})}),
                })

                # Las patas de ganador de ESTA pelea cotizan con la línea nueva Y
                # con la probabilidad nueva: una sin la otra es un EV inventado.
                for pata in ESTADO.patas:
                    if pata.mercado == "ganador" and pata.fight_id == pl["id"]:
                        pata.cuota = ca if pata.clase == "A" else cb
                        pata.p = sim.p_a if pata.clase == "A" else sim.p_b
                movidas += 1

            ESTADO.patas.sort(key=lambda x: (P.TIERS[x.tier]["orden"], -x.ev))
            datos["patas"] = [x.dict() for x in ESTADO.patas]
            datos["sugerencia"] = P.sugerir(ESTADO.patas)
            ESTADO.cuotas_en = time.time()
            ESTADO.vivo_en = time.time()
        return f"{movidas} cuotas movidas" if movidas else "sin cambios"
    except Exception as e:                            # noqa: BLE001
        return f"falló: {e}"


# --------------------------------------------------------------------------- #
# Portada: noticias y carteleras confirmadas por UFC
# --------------------------------------------------------------------------- #
_REFRESCO_PORTADA = threading.Lock()


def _refrescar_portada() -> None:
    from src import ufc_oficial
    try:
        ufc_oficial.noticias()
        ufc_oficial.eventos()
    except Exception:                                       # noqa: BLE001
        pass                      # se sigue mostrando lo guardado
    finally:
        _REFRESCO_PORTADA.release()


def _en_base(recientes: list[dict]) -> None:
    """
    Marca los eventos terminados que la base local ya tiene, para ofrecer
    Repetir. Se cruzan por fecha (±1 día: UFC fecha en hora de Chile y UFCStats
    en la del lugar) y por la estelar, no por el nombre del evento.
    """
    import datetime as dt
    try:
        from src import corte
        peleas = corte._peleas()
    except Exception:                                       # noqa: BLE001
        return
    estelares = peleas[peleas["estelar"]]
    for e in recientes:
        dia = dt.datetime.fromtimestamp(e["inicio"]["estelar"]).date()
        cerca = estelares[(estelares["date"].dt.date - dia).abs() <= dt.timedelta(days=1)]
        palabras = set(_slug(e.get("titular", "")).split("_"))
        hit = cerca[[_slug(a).split("_")[-1] in palabras and _slug(b).split("_")[-1] in palabras
                     for a, b in zip(cerca["fighter_a"], cerca["fighter_b"])]]
        if len(hit) == 1:
            r = hit.iloc[0]
            e["en_base"] = {"evento": r["event"], "fecha": r["date"].strftime("%Y-%m-%d")}


def portada() -> dict:
    """
    Noticias y eventos de UFC para la pestaña Inicio. Responde con lo guardado
    y, si está vencido, lo refresca en otro hilo (la UI vuelve a pedir). Solo
    la primera vez, sin nada guardado, espera a UFC.
    """
    from src import ufc_oficial
    noticias, eventos, vencido = ufc_oficial.guardado()
    actualizando = False
    if noticias is None or eventos is None:
        try:
            noticias, eventos = ufc_oficial.noticias(), ufc_oficial.eventos()
        except Exception:                                   # noqa: BLE001
            pass
    elif vencido and _REFRESCO_PORTADA.acquire(blocking=False):
        threading.Thread(target=_refrescar_portada, daemon=True).start()
        actualizando = True
    eventos = dict(eventos or {"proximos": [], "recientes": []})
    eventos["recientes"] = [dict(e) for e in eventos.get("recientes", [])]
    _en_base(eventos["recientes"])
    # Lo último que la base local sí tiene: siempre se puede repetir.
    try:
        from src import corte
        en_base = corte.peleas_anteriores("", 4)["peleas"]
    except Exception:                                       # noqa: BLE001
        en_base = []
    with ESTADO.lock:
        actual = ({"titulo": ESTADO.titulo, "peleas": len(ESTADO.datos.get("peleas", [])),
                   "corte": ESTADO.corte} if ESTADO.datos else None)
    return {"noticias": (noticias or {}).get("notas", []),
            "proximos": eventos.get("proximos", []),
            "recientes": eventos["recientes"],
            "en_base": en_base,
            "consultado": min(filter(None, [(noticias or {}).get("consultado"),
                                            eventos.get("consultado")]), default=None),
            "sin_conexion": noticias is None and not eventos.get("proximos"),
            "actualizando": actualizando or _REFRESCO_PORTADA.locked(),
            "actual": actual}


def cargar_oficial(id_evento: str) -> str:
    """Predice una cartelera confirmada por UFC (sin cuotas). Devuelve el CSV."""
    from src import ufc_oficial
    ruta = ufc_oficial.cartelera_csv(id_evento)
    cargar("csv", ruta.name, ruta)
    return ruta.name


# --------------------------------------------------------------------------- #
# Repetición: peleas que ya pasaron, con los datos de ese día
# --------------------------------------------------------------------------- #
def peleas_anteriores(q: str = "", limite: int = 24) -> dict:
    """Las peleas de la base local para elegir en Cargar (ver corte.peleas_anteriores)."""
    from src import corte
    return corte.peleas_anteriores(q, limite)


def cargar_historico(evento: str, fecha: str) -> str:
    """
    Arma el CSV del evento desde la base local y lo predice con corte en su
    fecha. Devuelve el nombre del archivo. Lanza ValueError si no existe o si
    la fecha no sirve como corte.
    """
    from src import corte
    dia = corte.a_fecha(fecha)
    ruta = corte.cartelera_de_evento(evento, dia.strftime("%Y-%m-%d"))
    cargar("csv", ruta.name, ruta, corte=dia.strftime("%Y-%m-%d"))
    return ruta.name


# --------------------------------------------------------------------------- #
# Portada: cómo le fue al modelo en las últimas carteleras
# --------------------------------------------------------------------------- #
# Las últimas carteleras de la base, predichas como repetición (solo con lo que
# se sabía ese día) y comparadas con cómo terminaron. Es la misma corrida que
# "Repetir", así que la portada y la repetición nunca dicen cosas distintas.
# Predecir una cartelera tarda, y si su fecha es anterior al modelo de
# producción hay que entrenar uno: se calcula en otro hilo y queda en disco. La
# UI vuelve a pedir mientras tanto. Se rehace solo si cambia la base o el modelo.
RESULTADOS_N = 3
RESULTADOS_JSON = C.DATA_PROCESSED / "resultados_recientes.json"
_RESULTADOS_LOCK = threading.Lock()
_METODOS = ("KO/TKO", "Submission", "Decision")


def _firma_resultados() -> str:
    rutas = (C.DATA_PROCESSED / "ufcstats_fights.csv", C.FEATURES_CSV,
             C.WINNER_MODEL, C.METHOD_MODEL)
    return ":".join(DB.signature(r) for r in rutas)


def _ultimos_eventos(n: int) -> list[dict]:
    """Los `n` eventos más nuevos de la base local, del más nuevo al más viejo."""
    from src import corte
    p = corte._peleas()
    return [{"evento": str(r.event), "fecha": r.date.strftime("%Y-%m-%d")}
            for r in p.drop_duplicates(["event", "date"]).head(n).itertuples()]


def _clave_evento(e: dict) -> str:
    return f"{e['fecha']}|{e['evento']}"


def _leer_resultados(firma: str) -> dict:
    """{clave: cartelera} guardadas con esta firma; con otra, nada sirve."""
    import json
    try:
        d = DB.read_json(RESULTADOS_JSON)
    except (OSError, ValueError):
        return {}
    return d.get("eventos", {}) if d.get("firma") == firma else {}


def _guardar_resultados(firma: str, eventos: dict) -> None:
    import json
    if DB.key(RESULTADOS_JSON) is not None:
        DB.write_text(RESULTADOS_JSON, json.dumps({"firma": firma, "eventos": eventos}, ensure_ascii=False),
                      encoding="utf-8")
        return
    tmp = RESULTADOS_JSON.with_suffix(".tmp")
    DB.write_text(tmp, json.dumps({"firma": firma, "eventos": eventos}, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(RESULTADOS_JSON)          # la UI nunca lee un archivo a medias


def _resumen_pelea(p: dict) -> dict:
    """Lo que la portada muestra de una pelea repetida: pronóstico contra resultado."""
    r = p.get("resultado") or None
    metodo = p.get("metodo") or {}
    # El más probable, con la misma regla de desempate que la UI (aciertoMetodo).
    top = max(_METODOS, key=lambda k: metodo.get(k) or 0)
    real = (r or {}).get("metodo")
    acierto_metodo = (real == top) if r and r.get("ganador") and real in _METODOS else None
    return {"a": p["a"], "b": p["b"], "ganador": p["ganador"],
            "p": float(max(p["p_a"], p["p_b"])), "confianza": p["confianza"],
            "es_titulo": p.get("es_titulo") is True,
            "estelar": str(p.get("segmento", "")).lower() == "estelar",
            "metodo": top, "p_metodo": _num(metodo.get(top)),
            "resultado": r, "acierto": (r or {}).get("acierto"),
            "acierto_metodo": acierto_metodo}


def _resultado_evento(evento: str, fecha: str) -> dict:
    from src import corte
    ruta = corte.cartelera_de_evento(evento, fecha)
    datos, _ = _serializar(_predecir_sync(ruta, corte=fecha, reports=False), ruta)
    # La cartelera viene como en Betano (preliminares arriba): se muestra al revés,
    # con la estelar primero.
    peleas = [_resumen_pelea(p) for p in reversed(datos["peleas"])]
    peleas.sort(key=lambda p: not p["estelar"])
    resueltas = [p for p in peleas if p["acierto"] is not None]
    metodos = [p for p in peleas if p["acierto_metodo"] is not None]
    return {"evento": evento, "fecha": fecha, "peleas": peleas,
            "con_cuotas": bool(datos.get("con_cuotas")),
            "aciertos": sum(p["acierto"] for p in resueltas), "resueltas": len(resueltas),
            "aciertos_metodo": sum(p["acierto_metodo"] for p in metodos),
            "metodos": len(metodos)}


def _calcular_resultados(pendientes: list[dict], firma: str) -> None:
    try:
        for e in pendientes:
            # Una cartelera que el usuario pidió va primero: esto puede esperar.
            while ESTADO.cargando:
                time.sleep(1)
            try:
                cartelera = _resultado_evento(e["evento"], e["fecha"])
            except (Exception, SystemExit) as ex:           # noqa: BLE001
                # Queda guardado para no reintentarlo en cada pedido de la UI;
                # con la base o el modelo nuevos se vuelve a intentar.
                cartelera = {**e, "error": str(ex) or type(ex).__name__}
            guardadas = _leer_resultados(firma)
            guardadas[_clave_evento(e)] = cartelera
            _guardar_resultados(firma, guardadas)
    finally:
        _RESULTADOS_LOCK.release()


def resultados_recientes() -> dict:
    """
    Las últimas RESULTADOS_N carteleras de la base con el pronóstico de ese día y
    cómo terminó cada pelea. Las que faltan se calculan en otro hilo: vuelven
    como {"pendiente": True} y `calculando` le dice a la UI que pregunte de nuevo.
    """
    try:
        eventos = _ultimos_eventos(RESULTADOS_N)
    except Exception:                                       # noqa: BLE001
        return {"carteleras": [], "sin_base": True, "calculando": False}
    firma = _firma_resultados()
    guardadas = _leer_resultados(firma)
    pendientes = [e for e in eventos if _clave_evento(e) not in guardadas]
    if pendientes and _RESULTADOS_LOCK.acquire(blocking=False):
        threading.Thread(target=_calcular_resultados, args=(pendientes, firma),
                         daemon=True).start()
    return {"carteleras": [guardadas.get(_clave_evento(e)) or {**e, "pendiente": True}
                           for e in eventos],
            "sin_base": False,
            "calculando": _RESULTADOS_LOCK.locked()}


# --------------------------------------------------------------------------- #
# Modo demo: carteleras ya predichas, sin modelos ni base de datos
# --------------------------------------------------------------------------- #
# data/ y models/ no se versionan, así que en un clon limpio (o en una sesión de
# Claude Code en la nube) la UI no puede predecir nada. Para poder trabajar la
# INTERFAZ igual, webui/demo/ guarda la salida real de tres carteleras tal como
# la dejó _serializar(): misma forma JSON que /api/estado. No es un modelo
# alternativo ni números inventados: es una foto de una corrida real.
DEMO_DIR = ROOT / "webui" / "demo"


def ruta_demo(nombre: str | None = None) -> Path | None:
    """El JSON de demo cuyo nombre contiene `nombre` (o el primero si no se da)."""
    archivos = sorted(DEMO_DIR.glob("*.json"))
    if nombre:
        archivos = [a for a in archivos if nombre.lower() in a.stem.lower()]
    return archivos[0] if archivos else None


def cargar_demo(ruta: Path) -> None:
    """Deja en ESTADO una cartelera de webui/demo/ como si se acabara de predecir."""
    import json
    from dataclasses import fields
    d = DB.read_json(Path(ruta))
    for pelea in d["datos"]["peleas"]:
        _ampliar_pelea(pelea)
    campos = {f.name for f in fields(P.Pata)}
    patas = [P.Pata(**{k: v for k, v in p.items() if k in campos}) for p in d["datos"]["patas"]]
    with ESTADO.lock:
        ESTADO.origen = "demo"
        ESTADO.consulta = d.get("csv", "")
        ESTADO.csv_path = None
        ESTADO.corte = d.get("corte")
        ESTADO.titulo = f"DEMO · {d.get('titulo', Path(ruta).stem)}"
        ESTADO.datos = d["datos"]
        ESTADO.patas = patas
        ESTADO.movimiento = d.get("movimiento", {})
        ESTADO.predicho_en = time.time()
        ESTADO.cuotas_en = None
        ESTADO.error = ""
        ESTADO.progreso = f"{len(d['datos']['peleas'])} peleas (modo demo)"
        ESTADO.carga = ProgresoCarga()


# --------------------------------------------------------------------------- #
# Auto-refresh: ciclo completo cada 10 min, línea en vivo cada 10 s
# --------------------------------------------------------------------------- #
def _bucle_auto() -> None:
    """
    Solo refresca la cartelera ACTIVA, no todo Betano: son ~22 peticiones con
    1,5 s de pausa entre medio (config.REQUEST_DELAY_SEC). Cada 10 minutos eso
    es scraping educado; barrer el sitio entero no lo sería.
    """
    while True:
        time.sleep(2)
        ahora = time.time()
        with ESTADO.lock:
            completo = (ESTADO.auto and not ESTADO.cargando and ESTADO.origen == "betano"
                        and ESTADO.proximo_auto and ahora >= ESTADO.proximo_auto)
            # El modo en vivo cede el paso al completo: si toca el grande, no se
            # pisan dos peticiones a la vez.
            vivo = (not completo and ESTADO.vivo and not ESTADO.cargando
                    and ESTADO.origen == "betano" and ESTADO.datos is not None
                    and (ESTADO.vivo_en is None
                         or ahora - ESTADO.vivo_en >= INTERVALO_VIVO_SEG))
        if completo:
            refrescar()
        elif vivo:
            refrescar_linea()


def arrancar_auto() -> None:
    threading.Thread(target=_bucle_auto, daemon=True).start()
