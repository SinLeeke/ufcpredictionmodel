"""
parlay.py
Constructor y evaluador de parlays (combinadas) de hasta 13 patas, que es el
máximo que acepta Betano.

Este módulo NO inventa un modelo nuevo: toma las probabilidades que ya produce
`card.predict_card` y las cuotas reales de Betano, y responde dos preguntas que
la consola no respondía:

  1. ¿Conviene meter ESTA pata? -> se responde con el nivel de EVIDENCIA medido
     en los backtests del proyecto, no con el EV a secas. Un +40% de EV en una
     finalización sigue siendo peor apuesta que un +5% en una decisión.
  2. ¿Conviene ESTE parlay? -> se responde con la matemática de la combinada y,
     sobre todo, con su FRAGILIDAD: cuánto puede equivocarse cada pata antes de
     que el EV se dé vuelta.

LA MATEMÁTICA INCÓMODA DEL PARLAY (leer antes de tocar nada)
-----------------------------------------------------------
Si las patas son independientes, el EV de la combinada es:

    EV_parlay = Π (1 + EV_i) − 1

O sea que 13 patas con +5% de EV cada una dan +88% de EV combinado. Eso es
cierto Y ES UNA TRAMPA, por dos motivos que este módulo mide explícitamente:

  * **La probabilidad de cobrar se desploma.** 13 patas al 60% = 0,13%. Son
    ~770 combinadas para esperar UN acierto. El EV es real a MUY largo plazo;
    tu bankroll no llega.
  * **El error se multiplica.** Si cada `p` está sobreestimada un 5% relativo,
    sobre 13 patas eso es 1,05^13 = 1,89: casi el doble. Un parlay de 13 patas
    con +88% de EV se cae a CERO si cada probabilidad está apenas un 4,7%
    inflada. Y las probabilidades de este proyecto tienen un Brier de 0,21, o
    sea error real, no error teórico.

Por eso `evaluar()` devuelve `error_tolerable`: el porcentaje de error relativo
por pata que el parlay aguanta antes de pasar a perder. Es el número más
honesto de toda la pantalla y la UI lo muestra en grande.

EXCLUYENTES Y SIMILARES
-----------------------
Dos patas de la MISMA pelea nunca son independientes, pero no todas chocan por
el mismo motivo, y la interfaz lo distingue porque el usuario lo pidió:

  * **Excluyentes**: no pueden ocurrir las dos. "Gana A" + "Gana B", o
    "A por KO" + "A por decisión". Ninguna casa las acepta juntas.
  * **Similares**: una contiene o solapa a la otra. "Gana A" + "A por decisión",
    o "A por finalización" (5 vías) + "A por KO" (7 vías). Betano casi no sube
    la cuota al combinarlas —a veces directamente no la sube— porque ya está
    cobrando la misma información dos veces.

Ambos casos se detectan igual: cada pata se representa como el CONJUNTO de
desenlaces elementales que cubre, sobre {A_KO, A_SUB, A_DEC, B_KO, B_SUB,
B_DEC}. Si dos conjuntos no se tocan, son excluyentes; si se tocan, son
similares. No hace falta enumerar casos a mano.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_PATAS = 13          # tope de Betano
MIN_PATAS = 2

# --------------------------------------------------------------------------- #
# Niveles de evidencia
# --------------------------------------------------------------------------- #
# Cada mercado se etiqueta con lo que el backtest DE ESTE PROYECTO midió sobre
# él. No es una opinión ni un ranking de "confianza del modelo": es el ROI fuera
# de muestra y su significancia estadística. Los números salen de
# backtest_metodo.py y backtest_valor.py.
TIERS = {
    "A": {
        "nombre": "Probado",
        "orden": 0,
        "resumen": "+15,4% de ROI, t=3,0 (1.145 apuestas, 2018-2024)",
        "detalle": ("Apostar DECISIONES en el mercado de método es la única ventaja del "
                    "proyecto que aguanta el test estadístico. El público paga de más por "
                    "las finalizaciones, así que las decisiones quedan baratas."),
    },
    "B": {
        "nombre": "Sin ventaja clara",
        "orden": 1,
        "resumen": "+1,0% de retorno ± 7,5 puntos (4.744 apuestas)",
        "detalle": ("Apostar al ganador no le gana a la casa ni le pierde: el margen de error "
                    "se come el resultado, así que no se puede afirmar que haya ventaja en "
                    "ninguna dirección. Y buscar solo las peleas donde el modelo discrepa "
                    "fuerte del precio es peor todavía (−8,1%): cuando se separan, el que "
                    "suele equivocarse es el modelo."),
    },
    "C": {
        "nombre": "Ruido",
        "orden": 2,
        "resumen": "t=0,5 — indistinguible de la suerte",
        "detalle": ("Apostar FINALIZACIONES (KO o sumisión) en el mercado de método no "
                    "sobrevivió al backtest. El EV puede verse enorme justamente porque "
                    "son cuotas altas, y eso no lo convierte en valor."),
    },
    "D": {
        "nombre": "Sin validar",
        "orden": 3,
        "resumen": "cero cuotas históricas: imposible saber si hay ventaja",
        "detalle": ("Rondas, 'llega al final', total de asaltos: el modelo puede predecirlos "
                    "(AUC 0,65) pero el proyecto no tiene ni una cuota histórica de esos "
                    "mercados, así que no hay forma de saber si esa señal le gana al precio."),
    },
}


# --------------------------------------------------------------------------- #
# Mercados (las secciones de la interfaz)
# --------------------------------------------------------------------------- #
# Se separan porque son mercados DISTINTOS en Betano, con precios distintos y
# reglas distintas. Mezclarlos en una sola lista hacía imposible ver, por
# ejemplo, que una pelea con 5 vías simplemente no ofrece KO por separado.
MERCADOS = {
    "ganador": {
        "nombre": "Quién gana",
        "orden": 0,
        "descripcion": ("El mercado principal: solo importa quién levanta la mano, sin "
                        "importar cómo. Es el que tiene la comisión más baja (~4%) y el "
                        "que más límite de apuesta acepta."),
    },
    "metodo7": {
        "nombre": "Cómo gana — 7 vías",
        "orden": 1,
        "descripcion": ("Betano separa KO/TKO, sumisión y decisión para cada peleador "
                        "(3 × 2 + empate = 7 opciones). Es el único mercado donde este "
                        "proyecto encontró una ventaja real, y está en las decisiones."),
    },
    "metodo5": {
        "nombre": "Cómo gana — 5 vías",
        "orden": 2,
        "descripcion": ("Cuando Betano NO separa KO de sumisión, ofrece solo "
                        "\"finalización\" y \"decisión\" por peleador (2 × 2 + empate = 5). "
                        "No es un mercado peor: es el mismo con menos granularidad. La "
                        "decisión vale exactamente lo mismo que en el de 7 vías, porque es "
                        "literalmente la misma apuesta."),
    },
}

# Desenlaces elementales. Toda pata se traduce a un subconjunto de esto, y de
# ahí sale sola la detección de excluyentes y similares.
_COBERTURA = {
    ("ganador", "A"): frozenset({"A_KO", "A_SUB", "A_DEC"}),
    ("ganador", "B"): frozenset({"B_KO", "B_SUB", "B_DEC"}),
    ("metodo7", "A_KO"): frozenset({"A_KO"}),
    ("metodo7", "A_SUB"): frozenset({"A_SUB"}),
    ("metodo7", "A_DEC"): frozenset({"A_DEC"}),
    ("metodo7", "B_KO"): frozenset({"B_KO"}),
    ("metodo7", "B_SUB"): frozenset({"B_SUB"}),
    ("metodo7", "B_DEC"): frozenset({"B_DEC"}),
    ("metodo5", "A_FIN"): frozenset({"A_KO", "A_SUB"}),
    ("metodo5", "A_DEC"): frozenset({"A_DEC"}),
    ("metodo5", "B_FIN"): frozenset({"B_KO", "B_SUB"}),
    ("metodo5", "B_DEC"): frozenset({"B_DEC"}),
}


# --------------------------------------------------------------------------- #
# Qué tan probable lo ve el sistema (eje distinto al de la evidencia)
# --------------------------------------------------------------------------- #
# El nivel de evidencia responde "¿vale la pena el PRECIO?". Esto responde otra
# pregunta, la que se hace uno primero: "¿qué tan probable es que pase?".
# Son independientes: una selección puede ser muy probable y aun así mal pagada.
#
# Los porcentajes de acierto son los MEDIDOS por tramo sobre peleas fuera de
# muestra, y van pegados a cada etiqueta a propósito: "segura" a secas haría
# creer que no falla, y a ese nivel falla alrededor de 1 de cada 7 veces.
NIVELES = [
    (0.80, "segura",   "El sistema la ve muy clara. En este tramo acierta cerca del 85 %, "
                       "o sea que aun así falla alrededor de 1 de cada 7."),
    (0.60, "buena",    "Favorito con margen. En este tramo el acierto real ronda el 70-73 %."),
    (0.55, "leve",     "Favorito por poco. El acierto real acá está entre 55 % y 60 %: "
                       "existe la ventaja, pero es chica."),
    (0.00, "coinflip", "Pelea pareja. Por debajo de 55 % el acierto real ronda el 50 %, "
                       "que es lo mismo que tirar una moneda."),
]


def nivel_confianza(p: float) -> tuple[str, str]:
    """(etiqueta, explicación) según la probabilidad estimada."""
    for corte, nombre, detalle in NIVELES:
        if p >= corte:
            return nombre, detalle
    return NIVELES[-1][1], NIVELES[-1][2]


@dataclass
class Pata:
    """Una pata candidata del parlay."""
    id: str
    fight_id: str
    pelea: str
    mercado: str          # "ganador" | "metodo7" | "metodo5"
    seleccion: str        # texto para humanos
    clase: str            # "A"/"B", "A_KO"…, "A_FIN"…
    p: float              # probabilidad final (mezclada con el mercado si hay cuotas)
    cuota: float          # decimal, tal como la paga Betano
    tier: str
    # Probabilidad del modelo SOLO, sin mirar la cuota. Se guarda aparte porque
    # la interfaz decía "el modelo le da X %" mostrando en realidad la mezcla.
    p_modelo: float | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def cubre(self) -> frozenset:
        """Los desenlaces elementales que hacen ganar esta pata."""
        return _COBERTURA.get((self.mercado, self.clase), frozenset())

    @property
    def ev(self) -> float:
        return self.p * self.cuota - 1.0

    @property
    def apostable(self) -> bool:
        """Si esta pata, SOLA, calificaría como apuesta."""
        return self.ev > 0 and not self.avisos and self.tier in ("A", "B")

    def dict(self) -> dict:
        t = TIERS[self.tier]
        return {
            "id": self.id, "fight_id": self.fight_id, "pelea": self.pelea,
            "mercado": self.mercado, "mercado_nombre": MERCADOS[self.mercado]["nombre"],
            "seleccion": self.seleccion, "clase": self.clase,
            "p": round(self.p, 4), "cuota": round(self.cuota, 2),
            "ev": round(self.ev, 4), "tier": self.tier,
            "tier_nombre": t["nombre"], "tier_resumen": t["resumen"],
            "tier_detalle": t["detalle"], "avisos": self.avisos,
            "apostable": self.apostable,
            "veredicto": self.veredicto(), "por_que": self.por_que(),
            "p_modelo": None if self.p_modelo is None else round(self.p_modelo, 4),
            "nivel": self.nivel()[0], "nivel_detalle": self.nivel()[1],
        }

    def nivel(self) -> tuple[str, str]:
        """Qué tan probable la ve el sistema. Independiente de si está bien pagada."""
        return nivel_confianza(self.p)

    def veredicto(self) -> str:
        """
        "si" | "quizas" | "no". Va SEPARADO del texto para que la interfaz pueda
        pintar el icono y el color sin tener que adivinar leyendo la frase.
        """
        if self.avisos or self.tier in ("C", "D") or self.ev < 0:
            return "no"
        if self.tier == "A":
            return "si"
        return "quizas" if self.ev >= 0.03 else "no"

    def por_que(self) -> str:
        """
        La explicación, en lenguaje llano y SIN prefijo de veredicto: el sí/no lo
        pone la interfaz a partir de `veredicto()`. Nada de jerga sin traducir —
        si aparece un término técnico, va explicado en la misma frase.
        """
        ev_pct = self.ev * 100

        if self.avisos:
            return (f"{' '.join(self.avisos)} No importa cuánto valor parezca tener: "
                    f"ese cálculo se apoya en un dato que no es de fiar.")

        if self.tier == "A":
            if ev_pct >= 0:
                return (f"La mejor clase de selección que ofrece este sistema. El modelo le "
                        f"da {self.p*100:.0f}% de probabilidad y la casa la paga a "
                        f"{self.cuota:.2f}, o sea paga de más: {ev_pct:+.1f}% de valor. "
                        f"Apostar a que la pelea llega a decisión rindió +15,4% sobre 1.145 "
                        f"apuestas históricas.")
            return (f"Es el mercado bueno, pero no a este precio: la cuota {self.cuota:.2f} "
                    f"no alcanza a cubrir el {self.p*100:.0f}% que le da el modelo "
                    f"({ev_pct:+.1f}% de valor). La ventaja está en el mercado en general, "
                    f"no en cada selección suelta.")

        if self.tier == "B":
            if ev_pct >= 3:
                return (f"Paga {ev_pct:+.1f}% más de lo que vale según el modelo, así que se "
                        f"puede usar. Pero apostar al ganador quedó en empate con la casa en "
                        f"las pruebas (4.744 apuestas, margen de error más grande que el "
                        f"resultado). Sirve para completar una combinada, no para sostenerla.")
            if ev_pct >= 0:
                return (f"Apenas {ev_pct:+.1f}% de valor, sobre un mercado donde además no hay "
                        f"ventaja demostrada. Estás pagando comisión a cambio de casi nada.")
            return (f"La casa paga {ev_pct:+.1f}% menos de lo que vale según el modelo, que "
                    f"le da {self.p*100:.0f}%. Es perder por definición.")

        if self.tier == "C":
            return (f"Apostar a KO o a sumisión no superó las pruebas de este proyecto. "
                    f"Que muestre {ev_pct:+.1f}% de valor no ayuda: las finalizaciones tienen "
                    f"cuotas altas justamente porque son poco probables, y eso se confunde "
                    f"fácil con tener ventaja.")

        return (f"No hay forma de evaluarla. El modelo opina ({self.p*100:.0f}%) pero de este "
                f"mercado no existen cuotas históricas, así que nadie sabe si esa opinión le "
                f"gana al precio.")


# --------------------------------------------------------------------------- #
# Generar las patas candidatas desde una cartelera ya predicha
# --------------------------------------------------------------------------- #
_METODO_TXT = {
    "KO": "por KO/TKO", "SUB": "por sumisión", "DEC": "por decisión",
    "FIN": "por finalización (KO o sumisión)",
}


def patas_de_cartelera(consenso: list[dict]) -> list[Pata]:
    """
    Convierte la salida de `card.predict_card(devolver_todo=True)` en la lista
    de patas que se pueden combinar, en los tres mercados de Betano.

    Solo entran las que tienen CUOTA REAL. Sin cuota no hay valor que calcular,
    así que la pata se omite en vez de mostrarla con un número inventado.
    """
    patas: list[Pata] = []
    for i, c in enumerate(consenso):
        fid = str(i)
        na, nb = c["a"], c["b"]
        pelea = f"{na} vs {nb}"
        pocos = c.get("pocos") or []
        aviso_datos = ([f"A {' y '.join(pocos)} le faltan datos en UFCStats."]
                       if pocos else [])

        # --- Quién gana (moneyline) ---
        v = c.get("v")
        if v is not None:
            sim = c["sim"]
            pm_a = getattr(v, "p_modelo_a", None)
            for lado, nombre, p in (("A", na, sim.p_a), ("B", nb, sim.p_b)):
                cuota = _decimal(v, lado)
                if cuota is None:
                    continue
                pm = None if pm_a is None else (pm_a if lado == "A" else 1 - pm_a)
                patas.append(Pata(
                    id=f"{fid}:ML:{lado}", fight_id=fid, pelea=pelea,
                    mercado="ganador", seleccion=f"Gana {nombre}",
                    clase=lado, p=float(p), cuota=cuota, tier="B",
                    p_modelo=None if pm is None else float(pm),
                    avisos=list(aviso_datos),
                ))

        # --- Método, 7 vías ---
        for op in (c.get("metodo6") or []):
            if "error" in op:
                continue
            clase = op["clase"]                      # "A_KO", "B_DEC", ...
            lado, met = clase.split("_")
            avisos = list(aviso_datos)
            if op.get("sospechoso"):
                avisos.append(
                    f"Las 6 cuotas de método de esta pelea suman "
                    f"{op['sobrerredondeo']:.3f}; una casa real suma 1,20-1,24.")
            patas.append(Pata(
                id=f"{fid}:M7:{clase}", fight_id=fid, pelea=pelea,
                mercado="metodo7",
                seleccion=f"Gana {na if lado == 'A' else nb} {_METODO_TXT[met]}",
                clase=clase, p=float(op["p_final"]), cuota=float(op["cuota_decimal"]),
                tier="A" if met == "DEC" else "C",
                p_modelo=float(op["p_modelo"]), avisos=avisos,
            ))

        # --- Método, 5 vías ---
        for op in (c.get("metodo5") or []):
            if "error" in op:
                continue
            clase = op["clase"]                      # "A_FIN", "B_DEC", ...
            lado, met = clase.split("_")
            avisos = list(aviso_datos)
            if op.get("sospechoso"):
                avisos.append(
                    f"Las 4 cuotas de este 5 vías suman {op['sobrerredondeo']:.3f}, "
                    f"más generoso de lo que ofrece una casa real.")
            patas.append(Pata(
                id=f"{fid}:M5:{clase}", fight_id=fid, pelea=pelea,
                mercado="metodo5",
                seleccion=f"Gana {na if lado == 'A' else nb} {_METODO_TXT[met]}",
                clase=clase, p=float(op["p_final"]), cuota=float(op["cuota_decimal"]),
                # La decisión es LA MISMA apuesta que en 7 vías, así que hereda su
                # respaldo. La finalización sigue siendo el lado que no lo tiene.
                tier="A" if met == "DEC" else "C",
                p_modelo=float(op["p_modelo"]), avisos=avisos,
            ))

    # Orden: primero lo que más respaldo tiene, y dentro de eso el mejor valor.
    patas.sort(key=lambda x: (TIERS[x.tier]["orden"], -x.ev))
    return patas


def conflicto(p1: Pata, p2: Pata) -> str | None:
    """
    None si se pueden combinar, o "excluyente" / "similar".

    Distintas peleas nunca chocan. Dentro de una pelea, decide la intersección
    de los desenlaces que cubre cada una: vacía = imposible que pasen las dos;
    no vacía = se solapan y Betano ya cobró esa información una vez.
    """
    if p1.fight_id != p2.fight_id:
        return None
    return "excluyente" if not (p1.cubre & p2.cubre) else "similar"


def _decimal(v, lado: str) -> float | None:
    """
    Cuota decimal de un lado del moneyline. El objeto Valor solo guarda la del
    lado que recomienda, así que la del otro se reconstruye desde la
    probabilidad de mercado y el vig, que sí están.
    """
    if lado == v.lado and math.isfinite(v.cuota_decimal):
        return float(v.cuota_decimal)
    p_mkt = v.p_mercado_a if lado == "A" else 1 - v.p_mercado_a
    if not math.isfinite(p_mkt) or p_mkt <= 0 or not math.isfinite(v.vig):
        return None
    # p_mercado viene SIN vig (normalizada). Se le devuelve para recuperar el
    # precio que la casa realmente ofrece.
    return float(1.0 / (p_mkt * (1.0 + v.vig)))


# --------------------------------------------------------------------------- #
# Evaluar una combinada
# --------------------------------------------------------------------------- #
def evaluar(patas: list[Pata], bankroll: float = 100.0) -> dict:
    """
    Matemática y veredicto de un parlay. `bankroll` solo escala la sugerencia
    de stake; no cambia ninguna conclusión.
    """
    n = len(patas)
    if n < MIN_PATAS:
        return {"ok": False, "error": f"Un parlay necesita al menos {MIN_PATAS} patas."}
    if n > MAX_PATAS:
        return {"ok": False, "error": f"Betano acepta máximo {MAX_PATAS} patas (tienes {n})."}

    # --- Correlación: dos patas de la misma pelea no son independientes ---
    por_pelea: dict[str, list[Pata]] = {}
    for p in patas:
        por_pelea.setdefault(p.fight_id, []).append(p)
    chocan = [ps for ps in por_pelea.values() if len(ps) > 1]
    if chocan:
        detalle = "; ".join(f"{ps[0].pelea}: {len(ps)} patas" for ps in chocan)
        return {"ok": False, "error":
                f"Hay patas de la misma pelea ({detalle}). No son independientes: "
                f"multiplicar sus probabilidades daría un número sin sentido, y Betano "
                f"tampoco suele dejar combinarlas fuera del 'bet builder'."}

    p_combo = 1.0
    cuota_combo = 1.0
    for p in patas:
        p_combo *= p.p
        cuota_combo *= p.cuota

    ev = p_combo * cuota_combo - 1.0
    b = cuota_combo - 1.0
    kelly_puro = (p_combo * b - (1 - p_combo)) / b if b > 0 else 0.0
    # Mismo criterio que value.kelly: 1/4 de Kelly con tope. En un parlay el
    # tope importa más todavía, porque la p tiene error multiplicado.
    kelly = max(0.0, min(kelly_puro * 0.25, 0.05))

    # --- FRAGILIDAD: el número que de verdad manda ---
    # Si cada p_i está sobreestimada un factor (1−d), el EV se vuelve
    # (1−d)^n · (1+EV) − 1. Se despeja la d que lo lleva a cero.
    if ev > 0:
        error_tolerable = 1.0 - (1.0 / (1.0 + ev)) ** (1.0 / n)
    else:
        error_tolerable = 0.0

    tiers = [p.tier for p in patas]
    n_a = tiers.count("A")
    n_ruido = tiers.count("C") + tiers.count("D")
    con_avisos = [p for p in patas if p.avisos]

    res = {
        "ok": True,
        "n_patas": n,
        "p_combinada": p_combo,
        "cuota_combinada": cuota_combo,
        "ev": ev,
        "kelly": kelly,
        "stake_sugerido": round(bankroll * kelly, 2),
        "pago_por_1000": round(1000 * cuota_combo, 0),
        "una_de_cada": round(1 / p_combo) if p_combo > 0 else float("inf"),
        "error_tolerable": error_tolerable,
        "n_probadas": n_a,
        "n_ruido": n_ruido,
        "n_con_avisos": len(con_avisos),
    }
    res["veredicto"], res["nivel"], res["motivos"] = _veredicto(patas, res)
    return res


def _veredicto(patas: list[Pata], r: dict) -> tuple[str, str, list[str]]:
    """El texto que resume si conviene o no, y los motivos concretos."""
    motivos: list[str] = []
    n = r["n_patas"]

    negativas = [p for p in patas if p.ev < 0]
    if negativas:
        motivos.append(
            f"{len(negativas)} de las {n} selecciones pagan menos de lo que valen, incluso "
            f"según el propio modelo. Una selección mala no se arregla combinándola con "
            f"otras: arrastra a todas hacia abajo.")

    if r["n_ruido"]:
        motivos.append(
            f"{r['n_ruido']} selección(es) vienen de mercados que no superaron las pruebas "
            f"de este proyecto. El valor que muestran no es prueba de nada.")

    if r["n_con_avisos"]:
        motivos.append(
            f"{r['n_con_avisos']} selección(es) tienen problemas de datos: un peleador sin "
            f"historial suficiente, o cuotas que parecen escritas a mano.")

    if r["p_combinada"] < 0.02:
        motivos.append(
            f"Cobrarías 1 de cada {r['una_de_cada']:,} veces. Aunque la matemática dé "
            f"positiva, harían falta miles de intentos para que eso se note — y en el "
            f"camino te quedas sin dinero.".replace(",", "."))

    if r["ev"] > 0:
        motivos.append(
            f"Cada pronóstico puede estar equivocado como máximo un {r['error_tolerable']*100:.1f}% "
            f"antes de que la combinada pase a perder, y los {n} tienen que cumplirlo al mismo "
            f"tiempo. Este modelo se equivoca de verdad, así que ese margen es lo primero "
            f"que hay que mirar.")

    # Nivel global.
    #
    # OJO CON UNA TENTACIÓN: 13 patas de tier A dan un EV combinado enorme
    # (13 patas al +5% = +88%) y sería fácil pintarlas de verde. Sería mentir.
    #
    # `error_tolerable` es el margen de error POR PATA, y con patas parecidas no
    # depende de n (13 patas al +5% toleran lo mismo que 2: 4,8%). Lo que sí
    # cambia con n es la probabilidad de que TODAS las patas estén dentro de ese
    # margen a la vez. Los errores independientes se suman en cuadratura, así
    # que el margen exigido crece como √n: con 4 patas se pide 4%, con 13 se
    # pide 7,2%. Por eso una combinada larga puede ser frágil aunque cada pata
    # suelta sea impecable.
    umbral_fragil = 0.04 * math.sqrt(n / 4.0)
    fragil = r["error_tolerable"] < umbral_fragil
    r["umbral_fragil"] = umbral_fragil
    if r["ev"] <= 0:
        nivel, ver = "malo", (
            f"No conviene. En conjunto paga {abs(r['ev'])*100:.1f}% MENOS de lo que vale, "
            f"o sea estás pagando por el privilegio de arriesgar. Empieza por sacar las "
            f"selecciones que ya de por sí pagan de menos.")
    elif r["n_ruido"] or r["n_con_avisos"]:
        nivel, ver = "malo", (
            f"No conviene como está. En el papel paga {r['ev']*100:.1f}% de más, pero ese "
            f"número se apoya en selecciones sin respaldo o con datos malos. Quítalas y "
            f"vuelve a mirar: lo que quede será poco, y será real.")
    elif r["n_probadas"] == n and not fragil:
        nivel, ver = "bueno", (
            f"Lo mejor que puede ofrecer este sistema. Las {n} selecciones son del único "
            f"mercado con ventaja demostrada, paga {r['ev']*100:.1f}% de más, y el margen de "
            f"error aguanta ({r['error_tolerable']*100:.1f}% por pronóstico). Aun así cobras "
            f"1 de cada {r['una_de_cada']} veces: apuesta poco.")
    elif r["n_probadas"] == n:
        nivel, ver = "aceptable", (
            f"Las selecciones son buenas, la combinada es frágil. Las {n} son del mercado con "
            f"ventaja demostrada y paga {r['ev']*100:.1f}% de más, pero cada pronóstico solo "
            f"puede errar un {r['error_tolerable']*100:.1f}% y con {n} juntos haría falta "
            f"{umbral_fragil*100:.1f}% para que aguanten todos a la vez. Las mismas "
            f"selecciones en combinadas de 2 o 3 rinden casi igual con mucho menos riesgo.")
    elif r["n_probadas"] >= max(2, n // 2):
        nivel, ver = "aceptable", (
            f"Se puede, con moderación. {r['n_probadas']} de {n} selecciones vienen del "
            f"mercado con ventaja demostrada; el resto son apuestas al ganador, donde no hay "
            f"ventaja probada. En conjunto paga {r['ev']*100:.1f}% de más.")
    else:
        nivel, ver = "flojo", (
            f"Floja. Paga {r['ev']*100:.1f}% de más, pero casi toda se apoya en apuestas al "
            f"ganador, donde las pruebas no encontraron ninguna ventaja. Ese número grande "
            f"sale de multiplicar ventajas que por separado no se distinguen de la suerte, "
            f"y multiplicar cosas inciertas no las vuelve seguras.")

    if n > 4 and r["ev"] > 0:
        motivos.append(
            f"Con {n} selecciones, el error de cada pronóstico se acumula. Las combinadas "
            f"cortas, de 2 a 4 selecciones con respaldo, son mucho más defendibles: rinden "
            f"casi lo mismo por unidad de riesgo y cobran muchísimo más seguido.")

    return ver, nivel, motivos


# Tope de la SUGERENCIA, no de lo que el usuario puede armar a mano (eso sigue
# en MAX_PATAS). Es el mismo consejo que da _veredicto: de 2 a 4 selecciones con
# respaldo rinden casi lo mismo por unidad de riesgo y cobran mucho más seguido.
MAX_SUGERIDAS = 4


def sugerir(patas: list[Pata], max_patas: int = MAX_SUGERIDAS) -> list[str]:
    """
    La mejor combinada que se puede armar con lo que hay. Devuelve los ids, o
    una lista vacía, que es un resultado normal.

    Tres reglas, las tres para no contradecir al resto de la pantalla:
      * solo selecciones que la propia UI marca "Conviene" o "Se puede"
        (veredicto "si"/"quizas"), una por pelea;
      * hasta MAX_SUGERIDAS, empezando por las de más respaldo y más valor;
      * si el evaluador calificaría la combinada de "flojo" o "malo", se van
        sacando las de menos respaldo; si no queda una combinada sana, nada.

    BUG QUE ESTO ARREGLA: antes filtraba por `apostable` (EV > 0) y el tope era
    13. Las de ganador con EV entre 0 y 3% la UI las marca "No conviene", y aun
    así entraban: en mkv.csv sugería 4 patas y las 4 decían "No conviene", y con
    12 peleas armaba combinadas de 12 que el evaluador calificaba de "flojo".
    """
    vistas: set[str] = set()
    elegidas: list[Pata] = []
    for p in sorted(patas, key=lambda x: (TIERS[x.tier]["orden"], -x.ev)):
        if p.veredicto() not in ("si", "quizas") or p.fight_id in vistas:
            continue
        vistas.add(p.fight_id)
        elegidas.append(p)
        if len(elegidas) >= max_patas:
            break
    while len(elegidas) >= MIN_PATAS and evaluar(elegidas)["nivel"] in ("flojo", "malo"):
        elegidas.pop()
    return [p.id for p in elegidas] if len(elegidas) >= MIN_PATAS else []
