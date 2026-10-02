# Auditoría de identidades e historial UFC

Fecha: 1 de octubre de 2026. Auditoría de la copia local del proyecto; no se regeneraron datasets, modelos ni calibradores.

## Alcance y resultados

Se revisaron las 2.241 filas de `data/processed/fighters.csv`, las 17.776 filas de estadísticas detalladas (2.744 nombres diferentes) y las 4.627 fichas de `ufcstats_bio.csv`. La verificación histórica cruzó además `data/raw/kaggle_ufc.csv` con `data/processed/ufcstats_fights.csv`.

Los 277 registros con `n_peleas_hist=0` se explicaron así:

| Situación inicial | Filas | Tratamiento |
| --- | ---: | --- |
| Historial ya existente bajo exactamente el mismo nombre normalizado | 179 | El enriquecimiento consulta el historial detallado al predecir; deja de confiar en el contador agregado antiguo. |
| Alias Bobby Green/King Green e Ian Garry/Ian Machado Garry | 2 | Se recupera la misma carrera en todas las fuentes. |
| Otras variantes verificadas | 95 | Equivalencias explícitas, sin búsqueda difusa automática. |
| Nombre incompleto `Derrick` | 1 | Se mantiene sin equivalencia global por ambigüedad. |

La auditoría inicial registró 96 grupos de identidad: los dos iniciales y 94 grupos añadidos. Hay 97 variantes de filas antiguas con evidencia de una o más peleas coincidentes. `Da Un Jung` y `Da-Un Jung` pertenecen al mismo grupo. Al comparar los CSV después de aplicar las equivalencias, solo `Derrick` sigue sin una correspondencia inequívoca global. El 2 de octubre de 2026 se añadió el orden alternativo `Cong Wang`/`Wang Cong`, verificado en la cartelera oficial de UFC 332 y en la ficha individual; esa fila no proviene del cruce histórico de los datasets.

El caso Bobby Green conserva el historial detallado de King Green: 31 peleas en esta descarga local, frente al contador agregado antiguo 28. No se inventa un contador; las cifras proceden de los registros disponibles y pueden diferir de una ficha en vivo más reciente.

## Criterio de verificación

Para cada equivalencia de la tabla se identificó la misma fecha, el mismo rival resuelto explícitamente y la URL única del combate UFCStats en las dos fuentes. Se comprobó que cada variante tuviera un único nombre de referencia en ese cruce. Los cambios legales de nombre más relevantes también se contrastaron con fuentes oficiales UFC, citadas más abajo. La similitud textual se usó únicamente para explorar candidatos durante la auditoría; no decide identidades al ejecutar la aplicación.

La tabla conserva una pelea de muestra por variante. `tests/fixtures/fighter_aliases.json` versiona esa evidencia y el tamaño del historial detallado observado. Las filas antiguas y las URLs del conjunto local no equivalen a haber consultado de nuevo cada ficha en internet.

## Equivalencias verificadas

El nombre de referencia corresponde a la ficha/dataset UFCStats auditado. Una casa de apuestas o UFC.com puede usar otra variante admitida del mismo grupo.

| Variante antigua | Referencia | Combates coincidentes | Ejemplo: fecha y rival | Fuente |
| --- | --- | ---: | --- | --- |
| Cong Wang (Betano) | Wang Cong | — | UFC 332 anunciado: 2026-10-03 local/04 UTC, Natalia Silva | [Ficha UFC](https://www.ufc.com/athlete/wang-cong), [Ficha UFCStats](http://ufcstats.com/fighter-details/2997e7fe3c9d3d4a), [Cartelera UFC 332](https://www.ufc.com/event/ufc-332) |
| Jun Yong Park | JunYong Park | 1 | 2019-12-21, Marc-Andre Barriault | [UFCStats](http://ufcstats.com/fight-details/b3bd27affa038e9c) |
| Alekander Volkov | Alexander Volkov | 1 | 2019-11-09, Greg Hardy | [UFCStats](http://ufcstats.com/fight-details/3cd1f2c31b4e325a) |
| Alessandro Ricci | Alex Ricci | 2 | 2017-02-19, Paul Felder | [UFCStats](http://ufcstats.com/fight-details/f00ac5af033f44b4) |
| Alex Munoz | Alexander Munoz | 1 | 2020-08-08, Nasrat Haqparast | [UFCStats](http://ufcstats.com/fight-details/26173f6491300eaa) |
| Alexandra Albu | Aleksandra Albu | 4 | 2019-10-26, Loma Lookboonmee | [UFCStats](http://ufcstats.com/fight-details/4ea4d0a73a90bfb0) |
| Ali Qaisi | Ali AlQaisi | 1 | 2020-08-08, Irwin Rivera | [UFCStats](http://ufcstats.com/fight-details/5c8d9d893d163d51) |
| Alvaro Herrera | Alvaro Herrera Mendoza | 4 | 2018-07-28, Devin Powell | [UFCStats](http://ufcstats.com/fight-details/62f564662f33692d) |
| An Ying Wang | Anying Wang | 2 | 2014-08-23, Colby Covington | [UFCStats](http://ufcstats.com/fight-details/4de8b5898e1a23c8) |
| Aori Qileng | Aoriqileng | 1 | 2021-04-24, Jeff Molina | [UFCStats](http://ufcstats.com/fight-details/b5a8323de18f7e95) |
| Ariane Lipski | Ariane da Silva | 8 | 2022-08-13, Priscila Cachoeira | [UFCStats](http://ufcstats.com/fight-details/abd50fad1e7b030b) |
| Benny Alloway | Ben Alloway | 3 | 2013-08-28, Zak Cummings | [UFCStats](http://ufcstats.com/fight-details/602e8602fe9c9121) |
| Bobby Green | King Green | 19 | 2022-12-17, Drew Dober | [UFCStats](http://ufcstats.com/fight-details/c335f44e4f3515ea) |
| Bradley Scott | Brad Scott | 8 | 2018-05-27, Carlo Pedersoli | [UFCStats](http://ufcstats.com/fight-details/3e9ddcd30fdc5d85) |
| Brianna Van Buren | Brianna Fortino | 2 | 2020-06-20, Tecia Torres | [UFCStats](http://ufcstats.com/fight-details/1adee75d6c671cc8) |
| Bubba McDaniel | Robert McDaniel | 3 | 2014-03-15, Sean Strickland | [UFCStats](http://ufcstats.com/fight-details/8f979d206eaec468) |
| Caludia Gadelha | Claudia Gadelha | 1 | 2019-07-06, Randa Markos | [UFCStats](http://ufcstats.com/fight-details/7fe0cec2b0f1c146) |
| Caludio Puelles | Claudio Puelles | 1 | 2019-09-21, Marcos Mariano | [UFCStats](http://ufcstats.com/fight-details/4f7ec66199bba232) |
| Carlo Pedersoli | Carlo Pedersoli Jr. | 3 | 2019-02-23, Dwight Grant | [UFCStats](http://ufcstats.com/fight-details/fd438db3e60f062a) |
| Cheyanne Buys | Cheyanne Vlismas | 2 | 2021-07-31, Gloria de Paula | [UFCStats](http://ufcstats.com/fight-details/b4622ca7cf0e8506) |
| Costas Philippou | Constantinos Philippou | 10 | 2015-05-16, Gegard Mousasi | [UFCStats](http://ufcstats.com/fight-details/1caec47dc08613a7) |
| Cris Cyborg | Cristiane Justino | 7 | 2019-07-27, Felicia Spencer | [UFCStats](http://ufcstats.com/fight-details/240e9389cca3bd18) |
| Da Un Jung | Da Woon Jung | 2 | 2019-12-21, Mike Rodriguez | [UFCStats](http://ufcstats.com/fight-details/47e49e04e32be7e9) |
| Da-Un Jung | Da Woon Jung | 1 | 2021-04-10, William Knight | [UFCStats](http://ufcstats.com/fight-details/cd5d9828b278181a) |
| Danaa Batgerel | Batgerel Danaa | 3 | 2021-04-24, Kevin Natividad | [UFCStats](http://ufcstats.com/fight-details/eb5d62bda1581c62) |
| Elizeu Dos Santos | Elizeu Zaleski dos Santos | 2 | 2020-03-14, Aleksei Kunchenko | [UFCStats](http://ufcstats.com/fight-details/9fc6aba53508dc48) |
| Emily Peters Kagan | Emily Kagan | 2 | 2015-12-10, Kailin Curran | [UFCStats](http://ufcstats.com/fight-details/8bfa9df5341c95c0) |
| Glaico Franca | Glaico Franca Moreira | 3 | 2016-09-24, Gregor Gillespie | [UFCStats](http://ufcstats.com/fight-details/fae3f395669b7285) |
| Grigorii Popov | Grigory Popov | 2 | 2019-11-09, Davey Grant | [UFCStats](http://ufcstats.com/fight-details/f0418c2c989a5cde) |
| Heather Jo Clark | Heather Clark | 3 | 2016-11-05, Alexa Grasso | [UFCStats](http://ufcstats.com/fight-details/52943c821416dc38) |
| Heili Alateng | Alatengheili | 3 | 2020-10-03, Casey Kenney | [UFCStats](http://ufcstats.com/fight-details/ac6b2a5f24c2b8bd) |
| Humberto Brown | Humberto Brown Morrison | 1 | 2014-11-15, Gabriel Benitez | [UFCStats](http://ufcstats.com/fight-details/4087bb7b3b1b9e24) |
| Ian Garry | Ian Machado Garry | 3 | 2022-07-02, Gabe Green | [UFCStats](http://ufcstats.com/fight-details/4d8d1701c43c5fea) |
| Isabela De Pauda | Isabela de Padua | 1 | 2019-11-16, Ariane Lipski | [UFCStats](http://ufcstats.com/fight-details/1800ffbb34ac7ed8) |
| Jim Crute | Jimmy Crute | 1 | 2020-02-22, Michal Oleksiejczuk | [UFCStats](http://ufcstats.com/fight-details/2b417eb1ffa56ac1) |
| Jimmy Wallhead | Jim Wallhead | 2 | 2017-06-03, Luan Chagas | [UFCStats](http://ufcstats.com/fight-details/88e0de323a83f241) |
| Joanne Calderwood | Joanne Wood | 13 | 2021-06-12, Lauren Murphy | [UFCStats](http://ufcstats.com/fight-details/34cb6e9952cd30a4) |
| Joe Gigliotti | Joseph Gigliotti | 2 | 2016-12-09, Gerald Meerschaert | [UFCStats](http://ufcstats.com/fight-details/85feac6924abb35b) |
| Joshua Culibao | Josh Culibao | 1 | 2020-02-22, Jalin Turner | [UFCStats](http://ufcstats.com/fight-details/02bdb7a5b2986571) |
| Joshua Sampo | Josh Sampo | 4 | 2015-05-23, Justin Scoggins | [UFCStats](http://ufcstats.com/fight-details/419d8143afbcd61c) |
| Juan Puig | Juan Manuel Puig | 2 | 2014-11-22, Dooho Choi | [UFCStats](http://ufcstats.com/fight-details/1a637fbda4bdf575) |
| Junior Hernandez | Ramiro Hernandez | 2 | 2014-01-25, Hugo Viana | [UFCStats](http://ufcstats.com/fight-details/df7cf7ef41eccbe6) |
| Kai Kamaka | Kai Kamaka III | 2 | 2021-05-01, TJ Brown | [UFCStats](http://ufcstats.com/fight-details/d72f9b3ac742a9e3) |
| Kai Kara France | Kai Kara-France | 2 | 2020-02-22, Tyson Nam | [UFCStats](http://ufcstats.com/fight-details/ecc23234e820458d) |
| Kalinn Williams | Khaos Williams | 1 | 2020-02-08, Alex Morono | [UFCStats](http://ufcstats.com/fight-details/ed499508be1e5532) |
| Katlyn Chookagian | Katlyn Cerminara | 16 | 2022-10-22, Manon Fiorot | [UFCStats](http://ufcstats.com/fight-details/25f3e4fa781c1c8a) |
| Kevin Souza | Edimilson Souza | 4 | 2015-11-07, Chas Skelly | [UFCStats](http://ufcstats.com/fight-details/6d9f6f7004c791d5) |
| Krzystof Jotko | Krzysztof Jotko | 1 | 2019-07-27, Marc-Andre Barriault | [UFCStats](http://ufcstats.com/fight-details/dbca9f6bb7290c0d) |
| Leonardo Augusto Leleco | Leonardo Guimaraes | 2 | 2016-09-17, Antonio Carlos Junior | [UFCStats](http://ufcstats.com/fight-details/c87d2569da8d4305) |
| Liu Pingyuan | Pingyuan Liu | 4 | 2019-12-21, Kyung Ho Kang | [UFCStats](http://ufcstats.com/fight-details/f93f794247af708a) |
| Luci Pudilova | Lucie Pudilova | 1 | 2020-01-25, Justine Kish | [UFCStats](http://ufcstats.com/fight-details/151c2bd6dfefb4b5) |
| Luiz Garagorri | Eduardo Garagorri | 1 | 2019-08-10, Humberto Bandenay | [UFCStats](http://ufcstats.com/fight-details/aef94727eb3897df) |
| Michelle Waterson | Michelle Waterson-Gomez | 11 | 2021-05-08, Marina Rodriguez | [UFCStats](http://ufcstats.com/fight-details/b948102c6205af63) |
| Minotauro Nogueira | Antonio Rodrigo Nogueira | 6 | 2015-08-01, Stefan Struve | [UFCStats](http://ufcstats.com/fight-details/b0367c907cc549c0) |
| Mirko Cro Cop | Mirko Filipovic | 5 | 2015-04-11, Gabriel Gonzaga | [UFCStats](http://ufcstats.com/fight-details/6a7892754af30685) |
| Mizuki Inoue | Mizuki | 2 | 2020-08-22, Amanda Lemos | [UFCStats](http://ufcstats.com/fight-details/0a3e48cdd97267f4) |
| Montserrat Conejo | Montserrat Conejo Ruiz | 2 | 2021-07-17, Amanda Lemos | [UFCStats](http://ufcstats.com/fight-details/c5e71fbf22f669f7) |
| Montserrat Rendon | Montse Rendon | 2 | 2024-03-23, Daria Zhelezniakova | [UFCStats](http://ufcstats.com/fight-details/f1c3abce15ef053e) |
| Na Liang | Liang Na | 1 | 2021-04-24, Ariane Carnelossi | [UFCStats](http://ufcstats.com/fight-details/a3cde349c8e018fb) |
| Nico Musoke | Nicholas Musoke | 6 | 2017-05-28, Bojan Velickovic | [UFCStats](http://ufcstats.com/fight-details/9c3f3bc7f7472e0c) |
| Nina Ansaroff | Nina Nunes | 7 | 2019-06-08, Tatiana Suarez | [UFCStats](http://ufcstats.com/fight-details/56403d0fd259c5d9) |
| Ning Guangyou | Guangyou Ning | 4 | 2016-11-26, Marlon Vera | [UFCStats](http://ufcstats.com/fight-details/2e209dc450b7ebe3) |
| Ode Obsourne | Ode Osbourne | 1 | 2020-01-18, Brian Kelleher | [UFCStats](http://ufcstats.com/fight-details/4eff0432bd364a23) |
| Omar Antonio Morales Ferrer | Omar Morales | 1 | 2019-12-21, Dong Hyun Ma | [UFCStats](http://ufcstats.com/fight-details/9140e6fdeaa7cd3f) |
| Patricio Freire | Patricio Pitbull | 2 | 2025-07-19, Dan Ige | [UFCStats](http://ufcstats.com/fight-details/acc961fd5cf5c62e) |
| Peter Yan | Petr Yan | 1 | 2019-12-14, Urijah Faber | [UFCStats](http://ufcstats.com/fight-details/a0c82ba11a373008) |
| Philip Rowe | Phil Rowe | 1 | 2021-02-13, Gabe Green | [UFCStats](http://ufcstats.com/fight-details/357c5b86ec83b826) |
| Phillip Hawes | Phil Hawes | 1 | 2020-10-24, Jacob Malkoun | [UFCStats](http://ufcstats.com/fight-details/a2620cbef573a837) |
| Polo Reyes | Marco Polo Reyes | 6 | 2019-02-23, Damir Hadzovic | [UFCStats](http://ufcstats.com/fight-details/18d6df67968bf06b) |
| Rafael Feijao | Rafael Cavalcante | 5 | 2016-02-06, Ovince Saint Preux | [UFCStats](http://ufcstats.com/fight-details/37008594c087470c) |
| Rampage Jackson | Quinton Jackson | 7 | 2015-04-25, Fabio Maldonado | [UFCStats](http://ufcstats.com/fight-details/4669c07f3cc9e35f) |
| Raphael Pessoa Nunes | Raphael Pessoa | 2 | 2019-10-26, Jeff Hughes | [UFCStats](http://ufcstats.com/fight-details/3d9aeef58dd0b51b) |
| Rick Glenn | Ricky Glenn | 6 | 2018-11-30, Kevin Aguilar | [UFCStats](http://ufcstats.com/fight-details/4e6bbc5832e55f64) |
| Rob Whiteford | Robert Whiteford | 5 | 2016-04-10, Lucas Martins | [UFCStats](http://ufcstats.com/fight-details/42afd8c4fc85f485) |
| Roberto Sanchez | Robert Sanchez | 3 | 2018-09-08, Jarred Brooks | [UFCStats](http://ufcstats.com/fight-details/9399c772adc7bcab) |
| Rocco Martin | Anthony Rocco Martin | 2 | 2019-11-09, Ramazan Emeev | [UFCStats](http://ufcstats.com/fight-details/1317d7cd79495a0e) |
| Rodolfo Rubio | Rodolfo Rubio Perez | 1 | 2014-11-08, Diego Rivas | [UFCStats](http://ufcstats.com/fight-details/7826c23386a1e09a) |
| Rong Zhu | Rongzhu | 2 | 2021-09-18, Brandon Jenkins | [UFCStats](http://ufcstats.com/fight-details/85e5498808346d6b) |
| Seohee Ham | Seo Hee Ham | 4 | 2016-11-26, Danielle Taylor | [UFCStats](http://ufcstats.com/fight-details/314aea77cd24210f) |
| Su Mudaerji | Sumudaerji | 4 | 2021-01-20, Zarrukh Adashev | [UFCStats](http://ufcstats.com/fight-details/ddbe6fd66d7f9e35) |
| Tecia Torres | Tecia Pennington | 15 | 2022-04-09, Mackenzie Dern | [UFCStats](http://ufcstats.com/fight-details/d8945e21a63e2451) |
| Tiago Trator | Tiago dos Santos e Silva | 4 | 2016-12-09, Shane Burgos | [UFCStats](http://ufcstats.com/fight-details/4bf0be780f2d09be) |
| Tiequan Zhang | Zhang Tiequan | 4 | 2012-11-10, Jon Tuck | [UFCStats](http://ufcstats.com/fight-details/8d556e2826924946) |
| Tim Johnson | Timothy Johnson | 7 | 2018-02-03, Marcelo Golm | [UFCStats](http://ufcstats.com/fight-details/0da43c3ec0e11650) |
| Ulka Sasaki | Yuta Sasaki | 9 | 2018-11-17, Alexandre Pantoja | [UFCStats](http://ufcstats.com/fight-details/961f434fe238f40e) |
| Vernon Ramos | Vernon Ramos Ho | 1 | 2015-11-21, Alvaro Herrera | [UFCStats](http://ufcstats.com/fight-details/44502b8c5546fb12) |
| Veronica Macedo | Veronica Hardy | 5 | 2020-03-14, Bea Malecki | [UFCStats](http://ufcstats.com/fight-details/ef526567c4dcf371) |
| Vincente Luque | Vicente Luque | 1 | 2019-08-10, Mike Perry | [UFCStats](http://ufcstats.com/fight-details/7feadf01c5920285) |
| Waldo Cortes-Acosta | Waldo Cortes Acosta | 6 | 2024-05-11, Robelis Despaigne | [UFCStats](http://ufcstats.com/fight-details/e98eb6de29c62c9c) |
| Weili Zhang | Zhang Weili | 4 | 2020-03-07, Joanna Jedrzejczyk | [UFCStats](http://ufcstats.com/fight-details/cf0a6466b762c668) |
| Wendell Oliveira | Wendell Oliveira Marques | 2 | 2015-05-30, Darren Till | [UFCStats](http://ufcstats.com/fight-details/61d6b591430b6e25) |
| William Patolino | William Macario | 4 | 2015-02-22, Matt Dwyer | [UFCStats](http://ufcstats.com/fight-details/ec659c4e19f62700) |
| Wuliji Buren | Wulijiburen | 3 | 2019-02-09, Jonathan Martinez | [UFCStats](http://ufcstats.com/fight-details/8e43d61ca6f2d904) |
| Yana Kunitskaya | Yana Santos | 7 | 2021-07-10, Irene Aldana | [UFCStats](http://ufcstats.com/fight-details/3740c8033e31c90d) |
| Youssef Zalel | Youssef Zalal | 1 | 2020-02-08, Austin Lingo | [UFCStats](http://ufcstats.com/fight-details/a6441acec6718f03) |
| Zachary Reese | Zach Reese | 3 | 2024-08-24, Jose Daniel Medina | [UFCStats](http://ufcstats.com/fight-details/d2caa1ddb9de7481) |
| Zhalgas Zhamagulov | Zhalgas Zhumagulov | 1 | 2020-07-11, Raulian Paiva | [UFCStats](http://ufcstats.com/fight-details/0e8d5c16eb9cb1cf) |
| Zu Anyanwu | Azunna Anyanwu | 1 | 2017-09-16, Justin Ledet | [UFCStats](http://ufcstats.com/fight-details/7b80dd233e200dd2) |

## Fuentes oficiales complementarias

- [King Green y su nuevo nombre](https://www.ufc.com/news/king-green-always-keeping-it-real-ufc-304).
- [Ficha de Ian Machado Garry](https://www.ufc.com/athlete/ian-machado-garry).
- [Katlyn Cerminara, antes Chookagian](https://www.ufc.com/video/137401).
- [Veronica Macedo pasó a llamarse Veronica Hardy](https://www.ufc.com/news/veronica-hardy-started-a-new-chapter-in-her-life-ufc-286?language_content_entity=en).
- [Tecia Torres, ficha Tecia Pennington](https://www.ufc.com.br/athlete/tecia-pennington).
- [Entrevista antigua de Ariane Lipski, ficha actual Ariane da Silva](https://www.ufc.com/video/Ariane-Lipski-post-fight-interview-ufc-fight-night-yan-vs-dvalishvili).
- [Ficha de Joanne Wood con historial Calderwood](https://www.ufc.com/athlete/joanne-wood).
- [Nina Nunes, antes Ansaroff](https://www.ufc.com/news/tatiana-suarez-its-long-way-top-ufc-312).
- [Patricio Freire y Patricio Pitbull](https://www.ufc.com/news/who-patricio-pitbull-golden-journey-ufc-314).
- [Khaos Williams y Kalinn Williams](https://jp.ufc.com/news/ufc-247-scorecard-jones-reyes-shevchenko-krause-khaos).
- [Ramiro «Junior» Hernandez](https://www.ufc.com/node/64593).
- [Cheyanne Buys y ficha Cheyanne Vlismas](https://www.ufc.com/video/jp-and-cheyanne-buys-married-combat-ufc-fight-night-brunson-holland-watch).
- [Isabela de Padua contra Ariane Lipski, 16-11-2019](https://www.ufc.com/news/ufc-sao-paulo-results-jacare-souza-jan-blachowicz?language_content_entity=en).

## Datos ausentes y debut confirmado

`n_peleas_hist` continúa representando el historial detallado usado por el modelo. Si la identidad no está disponible en la descarga local, se conserva `None` o un conteo explícito de la ficha y `historial_disponible=False`; eso mantiene la advertencia NO FIABLE. La ausencia de filas no demuestra cero peleas.

Para la etiqueta amarilla, `info_a.debut_ufc_confirmado` y `info_b.debut_ufc_confirmado` exigen `historial_ufc_confirmado=True` y `n_peleas_ufc=0`. Este contador solo incluye combates pasados de eventos UFC identificados en una tabla completa; una pelea futura no suma. Los no contest y empates pasados sí suman. Los eventos WEC, Strikeforce, PRIDE y otras organizaciones identificadas no suman. Las finales oficiales de The Ultimate Fighter cuentan; un episodio no basta. Una tabla ausente, incompleta o con eventos no reconocidos deja el conteo como desconocido y nunca activa la etiqueta.

Las fichas cacheadas sin resultados y sin estos metadatos se verifican mediante su URL ya conocida, conservando los demás campos de la ficha. Si falla la red, siguen disponibles y no se declara debut. No se invalida ni vuelve a descargar todo el caché.

`orden_cartelera` y `total_cartelera` preservan la posición en el CSV original aunque se omita una pelea. Esto permite identificar estelar/coestelar de Betano sin promover otra pelea por falta de datos.

## Limitaciones y caso pendiente

`Derrick` coincide contextualmente con Derrick Krantz contra Song Kenan el 31-08-2019 ([combate UFCStats](http://ufcstats.com/fight-details/676561d9690ce31d)). No se convierte en un alias global: también existen Derrick Lewis y otros peleadores con ese nombre. Para esa fila hace falta un identificador de combate o el nombre completo. Tampoco se unen automáticamente homónimos como Mike Davis; se conserva la selección existente de ficha con mayor información.

La auditoría cubre los nombres presentes en estos CSV, no todas las casas de apuestas ni variantes futuras. Los eventos no reconocidos requieren verificación antes de afirmar un debut. No se reentrenó ningún modelo, no se recalcularon históricos globales y no se modificaron CSV originales.

## Validación

Las regresiones offline cubren los aliases contra la fixture de evidencia, separación de homónimos, recuperación de cachés antiguos, enriquecimiento y cortes temporales, tablas UFC/otras organizaciones, historial desconocido, actualización de metadatos sin red y conservación del orden cuando se omite una pelea. Las pruebas usan carpetas temporales y respuestas simuladas; no dependen de la red ni sobrescriben datos reales.
