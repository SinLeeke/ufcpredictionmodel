---
name: UFC Predictor
description: Pronósticos de UFC que dicen dónde hay valor y, sobre todo, dónde no.
---

# Design System: UFC Predictor

> **Estado: borrador del paso 1 de la Fase 3.** La paleta se fija en el paso 3 y la
> dirección visual en el paso 4, ambas elegidas por el dueño. Los tokens (frontmatter) se
> escriben cuando el mundo visual esté construido, no antes: una regla escrita antes del
> build termina defendiéndose contra la realidad.

## Overview

**Creative North Star: pendiente (paso 4).**

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

**Pendiente (paso 3):** tres paletas propuestas, una de ellas la actual (negro, hueso,
rojo) refinada; cada una con modo claro y oscuro y colores semánticos (acierto, alerta,
error, probado) con contraste AA verificado.

### Named Rules

**La regla de la señal única.** Cada color semántico significa una sola cosa. El color de
marca no se reutiliza para advertencias, y una advertencia nunca comparte color con una
etiqueta favorable.

## Typography

**Pendiente (paso 4).** Requisitos: una cara de cartel para títulos y cifras grandes con
cifras tabulares, una cara de lectura para los párrafos explicativos (hay mucho texto que
leer en la Guía y en los avisos), y archivos `woff2` servidos desde `webui/static`.

## Layout

**Pendiente (paso 4).** Requisitos: sin scroll horizontal a 390 px; la barra superior se
sigue escondiendo al bajar; el boleto de la Combinada sigue pegado al hacer scroll.

## Do's and Don'ts

- **Do:** jerarquizar las advertencias por gravedad (bloqueo > aviso > información).
- **Do:** que "no apostar" se vea como un resultado, no como un hueco.
- **Don't:** degradados azul→violeta, esquinas de 10 px, sombras difusas, glassmorphism.
- **Don't:** suavizar, esconder o cambiar el significado de fuerte, buena, justa, moneda,
  NO FIABLE, sí/quizás/no, Probado, Sin ventaja clara, Ruido, Sin validar.
- **Don't:** imitar el logotipo de UFC.
