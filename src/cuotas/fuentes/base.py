"""Interfaz común de una fuente de cuotas (contrato 2.1) y su contabilidad.

Cada fuente implementa `obtener()` y `intervalo()`. Lo demás (estado, errores,
backoff ante 429) vive acá para que todas se comporten igual y para que una
fuente caída nunca tumbe a las otras: `ejecutar()` atrapa TODO.

Mensajes de error: nunca se usa `str(excepcion)` de requests, porque la URL
de The Odds API lleva la apiKey y requests la repite en el mensaje. Solo el
tipo de la excepción o un texto armado a mano.
"""
from __future__ import annotations

import threading
import time

import requests

from src.cuotas.tiempo import a_iso

# Backoff ante 429: 30 s, 60 s, 120 s... hasta 30 min. Se reinicia al primer OK.
BACKOFF_BASE_SEG = 30
BACKOFF_MAX_SEG = 30 * 60


class FuenteError(Exception):
    """Error con un mensaje ya seguro para mostrar (sin URLs ni claves)."""


class LimiteTasa(FuenteError):
    """HTTP 429: la fuente pide bajar el ritmo."""

    def __init__(self, mensaje: str = "HTTP 429: límite de peticiones", reintentar_en: float | None = None):
        super().__init__(mensaje)
        self.reintentar_en = reintentar_en


class Fuente:
    clave = ""
    nombre = ""
    tipo = "casa"            # "casa" | "mercado_prediccion"
    pasiva = False           # True = no se le pide nada: le entregan (Betano)
    # Una fuente que solo trae UFC (BFO filtra por título, Polymarket por tag)
    # mete todas sus peleas; una que trae todo MMA (The Odds API) solo las que
    # calzan con la base o con la cartelera oficial, para no colar PFL.
    solo_ufc = True

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ultimo_ok: str | None = None
        self._ultimo_error: str | None = None
        self._motivo: str | None = None
        self._ultimo_intento: float | None = None
        self._n429 = 0
        self._backoff_hasta = 0.0
        self.rechazadas = 0

    # --- lo que implementa cada fuente ------------------------------------- #
    def intervalo(self, en_vivo: bool) -> int | None:
        raise NotImplementedError

    def obtener(self) -> list[dict]:
        raise NotImplementedError

    def activa(self) -> bool:
        """False = desactivada por configuración (p. ej. sin API key)."""
        return True

    def motivo_inactiva(self) -> str | None:
        return None

    def creditos(self) -> dict | None:
        return None

    # --- común ------------------------------------------------------------- #
    def ejecutar(self) -> list[dict] | None:
        """obtener() sin dejar escapar nada. None si falló."""
        with self._lock:
            self._ultimo_intento = time.time()
            # `rechazadas` cuenta solo la última vuelta: acumulado, un mismo
            # mercado roto de Polymarket lo inflaría cada 30 s sin decir nada nuevo.
            self.rechazadas = 0
        try:
            crudas = self.obtener()
        except LimiteTasa as e:
            with self._lock:
                self._n429 += 1
                espera = min(BACKOFF_BASE_SEG * 2 ** (self._n429 - 1), BACKOFF_MAX_SEG)
                if e.reintentar_en:
                    espera = max(espera, min(float(e.reintentar_en), BACKOFF_MAX_SEG))
                self._backoff_hasta = time.time() + espera
            self.marcar_error(f"{e} — se reintenta en {int(espera)} s")
            return None
        except FuenteError as e:
            self.marcar_error(str(e))
            return None
        except requests.RequestException as e:
            self.marcar_error(f"Sin conexión con {self.nombre} ({type(e).__name__})")
            return None
        except Exception as e:                           # noqa: BLE001
            self.marcar_error(f"{self.nombre} falló ({type(e).__name__})")
            return None
        with self._lock:
            self._n429 = 0
            self._backoff_hasta = 0.0
        self.marcar_ok()
        return crudas

    def marcar_ok(self, cuando: float | None = None) -> None:
        with self._lock:
            self._ultimo_ok = a_iso(cuando if cuando is not None else time.time())
            self._motivo = None

    def marcar_error(self, mensaje: str) -> None:
        with self._lock:
            self._ultimo_error = a_iso(time.time())
            self._motivo = mensaje

    def espera(self, en_vivo: bool) -> float | None:
        """Segundos hasta la próxima consulta (0 = ya). None = no se consulta."""
        if self.pasiva or not self.activa():
            return None
        iv = self.intervalo(en_vivo)
        if iv is None:
            return None
        with self._lock:
            ahora = time.time()
            if self._backoff_hasta > ahora:
                return self._backoff_hasta - ahora
            if self._ultimo_intento is None:
                return 0.0
            return max(0.0, self._ultimo_intento + iv - ahora)

    def estado(self, en_vivo: bool = False) -> dict:
        """EstadoFuente del contrato (+ `rechazadas`, que el contrato admite como extra)."""
        activa = self.activa()
        with self._lock:
            motivo = self.motivo_inactiva() if not activa else self._motivo
            return {"clave": self.clave, "nombre": self.nombre, "tipo": self.tipo,
                    "activa": activa, "motivo": motivo,
                    "ultimo_ok": self._ultimo_ok, "ultimo_error": self._ultimo_error,
                    "intervalo_seg": None if self.pasiva or not activa else self.intervalo(en_vivo),
                    "creditos": self.creditos(),
                    "rechazadas": self.rechazadas}
