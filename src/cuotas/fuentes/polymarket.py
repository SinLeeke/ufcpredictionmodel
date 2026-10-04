"""Polymarket: mercado de predicción, datos públicos y sin API key.

Es la fuente principal del historial del gráfico en vivo: su CLOB guarda la
serie de precios de cada mercado, así que el gráfico puede partir con horas
de datos en vez de vacío.

- Gamma API (gamma-api.polymarket.com) para DESCUBRIR las peleas: eventos con
  el tag "UFC" (id 279, descubierto con GET /tags/slug/ufc) y, dentro de cada
  uno, el mercado `sportsMarketType == "moneyline"` con sus dos tokens.
  Polymarket arma un evento por pelea ("UFC 332: A vs. B (Peso, Main Card)")
  con ~19 mercados; solo interesa el de ganador.
- CLOB API (clob.polymarket.com) para el PRECIO (POST /midpoints, todos los
  tokens en una llamada) y el HISTORIAL (GET /prices-history por token).

Límites documentados (docs.polymarket.com, "Rate limits", 2026): Gamma 4.000
req/10 s en general, /events 500/10 s, /tags 200/10 s; CLOB /midpoints 500/10 s,
/prices-history 1.000/10 s. Acá se usa una fracción ínfima: en vivo, una
llamada a /midpoints cada 30 s y el descubrimiento cada 10 min; el historial,
una vez por mercado cada 6 h. Igual se deja 0,5 s entre peticiones (scraping
educado) y, si alguna vez responde 429, la capa aplica backoff exponencial.

Precios = probabilidades. La americana sale de prob_a_americana (contrato 2.2).
"""
from __future__ import annotations

import json
import time
from decimal import Decimal, InvalidOperation

import requests

import config as C
from src.cuotas import historial as H
from src.cuotas.fuentes.base import Fuente, FuenteError, LimiteTasa
from src.cuotas.tiempo import a_iso, ahora_iso

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
TAG_UFC = 279                   # GET /tags/slug/ufc → {"id": "279", "label": "UFC"}
HEADERS = {"User-Agent": "UFCFightPredictor/1.0", "Accept": "application/json"}
PAUSA = 0.5
CACHE = "polymarket"

INTERVALO_VIVO = 30
INTERVALO_FUERA = 15 * 60
DESCUBRIR_VIVO = 10 * 60
DESCUBRIR_FUERA = 30 * 60
HISTORIAL_CADA = 6 * 3600
# Solo se baja la serie de peleas cercanas: las de dentro de 2 meses no
# necesitan gráfico todavía y serían decenas de llamadas por nada.
HISTORIAL_HORIZONTE = 21 * 86400
HISTORIAL_MAX_POR_CICLO = 40
# Regla de Polymarket para mostrar un precio: spread ≤ 0,10 → punto medio.
SPREAD_MAX = 0.10
# El mismo descubrimiento incluye cierres recientes para poder comprobar su
# resolución. La consulta mantiene su cadencia y no agrega llamadas por pelea.
CIERRES_HORIZONTE = 24 * 3600


def _lista(valor) -> list:
    """Gamma manda outcomes / clobTokenIds como TEXTO con JSON adentro."""
    if isinstance(valor, list):
        return valor
    try:
        v = json.loads(valor or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if 0.0 < v < 1.0 else None


def resultado_de_mercado(m: dict) -> str | None:
    """Ganador solo con resolución final y precios exactos 1/0.

    Gamma distingue una propuesta de una resolución final. Un cierre, una
    suspensión o un precio 0,999 que la UI redondea a 100 % no son resultado.
    Decimal impide convertir por redondeo una cadena casi 1 en un 1 exacto.
    """
    if m.get("closed") is not True or m.get("umaResolutionStatus") != "resolved":
        return None
    nombres, valores = _lista(m.get("outcomes")), _lista(m.get("outcomePrices"))
    if len(nombres) != 2 or len(valores) != 2 or not all(isinstance(n, str) and n.strip() for n in nombres):
        return None
    if nombres[0] == nombres[1]:
        return None
    try:
        precios = [Decimal(str(v)) for v in valores]
    except InvalidOperation:
        return None
    if not all(p.is_finite() for p in precios):
        return None
    if precios == [Decimal(1), Decimal(0)]:
        return nombres[0]
    if precios == [Decimal(0), Decimal(1)]:
        return nombres[1]
    return None


def resueltos_de_eventos(eventos: list[dict]) -> list[dict]:
    """Metadata final aparte: jamás se ingiere como cuotas activas o consenso."""
    salida = []
    for e in eventos:
        if not isinstance(e, dict):
            continue
        for m in e.get("markets") or []:
            if not isinstance(m, dict) or m.get("sportsMarketType") != "moneyline":
                continue
            ganador = resultado_de_mercado(m)
            if ganador is None:
                continue
            inicio = None
            for campo in (m.get("gameStartTime"), e.get("startTime")):
                try:
                    inicio = a_iso(campo)
                except (TypeError, ValueError):
                    inicio = None
                if inicio:
                    break
            nombres = _lista(m.get("outcomes"))
            salida.append({"a": nombres[0], "b": nombres[1], "ganador": ganador,
                "evento": str(e.get("title") or "").split(":")[0].strip() or None,
                "fecha": e.get("eventDate"), "inicio": inicio,
                "closed": True, "umaResolutionStatus": "resolved",
                "outcomes": nombres, "outcomePrices": _lista(m.get("outcomePrices"))})
    return salida


def mercados_de_eventos(eventos: list[dict]) -> list[dict]:
    """Del JSON de Gamma /events, los moneyline de pelea con sus dos tokens."""
    salida = []
    for e in eventos:
        if not isinstance(e, dict) or e.get("closed") or e.get("active") is False:
            continue
        titulo = str(e.get("title") or "")
        for m in e.get("markets") or []:
            if m.get("sportsMarketType") != "moneyline" or m.get("closed"):
                continue
            nombres, tokens = _lista(m.get("outcomes")), _lista(m.get("clobTokenIds"))
            if len(nombres) != 2 or len(tokens) != 2 or nombres[0] == nombres[1]:
                continue
            precios = [_num(p) for p in _lista(m.get("outcomePrices"))] or [None, None]
            inicio = None
            for campo in (m.get("gameStartTime"), e.get("startTime")):
                try:
                    inicio = a_iso(campo)
                except ValueError:
                    inicio = None
                if inicio:
                    break
            salida.append({
                "slug": e.get("slug"),
                # "UFC 332: A vs. B (...)" → "UFC 332"; "UFC Fight Night: ..." → "UFC Fight Night"
                "evento": titulo.split(":")[0].strip() or None,
                "fecha": e.get("eventDate"), "inicio": inicio,
                "a": str(nombres[0]), "b": str(nombres[1]),
                "tokens": [str(tokens[0]), str(tokens[1])],
                "gamma": precios + [None] * (2 - len(precios)),
            })
    return salida


class Polymarket(Fuente):
    clave = "polymarket"
    nombre = "Polymarket"
    tipo = "mercado_prediccion"

    def __init__(self) -> None:
        super().__init__()
        self._en_vivo = False
        self._sesion = requests.Session()

    def intervalo(self, en_vivo: bool) -> int:
        self._en_vivo = en_vivo
        return INTERVALO_VIVO if en_vivo else INTERVALO_FUERA

    # --- red ---------------------------------------------------------------- #
    def _pedir(self, metodo: str, url: str, **kw):
        try:
            r = self._sesion.request(metodo, url, headers=HEADERS, timeout=C.REQUEST_TIMEOUT_SEC, **kw)
        except requests.RequestException as e:
            raise FuenteError(f"Sin conexión con Polymarket ({type(e).__name__})") from None
        if r.status_code == 429:
            try:
                reintentar = float(r.headers.get("Retry-After"))
            except (TypeError, ValueError):
                reintentar = None
            raise LimiteTasa("Polymarket respondió HTTP 429", reintentar_en=reintentar)
        if r.status_code != 200:
            raise FuenteError(f"Polymarket respondió HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise FuenteError("Polymarket devolvió algo que no es JSON") from None

    def _descubrir(self, cache: dict) -> list[dict]:
        ahora = time.time()
        ttl = DESCUBRIR_VIVO if self._en_vivo else DESCUBRIR_FUERA
        if cache.get("mercados") is not None and ahora - cache.get("consultado", 0) < ttl:
            return cache["mercados"]
        eventos, offset = [], 0
        while True:
            lote = self._pedir("GET", f"{GAMMA}/events", params={
                "tag_id": TAG_UFC, "end_date_min": a_iso(ahora - CIERRES_HORIZONTE),
                "limit": 100, "offset": offset})
            if not isinstance(lote, list):
                raise FuenteError("Gamma devolvió un formato inesperado")
            eventos.extend(lote)
            if len(lote) < 100 or offset >= 900:
                break
            offset += 100
            time.sleep(PAUSA)
        mercados = mercados_de_eventos(eventos)
        cache["mercados"], cache["consultado"] = mercados, ahora
        cache["resueltos"] = resueltos_de_eventos(eventos)
        return mercados

    def _lote(self, ruta: str, tokens: list[str]) -> dict[str, float]:
        """POST /midpoints, /spreads o /last-trades-prices para muchos tokens a la vez."""
        salida: dict[str, float] = {}
        for i in range(0, len(tokens), 100):
            if i:
                time.sleep(PAUSA)
            r = self._pedir("POST", f"{CLOB}/{ruta}", json=[{"token_id": t} for t in tokens[i:i + 100]])
            # /midpoints y /spreads: {token: "0.43"}; /last-trades-prices: [{token_id, price}].
            pares = r.items() if isinstance(r, dict) else (
                ((x.get("token_id"), x.get("price")) for x in r if isinstance(x, dict)) if isinstance(r, list) else ())
            for t, v in pares:
                try:
                    salida[str(t)] = float(v)
                except (TypeError, ValueError):
                    pass
        return salida

    def _precios(self, mercados: list[dict]) -> dict[str, float]:
        """El precio que muestra el propio Polymarket: el punto medio del libro si
        el spread es de 10 centavos o menos; si no, el último precio transado.

        Sin esa regla, un mercado recién abierto (compra a 0,01, venta a 0,99)
        daba un punto medio de 0,50 que nadie transó: medido el 3-oct-2026, las
        11 peleas del 17-oct salían "parejas" a −100/−100 por eso.
        """
        tokens = [t for m in mercados for t in m["tokens"]]
        medios = self._lote("midpoints", tokens)
        time.sleep(PAUSA)
        spreads = self._lote("spreads", tokens)
        anchos = [t for t in tokens if spreads.get(t) is None or spreads[t] > SPREAD_MAX]
        ultimos = {}
        if anchos:
            time.sleep(PAUSA)
            ultimos = self._lote("last-trades-prices", anchos)
        precios: dict[str, float] = {}
        for t in tokens:
            p = medios.get(t) if t not in anchos else ultimos.get(t)
            if p is not None and 0.0 < p < 1.0:
                precios[t] = p
        return precios

    def _historial(self, m: dict, cache: dict) -> list[dict] | None:
        """Serie del token de A; la de B es el complemento (mercado binario)."""
        ultimos = cache.setdefault("historial", {})
        ahora = time.time()
        if ahora - ultimos.get(m["tokens"][0], 0) < HISTORIAL_CADA:
            return None
        try:
            r = self._pedir("GET", f"{CLOB}/prices-history",
                            params={"market": m["tokens"][0], "interval": "max", "fidelity": 60})
        except LimiteTasa:
            raise
        except FuenteError:
            return None                   # sin serie se sigue con el precio actual
        ultimos[m["tokens"][0]] = ahora
        puntos = []
        for x in (r or {}).get("history") or []:
            p = _num(x.get("p")) if isinstance(x, dict) else None
            if p is None or not isinstance(x.get("t"), (int, float)):
                continue
            puntos.append({"timestamp": a_iso(x["t"]), "a_prob": p, "b_prob": round(1 - p, 6)})
        return puntos

    def obtener(self) -> list[dict]:
        cache = H.leer_cache(CACHE) or {}
        try:
            mercados = self._descubrir(cache)
            if not mercados:
                return []
            time.sleep(PAUSA)
            try:
                precios = self._precios(mercados)
            except LimiteTasa:
                raise
            except FuenteError:
                precios = None            # CLOB caído: se cae a los precios de Gamma (algo atrasados)
            ts, ahora = ahora_iso(), time.time()
            crudas, pedidos = [], 0
            clob_ok = precios is not None
            precios = precios or {}
            for m in mercados:
                pa, pb = precios.get(m["tokens"][0]), precios.get(m["tokens"][1])
                # Mercado binario: si solo un lado tiene precio, el otro es el complemento.
                if pa is None and pb is not None:
                    pa = round(1 - pb, 6)
                elif pb is None and pa is not None:
                    pb = round(1 - pa, 6)
                if (pa is None or pb is None) and not clob_ok:
                    # El CLOB no respondió nada: se usan los precios de Gamma, salvo
                    # el 0,50/0,50 con que nace todo mercado sin transacciones.
                    pa, pb = m["gamma"][0], m["gamma"][1]
                    if pa == 0.5 and pb == 0.5:
                        continue
                if pa is None or pb is None:
                    continue
                cruda = {"fuente": self.clave, "casa": "Polymarket", "evento": m["evento"],
                         "fecha": m["fecha"], "inicio": m["inicio"],
                         "a_texto": m["a"], "b_texto": m["b"],
                         "a_prob": pa, "b_prob": pb, "timestamp": ts}
                cerca = m["inicio"] and -12 * 3600 < _epoch(m["inicio"]) - ahora < HISTORIAL_HORIZONTE
                if cerca and pedidos < HISTORIAL_MAX_POR_CICLO:
                    antes = cache.get("historial", {}).get(m["tokens"][0], 0)
                    if ahora - antes >= HISTORIAL_CADA:
                        time.sleep(PAUSA)
                        pedidos += 1
                    serie = self._historial(m, cache)
                    if serie:
                        cruda["historial"] = serie
                crudas.append(cruda)
            # Se olvidan los tokens de mercados que ya cerraron: si no, la
            # caché crecería con cada cartelera.
            vigentes = {m["tokens"][0] for m in mercados}
            cache["historial"] = {t: v for t, v in cache.get("historial", {}).items() if t in vigentes}
            return crudas
        finally:
            try:
                H.escribir_cache(CACHE, cache)
            except Exception:                             # noqa: BLE001
                pass


def _epoch(iso: str) -> float:
    from src.cuotas.tiempo import a_epoch
    return a_epoch(iso)
