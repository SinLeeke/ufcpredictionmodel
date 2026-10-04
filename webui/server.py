"""
server.py
Servidor local de la UI. Se lanza con `scripts/lanzar_ui.bat` o:

    python -m webui.server

y abre http://127.0.0.1:8000

Escucha SOLO en 127.0.0.1 a propósito: esto maneja tu bankroll y tus cuotas, no
tiene autenticación, y no hay ningún motivo para exponerlo a la red.
"""
from __future__ import annotations

import json
import sys
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile, File           # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response      # noqa: E402
from fastapi.staticfiles import StaticFiles                             # noqa: E402
from pydantic import BaseModel                                          # noqa: E402

import config as C
from src import storage as DB                                                      # noqa: E402
from webui import engine, fotos, parlay as P                            # noqa: E402
from webui.jobs import GESTOR, RECETAS                                  # noqa: E402

@asynccontextmanager
async def _lifespan(_app):
    with DB.lease("ui"):
        engine.arrancar_auto()
        # Polling de cuotas (BFO, Polymarket, The Odds API) en hilos de fondo.
        # Si algo falla al arrancarlo, la UI abre igual: el mercado es un extra.
        try:
            from src.cuotas import capa as mercado
            mercado.arrancar()
        except Exception:                                   # noqa: BLE001
            mercado = None
        yield
        if mercado is not None:
            mercado.detener()


STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="UFC Predictor UI", docs_url=None, redoc_url=None, lifespan=_lifespan)


# --------------------------------------------------------------------------- #
# Cartelera
# --------------------------------------------------------------------------- #
@app.get("/api/peleadores")
def buscar_peleadores(q: str = "", limite: int = 40, offset: int = 0):
    from webui import catalogo
    return catalogo.buscar(q[:100], min(max(limite, 1), 100), max(0, offset))


@app.get("/api/peleadores/{identidad}")
def perfil_peleador(identidad: str):
    from webui import catalogo
    d = catalogo.perfil(identidad)
    if d is None:
        raise HTTPException(404, "No existe esa ficha en la base local.")
    return d


@app.get("/api/peleadores/{identidad}/pelea")
def pelea_del_historial(identidad: str, fecha: str, rival: str):
    """Una pelea del historial como se veía ese día (webui/historial.py)."""
    from webui import historial
    try:
        return historial.pelea(identidad, fecha, rival[:120])
    except historial.NoEncontrada as e:
        raise HTTPException(404, str(e)) from None
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/rankings")
def rankings_oficiales():
    from webui import catalogo
    return catalogo.rankings()


@app.get("/api/cuotas/configuracion")
def configuracion_cuotas():
    # Solo si hay clave, nunca la clave: config.ODDS_API_KEY viene del .env
    # (ODDS_API_KEY, con THE_ODDS_API_KEY como nombre antiguo de respaldo).
    return {"odds_api_configurada": bool(C.ODDS_API_KEY), "ttl_seg": 1800}


@app.get("/api/cuotas")
def consultar_cuotas(proveedor: str = "bfo"):
    from src import cuotas_fuentes
    from src import cartelera_completa
    try:
        return cartelera_completa.resumen(cuotas_fuentes.consultar(proveedor))
    except ValueError as e:
        raise HTTPException(502, str(e)) from None


# --------------------------------------------------------------------------- #
# Mercado: capa común de cuotas (src/cuotas). Contrato: docs/contrato-datos.md §2.
# Todos leen de SQLite y responden al instante: ninguno espera a la red.
# --------------------------------------------------------------------------- #
@app.get("/api/mercado/estado")
def mercado_estado():
    from src.cuotas import capa
    return capa.capa().estado()


@app.get("/api/mercado/peleas")
def mercado_peleas(evento: str | None = None):
    from src.cuotas import capa
    return capa.capa().peleas((evento or "")[:120] or None)


@app.get("/api/mercado/cartelera")
def mercado_cartelera():
    from src.cuotas import capa
    with engine.ESTADO.lock:
        peleas = list((engine.ESTADO.datos or {}).get("peleas") or [])
    pares = [(str(p.get("a") or ""), str(p.get("b") or "")) for p in peleas if p.get("a") and p.get("b")]
    return capa.capa().cartelera(pares)


@app.get("/api/mercado/historial")
def mercado_historial(pelea_id: str, desde: str | None = None, a: str | None = None):
    from src.cuotas import capa
    try:
        return capa.capa().historial(pelea_id[:300], desde, a)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/mercado/vivo")
def mercado_vivo(desde: str | None = None, pelea_id: str | None = None,
                 terminadas: str | None = None, evento_id: str | None = None):
    # Sección "Mercado en vivo" de Inicio (webui/vivo.py). Sin evento en curso: {"activo": false}.
    from webui import vivo
    marcas = None
    if terminadas is not None:
        # Son marcas de este navegador, no resultados deportivos ni datos del
        # modelo. Acotar la entrada evita convertir un GET en una carga arbitraria.
        if len(terminadas) > 10000:
            raise HTTPException(400, "Demasiadas marcas de peleas terminadas.")
        try:
            marcas = json.loads(terminadas)
        except (TypeError, ValueError):
            raise HTTPException(400, "Las marcas deben ser una lista de identificadores.") from None
        if (not isinstance(marcas, list) or len(marcas) > 50
                or any(not isinstance(marca, str) or not marca or len(marca) > 300 for marca in marcas)):
            raise HTTPException(400, "Las marcas deben ser una lista de hasta 50 identificadores.")
    if evento_id is not None and len(evento_id) > 300:
        raise HTTPException(400, "Identificador de evento demasiado largo.")
    return vivo.vivo((desde or "")[:40] or None, (pelea_id or "")[:300] or None,
                     terminadas=marcas, evento_id=evento_id)


class CargaCuotas(BaseModel):
    snapshot: str
    evento: str
    casa: str
    oficial: bool = False


@app.get("/api/cuotas/historial")
def historial_cuotas(proveedor: str | None = None):
    from src import cuotas_fuentes
    return {"capturas": cuotas_fuentes.historial(proveedor)}


@app.get("/api/cuotas/capturas/{identidad}")
def captura_cuotas(identidad: str):
    from src import cuotas_fuentes, cartelera_completa
    try:
        return cartelera_completa.resumen({**cuotas_fuentes.captura(identidad), "cache": True})
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@app.post("/api/cartelera/cuotas")
def cargar_desde_cuotas(body: CargaCuotas):
    from src import cuotas_fuentes
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    try:
        if body.oficial:
            from src import cartelera_completa
            ruta, titulo, meta = cartelera_completa.desde_snapshot(body.snapshot, body.evento, body.casa)
        else:
            ruta, titulo, meta = cuotas_fuentes.cartelera(body.snapshot, body.evento, body.casa)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # Una captura histórica no se predice con estadísticas actuales.
    corte = meta["fecha_fuente"][:10] if meta.get("fecha_fuente") else meta.get("corte")
    engine.cargar(meta["proveedor"], titulo, ruta, corte=corte,
                  fuente_cuotas=meta, titulo_fuente=titulo)
    return {"ok": True}


@app.get("/api/estado")
def estado():
    from webui import identidad_visual
    return identidad_visual.decorar_estado(engine.ESTADO.snapshot(), engine.ESTADO.csv_path)


@app.get("/api/bandera/{codigo}")
def bandera(codigo: str):
    from webui import banderas
    vector = banderas.svg(codigo)
    if vector is None:
        raise HTTPException(404, "Bandera no disponible")
    return Response(vector, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/betano/carteleras")
def betano_carteleras():
    try:
        return engine.listar_carteleras()
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
    corte: str | None = None      # AAAA-MM-DD: repetición con los datos de ese día


def _corte_valido(corte: str | None) -> str | None:
    """La fecha de corte normalizada, o 400 con el motivo en castellano."""
    from src import corte as CT
    try:
        dia = CT.a_fecha(corte)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return dia.strftime("%Y-%m-%d") if dia is not None else None


@app.get("/api/cards")
def listar_csvs():
    d = C.ROOT / "cards"
    d.mkdir(exist_ok=True)
    archivos = sorted(d.glob("*.csv"), key=lambda p: -DB.stat(p).st_mtime)
    return {"cards": [{"nombre": p.name,
                       "modificado": DB.stat(p).st_mtime,
                       "kb": round(DB.stat(p).st_size / 1024, 1)} for p in archivos]}


def _dentro_de(ruta: Path, carpeta: Path) -> bool:
    """
    True si `ruta` (ya resuelta) cae dentro de `carpeta`. Comparar prefijos de
    texto no sirve: "cards_x" también empieza con "cards", y "../cards_x/a.csv"
    pasaba el chequeo viejo.
    """
    return ruta.is_relative_to(carpeta.resolve())


@app.post("/api/cartelera/csv")
def cargar_csv(body: CargaCSV):
    ruta = (C.ROOT / "cards" / body.nombre).resolve()
    # El nombre viene del navegador: hay que verificar que no se salga de cards/.
    if not _dentro_de(ruta, C.ROOT / "cards") or not DB.exists(ruta):
        raise HTTPException(404, f"No existe cards/{body.nombre}")
    corte = _corte_valido(body.corte)
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    engine.cargar("csv", body.nombre, ruta, corte=corte)
    return {"ok": True}


@app.get("/api/inicio")
def inicio():
    """La portada: noticias y carteleras confirmadas de UFC, desde la caché."""
    return engine.portada()


@app.get("/api/inicio/resultados")
def resultados_recientes():
    """Las últimas carteleras de la base: el pronóstico de ese día contra cómo terminó."""
    return engine.resultados_recientes()


@app.get("/api/inicio/imagen/{id_nota}")
def imagen_nota(id_nota: str):
    """
    La imagen de una nota, bajada una vez a disco. Solo por un id que vino en la
    portada: el navegador nunca elige qué URL se baja. 204 si no hay.
    """
    from src import ufc_oficial
    ruta = ufc_oficial.imagen(id_nota)
    if ruta is None:
        return Response(status_code=204)
    return FileResponse(ruta, headers={"Cache-Control": "private, max-age=86400"})


class CargaOficial(BaseModel):
    id: str


@app.post("/api/cartelera/ufc")
def cargar_ufc(body: CargaOficial):
    """Predice una cartelera confirmada por UFC, sin cuotas."""
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    try:
        nombre = engine.cargar_oficial(body.id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "nombre": nombre}


@app.get("/api/anteriores")
def peleas_anteriores(q: str = "", limite: int = 24):
    """
    Peleas de la base local para repetirlas. Sin `q`, la estelar de cada evento;
    con `q`, todas las que nombren a ese peleador o evento. Nunca el resultado.
    """
    try:
        return engine.peleas_anteriores(q.strip()[:80], max(1, min(limite, 240)))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


class CargaHistorica(BaseModel):
    evento: str
    fecha: str                    # AAAA-MM-DD del evento: es también el corte


@app.post("/api/cartelera/anterior")
def cargar_anterior(body: CargaHistorica):
    _corte_valido(body.fecha)
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    try:
        nombre = engine.cargar_historico(body.evento, body.fecha)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "nombre": nombre}


@app.post("/api/cartelera/subir")
async def subir_csv(archivo: UploadFile = File(...)):
    nombre = Path(archivo.filename or "cartelera.csv").name
    if not nombre.lower().endswith(".csv"):
        raise HTTPException(400, "Tiene que ser un .csv")
    # ANTES de escribir: si no, con una carga en curso el usuario recibía el
    # 409 con su archivo de cards/ ya pisado por el nuevo.
    if engine.ESTADO.cargando:
        raise HTTPException(409, "Ya hay una carga en curso.")
    destino = C.ROOT / "cards" / nombre
    destino.parent.mkdir(exist_ok=True)
    DB.write_bytes(destino, await archivo.read())
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


@app.post("/api/carga/cancelar")
def cancelar_carga():
    """Detiene la carga en curso sin dejar nada a medias (engine.cancelar_carga)."""
    err = engine.cancelar_carga()
    if err:
        raise HTTPException(409, err)
    return {"ok": True}


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
        return {"existe": DB.exists(p),
                "modificado": DB.stat(p).st_mtime if DB.exists(p) else None}
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
# Fotos de peleadores
# --------------------------------------------------------------------------- #
@app.get("/api/foto/{nombre}")
def foto_peleador(nombre: str, calidad: str = ""):
    """
    La foto del peleador, de ESPN (o Wikipedia/Sherdog como respaldo), bajada y servida desde
    disco. 204 si no hay (o si no se puede saber con certeza cuál es): la UI
    muestra entonces una silueta. Es 204 y no 404 porque "no hay foto" es una
    respuesta normal, no un error, y el navegador anota cada 404 en la consola
    como si algo se hubiera roto. No toca /api/estado ni el contrato JSON.

    calidad=alta: el retrato de estudio de UFC a resolución completa (perfil,
    listado y Rankings), con las mismas reglas de identidad. X-Fondo dice si
    el archivo trae fondo transparente, para que la UI disimule el que no.
    """
    ruta = fotos.foto_alta(nombre) if calidad == "alta" else fotos.foto(nombre)
    if ruta is None:
        return Response(status_code=204)
    # A diferencia del resto de /api/, una foto no cambia: que el navegador la
    # guarde y no la pida en cada repintado de la cartelera.
    return FileResponse(ruta, headers={"Cache-Control": "private, max-age=86400",
                                       "X-Fondo": fotos.fondo(ruta)})


# --------------------------------------------------------------------------- #
# Reportes HTML por pelea (los que ya genera visuals.py)
# --------------------------------------------------------------------------- #
@app.get("/reportes/{evento}/{archivo}")
def reporte(evento: str, archivo: str):
    ruta = (C.OUTPUTS / evento / archivo).resolve()
    if not _dentro_de(ruta, C.OUTPUTS) or not DB.exists(ruta):
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
    # --demo [nombre]: arranca con una cartelera ya predicha de webui/demo/, sin
    # necesitar data/ ni models/. Sirve para trabajar la interfaz en un clon
    # limpio o en una sesión en la nube. Ver engine.cargar_demo.
    if "--demo" in sys.argv:
        i = sys.argv.index("--demo")
        nombre = sys.argv[i + 1] if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-") else None
        ruta = engine.ruta_demo(nombre)
        if ruta is None:
            raise SystemExit(f"No hay ninguna demo que contenga '{nombre}' en webui/demo/.")
        engine.cargar_demo(ruta)
        print(f"  [demo] {ruta.name}")
    # --puerto N: para abrir una segunda copia (por ejemplo la demo) sin cerrar
    # la que ya está en el 8000.
    puerto = 8000
    if "--puerto" in sys.argv:
        i = sys.argv.index("--puerto")
        if i + 1 >= len(sys.argv) or not sys.argv[i + 1].isdigit():
            raise SystemExit("--puerto necesita un número, por ejemplo --puerto 8010.")
        puerto = int(sys.argv[i + 1])
    print("=" * 60)
    print("  UFC Predictor — UI")
    print(f"  http://127.0.0.1:{puerto}")
    print("  (Ctrl+C para cerrar)")
    print("=" * 60)
    if "--sin-navegador" not in sys.argv:
        try:
            webbrowser.open(f"http://127.0.0.1:{puerto}")
        except Exception:                                    # noqa: BLE001
            pass
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
