# Manual de usuario — UFC Predictor

Todo se corre desde la carpeta del proyecto:

```
cd ruta/a/ufc_predictor
```

Detalle del diseño y las fuentes en `README.md`. Esto es el uso diario.

---

## 1. Los 3 comandos que importan

| Quiero… | Comando | Cada cuánto |
|---|---|---|
| Bajar las cuotas de una cartelera | `python -m src.betano_scraper "UFC 330"` | antes de cada evento |
| Predecir una cartelera | `python -m src.card cards\mi_evento.csv` | antes de cada evento |
| Datos frescos + reentrenar | `actualizar_bd.bat` | 1 vez al mes |

Los `.bat` son doble clic si prefieres no escribir comandos.

---

## 2. Alimentar la base de datos con datos actuales

El proyecto usa **dos fuentes**, y conviene entender la diferencia porque una va
atrasada a propósito:

| Fuente | Qué aporta | ¿Al día? |
|---|---|---|
| **UFCStats** (scraper propio) | resultados, control/grappling, fichas, historial de rivales | sí, el mismo día del evento |
| **Kaggle** (`mdabbert`) | base de entrenamiento, con cuotas históricas | va ~4 meses atrás |

### 2.1 Actualización normal (lo que harás casi siempre)

```bash
actualizar_bd.bat
```

Cuatro pasos: borra el dataset viejo → actualiza resultados de UFCStats →
reconstruye features/ELO → reentrena los modelos. Unos minutos.

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

### 2.2 Actualización profunda de UFCStats (ocasional)

```bash
bajar_datos_ufcstats.bat
```

Rebaja **todo** el historial de estadísticas por pelea (golpes, derribos,
control). ~20-25 min la primera vez. Se puede cortar con Ctrl+C: al volver a
correrlo retoma donde quedó.

Córrelo si es la primera instalación, si pasaron varios meses, o si notas que
faltan peleadores nuevos.

### 2.3 Refrescar la ficha de un peleador puntual

Las fichas se cachean para no re-scrapear en cada corrida. Si alguien acaba de
pelear y quieres su ficha al día:

```bash
del data\raw\ufcstats_cache.json
```

Se vuelve a llenar sola en la siguiente corrida (esa vez va más lenta).

---

## 3. Usar el scraper de cuotas de Betano

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

## 4. Qué poner en el CSV

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

## 5. Predecir la cartelera

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

1. **decisión en el mercado de método** → probado (+16,5% ROI, t=3,1)
2. **ganador (moneyline)** → empate técnico (t=0,3)
3. finalización en método → ruido (t=0,5), no se recomienda

Un +40% de EV en una finalización es **peor apuesta** que un +5% en una decisión:
el primero no sobrevive al test estadístico.

Las peleas `NO FIABLE` **no generan apuesta** aunque el EV se vea rico: salen
aparte como "DESCARTADAS por falta de datos".

### Reportes visuales

Cada pelea genera un HTML en `outputs\<nombre_del_csv>\` con el donut de victoria
y las barras de método. Doble clic para abrirlos.

---

## 6. Comprobar que el modelo sigue funcionando

```bash
python backtest_carteleras.py 4
```

Prueba las últimas 4 carteleras reales reconstruyendo cada peleador **tal como
estaba el día del evento** (sin ver el futuro). Para una cartelera puntual:

```bash
python backtest_carteleras.py --evento Ankalaev
```

| Comando | Para qué |
|---|---|
| `python evaluar_modelo.py` | calibración y acierto por umbral de confianza |
| `python -m src.oposicion "Ilia Topuria"` | últimas 5 peleas: rivales, nivel y método |
| `python -m src.ufcstats "Nombre"` | ficha cruda de un peleador |

Para generar los modelos de apuestas (**una sola vez**):

```bash
python backtest_valor.py
python backtest_metodo.py
```

---

## 7. Expectativas realistas

Números medidos, no promesas:

- El modelo acierta **65-69%** de las peleas. Sobre picks de confianza ≥75% sube
  a ~85%, pero esas son pocas por cartelera.
- El **mercado acierta 67%**, o sea más que el modelo solo. Por eso cuando le
  pasas cuotas el sistema mezcla los dos (llega a ~70%).
- **Apostar al ganador es un empate técnico con la casa** (+1,0% de ROI, margen
  de error ±7,5). La única ventaja que aguantó el test estadístico es apostar
  **decisiones en el mercado de método** (+16,5%, t=3,1).
- El mercado de método cobra 22% de comisión: es recreativo, con límites bajos, y
  las casas cierran cuentas ganadoras. El ROI no te dice cuánto volumen te aceptan.
- Que una cartelera no genere ninguna apuesta es el resultado normal y esperado.

---

## 8. Las tres reglas de oro

1. **Si un backtest da un número espectacular, el bug está en los datos.** El de
   método daba +63% hasta que se descubrió que las cuotas de 2025 sumaban menos
   de 1. Prueba barata: apostar a todas las opciones a la vez debe dar ≈ −comisión.
2. **`t` menor a 2 = suerte**, por lindo que se vea el ROI.
3. **`NO FIABLE`** significa que a un peleador le faltan datos. No apuestes ahí, y
   desconfía del pronóstico.

---

## 9. Si algo falla

| Síntoma | Qué hacer |
|---|---|
| "falta el calibrador" | `python backtest_valor.py` |
| "cuotas imposibles (suman 0.9x)" | Guarda anti-datos-malos. Revisa las 6 cuotas. |
| "CUOTAS DE MÉTODO SOSPECHOSAS" | Tus cuotas son más generosas que las de una casa real. Bájalas de Betano en vez de escribirlas a mano. |
| "N homónimos, elegido el de ficha más completa" | Normal. Hay peleadores con el mismo nombre; elige el que tiene carrera. |
| Peleador no encontrado | Debutante sin ficha en UFCStats. Se omite, no se inventa. |
| Stats viejos | `del data\raw\ufcstats_cache.json` y vuelve a correr. |
| Predicciones raras tras actualizar | `python train_model.py` para reentrenar. |
| El scraper de Betano no encuentra la cartelera | Corre `python -m src.betano_scraper` sin argumentos para ver los nombres exactos disponibles. |
