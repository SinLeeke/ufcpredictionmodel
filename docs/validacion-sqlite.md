# Resultado de la migración a SQLite

Verificación realizada el 3 de octubre de 2026 sobre `main`, después del merge
fast-forward de `mejoras-ui-sqlite`. La referencia fue el mismo código integrado,
commit `dad9177`, antes de sustituir sus lecturas y escrituras.

| Comprobación | Resultado |
|---|---|
| stdout de scraper, train, evaluación, valor/metodo con y sin refit, carteleras, card y repetición | 10 de 10 idénticos byte a byte |
| SHA256 de artefactos por cada etapa | Ninguna diferencia |
| Artefactos comparados en la última etapa | 431, incluidos modelos, CSV, JSON e imágenes |
| HTML incluidos | 151; se retiran únicamente UUID de divs Plotly |
| Tablas frente a CSV de referencia | 10 de 10 con `assert_frame_equal(check_exact=True)` |
| Lectura sin archivos CSV/JSON/PKL anteriores | Los 29 archivos fuente fueron retirados solo del sandbox; la corrida pasó |
| Originales y respaldos | 29 con SHA256 y timestamp originales intactos |
| Integridad SQLite | `integrity_check=ok`, sin infracciones de claves foráneas |
| Pruebas Python | 217 aprobadas |
| Pruebas UI | 29 aprobadas y 8 contratos de análisis verificados |
| Servidor | Inicio y salud responden correctamente desde SQLite |

Las corridas se hicieron con HTTP/HTTPS/ALL_PROXY en `127.0.0.1:9`, sin exclusiones,
en el mismo día y desde la misma ruta aislada. La repetición usó el corte explícito
`2026-08-01`. Cada nueva corrida de validación partió de la copia inicial de datos,
modelos, carteleras y exportaciones; los intentos anteriores se conservaron.

La migración inicial y su reejecución verificaron las tablas frente a cada copia
original. Las tablas generadas se compararon además frente a la salida de la línea
base. Se probó la interrupción entre una transacción y el manifiesto, así como una
interrupción después de descargar una página de UFCStats: al reanudar, no se pidió
de nuevo la página ya confirmada. Mantenimiento vacía la caché en SQLite y deja el
JSON antiguo intacto.

## Reutilización y tiempos de lectura

Medición local: primera lectura SQLite frente a la mediana de 20 lecturas con la
caché de memoria caliente. Incluye verificar el hash y entregar una copia del
DataFrame. Es una medición de tablas, no del tiempo completo de abrir la página.

| Tabla | Primera lectura | Lectura reutilizada | Mejora |
|---|---:|---:|---:|
| features | 259,43 ms | 12,72 ms | 20,4× |
| ufcstats_fight_stats | 387,16 ms | 17,57 ms | 22,0× |
| ufcstats_fights | 100,94 ms | 9,22 ms | 11,0× |

Una foto encontrada se conserva como imagen estática con su índice en SQLite.
La prueba elimina la caché Python y abre otra sesión sin red: reutiliza la misma
foto y no realiza ninguna petición. Los cambios de tablas invalidan la caché de
memoria, y las modificaciones de un DataFrame devuelto no contaminan otra lectura.

Los registros completos permanecen localmente en `backups/validacion_sqlite/`:
`origen.json`, stdout/stderr por etapa, hashes, `comparacion.json`,
`originales_verificados.json` y `rendimiento.json`. El respaldo de la instalación
está en `data/originales/`, con `manifiesto.json`; su base operativa es `data/ufc.db`.
