const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'webui/static/index.html'), 'utf8');
const js = fs.readFileSync(path.join(raiz, 'webui/static/explorar.js'), 'utf8');
const css = fs.readFileSync(path.join(raiz, 'webui/static/explorar.css'), 'utf8');
const grupo = html.match(/<div id="catalogo-tramos"[^>]*>([\s\S]*?)<\/div>/);

function entorno(api) {
  const botones = [...grupo[1].matchAll(/<button ([^>]+)>([^<]+)<\/button>/g)].map(([, atributos, texto]) => ({
    dataset: {tramo: atributos.match(/data-tramo="([^"]*)"/)[1]}, texto,
    atributos: {'aria-pressed': atributos.match(/aria-pressed="([^"]*)"/)[1]},
    setAttribute(k, v) { this.atributos[k] = v; },
  }));
  const elementos = new Map();
  const $ = selector => {
    if (!elementos.has(selector)) elementos.set(selector, {
      value: '', textContent: '', innerHTML: '', disabled: false,
      classList: {contains: () => false, toggle() {}}, setAttribute() {},
      querySelector: () => null, querySelectorAll: () => [], insertAdjacentHTML() {},
    });
    return elementos.get(selector);
  };
  $('#catalogo-tramos').querySelectorAll = () => botones;
  const peticiones = [];
  const contexto = vm.createContext({$, clearTimeout, setTimeout, encodeURIComponent,
    porTeclado: true, abrirCatalogo() {}, filaCatalogo: p => `<li>${p.nombre}</li>`,
    miles: String, fotosAlVerse() {}, entrarExploracion() {},
    api: url => { peticiones.push(url); return api ? api(url) : Promise.resolve({total: 3, peleadores: [{nombre: 'Prueba'}]}); },
  });
  vm.runInContext(js.slice(js.indexOf('const EXP ='), js.indexOf('const pesosEs =')), contexto);
  vm.runInContext(js.slice(js.indexOf('async function buscarPeleadores('), js.indexOf('const medidaPerfil =')), contexto);
  return {contexto, EXP: vm.runInContext('EXP', contexto), $, botones, peticiones};
}

test('cinco botones nativos accesibles, con Todos seleccionado', () => {
  assert.match(grupo[0], /role="group" aria-label="Filtrar por apellido"/);
  const {botones} = entorno();
  assert.deepEqual(botones.map(b => b.texto), ['Todos', 'A–F', 'G–L', 'M–R', 'S–Z']);
  assert.equal((grupo[1].match(/type="button"/g) || []).length, 5);
  assert.deepEqual(botones.map(b => b.atributos['aria-pressed']), ['true', 'false', 'false', 'false', 'false']);
  assert.doesNotMatch(grupo[0], /tabindex="-1"|onkeydown/);
});

test('elegir tramo cambia aria-pressed, reinicia offset y conserva texto', async () => {
  const e = entorno();
  e.EXP.offset = 80;
  e.$('#buscar-peleador').value = 'Ángel';
  await e.botones[1].onclick();
  assert.deepEqual(e.botones.map(b => b.atributos['aria-pressed']), ['false', 'true', 'false', 'false', 'false']);
  assert.match(e.peticiones[0], /q=%C3%81ngel&offset=0&limite=40&tramo=A-F$/);
  assert.equal(e.$('#catalogo-total').textContent, '3 peleadores con apellido de la A a la F');
  await e.contexto.buscarPeleadores(true);
  assert.match(e.peticiones[1], /offset=1&limite=40&tramo=A-F$/);
  assert.equal(e.EXP.tramo, 'A-F');
  await e.botones[0].onclick();
  assert.match(e.peticiones[2], /offset=0&limite=40&tramo=$/);
  assert.equal(e.$('#catalogo-total').textContent, '3 peleadores encontrados');
});

test('cada tramo informa sus letras y respeta el singular', async () => {
  const e = entorno(() => Promise.resolve({total: 1, peleadores: []}));
  for (const boton of e.botones.slice(1)) {
    await boton.onclick();
    assert.equal(e.$('#catalogo-total').textContent,
      `1 peleador con apellido de la ${boton.dataset.tramo[0]} a la ${boton.dataset.tramo[2]}`);
  }
});

test('una respuesta atrasada no reemplaza el tramo nuevo', async () => {
  const resolver = [];
  const e = entorno(() => new Promise(resolve => resolver.push(resolve)));
  const viejo = e.botones[1].onclick();
  const nuevo = e.botones[2].onclick();
  resolver[1]({total: 2, peleadores: []});
  await nuevo;
  resolver[0]({total: 99, peleadores: []});
  await viejo;
  assert.equal(e.$('#catalogo-total').textContent, '2 peleadores con apellido de la G a la L');
  assert.equal(e.EXP.tramo, 'G-L');
});

test('el grupo contiene su scroll, deja espacio al foco y conserva botones compactos', () => {
  assert.match(css, /\.catalogo-tramos\{[^}]*max-width:100%[^}]*overflow-x:auto/);
  assert.match(css, /\.catalogo-tramos\{[^}]*justify-content:flex-start[^}]*padding:4px 4px 8px/);
  assert.match(css, /\.catalogo-tramos button\{[^}]*flex:0 0 auto;min-width:72px;min-height:44px;padding:8px 18px/);
  assert.match(css, /\.catalogo-tramos button\{[^}]*scroll-margin-top:var\(--alto-cab\)/);
  assert.match(css, /\.catalogo-tramos button\[aria-pressed="true"\]\{[^}]*border-bottom:4px solid var\(--marca\)/);
  assert.match(css, /\.catalogo-tramos button:focus-visible\{outline:2px solid var\(--marca\);outline-offset:2px\}/);
  assert.match(css, /#catalogo-total\{[^}]*\}/);
  assert.doesNotMatch(css.match(/#catalogo-total\{[^}]*\}/)[0], /border-top/);
  assert.match(css, /\.catalogo-lista\{[^}]*border-top:3px solid var\(--txt\)/);
});

test('presión con tokens, hover solo con puntero fino y teclado sin movimiento', () => {
  const reglas = css.match(/\.catalogo-tramos[^}]*\}/g).join('\n');
  assert.doesNotMatch(reglas, /\b\d*\.?\d+(?:ms|s)\b|animation:|box-shadow:|#[\da-f]{3,8}/i);
  assert.match(reglas, /transition:background-color var\(--dur-press\) var\(--ease-out\),color var\(--dur-press\) var\(--ease-out\),transform var\(--dur-press\) var\(--ease-out\)/);
  assert.match(css, /@media\(hover:hover\) and \(pointer:fine\)\{\s*\.catalogo-tramos button:hover\{/);
  assert.match(reglas, /:active:not\(:disabled\)\{transform:scale\(\.97\)\}/);
  assert.match(reglas, /:focus-visible\{transition:none\}/);
  assert.match(reglas, /:focus-visible:active:not\(:disabled\)\{transform:none\}/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)\{\s*\.catalogo-tramos button\{transition:background-color var\(--dur-press\) var\(--ease-out\),color var\(--dur-press\) var\(--ease-out\)\}\s*\.catalogo-tramos button:active:not\(:disabled\)\{transform:none\}/);
  assert.match(reglas, /color:var\(--sup\)/);
});

test('tinta y superficie superan 4,5:1 en claro y oscuro, también invertidos', () => {
  const estilo = fs.readFileSync(path.join(raiz, 'webui/static/style.css'), 'utf8');
  const luminancia = hex => {
    const canales = hex.match(/../g).map(c => parseInt(c, 16) / 255)
      .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return canales[0] * 0.2126 + canales[1] * 0.7152 + canales[2] * 0.0722;
  };
  const tintas = [...estilo.matchAll(/--txt:#([\da-f]{6})/g)].map(m => m[1]);
  const superficies = [...estilo.matchAll(/--sup:#([\da-f]{6})/g)].map(m => m[1]);
  assert.equal(tintas.length, superficies.length);
  assert.ok(tintas.length >= 2);
  tintas.forEach((tinta, i) => {
    const valores = [luminancia(tinta), luminancia(superficies[i])].sort((a, b) => b - a);
    assert.ok((valores[0] + 0.05) / (valores[1] + 0.05) >= 4.5);
  });
});
