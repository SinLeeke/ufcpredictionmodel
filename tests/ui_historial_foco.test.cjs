const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Se ejecutan los manejadores reales sobre un DOM simulado, sin red ni base.
const raiz = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(raiz, 'webui/static/app.js'), 'utf8');
const explorar = fs.readFileSync(path.join(raiz, 'webui/static/explorar.js'), 'utf8');

function montar() {
  const documento = {activeElement:null, oyentes:{}, addEventListener(tipo, fn) {
    (this.oyentes[tipo] ||= []).push(fn);
  }};
  function nodo() {
    const clases = new Set();
    return {dataset:{}, inert:false, conectado:true, innerHTML:'',
      classList:{add:c => clases.add(c), remove:c => clases.delete(c), contains:c => clases.has(c)},
      querySelector:() => null, querySelectorAll:() => [], getAnimations:() => [],
      focus() { if (this.conectado && !this.inert) documento.activeElement = this; }};
  }
  const m = nodo(); m.classList.add('oculto');
  const cerrar = nodo(), cuerpo = nodo(), nombre = nodo(), volver = nodo();
  let botones, perfil;
  function renderizarPerfil() {
    if (botones) botones.forEach(b => { b.conectado = false; });
    botones = ['0', '1', '2'].map(hist => ({...nodo(), dataset:{hist}}));
    perfil = {...nodo(), querySelectorAll:s => s === '.hist-abrir' ? botones : [],
      querySelector:s => botones.find(b => s === `.hist-abrir[data-hist="${b.dataset.hist}"]`) || null};
  }
  renderizarPerfil();
  const $ = s => ({'#modal':m, '.modal-cerrar':cerrar, '#modal-cuerpo':cuerpo,
    '#perfil-vista':perfil, '#perfil-volver':volver})[s] || null;
  const raizDoc = {dataset:{}};
  const pendientes = [];
  const contexto = vm.createContext({document:documento, $, $$:() => [perfil, m], raizDoc,
    porTeclado:true, cargarFotos:() => {}, volverPeleadores:() => {}, esc:s => String(s ?? ''),
    api:() => new Promise(resolve => pendientes.push(resolve)),
    setTimeout:() => 1, clearTimeout:() => {}});
  vm.runInContext(explorar.slice(0, explorar.indexOf('async function cargarRankings(')), contexto);
  vm.runInContext(app.slice(app.indexOf('let focoAntesDelModal ='), app.indexOf('/* ============================== BARRA')), contexto);
  vm.runInContext(explorar.slice(explorar.indexOf('function activarPerfil('), explorar.indexOf('// Las filas del historial')), contexto);
  vm.runInContext(explorar.slice(explorar.indexOf('const cuerpoHistorial ='), explorar.indexOf('// La pelea llega como la estelar')), contexto);
  const EXP = vm.runInContext('EXP', contexto);
  EXP.perfil = {id:'f-prueba', nombre:'Peleador de prueba', historial:[0, 1, 2].map(i =>
    ({fecha:'2026-01-01', evento:'Evento de prueba', rival:`Rival ${i}`}))};
  contexto.activarPerfil();
  return {documento, m, cerrar, nombre, raizDoc, contexto, EXP,
    botones:() => botones,
    renderizar() { renderizarPerfil(); contexto.activarPerfil(); },
    escape() { documento.oyentes.keydown.forEach(fn => fn({key:'Escape'})); },
    async terminar() { pendientes.forEach(resolve => resolve({})); await new Promise(r => setImmediate(r)); }};
}

for (const reRender of [false, true]) {
  test(`Escape devuelve el foco al data-hist de origen${reRender ? ' después de re-renderizar el perfil' : ''}`, async () => {
    const d = montar();
    // El nombre era el foco anterior: el origen lo decide el clic de la fila.
    d.nombre.focus();
    const original = d.botones()[1];
    original.onclick();
    assert.equal(d.documento.activeElement, d.cerrar);
    assert.equal(d.m.classList.contains('oculto'), false);
    if (reRender) d.renderizar();
    d.escape();
    const vigente = d.botones()[1];
    assert.equal(d.documento.activeElement, vigente);
    assert.equal(vigente.dataset.hist, '1');
    if (reRender) assert.notEqual(vigente, original);
    assert.equal(d.m.classList.contains('oculto'), true);
    assert.equal(d.raizDoc.dataset.historialAbierto, undefined);
    assert.equal(d.EXP.pedidoHistorial, 2);
    await d.terminar();
  });
}

test('Cerrar y clic en el velo también resuelven la fila vigente del historial', async () => {
  for (const via of ['boton', 'velo']) {
    const d = montar();
    d.botones()[2].onclick(); d.renderizar();
    if (via === 'boton') d.cerrar.onclick();
    else d.m.onclick({target:{id:'modal'}});
    assert.equal(d.documento.activeElement, d.botones()[2]);
    await d.terminar();
  }
});

test('el modal común conserva la devolución automática cuando no se indica un destino', () => {
  const d = montar();
  d.nombre.focus();
  d.contexto.modal('<h2>Detalle de prueba</h2>');
  assert.equal(d.documento.activeElement, d.cerrar);
  d.escape();
  assert.equal(d.documento.activeElement, d.nombre);
});
