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

**Estilo opcional pendiente: C · Tarjeta del juez.** El dueño la quiere elegible en
Opciones para quien conozca las tarjetas de los jueces, con más detalle que la maqueta
del paso 4 (cuadrícula de formulario, campos rotulados, timbres, filas trazadas), como
una capa de estilo sobre el mismo HTML. No está construida.

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
- **Estelar y coestelar** dentro de un octágono regular de ocho lados iguales (hasta 800
  y 660 px); el resto de las peleas en tarjetas cara a cara.
- Puntos de quiebre: 1180, 1080, 900, 760, 640, 560 y 480 px.
- En el celular, todo lo que se toca mide al menos 44 px; lo que no puede crecer (el
  "?" de una pelea, la × de la cartelera) extiende su área táctil con un `::after`.

## Elevation & Depth

Sin sombras. La profundidad sale de tres cosas: el tono (fondo → superficie →
superficie 2), las **reglas gruesas** (3 px de tinta sobre cada panel, roja bajo la
cabecera y sobre el pie) y la inversión (el sello Probado, la pestaña activa y el aviso
flotante van en tinta o hueso sólidos). El modal se separa con un velo de tinta al 66 %.
La única sombra del archivo es el filo rojo de un poste del octágono, que es dibujo y no
elevación.

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
Dos retratos que ocupan todo el alto (cara arriba, nunca hundida), nombres, porcentajes
enfrentados, la barra dual y las filas en espejo. Sin foto oficial, una silueta de
peleador; nunca la foto de otro.

### Movimiento
Dos curvas para todo: `--ease-out` `cubic-bezier(0.23, 1, 0.32, 1)` para lo que entra,
sale o responde, y `--ease-in-out` `cubic-bezier(0.77, 0, 0.175, 1)` para lo que viaja
por la pantalla. Solo `transform` y `opacity`.

- Cifras que cambian en EN VIVO: entran desde abajo en 220 ms y dejan un destello que se
  apaga en 900 ms; las barras se reacomodan en 280 ms.
- Barras de probabilidad y de método: se llenan en 300 ms solo en el primer pintado de
  cada cartelera, con 40 ms de desfase entre tarjetas.
- Boleto: la pata entra bajando 6 px (200 ms), sale subiendo (140 ms) y las que quedan
  suben a su lugar (FLIP, 200 ms).
- Pestaña: el panel nuevo sube 4 px y aparece en 150 ms.
- Aviso: entra en 220 ms y sale en 160 ms por el mismo borde. Modal: 180 a 200 ms de
  entrada, 140 ms de salida.
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
- **Don't** usar rojo en algo que no sea marca o peligro.
- **Don't** usar sombras difusas, esquinas redondeadas, degradados azul a violeta ni
  glassmorphism.
- **Don't** poner franjas de color a un costado de tarjetas o avisos.
- **Don't** usar emojis ni caracteres sueltos (×, ✓) como íconos.
- **Don't** imitar el logotipo ni el sello de UFC.
- **Don't** mostrar la foto de otro peleador cuando no hay certeza: mejor la silueta.
