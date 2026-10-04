"""La cartelera anunciada y los precios son datos independientes.

Solo se cruzan parejas exactas, con aliases ya auditados. Sin cuota = NaN;
jamás eliminar esa pelea, rellenar un precio ni mezclar casas.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

import pandas as pd
import config as C
from src import storage as DB
from src.fighter_names import canonical_key


def pareja(a, b):
    return tuple(sorted((canonical_key(a), canonical_key(b))))


def oficiales():
    p = C.DATA_RAW / "ufc_oficial.json"
    if not DB.exists(p):
        return [], None
    e = DB.read_json(p).get("eventos", {})
    return [x for x in e.get("proximos", []) if x.get("peleas")], e.get("consultado")


def filas_oficiales(evento):
    rows = []
    for i, p in enumerate(evento["peleas"]):
        row = {"fighter_a": p["a"], "fighter_b": p["b"],
            "segment": "Estelar" if i == 0 else "Co-estelar" if i == 1 and p.get("seccion") == "estelar" else "",
            "es_titulo": p.get("titulo", False), "titulo_fuente": "UFC.com"}
        for k in ("rango_a", "rango_b", "perfil_a", "perfil_b"):
            if p.get(k) is not None:
                row[k] = p[k]
        if p.get("peso") is not None:
            row["weight_class"] = p["peso"]
        for lado in ("a", "b"):
            pais = p.get("pais_" + lado)
            if isinstance(pais, dict):
                for campo in ("codigo", "nombre"):
                    if pais.get(campo) is not None:
                        row[f"pais_{campo}_{lado}"] = pais[campo]
                if pais.get("bandera") or pais.get("codigo"):
                    row[f"pais_bandera_{lado}"] = pais.get("bandera") or pais["codigo"]
        rows.append(row)
    return rows[::-1]


def fusionar(evento, cuotas):
    """Conserva orden/segmentos/títulos oficiales y también mercados existentes."""
    grupos = {}
    for r in cuotas.to_dict("records"):
        grupos.setdefault(pareja(r["fighter_a"], r["fighter_b"]), []).append(r)
    rows, unidas = [], 0
    for base in filas_oficiales(evento):
        matchs = grupos.get(pareja(base["fighter_a"], base["fighter_b"]), [])
        r = dict(base)
        if len(matchs) == 1:
            q = matchs[0]
            invertida = canonical_key(q["fighter_a"]) != canonical_key(base["fighter_a"])
            for k, v in q.items():
                if not k.startswith("odds_") and k != "bookmaker":
                    continue
                if invertida and k.startswith("odds_a"):
                    k = k.replace("odds_a", "odds_b", 1)
                elif invertida and k.startswith("odds_b"):
                    k = k.replace("odds_b", "odds_a", 1)
                r[k] = v
            if pd.notna(r.get("odds_a")) and pd.notna(r.get("odds_b")):
                unidas += 1
        rows.append(r)
    df = pd.DataFrame(rows)
    for col in ("odds_a", "odds_b"):
        if col not in df:
            df[col] = float("nan")
    return df, unidas


def resumen(snapshot):
    eventos, actualizado = roster_snapshot(snapshot)
    carteleras = []
    for e in eventos:
        pares = {pareja(p["a"], p["b"]) for p in e["peleas"]}
        casas = {}
        for grupo in snapshot["eventos"]:
            for p in grupo["peleas"]:
                if pareja(p["a"], p["b"]) in pares:
                    for k, c in p["casas"].items():
                        casas[k] = c["casa"]
        peleas = []
        for p in e["peleas"]:
            precios = {}
            for book in casas:
                posibles = []
                for grupo in snapshot["eventos"]:
                    for q in grupo["peleas"]:
                        if pareja(q["a"], q["b"]) != pareja(p["a"], p["b"]) or book not in q["casas"]:
                            continue
                        c = q["casas"][book]
                        posibles.append((c["a"], c["b"]) if canonical_key(q["a"]) == canonical_key(p["a"]) else (c["b"], c["a"]))
                if posibles and len(set(posibles)) == 1:
                    a, b = posibles[0]
                    precios[book] = {"casa": casas[book], "a": a, "b": b}
            peleas.append({**p, "casas": precios})
        carteleras.append({"id": e["id"], "titulo": f"{e['nombre']} · {e['titular']}",
            "fecha": datetime.fromtimestamp(e["inicio"]["estelar"], timezone.utc).isoformat(),
            "peleas": peleas, "casas": casas, "fuente": e["url"]})
    return {**snapshot, "carteleras": carteleras, "cartelera_actualizada": actualizado,
            "cartelera_conservada": "carteleras_guardadas" in snapshot and not snapshot.get("fecha_fuente")}


def roster_snapshot(snapshot):
    # Una captura previa al soporte de roster no puede reconstruirse con el
    # calendario de hoy. Las cuotas originales siguen disponibles separadas.
    # La API histórica tampoco proporciona una cartelera anunciada completa.
    if snapshot.get("fecha_fuente"):
        return [], None
    d = snapshot.get("carteleras_guardadas")
    return (d["eventos"], d["consultado"]) if d is not None else ([], None)


def desde_snapshot(sid, evento_id, casa):
    from src import cuotas_fuentes as Q
    snapshot = Q.captura(sid)
    eventos, actualizado = roster_snapshot(snapshot)
    evento = next((e for e in eventos if e["id"] == evento_id), None)
    if evento is None:
        raise ValueError("No hay una cartelera anunciada guardada para ese evento.")
    with DB.connect() as con:
        Q._tablas(con)
        r = con.execute('SELECT contenido,capturado,proveedor,fecha_fuente FROM cuotas_snapshots WHERE id=?', (sid,)).fetchone()
    if not r or r[3]:
        raise ValueError("Elige una captura actual para una cartelera anunciada.")
    grupos, nombre_casa = {}, "Sin cuotas"
    for e in json.loads(r[0]):
        for p in e["peleas"]:
            c = p["casas"].get(casa)
            if not c:
                continue
            nombre_casa = c["casa"]
            grupos.setdefault(pareja(p["a"], p["b"]), []).append({"fighter_a": p["a"], "fighter_b": p["b"],
                "odds_a": c["a"], "odds_b": c["b"], "bookmaker": c["casa"]})
    rows = []
    for matches in grupos.values():
        # Una pareja repetida en distintos cuadros solo sirve si los precios
        # coinciden después de orientar las dos esquinas. Si discrepan, sin cuota.
        first = matches[0]
        a = canonical_key(first["fighter_a"])
        precios = {(m["odds_a"], m["odds_b"]) if canonical_key(m["fighter_a"]) == a
                   else (m["odds_b"], m["odds_a"]) for m in matches}
        if len(precios) == 1:
            rows.append(first)
    df, n = fusionar(evento, pd.DataFrame(rows))
    path = C.DATA_PROCESSED / f"cartelera_{evento_id}_{sid[:16]}_{hashlib.sha256(casa.encode()).hexdigest()[:8]}.csv"
    DB.to_csv(df, path, index=False)
    return path, f"{evento['nombre']} · {evento['titular']}", {"proveedor": r[2], "capturado": r[1],
        "fecha_fuente": None, "casa": nombre_casa, "snapshot": sid, "fuente": evento["url"],
        "corte": Q.corte_captura(r[1]),
        "peleas_sin_cuota": len(df) - n, "peleas_con_cuota": n, "cartelera_actualizada": actualizado}


def completar_betano(df, query, fecha=None):
    eventos, _ = oficiales()
    match = re.search(r"\bufc\s*(\d{2,3})\b", query, re.I)
    if match:
        eventos = [e for e in eventos if e["nombre"].upper() == f"UFC {match[1]}"]
    else:
        pares = {pareja(r.fighter_a, r.fighter_b) for r in df.itertuples()}
        eventos = [e for e in eventos if any(pareja(p["a"], p["b"]) in pares for p in e["peleas"])]
    if fecha:
        eventos = [e for e in eventos if datetime.fromtimestamp(e["inicio"]["estelar"]).date().isoformat() == fecha]
    if len(eventos) != 1:
        return df
    return fusionar(eventos[0], df)[0]
