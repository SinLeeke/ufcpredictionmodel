"""The Odds API: moneyline de MMA de varias casas de EE. UU. en una sola llamada.

Plan gratis: 500 créditos al mes; cada llamada a /odds cuesta mercados ×
regiones = 1 crédito (h2h, una región). Por eso:

- UNA llamada trae todas las peleas de MMA: nunca pelea por pelea.
- Cada 2 min solo durante un evento en vivo; fuera de eso cada 12 h.
- Se leen x-requests-remaining / x-requests-used en cada respuesta. Con pocos
  créditos se baja la frecuencia sola (10 min en vivo, 24 h fuera) y con casi
  ninguno se suspende hasta que el plan se renueve. Un evento entero a 2 min
  son ~180 créditos: sin este freno, dos eventos al mes vaciarían el plan.
- La última llamada y los créditos sobreviven a un reinicio (cuotas_cache):
  reabrir la UI no vuelve a gastar.

La clave sale de config.ODDS_API_KEY (.env) y NUNCA se imprime: requests mete
la URL completa (con apiKey) en el texto de sus excepciones, así que ninguna
se propaga tal cual.
"""
from __future__ import annotations

import requests

import config as C
from src.cuotas import historial as H
from src.cuotas.fuentes.base import Fuente, FuenteError, LimiteTasa
from src.cuotas.tiempo import a_iso, ahora_iso

URL = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds"
CACHE = "odds_api"

INTERVALO_VIVO = 120
INTERVALO_FUTURO = 12 * 3600
# Con menos de 100 créditos quedan ~8 h de polling en vivo a 2 min: se pasa a
# 10 min (y a 24 h fuera de evento) para que alcance hasta fin de mes.
CREDITOS_BAJOS = 100
INTERVALO_VIVO_BAJOS = 600
INTERVALO_FUTURO_BAJOS = 24 * 3600
# Con menos de esto se deja de llamar: un intento por día para notar la renovación.
CREDITOS_AGOTADOS = 5


class OddsAPI(Fuente):
    clave = "odds_api"
    nombre = "The Odds API"
    tipo = "casa"
    # Trae todo MMA (PFL, Bellator...): solo entran las peleas que calzan.
    solo_ufc = False

    def __init__(self) -> None:
        super().__init__()
        guardado = H.leer_cache(CACHE) or {}
        self._restantes = guardado.get("restantes")
        self._usados = guardado.get("usados")
        # Así un reinicio respeta el intervalo en vez de llamar al tiro.
        self._ultimo_intento = guardado.get("ultimo_intento")
        self._clave_rechazada = False

    # --- configuración ----------------------------------------------------- #
    def _key(self) -> str:
        return C.ODDS_API_KEY or ""

    def activa(self) -> bool:
        return bool(self._key())

    def motivo_inactiva(self) -> str | None:
        return "Falta ODDS_API_KEY en el .env: The Odds API queda desactivada" if not self._key() else None

    def creditos(self) -> dict | None:
        if self._restantes is None and self._usados is None:
            return None
        return {"restantes": self._restantes, "usados": self._usados, "bajos": self._bajos()}

    def _bajos(self) -> bool:
        return self._restantes is not None and self._restantes < CREDITOS_BAJOS

    def intervalo(self, en_vivo: bool) -> int:
        if self._clave_rechazada or (self._restantes is not None and self._restantes < CREDITOS_AGOTADOS):
            return INTERVALO_FUTURO_BAJOS
        if self._bajos():
            return INTERVALO_VIVO_BAJOS if en_vivo else INTERVALO_FUTURO_BAJOS
        return INTERVALO_VIVO if en_vivo else INTERVALO_FUTURO

    # --- red ---------------------------------------------------------------- #
    def _leer_creditos(self, r) -> None:
        def entero(nombre):
            try:
                return int(float(r.headers.get(nombre)))
            except (TypeError, ValueError):
                return None
        restantes, usados = entero("x-requests-remaining"), entero("x-requests-used")
        if restantes is not None:
            self._restantes = restantes
        if usados is not None:
            self._usados = usados

    def _persistir(self) -> None:
        try:
            H.escribir_cache(CACHE, {"restantes": self._restantes, "usados": self._usados,
                                     "ultimo_intento": self._ultimo_intento})
        except Exception:                                 # noqa: BLE001
            pass

    def obtener(self) -> list[dict]:
        key = self._key()
        if not key:
            raise FuenteError(self.motivo_inactiva())
        params = {"apiKey": key, "regions": C.ODDS_API_REGION, "markets": "h2h",
                  "oddsFormat": "american", "dateFormat": "iso"}
        try:
            r = requests.get(URL, params=params, headers={"User-Agent": "UFCFightPredictor/1.0"},
                             timeout=C.REQUEST_TIMEOUT_SEC)
        except requests.RequestException as e:
            # Solo el tipo: el texto de la excepción incluye la URL con la clave.
            raise FuenteError(f"Sin conexión con The Odds API ({type(e).__name__})") from None
        finally:
            self._persistir()
        self._leer_creditos(r)
        self._persistir()
        if r.status_code == 429:
            raise LimiteTasa("The Odds API respondió HTTP 429 (límite o créditos agotados)",
                             reintentar_en=_segundos(r.headers.get("Retry-After")))
        if r.status_code == 401:
            self._clave_rechazada = True
            raise FuenteError("The Odds API rechazó la ODDS_API_KEY (HTTP 401)")
        if r.status_code != 200:
            raise FuenteError(f"The Odds API respondió HTTP {r.status_code}")
        self._clave_rechazada = False
        try:
            datos = r.json()
        except ValueError:
            raise FuenteError("The Odds API devolvió algo que no es JSON") from None
        crudas = self.traducir(datos)
        if self._restantes is not None and self._restantes < CREDITOS_AGOTADOS:
            # Las cuotas de esta llamada sirven, pero el estado tiene que avisar.
            self._motivo_extra = "Créditos casi agotados: se pausa hasta que se renueve el plan"
        return crudas

    def ejecutar(self):
        self._motivo_extra = None
        crudas = super().ejecutar()
        if crudas is not None and self._motivo_extra:
            self.marcar_error(self._motivo_extra)
        return crudas

    def traducir(self, datos) -> list[dict]:
        from src import cuotas_fuentes
        try:
            eventos = cuotas_fuentes.parsear_odds_api(datos, formato="american")
        except ValueError:
            raise FuenteError("The Odds API devolvió un formato inesperado") from None
        ts = ahora_iso()
        crudas = []
        for e in eventos:
            inicio = None
            try:
                inicio = a_iso(e.get("fecha"))
            except ValueError:
                pass
            for p in e["peleas"]:
                for casa in p["casas"].values():
                    crudas.append({"fuente": self.clave, "casa": casa["casa"], "evento": None,
                                   "fecha": inicio[:10] if inicio else None, "inicio": inicio,
                                   "a_texto": p["a"], "b_texto": p["b"],
                                   "a_americana": int(round(casa["a"])),
                                   "b_americana": int(round(casa["b"])),
                                   # El instante en que la VIMOS, como las demás fuentes: así
                                   # `visto` avanza aunque la casa no toque la línea.
                                   "timestamp": ts})
        return crudas


def _segundos(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None
