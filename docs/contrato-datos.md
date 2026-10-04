# Contrato de datos: peleador y cuotas

Contrato compartido entre el backend (`src/`, `webui/*.py`) y la UI
(`webui/static/`). Cualquier cambio de forma se anota acá primero: la UI no
debe adivinar campos ni saber de qué fuente viene un dato.

Reglas comunes:

- Fechas y horas en ISO 8601 con zona, en UTC (`2026-10-03T22:15:00+00:00`).
- Nada de `NaN` en JSON: un dato desconocido es `null`, nunca `0` ni `""`
  (y recuerda que `NaN` es truthy en Python: `x or ""` no lo limpia).
- Cuotas siempre en **formato americano** hacia la UI (entero con signo:
  `-186`, `+186`, la UI antepone el `+`). El decimal viaja solo como apoyo.
- Cruce de nombres entre fuentes: normalizar (tildes, mayúsculas, espacios,
  puntuación) y luego **match exacto** contra la base, con desempate explícito
  para homónimos. Nada de fuzzy. Lo que no calce se registra, no se descarta
  en silencio.

## 1. Peleador

Lo devuelve cualquier endpoint que muestre a un peleador (rankings, mercado en
vivo, cartelera). Los campos existentes se conservan; los nuevos se agregan.

```jsonc
{
  "nombre": "Islam Makhachev",          // literal de la fuente oficial
  "id": "a1b2c3d4e5f6a7b8",             // ficha UFCStats (16 hex) o null si no se puede atribuir
  "perfil_ufc": "https://www.ufc.com/athlete/islam-makhachev",   // o null
  "pais": {                             // o null si de verdad no hay dato
    "codigo": "RU",                     // ISO 3166-1 alfa-2, siempre en mayúsculas
    "nombre": "Rusia",                  // en español
    "bandera": "RU"                     // lo que se pide a /api/bandera/{bandera}:
                                        // el ISO2, o EN / SC / WA para Inglaterra,
                                        // Escocia y Gales (codigo sigue siendo GB)
    "fuente": "https://www.ufc.com/event/ufc-320"   // procedencia del dato (página de UFC o Wikidata)
  },
  "campeon": {                          // o null si no es campeón actual
    "division": "Peso welter",          // igual a divisiones[].nombre de /api/rankings
    "clave": "Welterweight",            // nombre canónico en inglés
    "interino": false
  },
  "foto": "/api/foto/Islam%20Makhachev",  // URL ya codificada; 204 = sin foto -> silueta
  "identidad_visual": { "...": "sin cambios, se conserva por compatibilidad" }
}
```

- `pais` es la fuente única de la bandera en la UI. Si es `null`, la UI no
  dibuja hueco ni ícono roto: simplemente no pone bandera.
- `campeon` sale de cruzar con las divisiones (puesto `0` = campeón) por
  nombre exacto con desempate explícito por `perfil_ufc`. En una división, el
  campeón tiene `campeon` lleno; en el libra por libra, también (es lo que
  pinta el número dorado).
- Cada fila de rankings tiene `divisiones: [{clave, nombre, fuente, fecha}]`
  y `division` con ese mismo objeto o `null`. En libra por libra se cruzan las
  divisiones de la misma captura oficial, incluso para quienes no son campeones.
  Con dos divisiones se conservan ambas: `division` solo elige una si coincide
  con el campeonato; en otro caso queda `null`. Una ficha distinta o ambigua
  no hereda categoría por compartir nombre. Sin dato no se inventa una división.

### En `/api/rankings`

```jsonc
{
  "fecha": "2026-10-03",
  "fuente": "https://www.ufc.com/rankings",
  "grupos": [                           // NUEVO: orden del menú lateral
    {"titulo": "Hombres", "divisiones": [0, 1, 2, 3, 4, 5, 6, 7, 8]},
    {"titulo": "Mujeres", "divisiones": [9, 10, 11, 12]}
  ],
  "divisiones": [
    {
      "nombre": "Men's Pound-for-Pound",   // igual que hoy
      "clave": "Men's Pound-for-Pound",    // NUEVO: canónico en inglés
      "genero": "M",                       // NUEVO: "M" | "F"
      "p4p": true,                         // NUEVO
      "peleadores": [
        // Peleador (sección 1) + "puesto": entero (0 = campeón en divisiones;
        // el libra por libra empieza en 1)
      ]
    }
  ]
}
```

Hombres: libra por libra, Mosca, Gallo, Pluma, Ligero, Wélter, Medio,
Semipesado, Pesado. Mujeres: libra por libra, Paja, Mosca, Gallo.

## 2. Cuotas

Paquete Python: `src/cuotas/` (capa común). La UI consume solo los endpoints
`/api/mercado/*`; nunca sabe cómo se pidió cada dato.

### 2.1 Fuente (interfaz interna)

```python
class Fuente:
    clave: str        # "betano" | "bfo" | "odds_api" | "polymarket" | "simulada"
    nombre: str       # "Betano", "BestFightOdds", "The Odds API", "Polymarket"
    tipo: str         # "casa" | "mercado_prediccion"
    def estado(self) -> dict            # ver EstadoFuente
    def intervalo(self, en_vivo: bool) -> int | None   # segundos; None = pasiva (empuja)
    def obtener(self) -> list[CotizacionCruda]
```

Betano es **pasiva**: el ciclo actual de `webui/engine.py` (una petición por
ciclo) le entrega a la capa lo que ya bajó; la capa nunca le pide a Betano.

`CotizacionCruda` (antes del cruce de nombres):

```python
{"fuente": "odds_api", "casa": "DraftKings", "evento": "UFC 320",
 "a_texto": "Alex Pereira", "b_texto": "Magomed Ankalaev",
 "a_americana": -150, "b_americana": +125,      # o a_prob/b_prob para Polymarket
 "timestamp": "2026-10-03T22:15:00+00:00",
 # opcionales:
 "fecha": "2026-10-04", "inicio": "2026-10-05T02:00:00+00:00",
 "historial": [{"timestamp": ts, "a_prob": 0.55, "b_prob": 0.45}]}   # solo Polymarket
```

Agregar o quitar una fuente: subclase de `src/cuotas/fuentes/base.Fuente` y una
línea en `src/cuotas/registro.py`. Nada más (ni endpoints ni UI).

Frecuencias (implementadas en cada fuente; `None` = pasiva):

| Fuente | Fuera de evento | Evento en vivo | Notas |
|---|---|---|---|
| `betano` | — | — | pasiva: le entrega `webui/engine.py` (ciclo de 10 min y EN VIVO de 10 s) |
| `bfo` | 30 min | 30 min | `cuotas_fuentes.consultar('bfo')` y su TTL, sin cambios |
| `odds_api` | 12 h | 2 min | < 100 créditos: 24 h / 10 min; < 5: pausa (24 h) |
| `polymarket` | 15 min | 30 s | descubrimiento Gamma cada 30 / 10 min; serie remota cada 6 h |
| `simulada` | 10 s | 10 s | solo con `UFC_MERCADO_SIMULADO=1` |

Un 429 en cualquier fuente aplica backoff exponencial (30 s, 60 s, ... hasta
30 min) y se reinicia con la primera respuesta buena.

### 2.2 Cotización (lo que se guarda en el historial y se expone)

Una fila por fuente × casa × pelea × instante. Historial en SQLite (tabla
`cuotas_historial`), con fuente y timestamp.

```jsonc
{
  "fuente": "odds_api",                 // clave de la fuente
  "tipo": "casa",                       // "casa" | "mercado_prediccion"
  "casa": "DraftKings",                 // casa o mercado concreto ("Polymarket")
  "pelea_id": "alex pereira|magomed ankalaev",
  "timestamp": "2026-10-03T22:15:00+00:00",
  "a": {"americana": -150, "decimal": 1.667, "prob_implicita": 0.600},
  "b": {"americana": 125,  "decimal": 2.250, "prob_implicita": 0.444},
  "margen": 0.044,                      // suma de prob_implicita - 1 (casas: > 0)
  "prob_sin_margen": {"a": 0.575, "b": 0.425}
}
```

- `pelea_id`: los dos nombres **de la base** normalizados, ordenados y unidos
  con `|`. Así no depende del orden de las esquinas de cada fuente.
  Normalizado = `src/fighter_names.canonical_key` (alias auditados incluidos)
  más `ALIAS_MANUAL` de `src/cuotas/cruce.py`. Un nombre que no está en la base
  (debutante, grafía distinta) entra con su propio texto normalizado y queda
  registrado en `cuotas_no_calzados`: así se ve en la cartelera pero no se
  mezcla con nadie, porque el cruce sigue siendo exacto.
- `a`/`b` de la cotización siguen el orden del `pelea_id` (a = la clave menor).
- `visto` (extra): última vez que una fuente confirmó esa misma cuota. El
  historial no duplica filas idénticas consecutivas; extiende `visto`.
- `prob_implicita` = 1 / decimal (con margen). Polymarket trae
  probabilidades: `prob_implicita` es el precio.
- Conversión probabilidad → americana: si p ≥ 0,5, `-(p/(1-p))*100`; si no,
  `+((1-p)/p)*100`, redondeada al entero. 0,65 → −186; 0,35 → +186.
- En una casa, `a.prob_implicita + b.prob_implicita > 1` siempre. Si suma
  menos, el dato está corrupto (pasó con las cuotas de 2025): no entra.
  En un mercado de predicción se exige en cambio que los dos precios sumen
  ≈ 1 (± 0,10): si no, los tokens están cruzados.
- Polymarket: el precio es el que muestra el propio Polymarket, el punto medio
  del libro si el spread es ≤ 0,10 y si no el último transado. Un mercado sin
  transacciones no tiene precio y no entra (su punto medio 0,50 es ficticio).

### 2.3 Pelea consolidada (`GET /api/mercado/peleas`)

```jsonc
{
  "pelea_id": "alex pereira|magomed ankalaev",
  "a": "Alex Pereira", "b": "Magomed Ankalaev",     // nombres de la base
  "a_id": "e5549c82bfb5582d", "b_id": null,        // ficha UFCStats; null = no calzó u homónimo
  "evento": "UFC 320", "fecha": "2026-10-04",
  "inicio": "2026-10-05T02:00:00+00:00",           // hora de su parte de la cartelera, o null
  "oficial": true,                                 // la pareja está en la cartelera de UFC.com
  "cotizaciones": [ /* Cotización 2.2, la última de cada fuente×casa */ ],
  "consenso": {                         // o null si no hay ninguna cotización
    "a": {"prob": 0.575, "americana": -135, "etiqueta": "Favorito"},
    "b": {"prob": 0.425, "americana": 135,  "etiqueta": "Underdog"},
    "pareja": false,                    // ambos entre -115 y +115
    "n_cotizaciones": 4
  },
  "mejor": {                            // la mejor cuota (la que más paga) por peleador
    "a": {"fuente": "bfo", "casa": "FanDuel", "americana": -130},
    "b": {"fuente": "odds_api", "casa": "BetMGM", "americana": 140}
  }
}
```

Consenso: a cada cotización se le quita su margen (`prob / suma`) y después
se promedian las probabilidades sin margen, una cotización por casa. Etiquetas:
`"Favorito"`, `"Underdog"` o, si ambas cuotas quedan entre −115 y +115,
`"Pareja"` en los dos lados.

- "Una por casa": si la misma casa llega por dos fuentes (DraftKings vía BFO y
  vía The Odds API) cuenta una vez, la más reciente. Polymarket cuenta como
  una casa más en el consenso.
- `mejor` considera solo `tipo: "casa"` (el precio de Polymarket es un punto
  medio, no un precio comprable). Es `null` si no hay ninguna casa.
- `evento`/`fecha`/`inicio`: si la pareja está en la cartelera oficial
  (`data/raw/ufc_oficial.json`), mandan los de UFC.com (fecha local, como la
  portada). Si no, lo primero que dijo una fuente.
- Una pelea se muestra si alguna cotización se confirmó en los últimos 4 días
  y su fecha no es anterior a ayer.
- The Odds API trae todo MMA: de ella solo entran las peleas con ambos nombres
  en la base o en la cartelera oficial (para no colar PFL). Las fuentes que ya
  son solo UFC (Betano, BFO, Polymarket) meten todas sus peleas.

### 2.4 Endpoints

| Endpoint | Devuelve | Dueño |
|---|---|---|
| `GET /api/mercado/estado` | `{"fuentes": [EstadoFuente], "hay_cuotas": bool, "en_vivo": bool}` + extras `evento`, `simulado`, `no_calzados`, `consultado` | bloque 3 |
| `GET /api/mercado/peleas?evento=` | `{"peleas": [Pelea 2.3], "actualizado": ts \| null}` | bloque 3 |
| `GET /api/mercado/cartelera` | `{"peleas": {"<a>\|<b>": Pelea 2.3 + "invertida" \| null}}`, con `a`/`b` literales de `/api/estado` | bloque 3 |
| `GET /api/mercado/historial?pelea_id=&desde=&a=` | `{"pelea_id", "invertida", "series": [{"fuente","casa","tipo","puntos": [{"t","a","b","pa","pb"}]}]}` (`a`/`b` americanas, `pa`/`pb` prob. sin margen) | bloque 3 |
| `GET /api/mercado/vivo` | `{"activo": false}` o la sección en vivo (ver abajo) | bloque 4 |

Todos leen de caché/SQLite y responden al instante: **ninguno espera a la
red**. El polling corre en hilos de fondo (uno por fuente, arrancados en el
lifespan de `webui/server.py`).

Detalles de los parámetros:

- `peleas?evento=`: sin distinguir mayúsculas, el texto tiene que estar dentro
  del `evento` de la pelea ("UFC 332", "fight night") o ser igual a su `fecha`
  (`2026-10-10`).
- `cartelera`: la pelea viene **orientada como la cartelera** (su `a` es el
  `a` de `/api/estado`); `invertida: true` avisa que se dieron vuelta respecto
  del `pelea_id`. Clave del diccionario: `"<a>|<b>"` literal.
- `historial`: `desde` acepta ISO 8601 o epoch en segundos (400 si no). Con
  `a=<nombre>` las series se orientan con ese peleador como `a` (lo que
  necesita la cartelera); sin `a`, en el orden del `pelea_id`. Mezcla la serie
  remota de Polymarket (`/prices-history`, horaria) con lo capturado acá.
- `estado.no_calzados`: `{"total", "por_motivo": {"no_calza": n, "homonimo": n},
  "recientes": [{"fuente","texto","motivo","evento","primera_vez","ultima_vez","veces"}]}`.
  `homonimo` = el nombre existe más de una vez en la base: la pelea entra
  (el `pelea_id` es por nombre) pero el `id` queda en `null`.
- `estado.evento`: el evento en vivo (`{"id","nombre","inicio","estelar","fin","simulado"}`)
  o `null`. Convención de la portada: desde la primera parte de la cartelera
  hasta 6 h después del inicio de la estelar (`src/cuotas/calendario.py`).

`EstadoFuente`:

```jsonc
{"clave": "odds_api", "nombre": "The Odds API", "tipo": "casa",
 "activa": true, "motivo": null,          // "Falta ODDS_API_KEY", "HTTP 403 desde Chile", ...
 "ultimo_ok": ts, "ultimo_error": null,
 "intervalo_seg": 120,                    // null si es pasiva (Betano) o está desactivada
 "creditos": {"restantes": 431, "usados": 69, "bajos": false},   // solo Odds API; si no, null
 "rechazadas": 0}                         // extra: cotizaciones rechazadas en la última consulta
```

`activa: false` solo por configuración (sin clave). Una fuente que falla sigue
`activa: true` con `motivo` y `ultimo_error`; con `motivo` lleno y `ultimo_ok`
reciente, las cuotas sirven pero algo avisa (p. ej. BFO usando su captura
anterior, o créditos casi agotados).

`/api/mercado/vivo` con evento en curso:

```jsonc
{"activo": true, "simulado": false,
 "evento": {"id": "ufc-320", "nombre": "UFC 320", "inicio": ts, "estelar": ts},
 "actual": {"pelea_id": "...", "a": Peleador, "b": Peleador,
            "estado": "en_curso", "motivo_clave": "estimado", "motivo": "...",
            "cotizaciones": [ /* 2.3, con mejor_a y mejor_b */ ],
            "series": [{"fuente": "bfo", "casa": "...", "tipo": "casa",
                        "etiqueta": "...", "hasta": ts,
                        "puntos": [{"t": ts, "a": -150, "b": 125, "pa": 0.6, "pb": 0.4}]}],
            "incremental": false, "resolucion": null},
 "peleas": [{"pelea_id": "...", "a": Peleador, "b": Peleador,
             "estado": "por_pelear" | "en_curso" | "terminada",
             "motivo_clave": "...", "motivo": "...", "resolucion": null,
             "consenso": { /* 2.3 */ } }],
 "mercado": {"hay_cuotas": true, "todas_caidas": false, "con_error": []},
 "nota": "...", "consultado": ts}
```

- `desde` y `pelea_id` permiten devolver solo puntos nuevos de la misma pelea.
  Si cambia la pelea, la respuesta contiene su historial completo. `hasta`
  conserva el último instante confirmado; una serie incremental vacía no borra
  los puntos que ya vio el navegador.
- `terminadas` acepta un arreglo JSON de hasta 50 identificadores de pelea
  (máximo 300 caracteres por identificador) junto a `evento_id`. La marca se
  aplica únicamente al evento exacto y a peleas de esa respuesta. Se calcula
  en una copia de la respuesta: no escribe resultados, modelos ni SQLite y
  no altera la memoria compartida por otros navegadores. La UI guarda las
  marcas en `localStorage`, separadas por evento y modo simulado; permite deshacer.
- Una marca manual usa `motivo_clave: "manual"` y «Marcada por ti en este
  navegador.»; no atribuye un ganador. La pelea actual y sus series se vuelven
  a calcular después de aplicar las marcas.
- El marcado automático acepta resultados de la base para ese evento o un
  mercado Polymarket con `closed: true`, `umaResolutionStatus: "resolved"` y
  precios exactamente `1/0`. Una cuota de 99,9 %, un cierre sin resolución,
  una propuesta disputada o que una fuente deje de listar el mercado no bastan.
  También se comunica cualquier deducción por orden y horario como estimación.
- Una resolución del mercado agrega `resolucion: {fuente: "polymarket",
  ganador: "Nombre exacto", a: 1, b: 0, oficial: false,
  etiqueta: "Mercado resuelto"}` (orientada como la cartelera). El 100 % describe
  ese mercado resuelto: no es resultado oficial ni probabilidad del modelo.
- La UI consulta esta caché cada 12 s y pausa al ocultarse la pestaña. Esa
  consulta local no acelera las peticiones de las fuentes ni agrega peticiones
  por pelea a Betano. Si falla, conserva los últimos datos y muestra el aviso.

Modo simulado: variable de entorno `UFC_MERCADO_SIMULADO=1` (expuesta como
`config.MERCADO_SIMULADO`). Activa una fuente `simulada` (visible en
`/api/mercado/estado`) y un evento en vivo falso. Desde el bloque 4 las cuotas
simuladas viven **en memoria** (`src/cuotas/simulado.datos()`): la fuente no
entrega nada a la capa, así que nunca se mezclan con el historial ni el
consenso reales de esas mismas parejas (usa peleadores reales de la base), y
apagada no deja rastro. Solo las lee `/api/mercado/vivo`. El evento falso
tampoco pone a las fuentes reales en cadencia de evento (`calendario.en_vivo()`
mira solo el evento real).
