/* Ejecutar: node tests/test_analisis.js. Contratos de datos del análisis UI. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const contexto = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../webui/static/analisis.js'), 'utf8'), contexto);
const pintar = contexto.analisisPelea;
const base = { id: '1', a: 'Peleador A', b: 'Peleador B', p_a: .6, p_b: .4,
  ci_a: [.45, .73], metodo: { 'KO/TKO': .5, Submission: .2, Decision: .3 } };
const seis = { A_KO: .3, A_SUB: .1, A_DEC: .2, B_KO: .15, B_SUB: .1, B_DEC: .15 };

let html = pintar({ ...base, probabilidades_metodo: seis,
  metodo_hist_a: { 'KO/TKO': .5, Submission: .3, Decision: .2 },
  metodo_hist_b: { 'KO/TKO': .2, Submission: .2, Decision: .6 },
  metodo_hist_fuente_a: 'UFCStats' }, true);
assert.match(html, /data-analisis="1" open/);
assert.match(html, /aria-label="Victoria: Peleador A 60,0 %; Peleador B 40,0 %"/);
assert.match(html, /27,0 % – 55,0 %/); // intervalo B = espejo del A
assert.match(html, /Modelo por resultado/);
assert.match(html, /UFCStats/);
assert.equal((html.match(/class="analisis-metodo-fila"/g) || []).length, 6);
assert.equal((html.match(/class="analisis-apilada"/g) || []).length, 3);

html = pintar(base);
assert.doesNotMatch(html, /data-analisis="1" open/);
assert.match(html, /Historial de victorias por método no disponible/);
assert.match(html, /todavía no está disponible/);
assert.equal((html.match(/class="analisis-apilada"/g) || []).length, 1);
assert.doesNotMatch(html, /NaN|undefined/);

html = pintar({ ...base, probabilidades_metodo: { A_KO: null },
  metodo6: [{ clase: 'A_KO', p_modelo: .3 }] });
assert.match(html, /todavía no está disponible/); // no seis probabilidades sintéticas
assert.doesNotMatch(html, /class="analisis-metodo-fila"/);

html = pintar({ ...base, metodo6: Object.entries(seis).map(([clase, p_modelo]) => ({ clase, p_modelo })) });
assert.equal((html.match(/class="analisis-metodo-fila"/g) || []).length, 6);

html = pintar({ ...base, probabilidades_metodo: { ...seis, A_KO: .9 } });
assert.match(html, /todavía no está disponible/); // rechaza sumas falsas

html = pintar({ ...base, p_a: null, p_b: null, ci_a: [null, .5],
  metodo: { 'KO/TKO': .4, Submission: .2 },
  metodo_hist_a: { 'KO/TKO': null, Submission: .3, Decision: .2 } });
assert.match(html, /Probabilidad de victoria no disponible/);
assert.match(html, /Rango de incertidumbre no disponible/);
assert.doesNotMatch(html, /class="analisis-apilada"/);

html = pintar({ ...base, a: '<img src=x onerror="alert(1)">', id: '" onfocus="x' });
assert.doesNotMatch(html, /<img/);
assert.match(html, /&lt;img/);
assert.match(html, /data-analisis="&quot; onfocus=&quot;x"/);

html = pintar({ ...base, info_a: { metodo_victorias: { 'KO/TKO': .5, Submission: .3, Decision: .2 },
  metodo_victorias_fuente: 'carrera profesional' } });
assert.equal((html.match(/class="analisis-apilada"/g) || []).length, 2);
assert.match(html, /carrera profesional/);

console.log('Análisis UI: 8 contratos de datos verificados.');
