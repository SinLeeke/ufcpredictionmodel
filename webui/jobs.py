"""
jobs.py
Runner de los procesos largos del proyecto (actualizar la BD, reentrenar,
backtests, scrapers) para poder dispararlos desde la UI y ver el log en vivo.

Por qué SUBPROCESO y no llamar a las funciones directamente:

  * `modelado/train_model.py` y los backtests son scripts pensados para consola: imprimen
    a stdout y algunos terminan con `SystemExit`. Importarlos y llamarlos dentro
    del servidor haría que un fallo se lleve puesta la UI.
  * Corren minutos. En un hilo del servidor bloquearían las peticiones.
  * Recargan modelos y CSVs desde disco. Un subproceso arranca limpio, así que
    no hay estado viejo cacheado en memoria entre corridas.

Solo se permite UN trabajo pesado a la vez, a propósito: casi todos escriben en
`data/processed/` y dos a la vez se pisarían los archivos.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINEAS = 4000        # tope del buffer de log por trabajo


# --------------------------------------------------------------------------- #
# Catálogo: lo mismo que hay en los .bat, pero declarado en un solo lugar
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Receta:
    id: str
    nombre: str
    descripcion: str
    pasos: list[list[str]]
    minutos: str


RECETAS: dict[str, Receta] = {r.id: r for r in [
    Receta(
        id="actualizar_bd",
        nombre="Actualizar BD + reentrenar",
        descripcion=("Lo de todos los meses. Baja de UFCStats los eventos nuevos, sus "
                     "estadísticas por pelea y las fichas de quien debutó, los reemplazos "
                     "de Wikipedia y la versión nueva del dataset de Kaggle (si no se "
                     "puede, sigue con la copia que hay), reconstruye features/ELO y "
                     "reentrena los dos modelos. Al final imprime las métricas: míralas."),
        # Todos son incrementales: cada paso pide solo lo que falta. Las stats por
        # pelea estaban fuera y solo se actualizaban con la descarga profunda, así
        # que el control y la defensa real de cada peleador al predecir se
        # quedaban congelados en la última descarga profunda.
        pasos=[
            [sys.executable, "-m", "src.ufcstats_events"],
            [sys.executable, "-m", "src.ufcstats_fighters"],
            [sys.executable, "-m", "src.ufcstats_fightstats"],
            [sys.executable, "-m", "src.reemplazos"],
            [sys.executable, "-m", "src.scraper", "--refrescar-kaggle"],
            [sys.executable, "-m", "modelado.train_model"],
        ],
        minutos="5-12 min",
    ),
    Receta(
        id="entrenar",
        nombre="Solo reentrenar el modelo",
        descripcion=("Reentrena ganador y método con los datos que ya hay en disco, sin "
                     "bajar nada. Útil si tocaste config.py."),
        pasos=[[sys.executable, "-m", "modelado.train_model"]],
        minutos="~1 min",
    ),
    Receta(
        id="ufcstats_full",
        nombre="Bajar todo UFCStats",
        descripcion=("Actualización profunda: eventos, biometría y estadísticas por pelea "
                     "(incluido el desglose por asalto). Reanudable: si se corta, al "
                     "volver a lanzarlo retoma donde quedó."),
        pasos=[
            [sys.executable, "-m", "src.ufcstats_events"],
            [sys.executable, "-m", "src.ufcstats_fighters"],
            [sys.executable, "-m", "src.ufcstats_fightstats"],
        ],
        minutos="20-25 min la primera vez",
    ),
    Receta(
        id="bfo",
        nombre="Cuotas históricas recientes",
        descripcion=("Rellena con BestFightOdds el hueco de ~4 meses que arrastra el "
                     "dataset de Kaggle. Correr antes de los backtests de valor."),
        pasos=[[sys.executable, "-m", "src.bfo_odds"]],
        minutos="~12 min",
    ),
    Receta(
        id="backtest_valor",
        nombre="Recalcular el calibrador de ganador",
        descripcion=("Walk-forward del moneyline (2016→hoy). Regenera "
                     "models/calibrador_mercado.pkl, que es lo que permite mezclar modelo "
                     "y mercado. Correr DESPUÉS de reentrenar."),
        pasos=[[sys.executable, "-m", "modelado.backtest_valor", "--refit"]],
        minutos="~2 min",
    ),
    Receta(
        id="backtest_metodo",
        nombre="Recalcular el mercado de método",
        descripcion=("Walk-forward del mercado de 6 vías. Regenera metodo6_xgb.pkl y "
                     "calibrador_metodo.pkl, que es de donde sale la única ventaja "
                     "probada del proyecto."),
        pasos=[[sys.executable, "-m", "modelado.backtest_metodo", "--refit"]],
        minutos="~3 min",
    ),
    Receta(
        id="backtest_carteleras",
        nombre="Validar contra carteleras reales",
        descripcion=("Reconstruye las últimas 10 carteleras tal como estaban el día del "
                     "evento y compara. OJO: diferencias de menos de 4 peleas entre "
                     "corridas son ruido de semilla, no una mejora."),
        pasos=[[sys.executable, "-m", "modelado.backtest_carteleras", "10"]],
        minutos="~4 min",
    ),
    Receta(
        id="evaluar",
        nombre="Acierto y calibración fuera de muestra",
        descripcion=("Acierto sobre las peleas de 2025-2026 y reparto por tramo (¿un 70% "
                     "gana el 70% de las veces?). Usa winner_xgb_split.pkl, el modelo "
                     "entrenado solo hasta 2024, así que el número es fuera de muestra y "
                     "coincide con el que imprime train_model. Requiere haber "
                     "reentrenado al menos una vez."),
        pasos=[[sys.executable, "-m", "modelado.evaluar_modelo"]],
        minutos="~30 s",
    ),
    Receta(
        id="limpiar_cache",
        nombre="Refrescar fichas de peleadores",
        descripcion=("Borra data/raw/ufcstats_cache.json para que la próxima predicción "
                     "vuelva a bajar las fichas. Hazlo si alguien peleó hace poco y sus "
                     "stats se ven viejos."),
        pasos=[[sys.executable, "-c",
                "import pathlib,config as C; p=C.DATA_RAW/'ufcstats_cache.json'; "
                "p.unlink(missing_ok=True); print('[ok] cache de fichas borrado')"]],
        minutos="instantáneo",
    ),
]}


# --------------------------------------------------------------------------- #
# Estado de una corrida
# --------------------------------------------------------------------------- #
@dataclass
class Trabajo:
    id: str
    receta: str
    nombre: str
    estado: str = "corriendo"          # corriendo | ok | error | cancelado
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    paso: int = 0
    total_pasos: int = 1
    lineas: deque = field(default_factory=lambda: deque(maxlen=MAX_LINEAS))
    _proc: subprocess.Popen | None = None
    _cancelar: bool = False

    def dict(self, desde: int = 0) -> dict:
        # `desde` permite que el navegador pida solo lo nuevo en vez del log entero.
        todas = list(self.lineas)
        return {
            "id": self.id, "receta": self.receta, "nombre": self.nombre,
            "estado": self.estado, "paso": self.paso, "total_pasos": self.total_pasos,
            "segundos": round((self.fin or time.time()) - self.inicio),
            "lineas": todas[desde:], "n_lineas": len(todas),
        }


class Gestor:
    """Un solo trabajo pesado a la vez; el historial queda para consultarlo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trabajos: dict[str, Trabajo] = {}
        self._actual: str | None = None

    # -- consulta ---------------------------------------------------------- #
    def actual(self) -> Trabajo | None:
        with self._lock:
            return self._trabajos.get(self._actual) if self._actual else None

    def get(self, job_id: str) -> Trabajo | None:
        return self._trabajos.get(job_id)

    def historial(self) -> list[dict]:
        with self._lock:
            ts = sorted(self._trabajos.values(), key=lambda t: -t.inicio)[:20]
        return [{"id": t.id, "nombre": t.nombre, "estado": t.estado,
                 "segundos": round((t.fin or time.time()) - t.inicio),
                 "inicio": t.inicio} for t in ts]

    def ocupado(self) -> bool:
        t = self.actual()
        return t is not None and t.estado == "corriendo"

    # -- ejecución --------------------------------------------------------- #
    def lanzar(self, receta_id: str) -> tuple[Trabajo | None, str]:
        receta = RECETAS.get(receta_id)
        if receta is None:
            return None, f"No existe la tarea '{receta_id}'."
        with self._lock:
            if self._actual and self._trabajos[self._actual].estado == "corriendo":
                en_curso = self._trabajos[self._actual].nombre
                return None, (f"Ya hay una tarea corriendo ('{en_curso}'). Se permite una "
                              f"sola: casi todas escriben en data/processed y dos a la vez "
                              f"se pisarían los archivos.")
            job_id = f"{receta_id}-{int(time.time()*1000)}"
            t = Trabajo(id=job_id, receta=receta_id, nombre=receta.nombre,
                        total_pasos=len(receta.pasos))
            self._trabajos[job_id] = t
            self._actual = job_id

        threading.Thread(target=self._correr, args=(t, receta), daemon=True).start()
        return t, ""

    def cancelar(self, job_id: str) -> bool:
        t = self._trabajos.get(job_id)
        if t is None or t.estado != "corriendo":
            return False
        t._cancelar = True
        if t._proc and t._proc.poll() is None:
            t._proc.terminate()
        return True

    def _correr(self, t: Trabajo, receta: Receta) -> None:
        # Los scripts imprimen acentos y nombres como 'Błachowicz'. Sin forzar
        # UTF-8 en el subproceso, Windows los rompe con cp1252 a mitad de corrida.
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        for i, cmd in enumerate(receta.pasos, start=1):
            if t._cancelar:
                break
            t.paso = i
            if len(receta.pasos) > 1:
                t.lineas.append(f"─── paso {i}/{len(receta.pasos)}: {' '.join(cmd[1:])}")
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", bufsize=1,
                )
            except OSError as e:
                t.lineas.append(f"[ERROR] no se pudo lanzar: {e}")
                t.estado = "error"
                t.fin = time.time()
                return
            t._proc = proc
            assert proc.stdout is not None
            for linea in proc.stdout:
                t.lineas.append(linea.rstrip("\n"))
            code = proc.wait()
            if t._cancelar:
                t.lineas.append("[!] cancelado por el usuario")
                t.estado = "cancelado"
                t.fin = time.time()
                return
            if code != 0:
                t.lineas.append(f"[ERROR] el paso terminó con código {code}")
                t.estado = "error"
                t.fin = time.time()
                return

        t.estado = "ok"
        t.fin = time.time()
        t.lineas.append(f"[ok] terminado en {round(t.fin - t.inicio)} s")


GESTOR = Gestor()
