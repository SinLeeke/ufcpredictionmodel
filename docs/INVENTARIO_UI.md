# Inventario de la interfaz: lo que `app.js` necesita del HTML

Hecho antes del rediseño de la Fase 3 (octubre 2026), contra `webui/static/app.js` tal
como estaba. Es el contrato entre el HTML y el JS: si se renombra algo de esta lista, se
actualiza `app.js` **en el mismo commit**.

## IDs que `app.js` busca (45)

| Zona | IDs |
|---|---|
| Cabecera | `barra-superior`, `reloj-caja`, `reloj`, `vivo-caja`, `chk-vivo`, `btn-refresh`, `btn-opciones`, `panel-opciones`, `titulo-cartelera`, `btn-soltar`, `badge-patas` |
| Paneles | `tab-cartelera`, `tab-parlay`, `tab-datos`, `tab-mantenimiento`, `tab-guia` (se arman como `'#tab-' + data-tab`) |
| Estado | `barra-estado` |
| Cartelera | `bienvenida`, `cartelera-contenido`, `avisos`, `tarjetas-kpi`, `resumen`, `nota-base`, `peleas`, `tabla-wrap`, `tabla-principal` (vía `tabla('#tabla-principal')`) |
| Combinada | `parlay-vacio`, `parlay-contenido`, `explica-tiers`, `btn-sugerir`, `btn-limpiar`, `solo-positivo`, `lista-patas`, `cuenta-patas`, `boleto`, `bankroll`, `parlay-resultado` |
| Cargar | `btn-listar`, `lista-carteleras`, `query`, `btn-cargar-betano`, `archivo`, `btn-subir`, `lista-csvs` |
| Mantenimiento | `salud`, `lista-tareas`, `job-estado`, `btn-cancelar`, `log` |
| Modal | `modal`, `modal-cuerpo` |

## Clases que `app.js` usa como selector

`tab`, `panel`, `seg`, `filtro-tier`, `modal-cerrar`, `pata` (más `.cart` y los `button`
de `#lista-csvs`, `#lista-tareas` y `#boleto`, que genera él mismo).

## Clases de estado que `app.js` pone y quita

| Clase | Dónde | Significa |
|---|---|---|
| `oculto` | en todas partes | `display:none` |
| `activa` | `.tab`, `.panel`, `.seg` | la pestaña, el panel o la vista elegida |
| `activo` | `#vivo-caja` | EN VIVO encendido |
| `oculta` | `#barra-superior` | la barra se escondió al bajar |
| `error` | `#barra-estado` | el mensaje es un error |

## Atributos `data-`

| Atributo | Dónde | Para qué |
|---|---|---|
| `data-tab` | `.tab` | qué panel abre |
| `data-ir` | botones de la bienvenida, la combinada vacía y Mantenimiento | ir a otra pestaña |
| `data-vista` | `.seg` | Tarjetas o Tabla |
| `data-explica` | botón `?` de cada pelea | abre el modal de confianza |
| `data-id` | `.pata` | id de la selección |
| `data-q` | `.cart` (consulta de Betano) y botón quitar del boleto (id de la pata) | |
| `data-fecha` | `.cart` | fecha del evento de Betano |
| `data-n` | botón Analizar de `#lista-csvs` | nombre del CSV |
| `data-r` | botón Ejecutar de `#lista-tareas` | id de la receta |
| `data-tema` | `<html>` | tema claro u oscuro elegido a mano (sin atributo: el del sistema) |
| `data-estilo` | `<html>` | `juez` con el estilo Tarjeta del juez; sin atributo, Transmisión |
| `name="estilo"`, `name="tema"` | radios de `#panel-opciones` | lo que se elige en Opciones (se guarda en localStorage) |

## Clases que `app.js` genera en sus plantillas

Son solo de presentación: se pueden cambiar libremente siempre que se cambien en
`app.js` y en `style.css` a la vez. Las que llevan un valor dinámico codifican un
significado y **no** pueden perderlo:

- `aviso err|warn|info|ok`: la gravedad del aviso.
- `pill fuerte|buena|justa|moneda|nofiable` (vía `claseConf`): la confianza.
- `pill tA|tB|tC|tD`: Probado, Sin ventaja clara, Ruido, Sin validar.
- `pill n-segura|n-buena|n-leve|n-coinflip`: la probabilidad de la selección.
- `pata elegida|bloqueada`, `veredicto bueno|aceptable|flojo|malo`, `pos|neg`, `chip hay|falta`.
- `.porque .si|.quizas|.no`: el veredicto de una selección.
