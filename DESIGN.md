---
name: UFC Predictor
description: Pronósticos de UFC que dicen dónde hay valor y, sobre todo, dónde no.
colors:
  fondo: "#ece6db"
  superficie: "#faf7f1"
  superficie-2: "#e2dbcd"
  linea: "#cfc6b6"
  tinta: "#141210"
  texto-2: "#4a443b"
  tenue: "#645c50"
  rojo-cartel: "#b8102a"
  blanco: "#ffffff"
  acierto: "#1d6a35"
  acierto-sup: "#e3eedf"
  alerta: "#875400"
  alerta-sup: "#f6ead0"
  error-sup: "#f6e1df"
  fondo-oscuro: "#0e0d0c"
  superficie-oscuro: "#181614"
  superficie-2-oscuro: "#221f1c"
  linea-oscuro: "#36312b"
  hueso: "#efe9df"
  texto-2-oscuro: "#bfb6a8"
  tenue-oscuro: "#968c7e"
  rojo-cartel-oscuro: "#f2434f"
  acierto-oscuro: "#62c27f"
  acierto-sup-oscuro: "#15241a"
  alerta-oscuro: "#e4a83a"
  alerta-sup-oscuro: "#2a2010"
  error-sup-oscuro: "#2e1517"
  canal: "#0b0a09"
  canal-linea: "#2e2a25"
  canal-tenue: "#a39a8c"
  canal-rojo: "#c41230"
  canal-regla: "#e8293d"
  juez-escritorio: "#dad8d0"
  juez-papel: "#f7f6f1"
  juez-tinta: "#16181b"
  juez-forma: "#3b4a5e"
  juez-rotulo: "#46556a"
  juez-sello: "#b42318"
  juez-lapiz: "#1f4fa8"
  juez-carbon: "#171a1f"
  juez-forma-carbon: "#8d9eb4"
  juez-lapiz-carbon: "#8fb1ff"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(34px, 5vw, 56px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.005em"
  cifra:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "52px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "normal"
  headline:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "0.01em"
  title:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "0.01em"
  body:
    fontFamily: "Barlow, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.07em"
  maquina:
    fontFamily: "Courier Prime, Courier New, ui-monospace, monospace"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.05em"
rounded:
  none: "0"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "22px"
  xl: "30px"
components:
  button-primary:
    backgroundColor: "{colors.rojo-cartel}"
    textColor: "{colors.blanco}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "11px 22px"
  button-primary-hover:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.fondo}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.tinta}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "11px 18px"
  button-secondary-hover:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.fondo}"
  tab-active:
    backgroundColor: "{colors.hueso}"
    textColor: "{colors.canal}"
    typography: "{typography.label}"
    padding: "0 15px"
  sello-probado:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.superficie}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "4px 8px 3px"
  sello-fuerte:
    backgroundColor: "{colors.acierto}"
    textColor: "{colors.superficie}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "4px 8px 3px"
  sello-buena:
    backgroundColor: "{colors.acierto-sup}"
    textColor: "{colors.acierto}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "4px 8px 3px"
  sello-no-fiable:
    backgroundColor: "{colors.rojo-cartel}"
    textColor: "{colors.superficie}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "4px 8px 3px"
  aviso:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.fondo}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "11px 18px"
  input:
    backgroundColor: "{colors.fondo}"
    textColor: "{colors.tinta}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "10px 12px"
---

# Design System: UFC Predictor

## Overview

**Creative North Star: "La transmisión de la noche de pelea".**

La interfaz habla como la gráfica que el usuario ve en la tele la noche del evento: la
barra del canal arriba, la barra de información con los datos clave, los zócalos que
entran de costado con un nombre y un número, el cara a cara con los dos retratos
enfrentados y las estadísticas en espejo, y la pelea estelar dentro del octágono. Es la
dirección **B · Transmisión**, elegida por el dueño en el paso 4 entre tres (A · Lona,
C · Tarjeta del juez).

Es una herramienta para operar, no una página para persuadir: el usuario viene a leer
una cartelera y decidir si apuesta, y casi siempre la respuesta honesta es "no". La
expresión vive en los detalles precisos (la letra condensada, las reglas de tinta, las
cifras grandes y tabulares, los sellos) y nunca tapa la tarea ni el estado. Conviven
dos lecturas: la calmada de antes del evento y la de un vistazo durante el evento, con
EN VIVO prendido. La densidad es media: mucho dato, pero cada bloque con una cifra que
manda.

Lo que se descartó, del look anterior: el rojo para todo (una etiqueta buena y una
advertencia grave se veían iguales), todo metido en la misma caja de 1 px, las cifras
sin presencia, la tipografía del sistema, un logo que imitaba el de UFC, emojis como
íconos y el móvil con scroll horizontal.

**Estilo opcional: C · Tarjeta del juez ("El acta de la pelea").** Se elige en
Opciones, para quien conozca las tarjetas de los jueces. Es la misma información con
otra metáfora: un formulario impreso en tinta pizarra sobre papel, llenado a máquina de
escribir, con la confianza estampada como timbre de goma y el pronóstico encerrado con
el lápiz de pasta del juez. En oscuro es una copia al carbón. Se aplica con
`data-estilo="juez"` en `<html>`: los tokens cambian y el CSS agrega una capa; solo la
tarjeta de cada pelea tiene su propio armado (`actaPelea()` en `app.js`), con las mismas
claves `data-num` para que EN VIVO funcione igual.

**Key Characteristics:**
- Cabecera siempre oscura, como la barra de un canal, en los dos temas.
- Inclinación de 12° como único gesto de forma; todo lo demás recto y sin redondeo.
- Reglas gruesas de tinta en vez de sombras.
- Cifras tabulares con coma decimal en todo número que pueda cambiar.
- Contraste AA verificado en claro y oscuro, en todos los estados.
- Movimiento corto y con propósito, que respeta `prefers-reduced-motion` y no se usa en
  acciones de teclado.

## Colors

**Cartel:** papel hueso, tinta casi negra y un rojo de cartel que se gasta poco. El tema
oscuro es la sala con las luces apagadas, con los mismos roles.

### Primary
- **Rojo cartel** (`rojo-cartel` / `rojo-cartel-oscuro`): marca, EN VIVO, el botón
  principal y todo lo que es peligro o resta (NO FIABLE, ✕ No conviene, EV negativo,
  bloqueos, faltantes, errores) y el anillo de foco. Texto encima: blanco en el claro,
  tinta en el oscuro.

### Secondary
- **Acierto** (`acierto`, tinte `acierto-sup`): fuerte, buena, segura, ✓ Conviene, EV
  positivo, modelo presente.
- **Alerta** (`alerta`, tinte `alerta-sup`): justa, leve, Ruido, ~ Se puede, avisos.

### Neutral
- **Fondo** (`fondo` / `fondo-oscuro`): el papel del cartel; la página.
- **Superficie** y **Superficie 2** (`superficie`, `superficie-2`): tarjetas, boleto,
  modal; pistas de barras, celdas y campos.
- **Línea** (`linea`): separadores finos de 1 px.
- **Tinta / hueso** (`tinta` / `hueso`): texto principal, reglas gruesas, sello Probado
  (tinta invertida, no un color más) y el aviso flotante.
- **Texto 2** y **Tenue** (`texto-2`, `tenue`): párrafos explicativos; rótulos y
  metadatos (pasa AA incluso sobre Superficie 2).
- **Canal** (`canal`, `canal-*`): la cabecera y el pie, iguales en los dos temas. La
  regla roja bajo la cabecera es `canal-regla`.

Cada token pasa AA en los pares que usa la UI, en los dos temas (texto 4,5:1; borde de
control 3:1), medido con script en el paso 3 y otra vez en el navegador al cerrar.

### Cómo se reparten las etiquetas

La intensidad del tratamiento codifica la fuerza; la palabra siempre va escrita.

- Confianza: **fuerte** acierto sólido · **buena** acierto con borde · **justa** alerta
  con borde · **moneda** neutro apagado · **NO FIABLE** error sólido.
- Evidencia del mercado: **Probado** tinta sólida · **Sin ventaja clara** neutro con
  borde · **Ruido** alerta con borde · **Sin validar** punteado tenue.
- Probabilidad de la selección: **segura** acierto sólido · **buena** acierto con borde
  · **leve** alerta con borde · **coinflip** neutro.
- Veredicto: ✓ **Conviene** acierto · ~ **Se puede** alerta · ✕ **No conviene** error.

### Named Rules

**La regla del rojo caro.** El rojo es a la vez la marca y el peligro: por eso se gasta
poco. Va en la marca, en EN VIVO, en el botón principal, en el anillo de foco, en lo
que bloquea y en lo que resta. Nunca en una etiqueta favorable, en un dato neutro ni como adorno de un panel: si
algo rojo no es marca, es una advertencia.

**La regla de la señal única.** Cada color semántico significa una sola cosa. Una
advertencia nunca comparte color con una etiqueta favorable.

### Estilo C · Tarjeta del juez

| Rol | Papel | Copia al carbón | Uso |
|---|---|---|---|
| Escritorio | `juez-escritorio` | `#0d0f12` | El fondo de la página: la mesa donde están las hojas |
| Papel | `juez-papel` | `juez-carbon` | Cada hoja: cabecera, actas, cajas |
| Tinta de máquina | `juez-tinta` | `#e9e7e0` | Lo escrito a máquina: nombres y cifras |
| Tinta del formulario | `juez-forma` | `juez-forma-carbon` | Lo impreso: marcos, filetes y casillas |
| Rótulo | `juez-rotulo` | `#9cabbd` | Los rótulos impresos de cada casillero (AA sobre papel y escritorio) |
| Sello | `juez-sello` | `#f26b5b` | La marca y el peligro, como en B: NO FIABLE, faltantes, errores |
| Lápiz | `juez-lapiz` | `juez-lapiz-carbon` | Solo las marcas del juez: el círculo del pronóstico y el visto de las casillas |

Acierto y alerta son los mismos de Cartel. El destello de EN VIVO es un resaltador
amarillo. La regla del rojo caro se mantiene: el sello rojo es marca o peligro, y el
azul del lápiz nunca lleva un dato que no esté también escrito.

## Typography

**Display Font:** Barlow Condensed 600 / 700 / 800 (con Arial Narrow y la sans del sistema)
**Body Font:** Barlow 400 a 700 (con system-ui)

**Character:** la condensada en mayúsculas es la voz de la gráfica de transmisión;
la Barlow normal es la que se lee tranquila. Las dos son de Google Fonts, servidas como
`woff2` desde `webui/static/fuentes/` (la UI abre sin internet), y traen cifras tabulares.

### Hierarchy
- **Display** (800, `clamp(34px, 5vw, 56px)`, 0,95): el nombre de la cartelera.
- **Cifra** (800, 52 px, 1): los KPI y los porcentajes enfrentados. En el octágono, en
  unidades del contenedor, para crecer con él.
- **Headline** (800, 30 px, 1,05, mayúsculas): títulos de sección.
- **Title** (700, 22 px, 1,08, mayúsculas): la selección en un zócalo, el nombre de un
  peleador.
- **Body** (400, 15 px, 1,55): explicaciones, con línea de 65 a 75 caracteres.
- **Label** (800, 12,5 a 15 px, 0,06 a 0,08 em, mayúsculas): sellos, rótulos, pestañas.

**Máquina (estilo C):** Courier Prime 400 y 700, de Google Fonts y servida desde el
propio servidor; se descarga solo si ese estilo está elegido. Va en todo lo "llenado"
(nombres, cifras, títulos de acta) con el espaciado un poco cerrado (-0,05 em), porque en
monoespaciada la coma ocupa una celda entera. Los rótulos impresos siguen en Barlow
Condensed y los textos largos en Barlow, para que se lean igual de fácil.

### Named Rules

**La regla de la coma.** Coma decimal en toda la interfaz, como en `es-CL`: `65,0 %`,
cuota `1,57`, `+11,9 %`; miles con punto (`$2.500`); espacio fino antes de `%`.

**La regla de la cifra quieta.** Todo número que pueda cambiar usa cifras tabulares,
para que un cambio en EN VIVO no corra lo que tiene alrededor.

## Layout

Contenedor de 1300 px centrado, con márgenes de 28 px (16 a 20 en el celular). El ritmo
sale de 8, 12, 16, 22 y 30 px: apretado dentro de un grupo, generoso entre grupos. Sin
scroll horizontal a 390 ni a 320 px.

- La cabecera es sticky y se esconde al bajar; lo que flota bajo ella (el aviso, el
  índice de la Guía) sube con ella mediante la clase `cab-oculta` en la raíz.
- **Combinada a la altura de la pantalla:** la lista de selecciones y el boleto tienen
  scroll propio y la sección mide lo que la ventana; en el celular se apilan.
- **La estelar y cualquier combate por el título** dentro de un octágono regular
  de ocho lados iguales (hasta 460 px). Se aprovecha más la lona para conservar el
  tamaño de fotos y cifras al reducir el espacio exterior. En escritorio queda a la izquierda y las
  cuotas, modelo, métodos y datos del combate a la derecha; en pantallas estrechas se apilan.
  Una coestelar sin título lleva su rótulo en una tarjeta normal, en ambos estilos.
  La lona tiene textura de tejido, marca impresa y acolchados de esquinas roja y azul;
  cualquier combate por el título repite el mismo degradado metálico de la barra en
  bordes y reja. Los nombres usan dorado sólido (oscuro en claro y luminoso en oscuro),
  las cifras la tinta del tema: los reflejos metálicos no se aplican al texto. El título
  se identifica en ambos temas, confirmado por
  `es_titulo: true`. Este dato se obtiene de la ficha oficial de UFC para la pareja
  y fecha del evento, o de una anotación manual explícita en el CSV. La ubicación en la
  cartelera o los cinco asaltos no confirman un título.
- **Combates desplegables:** encabezado «Peleador 1 vs Peleador 2» para cada combate.
  Todos empiezan plegados; abrir uno muestra su tarjeta u octágono y el acceso al análisis.
  La altura se anima al abrir y cerrar, permite cambiar de dirección durante el
  movimiento y respeta la preferencia de movimiento reducido. El estado abierto
  o cerrado se conserva al refrescar.
  La etiqueta de confianza aparece únicamente en este encabezado, con la explicación
  accesible desde el cuerpo del combate.
- **Esquinas sin título:** nombres y porcentajes rojos para el lado izquierdo y azules
  para el derecho dentro de la tarjeta. Los nombres del encabezado conservan el color
  de texto del tema. Los dos tramos de
  la barra mantienen estos colores aunque cambie el favorito; el dorado identifica títulos.
- **Retratos y comparativa:** cajas 4:3 proporcionadas y apoyadas en una base de su
  esquina en tarjetas normales, con la imagen completa. Cuota, casa y modelo comparten
  columnas y separadores; las etiquetas secundarias tienen más tamaño sin aumentar
  el espacio vacío. Finalización, tendencia, comisión y ayuda tienen lugares estables.
- **Debuts confirmados:** encabezado de advertencia encima del combate y resumen en la
  cartelera. Nombra al debutante o a ambos; un historial faltante no activa este aviso.
- **Análisis debajo del combate:** donut de victoria con intervalos, barras de métodos
  históricos y proyectados, y seis resultados por peleador si existe el modelo. Los
  datos desconocidos se muestran como ausentes. El análisis interior empieza cerrado
  al abrir o reabrir el combate; la persona decide expandirlo. Los refrescos en vivo
  conservan su elección.
- **Últimas cinco peleas:** secuencia reciente de cada peleador con resultado y método.
  Casillas rectas bajo los nombres, antes de los porcentajes, verdes para victorias
  y rojas para derrotas; la letra y el método expresan el dato también sin color.
  En los octágonos las dos secuencias quedan dentro de la lona; cada fila abre el
  detalle completo del historial de ese peleador.
  Se muestran solo los combates disponibles.
- Puntos de quiebre: 1180, 1080, 900, 760, 640, 560 y 480 px.
- En el celular, todo lo que se toca mide al menos 44 px; lo que no puede crecer (el
  "?" de una pelea, la × de la cartelera) extiende su área táctil con un `::after`.

## Elevation & Depth

La profundidad principal sale de tres cosas: el tono (fondo → superficie →
superficie 2), las **reglas gruesas** (3 px de tinta sobre cada panel, roja bajo la
cabecera y sobre el pie) y la inversión (el sello Probado, la pestaña activa y el aviso
flotante van en tinta o hueso sólidos). El modal se separa con un velo de tinta al 66 %.
La jaula no proyecta sombra (se quitó el drop-shadow de arena: contradecía «sin sombras difusas»); sus acolchados conservan luces y sombras pintadas.
El conjunto de combate tiene una sombra tenue; los datos conservan superficies planas.

### Named Rules

**La regla de la regla.** Un panel empieza con una regla de 3 px de tinta de ancho
completo, nunca con una franja de color a un costado ni con una sombra.

## Shapes

Radio cero en todo. El único gesto de forma es la **inclinación de 12°** (`--incl`): la
pestaña activa, los sellos de la cabecera, el botón principal (un paralelogramo con
`clip-path`), los separadores de la barra de KPI y el dibujo de la marca. El octágono
de la estelar es la excepción figurativa: un polígono regular con `clip-path` en capas
(reja, baranda, lona) y ocho postes.

## Components

### Buttons
- **Shape:** rectos, radio 0; el principal es un paralelogramo inclinado.
- **Primary:** rojo cartel con texto blanco (tinta en el oscuro), letra Label; en
  hover pasa a tinta.
- **Secondary:** transparente con borde de tinta de 1,5 px; en hover se invierte.
- **Peligro:** rojo sólido, solo para acciones destructivas.
- **Presión:** `scale(.97)` en 160 ms con `--ease-out`. Foco: contorno de 2 px rojo.

### Chips / sellos
- **Style:** letra Label en mayúsculas, borde de 1,5 px, sin radio. La fuerza se dice
  con la intensidad (sólido, con borde, apagado), y la palabra va siempre escrita.
- **Filtro apagado:** tachado en tenue con borde de línea, sin bajar la opacidad.

### Cards / Containers
- **Corner Style:** 0.
- **Background:** superficie sobre fondo.
- **Shadow Strategy:** ninguna; regla de 3 px arriba (ver Elevation & Depth).
- **Internal Padding:** 14 a 22 px.

### Inputs / Fields
- **Style:** fondo de página, borde de línea de 1,5 px, radio 0, 44 px de alto en el
  celular.
- **Focus:** contorno de 2 px rojo hacia adentro.

### Navigation
- **Cabecera de canal:** marca propia, pestañas en Label de 15 px sobre `canal`; la
  activa es un bloque hueso inclinado con texto de canal. En el celular, las pestañas
  pasan a una segunda fila con scroll horizontal propio.

### Aviso flotante
Mensaje de estado bajo la cabecera que no empuja la página: tinta con texto de fondo
(hueso con texto oscuro en el oscuro), rojo sólido si es un error. Dura lo que toma
leerlo (3 s más 40 ms por carácter, hasta 10 s) y se cierra con un clic.

### Zócalo de "Qué apostar"
Fila de lower third: el sello de evidencia a la izquierda, la selección en Title y a la
derecha cuánto apostar, cuánto paga y el valor. La explicación de cada nivel va una vez
por grupo.

### Cara a cara y octágono
Dos retratos ajustados para conservar la cabeza completa, nombres, porcentajes
enfrentados, la barra dual y las filas en espejo. La estelar y todo título confirmado usan octágono;
los retratos quedan integrados dentro de la lona con margen frente a las diagonales,
junto al historial reciente y la marca propia centrada. La comparativa de cuotas,
métodos y datos finales se presentan en una columna lateral, debajo en pantallas
estrechas. La coestelar sin título usa una tarjeta normal con su rótulo.
Sin foto oficial, una silueta de peleador; nunca la foto de otro.

### Rankings
La cabecera muestra el nombre del peso y una franja inclinada Hombres o Mujeres:
`rk-genero`, con fondo `var(--txt)` y texto `var(--sup)`. Sobre el menú de divisiones
hay una copia en tinta invertida (`rk-copia`), recortada al botón activo con
`clip-path`; al cambiar de peso el recorte viaja con `--dur-viaje` y `--ease-in-out`. La
inclinación usa `--rk-sesgo` de 6 px; en estilo C vale 0 px. En pantalla angosta,
cada grupo del menú tiene scroll propio y trae a la vista la división activa.

### Fondo de la foto (`.foto-cartel`)
Fuera del combate (perfil y listado de Peleadores), la foto va en un cartel que es el
propio octágono regular de la jaula, igual que el marco del campeón en Rankings: un
filete sólido (`--cartel-regla`; 2 px en el listado, 4 px en el perfil) y adentro la
lona, oscura en los dos temas como la cabecera: grafito (`--cartel-*`) con filetes hueso
inclinados 12°. La foto se recorta con la lona y la llena (cabeza arriba del centro):
el peleador nunca se sale de la figura. El campeón usa la variante `.oro` (`--oro-*` y
el metal de la baranda de los títulos en el filete). Sin rojo ni azul: esos colores son
de las esquinas.

La respuesta de la foto trae `X-Fondo`; `fotos.fondo()` devuelve `transparente` si el
archivo tiene canal alfa (PNG o WebP) y `opaco` en los demás casos, incluido JPEG.
`app.js` lo copia a `data-fondo` en `.retrato` al recibir la imagen. El estilo usa
`object-position: 50% 18%` para el retrato opaco y `50% 0` para el transparente.
Este último encuadre corresponde a la foto alta de cuerpo entero (`foto_alta` /
`url_ufc_cuerpo`): al recortarla dentro de la lona conserva visibles la cabeza y el
torso. `identidad_visual.py` aporta metadatos de identidad, no decide este fondo;
`explorar.js` usa el mismo `retrato()` de `app.js` para perfil y catálogo.

Dentro de la lona, el bloque arranca a 10,5 cqw del borde y la barra mide el 84 % del
ancho, centrada: la franja de ancho completo de la línea pintada va de y = 32 a y = 68
(en % de la jaula) y abajo los chaflanes cierran 1 cqw por cada 1 cqw que se baja. Con
la barra a lo ancho y más abajo, sus puntas tocaban la diagonal. Todo lo que se agregue
debajo de la barra (la placa del resultado) se mide contra esa diagonal. La marca
impresa del centro es solo el glifo: el texto "UFC PREDICTOR" se leía a pedazos entre
las casillas del historial. En la lona, el historial abrevia KO/TKO como KO: sus
casillas miden ~27 px.

### Inicio
La portada que se abre por defecto, con la estructura de un sitio de liga y la gráfica
de la transmisión. Tres columnas (dos bajo 1180 px, una bajo 900 px), cada una un panel
con su regla de tinta:

- **Noticias**: la nota de portada a todo el ancho con la foto y el titular encima (velo
  oscuro solo bajo el texto, "hace X h" en un rótulo rojo inclinado), dos destacadas con
  foto y los titulares por día, con "Hoy" en rojo y "Ayer" en tinta. Cada uno abre la nota
  original en otra pestaña. Las horas van en 24 h.
- **Próximas peleas**: las próximas cuatro carteleras confirmadas por UFC; cada pelea en
  dos líneas, una por esquina, con el cuadro de color de la esquina, el ranking y la cuenta
  regresiva a su parte de la cartelera (verde; "En vivo" en rojo con latido durante 6 h).
  "Estelar / Todas" filtra la cartelera estelar o todas las partes.
- **Eventos**: un sello con el número (o FN / RTU) y el nombre; próximos con **Predecir**
  (la cartelera de UFC, sin cuotas), terminados con **Repetir** si la base ya los tiene, y
  los últimos de la base. La acción entra de costado al pasar el mouse o con el foco.
- Arriba, si hay una cartelera cargada, un rótulo invertido para volver a ella.
- **Resultados de las últimas 3 carteleras**, a todo el ancho sobre las columnas: una
  fila plegable por cartelera, con su regla de tinta. Cerrada: el sello del evento, el
  nombre y la fecha, una tira de barras verticales (verde acertó, rojo falló, gris sin
  resultado) y dos marcadores grandes, *ganador* y *método*, en cifras tabulares. Abierta:
  una línea por pelea con el pronóstico de ese día y el resultado lado a lado, el borde
  izquierdo del color del veredicto y dos sellos chicos al final (Ganador, Método) con
  ícono y palabra. El sello del evento se enciende en rojo al abrirla o al pasar el mouse.
  Mientras el servidor calcula, la fila es un esqueleto con brillo y un reloj que late;
  si falla, la regla se vuelve roja y dice por qué. La primera vez están todas cerradas y
  se recuerda cuál dejó abierta cada quien. En el teléfono, la tira baja a una franja
  bajo el nombre y cada pelea se apila en cuatro renglones.
- Las tres cabeceras de columna miden lo mismo (44 px) y el primer rótulo de cada
  columna también: los títulos y las reglas de tinta quedan alineados aunque Próximas
  lleve el botón Estelar/Todas.

### Movimiento de cuotas
Sin evento en curso, la sección queda en modo manual: ofrece el selector de peleas
con cuotas guardadas. Al elegir una, muestra evento y fecha, esquinas, tabla de cuotas
por casa y predicción y el gráfico con las lecturas almacenadas; sin elección el
gráfico queda vacío. El título dice «Movimiento de cuotas» y el sello indica «En vivo»
o «En vivo apagado» según la opción de cabecera. EN VIVO encendido confirma Betano
cada 10 s y la línea avanza con cada lectura; apagado, avanza con refrescos completos
(cada 10 min) y otras fuentes disponibles. Durante un evento en curso cambia a
«Mercado en vivo»: no hay selector, y aparecen controles para marcar peleas terminadas
y el estado del programa.

### Repetición
La cartelera de una noche que ya pasó, predicha con lo que se sabía antes de ese día.
Habla como la repetición de la tele:

- **Rótulo REPETICIÓN** en la cabecera, en hueso sobre el canal y con la fecha del corte,
  en el lugar del reloj de cuotas (no hay cuotas que refrescar: son las de cierre).
- **Aviso informativo** con qué se recortó y qué no (los dos calibradores), y un aviso si
  el corte cae después de la última pelea de la base.
- **Marcador**: "acertó X de N" en cifra grande, la advertencia de que una noche no mide
  un modelo (margen ±50/√N puntos) y una tira de casillas pelea por pelea (verde con
  visto, rojo con cruz, gris si la base no tiene el resultado) que lleva a cada combate.
- **Zócalo del resultado** bajo el cara a cara: el sello Acertó / Falló a la izquierda,
  con ícono y palabra, y "Ganó X · cómo · asalto" al lado. Debajo, el veredicto del
  método en verde o rojo con su ícono ("Acertó el método" / "Falló el método: veía
  decisión"): el sello grande habla solo del ganador. En el octágono es una placa
  angosta en la lona libre bajo la barra; en el acta del juez, un timbre más.
- En el encabezado plegable, el resultado va en tinta sólida con el ícono en verde o
  rojo (`--res-si` / `--res-no`), para no confundirse con los sellos de confianza. Al
  lado, una segunda píldora igual para el método.

### Peleas anteriores (Cargar)
La lista para elegir una repetición, debajo de Betano: fecha y evento arriba; abajo el
cara a cara con cada retrato apoyado en la línea de su esquina (roja la A, azul la B) y
el "vs" al medio, que al pasar el mouse o con el foco se convierte en "Repetir". El
orden de las esquinas nunca dice quién ganó. En el celular los nombres se apilan entre
los dos retratos. Las fotos se piden al acercarse a la pantalla. El CSV propio queda
plegado dentro de **Guardadas**, donde las carteleras con fecha pasada tienen
**Repetir**.

### Modal de una pelea del historial
Desde una fila del historial del perfil se abre un modal con evento y fecha, el
enfrentamiento en el orden de las esquinas sin mirar quién ganó, el octágono, las
estadísticas y el pronóstico reconstruidos con datos disponibles hasta el día
anterior. «Cómo terminó» aparece aparte; si no hay resultado local se indica. Si
falta el modelo ciego a esa fecha en `models/corte/`, el servidor lo entrena al abrir
con solo peleas anteriores y lo conserva para esa fecha. Si no hay `features.csv` o
datos suficientes, muestra las estadísticas recortadas, explica el motivo y deja
la probabilidad no disponible; la heurística no se presenta como modelo. El cuerpo
empieza con `aria-busy="true"` y un esqueleto «Reconstruyendo…»; tras 2,5 s informa
si está entrenando. Un error reemplaza el cuerpo por el motivo y quita el estado de
carga. El modal recibe y devuelve el foco según el componente común, se cierra con
Escape y, mientras está abierto, oculta Combinada.

### Cancelar la carga
El botón «Cancelar» está arriba a la derecha del panel de avance de Cartelera. Es
secundario, de 40 px de alto (44 px en móvil); desaparece si la carga terminó con
error o el panel está en estado `lista`. Antes del modelo detiene la carga en el
próximo aviso de progreso; durante el modelo pide confirmación. Al aceptar, el diario
revierte los archivos y cachés escritos, restaura informes y estado de la cartelera,
y un aviso dice «no se guardó nada y todo quedó como estaba». Mientras espera, el
botón dice «Cancelando…», queda desactivado y el panel/progreso pasa a tenue. Un paso
largo de entrenamiento termina antes de que se complete la cancelación.

### Acta de la pelea (estilo C)
La hoja con su marco impreso de doble filete y las perforaciones de la carpeta. Arriba,
dos casilleros: pelea (su lugar en la cartelera) y segmento. La confianza aparece una
sola vez en el encabezado desplegable. Las dos esquinas con su foto de carnet y el
nombre a máquina, seguidas del historial reciente. Las cifras en
filas como los asaltos de la tarjeta, con el rótulo en la columna del medio. "Cómo
termina" como tres casillas, la más probable tachada con lápiz. El pronóstico encerrado
con lápiz, salvo en moneda y NO FIABLE (un juez no marca ganador ahí). Observaciones
sobre renglones y la letra chica "Estimación del modelo, no una tarjeta oficial". La
estelar y cualquier título confirmado conservan el octágono también en este estilo.
La coestelar sin título y las demás peleas usan el acta normal, de a dos por fila y
una en el celular.

En las otras pestañas el estilo C es una capa: Qué apostar como libro de registro con
los niveles de evidencia como timbres, la Combinada como boleta (casillas y un ticket
con el borde perforado), Cargar y Mantenimiento como planillas, la Guía como reglamento
impreso.

### Opciones
Un panel que cuelga del botón de la cabecera: el estilo (con una muestra dibujada de
cada uno) y el tema (automático, claro u oscuro). Se recuerdan en el navegador; sin
tema elegido, la página sigue al sistema. Cambiar de estilo vuelve a pintar la cartelera
sin animar nada, porque ningún dato cambió.

### Movimiento
Dos curvas para todo: `--ease-out` `cubic-bezier(0.23, 1, 0.32, 1)` para lo que entra,
sale o responde, y `--ease-in-out` `cubic-bezier(0.77, 0, 0.175, 1)` para lo que viaja
por la pantalla. Las entradas usan `transform` y `opacity`; los desplegables de
combates animan su altura al abrir y cerrar.

- Cifras que cambian en EN VIVO: entran desde abajo en 220 ms y dejan un destello que se
  apaga en 900 ms; las barras se reacomodan en 280 ms.
- **El momento de la cartelera: entrar a la jaula.** Al abrir la estelar (o un título)
  la jaula se arma de afuera hacia adentro: la reja y la baranda se asientan (380 ms),
  caen los ocho postes (28 ms de desfase), la línea de la lona se pinta alrededor
  (720 ms), cada retrato entra desde su esquina con un barrido, los porcentajes corren
  de 0 a su valor (560 ms, cifras tabulares) y la barra se llena desde los dos lados.
  Solo con transform, opacity, clip-path y el trazo del SVG; ~1,1 s en total. La marca
  impresa del centro se funde **hasta su opacidad tenue** (7 %, 4,5 % con la placa del
  resultado), leída del CSS, y la escala va en el dibujo: si se animaba a 1 se veía a
  todo color y al terminar desaparecía de golpe.
- Barras de probabilidad y de método: se llenan desde su esquina al **abrir** cada
  combate (420 ms). Antes se llenaban al pintar la cartelera, con los combates
  plegados, y nadie lo veía.
- Repetición: el zócalo del resultado se descubre de izquierda a derecha (380 ms), el
  sello cae al final y después entra el veredicto del método; la tira del marcador se
  completa casilla por casilla (35 ms).
- **Resultados de las últimas carteleras**: la primera vez cada fila sube 10 px (90 ms de
  desfase), su tira crece barra por barra desde abajo (28 ms) y los marcadores corren
  hasta su valor. Al abrir una, la altura se anima como un combate, las peleas bajan una
  tras otra (40 ms) y los sellos se estampan al final de cada línea. La que termina de
  calcularse se descubre de izquierda a derecha.
- Peleas anteriores: las filas nuevas entran como lista (30 ms de desfase); el "vs"
  cede su lugar a "Repetir" (160 ms). La lista tiene scroll propio y se completa sola al
  llegar al final.
- **Pestañas**: la etiqueta hueso viaja de la pestaña vieja a la nueva (300 ms,
  ease-in-out), como el rótulo que se desliza en la gráfica de la tele.
- **Viajes compartidos** (`--dur-viaje: 300ms`; `MOV.viaje: 300`): la etiqueta de
  pestañas, el recorte del menú de Rankings y la foto del listado al perfil viajan
  con la misma duración y `--ease-in-out`. Es aparte de `--dur-press` (160 ms),
  `--dur-entrada` (240 ms), `--dur-salida` (160 ms), `--dur-modal-in` (200 ms),
  `--dur-modal-out` (140 ms), `--dur-conteo` (560 ms) y `--dur-brillo` (700 ms);
  `MOV` refleja esos valores en milisegundos y también define escalón (28 ms, máximo
  12 filas) y desplazamiento (8 px).
- **Cartelera nueva**: las cifras de la barra de información corren hasta su valor y los
  zócalos de "Qué apostar" se descubren de izquierda a derecha (70 ms de desfase).
- **Inicio**, una vez por visita: la foto de portada se asienta y su titular se barre de
  izquierda a derecha; las columnas se completan fila por fila. Las cuentas regresivas
  que cambian suben como las cifras de EN VIVO.
- El rótulo REPETICIÓN de la cabecera se descubre de lado al aparecer.
- Boleto: la pata entra bajando 6 px (200 ms), sale subiendo (140 ms) y las que quedan
  suben a su lugar (FLIP, 200 ms).
- Pestaña: el panel nuevo sube 4 px y aparece en 150 ms.
- Aviso: entra en 220 ms y sale en 160 ms por el mismo borde. Modal: 180 a 200 ms de
  entrada, 140 ms de salida.
- Estilo C, solo en la primera vista de una cartelera: el lápiz encierra al ganador
  (450 ms).
- **Duraciones compartidas** (`--dur-*` en `style.css`, `MOV` en `app.js`): presión y
  realce 160 ms, entrada 240 ms, salida 160 ms, modal 200 / 140 ms, conteo 560 ms,
  brillo de un marco dorado 700 ms (una vez) y 28 ms de desfase entre filas, cortado
  en la fila 12. Rankings, Peleadores, el perfil y su historial usan estas.
- Con teclado (Enter, Espacio, Esc) nada se anima. Con "menos movimiento" se quitan
  desplazamientos, escalas y el latido de EN VIVO; quedan los fundidos y el destello.

## Do's and Don'ts

### Do:
- **Do** jerarquizar las advertencias por gravedad (bloqueo > aviso > información).
- **Do** mostrar "no apostar" como un resultado, no como un hueco.
- **Do** escribir la palabra de cada etiqueta; el color solo refuerza.
- **Do** dar a los controles de la página los colores del tema: selección roja, cursor
  rojo, barras de scroll de línea.
- **Do** usar los íconos de Phosphor (variante bold) de `iconos.js`, un solo set y un
  solo grosor.

### Don't:
- **Don't** suavizar, esconder o cambiar el significado de fuerte, buena, justa, moneda,
  NO FIABLE, sí/quizás/no, Probado, Sin ventaja clara, Ruido, Sin validar.
- **Don't** usar rojo fuera de marca, peligro o la esquina izquierda identificada
  por su nombre. En el combate, el par rojo y azul expresa las esquinas y no el riesgo.
- **Don't** usar sombras difusas, esquinas redondeadas, degradados azul a violeta ni
  glassmorphism.
- **Don't** poner franjas de color a un costado de tarjetas o avisos.
- **Don't** usar emojis ni caracteres sueltos (×, ✓) como íconos.
- **Don't** imitar el logotipo ni el sello de UFC.
- **Don't** mostrar la foto de otro peleador cuando no hay certeza: mejor la silueta.
