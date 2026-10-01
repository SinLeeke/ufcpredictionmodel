---
name: UFC Predictor
description: Pronósticos de UFC que dicen dónde hay valor y, sobre todo, dónde no.
---

# Design System: UFC Predictor

> **Estado: en construcción (Fase 3).** Paleta elegida en el paso 3 (Cartel) y dirección
> elegida en el paso 4 (Transmisión), ambas por el dueño. Los tokens (frontmatter) se
> escriben cuando el mundo visual esté construido, no antes: una regla escrita antes del
> build termina defendiéndose contra la realidad.

## Overview

**Creative North Star: "La transmisión de la noche de pelea".**

La interfaz habla como la gráfica que el usuario ve en la tele la noche del evento: la
barra de información con los datos clave, los zócalos que entran de costado con un
nombre y un número, el cara a cara con los dos retratos enfrentados y las estadísticas
en espejo por el medio. Es la dirección **B · Transmisión**, elegida en el paso 4 entre
tres (A · Lona, cenital y con chaflanes; C · Tarjeta del juez, acta con cuadrícula).

### Dirección elegida: B · Transmisión

- **Cabecera** siempre oscura, como la barra de un canal, en los dos temas: marca
  propia, pestañas en mayúsculas condensadas y la pestaña activa como un bloque hueso
  inclinado. Debajo, una regla roja.
- **KPIs** en una sola barra de información partida en cuatro, con separadores
  inclinados y cifras condensadas grandes.
- **Qué apostar** como zócalos: el sello de evidencia a la izquierda (Probado en sólido,
  Sin ventaja clara en neutro), la selección en mayúsculas, y a la derecha cuánto
  apostar, cuánto paga y el valor. La explicación de cada nivel de evidencia va una vez
  por grupo, no repetida en cada fila.
- **Tarjeta de pelea** como cara a cara: los dos retratos ocupan **todo el alto** de la
  tarjeta a cada lado (la cara arriba y centrada, nunca hundida al fondo del encuadre);
  al medio los nombres, los porcentajes enfrentados, la barra y las filas en espejo
  (peleas en UFC, cuota, lo que da la casa, el modelo solo). Abajo, cómo termina.
- **Estelar y coestelar dentro del octágono** (pedido del dueño): un octágono
  **regular**, con los ocho lados iguales (estirado a lo ancho dejaba de parecer la jaula), con
  reja de alambre, baranda acolchada, los ocho postes con su franja roja, la línea
  pintada y la luz de la arena sobre la lona. Los retratos van adentro, arriba; los
  números debajo, en unidades del octágono, así crecen con él. La estelar mide hasta
  800 px y la coestelar 660: el tamaño dice cuál manda. La estelar se reconoce por
  el segmento "Estelar" o por los dos apellidos en el nombre de la cartelera; la
  coestelar por el segmento "Co-estelar" o por ser la vecina de la estelar en el
  orden de la cartelera (y entonces no se rotula "Co-estelar", porque no es seguro).
- **Movimiento** de transmisión: barridos de entrada, barras que crecen, cifras que
  cambian en EN VIVO sin mover nada alrededor.
- **Inclinación de 12°** como único gesto de forma (pestaña activa, sellos, botones,
  separadores). Todo lo demás es recto y sin redondeo.

### Estilo opcional: C · Tarjeta del juez

El dueño la quiere como **estilo alternativo elegible en Opciones**, para quien conozca
las tarjetas de los jueces, pero con **más detalle** que la maqueta (que se veía pobre):
cuadrícula de formulario, campos rotulados, timbres y filas trazadas. Se hace al final,
cuando las cinco pestañas ya estén en B, como una capa de estilo sobre el mismo HTML.

Es una herramienta para operar, no una página para persuadir: el usuario viene a leer una
cartelera y decidir. La expresión vive en los detalles precisos (tipografía, reglas,
cifras, el sello) y nunca tapa la tarea ni el estado. Dos lecturas conviven: la calmada
de antes del evento y la de un vistazo durante el evento, con EN VIVO prendido.

### Antirreferencia: el look actual (hasta septiembre 2026)

Lo que se descarta, visto en las capturas de las cinco pestañas con las tres demos:

- **Rojo para todo.** El mismo rojo es marca, nombre del favorito, porcentaje ganador,
  barra, botón principal, borde de sección, "buena", "Sin ventaja clara", "NO FIABLE",
  error y aviso de movimiento. Una etiqueta buena y una advertencia grave se ven iguales.
- **Todo es una caja con borde de 1 px.** KPIs, avisos, picks, tarjetas de pelea, tareas,
  info-cards y patas usan el mismo rectángulo, sin escala ni ritmo: nada manda.
- **Cifras sin presencia.** El porcentaje del favorito, que es el dato principal de la
  pantalla, mide 20 px, lo mismo que un subtítulo. Las cuotas van en monoespaciada del
  sistema, que se ve como código y no como un marcador.
- **Tipografía del sistema** (Segoe UI / system-ui) con "Archivo Black" declarada pero
  nunca cargada: en la práctica todo cae en Impact o en la sans del sistema.
- **Logo que imita el de UFC** (letras inclinadas en un sello): se reemplaza por una
  marca propia (ver PRODUCT.md).
- **Emojis como íconos** (📡 📄 🔍 📈 🚩 ⏳ ✨ ⏱): cambian de dibujo según el sistema
  operativo y no tienen el peso de la interfaz.
- **Avisos apilados** arriba de todo, uno por fila, antes de los KPIs: la primera vista
  es una pared de advertencias del mismo tamaño.
- **Móvil roto:** a 390 px la cabecera desborda y la página entera gana scroll
  horizontal (mide 624 px de ancho).

Lo que **sí** sobrevive, porque es producto y no look: el contenido y sus explicaciones,
las etiquetas y su significado, el orden por evidencia, la barra dual de probabilidad, el
agrupado por mercado y por pelea en la Combinada, y el espíritu de cartel de pelea (reglas
gruesas en vez de sombras, mayúsculas condensadas, ángulos rectos) como punto de partida
que la dirección elegida puede reinterpretar.

**Key Characteristics (fijas desde ya):**
- Cifras tabulares en todo número que pueda cambiar.
- Tipografías reales, con archivo local y respaldo del sistema (la UI abre sin internet).
- Contraste AA verificado en claro y oscuro.
- Movimiento con propósito y siempre bajo `prefers-reduced-motion`.

## Colors

**Paleta elegida (paso 3): Cartel.** La actual —negro, hueso y rojo— refinada. Se
propuso junto a "Cinturón" (oro de campeonato) y "Octágono" (acero y azul de esquina).
Cada token pasa AA en los 33 pares que usa la UI, en los dos temas (texto 4,5:1; borde de
control 3:1), verificado con un script y no a ojo.

| Rol | Claro | Oscuro | Uso |
|---|---|---|---|
| Fondo | `#ece6db` | `#0e0d0c` | El papel del cartel / la sala a oscuras |
| Superficie | `#faf7f1` | `#181614` | Tarjetas, boleto, modal |
| Superficie 2 | `#e2dbcd` | `#221f1c` | Pistas de barras, celdas, campos |
| Línea | `#cfc6b6` | `#36312b` | Separadores finos |
| Tinta / texto | `#141210` | `#efe9df` | Texto principal, reglas gruesas |
| Texto 2 | `#4a443b` | `#bfb6a8` | Párrafos explicativos |
| Tenue | `#645c50` | `#968c7e` | Rótulos, metadatos (AA incluso sobre Superficie 2) |
| **Rojo cartel** | `#b8102a` | `#f2434f` | Marca, EN VIVO y peligro. Texto sobre él: blanco / tinta |
| Acierto | `#1d6a35` | `#62c27f` | fuerte, segura, ✓ Conviene, EV positivo, modelo presente |
| Alerta | `#875400` | `#e4a83a` | justa, leve, Ruido, ~ Se puede, avisos |
| Error | = rojo cartel | = rojo cartel | NO FIABLE, ✕ No conviene, EV negativo, bloqueos, faltantes |
| Probado | tinta sólida | hueso sólido | Sello de "Probado": tinta invertida, no un color más |

Cada semántico tiene su tinte de fondo (`*-sup`) para avisos: acierto `#e3eedf` /
`#15241a`, alerta `#f6ead0` / `#2a2010`, error `#f6e1df` / `#2e1517`.

### Cómo se reparten las etiquetas

La intensidad del tratamiento codifica la fuerza; la palabra siempre va escrita.

- Confianza: **fuerte** acierto sólido · **buena** acierto con borde · **justa** alerta
  con borde · **moneda** neutro apagado · **NO FIABLE** error sólido.
- Evidencia del mercado: **Probado** sello de tinta sólida · **Sin ventaja clara** neutro
  con borde (ya no rojo) · **Ruido** alerta con borde · **Sin validar** punteado tenue.
- Probabilidad de la selección: **segura** acierto sólido · **buena** acierto con borde ·
  **leve** alerta con borde · **coinflip** neutro.
- Veredicto: ✓ **Conviene** acierto · ~ **Se puede** alerta · ✕ **No conviene** error.

### Named Rules

**La regla del rojo caro.** En Cartel el rojo es a la vez la marca y el peligro: por eso
se gasta poco. Va en la marca, en EN VIVO, en lo que bloquea y en lo que resta. Nunca en
una etiqueta favorable ni en un dato neutro: si algo rojo no es marca, es una advertencia.


**La regla de la señal única.** Cada color semántico significa una sola cosa. El color de
marca no se reutiliza para advertencias, y una advertencia nunca comparte color con una
etiqueta favorable.

## Typography

**Barlow Condensed** (600, 700, 800) para títulos, rótulos, pestañas y cifras grandes;
**Barlow** (400 a 700) para leer. Ambas de Google Fonts, servidas como `woff2` desde
`webui/static/fuentes/` (la UI abre sin internet) con respaldo del sistema. Las dos traen
cifras tabulares (`tnum`), verificado en el archivo.

**Cifras:** coma decimal en toda la interfaz, como en `es-CL` y como ya escribía la Guía:
`65,0 %`, cuota `1,57`, `+11,9 %`. Miles con punto (`$2.500`).

## Layout

Contenedor de 1240 px centrado. Sin scroll horizontal a 390 px; la barra superior se
sigue escondiendo al bajar.

**Combinada a la altura de la pantalla** (pedido del dueño): la lista de selecciones
tiene su propia barra de scroll y la sección completa mide lo que la ventana, así la
página no se alarga hacia abajo y el boleto queda siempre a la vista al lado.

## Do's and Don'ts

- **Do:** jerarquizar las advertencias por gravedad (bloqueo > aviso > información).
- **Do:** que "no apostar" se vea como un resultado, no como un hueco.
- **Don't:** degradados azul→violeta, esquinas de 10 px, sombras difusas, glassmorphism.
- **Don't:** suavizar, esconder o cambiar el significado de fuerte, buena, justa, moneda,
  NO FIABLE, sí/quizás/no, Probado, Sin ventaja clara, Ruido, Sin validar.
- **Don't:** imitar el logotipo de UFC.
