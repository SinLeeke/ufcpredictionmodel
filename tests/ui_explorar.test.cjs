const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Renderizadores de producción sin navegador, red ni scrapers. Los datos de
// prueba no se escriben en SQLite ni en las cachés de la aplicación.
const raiz = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(raiz, 'webui/static/app.js'), 'utf8');
const explorar = fs.readFileSync(path.join(raiz, 'webui/static/explorar.js'), 'utf8');
const contexto = vm.createContext({porTeclado:false, movimientoReducido:false});
vm.runInContext(fs.readFileSync(path.join(raiz, 'webui/static/iconos.js'), 'utf8'), contexto);
vm.runInContext(app.slice(app.indexOf('const NBSP_FINO ='), app.indexOf('const cls =')), contexto);
vm.runInContext(app.slice(app.indexOf('const SILUETA ='), app.indexOf('function cargarFotos(')), contexto);
vm.runInContext("const miles = n => Number(n).toLocaleString('es-CL'); const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'; const reducir = () => movimientoReducido;", contexto);
// Las duraciones compartidas (MOV) tal cual están en app.js.
vm.runInContext(app.slice(app.indexOf('const MOV ='), app.indexOf('// Lo que se hace con el teclado')), contexto);
vm.runInContext(explorar.slice(0, explorar.indexOf('async function cargarRankings(')), contexto);
vm.runInContext(explorar.slice(explorar.indexOf('function filaCatalogo('), explorar.indexOf('async function buscarPeleadores(')), contexto);
vm.runInContext(explorar.slice(explorar.indexOf('const medidaPerfil ='), explorar.indexOf('function volverPeleadores(')), contexto);

const p4p = {clave:"Men's Pound-for-Pound", nombre:"Men's Pound-for-Pound", p4p:true, genero:'M'};
const division = clave => ({clave, nombre:{Featherweight:'Peso pluma', Lightweight:'Ligero', Bantamweight:'Peso gallo'}[clave], fuente:'ranking', fecha:'2026-10-04'});

test('cada peleador P4P muestra su categoría junto al nombre, aunque no sea campeón', () => {
  const html = contexto.filaRanking({nombre:'Ilia Topuria', puesto:5, division:division('Lightweight'), campeon:null}, p4p);
  assert.match(html, /class="rk-identidad"/);
  assert.match(html, /Ilia Topuria<\/span>/);
  assert.match(html, /class="rk-categoria">Peso ligero<\/span>/);
  assert.doesNotMatch(html, /rk-oro|Campeón/);
});

test('un campeón del P4P dice de qué peso es y no repite la división en otra etiqueta', () => {
  const html = contexto.filaRanking({nombre:'Alexander Volkanovski', puesto:2,
    division:division('Featherweight'), campeon:{clave:'Featherweight', division:'Peso pluma'}}, p4p);
  assert.match(html, /rk-oro/);
  assert.match(html, /class="rk-rotulo">Campeón peso pluma<\/small>/);
  assert.doesNotMatch(html, /rk-categoria/);
  assert.equal((html.match(/peso pluma/gi) || []).length, 1);
  const welter = contexto.filaRanking({nombre:'Islam Makhachev', puesto:1, division:{clave:'Welterweight', nombre:'Peso welter'},
    campeon:{clave:'Welterweight', division:'Peso welter', interino:false}}, p4p);
  assert.match(welter, /class="rk-rotulo">Campeón peso wélter<\/small>/);
});

test('una campeona dice «Campeona», con su peso en el P4P y sin él en su división', () => {
  const p4pF = {clave:"Women's Pound-for-Pound", nombre:"Women's Pound-for-Pound", p4p:true, genero:'F'};
  const mosca = {clave:"Women's Flyweight", nombre:"Women's Flyweight", p4p:false, genero:'F'};
  const campeon = {clave:"Women's Flyweight", division:"Women's Flyweight", interino:false};
  assert.match(contexto.filaRanking({nombre:'Valentina Shevchenko', puesto:1, campeon,
    division:{clave:"Women's Flyweight", nombre:"Women's Flyweight"}}, p4pF), /class="rk-rotulo">Campeona peso mosca<\/small>/);
  assert.match(contexto.filaRanking({nombre:'Valentina Shevchenko', puesto:0, campeon}, mosca), /class="rk-rotulo">Campeona<\/small>/);
  assert.match(contexto.filaRanking({nombre:'X', puesto:0, campeon:{...campeon, interino:true}}, mosca), /Campeona interina/);
  // Un campeón de otro peso que además figura en una segunda división muestra solo la otra.
  const doble = contexto.filaRanking({nombre:'Ilia Topuria', puesto:2, division:null,
    divisiones:[division('Featherweight'), division('Lightweight')], campeon:{clave:'Lightweight', division:'Ligero'}}, p4p);
  assert.match(doble, /Campeón peso ligero/);
  assert.match(doble, /class="rk-categoria">Peso pluma<\/span>/);
});

test('sin division en la respuesta (servidor viejo) se busca por identidad exacta en la misma captura', () => {
  const EXP = vm.runInContext('EXP', contexto);   // const de explorar.js: no es propiedad del contexto
  EXP.rankings = {divisiones:[p4p,
    {clave:'Featherweight', nombre:'Peso pluma', peleadores:[{nombre:'Jean Silva', perfil_ufc:'https://www.ufc.com/athlete/jean-silva', puesto:1}]},
    {clave:'Lightweight', nombre:'Ligero', peleadores:[{nombre:'Jean Silva', perfil_ufc:'https://www.ufc.com/athlete/otro-jean-silva', puesto:3}]}]};
  try {
    const html = contexto.filaRanking({nombre:'Jean Silva', perfil_ufc:'https://www.ufc.com/athlete/jean-silva', puesto:5}, p4p);
    assert.match(html, /class="rk-categoria">Peso pluma<\/span>/);          // el homónimo de Ligero no cuenta
    // Sin ficha ni ID no se adivina por el nombre.
    assert.match(contexto.filaRanking({nombre:'Jean Silva', puesto:5}, p4p), /División no disponible/);
    // Con la respuesta actual, una lista vacía se respeta: el servidor ya decidió.
    assert.match(contexto.filaRanking({nombre:'Jean Silva', perfil_ufc:'https://www.ufc.com/athlete/jean-silva', puesto:5,
      division:null, divisiones:[]}, p4p), /División no disponible/);
  } finally { EXP.rankings = null; }
});

test('dos divisiones verificadas se muestran juntas sin escoger una por orden', () => {
  for (const divisiones of [[division('Featherweight'),division('Lightweight')], [division('Lightweight'),division('Featherweight')]]) {
    const html = contexto.filaRanking({nombre:'Ilia Topuria', puesto:5, division:null, divisiones}, p4p);
    assert.match(html, /class="rk-categoria">Peso (?:pluma \/ Peso ligero|ligero \/ Peso pluma)<\/span>/);
    assert.doesNotMatch(html, /Campeón/);
  }
});

test('sin categoría verificada se informa el faltante; fuera de P4P no se repite', () => {
  assert.match(contexto.filaRanking({nombre:'Peleador', puesto:4, division:null, divisiones:[]}, p4p), /División no disponible/);
  const html = contexto.filaRanking({nombre:'Peleador', puesto:4, division:division('Featherweight')}, {clave:'Featherweight', nombre:'Peso pluma', p4p:false});
  assert.doesNotMatch(html, /rk-categoria/);
});

test('la fila de catálogo nombra una pelea, informa la ausencia y preserva homónimos', () => {
  assert.match(contexto.filaCatalogo({nombre:'Aaron Brink', id:'1234', peso:'Pesado', peleas:1}), /<b>1<\/b><span>pelea en UFC/);
  assert.match(contexto.filaCatalogo({nombre:'Sin historial', id:'5678', peleas:0}), /División no disponible/);
  const ambiguo = contexto.filaCatalogo({nombre:'Mike Davis', id:null, homonimo:true, peso:'Ligero', peleas:null});
  assert.match(ambiguo, /Nombre compartido: historiales sin separar/);
  assert.match(ambiguo, /href="#buscar-Mike%20Davis"/);
  assert.doesNotMatch(ambiguo, /<b>0<\/b>|Ligero/);
});

test('nombres y categorías de las listas no se convierten en HTML', () => {
  const html = contexto.filaRanking({nombre:'Alpha <script>', puesto:4,
    division:{nombre:'<img src=x>', clave:null}}, p4p) + contexto.filaCatalogo({nombre:'Beta <script>', peso:'<img src=x>', peleas:0});
  assert.doesNotMatch(html, /<script>|<img src=x>/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img src=x&gt;/);
});

const perfil = (extras={}) => ({nombre:'Aalon Cruz', peso:'Ligero', edad:37,
  bio:{height_cm:182.9, reach_cm:198.1, stance:'Switch', fighter_url:'http://ufcstats.com/fighter-details/1234'},
  record:{V:0,P:2,E:0,NC:0}, metricas:{slpm:.65, sapm:21.08, str_acc:.13, td_avg:0},
  metricas_fuente:'Peleas UFC con estadísticas y duración disponibles', muestra:2,
  zonas:{head:10,body:5,leg:5}, posiciones:{distance:20}, actualizado:'2021-03-06',
  historial:[{fecha:'2021-03-06',evento:'UFC 259',rival:'Uros Medic',rival_id:'5678',resultado:'P',metodo:'KO/TKO',asalto:1,tiempo:'1:40'}], ...extras});

test('la ficha identifica medidas, conserva ceros reales y mantiene el alcance del récord', () => {
  const html = contexto.vistaPerfil(perfil());
  assert.match(html, /<dt>Altura<\/dt><dd>182,9 cm<\/dd>/);
  assert.match(html, /<dt>Alcance<\/dt><dd>198,1 cm<\/dd>/);
  assert.match(html, /<dt>Guardia<\/dt><dd>Cambiante<\/dd>/);
  assert.match(html, /<dt>Victorias<\/dt><dd>0<\/dd>/);
  assert.match(html, /no es el récord profesional completo/);
  assert.match(html, /última división registrada/);
  assert.match(html, /Conectados.*?<dd>0,65<\/dd>/s);
  assert.match(html, /Derribos.*?<dd>0,00<\/dd>/s);
  assert.doesNotMatch(html, /NaN|undefined|path d="undefined"/);
});

test('el historial real queda accesible como despliegue nativo abierto y tabla con encabezados', () => {
  const html = contexto.vistaPerfil(perfil());
  assert.match(html, /<details class="perfil-desplegable" open><summary><h2>Historial en UFC/);
  assert.match(html, /<span>1 pelea<small>Elige una para verla como se veía ese día<\/small><\/span>/);
  // Cada fila abre su pelea: un botón real con nombre accesible, y el rival sigue siendo su enlace.
  assert.match(html, /<button type="button" class="hist-abrir" data-hist="0" aria-label="Ver UFC 259 frente a Uros Medic como se veía ese día">/);
  assert.match(html, /href="#peleador-5678"/);
  assert.equal((html.match(/scope="col"/g) || []).length, 5);
  assert.match(html, /res-P">Derrota/);
  assert.match(html, /KO\/TKO/);
});

test('la ficha sin historia ni métricas no inventa récord, porcentajes ni fotografía de un homónimo', () => {
  const html = contexto.vistaPerfil(perfil({homonimo:true, record:null, historial:[], bio:{}, edad:null, peso:null, metricas:{}, zonas:{}, posiciones:{}}));
  assert.match(html, /Récord UFC sin atribución verificable/);
  assert.match(html, /no se mezcla ni se atribuye aquí/);
  assert.match(html, /División no disponible/);
  assert.match(html, /<dd>—<\/dd>/);
  assert.doesNotMatch(html, /perfil-retrato|data-foto|perfil-desplegable|<dd>0,00<\/dd>/);
});

test('los desgloses ignoran valores ausentes y conservan la proporción medida', () => {
  assert.match(contexto.repartoPerfil({head:10,body:10,leg:null},{head:'Cabeza',body:'Cuerpo',leg:'Piernas'}), /50 %/);
  assert.doesNotMatch(contexto.repartoPerfil({head:10,body:10,leg:null},{head:'Cabeza',body:'Cuerpo',leg:'Piernas'}), /Piernas|NaN/);
  assert.match(contexto.repartoPerfil({head:null,body:0},{head:'Cabeza',body:'Cuerpo'}), /Desglose no disponible/);
});

test('la exploración escalona con las duraciones compartidas, solo transform y opacidad, y corta en la fila 12', () => {
  const animaciones = [];
  const filas = Array.from({length:20},()=>({animate:(frames,opciones)=>animaciones.push({frames,opciones})}));
  contexto.entrarExploracion(filas);
  assert.equal(animaciones.length, 20);
  assert.equal(animaciones[0].opciones.delay, 0);
  assert.equal(animaciones[12].opciones.delay, 12 * 28);
  assert.equal(animaciones[19].opciones.delay, 12 * 28);       // la cola no se alarga
  for (const a of animaciones) {
    assert.equal(a.opciones.duration, 240);
    assert.ok(a.frames.every(f => Object.keys(f).every(k => ['transform','opacity'].includes(k))));
    assert.match(a.opciones.easing, /^cubic-bezier/);
  }
});

test('teclado no anima la exploración y movimiento reducido conserva un fundido', () => {
  const animaciones = [], filas = [{animate:(frames,opciones)=>animaciones.push({frames,opciones})}];
  contexto.porTeclado = true;
  contexto.entrarExploracion(filas);
  assert.equal(animaciones.length, 0);
  contexto.porTeclado = false;
  contexto.movimientoReducido = true;
  contexto.entrarExploracion(filas);
  assert.equal(animaciones[0].opciones.duration, 150);
  assert.equal(animaciones[0].opciones.delay, 0);
  assert.ok(animaciones[0].frames.every(f => Object.keys(f).length === 1 && 'opacity' in f));
  contexto.movimientoReducido = false;
});


test('la foto del perfil va en su cartel: grafito para todos, dorado y con su sello para el campeón', () => {
  const normal = contexto.vistaPerfil(perfil());
  assert.match(normal, /class="perfil-retrato foto-cartel"><figure class="retrato" data-foto="Aalon Cruz" data-calidad="alta">/);
  assert.doesNotMatch(normal, /perfil-cinturon|foto-cartel oro/);
  const campeon = contexto.vistaPerfil(perfil({campeon:{clave:'Lightweight', division:'Ligero', interino:false}}));
  assert.match(campeon, /class="perfil-retrato foto-cartel oro"/);
  assert.match(campeon, /<p class="perfil-cinturon">Campeón peso ligero<\/p>/);
});

// El modal de una pelea del historial, con el octágono y el análisis de app.js
// y analisis.js simulados: aquí se prueba qué se le pide a cada uno y el orden.
const modal = vm.createContext({esc:vm.runInContext('esc', contexto), fechaExplorar:vm.runInContext('fechaExplorar', contexto), ico:()=>'<svg></svg>', pedidos:[],
  escenaJaula:(p, o) => { modal.pedidos.push(o); return `<div class="jaula" data-cifras="${o.cifras}"></div>`; },
  analisisContenido:p => '<div class="analisis-contenido">ANALISIS</div>',
  textoResultado:r => ({titulo:'Ganó ' + r.ganador, detalle:r.como}),
  resultadoReal:p => `<div class="resultado-real" data-acierto="${p.resultado.acierto ? 'si' : 'no'}">REAL</div>`});
vm.runInContext(explorar.slice(explorar.indexOf('function resultadoHistorialPelea('), explorar.indexOf('async function abrirPeleaHistorial(')), modal);

test('el modal pone el octágono arriba, las estadísticas abajo y el resultado después, aparte', () => {
  const base = {id:'h1', a:'Ana Arco', b:'Bia Bravo', es_titulo:false, p_a:null, p_b:null, metodo:null};
  const sinModelo = modal.vistaHistorialPelea({pelea:base, corte:{fecha:'2024-06-15', motivo:'Sin modelo de ese día.'},
    resultado:{ganador:'Bia Bravo', lado:'b', como:'decisión unánime', acierto:null}});
  assert.equal(modal.pedidos.at(-1).cifras, false);          // sin modelo no hay porcentajes inventados
  assert.equal(modal.pedidos.at(-1).resultado, false);       // ni la placa del resultado en la lona
  const [oct, stats, real] = ['class="jaula"', 'ANALISIS', 'Ganó Bia Bravo'].map(t => sinModelo.indexOf(t));
  assert.ok(oct >= 0 && oct < stats && stats < real, 'octágono, estadísticas y después el resultado');
  assert.match(sinModelo, /class="hist-seccion hist-final"><h3>Cómo terminó<\/h3>/);
  assert.match(sinModelo, /Sin modelo de ese día\./);
  assert.doesNotMatch(sinModelo, /estelar-titulo/);
  const conModelo = modal.vistaHistorialPelea({pelea:{...base, es_titulo:true, p_a:.6, p_b:.4, metodo:{}},
    corte:{fecha:'2024-06-15', modelo:'reentrenado'}, resultado:{ganador:'Ana Arco', lado:'a', acierto:true}});
  assert.equal(modal.pedidos.at(-1).cifras, true);
  assert.match(conModelo, /class="estelar hist-oct estelar-titulo"/);      // dorado si fue por el título
  assert.match(conModelo, /data-acierto="si">REAL/);
  assert.match(conModelo, /entrenado solo con las peleas anteriores/);
});

test('sin pelea reconstruible se dice por qué, y aun así cómo terminó', () => {
  const html = modal.vistaHistorialPelea({pelea:null, corte:{motivo:'La base no alcanza para antes de 2013.'},
    resultado:{ganador:'Ana Arco', lado:'a', como:'KO/TKO'}});
  assert.match(html, /La base no alcanza para antes de 2013\./);
  assert.match(html, /Ganó Ana Arco/);
});


test('cada fila del listado lleva su foto en el cartel; el campeón en dorado y un nombre compartido sin foto', () => {
  const normal = contexto.filaCatalogo({nombre:'Aaron Brink', id:'1234', peso:'Pesado', peleas:1});
  assert.match(normal, /data-id="1234"/);
  assert.match(normal, /class="catalogo-foto foto-cartel" aria-hidden="true"><figure class="retrato" data-foto="Aaron Brink" data-calidad="alta">/);
  const campeon = contexto.filaCatalogo({nombre:'Islam Makhachev', id:'44', peso:'Wélter', peleas:18,
    campeon:{clave:'Welterweight', division:'Peso welter', interino:false}});
  assert.match(campeon, /class="catalogo-fila catalogo-oro"/);
  assert.match(campeon, /catalogo-foto foto-cartel oro/);
  assert.match(campeon, /class="catalogo-cinturon">Campeón peso wélter</);
  const homonimo = contexto.filaCatalogo({nombre:'Mike Davis', id:null, homonimo:true, campeon:{clave:'Lightweight'}, peleas:null});
  assert.doesNotMatch(homonimo, /data-foto|catalogo-oro|catalogo-cinturon/);
});
