# Fuentes, cuotas y publicación

Revisión del 3 de octubre de 2026. Contexto: proyecto gratuito en Chile, sin publicidad,
con posible donación voluntaria. Esta revisión identifica condiciones y aspectos pendientes;
no determina que el repositorio sea ilegal ni sustituye una evaluación jurídica del uso concreto.

## Cartelera y cuotas son cosas diferentes

La lista de combates se toma de la cartelera anunciada que ya está en SQLite. El proveedor
de cuotas aporta precios para las parejas que cubre. Una pelea sin cuota sigue en la lista:
se puede predecir con el modelo, pero no se calcula valor ni una apuesta con un precio inventado.
Los cruces usan parejas completas y equivalencias previamente auditadas; nunca un apellido
parecido. Los historiales del catálogo usan nombre exacto y fichas identificadas por URL.

El caso comprobado es UFC 333: 9 peleas anunciadas en la caché oficial y 2 con precios
en BestFightOdds. Cambiar solamente la casa no garantiza encontrar cuotas para las otras 7.
La cartelera puede cambiar antes del evento y se muestra la fecha de la captura.

En **Cargar → Comparar cuotas** se consulta una fuente y se elige una casa. Todos los
precios de un combate pertenecen a esa misma casa. **Ver capturas guardadas** abre el
historial desde SQLite, sin consultar al proveedor.

Las capturas nuevas conservan precios, proveedor, casa, momento de consulta y la cartelera
anunciada completa. No sustituyen capturas anteriores; se guardan en `cuotas_snapshots`.
Los registros previos a esta función no tenían la lista anunciada adjunta: muestran únicamente
los precios conservados, sin completarlos con la cartelera de hoy. Las capturas de otro día fijan el corte de las estadísticas al reabrirse;
un precio histórico no se presenta como cotización en vivo. Solo se conserva lo que realmente
se consultó: no se inventan cuotas anteriores a la primera captura.

Betano sigue disponible como alternativa. Después de su descarga se guarda el CSV recibido
en SQLite con una clave basada en SHA256 y se completa con la cartelera anunciada compatible.
El refresco en vivo conserva cada cambio de precios, sin duplicar respuestas idénticas.
Esto no añade peticiones a Betano ni cambia los delays de los scrapers.

## Proveedores

| Fuente | Integración | Condiciones y límites |
|---|---|---|
| BestFightOdds | Consulta manual de su portada, una petición para todas las carteleras, caché compartida de 30 minutos. No necesita cuenta. | No garantiza cobertura completa. Su página de condiciones consultada no concede expresamente una licencia de extracción o redistribución. No se afirma que sea una fuente autorizada para publicar. |
| The Odds API | Preparada para `THE_ODDS_API_KEY` en el servidor; mercado `h2h`, región `us`, una petición por consulta. | Requiere registro. El plan gratuito anuncia 500 créditos/mes y excluye históricos. La integración no crea cuentas, contrata planes ni publica la clave. |
| Betano | Integración existente y conservación local de las capturas. | No se depende de su archivo histórico; la aplicación empieza a conservar sus propias consultas. |

[The Odds API](https://the-odds-api.com/) anuncia el plan gratuito. Su [documentación V4](https://the-odds-api.com/liveapi/guides/v4/)
describe MMA y las consultas históricas, que requieren un plan de pago; estas últimas no se
activan desde la UI gratuita. Los [términos de The Odds API](https://the-odds-api.com/terms-and-conditions.html),
actualizados el 31 de agosto de 2026, permiten conservar datos, mostrarlos en aplicaciones y
usarlos en análisis/modelos. Prohíben redistribuirlos como producto de datos independiente.
No debe exponerse públicamente esta API local de capturas como un feed de datos crudos.

Los [términos de BestFightOdds](https://www.bestfightodds.com/terms) son una exclusión de
garantías. La ausencia de una prohibición en esa página y un `robots.txt` permisivo no
equivalen a permiso de uso. Para el dominio público, The Odds API tiene condiciones de
reutilización más claras; BFO necesita aclaración de derechos antes de considerarlo autorizado.

## Rankings y perfiles

**Rankings** muestra una captura oficial fechada, con 13 clasificaciones: 11 categorías
de peso y las dos listas libra por libra. No sustituye esas posiciones por ELO.
Los nombres enlazan al perfil local cuando existe una identidad exacta única; de lo contrario,
abren el buscador. La fecha es la de captura, no una afirmación de cuándo UFC revisó el ranking.

No se agregó un crawler ni un refresco automático de rankings. Para importar un HTML obtenido
con autorización:

```powershell
.\.venv\Scripts\python.exe -m src.rankings ruta\rankings.html --fecha 2026-10-03
```

Se valida la captura antes de sustituir la anterior. Se guarda el original en
`data/originales/<sha256>/` y su hash en el registro de SQLite. La captura inicial se usa
para revisar la aplicación local; la importación manual no convierte el contenido en licenciado.

**Peleadores** ofrece búsqueda local paginada, biografía, récord de peleas registradas en UFC,
golpes significativos por minuto, precisión/defensa, derribos, sumisiones, control y distribución
del golpeo, además del historial con rivales enlazados. Las tasas se calculan con las peleas
que tienen estadísticas y duración disponibles, indicando la muestra. No son necesariamente
las tasas oficiales de toda la carrera. Los asaltos antiguos de duración incierta se excluyen
de las tasas por minuto. Los resultados desconocidos quedan por confirmar.

Si dos fichas tienen el mismo nombre, no se les atribuye el historial antiguo: este no incluye
identificadores suficientes. Una ficha de carrera solo se acepta con su URL/ID exacto.
Las fotos verificadas se reutilizan desde la caché existente; no se elige la primera coincidencia.

Los códigos internos de identidad siguen en los enlaces, pero no se muestran como texto.
Para distinguir homónimos se muestra el nacimiento registrado. Las banderas se basan en
fuentes individuales verificadas y sus metadatos se conservan en SQLite; no se usa el país
del evento de Kaggle como nacionalidad. Los vectores son recursos de la interfaz bajo
[licencia MIT](licencia-banderas.md), servidos localmente con caché del navegador.
El número se muestra en gris, y C/IC en dorado solo con una posición o marcador explícito.
Una pelea por el título no convierte a ambos participantes en campeones. El ranking actual
no se añade a una repetición anterior a su captura.

Las dos fichas Jean Silva tienen Brasil verificado individualmente en Wikidata, cuyos
[datos estructurados son CC0](https://www.wikidata.org/wiki/Wikidata:Licensing).
Solo la ficha moderna se vincula al atleta oficial para mostrar su ranking: nombre, año
de nacimiento, altura, alcance e identificadores deportivos coinciden. Las fuentes discrepan
en el día de nacimiento; queda registrada esa discrepancia y no se cambia BIO ni se asigna
el historial numérico compartido.

## Derechos y publicación en Chile

Tener código para procesar datos, extraer un sitio y republicar su contenido son actos distintos.
No se puede concluir que todo el repositorio infringe una ley por contener un scraper.
Tampoco se puede garantizar que no existan reclamaciones.

La página oficial [Terms of Use de UFC](https://www.ufc.com/news/terms-use) incluye una
restricción de extracción automática y restricciones sobre reproducción de contenido.
La licencia personal descrita allí no habilita por sí sola una página pública. Un intervalo
de cortesía reduce carga, pero no concede permiso. Infringir una condición contractual y
cometer un delito no son conceptos equivalentes; su aplicación concreta requiere análisis.

Para **UFCStats** no se verificó una licencia abierta específica ni permiso escrito para este
uso. No se presupone que toda condición de otra página se aplique automáticamente a este
dominio. Que las estadísticas sean públicas no resuelve por sí solo los permisos de extracción
o de reutilización del conjunto.

La [Ley chilena 17.336](https://www.bcn.cl/leychile/navegar?idNorma=28933), artículo 3,
protege artículos, fotografías y compilaciones con selección/disposición creativa. El número 17
aclara que esa protección de la compilación no se extiende a los datos mismos. Los artículos
17 y 18 reservan al titular ciertos usos de la obra. Por tanto, estadísticas factuales, fotografías
y textos completos requieren análisis diferentes. Ser gratuito o aceptar donaciones no reemplaza
la autorización que corresponda; citar una fuente tampoco otorga derechos automáticamente.

La sección de noticias existente usa titulares/enlaces del RSS y consulta `og:image` para sus
imágenes: no copia artículos completos. La existencia del RSS no demuestra permiso para
republicar todas las fotografías. Antes de abrir un dominio, conviene confirmar los usos del
feed, enlazar las notas y utilizar imágenes propias o con licencia verificable.

También deben verificarse la licencia del dataset concreto de Kaggle y la de las fotos de ESPN,
UFC o Sherdog. La licencia MIT del código no licencia esos contenidos de terceros. Un aviso de
no afiliación ayuda a describir el proyecto, pero no soluciona los derechos sobre contenido o marcas.

La aplicación sigue escuchando únicamente en `127.0.0.1`. No tiene autenticación ni separación
por usuario para mantenimiento, capturas o combinadas. Este trabajo no la despliega en un dominio
ni hace push; la publicación requiere resolver permisos de contenido y el diseño del servidor público.
