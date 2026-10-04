"""Detalle de una pelea del historial de un peleador, como se veía ESE día.

Lo abre el modal del perfil (explorar.js) al hacer clic en una fila del
historial. Es la receta de la repetición (src/corte.py) para una sola pelea:
fichas, récord, últimas cinco, ELO, rivales y modelo con SOLO lo anterior a la
fecha, las esquinas orientadas sin mirar el resultado (UFCStats pone al
ganador primero) y el título con la misma lógica de la cartelera.

El modelo es ciego a esa fecha: el de producción si terminó de entrenar
antes, o uno entrenado SOLO con las peleas anteriores (corte.modelos_a_fecha).
Si no hay uno guardado en models/corte/ se entrena en el clic: son dos
XGBoost sobre features.csv, unos segundos, y queda guardado para la próxima
pelea de ese mismo día. Un entrenamiento a la vez (_ENTRENANDO): dos clics
seguidos en la misma fecha no lo repiten. Sin features.csv, o con muy pocas
peleas antes, no hay modelo: se muestran las stats recortadas y la
probabilidad queda como no disponible, con el motivo. Las cifras de la
heurística nunca se muestran como si fueran del modelo.

El resultado real se lee DESPUÉS de predecir y viaja aparte, fuera de `pelea`:
la UI lo pinta separado y nunca entra a ningún cálculo.
"""
from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path

import pandas as pd

from src.fighter_names import canonical_key

_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
# Campos que salen del modelo: sin modelo ciego a la fecha se descartan, porque
# predict_card los llena con la heurística.
_DEL_MODELO = ("p_a", "p_b", "ci_a", "ci_b", "metodo", "p_finish", "p_decision", "probabilidades_metodo",
               "ganador", "confianza", "tendencia", "por_que_confianza", "metodo6", "metodo5", "mercado",
               "p_sin_corto_a", "p_con_corto_a")
_ENTRENANDO = threading.Lock()


class NoEncontrada(LookupError):
    """La pelea pedida no está en el historial verificado de esa ficha."""


def _pelea_en_base(nombre: str, rival: str, fecha: str):
    """La fila de corte._peleas() de esa pareja y fecha exactas, o NoEncontrada."""
    from src import corte as CT
    p = CT._peleas()
    dia = pd.Timestamp(fecha).normalize()
    sub = p[(p["par"] == CT._clave_par(nombre, rival)) & (p["date"] == dia)]
    if len(sub) != 1:
        # Dos filas iguales serían un duplicado de la base: no se elige una.
        raise NoEncontrada("No encontré esa pelea en la base local.")
    return next(sub.itertuples())


def _modelo_ciego(corte) -> tuple[dict | None, str]:
    """(modelos que no vieron nada desde `corte`, motivo si no los hay). Entrena si hace falta."""
    import config as C
    from src import corte as CT, storage as DB
    # Sin features.csv no se puede saber hasta dónde vio el de producción, y
    # modelos_a_fecha caería en él: aquí eso sería mirar el futuro.
    if not DB.exists(C.FEATURES_CSV):
        return None, "Sin la tabla de entrenamiento (features.csv) no se puede armar un modelo ciego a esa fecha."
    try:
        with _ENTRENANDO:
            return CT.modelos_a_fecha(corte), ""
    except ValueError as e:                                 # muy pocas peleas antes
        return None, str(e)
    except Exception as e:                                  # noqa: BLE001
        return None, f"No pude entrenar el modelo de esa fecha ({type(e).__name__})."


def pelea(identidad: str, fecha: str, rival: str) -> dict:
    """{"pelea": ..., "corte": ..., "resultado": ...} para el modal del historial.

    Solo acepta una pelea que el perfil ya atribuye a esa ficha (misma fecha y
    rival exactos): el navegador no puede pedir que se prediga cualquier cosa.
    """
    from webui import catalogo
    from src import corte as CT, card
    from webui import engine
    if not _FECHA.fullmatch(fecha or ""):
        raise ValueError("La fecha tiene que ir como AAAA-MM-DD.")
    perfil = catalogo.perfil(identidad)
    if perfil is None:
        raise NoEncontrada("No existe esa ficha en la base local.")
    entrada = next((h for h in perfil.get("historial") or []
                    if str(h.get("fecha"))[:10] == fecha and h.get("rival") == rival), None)
    if entrada is None:
        raise NoEncontrada("Esa pelea no figura en el historial de esta ficha.")
    r = _pelea_en_base(perfil["nombre"], rival, fecha)
    fila = CT.fila_historica(r)
    titulo_evento = str(r.event)

    try:
        dia = CT.a_fecha(fecha)
    except ValueError as e:
        # Antes de 2013 no hay con qué reconstruir el día: se dice por qué.
        return {"pelea": None, "corte": {"fecha": fecha, "modelo": None, "motivo": str(e)},
                "resultado": CT.resultado_real(fila["fighter_a"], fila["fighter_b"], fecha), "evento": titulo_evento}
    corte = CT.corte_efectivo([(fila["fighter_a"], fila["fighter_b"])], dia)
    modelos, motivo_modelo = _modelo_ciego(corte)
    sin_modelo = modelos is None or modelos.get("ganador") is None
    if sin_modelo:
        modelos = {"ganador": None, "metodo": None, "metodo6": None, "origen": "sin_modelo",
                   "entrenado_hasta": None, "peleas": None}

    # El nombre del archivo lleva la fecha, como los de la repetición: así la
    # confirmación de títulos busca la cartelera de ese día (card.completar_titulos).
    with tempfile.TemporaryDirectory(prefix="ufc_historial_") as tmp:
        ruta = Path(tmp) / f"historico_{corte:%Y-%m-%d}_{CT._slug(titulo_evento)}.csv"
        pd.DataFrame([fila]).to_csv(ruta, index=False)
        res = card.predict_card(ruta, reports=False, devolver_todo=True,
                                corte=corte.strftime("%Y-%m-%d"), modelos_corte=modelos,
                                carpeta_salida=Path(tmp))
        datos, _ = engine._serializar(res, ruta)
    if not datos["peleas"]:
        motivo = ("Faltan datos de " + ", ".join(datos["missing"]) + " antes de esa fecha."
                  if datos.get("missing") else "No hay datos suficientes de esa pelea antes de esa fecha.")
        return {"pelea": None, "corte": {"fecha": corte.strftime("%Y-%m-%d"), "modelo": None, "motivo": motivo},
                "resultado": CT.resultado_real(fila["fighter_a"], fila["fighter_b"], corte), "evento": titulo_evento}
    p = datos["peleas"][0]
    resultado = p.pop("resultado", None)
    p["id"] = f"historial-{identidad}-{fecha}"
    if sin_modelo:
        for campo in _DEL_MODELO:
            p[campo] = None
        if resultado:
            resultado["acierto"] = None        # se comparaba con el pick de la heurística
    rep = datos.get("repeticion") or {}
    motivo = ("" if not sin_modelo else
              (motivo_modelo or "No hay un modelo que no haya visto esa pelea.")
              + " Las estadísticas sí están recortadas al día de la pelea.")
    return {"pelea": p, "evento": titulo_evento,
            "corte": {"fecha": rep.get("fecha") or corte.strftime("%Y-%m-%d"),
                      "modelo": None if sin_modelo else rep.get("modelo"),
                      "modelo_hasta": None if sin_modelo else rep.get("modelo_hasta"),
                      "base_hasta": rep.get("base_hasta"), "motivo": motivo},
            # La esquina del peleador del perfil, para que la UI no tenga que
            # adivinarla por el nombre (pueden diferir en tildes o alias).
            "lado_perfil": "a" if canonical_key(p["a"]) == canonical_key(perfil["nombre"]) else "b",
            "resultado": resultado}
