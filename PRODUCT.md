# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Usuario principal: el dueño del proyecto**, un estudiante universitario de habla
  hispana (Chile, `es-CL`), que lo corre en su propio PC (`127.0.0.1:8000`). Su trabajo
  antes de cada evento de UFC es cargar la cartelera con las cuotas de Betano, leer los
  pronósticos con calma, decidir qué apostar y sobre todo qué no, y, si quiere, armar una
  combinada. La noche del evento puede dejar **EN VIVO** prendido para ver cómo se mueve
  la línea de ganador mientras mira la transmisión.
- **Audiencia de portafolio**: quien ve el proyecto en GitHub, en capturas o con
  `python -m webui.server --demo` (reclutadores, compañeros). Tiene que reconocer a primera
  vista un trabajo serio y honesto. No opera la herramienta: la evalúa.

## Product Purpose

Estima quién gana cada pelea de una cartelera de UFC y cómo termina (KO/TKO, sumisión,
decisión) con un modelo entrenado sobre más de 8.000 peleas reales. Con las cuotas de la
casa dice **dónde hay valor y, sobre todo, dónde no**. El éxito no es que recomiende
apuestas: es que el usuario decida informado. Que no recomiende nada es el resultado más
común y está bien.

## Positioning

La evidencia ordena, no el pago. Cada selección se clasifica por cuánta prueba
estadística hay detrás de su mercado (**Probado**, **Sin ventaja clara**, **Ruido**,
**Sin validar**), no por cuánto promete pagar. El proyecto dice en voz alta que **no le
gana al mercado apostando al ganador** (+1,0 % ± 7,5 sobre 4.744 apuestas) y que la única
ventaja probada son las **decisiones en el mercado de método** (+15,4 % de ROI, t = 3,0,
1.145 apuestas, con 22 % de comisión). Una app de pronósticos que vende seguridad no puede
copiar eso sin dejar de vender seguridad.

## Operating Context

- Servidor local FastAPI en `127.0.0.1`, sin autenticación, a propósito. La UI es
  HTML/CSS/JS vanilla en `webui/static`, sin build y **sin CDN**: tiene que abrir sin
  internet, que es justo cuando se mira una cartelera ya bajada.
- Cinco pestañas: **Cartelera** (avisos, KPIs, Qué apostar, peleas en tarjetas o tabla,
  modal de confianza), **Combinada** (selecciones agrupadas por mercado y por pelea,
  bloqueos excluyente/similar, boleto de hasta 13 patas, bankroll, veredicto y métricas),
  **Cargar** (carteleras de Betano con un clic, CSV, archivos guardados),
  **Mantenimiento** (estado de modelos, tareas de a una, registro) y **Guía**.
- Las cuotas se refrescan solas cada 10 min con origen Betano; **EN VIVO** refresca solo
  la línea de ganador cada 10 s. Reloj de cuenta regresiva en la cabecera.
- Dos situaciones de uso: **antes del evento** (lectura calmada y análisis) y, si se
  puede, **durante el evento** (lectura de un vistazo, números que cambian).
- El celular **no** es objetivo por ahora (el servidor escucha solo en 127.0.0.1), pero la
  página no debe romperse en una ventana angosta (se verifica a 390 px).
- Modo `--demo` con tres carteleras reales ya predichas (`webui/demo/*.json`).

## Capabilities and Constraints

- **Fase 3 es solo presentación.** No se tocan `src/`, `modelado/`, `config.py` ni la
  lógica de `webui/*.py`; el contrato JSON de `/api/estado` queda igual. Única excepción
  aprobada: un endpoint chico de fotos de peleadores con caché en disco.
- **Vocabulario con significado fijo** (se le puede dar jerarquía, nunca suavizarlo ni
  esconderlo):
  - Confianza: **fuerte** (≥ 75 %, acierto ~85 %), **buena** (65-75 %, ~73 %), **justa**
    (60-65 %, ~70 %), **moneda** (< 60 %, ~50 %), **NO FIABLE** (faltan datos de algún
    peleador; se predice pero **nunca** genera apuesta).
  - Probabilidad de una selección: **segura**, **buena**, **leve**, **coinflip**.
  - Veredicto de una selección: **sí / quizás / no** ("Conviene", "Se puede", "No
    conviene").
  - Precio/evidencia: **Probado**, **Sin ventaja clara**, **Ruido**, **Sin validar**.
- Funciones que se mantienen: 5 pestañas, EN VIVO, reloj, tema claro/oscuro, modal,
  constructor de combinada con bloqueos, KPIs, tarjetas de pelea, tabla, log de tareas,
  guía, barra superior que se esconde al bajar.
- **Fotos de peleadores**: Wikipedia/Commons primero (API `prop=pageimages`, con el
  User-Agent de `src/reemplazos.py`), Sherdog de respaldo y, si no hay, una **silueta
  genérica de peleador** (como la foto por defecto de un perfil sin foto, pero de un
  peleador de UFC), nunca una imagen rota. Cruce por **nombre exacto con desempate**:
  mejor sin foto que con la foto de otro. Las fotos de UFC.com no se usan: responden 403
  a los bots y tienen derechos de autor.
- Cifras con **coma decimal** (`es-CL`) en toda la interfaz.
- El dueño quiere que la interfaz pase a ser **más llamativa y limpia, con movimiento**:
  hasta septiembre de 2026 no tenía ninguna animación.

## Brand Commitments

- Nombre: **UFC Predictor**. "UFC" se usa de forma descriptiva (de qué trata), no como
  marca propia.
- **Marca propia, no el sello de UFC.** El dueño prefiere evitar el riesgo legal de
  imitar el logotipo de UFC en un proyecto de portafolio: el logo pasa a ser una marca
  propia del proyecto, con una nota de que no tiene relación con UFC.
- Voz: español de Chile, directo, honesto, explica cada número, nunca optimista. Las
  advertencias no se suavizan.
- Espíritu de partida (puede cambiar de paleta en la Fase 3): **cartel de pelea, no
  dashboard**.

## Evidence on Hand

- Números medidos en `README.md`: acierto 66-69 % (modelo), ~70 % (modelo + mercado),
  Brier 0,195; picks ≥ 75 % aciertan ~81-86 %; ROI de decisiones +15,4 % (t = 3,0, 1.145
  apuestas); moneyline +1,0 % ± 7,5 (4.744 apuestas).
- Tres carteleras reales en `webui/demo/*.json`: aparecen las 5 etiquetas de confianza,
  NO FIABLE, peleadores no encontrados, cuotas sospechosas, movimiento de cuotas y los
  mercados de ganador y de 7 vías.
- No hay fotos de peleadores en el repo, ni testimonios, ni usuarios externos: no se
  inventan.

## Product Principles

1. **No apostar es un resultado de primera clase.** Se diseña con el mismo cuidado que una
   recomendación, no como un estado vacío.
2. **Cada número viene con su significado.** Nadie debería tener que preguntar qué es
   "NO FIABLE" o qué es el EV.
3. **La evidencia ordena; el pago no.** Lo probado va primero aunque prometa menos.
4. **Las advertencias tienen jerarquía, nunca camuflaje.** Un aviso grave no puede verse
   igual que una etiqueta neutra.
5. **Local y sin red.** Una persona, su PC, sin dependencias externas para abrir.

## Accessibility & Inclusion

- Contraste WCAG AA en los dos temas (texto normal 4,5:1; texto grande y elementos de
  interfaz 3:1).
- `prefers-reduced-motion` respetado en toda animación.
- Cifras tabulares en todos los números, para que las columnas no bailen al refrescar.
- El color nunca es la única señal: cada etiqueta lleva su palabra.
- Teclado: el modal se cierra con Esc; los controles son botones reales.
