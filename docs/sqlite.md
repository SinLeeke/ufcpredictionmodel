# Persistencia SQLite

La app guarda en `data/ufc.db` todos los CSV de `data/raw` y `data/processed`, los
JSON operativos (incluidos `resultados_recientes` e `indice` de fotos), los modelos
y calibradores, y los modelos recortados por fecha. SQLite forma parte de Python;
no necesita un servicio ni una dependencia adicional. `UFC_DB` permite indicar
otro archivo para pruebas o despliegues.

Las excepciones elegidas para un futuro alojamiento son los recursos que se
entregan como archivos: imágenes PNG/JPG/WebP, `cards/` para intercambiar carteleras,
`outputs/` para exportar resultados e informes HTML, `webui/demo` para ejemplos
versionados y `tests/fixtures` para pruebas. Los originales y las evidencias son
respaldos, no fuentes operativas. Los estáticos y el código también siguen siendo
archivos de la aplicación.

## Migrar una instalación existente

1. Cierra la UI y cualquier trabajo de mantenimiento.
2. Ejecuta desde la raíz `python -m src.migrate_sqlite`.
3. Abre la UI normalmente o ejecuta los comandos habituales de modelado.

El script copia cada original a `data/originales/<sha256>/<ruta>`, sin borrarlo ni
modificarlo. `manifiesto.json` registra ruta, tamaño, hash, timestamp y estado. Cada
tabla se compara contra la copia con `assert_frame_equal(check_exact=True)`, y
cada recurso conserva el SHA256 del original. La migración admite interrupciones:
una transacción confirmada antes del checkpoint se reconoce por su hash al
reiniciar. Una entrada ya migrada y posteriormente actualizada no se revierte al
original antiguo. Una procedencia incompatible genera un error y exige revisión.

La UI mantiene un permiso con latido en SQLite durante su ejecución. La migración
exige exclusividad y rechaza una UI abierta; una caída libera el permiso al caducar
el latido en 90 segundos. Antes de migrar por primera vez una versión antigua de
la UI, hay que cerrarla manualmente porque todavía no registra ese permiso.

## Tablas, exactitud y actualizaciones

- `_resources`: clave lógica, tipo, contenido serializado, SHA256, timestamp y
  esquema pandas. Los modelos se conservan como blobs con sus bytes originales.
- `csv_data__raw__kaggle_ufc_csv` y las tablas `csv_data__processed__…`: columnas
  reales, con `_row_order` como clave primaria. Todas las lecturas ordenan por
  esa columna y restituyen el dtype, incluidos booleanos.
- `_json_entries`: una entrada por clave del objeto cacheado, conservando orden.
  Las escrituras actualizan solo las entradas distintas; el contenido serializado
  en `_resources` permite exportar y verificar el artefacto original.

Al producir una tabla nueva se realiza `to_csv` → `read_csv` **en memoria**, antes
de insertar los valores. Esto reproduce la precisión del parser de CSV que ya
recibía el modelo. Guardar los floats previos a ese paso cambiaría resultados.
Las tablas se actualizan por posición, modificando solo filas distintas; cambios
de esquema reconstruyen la tabla dentro de una transacción. No se cambian los
cruces por nombre, los lookups temporales ni los hiperparámetros del modelo.

Las tablas y los JSON ya interpretados se reutilizan en una caché de memoria
limitada a 64 MiB y 32 entradas. Cada lectura consulta el hash en SQLite; un cambio
desde otro proceso invalida la entrada. El llamador recibe una copia, para que sus
filtros o transformaciones no contaminen lecturas posteriores. Consultar firmas
y fechas no carga los blobs grandes de CSV o modelos.

Los retratos encontrados se descargan una sola vez a `data/raw/fotos/`, con su
identidad, fuente y nombre de archivo registrados en SQLite. Una nueva sesión
reutiliza el archivo válido sin buscar ni descargar de nuevo. El navegador los
cachea por 24 horas. También se recuerdan temporalmente resultados sin foto; una
caída de red no se confunde con ausencia permanente. Las verificaciones de
identidad continúan rechazando homónimos, logos y fotos editoriales incorrectas.

Los scrapers escriben en SQLite. UFCStats confirma cada página descargada antes
de continuar; las siguientes corridas omiten lo ya cacheado. Los delays se
conservan, igual que la petición única a Betano por ciclo. Las firmas de contenido
invalidan las cachés en memoria de la UI cuando los datos cambian.

Las rutas CSV/JSON/PKL siguen apareciendo como claves lógicas en stdout, para
conservar la compatibilidad y poder comparar stdout byte a byte. La existencia
de un archivo viejo en esas rutas nunca sustituye una entrada que falte en SQLite.

## Evidencia reproducible

`scripts/validar_sqlite.py` prepara una copia aislada del código y los datos bajo
`backups/validacion_sqlite/`. Registra el commit original y ejecuta el mismo ciclo
antes y después sobre una misma ruta de trabajo, con HTTP/HTTPS/ALL_PROXY apuntando
a `127.0.0.1:9`, sin exclusiones de proxy. Incluye scraper, entrenamiento,
evaluación, backtests con y sin `--refit`, backtest de carteleras, predicción y
repetición. Ninguno de esos comandos modifica los datos de la instalación real.

Se conservan stdout y stderr separados, hashes por etapa de todos los artefactos
(incluidos modelos y tablas), y `comparacion.json`. Para HTML se sustituyen solo
los UUID de Plotly antes de calcular el hash. Las tablas finales se comparan
contra los CSV de la línea base con igualdad exacta. El día debe ser el mismo
en ambas corridas de predicción normal; la repetición tiene un corte explícito.

Una nueva comparación se prepara con `preparar`, se ejecuta con `base`, luego
`preparar_sqlite`, `sqlite` y `comparar`. Para comparar dos versiones de código,
prepara y ejecuta `base` con la versión de referencia; después actualiza el código
y continúa. El script rechaza sobrescribir una referencia que ya existe.

Para repetir solo la parte SQLite, usa `reiniciar_sqlite`: conserva la corrida
anterior y repone la misma entrada inicial. Después ejecuta `sqlite` y `comparar`.
`retirar_fuentes` aparta solo los archivos viejos del sandbox para comprobar que
la app funciona leyendo SQLite. [Resultados medidos](validacion-sqlite.md).
