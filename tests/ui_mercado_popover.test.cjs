const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Se carga el app.js de producción (solo el tramo del detalle del mercado) en un
// contexto con un DOM mínimo simulado. Sin navegador: lo que se prueba es el
// cálculo de posición (función pura) y el ciclo abrir / Escape / clic afuera /
// foco, con elementos falsos que registran lo que el código les hace.
const fuente = fs.readFileSync(path.join(__dirname, '../webui/static/app.js'), 'utf8');
const ini = fuente.indexOf('// --- Posición del detalle del mercado');
const fin = fuente.indexOf("addEventListener('scroll', recolocarDetallesConsenso");
assert.ok(ini > 0 && fin > ini, 'no encuentro el tramo del popover en app.js');
const tramo = fuente.slice(ini, fin) + "addEventListener('scroll', recolocarDetallesConsenso, {});";

function crearEntorno({ ancho = 1440, alto = 900, rectBoton, caja = { width: 460, height: 300 } } = {}) {
  const oyentes = {};
  const foco = { actual: null };
  const crear = (extra = {}) => {
    const attrs = {};
    return Object.assign({
      dataset: {}, style: {}, attrs, hidden: false, isConnected: true,
      getAttribute: k => attrs[k], setAttribute(k, v) { attrs[k] = String(v); },
      toggleAttribute() {}, getAnimations: () => [], animate() {},
      focus() { foco.actual = this; },
      closest(sel) { return this._cierra?.(sel) ?? null; },
    }, extra);
  };
  const panel = crear({
    abierto: false,
    getBoundingClientRect() {
      // Al angostarse, el texto baja: el alto crece en proporción inversa.
      const w = parseFloat(this.style.width) || caja.width;
      return { width: w, height: Math.min(caja.height * caja.width / w, 5000) };
    },
    matches(s) { return s === ':popover-open' && this.abierto; },
    showPopover() { this.abierto = true; }, hidePopover() { this.abierto = false; },
  });
  const boton = crear({
    dataset: { consBoton: 'p1' },
    getBoundingClientRect: () => rectBoton,
  });
  boton.setAttribute('aria-controls', 'det');
  boton.setAttribute('aria-expanded', 'false');
  panel.hidden = true;
  const estado = { boton };   // el botón vigente: un refresco lo reemplaza por otro nodo
  const raiz = {
    querySelectorAll: () => [estado.boton],
    querySelector: sel => (sel.includes('aria-controls="det"') ? estado.boton : null),
  };
  const seccion = { querySelector: () => boton, contains: () => true };
  const doc = {
    documentElement: { clientWidth: ancho },
    get activeElement() { return foco.actual; },
    getElementById: id => (id === 'det' ? panel : null),
    querySelector: () => null,
    addEventListener: (t, f) => { (oyentes[t] ||= []).push(f); },
  };
  const ctx = vm.createContext({
    document: doc, window: { innerHeight: alto }, CSS: { escape: s => s },
    $: () => raiz, MERCADO: { abiertas: new Set(), hover: null }, porTeclado: false,
    reducir: () => true, EASE_OUT: 'ease', matchMedia: () => ({ matches: false }),
    addEventListener: (t, f) => { (oyentes['ventana:' + t] ||= []).push(f); }, requestAnimationFrame: f => f(), clearTimeout() {}, setTimeout() {},
    esperaConsenso: null, salidaConsenso: null, HTML_CONSENSO: new WeakMap(),
  });
  vm.runInContext(tramo, ctx);
  const emitir = (tipo, e) => (oyentes[tipo] || []).forEach(f => f(e));
  return { ctx, boton, panel, foco, emitir, seccion, estado, crear };
}

const dentro = (r, ancho, alto, margen = 8) =>
  r.left >= margen && r.top >= margen && r.left + r.ancho <= ancho - margen && r.top + r.altoMax <= alto - margen;
const calc = (ctx, ancla, panel, viewport) =>
  vm.runInContext('calcularPosicionPopover', ctx)({ ancla, panel, viewport });

const VISTAS = [{ ancho: 390, alto: 844 }, { ancho: 1440, alto: 900 }];
const rectEn = (v, x, y, w = 150, h = 44) => ({ left: x, top: y, width: w, height: h, bottom: y + h, right: x + w });
// Disparador en el borde izquierdo, el derecho, al pie de la pantalla y al centro.
const casos = v => ({
  izquierdo: rectEn(v, 0, 300), derecho: rectEn(v, v.ancho - 150, 300),
  pie: rectEn(v, v.ancho / 2 - 75, v.alto - 44), centro: rectEn(v, v.ancho / 2 - 75, 300),
  arriba: rectEn(v, v.ancho / 2 - 75, 0),
});

for (const v of VISTAS) {
  for (const [nombre, ancla] of Object.entries(casos(v))) {
    test(`el panel queda dentro de ${v.ancho}x${v.alto} con el disparador ${nombre}`, () => {
      const { ctx } = crearEntorno({ rectBoton: ancla });
      for (const alto of [120, 300, 700, 2000]) {
        const r = calc(ctx, ancla, { ancho: 460, alto }, v);
        assert.ok(dentro(r, v.ancho, v.alto), `${JSON.stringify(r)} alto=${alto}`);
        assert.ok(r.ancho <= v.ancho - 16);
        assert.ok(r.lado === 'abajo' || r.lado === 'arriba');
      }
    });
  }
}

test('a 390 px se angosta y, si no cabe debajo del disparador, se abre arriba', () => {
  const v = { ancho: 390, alto: 844 };
  const ancla = rectEn(v, 120, v.alto - 60);
  const { ctx } = crearEntorno({ rectBoton: ancla });
  const r = calc(ctx, ancla, { ancho: 460, alto: 300 }, v);
  assert.equal(r.ancho, 390 - 24);
  assert.equal(r.lado, 'arriba');
  assert.ok(r.top + 300 <= ancla.top, 'el panel queda por encima del disparador');
});

test('si cabe debajo se abre debajo, pegado al disparador', () => {
  const v = { ancho: 1440, alto: 900 };
  const ancla = rectEn(v, 600, 200);
  const { ctx } = crearEntorno({ rectBoton: ancla });
  const r = calc(ctx, ancla, { ancho: 460, alto: 300 }, v);
  assert.equal(r.lado, 'abajo');
  assert.equal(r.top, ancla.bottom + 5);
});

test('un panel más alto que cualquier lado se acota y se desplaza por dentro', () => {
  const v = { ancho: 390, alto: 844 };
  const ancla = rectEn(v, 100, 400);
  const { ctx } = crearEntorno({ rectBoton: ancla });
  const r = calc(ctx, ancla, { ancho: 460, alto: 3000 }, v);
  assert.ok(r.altoMax < 3000 && dentro(r, v.ancho, v.alto));
});

test('situarDetalleConsenso deja el panel real dentro de la ventana a 390 px', () => {
  const v = { ancho: 390, alto: 844 };
  for (const ancla of Object.values(casos(v))) {
    const { ctx, boton, panel } = crearEntorno({ ancho: v.ancho, alto: v.alto, rectBoton: ancla });
    vm.runInContext('situarDetalleConsenso', ctx)(boton, panel);
    const left = parseFloat(panel.style.left), top = parseFloat(panel.style.top);
    const w = parseFloat(panel.style.width), h = parseFloat(panel.style.maxHeight);
    assert.ok(left >= 8 && left + w <= v.ancho - 8, `x: ${left}+${w}`);
    assert.ok(top >= 8 && top + h <= v.alto - 8, `y: ${top}+${h}`);
  }
});

function abrirConClic(e) {
  const { ctx, boton, panel, foco, emitir, seccion } = e;
  const marcar = (obj, tipo) => { obj._cierra = sel => (sel.includes(tipo) ? obj : null); return obj; };
  marcar(boton, '[data-cons-boton]');
  emitir('click', { target: boton });
  return { ctx, boton, panel, foco, emitir, seccion };
}

test('el clic abre: aria-expanded, aria-controls, foco alcanzable y panel visible', () => {
  const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
  abrirConClic(e);
  assert.equal(e.boton.attrs['aria-expanded'], 'true');
  assert.equal(e.boton.getAttribute('aria-controls'), 'det');
  assert.equal(e.panel.hidden, false);
  assert.equal(e.panel.abierto, true);
  assert.match(fuente, /class="cons-detalle"[^>]*tabindex="0"/, 'el panel es alcanzable con Tab');
});

test('Escape cierra el detalle y devuelve el foco al disparador', () => {
  const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
  abrirConClic(e);
  e.foco.actual = e.panel;                  // el usuario tabuló hasta el panel
  e.panel._cierra = sel => (sel.includes('.consenso') ? e.seccion : null);
  e.emitir('keydown', { key: 'Escape' });
  assert.equal(e.boton.attrs['aria-expanded'], 'false');
  assert.equal(e.panel.hidden, true);
  assert.equal(e.foco.actual, e.boton);
});

test('un clic afuera cierra y, si no cae en algo enfocable, el foco vuelve al disparador', () => {
  const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
  abrirConClic(e);
  e.foco.actual = null;                     // el clic dejó el foco en <body>
  e.emitir('click', { target: { closest: () => null } });
  assert.equal(e.boton.attrs['aria-expanded'], 'false');
  assert.equal(e.panel.hidden, true);
  assert.equal(e.foco.actual, e.boton);
});

test('un clic dentro del panel no lo cierra', () => {
  const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
  abrirConClic(e);
  e.emitir('click', { target: { closest: sel => (sel === '.cons-detalle' ? e.panel : null) } });
  assert.equal(e.boton.attrs['aria-expanded'], 'true');
});

test('el scroll interno del panel no lo reposiciona y situar conserva scrollTop', () => {
  const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
  abrirConClic(e);
  let medidas = 0;
  const original = e.panel.getBoundingClientRect.bind(e.panel);
  e.panel.getBoundingClientRect = () => { medidas++; return original(); };
  e.panel.scrollTop = 140;
  // El scroll nace dentro del panel: ni se mide ni se toca el scroll.
  e.emitir('ventana:scroll', { target: { closest: sel => (sel === '.cons-detalle' ? e.panel : null) } });
  assert.equal(medidas, 0);
  assert.equal(e.panel.scrollTop, 140);
  // Un scroll de la página sí reposiciona, y el scroll interno sobrevive a la medición
  // (al quitar maxHeight el navegador lo deja en 0: se simula).
  e.panel.getBoundingClientRect = () => { e.panel.scrollTop = 0; return original(); };
  e.emitir('ventana:scroll', { target: { closest: () => null } });
  assert.equal(e.panel.scrollTop, 140);
});

test('tras un refresco que reemplaza el botón, Escape y clic afuera devuelven el foco al vigente', () => {
  for (const via of ['escape', 'clic']) {
    const e = crearEntorno({ rectBoton: rectEn({ ancho: 1440 }, 600, 200) });
    abrirConClic(e);
    // Refresco de cuotas: el innerHTML crea un nodo nuevo y el viejo se desconecta.
    const nuevo = e.crear({ dataset: { consBoton: 'p1' }, getBoundingClientRect: () => rectEn({ ancho: 1440 }, 600, 200) });
    nuevo.setAttribute('aria-controls', 'det');
    nuevo.setAttribute('aria-expanded', 'true');
    e.boton.isConnected = false;
    e.estado.boton = nuevo;
    e.foco.actual = null;
    if (via === 'escape') e.emitir('keydown', { key: 'Escape' });
    else e.emitir('click', { target: { closest: () => null } });
    assert.equal(e.foco.actual, nuevo, via);
    assert.equal(e.panel.hidden, true, via);
  }
});
