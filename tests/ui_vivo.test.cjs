const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const archivo = path.resolve(__dirname, '../webui/static/vivo.js');
const vista = require(archivo);
const punto = (segundo, pa = .6, a = -150) => ({t:`2026-10-04T00:00:${String(segundo).padStart(2, '0')}+00:00`, pa, pb:1 - pa, a, b:125});
const serie = (puntos, extra = {}) => ({tipo:'casa', casa:'Casa A', fuente:'odds_api', etiqueta:'Casa A', puntos, ...extra});
const pelea = (id = 'a|b') => ({pelea_id:id, a:{nombre:'Alpha'}, b:{nombre:'Beta'},
  estado:'en_curso', motivo_clave:'estimado', motivo:'Estimado: primera pelea pendiente.', cotizaciones:[]});
const paquete = (series = [], extra = {}) => ({activo:true, simulado:false,
  evento:{id:'evento-a', nombre:'UFC de prueba'}, actual:{...pelea(), series, incremental:false},
  peleas:[pelea()], mercado:{hay_cuotas:true, todas_caidas:false, con_error:[]},
  consultado:'2026-10-04T00:00:30+00:00', ...extra});

test('las actualizaciones incrementales conservan casas sin cambios y reemplazan el mismo instante', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([
    serie([punto(0), punto(10, .61)], {hasta:punto(20).t}),
    serie([punto(0, .55)], {casa:'Casa B', etiqueta:'Casa B', hasta:punto(20).t}),
  ]));
  const siguiente = vista.recibirPaquete(inicial, paquete([], {actual:{...pelea(), incremental:true,
    series:[serie([punto(10, .62), punto(25, .63)], {hasta:punto(30).t})]}}));
  const a = siguiente.series.get(vista.claveSerie(serie([])));
  assert.deepEqual(a.puntos.map(p => p.pa), [.6, .62, .63]);
  assert.equal(a.hasta, punto(30).t);
  assert.equal(siguiente.series.size, 2);
  assert.equal(siguiente.ultimo, punto(25).t);
  assert.deepEqual(inicial.series.get(vista.claveSerie(serie([]))).puntos.map(p => p.pa), [.6, .61]);
});

test('una serie incremental vacía actualiza hasta sin borrar el historial', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])]));
  const siguiente = vista.recibirPaquete(inicial, paquete([], {actual:{...pelea(), incremental:true,
    series:[serie([], {hasta:punto(30).t})]}}));
  assert.deepEqual([...siguiente.series.values()][0].puntos, [punto(0)]);
  assert.equal([...siguiente.series.values()][0].hasta, punto(30).t);
});

test('cambiar de pelea limpia las series aunque el servidor mande incremental por error', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])]));
  const siguiente = vista.recibirPaquete(inicial, paquete([], {actual:{...pelea('c|d'), incremental:true,
    series:[serie([punto(25, .4)], {casa:'Otra casa'})]}}));
  assert.equal(siguiente.series.size, 1);
  assert.equal([...siguiente.series.values()][0].casa, 'Otra casa');
  assert.equal(siguiente.pelea_id, 'c|d');
});

test('cambiar de evento o de simulación tampoco mezcla cuotas de la misma pareja', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])]));
  for (const cambio of [{evento:{id:'otro'}}, {simulado:true}]) {
    const siguiente = vista.recibirPaquete(inicial, paquete([], {actual:{...pelea(), incremental:true, series:[]}, ...cambio}));
    assert.equal(siguiente.series.size, 0);
    assert.equal(siguiente.ultimo, null);
  }
});

test('sin evento la sección queda en modo manual y elimina el cursor incremental anterior', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])]));
  const fin = vista.recibirPaquete(inicial, {activo:false, opciones:[]});
  assert.equal(fin.visible, true);
  assert.equal(fin.manual, true);
  assert.equal(fin.series.size, 0);
  assert.equal(vista.urlConsulta(fin), '/api/mercado/vivo');
  assert.match(vista.ayudaManual(fin), /No hay peleas con cuotas guardadas/);
  assert.equal(vista.prepararGrafico(fin.series), null);
});

test('la pelea elegida a mano se va llenando sin mezclarse con un evento real', () => {
  const manual = (series, incremental = false) => ({activo:false, opciones:[{pelea_id:'a|b', a:'Alpha', b:'Beta'}],
    actual:{pelea_id:'a|b', a:{nombre:'Alpha'}, b:{nombre:'Beta'}, cotizaciones:[{}], series, incremental},
    consultado:'2026-10-04T00:00:30+00:00'});
  const sinElegir = vista.recibirPaquete(vista.crearEstado(), {activo:false, opciones:[{pelea_id:'a|b', a:'Alpha', b:'Beta'}]});
  assert.match(vista.ayudaManual(sinElegir), /Elige una pelea/);
  const url = new URL(vista.urlConsulta(sinElegir, [], 'a|b'), 'http://127.0.0.1');
  assert.equal(url.searchParams.get('elegida'), 'a|b');
  assert.equal(url.searchParams.get('desde'), null);
  const uno = vista.recibirPaquete(sinElegir, manual([serie([punto(0)], {hasta:punto(0).t})]));
  const dos = vista.recibirPaquete(uno, manual([serie([], {hasta:punto(10).t})], true));
  assert.equal(dos.series.get(vista.claveSerie(serie([]))).puntos.length, 1);
  assert.equal(vista.prepararGrafico(dos.series).hasta, Date.parse(punto(10).t));
  const tres = vista.recibirPaquete(dos, manual([serie([punto(20, .65)])], true));
  assert.equal(tres.series.get(vista.claveSerie(serie([]))).puntos.length, 2);
  assert.equal(new URL(vista.urlConsulta(tres, [], 'a|b'), 'http://127.0.0.1').searchParams.get('desde'), punto(20).t);
  assert.match(vista.ayudaManual(tres, {encendido:false, disponible:true}), /EN VIVO está apagado/);
  assert.match(vista.ayudaManual(tres, {encendido:true, disponible:true}), /cada 10 s/);
  assert.match(vista.ayudaManual(tres, {}), /desde Betano/);
  // El mismo par durante un evento real arranca de cero.
  const real = vista.recibirPaquete(tres, {...paquete([serie([punto(5)])]), actual:{...pelea('a|b'), series:[serie([punto(5)])], incremental:true}});
  assert.equal(real.series.get(vista.claveSerie(serie([]))).puntos.length, 1);
});

test('un fallo conserva el paquete y las cifras con un aviso honesto y recuperación posterior', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])]));
  const fallo = vista.registrarFallo(inicial);
  assert.equal(fallo.paquete, inicial.paquete);
  assert.equal(fallo.series, inicial.series);
  assert.equal(fallo.visible, true);
  assert.match(vista.avisoMercado(fallo), /conservan los últimos datos/);
  assert.equal(vista.recibirPaquete(fallo, paquete()).error, null);
  assert.throws(() => vista.recibirPaquete(inicial, {}), /incompleta/);
});

test('la simulación disponible no muestra caída y los fallos reales conservan su aviso', () => {
  const simulado = vista.recibirPaquete(vista.crearEstado(), paquete([], {simulado:true,
    mercado:{hay_cuotas:true, todas_caidas:false, con_error:[]}}));
  assert.equal(vista.avisoMercado(simulado), '');
  assert.match(vista.avisoMercado(vista.registrarFallo(simulado)), /No pude actualizar/);
  const caidas = vista.recibirPaquete(vista.crearEstado(), paquete([], {
    mercado:{hay_cuotas:true, todas_caidas:true, con_error:['Fuente real']}}));
  assert.match(vista.avisoMercado(caidas), /ninguna fuente confirma datos recientes/);
});

test('la URL incremental codifica nombres exactos y las marcas locales para el evento', () => {
  const inicial = vista.recibirPaquete(vista.crearEstado(), paquete([serie([punto(0)])], {
    actual:{...pelea('alpha & uno|beta/otro'), series:[serie([punto(0)])], incremental:false},
  }));
  const url = new URL(vista.urlConsulta(inicial, ['alpha & uno|beta/otro']), 'http://127.0.0.1');
  assert.equal(url.searchParams.get('pelea_id'), 'alpha & uno|beta/otro');
  assert.equal(url.searchParams.get('desde'), punto(0).t);
  assert.deepEqual(JSON.parse(url.searchParams.get('terminadas')), ['alpha & uno|beta/otro']);
  assert.equal(url.searchParams.get('evento_id'), 'evento-a');
});

test('la serie conserva floats exactos, ordena instantes y nunca convierte null en cero', () => {
  const prob = .6222222222222222;
  const ordenados = vista.unirPuntos([], [punto(20, prob), punto(0, null), punto(10, .57), punto(30, 1), punto(40, 0)]);
  assert.equal(ordenados[1].pa, prob);
  assert.deepEqual(ordenados.map(p => p.t), [punto(10).t, punto(20).t, punto(30).t, punto(40).t]);
});

test('las cifras usan es-CL y la conversión de los ticks no altera la cuota de una casa', () => {
  assert.equal(vista.americana(-186), '−186');
  assert.equal(vista.americana(186), '+186');
  assert.equal(vista.porcentaje(.65), '65,0 %');
  assert.equal(vista.americana(null), '—');
  assert.equal(vista.probAmericana(.65), -186);
  assert.equal(vista.probAmericana(.35), 186);
  assert.equal(vista.probAmericana(.5), -100);
  for (const valor of [null, 0, 1, NaN]) assert.equal(vista.probAmericana(valor), null);
});

test('las horas del mercado se leen en formato de 24 horas', () => {
  const tarde = new Date(2026, 9, 4, 17, 5).toISOString();
  assert.equal(vista.hora(tarde), '17:05');
  assert.match(vista.fechaHora(tarde), /17:05/);
  assert.doesNotMatch(vista.fechaHora(tarde), /a\.?\s*m|p\.?\s*m/i);
});

test('el SVG mantiene escalones y termina en la última confirmación de la fuente', () => {
  const datos = serie([punto(0, .6), punto(10, .7)], {hasta:punto(20).t});
  const x = t => (t - Date.parse(punto(0).t)) / 1000;
  const y = p => p * 100;
  assert.equal(vista.trazoEscalones(datos, x, y), 'M0 60 H10 V70 H20');
  const grafico = vista.prepararGrafico(new Map([['a', datos]]));
  assert.equal(grafico.hasta, Date.parse(punto(20).t));
  assert.deepEqual(vista.valoresEn(grafico, Date.parse(punto(5).t))[0].punto, punto(0, .6));
  assert.deepEqual(vista.valoresEn(grafico, Date.parse(punto(10).t))[0].punto, punto(10, .7));
  assert.equal(vista.valoresEn(grafico, Date.parse(punto(25).t))[0].punto, null);
});

test('una sola observación tiene dominio visible y un historial vacío no inventa una línea', () => {
  const grafico = vista.prepararGrafico(new Map([['a', serie([punto(0)])]]));
  assert.ok(grafico.hasta > grafico.desde);
  assert.ok(grafico.maximo > grafico.minimo);
  assert.equal(vista.prepararGrafico(new Map()), null);
});

test('las mejores cuotas solo se marcan en casas y Polymarket aparece separado', () => {
  const filas = [{tipo:'casa', casa:'Casa <A>', fuente:'bfo', a:{americana:-150}, b:{americana:125}, mejor_a:true, visto:punto(0).t},
    {tipo:'mercado_prediccion', casa:'Polymarket', fuente:'polymarket', a:{americana:-135}, b:{americana:135}, mejor_a:true, visto:punto(0).t}];
  const casas = vista.tablaCuotas(filas, pelea(), 'casa');
  const prediccion = vista.tablaCuotas(filas, pelea(), 'mercado_prediccion');
  assert.match(casas, /Casa &lt;A&gt;/);
  assert.match(casas, /Mejor/);
  assert.doesNotMatch(casas, /Polymarket/);
  assert.match(prediccion, /Polymarket/);
  assert.doesNotMatch(prediccion, /vivo-mejor/);
});

test('una marca manual no inventa ganador y una resolución exige 1/0 exacto', () => {
  assert.equal(vista.resolucionMercado({...pelea(), motivo_clave:'manual'}), '');
  assert.equal(vista.resolucionMercado({...pelea(), resolucion:{ganador:'Alpha', a:.999, b:.001}}), '');
  const html = vista.resolucionMercado({...pelea(), resolucion:{ganador:'Alpha', a:1, b:0, fuente:'polymarket'}});
  assert.match(html, /Alpha · 100 %/);
  assert.match(html, /Polymarket/);
  assert.match(html, /No es un resultado oficial ni una probabilidad del modelo/);
});

// DOM mínimo para medir el ciclo real: no scrapea ni escribe en una base.
function navegador(responder, {oculto = false, guardadas = {}, S} = {}) {
  const nodos = new Map(), eventos = new Map(), consultas = [], tiempos = new Map();
  let idTemporizador = 0;
  function nodo(id) {
    if (!nodos.has(id)) nodos.set(id, {id, innerHTML:'', textContent:'', hidden:false, disabled:false,
      classList:{valores:new Set(id === 'vivo' ? ['oculto'] : []),
        add(clase) { this.valores.add(clase); }, remove(clase) { this.valores.delete(clase); },
        contains(clase) { return this.valores.has(clase); }, toggle(clase, activar) { activar ? this.valores.add(clase) : this.valores.delete(clase); }},
      addEventListener(tipo, fn) { eventos.set(`${id}:${tipo}`, fn); },
      querySelectorAll() { return []; }, setAttribute() {}, clientWidth:920,
      querySelector() { return {getBoundingClientRect:() => ({left:0, width:920})}; },
    });
    return nodos.get(id);
  }
  const document = {hidden:oculto, getElementById:nodo, addEventListener(tipo, fn) { eventos.set(tipo, fn); }};
  const contexto = vm.createContext({document, URLSearchParams, AbortController, ...(S ? {S} : {}),
    localStorage:{getItem:clave => guardadas[clave] || null, setItem:(clave, valor) => { guardadas[clave] = valor; },
      removeItem:clave => { delete guardadas[clave]; }},
    setTimeout:(fn, ms) => { tiempos.set(++idTemporizador, {fn, ms}); return idTemporizador; },
    clearTimeout:id => tiempos.delete(id),
    fetch:async url => { consultas.push(url); return responder(url); },
  });
  vm.runInContext(fs.readFileSync(archivo, 'utf8'), contexto);
  return {nodo, eventos, document, consultas, tiempos, guardadas};
}
const completar = () => new Promise(resolve => setImmediate(resolve));

test('el polling real no inicia con pestaña oculta y se reanuda con cadencia de 12 segundos', async () => {
  const dom = navegador(() => ({ok:true, json:async () => ({activo:false})}), {oculto:true});
  assert.equal(dom.consultas.length, 0);
  dom.document.hidden = false;
  dom.eventos.get('visibilitychange')();
  await completar();
  assert.equal(dom.consultas.length, 1);
  // Sin evento la sección se queda, con el gráfico vacío y el selector.
  assert.ok(!dom.nodo('vivo').classList.contains('oculto'));
  assert.equal(dom.nodo('vivo-elegir-caja').hidden, false);
  assert.match(dom.nodo('vivo-trazo').innerHTML, /Sin pelea elegida/);
  assert.deepEqual([...dom.tiempos.values()].map(t => t.ms), [12000]);
  dom.document.hidden = true;
  dom.eventos.get('visibilitychange')();
  assert.equal(dom.tiempos.size, 0);
});

test('elegir una pelea sin evento pide su línea y con EN VIVO se lee cada 5 segundos', async () => {
  const S = {vivo:false, origen:'betano'};
  const opciones = [{pelea_id:'a|b', a:'Alpha', b:'Beta', evento:'UFC de prueba', fecha:'2026-10-04'}];
  const dom = navegador(url => ({ok:true, json:async () => new URL(url, 'http://x').searchParams.get('elegida')
    ? {activo:false, opciones, actual:{pelea_id:'a|b', a:{nombre:'Alpha'}, b:{nombre:'Beta'}, evento:'UFC de prueba',
      cotizaciones:[], series:[serie([punto(0)], {hasta:punto(10).t})], incremental:false}}
    : {activo:false, opciones}}), {S});
  await completar();
  assert.match(dom.nodo('vivo-elegir').innerHTML, /Alpha vs Beta/);
  assert.match(dom.nodo('vivo-ayuda').innerHTML, /Elige una pelea/);
  dom.eventos.get('vivo-elegir:change')({target:{value:'a|b'}});
  await completar();
  assert.equal(new URL(dom.consultas.at(-1), 'http://x').searchParams.get('elegida'), 'a|b');
  assert.equal(dom.guardadas['ufc-mercado-elegida'], 'a|b');
  assert.match(dom.nodo('vivo-trazo').innerHTML, /vivo-linea/);
  assert.match(dom.nodo('vivo-ayuda').innerHTML, /EN VIVO está apagado/);
  assert.deepEqual([...dom.tiempos.values()].map(t => t.ms), [12000]);
  S.vivo = true;
  dom.eventos.get('vivo-refrescar:click')();
  await completar();
  assert.deepEqual([...dom.tiempos.values()].map(t => t.ms), [5000]);
  assert.match(dom.nodo('vivo-sello').innerHTML, /En vivo/);
});

test('el DOM muestra simulación inequívoca y conserva el cuerpo al fallar el siguiente pedido', async () => {
  let fallar = false;
  const dom = navegador(async () => {
    if (fallar) throw new Error('Sin conexión');
    return {ok:true, json:async () => paquete([], {simulado:true})};
  });
  await completar();
  assert.ok(!dom.nodo('vivo').classList.contains('oculto'));
  assert.equal(dom.nodo('vivo-sello').innerHTML, 'Datos simulados');
  const antes = dom.nodo('vivo-actual').innerHTML;
  fallar = true;
  dom.eventos.get('vivo-refrescar:click')();
  await completar();
  assert.equal(dom.nodo('vivo-actual').innerHTML, antes);
  assert.match(dom.nodo('vivo-aviso').innerHTML, /conservan los últimos datos/);
  assert.equal(dom.nodo('vivo-refrescar').disabled, false);
});

test('marcar y deshacer solo guarda IDs locales y solicita al backend la pelea orientada', async () => {
  const dom = navegador(url => {
    const parametros = new URL(url, 'http://127.0.0.1').searchParams;
    const manual = parametros.has('terminadas');
    return {ok:true, json:async () => paquete([], manual ? {actual:{...pelea('c|d'), a:{nombre:'Charlie'}, b:{nombre:'Delta'}, series:[]},
      peleas:[{...pelea(), estado:'terminada', motivo_clave:'manual', motivo:'Marcada por ti en este navegador.'}, pelea('c|d')]} : {})};
  });
  await completar();
  dom.eventos.get('vivo-marcar:click')();
  await completar();
  assert.match(dom.nodo('vivo-actual').innerHTML, /Charlie/);
  assert.match(dom.nodo('vivo-peleas').innerHTML, /Marcada por ti/);
  assert.match(dom.nodo('vivo-peleas').innerHTML, /Deshacer marca/);
  assert.equal(dom.nodo('vivo-deshacer').hidden, false);
  assert.deepEqual(Object.values(dom.guardadas).map(JSON.parse), [['a|b']]);
  const ultima = new URL(dom.consultas.at(-1), 'http://127.0.0.1');
  assert.deepEqual(JSON.parse(ultima.searchParams.get('terminadas')), ['a|b']);
  dom.eventos.get('vivo-deshacer:click')();
  await completar();
  assert.match(dom.nodo('vivo-actual').innerHTML, /Alpha/);
  assert.equal(dom.nodo('vivo-deshacer').hidden, true);
  assert.deepEqual(Object.values(dom.guardadas).map(JSON.parse), [[]]);
});

test('el gráfico del navegador conserva el orden categórico y el control lee el cambio seleccionado', async () => {
  const dom = navegador(() => ({ok:true, json:async () => paquete([
    serie([punto(0, .4), punto(10, .45)], {hasta:punto(20).t}),
    serie([punto(0, .7)], {casa:'Casa B', etiqueta:'Casa B', hasta:punto(20).t}),
  ])}));
  await completar();
  const dibujo = dom.nodo('vivo-trazo').innerHTML;
  assert.doesNotMatch(dibujo, /NaN/);
  assert.match(dibujo, /aria-labelledby="vivo-svg-titulo vivo-svg-descripcion"/);
  assert.match(dibujo, /stroke:var\(--vivo-color-1\)/);
  assert.equal(dom.nodo('vivo-tiempo').max, '1');
  dom.eventos.get('vivo-tiempo:input')({target:{value:'0'}});
  assert.match(dom.nodo('vivo-lectura').innerHTML, /40,0 %/);
  dom.eventos.get('vivo-tiempo:input')({target:{value:'1'}});
  assert.match(dom.nodo('vivo-lectura').innerHTML, /45,0 %/);
});

test('al recargar se aplican marcas del evento antes de mostrar una pelea anterior', async () => {
  const dom = navegador(url => ({ok:true, json:async () => new URL(url, 'http://127.0.0.1').searchParams.has('terminadas')
    ? paquete([], {actual:{...pelea('c|d'), a:{nombre:'Charlie'}, b:{nombre:'Delta'}, series:[]}}) : paquete()}), {
      guardadas:{'ufc-mercado-terminadas:["evento-a",false]':'["a|b"]',
        'ufc-mercado-terminadas:["otro-evento",false]':'["c|d"]'},
    });
  await completar();
  assert.equal(dom.consultas.length, 2);
  assert.match(dom.nodo('vivo-actual').innerHTML, /Charlie/);
  assert.deepEqual(JSON.parse(new URL(dom.consultas[1], 'http://127.0.0.1').searchParams.get('terminadas')), ['a|b']);
});

test('la lista permite corregir otra pelea con su ID exacto sin inventar resultado', async () => {
  const dom = navegador(() => ({ok:true, json:async () => paquete([], {
    peleas:[pelea(), {...pelea('c|d'), estado:'por_pelear'}],
  })}));
  await completar();
  assert.match(dom.nodo('vivo-peleas').innerHTML, /data-marcar="c\|d"/);
  dom.eventos.get('vivo-peleas:click')({target:{closest:() => ({dataset:{marcar:'c|d'}})}});
  await completar();
  assert.deepEqual(Object.values(dom.guardadas).map(JSON.parse), [['c|d']]);
  assert.deepEqual(JSON.parse(new URL(dom.consultas.at(-1), 'http://127.0.0.1').searchParams.get('terminadas')), ['c|d']);
  assert.doesNotMatch(dom.nodo('vivo-actual').innerHTML, /100 %/);
});
