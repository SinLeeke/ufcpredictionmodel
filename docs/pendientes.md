# Pendientes

> Actualización 2026-10-04: los bloques 4 y 5 y las mejoras de peleadores fueron
> completados en codex/completar-mercado-ui. Hay 384 casos Python aprobados,
> 74 pruebas UI y 8 contratos de análisis. Las anotaciones siguientes describen
> el estado anterior y se conservan como antecedente. El cierre de SQLite se
> detuvo a pedido del usuario para transferirlo a otro agente; ver
> C:\Users\Juan\Downloads\ufc_predictor\docs\traspaso-sqlite.md.

## Bloque 5 — Cuotas en la Cartelera

**Hecho** (solo `webui/static/app.js`, `webui/static/style.css` y un test en `tests/ui_cards.test.cjs`):

- Estado aparte `MERCADO` y helpers de vista en `app.js`, junto a `etiquetaTitulo()`: `americana()` (signo −
  tipográfico), `etqConsenso()`, `consensoDe()`, `cabConsenso()`, `cuerpoConsenso()`, `detalleCuotas()`,
  `tablaConsenso()`, `ranuraCab()` y `ranuraCuerpo()`.
- Se muestra solo si la cartelera es futura: no es una repetición, no hay `S.corte` y la fecha `evento().iso`
  no es anterior a ayer (`eventoPasado()`). `evento()` ahora devuelve también `iso`.
- Encabezado plegable: «MERCADO −135 FAVORITO / +115 UNDERDOG», o «PAREJA» una vez; «sin cuotas publicadas
  todavía» si la pelea viene `null` o sin consenso. Va en `.combate-etiquetas`, junto al segmento (que ahora
  vive en `.combate-segmento`).
- Tarjeta (debajo del espejo), jaula (sección en la columna de datos) y acta del juez (en `.ac-filas`): una
  fila en espejo con las dos cuotas y su etiqueta, y al medio el botón «Consenso del mercado · N cuotas»
  (`aria-expanded`). Al pasar el mouse (con 120 ms de espera) o con clic o toque se abre un detalle flotante:
  las casas con su cuota americana y la hora, «mejor» marcado de cada lado y Polymarket aparte, en
  «Mercado de predicción». Esc lo cierra, y también un clic afuera.
- Vista de tabla: columna «Mercado».
- `cargarMercado()` pide `/api/mercado/cartelera` y `/api/mercado/estado` al cargar otra cartelera, al apretar
  Refrescar y cada 60 s (no con la pestaña oculta). Nunca llama a Betano: la cadencia de EN VIVO y del auto
  sigue igual. `pintarConsenso()` solo cambia las ranuras que cambiaron, conserva el foco y el detalle abierto,
  y hace destellar la cifra que cambia con `resaltarCambios`, como EN VIVO. Si el endpoint falla, el cuerpo
  dice «No pude leer las cuotas del mercado», el encabezado no muestra nada y el resto de la cartelera se
  pinta igual.
- Reloj de la cabecera (`reloj()` + `estadoMercadoCab()`): si `hay_cuotas` es false, el texto es el mismo de
  antes. Con origen archivo y consenso, dice «archivo · consenso del mercado». Con `creditos.bajos` agrega
  «· The Odds API: quedan N créditos» en ámbar (`--cab-alerta`). El `title` resume cada fuente. No muestra
  claves.
- CSS: sección «consenso del mercado» al final de `style.css`. Favorito usa tinta con regla de 2 px, Underdog
  va en tenue y Pareja en texto 2 con regla tenue. No usa los colores de confianza ni el rojo. Tiene ajustes
  para el estilo juez, ≤ 640 px y movimiento reducido.

**Falta:**

1. **Revisarlo en el navegador.** Claude in Chrome no respondió, así que nada se miró en pantalla. Comprobar:
   - que se lea bien en claro y en oscuro;
   - que no haya scroll horizontal a 390 px;
   - que el detalle flotante no se corte en el último combate ni en la columna de la jaula;
   - el contraste AA de `.cons-etq` y `.cab-mercado`;
   - que la consola no tenga errores.
2. Pasar el detector: `impeccable detect --json webui/static/app.js webui/static/style.css` (no se corrió).
3. Opcional: decidir si en el acta conviene cambiar «Sin cuotas: solo la probabilidad del modelo». Hoy aparece
   junto al consenso cuando no hay cuota de Betano; ese texto se refiere a la casa.

**Cómo retomarlo:**

1. Levantar `python -m uvicorn webui.server:app --port 8012` desde la raíz.
2. Cargar `cards/ufc_2026-10-03_ufc_332_silva_vs_wang.csv` con `POST /api/cartelera/csv`
   `{"nombre": "ufc_2026-10-03_ufc_332_silva_vs_wang.csv"}`. Sus 14 peleas calzan con el consenso de BFO,
   Soldić incluido.
3. Abrir la pestaña Cartelera.

Las demos de `webui/demo` son de agosto, ya pasaron, y por diseño no muestran consenso.

**Tests:**

- `node --test tests/ui_cards.test.cjs`: 30/30, incluido el test nuevo de Favorito/Underdog, signo menos,
  «mejor», Polymarket aparte y «sin cuotas publicadas».
- `node tests/test_analisis.js`: OK.
- `python -m pytest tests -q`: 348 passed.
- Una corrida anterior con `-x` falló una vez en
  `test_cuotas_capa.py::Simulado::test_encendido_agrega_fuente_y_evento`, del bloque 3. Al repetirla pasó:
  parece intermitente, posiblemente por el servidor de prueba que estaba levantado al mismo tiempo.

## Bloque 4 — Mercado en vivo

### Hecho (backend completo, sin UI)
- `GET /api/mercado/vivo?desde=&pelea_id=` en `webui/server.py`, armado en `webui/vivo.py`.
  Sin evento: `{"activo": false}`. Con evento: `evento`, `actual` (Peleador a/b con país,
  campeón y foto; `estado`, `motivo`; `cotizaciones` por fuente × casa con `mejor_a`/`mejor_b`
  entre casas, empates incluidos; `series` del gráfico, una por casa, Polymarket con su nombre
  y `tipo: mercado_prediccion`, con `hasta` = último visto; `incremental`), `peleas` con estado
  y consenso, `mercado` (`hay_cuotas`, `todas_caidas`, `con_error`) y `nota` de honestidad.
  Lee solo caché/SQLite; la parte común se memoriza 4 s. Medido: 0,7 s la primera vez en
  frío con UFC 332 en vivo (lectura de `capa.peleas()`), luego desde memoria; simulado 0,06 s.
- Estados (`vivo.estados`, función pura): señal directa de terminada (resultado en la base
  local; Polymarket cerró el mercado y su descubrimiento de < 30 min ya no lo trae), orden de
  la cartelera (lo anterior a una terminada también terminó), hora de cada parte (por pelear)
  y "en curso" = ESTIMACIÓN (primera sin señal de una parte empezada). Confiabilidad
  documentada en el docstring de `webui/vivo.py`.
- `src/cuotas/simulado.py`: series en memoria derivadas del reloj (3 casas "sim." + un
  "Polymarket sim."), ciclo de 20 min por pelea, `cerradas()` como señal. Ya no entrega nada a
  la capa: lo simulado no contamina historial ni consenso reales y apagado no deja rastro.
- `src/cuotas/calendario.py`: `evento_real()`, `secciones` (hora de cada parte) en el evento,
  y `en_vivo()` mira solo el evento real (el simulado no gasta créditos de The Odds API).
- Contrato actualizado (`docs/contrato-datos.md`, párrafo del modo simulado).
- Paleta categórica del gráfico validada con el validador de la skill dataviz (CVD adyacente
  ≥ 15, visión normal ≥ 18,6, contraste ≥ 3:1 en claro #faf7f1, oscuro #181614, juez #f7f6f1
  y carbón #171a1f), orden fijo: teal, violeta, naranja, magenta, ocre, azul.
  Claro: `#00897c,#6b4cc7,#c25a12,#b03a8c,#8a7000,#3b6fc4`.
  Oscuro: `#1fa592,#8f78ea,#d6711f,#d466b0,#b08a10,#5f8fe0`.
  Polymarket: tinta del tema (`--txt`) punteada, fuera de la paleta. Sin rojo como dato.
  Eje Y decidido: probabilidad sin margen de la esquina A (lineal y comparable entre casas y
  Polymarket), con las marcas etiquetadas también en americana; líneas en escalón (la cuota
  rige hasta que cambia) extendidas hasta `hasta`. Más de 6 casas: el resto en gris sin color.

### Falta
1. **Frontend entero** (nada se carga hoy; `index.html` no se tocó):
   - `webui/static/index.html`: contenedor `<section id="vivo" class="vivo oculto" aria-live="polite">`
     antes de `#inicio-actual`, más `<link href="/vivo.css">` y `<script src="/vivo.js">` después de app.js.
   - `webui/static/vivo.js` (en un IIFE: app.js declara `const` globales y redeclararlos rompe):
     poll a `/api/mercado/vivo` cada 12 s con `desde`=último `t` y `pelea_id`; si `activo` es
     false, ocultar sin hueco. Usar de app.js `retrato()`, `cargarFotos()`, `esc()`, `ico()`,
     `fmt()`, `capturarCifras()/resaltarCambios()` (data-num), `reducir()`. Gráfico SVG propio:
     escalones, etiqueta directa al final de cada línea + leyenda, crosshair con tooltip,
     transición del dominio en 280 ms ease-in-out con rAF (sin tween si reduce motion).
     Americanas con signo menos tipográfico (−) y `+`. Tabla con "Mejor" en palabra/ícono.
     Sello "DATOS SIMULADOS" si `simulado`. Mensaje si `mercado.todas_caidas` o `!hay_cuotas`.
     Aparecer/desaparecer con `grid-template-rows 0fr→1fr` + opacidad.
   - `webui/static/vivo.css`: tokens de la paleta de arriba (claro, oscuro x2 y juez), regla de
     3 px, sin radios ni sombras, sin scroll horizontal a 390 px.
2. `tests/test_mercado_vivo.py`: sin evento → `{"activo": false}`; simulado → forma del
   contrato; `vivo.estados` (señal, orden, horario, estimado); simulado no escribe en SQLite;
   endpoint rápido. Hoy solo se probó a mano (ver abajo).
3. Limitación real vista con UFC 332 en vivo: sin señales (Polymarket solo listaba la estelar),
   el estimado marca "en curso" la PRIMERA pelea aunque se esté peleando la estelar. Ideas sin
   medir: tratar como terminada una pelea cuyas casas dejaron de confirmarla (BFO/Betano retiran
   el mercado al empezar) o leer los resultados que UFC.com muestra durante el evento
   (`ufc_oficial.parsear_evento` no los parsea). La UI debe mostrar el `motivo` "Estimado".
4. Menor: `capa.estado()` usa el evento simulado para `intervalo_seg` mostrado, así que en modo
   simulado informa la cadencia de evento aunque las fuentes reales no la usen.

### Cómo retomarlo
`$env:UFC_MERCADO_SIMULADO='1'; python -m uvicorn webui.server:app --port 8011` y abrir
`/api/mercado/vivo`; construir vivo.js/vivo.css contra esa respuesta; luego probar sin la variable.

### Tests
`python -m pytest tests -q`: 348 passed. Se ajustó `tests/test_cuotas_capa.py::Simulado::
test_encendido_agrega_fuente_y_evento` (la fuente simulada ya no guarda en SQLite).

## Cierre (sesión principal)

- Hecho: se quitó `aria-live="polite"` de `#ranking-lista` en `index.html` (releía ~16 filas por cambio de categoría).
- Saltado a pedido del dueño: `/review-animations`, auditoría con `/impeccable` sobre Rankings, Inicio y Cartelera, y validación final de datos.
- Revisar: en la base real, `/api/mercado/estado.no_calzados` trae «Otro Rakic» y «Otro Tybura» (fuente betano). Parecen filas de un test que escribió en `data/ufc.db` en vez de una base temporal: buscar qué test las genera, aislarlo y borrar esas filas de `cuotas_no_calzados`.
- Pendiente de bloques 2 y 5: revisar en el navegador (claro/oscuro, 390 px, consola), porque Claude in Chrome no respondió.
