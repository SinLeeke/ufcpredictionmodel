const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// «Fuente» de Comparar cuotas: el listbox propio, sin navegador ni red. Se carga
// el bloque de producción de explorar.js sobre un DOM mínimo simulado; las
// respuestas del servidor son de prueba y nada se escribe en disco ni en SQLite.
const raiz = path.resolve(__dirname, '..');
const explorar = fs.readFileSync(path.join(raiz, 'webui/static/explorar.js'), 'utf8');
const html = fs.readFileSync(path.join(raiz, 'webui/static/index.html'), 'utf8');
const iconos = fs.readFileSync(path.join(raiz, 'webui/static/iconos.js'), 'utf8');
const BLOQUE = explorar.slice(explorar.indexOf('/* =========================== COMPARAR CUOTAS'), explorar.lastIndexOf('rutaExplorar();'));
const CABEZA = explorar.slice(0, explorar.indexOf('async function cargarRankings('));

/* ----------------------------- DOM mínimo ----------------------------- */
// Solo lo que usa el bloque: atributos, hijos, clases, eventos con burbujeo y
// foco. El texto de un nodo armado con innerHTML se lee quitando las etiquetas.
function crearDom() {
  const porId = new Map();
  const documento = {activeElement:null, oyentes:{}};
  class Nodo {
    constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.attrs = new Map(); this.hijos = []; this.padre = null;
      this.oyentes = {}; this._html = ''; this.value = undefined; this.disabled = false;
      const clases = new Set(); this._clases = clases;
      this.classList = {add:(...c) => c.forEach(x => clases.add(x)), remove:(...c) => c.forEach(x => clases.delete(x)),
        contains:c => clases.has(c), toggle:(c, f = !clases.has(c)) => { if (f) clases.add(c); else clases.delete(c); return f; }}; }
    get id() { return this.attrs.get('id') || ''; }
    set id(v) { this.setAttribute('id', v); }
    get className() { return [...this._clases].join(' '); }
    set className(v) { this._clases.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => this._clases.add(c)); }
    setAttribute(k, v) { this.attrs.set(k, String(v)); if (k === 'id') porId.set(String(v), this); }
    getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
    hasAttribute(k) { return this.attrs.has(k); }
    removeAttribute(k) { this.attrs.delete(k); }
    toggleAttribute(k, f = !this.attrs.has(k)) { if (f) this.attrs.set(k, ''); else this.attrs.delete(k); return f; }
    append(...ns) { ns.forEach(n => { n.padre = this; this.hijos.push(n); }); }
    appendChild(n) { this.append(n); return n; }
    replaceChildren(...ns) { this.hijos = []; this._html = ''; this.append(...ns); }
    insertAdjacentHTML(_donde, h) { const n = new Nodo('span'); n.innerHTML = h; this.append(n); }
    set innerHTML(h) { this.hijos = []; this._html = String(h); }
    get innerHTML() { return this._html; }
    set textContent(t) { this.hijos = []; this._html = String(t).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
    get textContent() {
      if (this.hijos.length) return this.hijos.map(h => h.textContent).join('');
      return this._html.replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    }
    contains(n) { for (let x = n; x; x = x.padre) if (x === this) return true; return false; }
    addEventListener(t, fn) { (this.oyentes[t] ||= []).push(fn); }
    focus() {
      if (documento.activeElement === this) return;
      const antes = documento.activeElement; documento.activeElement = this;
      if (antes) antes.disparar('blur', {burbujea:false});
      this.disparar('focus', {burbujea:false});
    }
    disparar(tipo, extra = {}) {
      const ev = {type:tipo, target:this, key:undefined, altKey:false, ctrlKey:false, metaKey:false, defaultPrevented:false,
        preventDefault() { this.defaultPrevented = true; }, ...extra};
      for (let x = this; x; x = ev.burbujea === false ? null : (x.padre || (x === documento ? null : documento))) {
        (x.oyentes[tipo] || []).forEach(fn => fn(ev));
        if (x === documento) break;
      }
      return ev;
    }
  }
  documento.oyentes = {};
  documento.addEventListener = (t, fn) => { (documento.oyentes[t] ||= []).push(fn); };
  documento.createElement = tag => new Nodo(tag);
  documento.getElementById = id => porId.get(id) || null;
  documento.disparar = (tipo, extra = {}) => { const ev = {type:tipo, ...extra}; (documento.oyentes[tipo] || []).forEach(fn => fn(ev)); };
  // El marcado de la sección tal como está en index.html (lo comprueba otro test).
  const nodo = (tag, id, padre) => { const n = new Nodo(tag); n.id = id; if (padre) padre.append(n); return n; };
  const seccion = nodo('section', 'caja-cuotas-prueba');
  const rotulo = nodo('label', 'lbl-fuente-cuotas', seccion);
  const sel = nodo('div', 'fuente-sel', seccion);
  const combo = nodo('div', 'fuente-cuotas', sel);
  for (const [k, v] of Object.entries({role:'combobox', tabindex:'0', 'aria-haspopup':'listbox', 'aria-expanded':'false',
    'aria-controls':'fuente-cuotas-lista', 'aria-labelledby':'lbl-fuente-cuotas'})) combo.setAttribute(k, v);
  const lista = nodo('div', 'fuente-cuotas-lista', sel);
  lista.setAttribute('role', 'listbox');
  for (const id of ['btn-consultar-cuotas', 'btn-historial-cuotas', 'cuotas-estado', 'cuotas-lista', 'cuotas-historial'])
    nodo(id.startsWith('btn') ? 'button' : 'div', id, seccion);
  // `$` como querySelector: los id directos salen del registro; lo demás
  // (#cuotas-detalle ul, ids que crea innerHTML) son nodos de relleno estables.
  const relleno = new Map();
  const $ = s => {
    if (/^#[\w-]+$/.test(s) && porId.has(s.slice(1))) return porId.get(s.slice(1));
    if (!relleno.has(s)) relleno.set(s, new Nodo('div'));
    return relleno.get(s);
  };
  return {documento, $, combo, lista, rotulo, sel, afuera:nodo('div', 'afuera')};
}

const fuente = (clave, nombre, tipo, extra = {}) => ({clave, nombre, tipo, activa:true, motivo:null,
  ultimo_ok:'2026-10-04T17:05:00+00:00', ...extra});
const ESTADO = {hay_cuotas:true, en_vivo:false, fuentes:[
  fuente('simulada', 'Simulada', 'casa'),
  fuente('polymarket', 'Polymarket', 'mercado_prediccion', {activa:false, motivo:'Sin eventos de UFC abiertos', ultimo_ok:null}),
  fuente('odds_api', 'The Odds API', 'casa', {activa:false, motivo:'Falta ODDS_API_KEY', ultimo_ok:null}),
  fuente('bfo', 'BestFightOdds', 'casa'),
  fuente('betano', 'Betano', 'casa'),
]};
const CUOTAS_POLY = {snapshot:'s-poly', proveedor:'polymarket', tipo:'mercado_prediccion', capturado:'2026-10-04T17:00:00+00:00',
  actualizado:'2026-10-04T16:58:00+00:00', cache:true, desactualizado:false, carteleras:[],
  eventos:[{id:'ev1', titulo:'UFC de prueba', fecha:'2026-10-11', fuente:'polymarket',
    peleas:[{a:'Alpha', b:'Beta', casas:{polymarket:{casa:'Polymarket', a:1.6, b:2.4}}}]}]};

// Monta el bloque con un servidor simulado. `respuestas` decide qué devuelve
// cada URL; si devuelve un Error, la llamada falla como api() de la app.
async function montar(respuestas) {
  const dom = crearDom();
  const pedidos = [];
  const api = async url => {
    pedidos.push(url);
    const r = respuestas(url);
    if (r instanceof Error) throw r;
    return JSON.parse(JSON.stringify(r));
  };
  const contexto = vm.createContext({document:dom.documento, $:dom.$, $$:() => [], api, post:async () => ({}),
    irA:() => {}, fmt:(x, d) => Number(x).toFixed(d).replace('.', ','),
    esc:s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    insigniasIdentidad:() => ''});
  vm.runInContext(iconos, contexto);
  vm.runInContext(CABEZA + BLOQUE, contexto);
  await new Promise(r => setImmediate(r));
  const opciones = () => dom.lista.hijos;
  const tecla = (key, extra = {}) => dom.combo.disparar('keydown', {key, ...extra});
  const activa = () => dom.combo.getAttribute('aria-activedescendant');
  return {...dom, pedidos, opciones, tecla, activa, contexto};
}
const estadoOk = url => url === '/api/mercado/estado' ? ESTADO
  : url.startsWith('/api/cuotas?') ? CUOTAS_POLY : new Error('URL inesperada ' + url);

test('el marcado de «Fuente» es un combobox APG con su listbox y la etiqueta asociada', () => {
  const seccion = html.slice(html.indexOf('<section class="caja caja-cuotas"'), html.indexOf('</section>', html.indexOf('caja-cuotas')));
  assert.doesNotMatch(seccion, /<select id="fuente-cuotas"/);
  assert.match(seccion, /<label id="lbl-fuente-cuotas">Fuente<\/label>/);
  const combo = seccion.match(/<div id="fuente-cuotas"[^>]*>/s)[0];
  for (const attr of ['role="combobox"', 'tabindex="0"', 'aria-haspopup="listbox"', 'aria-expanded="false"',
    'aria-controls="fuente-cuotas-lista"', 'aria-labelledby="lbl-fuente-cuotas"']) assert.ok(combo.includes(attr), attr);
  assert.match(seccion, /<div id="fuente-cuotas-lista"[^>]*role="listbox"[^>]*aria-labelledby="lbl-fuente-cuotas"/);
  // La nota nombra las cuatro fuentes y no llama casa a Polymarket.
  assert.match(seccion, /Polymarket es un mercado\s+de predicción, no una casa/);
  for (const n of ['Betano', 'BestFightOdds', 'The Odds API', 'Polymarket']) assert.ok(seccion.includes(n), n);
});

test('con el estado de las 4 fuentes (+ simulada) hay exactamente 4 opciones en orden, cada una con su estado', async () => {
  const d = await montar(estadoOk);
  assert.deepEqual(d.pedidos, ['/api/mercado/estado']);
  const ops = d.opciones();
  assert.deepEqual(ops.map(o => o.getAttribute('data-clave')), ['betano', 'bfo', 'odds_api', 'polymarket']);
  ops.forEach(o => {
    assert.equal(o.getAttribute('role'), 'option');
    assert.ok(o.hasAttribute('aria-selected'));
    assert.match(o.textContent, /Activa|Inactiva/);
  });
  assert.match(ops[0].textContent, /Casa de apuestas/);
  assert.match(ops[0].textContent, /Activa · último OK /);
  assert.match(ops[2].textContent, /Inactiva · sin datos aún · Falta ODDS_API_KEY/);
  const poly = ops[3];
  assert.match(poly.textContent, /Mercado de predicción/);
  assert.doesNotMatch(poly.textContent, /casa/i);
  assert.doesNotMatch([...poly.attrs.values()].join(' ') + poly.className, /casa/i);
  assert.doesNotMatch(poly.textContent, /simulada/i);
  // BestFightOdds sigue siendo la elegida al abrir la página, como con el <select> viejo.
  assert.equal(d.opciones()[1].getAttribute('aria-selected'), 'true');
  assert.match(d.combo.textContent, /BestFightOdds/);
});

test('teclado: abre con ↓, mueve con ↓/↑/Inicio/Fin, elige con Enter, Escape no cambia y la letra salta', async () => {
  const d = await montar(estadoOk);
  const id = c => `fuente-cuotas-lista-${c}`;
  d.combo.focus();
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.activa(), null);

  assert.ok(d.tecla('ArrowDown').defaultPrevented);
  assert.equal(d.combo.getAttribute('aria-expanded'), 'true');
  assert.equal(d.activa(), id('bfo'));                 // abre sobre la elegida
  d.tecla('ArrowDown'); assert.equal(d.activa(), id('odds_api'));
  d.tecla('ArrowUp'); d.tecla('ArrowUp'); assert.equal(d.activa(), id('betano'));
  d.tecla('ArrowUp'); assert.equal(d.activa(), id('betano'));   // no da la vuelta
  d.tecla('End'); assert.equal(d.activa(), id('polymarket'));
  d.tecla('Home'); assert.equal(d.activa(), id('betano'));
  d.tecla('PageDown'); assert.equal(d.activa(), id('polymarket'));
  assert.ok(d.opciones()[3].classList.contains('activa'));

  d.tecla('Enter');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.activa(), null);
  assert.deepEqual(d.opciones().map(o => o.getAttribute('aria-selected')), ['false', 'false', 'false', 'true']);
  assert.match(d.combo.textContent, /Polymarket.*Mercado de predicción/);

  // Escape cierra sin cambiar y el foco sigue en el combobox.
  d.tecla('ArrowDown'); d.tecla('Home');
  assert.equal(d.activa(), id('betano'));
  d.tecla('Escape');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.opciones()[3].getAttribute('aria-selected'), 'true');
  assert.equal(d.documento.activeElement, d.combo);

  // Letra tecleada: abre y salta; la misma letra recorre las que empiezan igual.
  d.tecla('t');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'true');
  assert.equal(d.activa(), id('odds_api'));
  d.tecla('Escape');
  d.tecla('ArrowDown'); d.tecla('Home');
  d.tecla('b'); assert.equal(d.activa(), id('bfo'));
  d.tecla('b'); assert.equal(d.activa(), id('betano'));

  // Espacio elige (una flecha antes termina la búsqueda por letras); Tab elige
  // y no retiene el foco; Alt+↓ abre.
  d.tecla('ArrowDown'); d.tecla('ArrowUp');
  d.tecla(' ');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.opciones()[0].getAttribute('aria-selected'), 'true');
  d.tecla('ArrowDown', {altKey:true});
  assert.equal(d.combo.getAttribute('aria-expanded'), 'true');
  d.tecla('ArrowDown');
  assert.equal(d.tecla('Tab').defaultPrevented, false);
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.opciones()[1].getAttribute('aria-selected'), 'true');
});

test('el puntero: clic abre y elige; clic afuera cierra sin cambiar', async () => {
  const d = await montar(estadoOk);
  d.combo.disparar('click');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'true');
  assert.ok(d.sel.hasAttribute('data-abierta'));
  d.opciones()[0].disparar('click');
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.equal(d.opciones()[0].getAttribute('aria-selected'), 'true');
  d.combo.disparar('click');
  d.opciones()[3].disparar('pointermove');
  d.documento.disparar('pointerdown', {target:d.afuera});
  assert.equal(d.combo.getAttribute('aria-expanded'), 'false');
  assert.ok(!d.sel.hasAttribute('data-abierta'));
  assert.equal(d.opciones()[0].getAttribute('aria-selected'), 'true');
});

test('elegir Polymarket y consultar pide su proveedor y el rótulo pasa a «Mercado para esta cartelera»', async () => {
  const d = await montar(estadoOk);
  d.combo.focus(); d.tecla('End'); d.tecla('Enter');
  await d.$('#btn-consultar-cuotas').onclick();
  assert.ok(d.pedidos.includes('/api/cuotas?proveedor=polymarket'));
  assert.ok(!d.pedidos.includes('/api/cuotas/configuracion'));
  const detalle = d.$('#cuotas-detalle').innerHTML;
  assert.match(detalle, /Mercado para esta cartelera/);
  assert.doesNotMatch(detalle, /Casa para esta cartelera/);
  assert.match(d.$('#cobertura-cuotas-0').textContent, /^Este mercado cubre/);
  // Se lee de lo que la app ya tiene: usa `actualizado` y no finge una consulta.
  const estado = d.$('#cuotas-estado').textContent;
  assert.match(estado, /Polymarket · última cuota vista/);
  assert.doesNotMatch(estado, /consulta completada/);
});

test('The Odds API sin clave mantiene el aviso y no consulta las cuotas', async () => {
  const d = await montar(url => url === '/api/cuotas/configuracion' ? {odds_api_configurada:false} : estadoOk(url));
  d.combo.focus(); d.tecla('t'); d.tecla('Enter');
  await d.$('#btn-consultar-cuotas').onclick();
  assert.ok(d.pedidos.includes('/api/cuotas/configuracion'));
  assert.ok(!d.pedidos.some(u => u.startsWith('/api/cuotas?')));
  assert.match(d.$('#cuotas-estado').textContent, /The Odds API requiere una cuenta gratuita/);
});

test('Betano y Polymarket separan el estado con un solo punto y omiten el aviso de captura', async () => {
  for (const proveedor of ['betano', 'polymarket']) {
    for (const desactualizado of [false, true]) {
      const cuotas = {...CUOTAS_POLY, proveedor, desactualizado, cartelera_conservada:false};
      const d = await montar(url => url.startsWith('/api/cuotas?') ? cuotas : estadoOk(url));
      // Se fuerza la terminación de es-CL para cubrirla también en otros sistemas.
      vm.runInContext("Date.prototype.toLocaleString = () => '04-10-2026, 10:46:45 p. m.'", d.contexto);
      d.combo.focus(); d.tecla(proveedor === 'betano' ? 'Home' : 'End'); d.tecla('Enter');
      await d.$('#btn-consultar-cuotas').onclick();
      const texto = d.$('#cuotas-estado').textContent;
      assert.doesNotMatch(texto, /\.\./);
      assert.match(texto, /\. Se lee de lo que la app ya tiene/);
      assert.doesNotMatch(texto, /solo conserva precios|cartelera anunciada/);
      assert.equal(texto.includes('puede estar desactualizada'), desactualizado);
    }
  }
});

test('las capturas de BFO y The Odds API conservan el aviso de cartelera faltante', async () => {
  for (const proveedor of ['bfo', 'odds_api']) {
    const cuotas = {...CUOTAS_POLY, proveedor, cartelera_conservada:false};
    const d = await montar(url => url.startsWith('/api/cuotas?') ? cuotas
      : url === '/api/cuotas/configuracion' ? {odds_api_configurada:true} : estadoOk(url));
    if (proveedor === 'odds_api') { d.combo.focus(); d.tecla('t'); d.tecla('Enter'); }
    await d.$('#btn-consultar-cuotas').onclick();
    assert.match(d.$('#cuotas-estado').textContent, /Esta captura solo conserva precios; no tiene la cartelera anunciada/);
  }
});

test('el combobox cerrado abrevia la hora de hoy y la fecha anterior; las opciones conservan el detalle', async () => {
  const hoy = new Date(); hoy.setHours(22, 46, 45, 0);
  const ayer = new Date(hoy); ayer.setDate(ayer.getDate() - 1);
  for (const fecha of [hoy, ayer]) {
    const estado = {fuentes:[fuente('bfo', 'BestFightOdds', 'casa', {
      ultimo_ok:fecha.toISOString(), motivo:'Detalle completo de la fuente'})]};
    const d = await montar(() => estado);
    const esperado = fecha === hoy
      ? fecha.toLocaleTimeString('es-CL', {hour:'2-digit', minute:'2-digit', hourCycle:'h23'})
      : fecha.toLocaleDateString('es-CL', {day:'2-digit', month:'2-digit', year:'2-digit'});
    assert.equal(d.combo.hijos[1].textContent, `Casa de apuestas · Activa · ${esperado}`);
    assert.doesNotMatch(d.combo.textContent, /último OK|Detalle completo|p\. m\./);
    assert.match(d.opciones()[0].textContent, /último OK .*Detalle completo de la fuente/);
  }
  const d = await montar(estadoOk);
  d.combo.focus(); d.tecla('End'); d.tecla('Enter');
  assert.equal(d.combo.hijos[1].textContent, 'Mercado de predicción · Inactiva');
  assert.match(d.opciones()[3].textContent, /Sin eventos de UFC abiertos/);
});

test('una casa sigue diciendo «Casa para esta cartelera»', async () => {
  const bfo = {...CUOTAS_POLY, proveedor:'bfo', tipo:'casa', cache:false,
    eventos:[{...CUOTAS_POLY.eventos[0], peleas:[{a:'Alpha', b:'Beta', casas:{fanduel:{casa:'FanDuel', a:1.6, b:2.4}}}]}]};
  const d = await montar(url => url.startsWith('/api/cuotas?') ? bfo : estadoOk(url));
  await d.$('#btn-consultar-cuotas').onclick();
  assert.ok(d.pedidos.includes('/api/cuotas?proveedor=bfo'));
  assert.match(d.$('#cuotas-detalle').innerHTML, /Casa para esta cartelera/);
  assert.match(d.$('#cuotas-estado').textContent, /consulta completada/);
});

test('si /api/mercado/estado falla quedan BestFightOdds y The Odds API con estado desconocido', async () => {
  const d = await montar(url => url === '/api/mercado/estado' ? new Error('HTTP 502') : estadoOk(url));
  const ops = d.opciones();
  assert.deepEqual(ops.map(o => o.getAttribute('data-clave')), ['bfo', 'odds_api']);
  ops.forEach(o => assert.match(o.textContent, /Estado desconocido/));
  assert.equal(ops[0].getAttribute('aria-selected'), 'true');
});

test('las capturas guardadas rotulan las cuatro fuentes, también con el nombre viejo de The Odds API', async () => {
  const capturas = ['betano', 'bfo', 'odds-api', 'odds_api', 'polymarket'].map((proveedor, i) =>
    ({snapshot:'s' + i, proveedor, capturado:'2026-10-04T17:00:00+00:00'}));
  const d = await montar(url => url === '/api/cuotas/historial' ? {capturas} : estadoOk(url));
  await d.$('#btn-historial-cuotas').onclick();
  const h = d.$('#cuotas-historial').innerHTML;
  for (const n of ['Betano ·', 'BestFightOdds ·', 'Polymarket ·']) assert.ok(h.includes(n), n);
  assert.equal((h.match(/The Odds API ·/g) || []).length, 2);
  assert.doesNotMatch(h, />(?:betano|polymarket|odds-api|odds_api) ·/);
});

test('CSS: combobox, listbox y desplegables nativos rectos, sin sombra y con la opción resaltada explícita', () => {
  const css = fs.readFileSync(path.join(raiz, 'webui/static/explorar.css'), 'utf8');
  const regla = sel => { const m = css.match(new RegExp('(?:^|\\n)' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}')); assert.ok(m, sel); return m[1]; };
  for (const sel of ['.fuente-combo', '.fuente-lista', '.caja-cuotas select']) {
    assert.match(regla(sel), /border-radius:0/, sel);
    assert.match(regla(sel), /box-shadow:none/, sel);
  }
  assert.match(regla('.fuente-op.activa'), /background:var\(--txt\);color:var\(--bg\)/);
  assert.match(regla('.caja-cuotas option:checked'), /background:var\(--txt\);color:var\(--bg\)/);
  for (const propiedad of ['min-width:0', 'white-space:nowrap', 'overflow:hidden', 'text-overflow:ellipsis'])
    assert.ok(regla('.fuente-combo-estado').includes(propiedad), propiedad);
  assert.match(css, /:root\[data-tema="oscuro"\] \.caja-cuotas select\{color-scheme:dark\}/);
  // Duraciones compartidas y nada de movimiento con "menos movimiento".
  assert.match(regla('.fuente-lista'), /var\(--dur-salida\)/);
  assert.match(css, /\.fuente-sel\[data-abierta\] \.fuente-lista\{[^}]*var\(--dur-entrada\)/);
  assert.match(css, /prefers-reduced-motion:reduce\)\{\s*\.fuente-lista,\.fuente-sel\[data-abierta\] \.fuente-lista\{translate:none\}/);
});

test('las peleas descartadas por precio extremo se dicen en el estado, no desaparecen en silencio', async () => {
  const cuotas = {...CUOTAS_POLY, proveedor:'betano', descartadas:[{a:'X', b:'Y', motivo:'cuota > 50'}, {a:'Z', b:'W', motivo:'cuota > 50'}]};
  const d = await montar(url => url.startsWith('/api/cuotas?') ? cuotas : estadoOk(url));
  d.combo.focus(); d.tecla('Home'); d.tecla('Enter');
  await d.$('#btn-consultar-cuotas').onclick();
  assert.match(d.$('#cuotas-estado').textContent, /2 peleas sin cuota utilizable: precio demasiado extremo para el predictor/);
  const una = {...cuotas, descartadas:[cuotas.descartadas[0]]};
  const e = await montar(url => url.startsWith('/api/cuotas?') ? una : estadoOk(url));
  await e.$('#btn-consultar-cuotas').onclick();
  assert.match(e.$('#cuotas-estado').textContent, /1 pelea sin cuota utilizable/);
  // Sin descartadas no se añade nada.
  const f = await montar(estadoOk);
  await f.$('#btn-consultar-cuotas').onclick();
  assert.doesNotMatch(f.$('#cuotas-estado').textContent, /sin cuota utilizable/);
});

test('si se descartan todas las peleas no dice «no hay eventos»', async () => {
  const cuotas = {...CUOTAS_POLY, proveedor:'betano', eventos:[], carteleras:[], descartadas:[{a:'X', b:'Y', motivo:'cuota > 50'}]};
  const d = await montar(url => url.startsWith('/api/cuotas?') ? cuotas : estadoOk(url));
  d.combo.focus(); d.tecla('Home'); d.tecla('Enter');
  await d.$('#btn-consultar-cuotas').onclick();
  assert.match(d.$('#cuotas-estado').textContent, /Se descartaron todas las peleas de la captura \(1 pelea\)/);
  const lista = d.$('#cuotas-lista').innerHTML;
  assert.match(lista, /se descartaron por tener un precio demasiado extremo/);
  assert.doesNotMatch(lista, /No hay eventos/);
  // Sin descartadas y sin eventos se conserva el mensaje de siempre.
  const v = await montar(url => url.startsWith('/api/cuotas?') ? {...cuotas, descartadas:[]} : estadoOk(url));
  await v.$('#btn-consultar-cuotas').onclick();
  assert.match(v.$('#cuotas-lista').innerHTML, /No hay eventos con cuotas disponibles/);
});

test('CSS: la opción elegida (regla roja, sin invertir) se distingue de la resaltada y el chevrón transiciona rotate y translate', () => {
  const css = fs.readFileSync(path.join(raiz, 'webui/static/explorar.css'), 'utf8');
  const regla = sel => { const m = css.match(new RegExp('(?:^|\\n)' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}')); assert.ok(m, sel); return m[1]; };
  const elegida = regla('.fuente-op[aria-selected="true"]');
  assert.match(elegida, /border-left-color:var\(--marca\)/);
  assert.doesNotMatch(elegida, /background|box-shadow/);
  assert.match(regla('.fuente-op'), /border-left:4px solid transparent/);
  assert.match(regla('.fuente-op'), /background:var\(--sup\)/);
  assert.match(regla('.fuente-combo::after'), /transition:rotate var\(--dur-entrada\) var\(--ease-out\),translate var\(--dur-entrada\) var\(--ease-out\)/);
});
