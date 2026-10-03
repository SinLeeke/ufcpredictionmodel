const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Exercise the actual view helpers without starting scrapers or a browser.
const source = fs.readFileSync(path.join(__dirname, '../webui/static/app.js'), 'utf8');
const context = vm.createContext({
  ico: name => `<svg data-icon="${name}"></svg>`,
});
// Load the production formatters and portrait renderer too: the complete card
// helpers should be exercised with the same markup used by the application.
vm.runInContext(source.slice(source.indexOf('const NBSP_FINO ='), source.indexOf('const cls =')), context);
vm.runInContext(source.slice(source.indexOf('const SILUETA ='), source.indexOf('function cargarFotos(')), context);
vm.runInContext(source.slice(source.indexOf('const claseConf ='), source.indexOf('function mejorMetodo(')), context);
const warning = p => context.avisoDebut(p);

test('identifies a debutant in either corner and names only that fighter', () => {
  for (const side of ['a', 'b']) {
    const p = {a:'Fighter Alpha', b:'Fighter Beta', [`info_${side}`]:{debut_ufc_confirmado:true}};
    const html = warning(p);
    assert.match(html, /Debut en UFC/);
    assert.ok(html.includes(p[side]));
    assert.ok(!html.includes(p[side === 'a' ? 'b' : 'a']));
  }
});

test('distinguishes two confirmed debuts and escapes source names', () => {
  const html = warning({a:'Alpha <script>', b:'Beta', debutantes:['Alpha <script>', 'Beta']});
  assert.match(html, /Ambos debutan en UFC/);
  assert.match(html, /Alpha &lt;script&gt; y Beta/);
  assert.ok(!html.includes('<script>'));
});

test('does not turn missing or locally empty history into a debut', () => {
  assert.equal(warning({a:'Alpha', b:'Beta', info_a:{n_peleas_hist:0}, info_b:null}), '');
  assert.equal(warning({a:'Alpha', b:'Beta', debutantes:[], info_a:{debut_ufc_confirmado:true}}), '');
});

const history = p => context.historialReciente(p);
const fight = (resultado, metodo, rival = 'Rival', fecha = '2026-09-01') =>
  ({resultado, metodo, rival, fecha});
const recent = (peleasA, peleasB) => history({id:'fight-8', a:'Alpha', b:'Beta',
  info_a:{ultimas_peleas:peleasA}, info_b:{ultimas_peleas:peleasB}});
const buttons = html => [...html.matchAll(/<button\b[^>]*class="historial-cuadro [^"]*"[^>]*>.*?<\/button>/gs)].map(m => m[0]);

test('recent results keep victory, defeat, draw and no contest distinct with visible methods', () => {
  const rendered = buttons(recent([
    fight('W', 'KO/TKO', 'Opponent W'), fight('L', 'Submission', 'Opponent L'),
    fight('D', 'Decision - Split', 'Opponent D'), fight('NC', 'No Contest', 'Opponent NC'),
  ], []));
  assert.equal(rendered.length, 4);
  const expected = [
    ['victoria', 'Victoria frente a Opponent W', 'V', 'KO/TKO'],
    ['derrota', 'Derrota frente a Opponent L', 'P', 'SUB'],
    ['neutral', 'Empate frente a Opponent D', 'E', 'DEC'],
    ['neutral', 'Sin resultado frente a Opponent NC', 'NC', 'NC'],
  ];
  expected.forEach(([status, accessible, mark, method], i) => {
    assert.ok(rendered[i].includes(`class="historial-cuadro ${status}"`));
    assert.ok(rendered[i].includes(`aria-label="${accessible} ·`));
    assert.ok(rendered[i].includes(`<small>${mark}</small><span>${method}</span>`), rendered[i]);
    assert.ok(rendered[i].includes(`data-historial-indice="${i}"`));
    assert.ok(rendered[i].includes('data-historial-lado="a"'));
  });
});

test('recent history limits each fighter to five real fights and preserves supplied order', () => {
  const a = Array.from({length:7}, (_, i) => fight(i % 2 ? 'L' : 'W', 'KO', `Alpha Rival ${i}`));
  const b = [fight('W', 'Submission', 'Beta Rival 0'), fight('L', 'Decision', 'Beta Rival 1')];
  const html = recent(a, b);
  const rendered = buttons(html);
  assert.equal(rendered.length, 7);
  assert.equal(rendered.filter(s => s.includes('data-historial-lado="a"')).length, 5);
  assert.equal(rendered.filter(s => s.includes('data-historial-lado="b"')).length, 2);
  assert.match(html, /Últimas 5 peleas de Alpha, más reciente primero/);
  assert.match(html, /Últimas 2 peleas de Beta, más reciente primero/);
  assert.ok(html.indexOf('Alpha Rival 0') < html.indexOf('Alpha Rival 4'));
  assert.doesNotMatch(html, /Alpha Rival [56]/);
  assert.equal(a.length, 7); // rendering never truncates the underlying payload
});

test('recent history escapes names, identity, opponents, dates and full methods in accessible details', () => {
  const html = history({id:'9" autofocus onfocus="bad', a:'Alpha <img src=x>', b:'Beta & Name',
    info_a:{ultimas_peleas:[fight('W', 'KO" onclick="bad <script>', 'Rival <svg onload="bad">', '2026 & "date"')]},
    info_b:{ultimas_peleas:[]}});
  assert.doesNotMatch(html, /<img|<script>|<svg|" onclick="|" autofocus /);
  assert.match(html, /Alpha &lt;img src=x&gt;/);
  assert.match(html, /Beta &amp; Name/);
  assert.match(html, /data-historial-id="9&quot; autofocus onfocus=&quot;bad"/);
  assert.match(html, /Rival &lt;svg onload=&quot;bad&quot;&gt;/);
  assert.match(html, /KO&quot; onclick=&quot;bad &lt;script&gt;/);
  assert.match(html, /2026 &amp; &quot;date&quot;/);
});

test('absent and malformed recent histories stay unavailable instead of creating five placeholder results', () => {
  for (const absent of [null, undefined, {}, 'unavailable', []]) {
    const html = recent(absent, absent);
    assert.equal(buttons(html).length, 0);
    assert.equal((html.match(/Historial reciente no disponible/g) || []).length, 2);
    assert.doesNotMatch(html, /<ol/);
  }
  const html = history({id:'1', a:'Alpha', b:'Beta'});
  assert.equal(buttons(html).length, 0);
  assert.doesNotMatch(html, /NaN|undefined|null/);
});

test('unknown results and missing method metadata remain visibly unknown', () => {
  const html = recent([{resultado:'?', metodo:null, rival:null, fecha:null}], []);
  const [button] = buttons(html);
  assert.match(button, /class="historial-cuadro neutral"/);
  assert.match(button, /Resultado no registrado · Método no registrado/);
  assert.match(button, /<small>—<\/small><span>—<\/span>/);
  assert.doesNotMatch(button, /frente a|undefined|null/);
});

test('full methods retain distinctions in compact recent history labels', () => {
  const values = [
    ['KO', 'KO'], ['KO/TKO', 'KO/TKO'], ['TKO - Doctor Stoppage', 'TKO'], ['Submission - RNC', 'SUB'],
    ['Sumisión', 'SUB'], ['Decision - Unanimous', 'DEC'], ['Decisión dividida', 'DEC'],
    ['Disqualification', 'DQ'], ['No Contest', 'NC'], ['Other medical stoppage', 'OTRO'], ['', '—'],
  ];
  for (const [input, label] of values) assert.equal(context.metodoHistorial(input), label);
});

const fold = (p, type = '', open = false) => context.combatePlegable(
  {id:'4', a:'Alpha', b:'Beta', confianza:'buena', ...p},
  '<article data-rendered="true">Tarjeta y análisis</article>', type, open);

test('every fight starts collapsed with fighter names in its native disclosure header', () => {
  for (const type of ['', 'coestelar', 'estelar']) {
    const html = fold({}, type);
    const opening = html.slice(0, html.indexOf('>'));
    assert.match(opening, /^<details /);
    assert.match(opening, /data-combate="4"/);
    assert.doesNotMatch(opening, /\bopen\b/);
    assert.match(html, /<summary class="combate-cab">/);
    assert.match(html, /<b\b[^>]*>Alpha<\/b><small>vs<\/small><b\b[^>]*>Beta<\/b>/);
    assert.match(html, /<div class="combate-contenido"><article data-rendered="true">Tarjeta y análisis<\/article><\/div><\/details>/);
  }
});

test('restored open state is applied explicitly without changing disclosure content', () => {
  const html = fold({}, 'coestelar', true);
  assert.match(html, /data-combate="4" open>/);
  assert.match(html, /Co-estelar/);
  assert.match(html, /Tarjeta y análisis/);
});

test('every confirmed title fight is gold regardless of its position on the card', () => {
  for (const type of ['', 'estelar', 'coestelar']) {
    assert.match(fold({es_titulo:true}, type), /class="combate-desplegable combate-titulo"/);
    for (const flag of [undefined, null, false, 'true']) {
      const html = fold({es_titulo:flag}, type);
      assert.doesNotMatch(html, /combate-titulo|Por el título/);
    }
  }
  assert.match(fold({es_titulo:true}, 'estelar'), /Pelea estelar · Por el título/);
  assert.match(fold({es_titulo:true}, 'coestelar'), /Co-estelar · Por el título/);
  const regular = fold({es_titulo:true});
  assert.match(regular, /combate-titulo/);
  assert.match(regular, /Por el título/);
});

test('collapsed headers escape source identity and fighter or segment names', () => {
  const html = fold({id:'x" onfocus="bad', a:'Alpha <script>', b:'Beta & "Name"', segmento:'Main <img src=x>'});
  assert.doesNotMatch(html, /<script>|<img|" onfocus="/);
  assert.match(html, /data-combate="x&quot; onfocus=&quot;bad"/);
  assert.match(html, /<b\b[^>]*>Alpha &lt;script&gt;<\/b>/);
  assert.match(html, /<b\b[^>]*>Beta &amp; &quot;Name&quot;<\/b>/);
  assert.match(html, /Main &lt;img src=x&gt;/);
});

test('table title labels only appear for confirmed championships', () => {
  assert.match(context.etiquetaTitulo({es_titulo:true}), /class="pelea-cinturon">Por el título/);
  for (const flag of [null, false, undefined, 'true']) assert.equal(context.etiquetaTitulo({es_titulo:flag}), '');
});

let reducedMotion = false;
context.reducir = () => reducedMotion;
context.EASE_OUT = 'ease-out';
// Cerrado, un details mide su summary más su borde y su relleno: aquí, 75 px
// de summary y 1 px de borde arriba = los 76 px de la fila cerrada.
context.getComputedStyle = () => ({borderTopWidth:'1px', borderBottomWidth:'0px', paddingTop:'0px', paddingBottom:'0px'});
function animatedFight() {
  const attrs = new Set();
  const animations = [];
  const analysis = {open:false};
  const detail = {
    open:false, style:{height:'', overflow:''}, visualHeight:null,
    getBoundingClientRect() { return {height:this.visualHeight ?? (this.open ? 600 : 76)}; },
    querySelector() { return {getBoundingClientRect:() => ({height:75})}; },
    querySelectorAll(selector) { assert.equal(selector, '[data-analisis]'); return [analysis]; },
    setAttribute(name) { attrs.add(name); },
    removeAttribute(name) { attrs.delete(name); },
    hasAttribute(name) { return attrs.has(name); },
    animate(frames, options) {
      const animation = {frames, options, cancelled:false,
        cancel() { this.cancelled = true; detail.visualHeight = null; }};
      animations.push(animation);
      return animation;
    },
  };
  return {detail, animations, analysis};
}

test('opening a fight leaves analysis closed until the person explicitly expands it', () => {
  for (const reduced of [false, true]) {
    reducedMotion = reduced;
    const {detail, animations, analysis} = animatedFight();
    analysis.open = true;
    context.desplegarCombate(detail, true);
    assert.equal(analysis.open, false);
    if (!reduced) animations.at(-1).onfinish();
    analysis.open = true; // the person's choice survives a redundant open request
    context.desplegarCombate(detail, true);
    assert.equal(analysis.open, true);
    context.desplegarCombate(detail, false);
    if (!reduced) animations.at(-1).onfinish();
    context.desplegarCombate(detail, true);
    assert.equal(analysis.open, false);
    if (!reduced) animations.at(-1).onfinish();
  }
  reducedMotion = false;
});

test('fight disclosure animates open and close, then releases height and overflow', () => {
  reducedMotion = false;
  const {detail, animations} = animatedFight();
  context.desplegarCombate(detail, true);
  assert.equal(detail.open, true);
  assert.equal(animations[0].frames[0].height, '76px');
  assert.equal(animations[0].frames[1].height, '600px');
  animations[0].onfinish();
  assert.equal(detail.style.height, '');
  assert.equal(detail.style.overflow, '');
  context.desplegarCombate(detail, false);
  assert.equal(detail.open, true); // remain rendered during the closing animation
  assert.equal(detail.hasAttribute('data-cerrando'), true);
  assert.equal(animations[1].frames[1].height, '76px');
  animations[1].onfinish();
  assert.equal(detail.open, false);
  assert.equal(detail.hasAttribute('data-cerrando'), false);
  assert.equal(detail.style.height, '');
  assert.equal(detail.style.overflow, '');
});

test('rapid reversal starts at the visible height and cancels the previous animation', () => {
  const {detail, animations} = animatedFight();
  context.desplegarCombate(detail, true);
  detail.visualHeight = 200;
  context.desplegarCombate(detail, false);
  assert.equal(animations[0].cancelled, true);
  assert.equal(animations[1].frames[0].height, '200px');
  detail.visualHeight = 170;
  context.desplegarCombate(detail, true);
  assert.equal(animations[1].cancelled, true);
  assert.equal(animations[2].frames[0].height, '170px');
  assert.equal(detail.hasAttribute('data-cerrando'), false);
  animations[2].onfinish();
  assert.equal(detail.open, true);
  assert.equal(detail.style.overflow, '');
});

test('reduced motion cancels a running disclosure and applies the final state immediately', () => {
  const {detail, animations} = animatedFight();
  context.desplegarCombate(detail, true);
  reducedMotion = true;
  context.desplegarCombate(detail, false);
  assert.equal(animations.length, 1);
  assert.equal(animations[0].cancelled, true);
  assert.equal(detail.open, false);
  assert.equal(detail.style.height, '');
  assert.equal(detail.style.overflow, '');
  context.desplegarCombate(detail, true);
  assert.equal(detail.open, true);
  assert.equal(animations.length, 1);
  reducedMotion = false;
});

test('compact canvas history exposes real results without nested interactive controls', () => {
  const html = context.historialReciente({id:'4', a:'Alpha', b:'Beta',
    info_a:{ultimas_peleas:[fight('W', 'KO/TKO'), fight('NC', 'CNC')]},
    info_b:{ultimas_peleas:[fight('L', 'SUB')]}}, true);
  assert.equal((html.match(/<button/g) || []).length, 2);
  assert.equal((html.match(/class="historial-cuadro /g) || []).length, 3);
  assert.equal((html.match(/data-historial-todo="true"/g) || []).length, 2);
  assert.match(html, /Ver las últimas 2 peleas de Alpha/);
  assert.match(html, /<small>NC<\/small><span>NC<\/span>/);
  let depth = 0;
  for (const tag of html.match(/<\/?button\b[^>]*>/g) || []) {
    depth += tag.startsWith('</') ? -1 : 1;
    assert.ok(depth === 0 || depth === 1, 'button controls must not nest');
  }
  assert.equal(depth, 0);
});

const fullFight = (extra = {}) => ({
  id:'fight-12', a:'Alpha Fighter', b:'Beta Fighter', confianza:'buena',
  p_a:.62, p_b:.38, ganador:'Alpha Fighter', p_finish:.55,
  metodo:{'KO/TKO':.35, Submission:.2, Decision:.45}, tendencia:'pelea promedio',
  mercado:{cuota_a:1.65, cuota_b:2.3, p_mercado_a:.59, p_modelo_a:.65, vig:.055},
  info_a:{n_peleas_hist:7, ultimas_peleas:[fight('W', 'KO/TKO')]},
  info_b:{n_peleas_hist:4, ultimas_peleas:[fight('L', 'Submission')]},
  por_que_confianza:'Confianza explicada con los datos disponibles.', ...extra,
});

test('a newly loaded card does not automatically open analysis; live refresh retains explicit choices', () => {
  const start = source.indexOf('  const pelea = (p, i) => {', source.indexOf('function pintarCartelera('));
  const end = source.indexOf("  $('#peleas').innerHTML", start);
  assert.ok(start > 0 && end > start);
  const renderer = source.slice(start, end);
  for (const opened of [null, new Set(), new Set(['fight-12']), new Set(['another-fight'])]) {
    let passed;
    const ctx = vm.createContext({analisisAbiertos:opened, idEstelar:null, idCo:null, mov:{},
      peleas:[fullFight()], esJuez:() => false, vistaPelea:() => '<article></article>',
      analisisPelea:(p, open) => { passed = open; return '<details></details>'; }});
    vm.runInContext(renderer + '\npelea(peleas[0], 0);', ctx);
    assert.equal(passed, opened?.has('fight-12') === true);
  }
});

test('cage portraits and recent results stay on the canvas while comparisons and methods form a separate column', () => {
  for (const title of [true, false]) {
    for (const market of [fullFight().mercado, null]) {
      const html = context.jaula(fullFight({es_titulo:title, mercado:market}), {}, 'coestelar');
      const aside = html.match(/<aside class="estelar-datos"[^>]*>(.*?)<\/aside>/s)?.[1] || '';
      assert.match(html, /class="estelar-distribucion"/);
      assert.ok(html.indexOf('class="historial-reciente') < html.indexOf('<aside'));
      assert.match(aside, /Cómo puede terminar/);
      assert.match(aside, /class="metodo"/);
      assert.match(aside, /No llega a tarjetas/);
      assert.equal((html.match(/:finish"/g) || []).length, 1);
      assert.equal(aside.includes('Cuotas y modelo'), market !== null);
      assert.doesNotMatch(html, /NaN|undefined/);
    }
  }
});

test('title canvas uses its own metallic line without source identifiers becoming SVG attributes', () => {
  const first = context.lineaLona({id:'x" onload="bad', es_titulo:true});
  const second = context.lineaLona({id:'other', es_titulo:true});
  const id = first.match(/<linearGradient id="([^"]+)"/)?.[1];
  assert.ok(id);
  assert.ok(first.includes(`stroke="url(#${id})"`));
  assert.ok(!second.includes(`id="${id}"`));
  assert.doesNotMatch(first, /onload|id="x"/);
  assert.doesNotMatch(context.lineaLona({id:'ordinary', es_titulo:false}), /linearGradient|url\(#/);
});

test('main events and every confirmed title use the cage in both card styles', () => {
  for (const judge of [false, true]) {
    for (const type of ['estelar', 'coestelar', '']) {
      for (const title of [true, false, null, undefined, 'true']) {
        const p = fullFight({es_titulo:title});
        const expectedCage = type === 'estelar' || title === true;
        assert.equal(context.usaOctagono(p, type), expectedCage);
        const html = context.vistaPelea(p, {}, type, judge, 2, 6);
        assert.equal(html.includes('class="jaula"'), expectedCage,
          `style=${judge ? 'judge' : 'broadcast'}, type=${type}, title=${title}`);
        if (!expectedCage) assert.match(html, judge ? /class="acta\s*"/ : /class="pelea"/);
        const wrapped = context.combatePlegable(p, html, type);
        assert.equal(wrapped.includes('combate-titulo'), title === true);
        assert.equal(html.includes('estelar-titulo'), expectedCage && title === true);
      }
    }
  }
});

test('expanded cards retain exactly one confidence pill in the outer disclosure header', () => {
  for (const judge of [false, true]) {
    for (const [type, title] of [['estelar', false], ['coestelar', true], ['coestelar', false], ['', false]]) {
      for (const confidence of ['buena', 'NO FIABLE']) {
        const p = fullFight({es_titulo:title, confianza:confidence});
        const body = context.vistaPelea(p, {}, type, judge, 2, 6);
        const wrapped = context.combatePlegable(p, body, type, true);
        const summary = wrapped.match(/<summary\b[^>]*>(.*?)<\/summary>/s)?.[1] || '';
        assert.equal((wrapped.match(/class="pill /g) || []).length, 1);
        assert.equal((summary.match(/class="pill /g) || []).length, 1);
        assert.doesNotMatch(body, /class="pill |class="ac-conf|class="ac-timbre|class="cara-top/);
        assert.doesNotMatch(summary, /<button\b/); // preserve native disclosure interaction
        assert.equal((body.match(/data-explica="fight-12"/g) || []).length, 1);
        assert.match(body, /<button\b[^>]*data-explica="fight-12"[^>]*>/);
      }
    }
  }
});

test('fighter side markers stay stable when the favourite changes, in every rendering', () => {
  for (const favouriteA of [true, false]) {
    const p = fullFight({p_a:favouriteA ? .62 : .38, p_b:favouriteA ? .38 : .62});
    const wrapped = context.combatePlegable(p, '', 'coestelar');
    assert.match(wrapped, /<b data-lado="a">Alpha Fighter<\/b>/);
    assert.match(wrapped, /<b data-lado="b">Beta Fighter<\/b>/);
    const bar = context.barraDuelo(p);
    assert.match(bar, /<i\b[^>]*data-lado="a"[^>]*style="width:38%|<i\b[^>]*data-lado="a"[^>]*style="width:62%/);
    assert.match(bar, /<i\b[^>]*data-lado="b"[^>]*style="width:38%|<i\b[^>]*data-lado="b"[^>]*style="width:62%/);
    for (const render of [
      () => context.tarjetaPelea(p, {}, ''),
      () => context.actaPelea(p, {}, '', 2, 6),
      () => context.jaula(p, {}, 'estelar'),
    ]) {
      const html = render();
      for (const [side, corner] of [['a','A'], ['b','B']]) {
        const name = side === 'a' ? p.a : p.b;
        assert.match(html, new RegExp(`<[^>]*data-lado="${side}"[^>]*>${name}(?:<|$)`));
        const numbers = [...html.matchAll(/<[^>]+\bdata-num="([^"]+)"[^>]*>/g)];
        const scoped = numbers.filter(m => new RegExp(`:(?:p${corner}|(?:p|cuota|casa|modelo):${corner})$`).test(m[1]));
        assert.ok(scoped.length >= 4);
        scoped.forEach(m => assert.match(m[0], new RegExp(`data-lado="${side}"`)));
      }
    }
  }
});

test('recent history belongs immediately below names and above winning percentages', () => {
  const p = fullFight();
  const normal = context.tarjetaPelea(p, {}, 'coestelar');
  assert.ok(normal.indexOf('class="vs-sub"') < normal.indexOf('class="historial-reciente'));
  assert.ok(normal.indexOf('class="historial-reciente') < normal.indexOf('class="pcts"'));
  assert.equal((normal.match(/class="historial-reciente/g) || []).length, 1);
  const cage = context.jaula(p, {}, 'estelar');
  assert.ok(cage.indexOf('class="j-b j-nombre"') < cage.indexOf('class="historial-reciente'));
  assert.ok(cage.indexOf('class="historial-reciente') < cage.indexOf('class="j-a j-pct'));
  assert.equal((cage.match(/class="historial-reciente/g) || []).length, 1);
  const scorecard = context.actaPelea(p, {}, 'coestelar', 2, 6);
  assert.ok(scorecard.indexOf('class="ac-id"') < scorecard.indexOf('class="historial-reciente'));
  assert.ok(scorecard.lastIndexOf('class="ac-id"') < scorecard.indexOf('class="historial-reciente'));
  assert.ok(scorecard.indexOf('class="historial-reciente') < scorecard.indexOf('class="ac-fila ac-prob"'));
  assert.equal((scorecard.match(/class="historial-reciente/g) || []).length, 1);
});

test('a replay shows the real result after the forecast; a normal card shows none', () => {
  const p = fullFight();
  assert.equal(context.resultadoReal(p), '');
  assert.equal(context.pillResultado(p), '');
  const hit = {...p, resultado: {ganador: p.b, lado: 'b', acierto: true, como: 'decisión unánime',
    asalto: 5, tiempo: '5:00', fecha: '2025-11-15', metodo: 'Decision'}};
  const card = context.tarjetaPelea(hit, {}, '');
  assert.ok(card.indexOf('class="pcts"') < card.indexOf('class="resultado-real'));
  assert.match(context.resultadoReal(hit), /data-acierto="si"/);
  assert.match(context.resultadoReal(hit), /Acertó/);
  assert.match(context.pillResultado(hit), /acertó/);
  // The canvas plaque uses the short form so it fits between the diagonals.
  assert.match(context.resultadoReal(hit, true), /dec\. unánime · R5 5:00/);
  const miss = {...hit, resultado: {...hit.resultado, acierto: false}};
  assert.match(context.resultadoReal(miss), /Falló/);
  // In a replay without the result in the local base: said, never guessed.
  const pending = {...p, resultado: null};
  assert.match(context.resultadoReal(pending), /data-acierto="nd"/);
  assert.match(context.pillResultado(pending), /sin resultado/);
});

test('canvas history labels are short enough for their cells', () => {
  assert.equal(context.metodoHistorial('KO/TKO', true), 'KO');
  assert.equal(context.metodoHistorial('KO/TKO'), 'KO/TKO');
});

test('a replay says whether the most likely method was the real one', () => {
  const p = {...fullFight(), metodo: {'KO/TKO': .2, Submission: .1, Decision: .7}};
  assert.doesNotMatch(context.metodoFila(p), /metodo-veredicto/);          // normal card: nothing
  const hit = {...p, resultado: {ganador: p.a, metodo: 'Decision', acierto: true}};
  assert.match(context.metodoFila(hit), /Acertó el método/);
  assert.match(context.metodoFila(hit), /class="top real"/);
  const miss = {...p, resultado: {ganador: p.a, metodo: 'KO/TKO', acierto: true}};
  assert.match(context.metodoFila(miss), /Falló el método/);
  // A draw or no contest has no method to judge.
  assert.doesNotMatch(context.metodoFila({...p, resultado: {ganador: '', metodo: 'Decision'}}), /metodo-veredicto/);
});
