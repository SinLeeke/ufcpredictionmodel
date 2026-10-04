"""La capa común: junta todas las fuentes detrás de una sola interfaz.

Flujo de un dato:
    fuente.obtener()  →  CotizacionCruda (nombres tal como los escribe la fuente)
    → cruce exacto de nombres contra la base (src/cuotas/cruce.py)
    → Cotización validada (conversion.cotizacion: en una casa, suma > 1)
    → SQLite (cuotas_historial, sin filas idénticas consecutivas)
    → /api/mercado/* lee de SQLite y responde al instante.

El polling corre en hilos de fondo, uno por fuente, para que una fuente lenta
(BFO tarda hasta 25 s) no atrase a Polymarket, que en vivo va cada 30 s. Una
fuente que falla solo se marca en su EstadoFuente: las demás siguen.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import threading
import time

import config as C
from src.cuotas import calendario, consenso as K, cruce, historial as H, registro
from src.cuotas.conversion import CuotaInvalida, cotizacion
from src.cuotas.tiempo import a_iso, ahora_iso

# Una cotización que nadie vuelve a confirmar en 4 días ya no describe el
# mercado (la cartelera se canceló o la fuente dejó de listarla).
VENTANA_VIGENCIA = 4 * 86400
# Las peleas de antes de ayer ya se pelearon: no se muestran como mercado.
DIAS_DESPUES = 1
TICK = 5.0
# Un mismo nombre no calzado se anota a lo más una vez cada 10 min (Polymarket
# lo vería cada 30 s); el contador `veces` sigue sirviendo de pista.
REGISTRO_CADA = 600


class Capa:
    def __init__(self, fuentes: list | None = None) -> None:
        self.fuentes = list(fuentes) if fuentes is not None else registro.fuentes()
        self._por_clave = {f.clave: f for f in self.fuentes}
        self._parar = threading.Event()
        self._hilos: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._anotados: dict[tuple, float] = {}
        self._peleas_vistas: dict[str, tuple] = {}
        self._oficiales_memo: tuple[float, dict] | None = None
        if not C.MERCADO_SIMULADO:
            # Modo simulado apagado = sin rastro, aunque haya quedado algo de
            # una sesión anterior con UFC_MERCADO_SIMULADO=1.
            try:
                H.borrar_fuente("simulada")
                H.borrar_no_calzados("simulada")
            except Exception:                            # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _excluir() -> tuple[str, ...]:
        return () if C.MERCADO_SIMULADO else ("simulada",)

    def _oficiales(self) -> dict[str, dict]:
        """pelea_id → evento/fecha/inicio de la cartelera oficial (caché de UFC.com, sin red)."""
        ahora = time.monotonic()
        if self._oficiales_memo and ahora - self._oficiales_memo[0] < 60:
            return self._oficiales_memo[1]
        salida: dict[str, dict] = {}
        try:
            from src import cartelera_completa
            eventos, _ = cartelera_completa.oficiales()
        except Exception:                                # noqa: BLE001
            eventos = []
        for e in eventos:
            inicio = e.get("inicio") or {}
            estelar = inicio.get("estelar")
            # Fecha local, igual que la portada (diaLocal) y engine._en_base.
            fecha = datetime.fromtimestamp(estelar).date().isoformat() if estelar else None
            for p in e.get("peleas") or []:
                try:
                    pid = cruce.pelea_id(p["a"], p["b"])
                except (KeyError, TypeError):
                    continue
                parte = inicio.get(p.get("seccion") or "estelar") or estelar
                salida[pid] = {"evento": e.get("nombre"), "fecha": fecha,
                               "inicio": a_iso(parte) if parte else None,
                               "a": p["a"], "b": p["b"]}
        self._oficiales_memo = (ahora, salida)
        return salida

    def _anotar(self, fuente: str, texto: str, motivo: str, evento) -> None:
        k = (fuente, texto, motivo)
        ahora = time.time()
        if ahora - self._anotados.get(k, 0) < REGISTRO_CADA:
            return
        self._anotados[k] = ahora
        try:
            H.registrar_no_calzado(fuente, texto, motivo, evento)
        except Exception:                                # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Ingesta
    # ------------------------------------------------------------------ #
    def ingerir(self, fuente, crudas: list[dict]) -> dict:
        """CotizacionCruda → historial. Nunca lanza: cada cruda falla sola."""
        stats = {"guardadas": 0, "iguales": 0, "rechazadas": 0, "descartadas": 0}
        oficiales = self._oficiales()
        for c in crudas or []:
            try:
                self._ingerir_una(fuente, c, oficiales, stats)
            except CuotaInvalida:
                stats["rechazadas"] += 1
                fuente.rechazadas += 1
            except Exception:                            # noqa: BLE001
                stats["rechazadas"] += 1
                fuente.rechazadas += 1
        return stats

    def _ingerir_una(self, fuente, c: dict, oficiales: dict, stats: dict) -> None:
        ta, tb = str(c.get("a_texto") or "").strip(), str(c.get("b_texto") or "").strip()
        if not ta or not tb:
            raise CuotaInvalida("faltan los nombres")
        ra, rb = cruce.resolver(ta, tb), cruce.resolver(tb, ta)
        if not ra.clave or not rb.clave or ra.clave == rb.clave:
            raise CuotaInvalida("pelea sin dos peleadores distintos")
        pid = "|".join(sorted((ra.clave, rb.clave)))
        of = oficiales.get(pid)
        evento = c.get("evento")
        for r, texto in ((ra, ta), (rb, tb)):
            if r.motivo:
                self._anotar(fuente.clave, texto, r.motivo, evento)
        if not fuente.solo_ufc and not of and not (ra.en_base and rb.en_base):
            # Fuente de todo MMA (The Odds API) y la pelea no es de UFC
            # reconocible: no entra, pero los nombres ya quedaron anotados.
            stats["descartadas"] += 1
            return
        # Orientación del contrato: `a` es el de la clave menor del pelea_id.
        invertida = ra.clave > rb.clave
        (x, tx), (y, ty) = ((rb, tb), (ra, ta)) if invertida else ((ra, ta), (rb, tb))
        if fuente.tipo == "mercado_prediccion":
            pa, pb = (c["b_prob"], c["a_prob"]) if invertida else (c["a_prob"], c["b_prob"])
            cot = cotizacion(fuente.clave, fuente.tipo, c.get("casa") or fuente.nombre, pid,
                             a_iso(c["timestamp"]), a_prob=pa, b_prob=pb)
        else:
            am_a, am_b = (c["b_americana"], c["a_americana"]) if invertida else (c["a_americana"], c["b_americana"])
            cot = cotizacion(fuente.clave, fuente.tipo, c.get("casa") or fuente.nombre, pid,
                             a_iso(c["timestamp"]), a_americana=am_a, b_americana=am_b)

        def nombre(r, texto, lado):
            if r.nombre:
                return r.nombre
            if of:                                       # literal de UFC.com
                return of["a"] if cruce.clave(of["a"]) == r.clave else of["b"]
            return texto
        meta = (nombre(x, tx, "a"), nombre(y, ty, "b"), x.id, y.id,
                (of or {}).get("evento") or evento, (of or {}).get("fecha") or c.get("fecha"),
                (of or {}).get("inicio") or c.get("inicio"), bool(of))
        if self._peleas_vistas.get(pid) != meta:
            H.guardar_pelea(pid, *meta)
            self._peleas_vistas[pid] = meta
        if H.guardar(cot):
            stats["guardadas"] += 1
        else:
            stats["iguales"] += 1

        serie = c.get("historial")
        if serie and fuente.tipo == "mercado_prediccion":
            puntos = []
            for p in serie:
                try:
                    pa, pb = (p["b_prob"], p["a_prob"]) if invertida else (p["a_prob"], p["b_prob"])
                    puntos.append(cotizacion(fuente.clave, fuente.tipo, cot["casa"], pid,
                                             a_iso(p["timestamp"]), a_prob=pa, b_prob=pb))
                except (CuotaInvalida, KeyError, TypeError, ValueError):
                    continue
            if puntos:
                H.importar_serie(puntos)

    def recibir_betano(self, cuotas, evento: str | None = None, fecha: str | None = None) -> dict:
        """Lo llama webui/engine.py con lo que su ciclo YA bajó. No hace red."""
        f = self._por_clave.get("betano")
        if f is None:
            return {}
        crudas = f.traducir(list(cuotas), evento, fecha)
        f.marcar_ok()
        return self.ingerir(f, crudas)

    # ------------------------------------------------------------------ #
    # Polling de fondo
    # ------------------------------------------------------------------ #
    def arrancar(self) -> None:
        with self._lock:
            self._parar.clear()
            for f in self.fuentes:
                if f.pasiva or (f.clave in self._hilos and self._hilos[f.clave].is_alive()):
                    continue
                h = threading.Thread(target=self._bucle, args=(f,), daemon=True,
                                     name=f"cuotas-{f.clave}")
                self._hilos[f.clave] = h
                h.start()

    def detener(self, esperar: float = 2.0) -> None:
        self._parar.set()
        for h in list(self._hilos.values()):
            h.join(timeout=esperar)
        self._hilos.clear()

    def consultar_todas(self) -> dict[str, dict | None]:
        """Una vuelta sincrónica por cada fuente consultable (diagnóstico y tests).

        Cada fuente en su propio try: una caída no impide consultar la siguiente.
        """
        salida: dict[str, dict | None] = {}
        for f in self.fuentes:
            if f.pasiva or not f.activa():
                continue
            crudas = f.ejecutar()
            salida[f.clave] = None if crudas is None else self.ingerir(f, crudas)
        return salida

    def _bucle(self, f) -> None:
        while not self._parar.is_set():
            try:
                espera = f.espera(calendario.en_vivo())
                if espera is not None and espera <= 0:
                    crudas = f.ejecutar()
                    if crudas:
                        self.ingerir(f, crudas)
                    continue
                self._parar.wait(TICK if espera is None else min(TICK, espera))
            except Exception:                            # noqa: BLE001
                # Nada de lo que pase en una fuente puede matar su hilo.
                self._parar.wait(TICK)

    # ------------------------------------------------------------------ #
    # Lecturas (endpoints): solo SQLite, nunca red
    # ------------------------------------------------------------------ #
    def peleas(self, evento: str | None = None) -> dict:
        desde = a_iso(time.time() - VENTANA_VIGENCIA)
        cots = H.ultimas(desde, self._excluir())
        por_pelea: dict[str, list[dict]] = {}
        for c in cots:
            por_pelea.setdefault(c["pelea_id"], []).append(c)
        metas = H.peleas(list(por_pelea))
        limite = (date.today() - timedelta(days=DIAS_DESPUES)).isoformat()
        filtro = " ".join(str(evento or "").lower().split())
        salida, actualizado = [], None
        for pid, lista in por_pelea.items():
            m = metas.get(pid)
            if m is None:
                continue
            if m["fecha"] and m["fecha"] < limite:
                continue
            if filtro and filtro != (m["fecha"] or "") and filtro not in " ".join(str(m["evento"] or "").lower().split()):
                continue
            lista.sort(key=lambda c: (c["fuente"], c["casa"]))
            for c in lista:
                if actualizado is None or c["visto"] > actualizado:
                    actualizado = c["visto"]
            salida.append({"pelea_id": pid, "a": m["a"], "b": m["b"], "a_id": m["a_id"], "b_id": m["b_id"],
                           "evento": m["evento"], "fecha": m["fecha"], "inicio": m["inicio"],
                           "oficial": m["oficial"], "cotizaciones": lista,
                           "consenso": K.consenso(lista), "mejor": K.mejor(lista)})
        salida.sort(key=lambda p: (p["fecha"] or "9999", p["inicio"] or "", p["pelea_id"]))
        return {"peleas": salida, "actualizado": actualizado}

    def cartelera(self, pares: list[tuple[str, str]]) -> dict:
        """{"<a>|<b>": Pelea orientada como la cartelera, o None}. a/b literales de /api/estado."""
        por_id = {p["pelea_id"]: p for p in self.peleas()["peleas"]}
        salida = {}
        for a, b in pares:
            k = f"{a}|{b}"
            try:
                pid = cruce.pelea_id(a, b)
            except Exception:                            # noqa: BLE001
                salida[k] = None
                continue
            p = por_id.get(pid)
            if p is None:
                salida[k] = None
                continue
            invertida = cruce.clave(a) != pid.split("|")[0]
            salida[k] = {**(K.invertir(p) if invertida else p), "invertida": invertida}
        return {"peleas": salida}

    def historial(self, pelea_id: str, desde=None, a: str | None = None) -> dict:
        desde_iso = None
        if desde not in (None, ""):
            try:
                desde_iso = a_iso(float(desde)) if str(desde).replace(".", "", 1).isdigit() else a_iso(desde)
            except (TypeError, ValueError):
                raise ValueError("`desde` tiene que ser ISO 8601 o epoch en segundos") from None
        invertida = bool(a) and "|" in pelea_id and cruce.clave(a) == pelea_id.split("|")[1]
        series: dict[tuple, dict] = {}
        for fuente, casa, tipo, t, am_a, am_b, pa, pb in H.serie(pelea_id, desde_iso, self._excluir()):
            s = series.setdefault((fuente, casa), {"fuente": fuente, "casa": casa, "tipo": tipo, "puntos": []})
            if invertida:
                am_a, am_b, pa, pb = am_b, am_a, pb, pa
            s["puntos"].append({"t": t, "a": am_a, "b": am_b, "pa": pa, "pb": pb})
        return {"pelea_id": pelea_id, "invertida": invertida,
                "series": sorted(series.values(), key=lambda s: (s["fuente"], s["casa"]))}

    def estado(self) -> dict:
        ev = calendario.evento_en_vivo()
        en_vivo = ev is not None
        # El evento falso sirve a la vista, pero los hilos solo aceleran por
        # un evento real. Informar esa misma cadencia evita prometer un
        # refresco de 2 min cuando The Odds API sigue consultando cada 12 h.
        en_vivo_real = calendario.en_vivo()
        try:
            hay = bool(self.peleas()["peleas"])
        except Exception:                                # noqa: BLE001
            hay = False
        try:
            no_calzados = H.resumen_no_calzados(excluir=self._excluir())
        except Exception:                                # noqa: BLE001
            no_calzados = {"total": 0, "por_motivo": {}, "recientes": []}
        return {"fuentes": [f.estado(en_vivo if f.clave == "simulada" else en_vivo_real)
                            for f in self.fuentes],
                "hay_cuotas": hay, "en_vivo": en_vivo,
                "evento": ({k: ev.get(k) for k in ("id", "nombre", "inicio", "estelar", "fin", "simulado")}
                           if ev else None),
                "simulado": bool(C.MERCADO_SIMULADO),
                "no_calzados": no_calzados,
                "consultado": ahora_iso()}


# ---------------------------------------------------------------------- #
# Instancia única de la app
# ---------------------------------------------------------------------- #
_CAPA: Capa | None = None
_CAPA_LOCK = threading.Lock()


def capa() -> Capa:
    global _CAPA
    with _CAPA_LOCK:
        if _CAPA is None:
            _CAPA = Capa()
        return _CAPA


def arrancar() -> None:
    capa().arrancar()


def detener() -> None:
    if _CAPA is not None:
        _CAPA.detener()


def recibir_betano(cuotas, evento: str | None = None, fecha: str | None = None) -> dict:
    return capa().recibir_betano(cuotas, evento, fecha)
