"""
server.py
Servidor local de la UI. Se lanza con `scripts/lanzar_ui.bat` o:

    python -m webui.server

y abre http://127.0.0.1:8000

Escucha SOLO en 127.0.0.1 a propósito: esto maneja tu bankroll y tus cuotas, no
tiene autenticación, y no hay ningún motivo para exponerlo a la red.
"""
from __future__ import annotations

import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile, File           # noqa: E402
from fastapi.responses import FileResponse, JSONResponse                # noqa: E402
from fastapi.staticfiles import StaticFiles                             # noqa: E402
from pydantic import BaseModel                                          # noqa: E402

import config as C                                                      # noqa: E402
from webui import engine, parlay as P                                   # noqa: E402
from webui.jobs import GESTOR, RECETAS                                  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="UFC Predictor UI", docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- #
# Cartelera
# --------------------------------------------------------------------------- #
@app.get("/api/estado")
def estado():
    return engine.ESTADO.snapshot()


@app.get("/api/betano/carteleras")
def betano_carteleras():
    try:
        return {"carteleras": engine.listar_carteleras()}
    except Exception as e:                                   # noqa: BLE001
        raise HTTPException(502, f"No pude consultar Betano: {e}")


class CargaBetano(BaseModel):
    query: str
    fecha: str | None = None      # AAAA-MM-DD, para elegir uno de los eventos
                                  # que comparten nombre de liga


@app.post("/api/cartelera/betano")
def cargar_betano(body: CargaBetano):
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    engine.cargar("betano", body.query.strip(), fecha=body.fecha)
    return {"ok": True}


class CargaCSV(BaseModel):
    nombre: str


@app.get("/api/cards")
def listar_csvs():
    d = C.ROOT / "cards"
    d.mkdir(exist_ok=True)
    archivos = sorted(d.glob("*.csv"), key=lambda p: -p.stat().st_mtime)
    return {"cards": [{"nombre": p.name,
                       "modificado": p.stat().st_mtime,
                       "kb": round(p.stat().st_size / 1024, 1)} for p in archivos]}


@app.post("/api/cartelera/csv")
def cargar_csv(body: CargaCSV):
    ruta = (C.ROOT / "cards" / body.nombre).resolve()
    # El nombre viene del navegador: hay que verificar que no se salga de cards/.
    if not str(ruta).startswith(str((C.ROOT / "cards").resolve())) or not ruta.exists():
        raise HTTPException(404, f"No existe cards/{body.nombre}")
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    engine.cargar("csv", body.nombre, ruta)
    return {"ok": True}


@app.post("/api/cartelera/subir")
async def subir_csv(archivo: UploadFile = File(...)):
    nombre = Path(archivo.filename or "cartelera.csv").name
    if not nombre.lower().endswith(".csv"):
        raise HTTPException(400, "Tiene que ser un .csv")
    destino = C.ROOT / "cards" / nombre
    destino.parent.mkdir(exist_ok=True)
    destino.write_bytes(await archivo.read())
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    engine.cargar("csv", nombre, destino)
    return {"ok": True, "nombre": nombre}


@app.post("/api/vivo")
def modo_vivo(encender: bool = True):
    """
    Enciende o apaga el refresco EN VIVO de la línea de ganador.

    Arranca apagado a propósito: son ~6 peticiones por minuto a Betano, y eso
    solo se justifica mientras estás mirando la cartelera. Dejarlo prendido de
    fondo es la forma de que te bloqueen la IP.
    """
    with engine.ESTADO.lock:
        engine.ESTADO.vivo = bool(encender)
        if not encender:
            engine.ESTADO.vivo_en = None
    return {"ok": True, "vivo": engine.ESTADO.vivo,
            "intervalo_seg": engine.INTERVALO_VIVO_SEG}


@app.post("/api/limpiar")
def limpiar_cartelera():
    """Suelta la cartelera activa para poder elegir otra desde cero."""
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Hay una carga en curso; espera a que termine.")
    engine.limpiar()
    return {"ok": True}


@app.post("/api/refrescar")
def refrescar():
    err = engine.refrescar()
    if err:
        raise HTTPException(409, err)
    return {"ok": True}


class Auto(BaseModel):
    activo: bool


@app.post("/api/auto")
def set_auto(body: Auto):
    with engine.ESTADO.lock:
        engine.ESTADO.auto = body.activo
        engine.ESTADO.proximo_auto = (
            time.time() + engine.INTERVALO_AUTO_SEG if body.activo else None)
    return {"ok": True, "auto": body.activo}


# --------------------------------------------------------------------------- #
# Parlay
# --------------------------------------------------------------------------- #
class ParlayReq(BaseModel):
    ids: list[str]
    bankroll: float = 100.0


@app.post("/api/parlay")
def evaluar_parlay(body: ParlayReq):
    with engine.ESTADO.lock:
        por_id = {p.id: p for p in engine.ESTADO.patas}
    faltan = [i for i in body.ids if i not in por_id]
    if faltan:
        raise HTTPException(400, f"Patas desconocidas: {faltan}. Recarga la cartelera.")
    elegidas = [por_id[i] for i in body.ids]
    res = P.evaluar(elegidas, bankroll=max(0.0, body.bankroll))
    res["patas"] = [p.dict() for p in elegidas]
    return res


# --------------------------------------------------------------------------- #
# Mantenimiento
# --------------------------------------------------------------------------- #
@app.get("/api/tareas")
def tareas():
    return {
        "recetas": [{"id": r.id, "nombre": r.nombre, "descripcion": r.descripcion,
                     "minutos": r.minutos, "pasos": len(r.pasos)}
                    for r in RECETAS.values()],
        "ocupado": GESTOR.ocupado(),
        "historial": GESTOR.historial(),
    }


class LanzarReq(BaseModel):
    receta: str


@app.post("/api/tareas/lanzar")
def lanzar(body: LanzarReq):
    t, err = GESTOR.lanzar(body.receta)
    if t is None:
        raise HTTPException(409, err)
    return {"ok": True, "job": t.id}


@app.get("/api/tareas/{job_id}")
def ver_job(job_id: str, desde: int = 0):
    t = GESTOR.get(job_id)
    if t is None:
        raise HTTPException(404, "No existe ese trabajo.")
    return t.dict(desde=desde)


@app.post("/api/tareas/{job_id}/cancelar")
def cancelar(job_id: str):
    if not GESTOR.cancelar(job_id):
        raise HTTPException(409, "Ese trabajo ya no está corriendo.")
    return {"ok": True}


@app.get("/api/salud")
def salud():
    """Qué hay y qué falta. Es lo primero que ve la UI al abrirse."""
    def _existe(p: Path) -> dict:
        return {"existe": p.exists(),
                "modificado": p.stat().st_mtime if p.exists() else None}
    return {
        "modelo_ganador": _existe(C.WINNER_MODEL),
        "modelo_metodo": _existe(C.METHOD_MODEL),
        "modelo_metodo6": _existe(C.MODELS / "metodo6_xgb.pkl"),
        "calibrador_mercado": _existe(C.MODELS / "calibrador_mercado.pkl"),
        "calibrador_metodo": _existe(C.MODELS / "calibrador_metodo.pkl"),
        "features": _existe(C.FEATURES_CSV),
        "ventana_anios": C.TRAIN_WINDOW_YEARS,
        "simulaciones": C.N_SIMULATIONS,
    }


# --------------------------------------------------------------------------- #
# Reportes HTML por pelea (los que ya genera visuals.py)
# --------------------------------------------------------------------------- #
@app.get("/reportes/{evento}/{archivo}")
def reporte(evento: str, archivo: str):
    ruta = (C.OUTPUTS / evento / archivo).resolve()
    if not str(ruta).startswith(str(C.OUTPUTS.resolve())) or not ruta.exists():
        raise HTTPException(404, "No existe ese reporte.")
    return FileResponse(ruta)


@app.exception_handler(Exception)
async def _err(request, exc):                                # noqa: ANN001
    return JSONResponse({"detail": str(exc)}, status_code=500)


@app.middleware("http")
async def _sin_cache(request, call_next):
    """
    La UI se sirve desde el disco local, así que cachearla no ahorra nada y en
    cambio hace que tras editar el HTML o el CSS el navegador siga mostrando la
    versión vieja hasta un Ctrl+F5. Se desactiva el caché para los estáticos.
    """
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


def main() -> None:
    import uvicorn
    engine.arrancar_auto()
    puerto = 8000
    print("=" * 60)
    print("  UFC Predictor — UI")
    print(f"  http://127.0.0.1:{puerto}")
    print("  (Ctrl+C para cerrar)")
    print("=" * 60)
    try:
        webbrowser.open(f"http://127.0.0.1:{puerto}")
    except Exception:                                        # noqa: BLE001
        pass
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
