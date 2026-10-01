/* UFC Predictor — interfaz
   Sin frameworks ni CDN a propósito: corre en tu PC y tiene que abrir aunque no
   haya internet, que es justo cuando quieres mirar una cartelera ya bajada.

   Criterio de diseño: cada número que se muestra viene acompañado de qué
   significa. El usuario no debería tener que preguntar qué es "NO FIABLE". */

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const S = { datos:null, patas:[], elegidas:[], job:null, logLeidas:0,
            proximoAuto:null, origen:'', vista:'tarjetas' };

const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const txt = await r.text();
  let body; try { body = JSON.parse(txt); } catch { body = { detail: txt }; }
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
};
const post = (url, obj) => api(url, {
  method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify(obj || {}) });

/* Cifras en español de Chile: coma decimal y punto de miles, como ya escribía
   la Guía. El % va pegado con un espacio fino que no corta línea, para que
   nunca quede "75" en una línea y "%" en la siguiente. */
const NBSP_FINO = ' ';
const fmt = (x, d) => Number(x).toLocaleString('es-CL',
  { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x, d = 1) => fmt(x * 100, d) + NBSP_FINO + '%';
const sgn = (x, d = 1) => (x >= 0 ? '+' : '−') + fmt(Math.abs(x) * 100, d) + NBSP_FINO + '%';
const cuota = (x) => (x ? fmt(x, 2) : 'sin cuota');
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cls = (x) => x >= 0 ? 'pos' : 'neg';
const miles = (n) => n.toLocaleString('es-CL');

// Los íconos de la cabecera se dibujan desde iconos.js: un solo set en toda la UI.
$$('[data-ico]').forEach(e => { e.outerHTML = ico(e.dataset.ico); });

/* =============================== TEMA ================================= */
const temaGuardado = localStorage.getItem('tema');
if (temaGuardado) document.documentElement.dataset.tema = temaGuardado;
$('#btn-tema').onclick = () => {
  const oscuroAhora = document.documentElement.dataset.tema
    ? document.documentElement.dataset.tema === 'oscuro'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const nuevo = oscuroAhora ? 'claro' : 'oscuro';
  document.documentElement.dataset.tema = nuevo;
  localStorage.setItem('tema', nuevo);
};

/* =============================== TABS ================================= */
const irA = (t) => $(`.tab[data-tab="${t}"]`).click();
$$('.tab').forEach(t => t.onclick = () => {
  $$('.tab').forEach(x => { x.classList.remove('activa'); x.removeAttribute('aria-current'); });
  $$('.panel').forEach(x => x.classList.remove('activa'));
  t.classList.add('activa');
  t.setAttribute('aria-current', 'page');
  $('#tab-' + t.dataset.tab).classList.add('activa');
  window.scrollTo({ top: 0 });
  if (t.dataset.tab === 'mantenimiento') cargarTareas();
  if (t.dataset.tab === 'datos') { cargarCSVs(); listarCarteleras(); }
});
$$('[data-ir]').forEach(b => b.onclick = () => irA(b.dataset.ir));

$$('.seg').forEach(b => b.onclick = () => {
  $$('.seg').forEach(x => x.classList.remove('activa'));
  b.classList.add('activa');
  S.vista = b.dataset.vista;
  $('#peleas').classList.toggle('oculto', S.vista !== 'tarjetas');
  $('#tabla-wrap').classList.toggle('oculto', S.vista !== 'tabla');
});

/* ============================== MODAL ================================= */
// Al abrir se lleva el foco a la × y al cerrar se devuelve a quien lo abrió:
// sin eso, con teclado, el foco quedaba detrás del velo.
let focoAntesDelModal = null;
function modal(html) {
  focoAntesDelModal = document.activeElement;
  $('#modal-cuerpo').innerHTML = html;
  $('#modal').classList.remove('oculto');
  $('.modal-cerrar').focus();
}
function cerrarModal() {
  if ($('#modal').classList.contains('oculto')) return;
  $('#modal').classList.add('oculto');
  focoAntesDelModal?.focus?.();
}
$('.modal-cerrar').onclick = cerrarModal;
$('#modal').onclick = (e) => { if (e.target.id === 'modal') cerrarModal(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') cerrarModal(); });

/* ============================== BARRA ================================= */
function barra(txt, tipo) {
  const b = $('#barra-estado');
  if (!txt) { b.classList.add('oculto'); return; }
  b.className = 'barra' + (tipo === 'error' ? ' error' : '');
  b.textContent = txt;
  b.classList.remove('oculto');
}

/* =========================== ESTADO / POLL ============================ */
// El nombre de la cartelera llega como nombre de archivo
// ("betano_2026-08-08_gamrot_vs_salkilld"). Se muestra como lo diría la
// transmisión: "Gamrot vs Salkilld", con la fecha aparte.
const ES_SLUG = /^[a-z0-9_.\-]+$/;
function evento(e) {
  const crudo = (e.titulo || '').replace(/^DEMO · /, '');
  const candidatos = [e.datos?.titulo, e.csv, crudo].filter(Boolean);
  const conFecha = candidatos.map(t => t.match(/(\d{4})-(\d{2})-(\d{2})_(.+?)(?:\.csv)?$/)).find(Boolean);
  let fecha = '';
  if (conFecha) {
    const [, a, m, d] = conFecha.map(Number);
    fecha = new Date(a, m - 1, d).toLocaleDateString('es-CL',
      { weekday:'short', day:'numeric', month:'short' }).replace(',', '');
  }
  const deSlug = (t) => t.replace(/\.csv$/i, '').replace(/^betano_/i, '').replace(/^\d{4}-\d{2}-\d{2}_/, '')
    .replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\bVs\b/g, 'vs').replace(/\bUfc\b/g, 'UFC').trim();
  let nombre = crudo;
  let liga = '';
  if (!crudo || ES_SLUG.test(crudo)) nombre = deSlug(conFecha ? conFecha[4] : (crudo || e.csv || ''));
  else if (conFecha) { liga = crudo; nombre = deSlug(conFecha[4]); }
  return { nombre: nombre || 'Cartelera', fecha, liga, demo: /^DEMO · /.test(e.titulo || ''),
           crudo: e.titulo || e.csv || '' };
}

async function tick() {
  try {
    const e = await api('/api/estado');
    S.proximoAuto = e.proximo_auto; S.origen = e.origen; S.vivo = e.vivo;
    const hayCartelera = !!(e.titulo || e.csv);
    const ev = evento(e);
    S.evento = ev;
    S.textosEvento = [e.titulo, e.csv, e.datos?.titulo].filter(Boolean);
    $('#titulo-cartelera').textContent = hayCartelera ? ev.nombre : 'sin cartelera cargada';
    $('#titulo-cartelera').title = hayCartelera ? `${ev.crudo}. Toca para cambiar de cartelera.` : 'Cambiar de cartelera';
    // La × solo aparece si hay algo que soltar.
    $('#btn-soltar').classList.toggle('oculto', !hayCartelera);
    $('#btn-refresh').disabled = e.cargando || !e.origen;

    if (e.error)         barra(e.error, 'error');
    else if (e.cargando) barra(e.progreso || 'trabajando…');
    else                 barra('');

    if (e.datos && JSON.stringify(e.datos) !== JSON.stringify(S.datos)) {
      S.datos = e.datos; S.patas = e.datos.patas;
      const vivos = new Set(S.patas.map(p => p.id));
      S.elegidas = S.elegidas.filter(id => vivos.has(id));
      pintarCartelera(e.datos, e.movimiento || {});
      pintarTiers(e.datos.tiers);
      pintarPatas();
      evaluarParlay();
    } else if (!e.datos && !e.cargando && S.datos === null) {
      mostrarVacio();
    }
  } catch (err) { barra('No pude hablar con el servidor: ' + err.message, 'error'); }
}

// Sin cartelera (al abrir, o después de soltarla con la ×) vuelve la
// bienvenida. Antes, tras soltarla, la pestaña seguía mostrando la anterior.
function mostrarVacio() {
  $('#bienvenida').classList.remove('oculto');
  $('#cartelera-contenido').classList.add('oculto');
  $('#parlay-vacio').classList.remove('oculto');
  $('#parlay-contenido').classList.add('oculto');
  $('#badge-patas').textContent = '0';
}

// Modo EN VIVO: solo la línea de ganador, 1 petición cada 10 s. Va aparte del
// refresco completo porque ese re-baja el mercado de método (1 petición POR
// pelea) y vuelve a correr el modelo: eso no se puede hacer cada 10 segundos
// sin que Betano te bloquee.
$('#chk-vivo').onchange = async (e) => {
  const on = e.target.checked;
  try {
    await post(`/api/vivo?encender=${on}`);
    barra(on
      ? 'En vivo: la cuota de ganador se refresca cada 10 s. Apágalo cuando no estés mirando.'
      : 'Modo en vivo apagado.');
  } catch { e.target.checked = !on; barra('No pude cambiar el modo en vivo.'); }
};

function reloj() {
  const r = $('#reloj');
  if (!S.origen) { $('#reloj-caja').classList.add('oculto'); $('#vivo-caja').classList.add('oculto'); return; }
  $('#reloj-caja').classList.remove('oculto');
  // El interruptor solo aparece con origen Betano: un CSV en disco no cambia.
  $('#vivo-caja').classList.toggle('oculto', S.origen !== 'betano');
  if ($('#chk-vivo').checked !== !!S.vivo) $('#chk-vivo').checked = !!S.vivo;
  $('#vivo-caja').classList.toggle('activo', !!S.vivo);
  // El auto-refresco solo tiene sentido con origen Betano: un archivo en disco
  // no cambia solo, y mostrar una cuenta regresiva ahí haría creer lo contrario.
  if (S.origen !== 'betano') { r.textContent = 'archivo: sin cuotas en vivo'; return; }
  if (!S.proximoAuto) { r.textContent = 'auto apagado'; return; }
  const s = Math.max(0, Math.round(S.proximoAuto - Date.now() / 1000));
  r.innerHTML = `cuotas en <b>${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}</b>`;
}

setInterval(tick, 2000);
setInterval(reloj, 1000);
setInterval(() => { if (S.job) seguirJob(); }, 1200);

/* ============================== FOTOS ================================= */
// Silueta de peleador en guardia: lo que se ve mientras llega la foto y cuando
// no hay. Nunca una imagen rota. Los colores salen del tema.
const SILUETA = `<svg viewBox="0 0 120 120" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<rect width="120" height="120" fill="var(--sil-fondo)"/>
<g fill="var(--sil-fig)"><path d="M8 124C8 99 20 86 38 82c6-1 10-5 12-12V58h20v12c2 7 6 11 12 12 18 4 30 17 30 42Z"/>
<ellipse cx="60" cy="40" rx="15.5" ry="18.5"/></g>
<g fill="var(--sil-fig)" stroke="var(--sil-fondo)" stroke-width="2.5" stroke-linejoin="round">
<path d="M33 77c0-8 5-12 13-12s13 4 13 12v10c0 6-4 10-10 10h-6c-6 0-10-4-10-10Z"/>
<path d="M87 77c0-8-5-12-13-12s-13 4-13 12v10c0 6 4 10 10 10h6c6 0 10-4 10-10Z"/></g>
<g fill="var(--sil-fondo)"><rect x="35" y="99" width="22" height="3.5" rx="1.5"/><rect x="63" y="99" width="22" height="3.5" rx="1.5"/></g></svg>`;

// nombre -> URL de la foto, o null mientras se pide / si no hay. Así un
// repintado (EN VIVO) no vuelve a pedirla ni la hace parpadear.
const FOTOS = new Map();
const retrato = (nombre) => {
  const url = FOTOS.get(nombre);
  return `<figure class="retrato" data-foto="${esc(nombre)}">${
    url ? `<img src="${url}" alt="">` : SILUETA}</figure>`;
};
function cargarFotos(raiz) {
  raiz.querySelectorAll('[data-foto]').forEach(f => {
    const n = f.dataset.foto;
    if (FOTOS.has(n)) return;
    FOTOS.set(n, null);
    const url = '/api/foto/' + encodeURIComponent(n);
    // 204 = no hay foto: queda la silueta, que ya está puesta.
    fetch(url).then(r => {
      if (r.status !== 200) return;
      FOTOS.set(n, url);
      document.querySelectorAll(`[data-foto="${CSS.escape(n)}"]`)
        .forEach(x => { x.innerHTML = `<img src="${url}" alt="">`; });
    }).catch(() => {});
  });
}

/* ============================= CARTELERA ============================== */
const TXT_TIER = {
  A: ['Probado', 'Este mercado es el único con ventaja demostrada: +15,4% de retorno sobre 1.145 apuestas históricas.'],
  B: ['Sin ventaja clara', 'Ojo: el mercado de ganador quedó en empate técnico con la casa en las pruebas, así que esto es un complemento, no una base.'],
};

function pintarCartelera(d, mov) {
  $('#bienvenida').classList.add('oculto');
  $('#cartelera-contenido').classList.remove('oculto');
  const hayPatas = d.patas.length > 0;
  $('#parlay-vacio').classList.toggle('oculto', hayPatas);
  $('#parlay-contenido').classList.toggle('oculto', !hayPatas);
  $('#badge-patas').textContent = d.patas.length;

  /* ---- el evento ---- */
  const ev = S.evento || { nombre: d.titulo, fecha: '' };
  const origen = { betano: 'Cuotas de Betano', csv: 'Desde un archivo', demo: 'Cartelera de ejemplo' }[S.origen] || '';
  $('#evento-origen').innerHTML = (ev.demo ? '<span class="demo">Demo</span>' : '') +
    esc([ev.fecha, ev.liga || origen].filter(Boolean).join(' · '));
  $('#evento-titulo').textContent = ev.nombre;

  /* ---- avisos ---- */
  // Gravedad: err (bloquea o invalida), warn (cuidado), info (dato). La marca
  // de la izquierda la dice sin depender del color.
  const av = [];
  if (!d.modelo_real) av.push(['err','alerta',
    'No hay un modelo entrenado, así que estas probabilidades son una aproximación gruesa. Ve a Mantenimiento y ejecuta "Solo reentrenar el modelo".']);
  if (d.con_cuotas && !d.calibrador) av.push(['err','alerta',
    'Hay cuotas pero falta el calibrador, que es lo que permite combinar el modelo con el mercado. Ve a Mantenimiento → "Recalcular el calibrador de ganador". Sin él las señales de valor no son de fiar.']);
  const sosp = d.peleas.filter(p => (p.metodo6 || []).some(o => o.sospechoso));
  if (sosp.length) av.push(['err','prohibido',
    `Las cuotas de método de ${sosp.length} pelea(s) son <b>demasiado generosas para ser reales</b>. Suelen indicar números escritos a mano en vez de bajados de la casa. Como el valor se calcula con el precio, esas peleas mostrarían valor falso, así que quedan bloqueadas.`]);
  if (!d.con_cuotas) av.push(['warn','info',
    'Esta cartelera no trae cuotas, así que se predice pero no se puede decir dónde hay valor ni armar combinadas. Bajarla desde Betano suma cuotas y ~3 puntos de acierto.']);
  // Caso muy frecuente y que sin explicación se lee como si el sistema fallara:
  // hay cuotas de ganador pero Betano todavía no abrió el mercado de método, que
  // es justo el único con ventaja demostrada. Sin este aviso el usuario ve una
  // pantalla entera de "sin ventaja clara" y no sabe si es culpa del modelo.
  const hayMetodo = d.patas.some(p => p.mercado !== 'ganador');
  if (d.con_cuotas && !hayMetodo) av.push(['warn','info',
    '<b>Betano todavía no abre el mercado de método para esta cartelera.</b> Por ahora solo publica "Ganador", que es precisamente el mercado donde las pruebas <b>no</b> encontraron ventaja; por eso todas las selecciones salen como <i>sin ventaja clara</i>. No es un fallo del modelo ni falta de datos. Los mercados de método (KO / sumisión / decisión) suelen abrirse en los días previos al evento: vuelve a refrescar más cerca de la fecha y aparecerán las selecciones <i>probadas</i>.']);
  if (d.missing.length) av.push(['warn','duda',
    `No encontré a estos peleadores en ninguna fuente, probablemente son debutantes absolutos: <b>${d.missing.map(esc).join(', ')}</b>. Sus peleas se omiten en vez de inventar datos.`]);
  const nMov = Object.keys(mov).length;
  if (nMov) av.push(['info','mov',
    `<b>${nMov} cuota(s) se movieron</b> desde el refresco anterior. En las tarjetas y en la tabla salen con ▲ o ▼; pasa el mouse por encima para ver el valor de antes.`]);
  $('#avisos').innerHTML = av.map(([t,i,m]) =>
    `<div class="aviso ${t}"><span class="ai">${ico(i)}</span><div>${m}</div></div>`).join('');

  /* ---- KPIs ---- */
  const apuestas = recolectarApuestas(d);
  const validas = apuestas.filter(a => !a.pocos.length);
  const noFiables = d.peleas.filter(p => p.confianza === 'NO FIABLE').length;
  const solidas = d.peleas.filter(p => ['fuerte','buena'].includes(p.confianza)).length;
  $('#tarjetas-kpi').innerHTML = `
    <div class="kpi"><div class="v">${d.peleas.length}</div><div class="k">peleas analizadas</div></div>
    <div class="kpi"><div class="v">${solidas}</div><div class="k">pronósticos sólidos (65${NBSP_FINO}%+)</div></div>
    <div class="kpi"><div class="v ${noFiables ? 'neg' : ''}">${noFiables}</div>
      <div class="k">sin datos suficientes</div></div>
    <div class="kpi"><div class="v ${validas.length ? 'pos' : ''}">${validas.length}</div>
      <div class="k">apuestas sugeridas</div></div>`;

  /* ---- qué apostar ---- */
  // Zócalos agrupados por evidencia. La explicación de cada nivel va una vez
  // por grupo: repetida en cada fila tapaba lo que cambia de una a otra.
  const descartes = apuestas.filter(a => a.pocos.length);
  let html = '';
  if (!validas.length) {
    html += `<div class="sin-apuestas"><span class="marca-ok">${ico('ok')}</span><div>
      <b>Ninguna apuesta recomendada, y eso está bien.</b>
      <p>Es el resultado más común: la mayoría de las carteleras no ofrecen una ventaja
      medible sobre el precio de la casa. Forzar una apuesta donde no hay valor es
      exactamente cómo se pierde dinero a la larga.</p></div></div>`;
  } else {
    for (const tier of ['A', 'B']) {
      const del = validas.filter(a => a.tier === tier);
      if (!del.length) continue;
      const [nombre, porque] = TXT_TIER[tier];
      html += `<div class="grupo-apuestas">${del.map(a => `
        <div class="zocalo t${tier}">
          <span class="z-sello">${nombre}</span>
          <div class="z-que"><b>${esc(a.que)}</b><span>${esc(a.pelea)}</span></div>
          <div class="z-dato"><small>apostar</small><b>${pct(a.kelly)}</b><small>de tu bankroll</small></div>
          <div class="z-dato"><small>paga</small><b>${cuota(a.cuota)}</b></div>
          <div class="z-dato z-valor"><small>valor</small><b class="${cls(a.ev)}">${sgn(a.ev)}</b></div>
        </div>`).join('')}
        <p class="grupo-motivo">${porque}</p></div>`;
    }
    const exp = validas.reduce((s,a) => s + a.kelly, 0);
    if (exp > 0.15) html += `<div class="aviso warn"><span class="ai">${ico('alerta')}</span><div>
      Sumando todo estarías arriesgando el <b>${pct(exp)}</b> de tu bankroll en una sola
      noche. El cálculo de cuánto apostar asume que las apuestas son independientes, y
      las peleas de un mismo evento no lo son del todo.</div></div>`;
  }
  if (descartes.length) html += `<div class="aviso warn"><span class="ai">${ico('prohibido')}</span><div>
    <b>Descartadas por falta de datos:</b> ${descartes.map(a=>esc(a.que)).join(' · ')}.
    Mostraban valor, pero se apoyan en peleadores de los que casi no hay información.
    Cuando el dato es malo, el valor calculado también lo es.</div></div>`;
  $('#resumen').innerHTML = html;

  /* ---- peleas ---- */
  $('#nota-base').innerHTML = d.con_cuotas
    ? 'Las probabilidades combinan el modelo con las cuotas de la casa, que es la versión más certera (~70% de acierto).'
    : 'Probabilidades del modelo solo, sin cuotas. Con cuotas acertaría ~3 puntos más.';

  const idEstelar = estelar(d.peleas, S.textosEvento || [d.titulo]);
  const idCo = coestelar(d.peleas, idEstelar);
  const principal = d.peleas.find(p => p.id === idEstelar);
  const segunda = d.peleas.find(p => p.id === idCo);
  const resto = d.peleas.filter(p => p.id !== idEstelar && p.id !== idCo);
  $('#peleas').innerHTML = `<div class="peleas-lista">${
    principal ? jaula(principal, mov, 'estelar') : ''}${
    segunda ? jaula(segunda, mov, 'coestelar') : ''}${resto.map(p => tarjetaPelea(p, mov)).join('')}</div>`;
  cargarFotos($('#peleas'));
  $$('#peleas [data-explica]').forEach(b => b.onclick = () => {
    const p = d.peleas.find(x => x.id === b.dataset.explica);
    modal(`<h2>${esc(p.a)} vs ${esc(p.b)}</h2>
      <p><span class="pill ${claseConf(p.confianza)}">${p.confianza}</span></p>
      <p>${p.por_que_confianza}</p>`);
  });

  tabla('#tabla-principal',
    ['Pelea','Ganador','Probabilidad','Cuotas','Confianza','Termina por','No llega a tarjetas','Comparado con lo normal'],
    d.peleas.map(p => {
      const pg = Math.max(p.p_a, p.p_b);
      const m = p.mercado;
      return [esc(`${p.a} vs ${p.b}`), esc(p.ganador), td(pct(pg)),
        td(m ? `${cuota(m.cuota_a)}${flecha(mov, p.id, 'A')} / ${cuota(m.cuota_b)}${flecha(mov, p.id, 'B')}` : 'sin cuotas'),
        `<span class="pill ${claseConf(p.confianza)}">${p.confianza}</span>`,
        mejorMetodo(p.metodo), td(pct(p.p_finish,0)), esc(p.tendencia)];
    }));
}

function recolectarApuestas(d) {
  const out = [];
  d.peleas.forEach(p => {
    // La decisión es la misma apuesta en el mercado de 7 y de 5 vías.
    [...(p.metodo6 || []), ...(p.metodo5 || [])]
      .filter(o => o.apostar && o.clase.endsWith('DEC')).forEach(o =>
      out.push({ orden:0, tier:'A', pelea:`${p.a} vs ${p.b}`,
        que:`${o.clase[0]==='A'?p.a:p.b} gana por decisión`,
        cuota:o.cuota_decimal, ev:o.ev, kelly:o.kelly, pocos:p.pocos }));
    const m = p.mercado;
    if (m && m.lado && m.ev > 0)
      out.push({ orden:1, tier:'B', pelea:`${p.a} vs ${p.b}`,
        que:`Gana ${m.lado==='A'?p.a:p.b}`,
        cuota:m.cuota, ev:m.ev, kelly:m.kelly, pocos:p.pocos });
  });
  return out.sort((x,y) => x.orden - y.orden || y.ev - x.ev);
}

// La pelea estelar, si se puede saber con certeza: el CSV la rotula "Estelar",
// o los dos apellidos de UNA pelea están en el nombre de la cartelera
// ("gamrot_vs_salkilld"). Si no, ninguna: mejor sin octágono que en la pelea
// equivocada.
const plano = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
function estelar(peleas, textos) {
  const porSegmento = peleas.filter(p => /^\s*(estelar|main event)\b/i.test(p.segmento || ''));
  if (porSegmento.length) return porSegmento.length === 1 ? porSegmento[0].id : null;
  const palabras = new Set(plano(textos.join(' ')).split(' '));
  const apellido = (n) => plano(n).split(' ').pop();
  const cand = peleas.filter(p => palabras.has(apellido(p.a)) && palabras.has(apellido(p.b)));
  return cand.length === 1 ? cand[0].id : null;
}

// La coestelar: la que el CSV rotula "Co-estelar"; si no hay rótulo, la vecina
// de la estelar en el orden de la cartelera (que va de la estelar hacia abajo o
// al revés). Solo si la estelar está en una punta: si no, no hay orden que
// leer. En ese caso va en octágono pero sin decir "Co-estelar".
const esCoSegmento = (p) => /^\s*co[\s-]?(estelar|main)/i.test(p.segmento || '');
function coestelar(peleas, idEstelar) {
  const porSegmento = peleas.filter(esCoSegmento);
  if (porSegmento.length) return porSegmento.length === 1 ? porSegmento[0].id : null;
  const i = peleas.findIndex(p => p.id === idEstelar);
  if (i < 0 || peleas.length < 3) return null;
  if (i === 0) return peleas[1].id;
  if (i === peleas.length - 1) return peleas[i - 1].id;
  return null;
}

const claseConf = (c) => c.toLowerCase().replace(/\s+/g,'');
const td = (t) => `<td class="num">${t}</td>`;
function flecha(mov, id, lado) {
  const m = mov[`${id}:ML:${lado}`];
  if (!m || m.antes === m.ahora) return '';
  return `<span class="mov" title="antes ${cuota(m.antes)}">${m.ahora > m.antes ? '▲' : '▼'}</span>`;
}
const peleasUFC = (info) => {
  if (!info || info.n_peleas_hist == null) return '';
  const n = Number(info.n_peleas_hist);
  return n === 0 ? 'ninguna pelea en UFC' : `${n} pelea${n === 1 ? '' : 's'} en UFC`;
};

// Las filas en espejo: lo mismo para cada esquina, enfrentado por el medio.
function espejo(p, mov) {
  const m = p.mercado;
  if (!m) return '';
  const fila = (a, lbl, b) => `<div><b>${a}</b><span>${lbl}</span><b class="r">${b}</b></div>`;
  return `<div class="espejo">
    ${fila(cuota(m.cuota_a) + flecha(mov, p.id, 'A'), 'cuota', cuota(m.cuota_b) + flecha(mov, p.id, 'B'))}
    ${fila(pct(m.p_mercado_a), 'le da la casa', pct(1 - m.p_mercado_a))}
    ${fila(pct(m.p_modelo_a), 'el modelo solo', pct(1 - m.p_modelo_a))}
  </div>`;
}

function barraDuelo(p) {
  const favA = p.p_a >= p.p_b;
  return `<div class="duelo-barra" role="img" aria-label="${esc(p.a)} ${pct(p.p_a)}, ${esc(p.b)} ${pct(p.p_b)}">
    <i class="${favA ? 'fav' : ''}" style="width:${p.p_a * 100}%"></i><i class="${favA ? '' : 'fav'}" style="width:${p.p_b * 100}%"></i></div>`;
}

function metodoFila(p) {
  const met = [['KO/TKO','KO/TKO'],['Submission','Sumisión'],['Decision','Decisión']];
  const maxMet = Math.max(...met.map(([k]) => p.metodo[k] || 0));
  return `<div class="metodo">${met.map(([k, lbl]) => {
    const v = p.metodo[k] || 0;
    return `<div class="${v === maxMet ? 'top' : ''}"><span class="mv">${fmt(v * 100, 0)}${NBSP_FINO}%</span><span class="mk">${lbl}</span>
      <span class="mbar"><i style="width:${v * 100}%"></i></span></div>`;
  }).join('')}</div>`;
}

// En el octágono el "% de que no llegue a las tarjetas" ya va en la lona.
function piePelea(p, enLona = false) {
  const m = p.mercado;
  return `<div class="pelea-pie">
    <span class="${enLona ? 'fin-angosto' : ''}"><b>${pct(p.p_finish,0)}</b> de que no llegue a las tarjetas</span>
    <span>${p.tendencia === 'pelea promedio'
      ? 'Nada la distingue de una pelea promedio'
      : `Más propensa a terminar así que lo normal: <b>${esc(p.tendencia)}</b>`}</span>
    ${m ? `<span>Comisión de la casa: <b>${pct(m.vig)}</b></span>` : ''}
  </div>`;
}

const selloConf = (p) => `<span class="pill ${claseConf(p.confianza)}">${p.confianza}</span>
  <button class="btn-q" data-explica="${p.id}" title="¿Qué significa?" aria-label="¿Qué significa ${esc(p.confianza)}?">?</button>`;

function tarjetaPelea(p, mov) {
  const favA = p.p_a >= p.p_b;
  return `
  <article class="pelea">
    <div class="cara-top">${p.segmento ? `<span class="cara-seg">${esc(p.segmento)}</span>` : ''}${selloConf(p)}</div>
    <div class="cara">
      ${retrato(p.a)}
      <div class="centro">
        <div class="vs-nombres"><span class="n">${esc(p.a)}</span><span class="x">vs</span><span class="n b">${esc(p.b)}</span></div>
        <div class="vs-sub"><span>${peleasUFC(p.info_a)}</span><span>${peleasUFC(p.info_b)}</span></div>
        <div class="pcts"><span class="${favA ? '' : 'menos'}">${pct(p.p_a)}</span><span class="${favA ? 'menos' : ''}">${pct(p.p_b)}</span></div>
        ${barraDuelo(p)}
        ${espejo(p, mov)}
      </div>
      ${retrato(p.b)}
    </div>
    ${metodoFila(p)}
    ${piePelea(p)}
    ${p.confianza === 'NO FIABLE' ? `<div class="explica alerta">${ico('alerta')}<div>${p.por_que_confianza}</div></div>` : ''}
  </article>`;
}

// La línea pintada a un paso de la reja, paralela a ella: es un octágono
// regular, con el corte un poco menor porque la línea va metida hacia adentro
// (misma cuenta que los recortes de las capas en el CSS).
function lineaLona() {
  const k = ((29.29 - 1.16 - 0.414 * 2) / (100 - 5.6 - 4) * 100).toFixed(2);
  const pts = `${k},0.5 ${100 - k},0.5 99.5,${k} 99.5,${100 - k} ${100 - k},99.5 ${k},99.5 0.5,${100 - k} 0.5,${k}`;
  return `<svg class="lona-linea" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
    <polygon points="${pts}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

// Las dos peleas principales van DENTRO del octágono: la reja, la baranda con
// sus ocho postes, la lona con su luz y, sobre ella, los dos retratos y los
// números. Es un octágono regular y todo escala con su ancho.
function jaula(p, mov, tipo) {
  const favA = p.p_a >= p.p_b;
  const titulo = tipo === 'estelar' ? 'Pelea estelar' : (esCoSegmento(p) ? 'Co-estelar' : '');
  const postes = [1,2,3,4,5,6,7,8].map(n => `<i class="poste p${n}"></i>`).join('');
  return `
  <article class="estelar ${tipo}">
    <header class="estelar-cab">
      ${titulo ? `<span class="estelar-kicker">${titulo}${p.segmento ? ` <small>${esc(p.segmento)}</small>` : ''}</span>`
               : (p.segmento ? `<span class="cara-seg">${esc(p.segmento)}</span>` : '')}
      <span class="sellos">${selloConf(p)}</span>
    </header>
    <div class="jaula-escena"><div class="jaula">
      <div class="reja"></div><div class="baranda"></div>${postes}
      <div class="lona">
        ${lineaLona()}
        <svg class="lona-marca" viewBox="0 0 32 32" aria-hidden="true">
          <path d="M9 2h14l7 7v14l-7 7H9l-7-7V9z" fill="none" stroke="currentColor" stroke-width="1.6"/>
          <path d="M11 22L15 10h7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="bevel"/></svg>
        ${retrato(p.a).replace('class="retrato"', 'class="retrato a"')}
        <div class="jaula-centro">
          <div class="vs-nombres"><span class="n">${esc(p.a)}</span><span class="x">vs</span><span class="n b">${esc(p.b)}</span></div>
          <div class="vs-sub"><span>${peleasUFC(p.info_a)}</span><span>${peleasUFC(p.info_b)}</span></div>
          <div class="pcts"><span class="${favA ? '' : 'menos'}">${pct(p.p_a)}</span><span class="${favA ? 'menos' : ''}">${pct(p.p_b)}</span></div>
          ${barraDuelo(p)}
          ${espejo(p, mov)}
          <p class="lona-pie"><b>${pct(p.p_finish,0)}</b> de que no llegue a las tarjetas</p>
        </div>
        ${retrato(p.b).replace('class="retrato"', 'class="retrato b"')}
      </div>
    </div></div>
    ${metodoFila(p)}
    ${piePelea(p, true)}
    ${p.confianza === 'NO FIABLE' ? `<div class="explica alerta">${ico('alerta')}<div>${p.por_que_confianza}</div></div>` : ''}
  </article>`;
}

function mejorMetodo(m) {
  const k = Object.keys(m).reduce((a,b) => m[a] > m[b] ? a : b);
  const n = {'KO/TKO':'KO/TKO','Submission':'sumisión','Decision':'decisión'}[k];
  return `${n} (${fmt(m[k]*100, 0)}${NBSP_FINO}%)`;
}
function tabla(sel, cab, filas) {
  $(sel).innerHTML =
    `<thead><tr>${cab.map(h=>`<th>${h}</th>`).join('')}</tr></thead>` +
    `<tbody>${filas.map(f=>`<tr>${f.map(c =>
      String(c).startsWith('<td') ? c : `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

/* ============================== PARLAY ================================ */
function pintarTiers(tiers) {
  if (!tiers) return;
  const orden = ['A','B','C'];
  const nombres = {A:'Probado', B:'Sin ventaja clara', C:'Ruido'};
  $('#explica-tiers').innerHTML = orden.map(k => `
    <div class="tier-mini">
      <span class="pill t${k}">${nombres[k]}</span>
      <p>${esc(tiers[k].detalle)}</p>
    </div>`).join('');
}

$$('.filtro-tier').forEach(c => c.onchange = pintarPatas);
$('#solo-positivo').onchange = pintarPatas;
$('#btn-limpiar').onclick = () => { S.elegidas = []; pintarPatas(); evaluarParlay(); };
$('#btn-sugerir').onclick = () => {
  S.elegidas = (S.datos?.sugerencia || []).slice();
  if (!S.elegidas.length) barra('No hay ninguna selección con respaldo y con valor en esta cartelera. Es lo normal, no un error.');
  pintarPatas(); evaluarParlay();
};
$('#bankroll').oninput = () => evaluarParlay();

// Tocar el nombre de la cartelera lleva a elegir otra: es donde el usuario
// mira cuando quiere cambiarla, más que en una pestaña.
$('#titulo-cartelera').onclick = () => irA('datos');

$('#btn-soltar').onclick = async () => {
  try {
    await post('/api/limpiar');
    S.datos = null; S.patas = []; S.elegidas = [];
    carterasCargadas = false;          // que vuelva a consultar Betano
    barra('Cartelera soltada. Elige otra abajo.');
    irA('datos');
  } catch (e) { barra(e.message, 'error'); }
};

// Los desenlaces elementales que cubre cada selección. Es lo mismo que
// parlay._COBERTURA en el backend, replicado acá para poder explicar el choque
// SIN ir al servidor en cada clic. Si agregas un mercado, actualiza los dos.
const COBERTURA = {
  'ganador:A'      : ['A_KO','A_SUB','A_DEC'],
  'ganador:B'      : ['B_KO','B_SUB','B_DEC'],
  'metodo7:A_KO'   : ['A_KO'],   'metodo7:A_SUB': ['A_SUB'], 'metodo7:A_DEC': ['A_DEC'],
  'metodo7:B_KO'   : ['B_KO'],   'metodo7:B_SUB': ['B_SUB'], 'metodo7:B_DEC': ['B_DEC'],
  'metodo5:A_FIN'  : ['A_KO','A_SUB'], 'metodo5:A_DEC': ['A_DEC'],
  'metodo5:B_FIN'  : ['B_KO','B_SUB'], 'metodo5:B_DEC': ['B_DEC'],
};

function cubre(p) { return COBERTURA[`${p.mercado}:${p.clase}`] || []; }

// null si se pueden combinar; si no, por qué chocan.
function conflicto(a, b) {
  if (a.fight_id !== b.fight_id) return null;
  const ca = cubre(a), cb = cubre(b);
  const cruzan = ca.some(x => cb.includes(x));
  return cruzan ? 'similar' : 'excluyente';
}

function pintarPatas() {
  const tiers = $$('.filtro-tier').filter(c => c.checked).map(c => c.value);
  const soloPos = $('#solo-positivo').checked;
  const elegidas = S.patas.filter(p => S.elegidas.includes(p.id));
  const lista = S.patas.filter(p => tiers.includes(p.tier) && (!soloPos || p.ev > 0));

  // Motivo del bloqueo, por pata: el choque concreto contra lo ya elegido.
  const bloqueo = {};
  for (const p of lista) {
    if (S.elegidas.includes(p.id)) continue;
    for (const e of elegidas) {
      const c = conflicto(p, e);
      if (c) { bloqueo[p.id] = { tipo: c, contra: e }; break; }
    }
  }

  const V = { si:['si','✓','Conviene'], quizas:['quizas','~','Se puede'], no:['no','✕','No conviene'] };

  const tarjeta = p => {
    const on = S.elegidas.includes(p.id);
    const bl = bloqueo[p.id];
    const [k, ico, lbl] = V[p.veredicto] || V.no;
    const aviso = bl
      ? `<div class="choque">${bl.tipo === 'excluyente'
          ? '✕ Imposible junto con lo que ya elegiste: no pueden pasar las dos.'
          : '≈ Se solapa con lo que ya elegiste: Betano casi no sube la cuota al combinarlas.'}</div>`
      : '';
    return `<div class="pata ${on?'elegida':''} ${bl?'bloqueada':''}" data-id="${p.id}">
      <div class="top">
        <div>
          <div class="sel">${esc(p.seleccion)}</div>
          <div class="meta">
            <span class="pill n-${p.nivel}" title="${esc(p.nivel_detalle)}">${esc(p.nivel)}</span>
            <span class="pill t${p.tier}" title="Esto habla del PRECIO, no de la probabilidad: ${esc(p.tier_detalle)}">${esc(p.tier_nombre)}</span>
          </div>
          <div class="probs">
            <span title="Lo que dice el modelo por su cuenta, sin mirar la cuota">
              modelo <b>${p.p_modelo != null ? pct(p.p_modelo) : 'sin dato'}</b></span>
            <span title="El modelo combinado con la línea de la casa. Es la estimación más certera de las dos (~70% de acierto contra 67%).">
              con la cuota <b>${pct(p.p)}</b></span>
          </div>
        </div>
        <div class="precio">
          <span class="cuota">${cuota(p.cuota)}</span>
          <span class="ev ${cls(p.ev)}">${sgn(p.ev)}</span>
        </div>
      </div>
      <div class="porque"><b class="${k}">${ico} ${lbl}.</b> ${esc(p.por_que)}</div>
      ${aviso}
    </div>`;
  };

  // --- Agrupado por MERCADO -------------------------------------------------
  // Son mercados distintos en Betano, con precios y reglas distintas. En una
  // sola lista era imposible ver, por ejemplo, que una pelea con 5 vías
  // simplemente no ofrece KO por separado.
  const mercados = S.datos?.mercados || {};
  const orden = Object.keys(mercados).sort((a,b) => mercados[a].orden - mercados[b].orden);

  const secciones = orden.map(clave => {
    const patas = lista.filter(p => p.mercado === clave);
    if (!patas.length) return '';
    const m = mercados[clave];

    // Dentro del mercado se agrupa por PELEA y las opciones van lado a lado.
    // Antes salían una debajo de otra y había que subir y bajar para ver quién
    // peleaba contra quién; enfrentadas se leen de un vistazo y se nota al toque
    // que elegir una bloquea a la otra.
    const porPelea = new Map();
    patas.forEach(p => {
      if (!porPelea.has(p.fight_id)) porPelea.set(p.fight_id, []);
      porPelea.get(p.fight_id).push(p);
    });

    const grupos = Array.from(porPelea.values()).map(ps => `
      <div class="pelea-grupo">
        <div class="pelea-grupo-cab">${esc(ps[0].pelea)}</div>
        <div class="pelea-grupo-opciones">${ps.map(tarjeta).join('')}</div>
      </div>`).join('');

    return `<section class="mercado-bloque">
      <header class="mercado-cab">
        <h3>${esc(m.nombre)} <span class="cuenta">${patas.length}</span></h3>
        <p>${esc(m.descripcion)}</p>
      </header>
      ${grupos}
    </section>`;
  }).filter(Boolean).join('');

  $('#lista-patas').innerHTML = secciones || `<p class="nota">No hay selecciones con
    esos filtros. Prueba activando más categorías arriba.</p>`;

  $$('#lista-patas .pata').forEach(el => el.onclick = () => {
    const id = el.dataset.id;
    const bl = bloqueo[id];
    if (bl) {
      const p = S.patas.find(x => x.id === id);
      barra(bl.tipo === 'excluyente'
        ? `"${p.seleccion}" y "${bl.contra.seleccion}" no pueden pasar las dos a la vez, así que ninguna casa acepta esa combinada.`
        : `"${p.seleccion}" ya está contenida en "${bl.contra.seleccion}". Betano casi no sube la cuota al combinarlas (a veces ni la sube) porque estarías pagando dos veces por la misma información.`);
      return;
    }
    const i = S.elegidas.indexOf(id);
    if (i >= 0) S.elegidas.splice(i,1);
    else if (S.elegidas.length >= 13) { barra('Betano acepta un máximo de 13 selecciones.'); return; }
    else S.elegidas.push(id);
    pintarPatas(); evaluarParlay();
  });

  $('#cuenta-patas').textContent = `${S.elegidas.length}/13`;
  const byId = Object.fromEntries(S.patas.map(p => [p.id,p]));
  $('#boleto').innerHTML = S.elegidas.length
    ? S.elegidas.map(id => { const p = byId[id];
        return `<div class="boleto-item">
          <span>${esc(p.seleccion)}<br><span class="sub">${esc(p.pelea)}</span></span>
          <span class="boleto-cuota"><b>${cuota(p.cuota)}</b>
            <button data-q="${id}" title="Quitar">×</button></span>
        </div>`; }).join('')
    : `<div class="boleto-vacio">Toca una selección de la izquierda para agregarla.</div>`;
  $$('#boleto button').forEach(b => b.onclick = (ev) => {
    ev.stopPropagation();
    S.elegidas = S.elegidas.filter(x => x !== b.dataset.q);
    pintarPatas(); evaluarParlay();
  });
}

async function evaluarParlay() {
  const out = $('#parlay-resultado');
  if (S.elegidas.length < 2) {
    out.innerHTML = `<p class="nota">Elige al menos 2 selecciones.<br><br>
      Recuerda que una combinada <b>multiplica el error</b> de cada pronóstico:
      si cada uno está un poco inflado, juntos pueden estarlo mucho. Por eso este
      sistema prefiere apuestas simples y combinadas cortas.</p>`;
    return;
  }
  try {
    const r = await post('/api/parlay', {
      ids:S.elegidas, bankroll: parseFloat($('#bankroll').value) || 100 });
    if (!r.ok) { out.innerHTML = `<div class="aviso err"><span class="ai">✕</span>
      <div>${esc(r.error)}</div></div>`; return; }

    out.innerHTML = `
      <div class="veredicto ${r.nivel}">${esc(r.veredicto)}</div>
      <div class="metricas">
        <div class="metrica"><div class="k">Paga</div>
          <div class="v">${cuota(r.cuota_combinada)}×</div>
          <div class="expl">$1.000 se convierten en $${miles(Math.round(r.pago_por_1000))}</div></div>
        <div class="metrica"><div class="k">Valor</div>
          <div class="v ${cls(r.ev)}">${sgn(r.ev)}</div>
          <div class="expl">ganancia esperada por peso, a muy largo plazo</div></div>
        <div class="metrica"><div class="k">Chance de cobrar</div>
          <div class="v">${pct(r.p_combinada,2)}</div>
          <div class="expl">1 de cada ${miles(r.una_de_cada)} intentos</div></div>
        <div class="metrica"><div class="k">Cuánto apostar</div>
          <div class="v">${miles(r.stake_sugerido)}</div>
          <div class="expl">${pct(r.kelly)} de tu bankroll.
            ${r.kelly < 0.005
              ? '<b>Prácticamente cero: así es como el sistema dice que no apuestes esto.</b> Una combinada que sí convenga suele quedar entre el 1 % y el 4 %.'
              : 'Sobre el total que apartaste para apostar, no sobre esta apuesta.'}</div></div>
        <div class="metrica destacada">
          <div class="k">Margen de error que aguanta</div>
          <div class="v ${r.error_tolerable >= r.umbral_fragil ? 'pos':'neg'}">${pct(r.error_tolerable,1)}</div>
          <div class="expl">Es lo que puede estar equivocado <b>cada</b> pronóstico antes de
            que la combinada pase a perder, y las ${r.n_patas} tienen que cumplirlo
            <b>a la vez</b>. Con ${r.n_patas} selecciones lo sano sería
            ${pct(r.umbral_fragil,1)}. Este modelo se equivoca de verdad, así que el
            margen no es un detalle teórico: es el número que decide si la combinada
            se sostiene.</div></div>
      </div>
      <ul class="motivos">${r.motivos.map(m=>`<li>${esc(m)}</li>`).join('')}</ul>`;
  } catch (e) { out.innerHTML = `<div class="aviso err"><span class="ai">✕</span>
    <div>${esc(e.message)}</div></div>`; }
}

/* ============================== CARGAR ================================ */
$('#btn-refresh').onclick = async () => {
  try { await post('/api/refrescar'); barra('refrescando cuotas…'); }
  catch (e) { barra(e.message,'error'); }
};

// Carteleras de Betano: se listan SOLAS al entrar a la pestaña y cada una
// predice con un clic. Antes había que apretar un botón, leer los nombres y
// escribir el nombre a mano en el campo de abajo: tres pasos para algo que
// Betano ya nos está diciendo.
let carterasCargadas = false;

async function listarCarteleras(forzar) {
  const div = $('#lista-carteleras');
  if (carterasCargadas && !forzar) return;
  carterasCargadas = true;
  div.innerHTML = '<p class="nota">consultando Betano…</p>';
  try {
    const r = await api('/api/betano/carteleras');
    if (!r.carteleras.length) {
      div.innerHTML = '<p class="nota">Betano no está listando carteleras de MMA ahora mismo.</p>';
      return;
    }
    div.innerHTML = r.carteleras.map(c => {
      const d = c.dias;
      const cuando = d === null || d === undefined ? ''
        : d === 0 ? 'HOY' : d === 1 ? 'MAÑANA' : d > 0 ? `en ${d} días` : 'ya pasó';
      // Betano abre algunas carteleras con solo un par de peleas montadas.
      // Avisarlo evita la sorpresa de bajar una cartelera "vacía".
      const parcial = c.peleas && c.peleas <= 4
        ? `<span class="cart-parcial">solo ${c.peleas} peleas montadas todavía</span>` : '';
      return `<button class="cart" data-q="${esc(c.query || c.name)}"
                      data-fecha="${esc(c.fecha || '')}">
        <span class="cart-cuando">${esc(cuando)}</span>
        <span class="cart-cuerpo">
          <b>${esc(c.estelar || c.name)}</b>
          <span class="cart-meta">${esc(c.name)}${c.peleas ? ` · ${c.peleas} peleas` : ''}${
            c.fecha ? ` · ${esc(c.fecha)}` : ''}</span>
          ${parcial}
        </span>
        <span class="cart-ir">Predecir →</span>
      </button>`;
    }).join('');

    div.querySelectorAll('.cart').forEach(b => b.onclick = async () => {
      try {
        await post('/api/cartelera/betano',
                   { query: b.dataset.q, fecha: b.dataset.fecha || null });
        barra('bajando cuotas y prediciendo… puede tardar un minuto.');
        irA('cartelera');
      } catch (e) { barra(e.message, 'error'); }
    });
  } catch (e) {
    div.innerHTML = `<div class="aviso err"><span class="ai">✕</span>
      <div>${esc(e.message)}</div></div>`;
    carterasCargadas = false;   // que se pueda reintentar
  }
}

$('#btn-listar').onclick = () => listarCarteleras(true);

$('#btn-cargar-betano').onclick = async () => {
  const q = $('#query').value.trim();
  if (!q) { barra('Escribe parte del nombre de la cartelera, o toca "Ver qué carteleras hay".','error'); return; }
  try {
    await post('/api/cartelera/betano', { query:q });
    barra('bajando cuotas de Betano… puede tardar un minuto.'); irA('cartelera');
  } catch (e) { barra(e.message,'error'); }
};

$('#btn-subir').onclick = async () => {
  const f = $('#archivo').files[0];
  if (!f) { barra('Primero elige un archivo .csv','error'); return; }
  const fd = new FormData(); fd.append('archivo', f);
  try {
    await api('/api/cartelera/subir', { method:'POST', body:fd });
    barra('analizando la cartelera…'); irA('cartelera');
  } catch (e) { barra(e.message,'error'); }
};

async function cargarCSVs() {
  try {
    const r = await api('/api/cards');
    $('#lista-csvs').innerHTML = r.cards.length
      ? r.cards.slice(0,12).map(c => `<div class="pick"><div class="cab">
          <b>${esc(c.nombre)}</b>
          <button class="secundario" data-n="${esc(c.nombre)}">Analizar</button></div>
          <div class="det">${new Date(c.modificado*1000).toLocaleString('es-CL')}</div></div>`).join('')
      : '<p class="nota">Todavía no hay ninguna cartelera guardada.</p>';
    $$('#lista-csvs button').forEach(b => b.onclick = async () => {
      try { await post('/api/cartelera/csv', { nombre:b.dataset.n });
            barra('analizando la cartelera…'); irA('cartelera'); }
      catch (e) { barra(e.message,'error'); }
    });
  } catch (e) { $('#lista-csvs').innerHTML = `<div class="aviso err"><span class="ai">✕</span>
    <div>${esc(e.message)}</div></div>`; }
}

/* =========================== MANTENIMIENTO ============================ */
const NOMBRES_SALUD = {
  modelo_ganador:'modelo de ganador', modelo_metodo:'modelo de método',
  modelo_metodo6:'mercado de método', calibrador_mercado:'calibrador de ganador',
  calibrador_metodo:'calibrador de método', features:'base de datos',
};

async function cargarTareas() {
  const [t,s] = await Promise.all([api('/api/tareas'), api('/api/salud')]);
  $('#salud').innerHTML =
    Object.entries(NOMBRES_SALUD).map(([k,lbl]) => {
      const hay = s[k]?.existe;
      return `<div class="chip ${hay?'hay':'falta'}"><span class="cm">${hay?'✓':'✕'}</span> ${lbl}</div>`;
    }).join('') +
    `<div class="chip hay">entrena con los últimos ${s.ventana_anios} años</div>` +
    `<div class="chip hay">${miles(s.simulaciones)} simulaciones por pelea</div>`;

  $('#lista-tareas').innerHTML = t.recetas.map(r => `
    <div class="tarea">
      <h4>${esc(r.nombre)}</h4>
      <p>${esc(r.descripcion)}</p>
      <span class="tiempo">${esc(r.minutos)}${r.pasos>1?` · ${r.pasos} pasos`:''}</span>
      <button class="primario" data-r="${r.id}" ${t.ocupado?'disabled':''}>Ejecutar</button>
    </div>`).join('');
  $$('#lista-tareas button').forEach(b => b.onclick = async () => {
    try {
      const r = await post('/api/tareas/lanzar', { receta:b.dataset.r });
      S.job = r.job; S.logLeidas = 0; $('#log').textContent = '';
      $('#btn-cancelar').classList.remove('oculto');
      cargarTareas();
    } catch (e) { barra(e.message,'error'); }
  });
}

async function seguirJob() {
  try {
    const j = await api(`/api/tareas/${S.job}?desde=${S.logLeidas}`);
    if (j.lineas.length) {
      const log = $('#log');
      const abajo = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      log.textContent += j.lineas.join('\n') + '\n';
      S.logLeidas = j.n_lineas;
      if (abajo) log.scrollTop = log.scrollHeight;
    }
    const paso = j.total_pasos > 1 ? ` · paso ${j.paso} de ${j.total_pasos}` : '';
    $('#job-estado').textContent = `${j.nombre}: ${j.estado}${paso} · ${j.segundos}${NBSP_FINO}s`;
    if (j.estado !== 'corriendo') {
      S.job = null;
      $('#btn-cancelar').classList.add('oculto');
      cargarTareas();
      barra(j.estado==='ok' ? `"${j.nombre}" terminó correctamente.`
                            : `"${j.nombre}" terminó con estado: ${j.estado}. Revisa el registro.`,
            j.estado==='ok' ? '' : 'error');
      setTimeout(() => barra(''), 8000);
    }
  } catch { S.job = null; }
}

$('#btn-cancelar').onclick = () => S.job && post(`/api/tareas/${S.job}/cancelar`);

/* ====================== BARRA SUPERIOR AL HACER SCROLL ================= */
/* Al bajar se esconde entera (cabecera + pestañas) para dejar la pantalla a la
   cartelera; al subir aunque sea un poco, vuelve. El umbral evita que
   parpadee con el rebote del scroll o con movimientos de un par de píxeles. */
(() => {
  const barra = $('#barra-superior');
  const UMBRAL = 8;      // px que hay que mover para que reaccione
  const LIBRE  = 90;     // arriba del todo siempre se muestra
  let ultimo = window.scrollY;
  let ultimoTick = 0;

  const evaluar = () => {
    const y = window.scrollY;
    const delta = y - ultimo;
    if (Math.abs(delta) <= UMBRAL) return;
    // Nunca esconderla cerca del tope, ni con un modal abierto (ahí el fondo no
    // scrollea y esconderla dejaría la página descabezada al cerrarlo).
    const ocultar = delta > 0 && y > LIBRE && $('#modal').classList.contains('oculto');
    barra.classList.toggle('oculta', ocultar);
    // El boleto del parlay es sticky y se posiciona bajo la barra: si la barra
    // se fue, puede subir también en vez de dejar un hueco.
    document.documentElement.style.setProperty('--tope', ocultar ? '0px' : barra.offsetHeight + 'px');
    ultimo = y;
  };

  // Throttle por tiempo y no con requestAnimationFrame: rAF no corre cuando la
  // pestaña está oculta, y un latch booleano esperando un frame que no llega
  // deja el handler mudo. Leer scrollY no fuerza layout, así que 60 ms sobra.
  addEventListener('scroll', () => {
    const ahora = performance.now();
    if (ahora - ultimoTick < 60) return;
    ultimoTick = ahora;
    evaluar();
  }, { passive: true });

  // Cambiar de pestaña vuelve al tope: la barra tiene que reaparecer.
  $$('.tab').forEach(t => t.addEventListener('click', () => {
    barra.classList.remove('oculta');
    document.documentElement.style.setProperty('--tope', barra.offsetHeight + 'px');
    ultimo = 0;
  }));
})();

/* ============================== ARRANQUE ============================== */
tick();
reloj();
