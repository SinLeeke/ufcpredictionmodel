# Manual de usuario — UFC Predictor

Todo se corre desde la carpeta del proyecto:

```
cd ruta/a/ufc_predictor
```

Este manual es el **uso diario**: qué comando correr, qué esperar y cómo leer la
salida. El **porqué** de cada decisión de diseño (features, anti-leakage, qué se
midió y se descartó) está en [README.md](README.md).

**Índice**

1. [Los 3 comandos que importan](#1-los-3-comandos-que-importan)
2. [Instalar desde cero](#2-instalar-desde-cero)
3. [Alimentar la base de datos](#3-alimentar-la-base-de-datos-con-datos-actuales)
4. [Bajar cuotas de Betano](#4-usar-el-scraper-de-cuotas-de-betano)
5. [Qué poner en el CSV](#5-qué-poner-en-el-csv)
6. [Predecir la cartelera](#6-predecir-la-cartelera)
7. [Comprobar que el modelo sigue funcionando](#7-comprobar-que-el-modelo-sigue-funcionando)
8. [Referencia de comandos y flags](#8-referencia-de-comandos-y-flags)
9. [Ajustes en `config.py`](#9-ajustes-en-configpy)
10. [Mapa de archivos](#10-mapa-de-archivos-qué-genera-cada-cosa)
11. [Calendario de mantenimiento](#11-calendario-de-mantenimiento)
12. [Glosario](#12-glosario-de-los-números-que-vas-a-ver)
13. [Mercados que este sistema NO cubre](#13-mercados-que-este-sistema-no-cubre)
14. [Expectativas realistas](#14-expectativas-realistas)
15. [Las tres reglas de oro](#15-las-tres-reglas-de-oro)
16. [Si algo falla](#16-si-algo-falla)
17. [La interfaz web](#17-la-interfaz-web)
18. [El simulador de parlay](#18-el-simulador-de-parlay)

---

## 1. Los 3 comandos que importan

| Quiero… | Comando | Cada cuánto |
|---|---|---|
| Bajar las cuotas de una cartelera | `python -m src.betano_scraper "UFC 330"` | antes de cada evento |
| Predecir una cartelera | `python -m src.card cards\mi_evento.csv` | antes de cada evento |
| Datos frescos + reentrenar | `scripts\actualizar_bd.bat` | 1 vez al mes |

Los `.bat` viven en `scripts\` y son doble clic si prefieres no escribir
comandos: cada uno se cambia solo a la raíz del proyecto antes de correr nada.

**O todo desde la interfaz web**, que hace lo mismo sin escribir nada:

```bash
scripts\lanzar_ui.bat
```

Para probar el gráfico «Mercado en vivo» con cuotas inventadas, abre
`scripts\simular_en_vivo.bat` con doble clic; instrucciones en
`scripts\simular_en_vivo.txt`.

Ver la [sección 17](#17-la-interfaz-web).

---

## 2. Instalar desde cero

Solo la primera vez, o si cambias de PC.

### Requisitos

| | |
|---|---|
| **Python** | 3.10 o superior (probado en 3.14) |
| **Espacio en disco** | ~60 MB de datos + ~4 MB de modelos |
| **Internet** | sí, para todos los scrapers |
| **Credenciales de Kaggle** | sí, un archivo `kaggle.json` (ver abajo) |
| **Navegador / Selenium** | **no**, ningún scraper lo necesita |
| **GPU** | no |

### Paso 1 — dependencias

```bash
pip install -r requirements.txt
```

### Paso 2 — credenciales de Kaggle

Es el único dato que pide login. En kaggle.com → *Account* → *Create New API
Token*: baja un `kaggle.json` y déjalo en `C:\Users\<tu-usuario>\.kaggle\kaggle.json`.

Si no lo haces, `python -m src.scraper` falla con un mensaje explicando esto
mismo. Alternativa manual: descargar el CSV del dataset y dejarlo en
`data\raw\kaggle_ufc.csv`.

### Paso 3 — construir la base (~1 hora la primera vez)

```bash
python -m src.ufcstats_events      # resultados históricos (~2 min)
python -m src.ufcstats_fighters    # biometría: altura, alcance, DOB (~3 min)
python -m src.ufcstats_fightstats  # stats por pelea (~20 min, reanudable)
python -m src.reemplazos           # reemplazos de Wikipedia (~25 min)
python -m src.bfo_odds             # cuotas recientes que Kaggle no tiene (~12 min)
python -m src.scraper              # dataset Kaggle + features + ELO
python -m modelado.train_model              # entrena los dos modelos
```

Los tres primeros los hace `scripts\bajar_datos_ufcstats.bat` con doble clic.

**Todo es reanudable.** Si se corta a mitad (Ctrl+C, se cae internet), vuelve a
correr el mismo comando: retoma donde quedó gracias a los cachés en `data\raw\`.

### Paso 4 — generar los modelos de apuestas (una sola vez)

```bash
python -m modelado.backtest_valor
python -m modelado.backtest_metodo
```

Producen `models\calibrador_mercado.pkl`, `models\calibrador_metodo.pkl` y
`models\metodo6_xgb.pkl`. Sin ellos, `card.py` predice igual pero **no** calcula
valor ni recomienda apuestas (avisa con "falta el calibrador").

### Paso 5 — cortesía opcional

Si vas a scrapear Wikipedia en volumen, pon tu contacto:

```bash
set WIKI_CONTACT=https://github.com/tu-usuario
```

---

## 3. Alimentar la base de datos con datos actuales

El proyecto usa **seis fuentes**, y conviene entender la diferencia porque una va
atrasada a propósito:

| Fuente | Qué aporta | ¿Al día? |
|---|---|---|
| **UFCStats** (scraper propio) | resultados, control/grappling, fichas, historial de rivales | sí, el mismo día del evento |
| **Kaggle** (`mdabbert`) | base de entrenamiento, con cuotas históricas | va ~4 meses atrás |
| **BestFightOdds** | rellena las cuotas que a Kaggle le faltan | sí |
| **Wikipedia** | quién entró de reemplazo (corto aviso) | sí |
| **Sherdog** | historial FUERA de UFC, solo al predecir debutantes | sí |
| **Betano** | cuotas de la cartelera que viene | sí |

### 3.1 Actualización normal (lo que harás casi siempre)

```bash
scripts\actualizar_bd.bat
```

Seis pasos: resultados de UFCStats → fichas de los que debutaron → estadísticas
de las peleas nuevas → reemplazos de Wikipedia → versión nueva de Kaggle y
reconstrucción de features/ELO → reentrenar los modelos. Unos minutos, porque
todos son incrementales y una corrida típica consulta **1 o 2 eventos**, no
los 780.

Si Kaggle no se puede bajar (falta `kaggle.json` o no hay internet), el paso 5
avisa y **sigue con la copia que ya tienes**. Antes el `.bat` borraba esa copia
primero, y una descarga fallida dejaba la base sin cuotas históricas.

Al final imprime las métricas. **Míralas, son tu control de calidad:**

```
=== GANADOR ===
  Accuracy : 0.665     <- normal: 0.64-0.67
  AUC-ROC  : 0.714     <- normal: 0.70-0.72
  Brier    : 0.217     <- normal: 0.21-0.23

=== MÉTODO ===
  Log loss : 0.950
  Log loss de la tasa base (a batir): 1.008   <- el de arriba DEBE ser menor
```

Dos alarmas que no hay que ignorar:

- **Si el AUC pasa de 0.85**, no celebres: volvió un *data leakage* (el modelo
  está viendo el futuro). Ya pasó una vez y daba 0.93.
- **Si el log loss del método supera al de la tasa base**, el modelo de método
  quedó peor que no tener modelo. Así estaba antes de julio 2026.

### 3.2 Actualización profunda de UFCStats (ocasional)

```bash
scripts\bajar_datos_ufcstats.bat
```

Rebaja **todo** el historial de estadísticas por pelea (golpes, derribos,
control, y el desglose asalto por asalto). ~20-25 min la primera vez. Se puede
cortar con Ctrl+C: al volver a correrlo retoma donde quedó.

Córrelo si es la primera instalación, si pasaron varios meses, o si notas que
faltan peleadores nuevos.

### 3.3 Refrescar cuotas históricas recientes

El dataset de Kaggle va ~4 meses atrás. Para tapar ese hueco:

```bash
python -m src.bfo_odds            # baja las cuotas que faltan
python -m src.bfo_odds --revisar  # solo reporta cuánto del hueco está cubierto
```

**Ojo: hoy ningún script lee estas cuotas.** Los backtests usan las de Kaggle, y
meter las filas del hueco al entrenamiento se midió y no mejora el AUC en ningún
período (ver README, "Ideas de modelado probadas y revertidas"). Sirven para saber
cuánto del hueco se podría cubrir si algún día se integran. No hace falta correrlo
antes de los backtests.

### 3.4 Refrescar la ficha de un peleador puntual

Las fichas se cachean para no re-scrapear en cada corrida. Si alguien acaba de
pelear y quieres su ficha al día:

```bash
del data\raw\ufcstats_cache.json
```

Se vuelve a llenar sola en la siguiente corrida (esa vez va más lenta).

---

## 4. Usar el scraper de cuotas de Betano

Baja las cuotas reales y arma el CSV solo, con el formato correcto.

### Paso 1 — ver qué carteleras hay

```bash
python -m src.betano_scraper
```

```
Carteleras de MMA disponibles ahora mismo en Betano:

  - UFC 330 - Makhachev vs Machado Garry
  - UFC Fight Night
  - Encuentros
```

### Paso 2 — bajar una

Basta parte del nombre, sin importar acentos ni mayúsculas:

```bash
python -m src.betano_scraper "UFC 330"
```

Queda en `cards\betano_ufc_330___makhachev_vs_machado_garry.csv`. Para elegir el
nombre del archivo:

```bash
python -m src.betano_scraper "UFC 330" cards\mi_evento.csv
```

### Qué esperar

```
[i] 22 peleas encontradas, pidiendo cuotas de cada una...
[i] Amanda Lemos vs Alexia Thainara: sin mercado de método activado
[ok] cards\betano_ufc_fight_night.csv  (22/22 con cuota Ganador, 14/22 con método)
```

**Que falten cuotas de método es normal, no es un fallo.** Betano activa los
mercados por partes y además tiene dos formatos:

| Lo que ofrece Betano | Qué llena en el CSV |
|---|---|
| Método **7-way** (KO, sumisión y decisión separados) | las 6 columnas |
| Método **5-way** (KO+sumisión juntos) | solo decisión; ko/sub quedan **vacías** |
| Solo "Ganador" | las 6 de método quedan **vacías** |

En el 5-way no existe un número real de "solo KO" ni "solo sumisión", así que
esas celdas quedan vacías a propósito en vez de inventarse un valor.

### Lo único que completas a mano

La columna **`segment`** queda vacía: Betano no publica si es estelar, co-estelar
o preliminar, ni la categoría de peso. Es solo una etiqueta para que tú te ubiques
en el reporte — **el modelo no la usa**, así que puedes dejarla vacía.

---

## 5. Qué poner en el CSV

Los CSV van en `cards\`.

### Lo mínimo que funciona

```csv
fighter_a,fighter_b,segment
Islam Makhachev,Ian Machado Garry,Estelar
Mackenzie Dern,Gillian Robertson,Co-estelar
```

Con eso predice ganador y método. Sin cuotas no hay recomendación de apuesta.

### Con cuotas de ganador (activa el análisis de valor)

```csv
fighter_a,fighter_b,segment,odds_a,odds_b
Islam Makhachev,Ian Machado Garry,Estelar,1.33,3.15
```

### Completo, con el mercado de método

```csv
fighter_a,fighter_b,segment,odds_a,odds_b,odds_a_ko,odds_a_sub,odds_a_dec,odds_b_ko,odds_b_sub,odds_b_dec
Islam Makhachev,Ian Machado Garry,Estelar,1.33,3.15,4.50,2.70,5.50,9.00,6.00,13.00
```

### Las columnas, una por una

| Columna | ¿Obligatoria? | Qué es |
|---|---|---|
| `fighter_a`, `fighter_b` | **sí** | nombre del peleador |
| `segment` | no | etiqueta tuya (Estelar / Prelim / lo que sea) |
| `odds_a`, `odds_b` | no | cuota de que gane cada uno |
| `odds_a_ko` / `odds_a_sub` / `odds_a_dec` | no | que **A** gane por KO / sumisión / decisión |
| `odds_b_ko` / `odds_b_sub` / `odds_b_dec` | no | ídem para **B** |
| `corto_a`, `corto_b` | no | `1` si ese peleador entró de reemplazo, `0` si no |

**`corto_a`/`corto_b` es la única columna que conviene poner a mano**: el sistema
ya busca los reemplazos en Wikipedia, pero un cambio anunciado hoy todavía no está
publicado. Marcarlo a mano tiene prioridad sobre el caché, y una celda que
dejes vacía se lee como "no lo sé": para ese peleador se consulta el caché.

**Cuatro reglas que evitan problemas:**

1. **Nombres**: escríbelos completos como en UFCStats. Si uno no aparece,
   compruébalo con `python -m src.ufcstats "Garry"`. Ojo con apellidos
   compuestos — Ian Garry está registrado como *Ian Machado Garry* — pero el
   buscador ya lo resuelve solo.

2. **Formato de cuota**: sirve decimal (`1.75`, el de las casas chilenas) o
   americano (`-133`, `+110`). Lo detecta solo y puedes mezclarlos.

3. **Celdas vacías**: están bien. Lo que falte simplemente no se analiza. Es
   mejor una celda vacía que un número inventado.

4. **No inventes cuotas de método.** Si pones números "a ojo" te va a avisar y
   bloquear las apuestas:

   ```
   [!] CUOTAS DE MÉTODO SOSPECHOSAS en 9 de 9 peleas (suman 1.05-1.16).
       Un mercado de método real suma 1.20-1.24.
   ```

   No es capricho: el valor esperado se calcula con el pago de la cuota, así que
   cuotas demasiado generosas producen "valor" falso en toda la cartelera.

---

## 6. Predecir la cartelera

```bash
python -m src.card cards\mi_evento.csv
```

Salida corta y accionable. Para el detalle largo (modelo vs mercado pelea por
pelea, mercado de método completo y **las últimas 5 peleas de cada peleador**):

```bash
python -m src.card cards\mi_evento.csv --detalle
```

### Leer la tabla principal

```
PELEA                    GANADOR              P%   MÉTODO       FIN%  TENDENCIA
Makhachev vs Garry       Islam Makhachev     74.9  Dec 52%       48%  pelea promedio
Luque vs Gore            Vicente Luque       61.2  KO/TKO 44%    64%  KO x1.4 vs base
```

- **MÉTODO** es el desenlace más probable. Casi siempre dirá `Dec`, porque el 51%
  de las peleas de verdad van a tarjetas. Eso no es el modelo rindiéndose.
- **TENDENCIA** es lo que distingue a esa pelea de una promedio. `KO x1.4 vs base`
  = 1,4 veces más propensa al KO que una pelea normal.

### Las cuatro tablas

| Tabla | Qué muestra | Cuándo aparece |
|---|---|---|
| 1. **MODELO SOLO** | el modelo sin cuotas y con el flag de corto aviso en 0 | siempre |
| 2. **MERCADO** | la casa, con la comisión quitada | si el CSV trae cuotas |
| 3. **MODELO + CORTO AVISO** | igual que la 1 pero con el flag activado | solo si hay reemplazos |
| 4. **TODO JUNTO** | modelo + mercado (+ corto aviso) — **la que manda** | si el CSV trae cuotas |

Están separadas a propósito. Cuando iban mezcladas, un pick donde el modelo iba
tibio (56%) y la casa muy convencida (75%) aparecía como "fuerte 79%" y se leía
como si el sistema estuviera seguro de algo que en realidad decía la casa.

La tabla 3 tiene una columna CAMBIO que aísla exactamente cuánto movió el dato de
reemplazo, y avisa si el pick se dio vuelta.

### Leer el bloque RESUMEN

Es lo que de verdad importa, y va primero: qué apostar, luego los avisos, luego
una línea por pelea.

| Confianza | Probabilidad | Acierto real medido |
|---|---|---|
| `fuerte` | ≥75% | ~85% |
| `buena` | 65-75% | ~73% |
| `justa` | 60-65% | ~70% |
| `moneda` | <60% | ~50% — ignórala |
| `NO FIABLE` | — | falta data de un peleador |

**Regla práctica: apostar solo desde 65%.**

Las apuestas salen ordenadas por **cuánto las respalda el backtest**, no por EV:

1. **decisión en el mercado de método** → probado (+15,4% ROI, t=3,0)
2. **ganador (moneyline)** → empate técnico (t=0,3)
3. finalización en método → ruido (t=0,5), no se recomienda

Un +40% de EV en una finalización es **peor apuesta** que un +5% en una decisión:
el primero no sobrevive al test estadístico.

Las peleas `NO FIABLE` **no generan apuesta** aunque el EV se vea rico: salen
aparte como "DESCARTADAS por falta de datos".

También avisa si la exposición total supera el **15% del bankroll**: Kelly asume
que las apuestas son independientes, y las peleas de una misma noche no lo son.

### Reportes visuales

Cada pelea genera un HTML en `outputs\<nombre_del_csv>\` con el donut de victoria
y las barras de método. Doble clic para abrirlos.

---

### Repetir una pelea que ya pasó

En la interfaz, pestaña **Cargar → Peleas anteriores**: busca por peleador o por evento
y elige la pelea. Se carga su cartelera completa con los datos que había **antes** de esa
fecha y la pelea elegida se abre sola. Lo mismo hace **Repetir** en una cartelera
guardada de Betano cuya fecha ya pasó.

Qué se recorta a la fecha: estadísticas, récord y racha (recalculados pelea a pelea),
edad, ELO, rivales recientes, corto aviso y el modelo, que se reentrena solo con las
peleas anteriores si el de producción ya las había visto (tarda ~30 s la primera vez por
fecha y queda en `models\corte\`). Lo que no: los dos calibradores (dos números cada
uno) y los hiperparámetros. El resultado real se lee **después** de predecir y solo se
muestra.

La lista llega hasta la última pelea de `data\processed\ufcstats_fights.csv`. Para
una cartelera más nueva, corre **Actualizar todo** o usa **Repetir** sobre el CSV de
Betano: se predice igual y avisa que el resultado todavía no está en la base.

Después del pronóstico, cada pelea dice cómo terminó con dos veredictos separados:
**Acertó / Falló** (el ganador) y **Acertó el método / Falló el método** (si terminó
como el modelo veía más probable: KO/TKO, sumisión o decisión). Los dos aparecen en el
encabezado del combate, en el zócalo del resultado y en el marcador de la noche. Un
empate o un "sin resultado" no cuentan para ninguno de los dos.

Desde la consola, `card.predict_card(ruta, corte="AAAA-MM-DD")` hace lo mismo.

## 7. Comprobar que el modelo sigue funcionando

```bash
python -m modelado.backtest_carteleras 4
```

Prueba las últimas 4 carteleras reales reconstruyendo cada peleador **tal como
estaba el día del evento** (sin ver el futuro). Para una cartelera puntual:

```bash
python -m modelado.backtest_carteleras --evento Ankalaev
```

**Cuidado al interpretarlo**: este backtest tiene mucho ruido. Diferencias de
menos de 4 peleas entre dos corridas son ruido de semilla, no una mejora ni un
empeoramiento. Y las carteleras encabezadas por un campeón son un subconjunto
fácil (peleadores con mucha data): ahí el sistema da ~80%, pero el número honesto
global sigue siendo 65-69%.

| Comando | Para qué |
|---|---|
| `python -m modelado.evaluar_modelo` | acierto fuera de muestra y calibración por umbral de confianza |
| `python -m src.oposicion "Ilia Topuria"` | últimas 5 peleas: rivales, nivel y método |
| `python -m src.ufcstats "Nombre"` | ficha cruda de un peleador |
| `python -m src.reemplazos --revisar` | tasa de victoria de los reemplazos |
| `python -m src.bfo_odds --revisar` | cobertura de cuotas del hueco de Kaggle |

---

## 8. Referencia de comandos y flags

Todo lo que acepta cada script. Los `[]` son opcionales.

### Predecir

| Comando | Qué hace |
|---|---|
| `python -m src.card [csv] [--detalle]` | predice una cartelera. Sin CSV usa la de por defecto. `--detalle` agrega las últimas 5 peleas de cada peleador y el mercado de método completo |
| `python -m src.betano_scraper` | lista las carteleras disponibles |
| `python -m src.betano_scraper "<nombre>" [salida.csv]` | baja las cuotas de una |
| `python -m src.oposicion "<nombre>"` | ficha de calidad de oposición de un peleador |
| `python -m src.ufcstats "<nombre>"` | ficha cruda de UFCStats |

### Datos

| Comando | Qué hace |
|---|---|
| `python -m src.ufcstats_events [--limit N] [--todo]` | eventos y resultados. `--todo` borra el caché y rebaja todo (por si cambian los selectores del sitio) |
| `python -m src.ufcstats_fighters` | biometría (altura, alcance, DOB, stance) |
| `python -m src.ufcstats_fightstats [--limit N]` | stats por pelea, incluido el desglose por asalto |
| `python -m src.reemplazos [N] [--refrescar] [--revisar]` | reemplazos de Wikipedia. `N` limita a N eventos, `--refrescar` re-consulta lo cacheado, `--revisar` solo reporta |
| `python -m src.bfo_odds [N] [--revisar]` | cuotas de BestFightOdds para el hueco de Kaggle |
| `python -m src.scraper` | descarga el dataset de Kaggle y reconstruye features + ELO |

`--limit N` sirve para probar que un scraper funciona sin esperar 20 minutos.

### Entrenar y validar

Los cinco viven en `modelado\` y se llaman **con `-m`, parados en la raíz del
proyecto**. Con la ruta suelta (`python modelado\train_model.py`) fallan: Python
buscaría `config.py` dentro de `modelado\`, y ese archivo está en la raíz.

| Comando | Qué hace |
|---|---|
| `python -m modelado.train_model` | entrena ganador + método e imprime las métricas |
| `python -m modelado.backtest_carteleras [N] [--cuotas] [--evento <nombre>]` | valida contra N carteleras reales. `--cuotas` compara modelo/mercado/mezcla |
| `python -m modelado.backtest_valor [--desde AAAA] [--refit]` | walk-forward del mercado de ganador |
| `python -m modelado.backtest_metodo [--desde AAAA] [--refit]` | walk-forward del mercado de método |
| `python -m modelado.evaluar_modelo` | acierto fuera de muestra y calibración por tramo de confianza |

**Sobre `--refit`**: los backtests de valor cachean sus 11 reentrenamientos en
`data\processed\walkforward_*.csv`, así que probar umbrales nuevos es instantáneo.
`--refit` fuerza el recálculo (~2 min) y es lo que hay que usar **después de
reentrenar el modelo**, o estarás midiendo el modelo viejo.

**Sobre `--cuotas` en `backtest_carteleras`**: las carteleras más recientes no
sirven para eso, porque las cuotas históricas llegan hasta donde llega Kaggle. El
flag filtra automáticamente a las últimas con cobertura.

---

## 9. Ajustes en `config.py`

Los únicos números que tiene sentido tocar. Todos están ahí para que no haya
constantes escondidas en el código.

| Constante | Por defecto | Qué pasa si la cambias |
|---|---|---|
| `TRAIN_WINDOW_YEARS` | `5` | años de historial que usa para entrenar. `None` = todo. Validado en 5 períodos: 5 años le gana a todo el historial en 4 de 5 |
| `N_SIMULATIONS` | `10_000` | simulaciones de Monte Carlo. Bajarlo acelera, ensancha el intervalo |
| `TRAIN_END_DATE` / `TEST_START_DATE` | 2024-12-31 / 2025-01-01 | el corte temporal del split. Moverlo cambia todas las métricas que reporta `modelado/train_model.py` |
| `REQUEST_DELAY_SEC` | `1.5` | pausa entre requests. **Bajarlo es maleducado y te puede ganar un bloqueo** |
| `ELO_K` | `32.0` | sensibilidad del ELO por pelea |
| `RANDOM_STATE` | `42` | semilla. Cambiarla mueve la accuracy ±0,008 sin que nada haya mejorado |
| `METHOD_BASE_RATES` | KO 30,8% / Sub 17,7% / Dec 51,5% | las tasas base contra las que se lee el LIFT del método. Solo tocar si reentrenas con otro período |

**Regla**: si tocas `TRAIN_WINDOW_YEARS` o `TRAIN_END_DATE`, tienes que correr
`modelado/train_model.py` **y** los dos backtests con `--refit`.

---

## 10. Mapa de archivos (qué genera cada cosa)

Nada de esto se versiona: todo se regenera con los comandos de arriba.

### `data\raw\` — cachés crudos, se borran sin miedo

| Archivo | Lo llena | Si lo borras |
|---|---|---|
| `ufcstats_events.json` | `ufcstats_events` | rebaja el historial de eventos (~2 min) |
| `ufcstats_fighters.json` | `ufcstats_fighters` | rebaja la biometría (~3 min) |
| `ufcstats_fightstats.json` | `ufcstats_fightstats` | rebaja las stats por pelea (~20 min) |
| `ufcstats_cache.json` | `card.py` al predecir | **este es el que quieres borrar** para refrescar fichas |
| `sherdog_cache.json` | `card.py` al predecir debutantes | se vuelve a llenar solo |
| `reemplazos_wiki.json` | `reemplazos` | rebaja Wikipedia (~25 min) |
| `bfo_odds.json` | `bfo_odds` | rebaja las cuotas del hueco (~12 min) |
| `kaggle_ufc.csv` | `scraper` | se re-descarga de Kaggle |

### `data\processed\` — lo que consume el modelo

| Archivo | Qué es |
|---|---|
| `features.csv` | el dataset diferencial listo para entrenar |
| `fights.csv` / `ufcstats_fights.csv` | 1 fila por pelea histórica |
| `fighters.csv` / `ufcstats_bio.csv` | 1 fila por peleador |
| `elo_ratings.csv` | el ELO por categoría de peso |
| `defense_stats.csv` | defensa de golpeo y de derribo (dataset de Rajeev Warrier) |
| `walkforward_valor.csv` | caché del backtest de moneyline |
| `walkforward_metodo.csv` | caché del backtest de método |
| `resultados_recientes.json` | caché de la sección **Resultados de las últimas 3 carteleras** de Inicio. Se rehace sola si cambia la base o el modelo; borrarla solo obliga a recalcularla |

### `models\`

| Archivo | Lo produce |
|---|---|
| `winner_xgb.pkl` | `modelado/train_model.py` |
| `method_xgb.pkl` | `modelado/train_model.py` |
| `winner_xgb_split.pkl` | `modelado/train_model.py` (solo para medir: entrenado hasta 2024, lo lee `modelado/evaluar_modelo.py`) |
| `metodo6_xgb.pkl` | `modelado/backtest_metodo.py` |
| `calibrador_mercado.pkl` | `modelado/backtest_valor.py` |
| `calibrador_metodo.pkl` | `modelado/backtest_metodo.py` |
| `corte\AAAA-MM-DD.pkl` | la repetición, cuando el modelo de producción ya había visto esa fecha (uno por fecha; se invalida al cambiar `features.csv`) |

### `outputs\<nombre_del_csv>\`

Un HTML por pelea. Se pueden borrar en cualquier momento.

---

## 11. Calendario de mantenimiento

| Cuándo | Qué correr | Por qué |
|---|---|---|
| **Antes de cada cartelera** | `python -m src.betano_scraper "<evento>"` | cuotas frescas = +3 puntos de acierto |
| | `del data\raw\ufcstats_cache.json` | para que las fichas incluyan la última pelea de cada uno |
| | `python -m src.card cards\<csv>` | el pronóstico |
| **1 vez al mes** | `scripts\actualizar_bd.bat` | mete los eventos nuevos y reentrena |
| **Cada 2-3 meses** | `python -m src.bfo_odds` | cuotas históricas nuevas |
| | `python -m modelado.backtest_valor --refit` | reajusta el calibrador con datos nuevos |
| | `python -m modelado.backtest_metodo --refit` | ídem para el mercado de método |
| **Cada 6 meses** | `scripts\bajar_datos_ufcstats.bat` | por si algún evento viejo quedó incompleto |
| **Si algo se ve raro** | `python -m src.ufcstats_events --todo` | rebaja todo, por si cambiaron los selectores del sitio |

**Qué mirar después de cada `scripts\actualizar_bd.bat`**: las 4 métricas de la sección
3.1. Si el AUC salta a 0,85+, hay leakage. Si el log loss del método supera a la
tasa base, el modelo de método se rompió.

---

## 12. Glosario (de los números que vas a ver)

| Término | Qué mide | Cómo leerlo |
|---|---|---|
| **Accuracy** | % de peleas donde acertó el ganador | 0,66 = acierta 2 de cada 3. Engaña: no distingue "70% seguro" de "51% seguro" |
| **AUC-ROC** | capacidad de **ordenar** — ¿le da más probabilidad al que ganó? | 0,50 = azar, 0,71 = lo normal aquí, **0,85+ = leakage** |
| **Brier** | **calibración** — ¿un "70%" gana de verdad el 70% de las veces? | más bajo = mejor. 0,21-0,23 es lo normal. **Es la métrica que importa si vas a apostar** |
| **Log loss** | como el Brier pero castiga más equivocarse con seguridad | solo tiene sentido comparado contra un baseline |
| **Tasa base** | cantar siempre la frecuencia histórica sin mirar la pelea | el baseline a batir. Si el modelo no le gana, el modelo no sirve |
| **ELO** | nivel del peleador, ajustado pelea a pelea | 1500 = debutante. Aquí es **graduado**: una decisión dividida suma menos que un KO |
| **Lift** | cuántas veces más probable que la pelea promedio | `KO x1,4` = 40% más propensa al KO que una pelea normal |
| **EV** | valor esperado de la apuesta, en % de lo apostado | +5% = ganas 5 centavos por peso a la larga. **Solo vale si la cuota es real** |
| **Kelly** | qué fracción del bankroll apostar | aquí va a **1/4 de Kelly con tope 5%**, porque Kelly puro sobreapuesta cuando la `p` tiene error |
| **`t`** | cuántos errores estándar está el ROI de cero | **`t` < 2 = suerte**, por lindo que se vea el ROI |
| **Sobrerredondeo** | cuánto suman las probabilidades implícitas de un mercado | 1,00 = sin comisión (imposible). Moneyline real ~1,04, método real 1,20-1,24. **Menos de 1,18 en método = cuotas sospechosas** |

---

## 13. Mercados que este sistema NO cubre

Para que no pierdas tiempo buscando algo que no está.

| Mercado | Estado |
|---|---|
| **Ganador (moneyline)** | cubierto, pero es empate técnico con la casa |
| **Método (KO/Sub/Dec)** | cubierto, y es la única ventaja probada |
| **Total de golpes over/under** | **no**. Se puede predecir (AUC 0,65) pero no hay ni una cuota histórica para validar rentabilidad. Además Betano no lo ofrece: es de bet365 |
| **Round exacto / total de rounds** | **no**. Mismo problema: cero cuotas históricas |
| **"¿Llega a tarjetas?"** | medido y **descartado**: el mercado infravalora el "sí" en 6 puntos reales, pero dutchear las dos patas de decisión cuesta 10 puntos de comisión → ROI −6,1%. Un mercado dedicado de 2 vías cobraría ~5%, y ahí sí saldría — pero no hay datos históricos para probarlo |
| **Peleas de otras ligas** (Bellator, PFL, ONE) | **no**. El ELO y las features se construyen sobre datos de UFC |

Si en algún momento quieres atacar los mercados de golpes o rounds, el camino
honesto es **empezar a registrar esas cuotas ahora** y validar en unos meses, no
apostar por el álgebra.

---

## 14. Expectativas realistas

Números medidos, no promesas:

- El modelo acierta **65-69%** de las peleas. Sobre picks de confianza ≥75% sube
  a ~85%, pero esas son pocas por cartelera.
- El **mercado acierta 69%**, o sea más que el modelo solo. Por eso cuando le
  pasas cuotas el sistema mezcla los dos (llega a ~70%).
- **Apostar al ganador es un empate técnico con la casa** (+1,0% de ROI, margen
  de error ±7,5). La única ventaja que aguantó el test estadístico es apostar
  **decisiones en el mercado de método** (+15,4%, t=3,0).
- El mercado de método cobra 22% de comisión: es recreativo, con límites bajos, y
  las casas cierran cuentas ganadoras. El ROI no te dice cuánto volumen te aceptan.
- Que una cartelera no genere ninguna apuesta es el resultado normal y esperado.

---

## 15. Las tres reglas de oro

1. **Si un backtest da un número espectacular, el bug está en los datos.** El de
   método daba +63% hasta que se descubrió que las cuotas de 2025 sumaban menos
   de 1. Prueba barata: apostar a todas las opciones a la vez debe dar ≈ −comisión.
2. **`t` menor a 2 = suerte**, por lindo que se vea el ROI.
3. **`NO FIABLE`** significa que a un peleador le faltan datos. No apuestes ahí, y
   desconfía del pronóstico.

---

## 16. Si algo falla

| Síntoma | Qué hacer |
|---|---|
| "falta el calibrador" | `python -m modelado.backtest_valor` |
| "cuotas imposibles (suman 0.9x)" | Guarda anti-datos-malos. Revisa las 6 cuotas. |
| "CUOTAS DE MÉTODO SOSPECHOSAS" | Tus cuotas son más generosas que las de una casa real. Bájalas de Betano en vez de escribirlas a mano. |
| "N homónimos, elegido el de ficha más completa" | Normal. Hay peleadores con el mismo nombre; elige el que tiene carrera. |
| Peleador no encontrado | Debutante sin ficha en UFCStats. Se omite, no se inventa. |
| Stats viejos | `del data\raw\ufcstats_cache.json` y vuelve a correr. |
| Predicciones raras tras actualizar | `python -m modelado.train_model` para reentrenar. |
| El scraper de Betano no encuentra la cartelera | Corre `python -m src.betano_scraper` sin argumentos para ver los nombres exactos disponibles. |
| **Todas las selecciones salen "sin ventaja clara"** | No es un fallo. Significa que Betano todavía no abrió el mercado de método para esa cartelera y solo publica "Ganador", que es justo el mercado donde no hay ventaja demostrada. Los mercados de método se abren en los días previos al evento: refresca más cerca de la fecha. La UI ya lo avisa arriba de la cartelera. |
| El CSV bajado no trae ninguna columna `odds_*_ko` ni `odds_*_fin` | Lo mismo de arriba: esos mercados no estaban activados al momento de bajarlo. Para comprobarlo, `python -m src.betano_scraper` y revisa si la pelea lista más de un mercado. |
| `feature_names mismatch` al predecir | El modelo se entrenó con otra lista de columnas. Corre `python -m modelado.train_model`. |
| "No se pudo cargar desde Kaggle" | Falta `~/.kaggle/kaggle.json` (sección 2, paso 2). |
| Wikipedia contesta 403 | Falta el User-Agent propio: `set WIKI_CONTACT=https://github.com/tu-usuario` |
| `UnicodeEncodeError` con nombres como Błachowicz | No debería pasar (`config.py` fuerza UTF-8 tolerante). Si pasa, corre `chcp 65001` antes. |
| El scraper se cortó a la mitad | Vuelve a correr el mismo comando: todos retoman donde quedaron. |
| El backtest de valor da lo mismo tras reentrenar | Te falta `--refit`: está usando el caché del modelo viejo. |
| `backtest_carteleras` da 2 peleas menos que ayer | Ruido de semilla. Menos de 4 peleas de diferencia no significa nada. |
| `modelado/evaluar_modelo.py` dice que falta `winner_xgb_split.pkl` | Es el modelo de medición (entrenado solo hasta 2024). Lo deja `python -m modelado.train_model`: córrelo una vez. |
| La UI no abre / "puerto ocupado" | Otro programa usa el 8000. Cierra la otra ventana de `scripts\lanzar_ui.bat` o cambia el puerto en `webui/server.py`. |
| La UI dice "falta el calibrador" | `python -m modelado.backtest_valor`, o el botón "Recalcular el calibrador de ganador". |

---

## 17. La interfaz web

Hace todo lo que hace la consola, sin escribir comandos.

```bash
scripts\lanzar_ui.bat
```

Abre `http://127.0.0.1:8000` en el navegador. **Deja la ventana negra abierta**
mientras la uses: ahí corre el servidor. Ctrl+C para cerrarlo.

Escucha solo en `127.0.0.1`, o sea **solo tu PC**: maneja tu bankroll y no tiene
contraseña, así que no hay motivo para exponerla a la red.

**Sin base de datos**: `python -m webui.server --demo` abre la interfaz con una de las
carteleras ya predichas de `webui/demo/` (`--demo gamrot`, `--demo manual`, `--demo medic`
para elegir). Sirve para ver o modificar la interfaz en un clon recién bajado, sin
construir la base. Son fotos de corridas reales, no se pueden refrescar ni repredecir.

### Las seis pestañas

| Pestaña | Qué hay |
|---|---|
| **Inicio** | Los resultados de las últimas 3 carteleras de tu base, las noticias de UFC, las próximas peleas con cuenta regresiva y los eventos (Predecir / Repetir) |
| **Cartelera** | Resumen de qué apostar + una tarjeta por pelea (o vista de tabla) |
| **Combinada** | El constructor de parlays (sección 18) |
| **Cargar** | Bajar de Betano, elegir una pelea anterior para repetirla, subir un CSV, o repredecir uno de `cards\` |
| **Mantenimiento** | Actualizar BD / reentrenar / backtests, con el registro en vivo |
| **Guía** | Glosario en lenguaje llano: qué es cada etiqueta, cada número y qué NO hace |

El botón de **opciones** (arriba a la derecha) elige el **estilo** —*Transmisión*, la
gráfica de la tele con el octágono, o *Tarjeta del juez*, el acta de la pelea— y el
**tema** claro, oscuro o automático (sigue al sistema). Las dos cosas se recuerdan en
ese navegador.

### Resultados de las últimas 3 carteleras

Arriba de todo en **Inicio**. Toma las tres carteleras más nuevas de tu base local, las
predice **como repeticiones** (solo con lo que se sabía ese día, igual que **Repetir**) y
las compara con cómo terminaron:

- Cada cartelera es una fila plegable. Cerrada muestra una tira de cuadros —verde si
  acertó al ganador, rojo si no, uno por pelea— y dos marcadores: **ganador** y
  **método**. Abierta muestra cada pelea con el pronóstico, el resultado y los dos sellos.
- La primera vez aparecen todas cerradas; después se recuerda cuál dejaste abierta.
- La primera vez tarda: se calculan en segundo plano (la fila dice *Prediciendo con los
  datos de ese día…*) y quedan guardadas en `data\processed\resultados_recientes.json`.
  Si la fecha es anterior al modelo de producción hay que entrenar uno para esa fecha
  (~30 s cada una). Se recalculan solas al actualizar la base o reentrenar.
- Son las tres últimas **de tu base**, no necesariamente las tres últimas de UFC: para
  ver las más nuevas, corre **Actualizar todo** en Mantenimiento.
- **Ver la repetición completa** carga esa cartelera en la pestaña Cartelera.

Una noche no mide un modelo: con 12-14 peleas el margen es de ±13-15 puntos, y la
misma fila lo dice.

### Cada etiqueta se explica sola

Este es el criterio de diseño de la interfaz: **ningún número aparece sin decir
qué significa**.

- El **`?`** al lado de la etiqueta de confianza de cada pelea abre la explicación
  de esa pelea en concreto.
- Las peleas marcadas **NO FIABLE** traen el motivo escrito debajo, con nombre y
  apellido: *"Dulatov tiene 1 pelea en UFC. Fuera de UFC tiene récord 12-1, pero
  de esas peleas no existen estadísticas de golpeo ni de lucha"*.
- En la pestaña **Combinada**, cada selección dice **Conviene / Se puede / No
  conviene** y el porqué, en vez de mostrar solo un porcentaje.
- La pestaña **Guía** tiene el glosario completo: cuota, valor, bankroll, Kelly,
  comisión, las etiquetas de confianza y las de evidencia.

### El refresco de cuotas

Arriba a la derecha hay una cuenta regresiva. **Cada 10 minutos vuelve a bajar
las cuotas de la cartelera activa** y repredice, marcando con ▲▼ las que se
movieron (pasa el mouse por encima para ver el valor anterior).

- **Refrescar** lo hace en el momento.
- **EN VIVO** (aparece con una cartelera de Betano) refresca solo la línea de
  ganador **cada 10 s** con una sola petición, para seguir el evento mientras pasa.
  No repredice: la probabilidad del modelo no cambia porque se mueva la cuota, solo
  la mezcla y el valor. Apágalo cuando dejes de mirar.
- Solo refresca la cartelera **que tienes abierta**, no todo Betano: son ~22
  peticiones con 1,5 s de pausa entre medio. Cada 10 min eso es scraping
  educado; barrer el sitio entero no lo sería.
- Si cargaste desde un CSV en vez de Betano, no hay nada que refrescar: el
  auto-refresh solo aplica al origen Betano.

### Mantenimiento

Cada tarea explica qué hace y cuánto tarda, y el log sale en vivo abajo. **Solo
corre una a la vez**, a propósito: casi todas escriben en `data\processed\` y dos
en paralelo se pisarían los archivos.

Los chips de arriba dicen qué modelos tienes y cuáles faltan. Si alguno sale en
rojo, el botón que lo genera está en la misma pantalla.

### Lo que la UI no reemplaza

Sigue siendo la consola el lugar para `--detalle`, `--evento`, `--desde` y los
flags finos de la [sección 8](#8-referencia-de-comandos-y-flags). La UI cubre el
uso diario, no el 100% de las opciones.

---

## 18. El simulador de parlay

Betano acepta hasta **13 patas**. El simulador las arma, calcula la combinada y
—lo importante— dice **si conviene y por qué**.

### Cómo lee cada pata

Cada pata trae una etiqueta de **evidencia**, que no es la confianza del modelo
sino lo que el backtest de este proyecto midió sobre ese mercado:

Cada selección lleva **dos** etiquetas, porque responden preguntas distintas.

**1. Qué tan probable es** — habla del pronóstico, sin mirar el precio:

| Etiqueta | Probabilidad | Acierto real medido |
|---|---|---|
| **segura** | ≥80% | ~85% — o sea que igual falla 1 de cada 7 |
| **buena** | 60-80% | 70-73% |
| **leve** | 55-60% | 55-60% |
| **coinflip** | <55% | ~50%, una moneda al aire |

**2. Si está bien pagada** — habla del precio, no de la pelea:

| Etiqueta | Mercado | Respaldo medido |
|---|---|---|
| **Probado** | decisión en el mercado de método | +15,4% ROI, t=3,0 (1.145 apuestas) |
| **Sin ventaja clara** | ganador (moneyline) | +1,0% ROI ± 7,5, t=0,3 |
| **Ruido** | finalización (KO/sub) en método | t=0,5 — indistinguible de la suerte |

Una selección puede ser **segura y a la vez estar mal pagada**: son ejes
independientes. "Sin ventaja clara" no dice que el peleador vaya a perder, dice
que la casa ya cobró esa información.

### Los dos porcentajes

Debajo de cada selección hay dos números que no son lo mismo:

- **modelo** — lo que estima el modelo por su cuenta, mirando solo a los
  peleadores.
- **con la cuota** — el modelo combinado con la línea de la casa. Es la
  estimación **más certera** de las dos: ~70% de acierto contra ~67%.

Cuando se separan mucho, la casa y el modelo están en desacuerdo. Está medido
que en esos casos **el que suele equivocarse es el modelo** (filtrar por
discrepancia grande da −8,1% de ROI), así que una diferencia enorme es motivo de
desconfianza, no de entusiasmo.

Debajo de cada pata hay una frase que dice SÍ o NO y el motivo. Una pata con
+32% de EV puede decir **NO** si a un peleador le faltan datos o si las cuotas de
método de esa pelea suman menos de 1,18: el EV se calcula con el pago de la
cuota, así que una cuota inflada produce "valor" que no existe.

Por defecto la lista muestra solo *Probado* y *Sin ventaja clara*. El filtro
**Ruido** existe para que veas lo que estás dejando fuera, no para que lo uses.

### Cuotas en vivo (solo en tu PC)

En la cabecera hay un interruptor **EN VIVO**. Con él encendido, la cuota de ganador se
refresca **cada 10 segundos**; apagado, las cuotas se actualizan cada 10 minutos como
siempre.

Funciona porque la página de Betano trae las cuotas de ganador de toda la cartelera de una
vez: es **una petición** por refresco, no una por pelea. Y no vuelve a predecir — solo
recalcula lo que depende de la cuota: la mezcla con el mercado (que es el porcentaje que ves
en la tarjeta, con su ganador y su etiqueta de confianza), el EV, cuánto apostar y la
probabilidad de las selecciones de ganador del simulador de combinada.

| | Completo (10 min) | En vivo (10 s) |
|---|---|---|
| Peticiones a Betano | 1 + una por pelea | **1** |
| Cuotas de ganador | sí | sí |
| Cuotas de método | sí | no |
| Vuelve a correr el modelo | sí | no |

**Apágalo cuando no estés mirando.** Son ~6 peticiones por minuto: sostenido durante horas
es la forma típica de que una casa te bloquee la IP. Por eso arranca apagado y el
interruptor solo aparece si la cartelera vino de Betano — un CSV en disco no cambia solo.

### Las tres secciones

Las selecciones vienen **agrupadas por mercado**, porque en Betano son mercados
distintos, con precios y reglas distintas:

| Sección | Qué es | Comisión |
|---|---|---|
| **Quién gana** | Solo importa quién levanta la mano | ~4% |
| **Cómo gana — 7 vías** | KO/TKO, sumisión y decisión separados por peleador (3×2 + empate) | ~22% |
| **Cómo gana — 5 vías** | Cuando Betano no separa KO de sumisión: solo "finalización" y "decisión" (2×2 + empate) | ~22% |

Las 5 vías no son un mercado peor, son el mismo con menos granularidad — y la
decisión vale exactamente lo mismo en los dos, porque es literalmente la misma
apuesta. Si una sección sale vacía es porque Betano no la abrió para esa
cartelera, no porque falte un dato.

### Reglas que aplica solo

- **Máximo 13 patas**, que es el tope de Betano.
- **Bloquea las EXCLUYENTES y las SIMILARES**, y te dice cuál de las dos es:

  | Caso | Ejemplo | Por qué se bloquea |
  |---|---|---|
  | **Excluyente** | "Gana A" + "Gana B"; "A por KO" + "A por decisión" | No pueden pasar las dos. Ninguna casa acepta la combinada. |
  | **Similar** | "Gana A" + "A por decisión"; "A por finalización" (5 vías) + "A por KO" (7 vías) | Una contiene a la otra. Betano casi no sube la cuota al combinarlas —a veces ni la sube— porque estarías pagando dos veces por la misma información. |

  No está hardcodeado caso por caso: cada selección se traduce al conjunto de
  desenlaces que la hacen ganar (sobre KO/sumisión/decisión de cada peleador).
  Si dos conjuntos no se tocan son excluyentes; si se tocan, similares.

- **"Sugerir"** arma la mejor combinada posible: solo selecciones que el propio
  sistema marca *Conviene* o *Se puede*, una por pelea, hasta 4, y nunca una
  combinada que el evaluador califique de *floja*. Por eso una cartelera con
  solo apuestas al ganador no sugiere nada: ese mercado no tiene ventaja
  probada. Que no sugiera nada es un resultado normal.

### El número que hay que mirar

No es el EV. Es **"cuánto error aguanta por pata"**.

El EV de una combinada de patas independientes es `Π(1+EV_i) − 1`. O sea: 13
patas con +5% de EV cada una dan **+88% de EV combinado**. Eso es cierto, y es
una trampa:

- **Cobras 1 de cada 766 veces.** El +88% es real a larguísimo plazo; tu
  bankroll no llega.
- **El error se multiplica.** Ese parlay de +88% se cae a **cero** si cada
  probabilidad está sobreestimada apenas un **4,8%**. El Brier del modelo es
  0,21: ese error existe, no es teórico.

Por eso el simulador puede decirte *"las patas son buenas, el parlay es frágil"*
aunque las 13 sean del mercado probado. **Las combinadas de 2-4 patas conservan
casi todo el EV por unidad de riesgo y cobran muchísimo más seguido.**

El **stake sugerido** va a ¼ de Kelly con tope 5%, igual que el resto del
sistema. En parlays largos te va a sugerir casi cero — eso no es un error del
cálculo, es la respuesta.
