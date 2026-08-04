# UFC Fight Predictor

Sistema de predicción de peleas de UFC construido de punta a punta: scraping propio →
features diferenciales → XGBoost → simulación Monte Carlo → reporte.

> **Proyecto personal de un estudiante universitario**, hecho por curiosidad y por
> diversión. No es un producto, no hay soporte y no pretende ser un servicio de
> pronósticos.
>
> **Úsalo con cautela.** Todo lo que verás son estimaciones estadísticas con su margen
> de error, medidas y documentadas — no certezas. El propio README dedica una sección a
> explicar por qué este sistema **no le gana al mercado** apostando al ganador.
>
> **Si apuestas, es bajo tu propia responsabilidad.** Las apuestas deportivas tienen
> valor esperado negativo salvo ventajas muy específicas y difíciles de sostener. Nada
> acá es consejo financiero.

Acierta **66-69%** de las peleas, y ~70% cuando se le pasan las cuotas del mercado.
Ese número no es humilde por modestia: es el techo real del problema, y más abajo
explico por qué.

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

## Qué necesita para funcionar

| | |
|---|---|
| **Python** | 3.10+ (probado en 3.14) |
| **Dependencias** | `pip install -r requirements.txt` — pandas, numpy, scikit-learn, xgboost, plotly, beautifulsoup4, requests, lxml, kagglehub |
| **Credenciales** | solo Kaggle (`~/.kaggle/kaggle.json`). Las otras cinco fuentes son públicas |
| **Navegador / Selenium** | **no**. Ni siquiera para el anti-bot de UFCStats ni para Betano |
| **GPU** | no. Entrenar tarda segundos en CPU |
| **Disco** | ~60 MB de datos + ~4 MB de modelos, todos regenerables |
| **Tiempo de construcción** | ~1 hora la primera vez; después las actualizaciones son de minutos |

Guía paso a paso en [MANUAL.md](MANUAL.md).

---

## Qué scrapea y cómo

Seis fuentes, ninguna necesita navegador. Todo con `requests`, caché en disco y
descarga incremental (solo se pide lo que falta).

### 1. UFCStats — la fuente oficial

Estadísticas técnicas de cada peleador y cada pelea. Es la fuente principal porque se
actualiza **el mismo día del evento**.

- **Anti-bot**: el sitio sirve un *challenge* de proof-of-work SHA256 ("Checking your
  browser…"). `src/ufcstats.py` lo resuelve en Python: busca el nonce y el target de N
  ceros, itera hasta encontrar el hash que cumple, y hace POST a `/__c` para obtener la
  cookie. Sin navegador, sin Selenium.
- **Búsqueda de peleadores**: usa el buscador propio del sitio
  (`/statistics/fighters/search?query=`) en vez del listado alfabético. Motivo concreto:
  Ian Garry está registrado como *"Ian Machado Garry"*, o sea indexado bajo la **M**, y
  buscarlo por la inicial de "Garry" nunca lo encontraba.
- **Homónimos**: hay dos "Mike Davis". Cuando aparecen varios match exactos, gana el de
  ficha más completa (se desempata con altura/alcance/récord del propio listado, sin
  abrir cada ficha).
- **Descarga masiva**: `src/fast_fetch.py` paraleliza a ~8 req/s (de 1 hora a 90 s para
  el historial completo).

### 2. Kaggle (`mdabbert/ultimate-ufc-dataset`) — cuotas históricas

Es el único dato que **no** se puede scrapear de UFCStats: las **cuotas históricas**
(moneyline y las 6 del mercado de método). Ese dataset combina stats de UFCStats con
cuotas de [BestFightOdds](https://www.bestfightodds.com/) y rankings de UFC.

Todo lo demás que trae —stats por pelea, biometría, promedios de carrera, y el tipo
exacto de decisión (unánime/dividida/mayoritaria)— lo scrapeamos nosotros directamente,
así que de Kaggle solo se usan las columnas de cuotas.

### 2b. BestFightOdds — para rellenar el hueco de Kaggle

El dataset de Kaggle va **~4 meses atrasado**, así que las peleas más recientes se quedan
sin cuotas. `src/bfo_odds.py` baja esas cuotas directamente de la misma fuente original,
solo para las peleas posteriores al último dato de Kaggle.

Es deliberadamente acotado: **no reemplaza a Kaggle**, lo completa. Re-scrapear los 16
años enteros serían ~4.400 páginas y, peor, obligaría a recruzar 8.000 peleas por nombre
entre dos fuentes — y el cruce de nombres ya causó los dos bugs más caros del proyecto.
Toma la cuota de **cierre** (no la de apertura) y exige match exacto de nombre.

### 3. Wikipedia — quién entró de reemplazo

`src/reemplazos.py`. La sección "Background" de cada evento trae frases como *"However,
Gafurov withdrew due to a leg injury and was replaced by Cody Gibson"*. De ahí sale un
flag binario de **corto aviso**.

Se eligió Wikipedia porque **Tapology devuelve HTTP 403**. La fecha del anuncio casi nunca
está en la misma frase (medido: 6% de los casos), así que no se calcula "días de aviso" —
solo el flag, que es lo extraíble de forma fiable.

### 4. Betano — cuotas actuales

`src/betano_scraper.py`. **No usa navegador**: el listado de carteleras y las peleas vienen
server-rendered con un JSON embebido en el HTML, y cada pelea tiene una API REST propia
(`/api/cuotas-de-partido/...`).

Dos detalles que costaron encontrar:
- Betano agrupa **todas** las "UFC Fight Night" bajo el mismo ID de liga, así que una sola
  página puede traer dos eventos de fines de semana distintos mezclados. El scraper los
  separa por fecha.
- El mercado de método viene en dos formatos: **7-way** (KO, sumisión y decisión separados)
  o **5-way** (KO+sumisión combinados). En el 5-way no existe un número real de "solo KO",
  así que esas celdas quedan **vacías** en vez de inventar un valor.

### 5. Sherdog — la carrera fuera de UFC

`src/sherdog.py`, y **solo en el camino de predicción**, nunca en el de entrenamiento.

UFCStats solo conoce lo que pasó dentro de UFC. Un debutante con 1 pelea en UFC puede
traer 15 peleas profesionales atrás, y el modelo lo trataba como un desconocido: en el
backtest, **8 de 31 fallos involucraban peleadores con menos de 3 peleas registradas**.
Sherdog aporta récord total, racha real y cómo gana/pierde contando la carrera completa.

Dos límites que se respetan a propósito:

- **No trae estadística fina** (golpes, derribos, control). Eso solo existe para UFC.
- **Ganar 12 peleas en shows regionales no equivale a ganarlas en UFC.** Las peleas fuera
  de UFC se marcan aparte para poder ponderarlas distinto, y **no entran al entrenamiento**:
  se probó meterlas al dataset y no mejoró.

---

## Cómo predice

### Features diferenciales

En un deporte 1v1 el modelo no debe ver stats absolutos sino la **diferencia** entre los
dos peleadores (`X_A − X_B`). Cada pelea genera dos filas espejo (A-vs-B y B-vs-A), lo que
duplica el dataset y fuerza una frontera antisimétrica, eliminando el sesgo de "esquina
roja gana más".

Las 23 features del modelo de ganador cubren cinco bloques (el de método usa 16, ver más abajo):

| Bloque | Ejemplos |
|---|---|
| **Físico y momentum** | edad, alcance, altura, racha, días desde la última pelea |
| **Nivel** | ELO por categoría de peso, con la victoria **graduada** según cómo se ganó |
| **Matchup de estilo** | golpeo de A amortiguado por la defensa de B; derribos de A menos la defensa de derribo de B; control, knockdowns, ground share |
| **Calidad de oposición** | ELO de los últimos 5 rivales, mejor rival al que le ganó, cuántas veces lo finalizaron, momentum ponderado por antigüedad |
| **Corto aviso** | +1 si solo A entró de reemplazo, −1 si solo B |

**ELO graduado**: una victoria por decisión dividida vale 0,55 (casi un empate — los jueces
ni se pusieron de acuerdo), mayoritaria 0,61, unánime 0,91, finalización 1,00. Idea tomada
de [FightMatrix](https://www.fightmatrix.com/2019/09/18/tuning-glicko-what-i-learned-confirmed/),
que ajustó un Glicko sobre 10 años de peleas.

Esa calibración es de **2019**, así que se verificó contra nuestros datos hasta 2026 con un
test directo: tras ganar de cada forma, ¿cómo le va al peleador en su **siguiente** pelea?

| Ganó por | n | Gana la siguiente |
|---|---|---|
| **S-DEC** | 775 | **46,8% ± 3,5** |
| U-DEC | 2.970 | 52,7% ± 1,8 |
| KO/TKO | 2.730 | 52,3% ± 1,9 |
| SUB | 1.619 | 52,9% ± 2,4 |

La parte que sostiene el peso del ajuste **sigue vigente**: ganar por decisión dividida
predice ~6 puntos menos de éxito futuro, y los intervalos no se solapan. Lo que **no** se
replica es la jerarquía fina entre unánime y finalización (0,91 vs 1,00): en nuestros datos
son indistinguibles. Se dejaron los valores originales igual — corregir esas décimas sobre
diferencias dentro del margen de error es justo el tipo de sobreajuste que este proyecto
evita a propósito.

### Anti-leakage

Es la parte más fácil de arruinar y la que más se cuidó:

- El ELO se construye en **un solo pase cronológico**, usando siempre el rating
  **pre-pelea**. Usar el ELO final para filas históricas infla el AUC a 0,93 (pasó).
- La calidad de oposición y el control usan `bisect`/`searchsorted` sobre fechas
  ordenadas: para una pelea de 2019 solo entran peleas **estrictamente anteriores**.
- El split es **temporal**, no aleatorio (train ≤ 2024, test ≥ 2025). Un split aleatorio
  pondría una fila y su espejo en lados distintos = la misma pelea en train y test.
- `backtest_carteleras.py` reconstruye cada peleador **tal como estaba el día del evento**.
  Sin eso el backtest daba 92% falso; el real es 70%.

### Dos modelos, no uno

- **Ganador** (XGBoost binario): Acc 0,669 · AUC 0,726 · Brier 0,211.
- **Método** (XGBoost 3 clases KO/Sub/Dec). Usa menos features que el de ganador: la
  calidad de oposición y el corto aviso le **empeoran** la discriminación KO-vs-sumisión
  (medido), porque cómo termina una pelea depende del estilo de los dos, no de contra
  quién pelearon antes. Va **sin balancear**: balancearlo mejora el recall pero destruye
  la probabilidad, y su log loss quedaba peor que cantar las tasas base.
- La predicción de método se **simetriza** (se promedia con la pelea espejo), porque
  "termina por KO" no depende de a quién pusiste en la columna A.

### Qué datos se ignoran a propósito (y por qué)

No todo lo que se scrapea entra al modelo. Cada exclusión está medida, no asumida.

**1. Métricas que scrapeamos y no aportan.** De las 22 métricas por pelea de
`ufcstats_fight_stats.csv`, el modelo usa 7. Las otras se probaron como features
diferenciales leak-free y se midieron en 4 períodos (accuracy, 3 semillas):

| Grupo | Gana en | Efecto |
|---|---|---|
| Ubicación del golpe (cabeza / cuerpo / pierna) | 2/4 | +0,0009 |
| Posición (distancia / clinch) | 1/4 | **−0,0031** |
| Intentos de sumisión (`sub_att`) | 3/4 | +0,0009 |
| Reversiones (`rev`) | 4/4 | +0,0027 |
| Las 7 juntas | 1/4 | +0,0010 |

Ninguna entró. Reversiones dio 4/4 y estuvo a punto de implementarse, pero su
correlación con ganar es **0,0068** (cero), solo ocurren en el 11% de las peleas, y
—lo decisivo— **se probaron 5 grupos**: la probabilidad de que al menos uno dé 4/4 por
puro azar es del **28%**. Es la trampa de comparaciones múltiples: un 4/4 impresiona
si lo predecías antes de mirar, no si elegiste el mejor de cinco.

Que las 7 juntas den 1/4 mientras una sola da 4/4 confirma el diagnóstico: es ruido.

**2. Features que existen pero un modelo excluye.**

- `market_edge` está en `features.csv` y **ningún modelo la usa**. Si el modelo viera la
  cuota, copiaría al mercado y nunca discreparía — y el punto es que aporte información
  propia. El mercado se mezcla después, en `value.py`.
- El modelo de **método** excluye las 6 de calidad de oposición y la de corto aviso
  (usa 16 features contra las 23 del ganador). Medido: le empeoran la discriminación
  KO-vs-sumisión. Tiene sentido — cómo termina una pelea depende del estilo de los dos,
  no de contra quién pelearon antes ni de si uno entró de reemplazo.

**3. Datos por round: se bajan, pero no entran al modelo.**

UFCStats publica el desglose asalto por asalto y el scraper lo captura
(`r1_sig`, `r2_sig`, …). La hipótesis era que el **desgaste** predice: en
Rakic vs Tybura los golpes significativos de Rakic van 36 / 18 / 17 — el total
(71) dice "domina", el detalle dice "domina un round y se apaga".

Se construyeron features de caída de ritmo (82% de cobertura) y se midieron:

| | Gana en | Media |
|---|---|---|
| Predecir el ganador (accuracy) | 4/7 | +0,0010 |
| Predecir el ganador (AUC) | 5/7 | +0,0030 |
| Predecir si llega a tarjetas | 3/5 | +0,0015 |

**No entraron.** Con 4 períodos daban 3/4 y parecían prometedoras; al extender a
7 se cayeron — el mismo patrón que ya había engañado antes. La explicación más
probable es que el desgaste **ya está** en los datos: un peleador que se apaga
pierde más, y eso se refleja en su récord, su ELO y sus tasas de finalización.

Los datos se siguen bajando igual: no cuestan nada, y son el insumo para modelar
el **round exacto** de finalización, un mercado que este proyecto no toca todavía.

**4. Datos disponibles que no se bajan.**

- **Formato de asaltos (3 vs 5).** UFCStats lo publica (`Time format: 3 Rnd (5-5-5)`).
  Se probó una aproximación derivada de la posición en la cartelera: Acc +0,0003,
  AUC −0,0007. Cero. El ELO ya lo capta indirecto, porque los estelares los pelean
  peleadores de ELO alto.
- **Días exactos de aviso** en los reemplazos: Wikipedia solo lo dice en el 6% de los
  casos, así que se usa un flag binario en vez de un número poco fiable.
- **El historial de Sherdog en el entrenamiento.** Se baja y se usa al predecir (arriba),
  pero meterlo al dataset de entrenamiento no mejoró: la calidad del dato no es comparable
  (una victoria regional no es una victoria en UFC) y no trae estadística fina.

**5. Ideas de modelado que se probaron y no quedaron.**

Todas están medidas. La tabla existe para no volver a gastar una tarde en ellas.

| Idea | Resultado medido | Veredicto |
|---|---|---|
| **Calibración post-hoc** (Platt / isotónica, ajustando con 2024) | Brier 0,2167 → 0,2181 (Platt) / 0,2178 (isotónica); log loss peor en las dos | XGBoost ya sale calibrado acá. **Empeora** |
| **Flag de 5 asaltos** (estelar = 1ª pelea del evento, 1.182 filas) | Acc +0,0003, AUC −0,0007 (ruido ±0,0037) | Cero. El ELO ya lo capta indirecto |
| **Ensemble de 10 semillas** | Acc 0,6570 → 0,6576, AUC +0,0014 | No sube el acierto. Solo quita la lotería de semilla |
| **Arquetipos de estilo** (features simétricas de nivel y de choque) | 4 períodos: +0,0049 / ±0 / **−0,0057** / +0,0023. Media **+0,0004** | Empate. Los diferenciales + XGBoost ya capturan el matchup |
| **Revanchas / head-to-head** ("le tiene el número") | el que ganó antes gana la revancha **115/217 = 53,0% ± 6,7**, y las revanchas son el 2,5% de las peleas | El efecto no existe |
| **Glicko-2** en vez de ELO | no implementado: FightMatrix lo probó y lo abandonó (la *rating deviation* es "fairly inconsequential" para MMA) | No vale la complejidad |
| **Balancear las clases del modelo de método** | log loss 1,033 (balanceado) vs 0,950 (sin balancear); anunciaba **el doble** de sumisiones de las que ocurren | Revertido. Estaba peor que cantar las tasas base |
| **Subir a 12 los rivales de la calidad de oposición** | ganaba en 7 de 8 semillas sobre el test… y perdía 2 de 3 al validar en **otros períodos** | Revertido a 5 |

Las dos últimas filas son las que más enseñaron:

- El modelo de método **balanceado** tenía accuracy 0,488 y parecía "solo un poco peor".
  Lo que delató el bug fue comparar su log loss contra el de **cantar las tasas base**
  (1,008): el modelo era literalmente peor que no tener modelo. Ese baseline ahora se
  imprime siempre en `train_model.py`.
- El **N=12** pasó 7 de 8 semillas. Pero 8 semillas son 8 corridas sobre *el mismo período
  de test*: miden consistencia entre semillas, no entre épocas. Para un hiperparámetro
  elegido mirando el test, eso **no es evidencia**. Desde entonces todo se valida en varios
  períodos, que es por qué las tablas de esta sección dicen "4/4" o "3/7" y no "p < 0,05".

**6. Mercados que se pueden predecir pero no validar.**

Golpes over/under, round exacto, total de rondas. Hay señal: para los golpes significativos
combinados el AUC es **0,645-0,651** en las líneas 50+/75+/100+/125+, comparable al modelo
de ganador.

**No se cubren igual**, porque las únicas cuotas históricas del proyecto son moneyline y
método 6-vías: **cero cuotas históricas de golpes, rondas o asalto exacto**. Sin ellas no
hay forma de saber si ese 0,65 de AUC le gana al precio, y las casas cotizan bien los
totales.

El caso de **"¿llega a tarjetas?"** muestra por qué esto importa. El sesgo es real y
grande: el mercado dice 44,1% (sin comisión) y ocurre **50,2%** — 6 puntos, estables en
todo el rango de precio y en todos los tramos. Y aun así **pierdes**: cobrar ese sesgo
dutcheando las dos patas de decisión cuesta 10 puntos de comisión, ROI real **−6,1%
(t=−3,1)**. Un mercado dedicado de 2 vías cobra ~5% en vez de 22% y ahí sí saldría, pero
eso es álgebra, no un resultado: no existe una sola cuota histórica de ese mercado para
probarlo. El camino honesto es empezar a registrarlas ahora y validar en unos meses.

*(Nota metodológica: al calcular "apostar a que NO llega" salía +12,6%. Era falso —
el precio del "No" estaba construido como complemento sin comisión, o sea un precio que
ninguna casa ofrece. Toda pata sintética tiene que pagar su propio vig.)*

**7. Datos viejos que se descartan por antigüedad.** El modelo NO entrena con todo el
historial: usa **los últimos 5 años**. El MMA cambia, y las peleas viejas meten patrones
que ya no aplican. Validado en 5 períodos por dos métricas: gana 4/5 en AUC (+0,0117) y
4/5 en accuracy (+0,0096). Se controla con `TRAIN_WINDOW_YEARS` en `config.py`.

### Monte Carlo

10.000 simulaciones. No es cosmético: en vez de repetir la `p` de XGBoost, muestrea
`p_i ~ Beta(α, β)` centrada en `p` para propagar la **incertidumbre** del modelo, y sortea
el método por simulación. De ahí sale el intervalo creíble, no un número puntual frágil.

### Mezcla con el mercado

Si el CSV trae cuotas, la probabilidad que manda es la **calibrada** (modelo + mercado):

| | Acierto | Brier |
|---|---|---|
| Modelo solo | 67,2% | 0,2143 |
| Mercado solo | 69,4% | 0,1968 |
| **Mezcla** | **70,3%** | **0,1950** |

Honestidad obligatoria: casi todo el mérito es del mercado. Los pesos ajustados son
mercado ~1,06 y modelo ~0,20 — el modelo aporta información real, pero vale como 1/5.

---

## Qué hace

Para cada cartelera genera:

1. **Cuatro tablas**: (1) modelo solo, (2) mercado solo, (3) modelo + corto aviso *— solo
   si hay reemplazos*, (4) todo junto. Separadas a propósito: cuando iban mezcladas, un
   pick donde el modelo iba tibio (56%) y la casa muy convencida (75%) aparecía como
   "fuerte 79%" y se leía como si el sistema estuviera seguro.
2. **Resumen accionable**: qué apostar, ordenado por **evidencia** y no por EV.
3. **Un HTML por pelea** con donut de victoria y barras de método.

Además marca lo que **no** sabe: peleas con `pocos datos` no generan apuesta aunque el EV
se vea rico, y avisa si las cuotas del CSV son más generosas que las de una casa real
(síntoma de números puestos a ojo).

---

## Interfaz web

`lanzar_ui.bat` levanta un servidor local (`127.0.0.1:8000`, sin exponer a la red) que
hace lo mismo que la consola sin escribir comandos: predice carteleras, baja las cuotas de
Betano **refrescándolas cada 10 minutos** con marca de movimiento de línea, dispara las
tareas de mantenimiento con el log en vivo, y arma **parlays de hasta 13 patas**.

No re-implementa nada: la predicción la sigue haciendo la misma `card.predict_card()` que
usa el CLI, solo que además devuelve sus estructuras en vez de imprimirlas y tirarlas.

Lo único que la UI agrega como lógica propia es el **simulador de parlay**, y su aporte no
es el EV sino la **fragilidad**. El EV de una combinada de patas independientes es
`Π(1+EV_i) − 1`, así que 13 patas al +5% dan +88% — un número que invita a apostar y que
es una trampa: se cae a **cero** si cada probabilidad está sobreestimada un **4,8%**, y el
Brier del modelo es 0,21. El simulador muestra ese umbral de error en grande y degrada su
propio veredicto cuando la combinada es larga, aunque las 13 patas vengan del mercado
probado. Además clasifica cada pata por el respaldo medido del mercado (decisión en método
t=3,1 / moneyline t=0,3 / finalización t=0,5).

### Modo EN VIVO

Un interruptor en la cabecera refresca la **línea de ganador cada 10 segundos**. Es viable
porque la página de la cartelera de Betano ya trae embebido el mercado de ganador de todas
sus peleas: **una sola petición** actualiza el evento completo.

Y no vuelve a predecir. La probabilidad del modelo no cambia porque se mueva la cuota —
sale de los stats del peleador. Lo que sí cambia es la mezcla con el mercado, el EV y
Kelly, y eso es aritmética en memoria. Por eso puede ir a segundos.

El refresco **completo** (que incluye el mercado de método, con una petición *por pelea*, y
sí re-corre el modelo) sigue en 10 minutos. El modo en vivo le cede el paso cuando toca,
para no solapar peticiones.

Arranca **apagado a propósito**: son ~6 peticiones por minuto a Betano y eso solo se
justifica mientras miras la cartelera en pantalla. Dejarlo prendido de fondo es la forma de
que te bloqueen la IP.

Las selecciones se agrupan en las **tres secciones que Betano ofrece de verdad** — *Quién
gana*, *Cómo gana 7 vías* (KO, sumisión y decisión separados) y *Cómo gana 5 vías* (cuando
no separa KO de sumisión) — porque son mercados distintos, con comisiones distintas (~4% vs
~22%) y disponibilidad distinta por pelea. En una sola lista era imposible ver que una pelea
con 5 vías simplemente no ofrece KO por separado.

Y bloquea las combinaciones imposibles distinguiendo los **dos motivos**, porque no son lo
mismo:

- **Excluyentes** — "Gana A" + "Gana B", o "A por KO" + "A por decisión". No pueden pasar
  las dos; ninguna casa acepta esa combinada.
- **Similares** — "Gana A" + "A por decisión", o "A por finalización" (5 vías) + "A por KO"
  (7 vías). Una contiene a la otra, y Betano casi no sube la cuota al combinarlas: estarías
  pagando dos veces por la misma información.

La detección no enumera casos: cada selección se traduce al conjunto de desenlaces
elementales que la hacen ganar, sobre `{A_KO, A_SUB, A_DEC, B_KO, B_SUB, B_DEC}`. Si dos
conjuntos son disjuntos son excluyentes; si se tocan, similares. Agregar un mercado nuevo
(rounds, distancia) es agregar una entrada al diccionario, no escribir reglas.

---

## Cómo se usa

```bash
pip install -r requirements.txt
```

Y las credenciales de Kaggle, que son lo único que pide login: en kaggle.com →
*Account* → *Create New API Token*, y el `kaggle.json` va a `~/.kaggle/kaggle.json`.

### 1. Construir la base (primera vez, ~1 hora)

```bash
python -m src.ufcstats_events      # resultados históricos (~2 min)
python -m src.ufcstats_fighters    # biometría: altura, alcance, DOB (~3 min)
python -m src.ufcstats_fightstats  # stats por pelea (~20 min, reanudable)
python -m src.reemplazos           # reemplazos de Wikipedia (~25 min)
python -m src.bfo_odds             # cuotas recientes que Kaggle no tiene (~12 min)
python -m src.scraper              # dataset Kaggle + features + ELO
python train_model.py              # entrena los dos modelos
python backtest_valor.py           # calibrador del mercado de ganador
python backtest_metodo.py          # calibrador + modelo de método 6-vías
```

Los dos últimos son los que habilitan el análisis de valor: sin ellos `card.py`
predice igual pero no recomienda apuestas.

### 2. Mantenerla al día

Todos los scrapers son **incrementales**: consultan solo lo que falta y cachean el resto,
así que actualizar es barato aunque construir de cero no lo sea.

```bash
actualizar_bd.bat     # Windows: hace los 5 pasos con doble clic
```

Hace: resultados nuevos de UFCStats → reemplazos nuevos de Wikipedia → dataset Kaggle →
features/ELO → reentrenar. Una corrida típica consulta **1 o 2 eventos**, no los 782.

Dos detalles del incremental que importan:

- `ufcstats_events` **re-baja los eventos que se cachearon antes de pelearse**. Si
  scrapeaste la cartelera el viernes, quedó guardada sin ganadores; sin esto se
  congelaba así para siempre y sus peleas nunca entraban al entrenamiento.
- `--todo` fuerza rebajar todo, por si cambian los selectores del sitio.

### 3. Bajar las cuotas de una cartelera

```bash
python -m src.betano_scraper                  # lista las disponibles
python -m src.betano_scraper "UFC 330"        # -> cards/betano_<fecha>_<estelar>.csv
```

### 4. Predecir

```bash
python -m src.card cards/mi_evento.csv
python -m src.card cards/mi_evento.csv --detalle   # + últimas 5 peleas de cada uno
```

El CSV mínimo son tres columnas; las cuotas son opcionales pero valen +3 puntos de acierto:

```csv
fighter_a,fighter_b,segment,odds_a,odds_b,odds_a_ko,odds_a_sub,odds_a_dec,odds_b_ko,odds_b_sub,odds_b_dec
Islam Makhachev,Ian Machado Garry,Estelar,1.33,3.15,4.50,2.70,5.50,9.00,6.00,13.00
```

### 5. Verificar que sigue funcionando

```bash
python backtest_carteleras.py 10          # carteleras reales, sin ver el futuro
python backtest_carteleras.py --evento Ankalaev
python evaluar_modelo.py                  # acierto y calibración fuera de muestra
python -m src.oposicion "Ilia Topuria"    # últimas 5 peleas de un peleador
```

Guía completa de uso en [MANUAL.md](MANUAL.md).

---

## Qué tan bien funciona (y qué no)

| | Acierto |
|---|---|
| Modelo solo | 66-69% |
| Modelo + cuotas | ~70% |
| Solo picks de confianza ≥75% | ~85% (n=227) |

Sobre 4 carteleras recientes: 27/37 global (73%), pero **18/21 (86%)** en los picks ≥60%.
La diferencia entre carteleras no es que el modelo funcione o no — es cuántas peleas
parejas trae cada una.

**Lo que este proyecto no puede hacer:**

- **No le gana al mercado apostando al ganador.** Medido sobre 4.744 apuestas: empate
  técnico (+1,0% ROI ± 7,5). Y filtrar por "donde el modelo discrepa fuerte" **pierde
  −8,1%**: cuando el modelo se separa de la línea, el equivocado suele ser el modelo.
- La única ventaja que aguantó el test estadístico es apostar **decisiones en el mercado
  de método** (+16,5% ROI, t=3,1) — un mercado con 22% de comisión, límites bajos y casas
  que cierran cuentas ganadoras.
- **No predice MMA al 80%.** Ni nadie. FightMatrix, tras años optimizando, tampoco pasa de
  "high 60s", y el mercado mismo acierta 69%. El contraste más claro está publicado por
  [FightEdge](https://fight-edge.com/accuracy), que reporta **76,8% en su backtest
  walk-forward** y, en la misma página, **65,5% en predicciones en vivo** (171 registradas)
  con un edge de **−1,4%** contra la línea de cierre. Los dos números son suyos y son
  honestos al publicarlos juntos; la lección es que un backtest y el rendimiento real
  pueden separarse 11 puntos. Cuando este proyecto muestre >80%, la primera hipótesis es
  leakage, no talento.

---

## Estructura

```
src/
  ufcstats.py             scraper de fichas + anti-bot PoW
  ufcstats_events.py      historial de eventos y resultados
  ufcstats_fighters.py    biometría (altura, alcance, DOB, stance)
  ufcstats_fightstats.py  stats por pelea (golpes, derribos, control)
  ufcstats_ingest.py      cruce de las tablas de UFCStats con el dataset
  fast_fetch.py           descarga paralela
  sherdog.py              carrera fuera de UFC (solo al predecir)
  betano_scraper.py       cuotas (sin navegador)
  reemplazos.py           corto aviso vía Wikipedia
  kaggle_ingest.py        ingesta + ELO + features (leak-free)
  bfo_odds.py             cuotas de BestFightOdds (rellena el hueco de Kaggle)
  scraper.py              orquestador de la ingesta (Kaggle -> features)
  features.py             features diferenciales, ELO graduado, simetría
  oposicion.py            calidad de los últimos rivales
  control_stats.py        grappling/control con lookup sin leakage
  odds.py                 conversión de cuotas (decimal / americana / implícita)
  model.py                arquitectura y entrenamiento de los dos modelos
  value.py                EV, Kelly, calibrador con el mercado
  card.py                 orquestador: predice una cartelera
  simulate.py             Monte Carlo
  visuals.py              reportes HTML

webui/
  server.py               API local (FastAPI) y estáticos
  engine.py               puente a card.predict_card, sin lógica propia
  parlay.py               combinadas: evidencia por mercado y fragilidad
  jobs.py                 tareas largas en subproceso con log en vivo
  static/                 index.html + app.js + style.css (sin CDN ni build)

train_model.py            entrena ganador + método
backtest_carteleras.py    valida contra carteleras reales
backtest_valor.py         walk-forward del mercado de ganador
backtest_metodo.py        walk-forward del mercado de método
evaluar_modelo.py         acierto y calibración por tramo, fuera de muestra
```

---

## Créditos

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

## Notas

- Los datos y modelos **no se versionan** (se regeneran con los comandos de arriba).
- Scraping educado: delays entre requests, caché en disco para no repetir, User-Agent
  identificable, y descarga incremental para no re-pedir lo que ya se tiene. Ajusta la
  variable de entorno `WIKI_CONTACT` si vas a scrapear Wikipedia en volumen.
- Proyecto personal con fines de aprendizaje. Las apuestas deportivas tienen valor
  esperado negativo salvo ventajas muy específicas y difíciles de sostener; los números
  de arriba son backtests, no una promesa de rendimiento.
