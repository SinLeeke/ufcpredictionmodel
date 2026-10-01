# Traspaso: continuar el proyecto desde una sesión en la nube

Para la IA (Claude Code en la nube u otra) que retoma este trabajo. Léelo entero antes
de tocar nada. El dueño del proyecto revisa cada paso; habla con él en español.

## 1. Lo que NO tienes, y por qué no lo necesitas

Este clon **no trae** `data/`, `models/`, `outputs/`, los CSV de `cards/` (salvo el
ejemplo), ni `CLAUDE.md` (son ~40 MB derivados que no se versionan, y `CLAUDE.md` es una
nota local). **No los reconstruyas**: construir la base tarda ~1 hora, gasta créditos de
la sesión y la red de la nube puede bloquear UFCStats, Kaggle o Betano.

Lo que queda por hacer (Fase 3) es **solo presentación**, y para eso alcanza con:

| Necesitas | Úsalo así |
|---|---|
| Ver la interfaz con datos reales | `pip install fastapi uvicorn python-multipart` y `python -m webui.server --demo` (o `--demo gamrot`, `--demo manual`, `--demo medic`) |
| La forma exacta de los datos | `webui/demo/*.json`: la salida real de `/api/estado` para tres carteleras. Entre las tres aparecen las 5 etiquetas de confianza, NO FIABLE, peleadores no encontrados, cuotas sospechosas y los mercados de ganador y de 7 vías |
| Qué significa cada número | `README.md` (diseño y lo que se midió) y `MANUAL.md` (uso, glosario, sección 17-18 de la UI) |
| Verificar que no rompiste nada | `python -m unittest discover -s tests -t .` (las pruebas que necesitan datos se saltan solas) y `node --check webui/static/app.js` |

**No corras** scrapers (`src.ufcstats*`, `src.betano_scraper`, `src.bfo_odds`,
`src.reemplazos`, `src.scraper`), ni `modelado.*`, ni la UI sin `--demo` (intentaría
predecir y pedir fichas a UFCStats). Si algo parece necesitar datos, dilo y para.

## 2. Estado

- Rama `revision-y-rediseno`. Fases 0, 1 y 2 terminadas (verificación de la lógica,
  arreglos y mediciones). El detalle está en `git log` y en las secciones del README
  "Anti-leakage", "Ideas de modelado probadas y revertidas" y "Lo que entró en la
  revisión de septiembre 2026".
- Falta la **Fase 3 (rediseño completo de la UI)** y la **Fase 4 (entrega)**.

## 3. Reglas del proyecto (resumen del CLAUDE.md local)

- **Código y comentarios en español.** Los comentarios explican **por qué**, no qué hace
  la línea.
- **Honestidad en la salida al usuario**: el proyecto reporta que no le gana al mercado,
  que la única ventaja probada es un mercado con 22 % de comisión, y marca lo que no
  sabe. No cambies eso por mensajes optimistas ni suavices advertencias.
- **Nada que cambie predicciones entra sin medirse**. En la Fase 3 no se toca nada de
  eso (ver reglas abajo).
- **Dirección visual de partida**: cartel de pelea, no dashboard. Negro, hueso y rojo;
  reglas gruesas en vez de sombras; mayúsculas condensadas; ángulos rectos. Un
  degradado azul→violeta o esquinas de 10 px van en la dirección equivocada. (La
  Fase 3 puede proponer otras paletas, pero ese es el espíritu.)
- Un commit por arreglo o por pantalla, con el formato de los commits existentes.

## 4. Fase 3 — instrucciones del dueño (textuales)

> Reglas: solo presentación. No toques src/, modelado/, config.py ni la lógica de
> webui/*.py. El contrato JSON queda igual. La UI es HTML/CSS/JS vanilla en
> webui/static, sin build. Antes de cambiar el HTML, inventaría todos los ids, clases y
> data- que usa app.js, y si renombras algo actualiza app.js en el mismo commit. Se
> mantienen todas las funciones: 5 pestañas, modo EN VIVO, reloj, tema claro/oscuro,
> modal, constructor de combinada con bloqueos, KPIs, tarjetas de pelea, tabla, log de
> tareas y guía. No cambies el significado de ninguna etiqueta ni advertencia (fuerte,
> buena, justa, moneda, NO FIABLE, sí/quizás/no, Probado, Sin ventaja clara, Ruido, Sin
> validar): puedes darles mejor jerarquía, pero no suavizarlas ni esconderlas.
>
> Orquestación de skills:
> 1. /impeccable para crear PRODUCT.md y DESIGN.md. Es un rediseño: trata el look actual
>    como antirreferencia, salvo la paleta si decido conservarla.
> 2. /redesign-existing-projects para auditar la UI actual y listar qué se ve genérico o
>    mal jerarquizado.
> 3. Paleta: propón 3 opciones que peguen con la temática de noche de pelea /
>    transmisión de UFC. Una tiene que ser la actual (negro, hueso, rojo) refinada, y las
>    otras dos alternativas coherentes, por ejemplo con acentos dorados de cinturón o
>    tonos de octágono. Cada una con modo claro y oscuro, colores semánticos (acierto,
>    alerta, error, "probado") y contraste AA verificado. **Espera a que elija.**
> 4. /design-taste-frontend para proponer 3 direcciones visuales de la pestaña Cartelera
>    (KPIs, "Qué apostar" y una tarjeta de pelea) usando la paleta elegida. **Espera a que
>    elija una** y fíjala en DESIGN.md.
> 5. Aplica la dirección pestaña por pestaña: Cartelera, Combinada, Cargar,
>    Mantenimiento, Guía. **Muéstrame cada una antes de seguir.** Carga las tipografías
>    de verdad (Google Fonts con respaldo) y usa cifras tabulares en todos los números.
> 6. /emil-design-eng como criterio de pulido, /find-animation-opportunities para decidir
>    qué animar, y /animate para implementarlo: barras de probabilidad que se llenan,
>    transiciones de pestañas, agregar y quitar patas del boleto, hover de tarjetas, y
>    números que cambian en EN VIVO sin mover el layout. Respeta prefers-reduced-motion.
> 7. Opcional: en src/visuals.py cambia solo colores y tipografía de los reportes Plotly
>    para que combinen, sin tocar qué calculan.
> 8. Cierre: /review-animations, luego /impeccable audit y /impeccable polish. Revisa
>    ambos temas, el contraste y la vista móvil a 390 px.

Y para la Fase 4: un resumen final con los bugs encontrados y arreglados, las mediciones,
las decisiones de diseño, la lista de commits y lo que haya quedado pendiente.

### Notas que agregó después

- **`/review-animations` no la puede lanzar la IA** (tiene `disable-model-invocation`).
  Cuando llegues al cierre, avísale y él la escribe.
- **Fotos de los peleadores** en las tarjetas donde se ven los porcentajes, si es posible.
  Es la única excepción aprobada a "no tocar la lógica de webui/*.py": un endpoint chico
  (por ejemplo `/api/foto/{nombre}`) que busque la imagen, la guarde en caché en disco y
  la sirva, sin cambiar el contrato de `/api/estado`. Fuentes:
  - UFC.com responde 403 (anti-bot): no sirve.
  - **Wikipedia/Commons** (licencias libres) con la API `prop=pageimages`, identificándose
    con el mismo User-Agent que usa `src/reemplazos.py`. Primera opción.
  - Sherdog (ya se scrapea en `src/sherdog.py`) como respaldo.
  - Sin foto: un monograma con las iniciales, nunca una imagen rota.
  - Cruce por nombre **exacto con desempate**: los cruces por nombre causaron los dos bugs
    más caros del proyecto (el récord de Ankalaev asignado a Temirov; los dos "Mike
    Davis"). Mejor sin foto que con la foto de otro.
  - Es probable que la red de la nube no deje salir a Wikipedia: implementa con pruebas
    que simulen la respuesta, y la verificación real la hace el dueño en su PC.
- Si alguna skill no está disponible en esta sesión, dilo y sigue los criterios
  escritos aquí.

## 5. Cómo verificar en la nube (no hay navegador del dueño)

1. `python -m webui.server --demo` (y las otras dos demos), en segundo plano.
2. Si puedes instalar un navegador sin cabeza (por ejemplo `pip install playwright` y
   `playwright install chromium`), saca capturas a 1440 px y a 390 px, en los dos temas,
   y revisa la consola: cero errores. Si no puedes, dilo; el dueño lo verifica en su PC.
3. Recorre: las 5 pestañas, modal, cambio de tema, vista tabla, armar una combinada,
   quitar patas, vaciar, y un bloqueo (elegir "Gana A" y después "Gana B" de la misma
   pelea: tiene que quedar bloqueada con su explicación).
4. Pruebas: `python -m unittest discover -s tests -t .` y `node --check webui/static/app.js`.

El dueño revisa los cambios en claude.ai/code y después los baja a su PC
(`claude --teleport` o `git pull`) para probarlos con su base y una cartelera real.
