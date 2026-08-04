<div align="center">

# 🥊 UFC Fight Predictor

**Scraping propio → features diferenciales → XGBoost → Monte Carlo → reporte**

[![Python](https://img.shields.io/badge/Python-3.10%2B-0d0d0d?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-gradient%20boosting-e53935?style=flat-square)](https://xgboost.readthedocs.io/)
[![Sin navegador](https://img.shields.io/badge/scraping-sin%20Selenium-1b5e20?style=flat-square)](#-qué-scrapea-y-cómo)
[![Acierto](https://img.shields.io/badge/acierto-66--69%25-0d0d0d?style=flat-square)](#-qué-tan-bien-funciona-y-qué-no)
[![UI web](https://img.shields.io/badge/UI-local%20incluida-e53935?style=flat-square)](#-interfaz-web)

</div>

> [!WARNING]
> **Proyecto personal de un estudiante universitario**, hecho por curiosidad y por
> diversión. No es un producto y no hay soporte.
>
> Lo que verás son **estimaciones estadísticas con margen de error**, no certezas — este
> mismo README explica por qué el sistema **no le gana al mercado**. Si apuestas, es bajo
> tu propia responsabilidad y nada acá es consejo financiero.

---

## 📊 Los números, primero

| | Acierto | Brier |
|---|:---:|:---:|
| Modelo solo | 66-69 % | 0,211 |
| Mercado solo (Betano) | ~69 % | 0,197 |
| **Modelo + mercado** | **~70 %** | **0,195** |
| Solo picks de confianza ≥75 % | ~85 % | — |

**Acc 0,669 · AUC 0,726 · Brier 0,211** sobre 1.256 peleas fuera de muestra.

Ese techo no es modestia: el mercado de apuestas, con información que nosotros nunca
vamos a tener, llega a ~69 %. Si este sistema marcara 85 %, sería *leakage*, no talento.

```
   UFCStats     Kaggle + BestFightOdds     Wikipedia     Sherdog     Betano
  (oficial)      (cuotas históricas)     (reemplazos)  (fuera UFC)  (cuotas)
      │                   │                    │            │          │
      └───────────────────┴──────────┬─────────┴────────────┴──────────┘
                                     ▼
                          features diferenciales
                           (ELO, estilo, forma)
                                     │
                         ┌───────────┴───────────┐
                         ▼                       ▼
                  modelo GANADOR           modelo MÉTODO
                   (XGBoost bin)         (XGBoost 3 clases)
                         │                       │
                         └───────────┬───────────┘
                                     ▼
                         Monte Carlo (10.000 sims)
                                     │
                                     ▼
                     reporte: 4 tablas + HTML por pelea
```

---

## 🚀 Empezar

```bash
pip install -r requirements.txt
lanzar_ui.bat            # interfaz web en 127.0.0.1:8000
```

O desde la consola, antes de cada cartelera:

```bash
python -m src.betano_scraper "UFC 330"     # baja las cuotas y arma el CSV
python -m src.card cards/mi_evento.csv     # predice  (--detalle para ver más)
```

La construcción inicial de la base tarda ~1 hora y se hace **una sola vez**.
Paso a paso, requisitos y mantenimiento en **[MANUAL.md](MANUAL.md)**.

---

## 🕸 Qué scrapea y cómo

Seis fuentes. **Ninguna necesita navegador**: todo con `requests`, caché en disco y
descarga incremental.

| Fuente | Aporta | Al día |
|---|---|:---:|
| **UFCStats** | resultados, stats por pelea y por round, fichas | ✅ mismo día |
| **Kaggle** (`mdabbert`) | cuotas históricas — lo único que UFCStats no publica | ⏳ ~4 meses |
| **BestFightOdds** | rellena las cuotas que a Kaggle le faltan | ✅ |
| **Wikipedia** | quién entró de reemplazo (corto aviso) | ✅ |
| **Sherdog** | carrera fuera de UFC, solo al predecir debutantes | ✅ |
| **Betano** | cuotas de la cartelera que viene | ✅ |

<details>
<summary><b>Los tres problemas que costó resolver</b></summary>

<br>

**El anti-bot de UFCStats.** El sitio sirve un *challenge* de proof-of-work SHA256
("Checking your browser…"). `src/ufcstats.py` lo resuelve en Python: busca el nonce y el
target de N ceros, itera hasta dar con el hash y hace POST a `/__c` para la cookie. Sin
navegador, sin Selenium.

**Ian Garry no aparecía.** UFCStats lo indexa como *"Ian Machado Garry"*, o sea bajo la
**M**, y el listado alfabético por la inicial de "Garry" nunca lo iba a encontrar. Se
resolvió usando el buscador propio del sitio. Lo mismo con los **dos "Mike Davis"**: ante
varios match exactos gana el de ficha más completa, desempatando por altura, alcance y
récord sin abrir cada perfil.

**Betano mezcla eventos.** Agrupa *todas* las "UFC Fight Night" bajo el mismo ID de liga,
así que una sola página puede traer dos carteleras de fines de semana distintos. El
scraper las separa por fecha. Y su mercado de método viene en dos formatos: **7 vías**
(KO, sumisión y decisión separados) o **5 vías** (KO+sumisión juntos). En el de 5 no
existe un número real de "solo KO", así que esas celdas quedan **vacías** en vez de
inventarse un valor.

</details>

---

## 🧠 Cómo predice

En un deporte 1v1 el modelo no ve stats absolutos sino la **diferencia** entre los dos
peleadores (`X_A − X_B`). Cada pelea genera dos filas espejo, lo que duplica el dataset y
elimina el sesgo de "esquina roja gana más".

| Bloque | Qué mide |
|---|---|
| **Físico y momentum** | edad, alcance, altura, racha, descanso |
| **Nivel** | ELO por categoría, con la victoria **graduada** según cómo se ganó |
| **Matchup de estilo** | golpeo de A amortiguado por la defensa de B, derribos vs defensa de derribo, control, knockdowns |
| **Calidad de oposición** | ELO de los últimos 5 rivales, mejor rival vencido, veces finalizado, momentum |
| **Corto aviso** | +1 si solo A entró de reemplazo, −1 si solo B |

Son **23 features** para el modelo de ganador y **16** para el de método. El
entrenamiento usa una ventana de **5 años**: el MMA cambia y las peleas viejas meten
patrones que ya no aplican (validado en 5 períodos, gana 4/5).

<details>
<summary><b>ELO graduado — y por qué se verificó una idea de 2019</b></summary>

<br>

Una victoria por decisión **dividida** vale 0,55 (casi un empate: los jueces ni se
pusieron de acuerdo), mayoritaria 0,61, unánime 0,91, finalización 1,00. La idea viene de
[FightMatrix](https://www.fightmatrix.com/2019/09/18/tuning-glicko-what-i-learned-confirmed/),
que ajustó un Glicko sobre 10 años de peleas.

Como esa calibración es de 2019, se verificó contra datos hasta 2026 con un test directo:
tras ganar de cada forma, ¿cómo le va al peleador en su **siguiente** pelea?

| Ganó por | n | Gana la siguiente |
|---|---:|:---:|
| **S-DEC** | 775 | **46,8 % ± 3,5** |
| U-DEC | 2.970 | 52,7 % ± 1,8 |
| KO/TKO | 2.730 | 52,3 % ± 1,9 |
| SUB | 1.619 | 52,9 % ± 2,4 |

Lo que sostiene el ajuste **sigue vigente**: la decisión dividida predice ~6 puntos menos
de éxito futuro y los intervalos no se solapan. Lo que **no** se replica es la jerarquía
fina entre unánime y finalización — en nuestros datos son indistinguibles. Se dejaron los
valores originales igual: corregir décimas sobre diferencias dentro del margen de error es
justo el sobreajuste que este proyecto evita.

</details>

<details>
<summary><b>Anti-leakage — lo más fácil de arruinar</b></summary>

<br>

- El **ELO** se construye en un solo pase cronológico, siempre con el rating *pre-pelea*.
  Usar el final en filas históricas infla el AUC a **0,93** (pasó de verdad).
- Calidad de oposición y control usan `bisect`/`searchsorted`: para una pelea de 2019 solo
  entran peleas **estrictamente anteriores**.
- El split es **temporal**, nunca aleatorio. Uno aleatorio pondría una fila y su espejo en
  lados distintos, o sea la misma pelea en train y test.
- `backtest_carteleras.py` reconstruye a cada peleador **tal como estaba el día del
  evento**. Sin eso el backtest daba 92 % falso; el real es 70 %.

</details>

<details>
<summary><b>Qué datos se ignoran a propósito (todo medido)</b></summary>

<br>

De las 22 métricas por pelea que se scrapean, el modelo usa 7. Las otras se probaron como
features diferenciales leak-free y se midieron en 4 períodos:

| Grupo | Gana en | Efecto |
|---|:---:|:---:|
| Ubicación del golpe (cabeza/cuerpo/pierna) | 2/4 | +0,0009 |
| Posición (distancia/clinch) | 1/4 | **−0,0031** |
| Intentos de sumisión | 3/4 | +0,0009 |
| Reversiones | 4/4 | +0,0027 |
| Las 7 juntas | 1/4 | +0,0010 |

Ninguna entró. Reversiones dio 4/4 y estuvo a punto de implementarse, pero su correlación
con ganar es **0,0068** (cero), solo ocurren en el 11 % de las peleas y —lo decisivo— se
probaron **5 grupos**: la probabilidad de que al menos uno dé 4/4 por azar es del **28 %**.
Que las 7 juntas den 1/4 mientras una sola da 4/4 confirma que es ruido.

**Datos por round.** Se scrapean (`r1_sig`, `r2_sig`…) pero no entran al modelo. La
hipótesis del desgaste era buena — Rakic va 36/18/17 golpes por asalto, el total dice
"domina" y el detalle dice "domina un round y se apaga" — pero midió 4/7 períodos y
+0,0010. Con 4 períodos daba 3/4 y parecía prometedor; al extender se cayó.

**`market_edge`** está en `features.csv` y **ningún modelo la usa**: si el modelo viera la
cuota copiaría al mercado y nunca discreparía. El mercado se mezcla después, en `value.py`.

**El modelo de método** excluye oposición y corto aviso — medido, le empeoran la
discriminación KO-vs-sumisión.

</details>

---

## 🖥 Interfaz web

`lanzar_ui.bat` levanta un servidor local (`127.0.0.1:8000`, sin exponer a la red). Hace
lo mismo que la consola sin escribir comandos, y **no re-implementa nada**: la predicción
la sigue haciendo la misma `card.predict_card()` del CLI.

- **Carteleras de Betano listadas solas**, con fecha, número de peleas y estelar. Un clic
  y predice. Avisa cuando Betano todavía tiene pocas peleas montadas.
- **Modo EN VIVO**: refresca la línea de ganador **cada 10 s** con *una sola* petición —
  la página del evento ya trae el mercado de ganador de toda la cartelera. No re-predice:
  la probabilidad del modelo no cambia porque se mueva la cuota, solo la mezcla y el EV.
- **Simulador de combinada** de hasta 13 patas.

<details>
<summary><b>Lo que aporta el simulador no es el EV, es la fragilidad</b></summary>

<br>

El EV de una combinada de patas independientes es `Π(1+EV_i) − 1`, así que 13 patas al
+5 % dan **+88 %**. Es un número que invita a apostar y es una trampa: se cae a **cero** si
cada probabilidad está sobreestimada un **4,8 %**, y el Brier del modelo es 0,21. El
simulador muestra ese umbral de error en grande y degrada su veredicto cuando la
combinada es larga, aunque las 13 patas vengan del mercado probado.

Las selecciones se agrupan en las **tres secciones que Betano ofrece de verdad** — *Quién
gana*, *Cómo gana 7 vías*, *Cómo gana 5 vías* — porque son mercados distintos, con
comisiones distintas (~4 % vs ~22 %) y disponibilidad distinta por pelea.

Y bloquea las combinaciones imposibles distinguiendo los **dos motivos**:

- **Excluyentes** — "Gana A" + "Gana B". No pueden pasar las dos; ninguna casa las acepta.
- **Similares** — "Gana A" + "A por decisión". Una contiene a la otra, y Betano casi no
  sube la cuota: estarías pagando dos veces por la misma información.

La detección no enumera casos: cada selección se traduce al conjunto de desenlaces que la
hacen ganar sobre `{A_KO, A_SUB, A_DEC, B_KO, B_SUB, B_DEC}`. Disjuntos = excluyentes; se
tocan = similares.

</details>

---

## ⚠️ Qué tan bien funciona (y qué no)

Sobre 4 carteleras reales: **27/37 global (73 %)**, pero **18/21 (86 %)** en los picks
≥60 %. La diferencia entre una cartelera buena y una mala no es que el modelo funcione o
no — es cuántas peleas parejas trae.

**Lo que este proyecto no puede hacer:**

- **No le gana al mercado apostando al ganador.** Medido sobre 4.744 apuestas: empate
  técnico (+1,0 % ROI ± 7,5). Y filtrar por "donde el modelo discrepa fuerte" **pierde
  8,1 %**: cuando el modelo se separa de la línea, el equivocado suele ser el modelo.
- La única ventaja que aguantó el test estadístico es apostar **decisiones en el mercado
  de método** (+16,5 % ROI, t=3,1) — un mercado con 22 % de comisión, límites bajos y
  casas que cierran cuentas ganadoras.
- **No predice MMA al 80 %.** Los sitios que lo anuncian no miden fuera de muestra.

---

## 🗂 Estructura

<details>
<summary><b>Qué hace cada archivo</b></summary>

<br>

**Lo que ejecutas**

| Archivo | Qué hace | Cuándo |
|---|---|---|
| `lanzar_ui.bat` | interfaz web | siempre |
| `actualizar_bd.bat` | los 5 pasos de actualización + reentrenar | 1 vez al mes |
| `bajar_datos_ufcstats.bat` | descarga profunda de UFCStats | primera vez |
| `predecir_cartelera.bat` | predice una cartelera | antes de cada evento |
| `train_model.py` | entrena ganador y método | tras cambiar features |
| `backtest_carteleras.py` | valida contra carteleras reales | cuando dudes |
| `evaluar_modelo.py` | calibración y acierto por umbral | cuando dudes |
| `backtest_valor.py` | walk-forward del moneyline **y genera el calibrador** | 1 vez |
| `backtest_metodo.py` | walk-forward del método **y genera `metodo6_xgb.pkl`** | 1 vez |

> Ojo con los dos últimos: el nombre dice "backtest" pero **también construyen modelos**
> que `card.py` necesita.

**Scrapers** — `ufcstats.py` (fichas + anti-bot), `ufcstats_events.py` (resultados),
`ufcstats_fighters.py` (biometría), `ufcstats_fightstats.py` (stats por pelea y round),
`betano_scraper.py`, `bfo_odds.py`, `reemplazos.py`, `sherdog.py`, `scraper.py` (Kaggle),
`fast_fetch.py` (paralelo, ~8 req/s).

**Modelo** — `kaggle_ingest.py` (arma `features.csv`), `features.py` (diferenciales, ELO
graduado, simetría), `oposicion.py`, `control_stats.py`, `ufcstats_ingest.py`,
`simulate.py` (Monte Carlo).

**Predicción** — `card.py` (el orquestador), `value.py` (EV, Kelly, calibrador),
`odds.py`, `visuals.py`, `model.py`.

**Web** — `webui/server.py`, `engine.py`, `parlay.py`, `jobs.py` y `static/`.

**Generadas, no versionadas** — `data/`, `models/`, `outputs/`, `cards/`.

</details>

---

## 🙏 Créditos

Este proyecto no habría sido posible sin estas fuentes y trabajos previos:

**Datos**

- **[UFCStats](http://ufcstats.com/)** — estadísticas oficiales de UFC. Es la fuente
  principal: resultados, stats por pelea y fichas de peleador.
- **[Ultimate UFC Dataset](https://www.kaggle.com/datasets/mdabbert/ultimate-ufc-dataset)**
  de **Matt Dabbert** ([@shortlikeafox](https://github.com/shortlikeafox)) — de acá salen
  las **cuotas históricas**, que son el único dato que UFCStats no publica. Su proyecto
  [tiger-millionaire](https://github.com/shortlikeafox/tiger-millionaire) combina
  UFCStats, BestFightOdds y los rankings de UFC.
- **[BestFightOdds](https://www.bestfightodds.com/)** — fuente original de las cuotas.
  Se consulta directamente solo para las peleas recientes que Kaggle aún no cubre.
- **[Wikipedia](https://en.wikipedia.org/)** — secciones "Background" de cada evento, de
  donde sale qué peleadores entraron de reemplazo.
- **[Betano](https://lat.betano.com/)** — cuotas de las carteleras próximas.
- **[Sherdog](https://www.sherdog.com/)** — historial completo de cada peleador, incluidas
  sus peleas fuera de UFC. Se consulta solo al predecir, para no tratar como desconocido a
  un debutante que trae 15 peleas profesionales atrás.
- **[Rajeev Warrier's UFC Dataset](https://www.kaggle.com/datasets/rajeevw/ufcdata)** —
  usado para inyectar defensa de golpeo y de derribo reales en el entrenamiento
  (`data/processed/defense_stats.csv`).

**Ideas y referencias metodológicas**

- **[FightMatrix](https://www.fightmatrix.com/2019/09/18/tuning-glicko-what-i-learned-confirmed/)**
  — de su artículo sobre ajustar Glicko para MMA salió el **ELO graduado** (una decisión
  dividida vale 0,55, no 1,00) y la confirmación de que ningún sistema de rating pasa de
  "high 60s" de acierto. También la decisión de **no** usar Glicko-2: ellos lo probaron y
  reportaron que la *rating deviation* aporta poco en MMA.
- **[MMA-AI](https://github.com/DanMcInerney/mma-ai)**, de Dan McInerney — el referente
  público en este problema: cinco años de trabajo, modelo y base de datos abiertos, y ~8%
  de ROI en moneyline con dinero real. Su decisión de **excluir las cuotas del set de
  entrenamiento** (incluirlas sube la métrica pero baja el ROI) es la misma que se toma acá
  con `market_edge`, y fue una confirmación externa útil.
- **[FightEdge](https://fight-edge.com/accuracy)** — por publicar su backtest (76,8%) junto
  a su acierto en vivo (65,5%) y su edge contra la línea de cierre. Es el mejor recordatorio
  disponible de por qué este README reporta números fuera de muestra y no de backtest.

**Herramientas**

XGBoost, scikit-learn, pandas, NumPy, Plotly, BeautifulSoup y Requests.

---
---

## 📝 Notas

- Los datos y modelos **no se versionan**: se regeneran con los comandos de arriba.
- **Scraping educado**: delays entre peticiones, caché en disco, User-Agent identificable
  y descarga incremental. Ajusta `WIKI_CONTACT` si vas a scrapear Wikipedia en volumen.
- `CLAUDE.md` documenta la regla del proyecto —*nada entra sin medirse*— y la lista de
  ideas ya descartadas con su número, para no reproponerlas.

<div align="center">
<br>

**hecho por [SinLeeke](https://github.com/SinLeeke/ufcpredictionmodel)**

<sub>Las apuestas deportivas tienen valor esperado negativo salvo ventajas muy específicas
y difíciles de sostener. Los números de arriba son backtests, no una promesa.</sub>

</div>
