# Traspaso de SQLite — 4 de octubre de 2026

El usuario pidió detener esta parte y entregar los faltantes para otro agente.
Esta sesión revisó SQLite en modo de lectura; no modificó su implementación ni
ejecutó nuevamente entrenamiento, migración o backtests completos.

## Estado que debe preservarse

- Raíz: C:\Users\Juan\Downloads\ufc_predictor.
- Rama actual: codex/completar-mercado-ui, creada desde main.
- main y mejoras-ui-sqlite apuntaban a dad917776d151d9601dd0249b634bbf1788aed4e
  al empezar; el merge de los 19 commits ya estaba registrado. Esta sesión no
  hizo merge, push ni commits. Hay cambios anteriores y nuevos sin commit.
- Respaldo del estado anterior de esta sesión:
  C:\Users\Juan\Downloads\ufc_predictor\backups\bloques_4_5_2026-10-04.
  Incluye cambios-previos.patch y copias del código previo.
- Plan actualizado:
  C:\Users\Juan\Downloads\ufc_predictor\.claude\planes\sqlite-2026-10-04\PLAN_SQLITE.md.
  Sus preguntas Q-D1–Q-D12, Q-E1–Q-E6, Q-O1–Q-O3 y Q-V1–Q-V4 siguen
  documentadas. El usuario autorizó continuar la verificación, pero no eligió
  excepciones adicionales de archivos ni respondió esas decisiones de tablas.
- NO acceder ni tocar
  C:\Users\Juan\Downloads\ufc_predictor\.claude\worktrees\agitated-murdock-ed832a.
- Conservar el worktree del plan original
  C:\Users\Juan\Downloads\ufc_predictor\.claude\worktrees\agent-a593fca2d00b280b4.
- Leer primero CLAUDE.md, PRODUCT.md y DESIGN.md. Código y comentarios en
  español; rutas absolutas; Python exclusivamente con -m desde la raíz.
- No merge ni push sin confirmación explícita. Consultar antes de acciones
  irreversibles. No borrar, mover ni modificar originales de la instalación.

## Faltantes de implementación comprobados

1. Completar el alcance del almacenamiento. src/storage.py:63 acepta solamente
   CSV/JSON de data/raw y data/processed, el índice de fotos y modelos PKL.
   cards/, outputs/, informes, imágenes y demos siguen fuera de ese contrato.
   src/migrate_sqlite.py:21 también omite esas entradas. Revisar sus lectores,
   escritores y endpoints, incluidos webui/server.py:252 y src/card.py:1124.
2. Corregir las excepciones. Actualmente los modelos PKL se guardan como BLOB;
   el usuario quiere que permanezcan como archivos. Solo PNG y PKL están
   autorizados como archivos operativos. JPG/WebP, notas, cards, outputs, HTML,
   webui/demo y tests/fixtures requieren consulta antes de aceptar excepciones.
   docs/sqlite.md describe excepciones heredadas que no deben darse por aprobadas.
3. Añadir la tabla de control de migración por archivo/hash. Actualmente el
   checkpoint histórico solo está en data/originales/manifiesto.json; _resources
   registra el recurso vigente, no el control de cada original migrado.
   La importación confirma su transacción antes de verify(); verificar y publicar
   deben permitir reanudación sin dejar datos no verificados activos.
4. Reparar el arnés antes de ejecutarlo. scripts/validar_sqlite.py copia el código
   actual ya migrado y omite ufc.db: su fase base intentaría leer una base que no
   existe. Hace falta una referencia CSV del mismo código, únicamente en la
   copia de comparación, sin fallback operativo en la entrega final.
5. Aislar el arnés explícitamente. UFC_DB heredado puede apuntar fuera de su WORK,
   tanto durante migración como ejecución. Fijarlo al sandbox y comprobar rutas
   resueltas. Sustituir python -c por módulos y las entradas de cartelera relativas
   por rutas absolutas. No sobrescribir las evidencias anteriores.
6. Regenerar la aceptación completa después de las correcciones: stdout byte a
   byte; mismos archivos y SHA256 de todos los PKL, incluido models/corte;
   tablas importadas y regeneradas con assert_frame_equal(check_exact=True,
   check_dtype=True); HTML quitando solo los UUID de Plotly. Red bloqueada, misma
   entrada y mismo código de negocio, mismo día o repetición explícita. Incluir
   UFC 331 al corte 2026-09-19 y la cartelera Betano 2026-10-03 si están disponibles.
   Registrar hashes del código completo y entradas, dependencias, fecha, comandos
   exactos y códigos de salida, además del commit.

## Lo que ya existe y debe conservarse

La migración heredada copia originales por SHA256, comprueba cambios concurrentes,
normaliza las escrituras calculadas mediante CSV en memoria, restituye dtypes y
ordena por _row_order. Hay checkpoints incrementales de UFCStats. La inspección
estática conserva los delays y una petición Betano por ciclo; faltan mediciones
nuevas de esos contratos antes de declarar el cierre.

La evidencia anterior es real y está en
C:\Users\Juan\Downloads\ufc_predictor\backups\validacion_sqlite:

- origen.json identifica dad917776d151d9601dd0249b634bbf1788aed4e y los comandos.
- comparacion.json registra 10 stdout idénticos, ninguna diferencia SHA256 por
  etapa y 10 tablas exactas.
- Hay stdout, stderr y hashes por etapa en base/ y sqlite/; originales_verificados.json
  registra 29 originales conservados. Integridad y claves foráneas resultaron correctas.
- Los registros anteriores incluyen 217 pruebas Python y la repetición de 2026-08-01.

Esa evidencia no identifica el hash del árbol sucio ni una copia congelada del
código base; el validador vuelve a copiar código antes de SQLite. Por tanto, no
demuestra todavía equivalencia del código actual ni del contrato final solicitado.
No desecharla: usarla como antecedente, conservándola separada de la corrida nueva.

## Trabajo de UI terminado en esta sesión

Mercado en vivo con gráfico y polling local, resolución automática estricta
Polymarket closed/resolved/1–0, botón «Marcar terminada» por pelea, deshacer y
persistencia por evento/navegador. Las marcas no escriben resultados ni modelos.
Se completaron categorías P4P, catálogo y ficha de peleador con animaciones,
Comparar cuotas y el detalle flotante de consenso, incluyendo teclado y caché
conservada ante errores. No atribuir esos cambios al agente de SQLite ni perderlos.

Verificación de UI y del árbol actual: 382 casos Python + 211 subpruebas en copia
aislada, más 2 pruebas de repositorio en la raíz: 384 casos aprobados. Node:
74 pruebas UI aprobadas y 8 contratos de análisis. SHA256 de los PKL originales
sin diferencias entre modelos-antes.csv y modelos-despues.csv del respaldo de
esta sesión. Esto no sustituye la comparación de predicciones/backtests SQLite.

Comandos ejecutados (desde la raíz de cada checkout):

```powershell
# Copia aislada, con HTTP/HTTPS/ALL_PROXY=http://127.0.0.1:9, NO_PROXY vacío,
# y sin UFC_DB global para no anular las bases temporales de los tests.
python -m pytest 'C:\Users\Juan\Downloads\ufc_predictor\backups\revision_mercado_2026_10_04\tests' --ignore='C:\Users\Juan\Downloads\ufc_predictor\backups\revision_mercado_2026_10_04\tests\test_repo.py' -q
# Raíz original; estas dos pruebas leen el inventario Git.
python -m pytest 'C:\Users\Juan\Downloads\ufc_predictor\tests\test_repo.py' -q
node --test 'C:\Users\Juan\Downloads\ufc_predictor\tests\ui_cards.test.cjs' 'C:\Users\Juan\Downloads\ufc_predictor\tests\ui_explorar.test.cjs' 'C:\Users\Juan\Downloads\ufc_predictor\tests\ui_vivo.test.cjs'
node 'C:\Users\Juan\Downloads\ufc_predictor\tests\test_analisis.js'
```

Antes de continuar, preparar un plan concreto de las correcciones y resolver las
excepciones todavía abiertas con el usuario. Trabajar en una rama desde main,
preservando el árbol actual; un commit por cambio coherente. Entregar commits,
comandos y comparaciones exactas, así como cualquier pendiente real.
