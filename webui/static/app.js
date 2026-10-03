/* UFC Predictor — interfaz
   Sin frameworks ni CDN a propósito: corre en tu PC y tiene que abrir aunque no
   haya internet, que es justo cuando quieres mirar una cartelera ya bajada.

   Criterio de diseño: cada número que se muestra viene acompañado de qué
   significa. El usuario no debería tener que preguntar qué es "NO FIABLE". */

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const S = { datos:null, patas:[], elegidas:[], job:null, logLeidas:0,
            proximoAuto:null, origen:'', vista:'tarjetas', carga:null, cargaRecibida:0 };

const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const txt = await r.text();
  let body; try { body = JSON.parse(txt); } catch {
    body = { detail: /^\s*</.test(txt)
      ? `El servidor devolvió una página de error (HTTP ${r.status}). Comprueba que esté iniciado el backend de UFC Predictor.`
      : txt };
  }
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
$$('[data-ico]').forEach(e => { e.outerHTML = ico(e.dataset.ico, e.className); });

/* ============================ MOVIMIENTO ============================== */
// Las mismas dos curvas que el CSS (--ease-out, --ease-in-out). Con "reducir
// movimiento" no se desplaza ni se escala nada, pero los fundidos se quedan:
// ayudan a entender qué cambió y no marean.
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)';
const EASE_IN_OUT = 'cubic-bezier(0.77, 0, 0.175, 1)';
const reducir = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
// Lo que se hace con el teclado no se anima: se repite tanto que el movimiento
// lo haría sentir lento. Se anota con qué se hizo lo último (tecla o puntero)
// y las acciones del usuario lo consultan. Lo que hace el sistema solo (EN
// VIVO) se anima igual: no depende de cómo navegas.
let porTeclado = false;
addEventListener('keydown', () => { porTeclado = true; }, true);
addEventListener('pointerdown', () => { porTeclado = false; }, true);

// Cada cifra que puede cambiar lleva data-num con una clave estable. Antes de
// repintar se anota lo que decía; después, la que cambió entra desde abajo y
// deja un destello que se apaga. Solo se mueve con transform y opacity, y las
// cifras son tabulares: nada alrededor se corre.
const capturarCifras = (raiz) => new Map(
  Array.from(raiz.querySelectorAll('[data-num]'), e => [e.dataset.num, e.textContent]));
function resaltarCambios(raiz, antes) {
  const cambiadas = Array.from(raiz.querySelectorAll('[data-num]')).filter(e => {
    const previo = antes.get(e.dataset.num);
    return previo != null && previo !== e.textContent;
  });
  if (!cambiadas.length) return;
  // Para reiniciar el destello de una cifra que ya lo tenía hay que sacar la
  // clase, forzar un reflow y volver a ponerla. Un solo reflow para todas, no
  // uno por cifra (eso obligaba al navegador a recalcular el layout N veces).
  cambiadas.forEach(e => e.classList.remove('destello'));
  void raiz.offsetWidth;
  cambiadas.forEach(e => {
    e.animate(reducir()
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [{ opacity: 0, transform: 'translateY(35%)' }, { opacity: 1, transform: 'none' }],
      { duration: 220, easing: EASE_OUT });
    e.classList.add('destello');
  });
}

/* ============================== OPCIONES ============================== */
// El estilo (la transmisión o la tarjeta del juez) y el tema se guardan en este
// navegador. Sin tema elegido, la página sigue al del sistema. localStorage
// puede no estar (ventana privada, sitio bloqueado): entonces simplemente no
// se recuerda, pero todo funciona.
const leer = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const guardar = (k, v) => {
  try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* sin memoria */ }
};
const raizDoc = document.documentElement;
const esJuez = () => raizDoc.dataset.estilo === 'juez';
function aplicarTema(t) {
  if (t === 'claro' || t === 'oscuro') raizDoc.dataset.tema = t; else delete raizDoc.dataset.tema;
}
function aplicarEstilo(e) {
  if (e === 'juez') raizDoc.dataset.estilo = 'juez'; else delete raizDoc.dataset.estilo;
}
aplicarTema(leer('tema'));
aplicarEstilo(leer('estilo'));
$(`input[name="tema"][value="${raizDoc.dataset.tema || 'auto'}"]`).checked = true;
$(`input[name="estilo"][value="${esJuez() ? 'juez' : 'transmision'}"]`).checked = true;

const btnOpciones = $('#btn-opciones'), panelOpciones = $('#panel-opciones');
// Se despliega desde el botón (arriba a la derecha) y se cierra con Esc, con
// un clic afuera o con el mismo botón. Con teclado, sin animación.
function abrirOpciones(abrir) {
  panelOpciones.classList.toggle('oculto', !abrir);
  btnOpciones.setAttribute('aria-expanded', abrir);
  if (!abrir) return;
  panelOpciones.querySelector('input:checked')?.focus();
  if (!porTeclado) panelOpciones.animate(reducir()
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ opacity: 0, transform: 'scale(0.97)' }, { opacity: 1, transform: 'none' }],
    { duration: 150, easing: EASE_OUT });
}
btnOpciones.onclick = () => abrirOpciones(panelOpciones.classList.contains('oculto'));
document.addEventListener('click', (e) => {
  if (!panelOpciones.classList.contains('oculto') && !e.target.closest('.opciones')) abrirOpciones(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || panelOpciones.classList.contains('oculto')) return;
  abrirOpciones(false); btnOpciones.focus();
});
// Cambiar de tema o de estilo cambia toda la página en un cuadro. Con View
// Transitions se funde la página vieja en la nueva (200 ms, solo opacidad, así
// que vale también con movimiento reducido). Con teclado, o en un navegador
// sin View Transitions, el cambio es instantáneo como antes.
function conFundido(cambio) {
  if (porTeclado || typeof document.startViewTransition !== 'function') return cambio();
  document.startViewTransition(cambio);
}
$$('input[name="tema"]').forEach(r => r.onchange = () => {
  conFundido(() => aplicarTema(r.value));
  guardar('tema', r.value === 'auto' ? null : r.value);
});
$$('input[name="estilo"]').forEach(r => r.onchange = () => {
  guardar('estilo', r.value === 'juez' ? 'juez' : null);
  conFundido(() => { aplicarEstilo(r.value); repintarEstilo(); });
});
// Cambiar de estilo cambia cómo se arma cada pelea (octágono o acta), así que
// la cartelera se vuelve a pintar; sin animar nada, porque ningún dato cambió.
function repintarEstilo() {
  medirCabecera();
  if (!S.datos) return;
  const previo = S.previo;
  S.previo = null;
  pintarCartelera(S.datos, S.mov || {});
  S.previo = previo;
}

/* =============================== TABS ================================= */
const irA = (t) => $(`.tab[data-tab="${t}"]`).click();
// La etiqueta de la pestaña activa viaja de la vieja a la nueva, como el
// rótulo que se desliza en la gráfica de la tele. Con teclado o con menos
// movimiento, cambia en el lugar.
function viajarPestana(desde, hasta) {
  if (!desde || desde === hasta || porTeclado || reducir()) return;
  const tabs = $('.tabs');
  const r0 = desde.getBoundingClientRect(), r1 = hasta.getBoundingClientRect(), rt = tabs.getBoundingClientRect();
  if (!r0.width || !r1.width) return;
  const incl = getComputedStyle(raizDoc).getPropertyValue('--incl').trim() || '0deg';
  const fantasma = document.createElement('span');
  fantasma.className = 'tab-viaje';
  fantasma.style.left = (r1.left - rt.left + tabs.scrollLeft + 4) + 'px';
  fantasma.style.width = (r1.width - 8) + 'px';
  tabs.append(fantasma);
  tabs.classList.add('viajando');
  const viaje = fantasma.animate([
    { transform: `translateX(${r0.left - r1.left}px) skewX(-${incl}) scaleX(${(r0.width - 8) / (r1.width - 8)})` },
    { transform: `translateX(0) skewX(-${incl}) scaleX(1)` }],
    { duration: 300, easing: EASE_IN_OUT });
  // Al llegar, la etiqueta propia aparece de golpe bajo el fantasma y recién
  // ahí se quita: si apareciera con su transición, parpadearía.
  const fin = () => {
    if (!fantasma.isConnected) return;
    tabs.classList.add('llegando'); tabs.classList.remove('viajando');
    void tabs.offsetWidth;
    fantasma.remove(); tabs.classList.remove('llegando');
  };
  viaje.onfinish = fin; viaje.oncancel = fin;
  // Si la ventana queda en segundo plano a medio viaje, la animación se
  // congela: la pestaña nueva no puede quedarse sin su etiqueta.
  setTimeout(() => { viaje.cancel(); fin(); }, 450);
}
$$('.tab').forEach(t => t.onclick = () => {
  viajarPestana($('.tab.activa'), t);
  $$('.tab').forEach(x => { x.classList.remove('activa'); x.removeAttribute('aria-current'); });
  $$('.panel').forEach(x => x.classList.remove('activa'));
  t.classList.add('activa');
  t.setAttribute('aria-current', 'page');
  $('#tab-' + t.dataset.tab).classList.add('activa');
  // Con teclado, sin la entrada del panel ni el crecimiento de la etiqueta.
  if (porTeclado) [$('.tabs'), $('#tab-' + t.dataset.tab)].forEach(e =>
    e.getAnimations({ subtree: true }).forEach(a => a.finish()));
  window.scrollTo({ top: 0 });
  if (t.dataset.tab === 'mantenimiento') cargarTareas();
  if (t.dataset.tab === 'datos') { cargarCSVs(); listarCarteleras(); listarAnteriores(); }
  if (t.dataset.tab === 'inicio') cargarInicio();
});
$$('[data-ir]').forEach(b => b.onclick = () => irA(b.dataset.ir));

$$('.seg[data-vista]').forEach(b => b.onclick = () => {
  $$('.seg[data-vista]').forEach(x => x.classList.remove('activa'));
  b.classList.add('activa');
  const antes = S.vista;
  S.vista = b.dataset.vista;
  $('#peleas').classList.toggle('oculto', S.vista !== 'tarjetas');
  $('#tabla-wrap').classList.toggle('oculto', S.vista !== 'tabla');
  // La vista que entra se funde como un panel de pestaña (150 ms): antes una
  // desaparecía y la otra aparecía en el mismo cuadro. La que sale no se anima,
  // y con teclado el cambio es instantáneo.
  if (antes === S.vista || porTeclado) return;
  $(S.vista === 'tabla' ? '#tabla-wrap' : '#peleas').animate(reducir()
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }],
    { duration: 150, easing: EASE_OUT });
});

/* ============================== MODAL ================================= */
// Al abrir se lleva el foco a la × y al cerrar se devuelve a quien lo abrió:
// sin eso, con teclado, el foco quedaba detrás del velo.
let focoAntesDelModal = null;
// Entra con el velo fundiéndose y la caja creciendo apenas desde el centro (es
// un modal: no sale de ningún botón). Sale más rápido de lo que entra. Con el
// teclado (Esc, o Enter sobre un botón) abre y cierra al instante.
function modal(html) {
  const m = $('#modal');
  // Si se abre mientras el anterior todavía sale, esa salida se corta: al
  // terminar habría escondido el modal nuevo.
  m.getAnimations({ subtree: true }).forEach(a => a.cancel());
  delete m.dataset.cerrando;
  if (m.classList.contains('oculto')) focoAntesDelModal = document.activeElement;
  $('#modal-cuerpo').innerHTML = html;
  // El título del modal es su primer encabezado: es lo que lee un lector de
  // pantalla al abrirlo (antes leía el cuerpo entero).
  $('#modal-cuerpo').querySelector('h1,h2,h3')?.setAttribute('id', 'modal-titulo');
  // Todo lo de atrás queda inerte mientras está abierto: sin esto, Tab sacaba
  // el foco del modal y lo dejaba detrás del velo.
  $$('body > *').forEach(e => { if (e !== m && e.tagName !== 'SCRIPT') e.inert = true; });
  m.classList.remove('oculto');
  $('.modal-cerrar').focus();
  if (porTeclado) return;
  m.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: EASE_OUT });
  if (!reducir()) $('.modal-caja').animate(
    [{ opacity: 0, transform: 'scale(0.97)' }, { opacity: 1, transform: 'none' }],
    { duration: 200, easing: EASE_OUT });
}
function cerrarModal(alInstante = false) {
  const m = $('#modal');
  if (m.classList.contains('oculto') || m.dataset.cerrando) return;
  const fin = () => {
    m.classList.add('oculto'); delete m.dataset.cerrando;
    $$('body > *').forEach(e => { e.inert = false; });
    focoAntesDelModal?.focus?.();
  };
  if (alInstante || porTeclado) { m.getAnimations({ subtree: true }).forEach(a => a.cancel()); fin(); return; }
  m.dataset.cerrando = '1';
  if (!reducir()) $('.modal-caja').animate([{ transform: 'none' }, { transform: 'scale(0.98)' }],
    { duration: 140, easing: EASE_OUT });
  m.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: EASE_OUT }).onfinish = fin;
}
$('.modal-cerrar').onclick = () => cerrarModal();
$('#modal').onclick = (e) => { if (e.target.id === 'modal') cerrarModal(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') cerrarModal(true); });

/* ============================== BARRA ================================= */
// El mensaje de estado flota bajo la cabecera en vez de empujar la página: antes
// aparecía entre la cabecera y el contenido y bajaba todo ~40 px. Entra y sale
// por el mismo borde (lo hace el CSS con la clase "visible").
//
// Un aviso dura lo que toma leerlo (3 s más 40 ms por carácter, hasta 10 s):
// antes lo borraba el siguiente tick, a veces a los pocos milisegundos de
// aparecer. Los avisos del propio tick (progreso, error de carga) pasan
// duración 0 porque el tick los renueva mientras sigan vigentes, y no deben
// quedarse pegados cuando la carga termina. Un clic lo cierra.
let avisoHasta = 0;
function barra(txt, tipo, duracion) {
  const b = $('#barra-estado');
  if (!txt) {
    if (Date.now() < avisoHasta) return;
    b.classList.remove('visible'); return;
  }
  avisoHasta = Date.now() + (duracion ?? Math.min(10000, 3000 + txt.length * 40));
  b.classList.toggle('error', tipo === 'error');
  b.textContent = txt;
  b.classList.add('visible');
}
$('#barra-estado').onclick = () => { avisoHasta = 0; barra(''); };

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

/* La barra mide unidades reales de la etapa actual. La estimación aparece
   cuando el servidor ya tiene una muestra; nunca inventamos un minuto fijo. */
const ETAPAS_CARGA = {
  buscando:'Buscando la cartelera', cuotas:'Descargando cuotas', guardando:'Guardando cuotas',
  preparando:'Preparando el análisis', prediccion:'Analizando las peleas',
  informes:'Generando los informes', serializando:'Preparando los resultados', lista:'Cartelera lista',
};
function duracionCarga(segundos) {
  const s = Math.max(0, Math.ceil(segundos));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), resto = s % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${resto} s` : `${resto} s`;
}
// Cada etapa del servidor cae en uno de los cuatro pasos de la tira.
const PASO_CARGA = { buscando:0, cuotas:0, guardando:0, preparando:1, prediccion:2,
  informes:3, serializando:3, lista:4 };
// El panel entra bajando, cada etapa nueva se enciende de izquierda a derecha y,
// al terminar, se queda un momento diciendo "Cartelera lista" con todo en visto
// antes de recogerse: sin eso, desaparecía de golpe y no se sabía si había
// terminado bien. Las cifras que cambian suben como las de EN VIVO.
function pintarCarga(e) {
  const anterior = S.carga?.estado;
  S.carga = e.carga || (e.cargando ? {
    estado:'cargando', etapa:'preparando', detalle:e.progreso || 'Preparando la cartelera…',
    porcentaje:null, total:null, transcurrido_seg:0, restante_seg:null, sin_avance_seg:0,
  } : null);
  S.cargaRecibida = performance.now();
  S.cargaConectada = true;
  const c = S.carga, panel = $('#carga-cartelera');
  if (c?.estado === 'completada' && anterior !== 'completada')
    $('#carga-final').textContent = `Cartelera lista. ${c.detalle || ''}`;
  else if (c?.estado !== 'completada') $('#carga-final').textContent = '';
  const visible = c && (e.cargando || c.estado === 'error');
  const estabaVisible = !panel.classList.contains('oculto');
  // Terminó bien mientras se veía: despedida corta en vez de desaparecer.
  if (!visible && estabaVisible && c?.estado === 'completada' && !S.cargaSaliendo) {
    despedirCarga(panel, c);
    return;
  }
  if (S.cargaSaliendo) return;
  panel.classList.toggle('oculto', !visible);
  if (!visible) return;
  if (!estabaVisible) {
    S.cargaPasos = new Set(); S.cargaPaso = null;
    panel.classList.remove('lista');
    if (!reducir()) panel.animate([{ opacity: 0, transform: 'translateY(-12px)' }, { opacity: 1, transform: 'none' }],
      { duration: 320, easing: EASE_OUT });
  }
  panel.dataset.estado = c.estado;
  const titulo = c.estado === 'error'
    ? 'No se pudo cargar la cartelera' : ETAPAS_CARGA[c.etapa] || 'Cargando la cartelera';
  if ($('#carga-titulo').textContent !== titulo) {
    $('#carga-titulo').textContent = titulo;
    if (estabaVisible && !reducir()) $('#carga-titulo').animate(
      [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: 360, easing: EASE_OUT });
  }
  pintarPasosCarga(c);
  const detalle = c.detalle || e.progreso || '';
  if ($('#carga-detalle').textContent !== detalle) {
    $('#carga-detalle').textContent = detalle;
    if (estabaVisible && !reducir()) $('#carga-detalle').animate(
      [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: EASE_OUT });
  }
  const unidades = c.total != null && c.total > 0
    ? ` · ${c.completadas} de ${c.total} peleas` : '';
  if ($('#carga-unidades').textContent !== unidades) {
    $('#carga-unidades').textContent = unidades;
    if (estabaVisible && unidades && !reducir()) $('#carga-unidades').animate(
      [{ opacity: 0, transform: 'translateY(35%)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: EASE_OUT });
  }
  const progreso = $('#carga-barra');
  if (c.porcentaje == null) progreso.removeAttribute('value');
  else progreso.value = c.porcentaje;
  // Entero y con el espacio fino de todas las cifras: el servidor manda 33.3 y
  // salía "33.3 %", con punto, en una interfaz que escribe con coma.
  $('#carga-porcentaje').textContent = c.porcentaje == null ? 'En curso' : `${fmt(c.porcentaje, 0)}${NBSP_FINO}%`;
  $('#carga-pista').classList.toggle('oculto', c.estado === 'error');
  $('.carga-medida').classList.toggle('oculto', c.estado === 'error');
  pintarTiempoCarga();
}
function pintarPasosCarga(c) {
  const paso = PASO_CARGA[c.etapa] ?? 1;
  S.cargaPasos ??= new Set();
  S.cargaPasos.add(paso);
  $$('#carga-etapas li').forEach(li => {
    const n = Number(li.dataset.paso);
    li.classList.toggle('hecha', n < paso && S.cargaPasos.has(n));
    // Un CSV no baja cuotas: ese paso se salta, no se "hace".
    li.classList.toggle('salteada', n < paso && !S.cargaPasos.has(n));
    li.classList.toggle('actual', n === paso && c.estado !== 'error');
  });
  if (S.cargaPaso !== paso) {
    const actual = $('#carga-etapas li.actual');
    if (S.cargaPaso != null && actual && !reducir()) actual.animate(
      [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: 320, easing: EASE_OUT });
    S.cargaPaso = paso;
  }
}
function despedirCarga(panel, c) {
  S.cargaSaliendo = true;
  panel.classList.add('lista');
  $('#carga-titulo').textContent = 'Cartelera lista';
  $('#carga-detalle').textContent = c.detalle || '';
  $('#carga-barra').value = 100;
  $('#carga-porcentaje').textContent = `100${NBSP_FINO}%`;
  $$('#carga-etapas li').forEach(li => {
    li.classList.remove('actual');
    li.classList.toggle('hecha', S.cargaPasos?.has(Number(li.dataset.paso)) || Number(li.dataset.paso) > 0);
  });
  const cerrar = () => { panel.classList.add('oculto'); panel.classList.remove('lista'); S.cargaSaliendo = false; };
  if (reducir()) { setTimeout(cerrar, 700); return; }
  $('#carga-titulo').animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: 320, easing: EASE_OUT });
  setTimeout(() => {
    const alto = panel.offsetHeight;
    const salida = panel.animate([{ opacity: 1, height: alto + 'px', marginBottom: '26px' },
                                  { opacity: 0, height: '0px', marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px' }],
      { duration: 360, easing: EASE_IN_OUT });
    salida.onfinish = cerrar; salida.oncancel = cerrar;
    setTimeout(cerrar, 600);       // por si la ventana está en segundo plano
  }, 900);
}
function pintarTiempoCarga() {
  const c = S.carga;
  if (!c || $('#carga-cartelera').classList.contains('oculto')) return;
  const activa = c.estado === 'cargando';
  const desdeRespuesta = activa ? (performance.now() - S.cargaRecibida) / 1000 : 0;
  $('#carga-transcurrido').textContent = `Tiempo transcurrido: ${duracionCarga(c.transcurrido_seg + desdeRespuesta)}`;
  const resto = c.restante_seg == null ? null : c.restante_seg - desdeRespuesta;
  const sinConexion = activa && (!S.cargaConectada || desdeRespuesta > 6);
  $('#carga-restante').textContent = !activa ? 'La carga se detuvo.'
    : sinConexion ? 'Tiempo restante estimado: esperando conexión con el servidor…'
    : resto == null ? 'Tiempo restante estimado de esta etapa: calculando…'
    : resto <= 0 ? 'Tiempo restante estimado de esta etapa: recalculando…'
    : `Tiempo restante estimado de esta etapa: aprox. ${duracionCarga(resto)}`;
  const aviso = $('#carga-aviso');
  const lento = activa && c.sin_avance_seg + desdeRespuesta >= 45;
  aviso.classList.toggle('oculto', !activa || (!sinConexion && !lento && c.etapa !== 'prediccion'));
  aviso.textContent = sinConexion ? 'No se está recibiendo el estado del servidor. Se reintentará automáticamente.'
    : lento ? 'La consulta está tardando más de lo habitual. Arriba puedes ver qué ficha o etapa está esperando.'
    : 'La primera carga puede tardar más porque descarga las fichas de los peleadores. La estimación se ajusta con cada pelea procesada.';
}

async function tick() {
  try {
    const e = await api('/api/estado');
    S.proximoAuto = e.proximo_auto; S.origen = e.origen; S.vivo = e.vivo; S.corte = e.corte || null;
    const hayCartelera = !!(e.titulo || e.csv);
    const ev = evento(e);
    S.evento = ev;
    S.textosEvento = [e.titulo, e.csv, e.datos?.titulo].filter(Boolean);
    $('#titulo-cartelera').textContent = hayCartelera ? ev.nombre : 'sin cartelera cargada';
    $('#titulo-cartelera').title = hayCartelera ? `${ev.crudo}. Toca para cambiar de cartelera.` : 'Cambiar de cartelera';
    // La × solo aparece si hay algo que soltar.
    $('#btn-soltar').classList.toggle('oculto', !hayCartelera);
    $('#btn-refresh').disabled = e.cargando || !e.origen;

    pintarCarga(e);
    if (e.error && e.carga?.estado !== 'error') barra(e.error, 'error', 0);
    else barra('');

    if (e.datos && JSON.stringify(e.datos) !== JSON.stringify(S.datos)) {
      const previo = S.datos;
      S.datos = e.datos; S.patas = e.datos.patas;
      // ¿Es otra cartelera o la misma con cifras nuevas (EN VIVO)? Solo en la
      // misma tiene sentido comparar cifras; en otra, las barras se llenan.
      const clave = `${e.titulo}|${e.csv}|${e.datos.titulo}`;
      S.otraCartelera = clave !== S.claveCartelera;
      S.claveCartelera = clave;
      S.previo = S.otraCartelera ? null : previo;
      const vivos = new Set(S.patas.map(p => p.id));
      S.elegidas = S.elegidas.filter(id => vivos.has(id));
      S.mov = e.movimiento || {};
      pintarCartelera(e.datos, S.mov);
      pintarTiers(e.datos.tiers);
      pintarPatas();
      evaluarParlay();
      // Ya pintada: de aquí en adelante (clics en el boleto, EN VIVO) se
      // comparan cifras contra lo que se ve.
      S.otraCartelera = false;
    } else if (!e.datos && !e.cargando && S.datos === null) {
      mostrarVacio();
    }
  } catch (err) {
    S.cargaConectada = false;
    pintarTiempoCarga();
    barra('No pude hablar con el servidor: ' + err.message, 'error');
  }
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
  pintarTiempoCarga();
  const r = $('#reloj');
  // Repetición: en vez de la cuenta regresiva de cuotas, el rótulo de la tele.
  // No hay cuotas que refrescar: son las de cierre de ese día.
  const repe = $('#repe-caja');
  repe.classList.toggle('oculto', !S.corte);
  if (S.corte && repe.dataset.corte !== S.corte) {
    repe.dataset.corte = S.corte;
    repe.innerHTML = `${ico('repetir')}<span>Repetición</span><b>${esc(fechaCorta(S.corte))}</b>`;
    repe.title = `Predicción con los datos que había antes del ${fechaLarga(S.corte)}`;
    // Entra como el rótulo de la repetición en la tele: se descubre de lado.
    if (!reducir()) repe.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
      { duration: 360, easing: EASE_OUT });
  }
  if (!S.origen || S.corte) {
    $('#reloj-caja').classList.add('oculto'); $('#vivo-caja').classList.add('oculto'); return;
  }
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
// Cambiar la versión evita reutilizar retratos antiguos del navegador después
// de corregir una identificación en las fuentes del servidor.
const FOTO_VERSION = '3';
const retrato = (nombre, lado = '') => {
  const url = FOTOS.get(nombre);
  return `<figure class="retrato"${lado ? ` data-lado="${esc(lado)}"` : ''} data-foto="${esc(nombre)}">${
    url ? `<img src="${url}" alt="${esc(nombre)}" decoding="async">` : SILUETA}</figure>`;
};
function cargarFotos(raiz) {
  raiz.querySelectorAll('[data-foto]').forEach(f => {
    const n = f.dataset.foto;
    if (FOTOS.has(n)) return;
    FOTOS.set(n, null);
    const url = '/api/foto/' + encodeURIComponent(n) + '?v=' + FOTO_VERSION;
    // 204 = no hay foto: queda la silueta, que ya está puesta.
    fetch(url).then(r => {
      if (r.status !== 200) return;
      FOTOS.set(n, url);
      document.querySelectorAll(`[data-foto="${CSS.escape(n)}"]`)
        .forEach(x => {
          x.innerHTML = `<img src="${url}" alt="${esc(n)}" decoding="async">`;
          const img = x.querySelector('img');
          img.onerror = () => { FOTOS.set(n, null); x.innerHTML = SILUETA; };
          if (!reducir()) img.animate([{opacity:0}, {opacity:1}], {duration:320});
        });
    }).catch(() => {});
  });
}

/* ============================= CARTELERA ============================== */
const TXT_TIER = {
  A: ['Probado', 'Este mercado es el único con ventaja demostrada: +15,4% de retorno sobre 1.145 apuestas históricas.'],
  B: ['Sin ventaja clara', 'Ojo: el mercado de ganador quedó en empate técnico con la casa en las pruebas, así que esto es un complemento, no una base.'],
};

/* ============================ REPETICIÓN ============================== */
// Una cartelera que ya pasó, predicha con lo que se sabía antes de ese día
// (src/corte.py). El resultado real llega aparte, leído DESPUÉS de predecir:
// acá solo se muestra, nunca se mezcla con el pronóstico.
// ¿La apuesta sugerida habría salido? Ganador, o ganador por decisión.
function resultadoApuesta(a) {
  const r = a.resultado;
  if (!S.repeticion || !r?.lado) return '';
  const gano = r.lado === a.lado.toLowerCase() && (!a.decision || r.metodo === 'Decision');
  return ` · <span class="z-res ${gano ? 'si' : 'no'}">${gano ? 'salió' : 'no salió'}</span>`;
}
// El marcador de la noche, con el margen de error al lado: una cartelera no
// mide un modelo (50/√n puntos, la misma cuenta del backtest de carteleras).
function pintarMarcador(d, peleas) {
  const m = $('#marcador');
  if (!d.repeticion) { m.classList.add('oculto'); m.innerHTML = ''; return; }
  m.classList.remove('oculto');
  const resueltas = peleas.filter(p => p.resultado && p.resultado.acierto != null);
  const ok = resueltas.filter(p => p.resultado.acierto).length;
  const n = resueltas.length;
  if (!n) {
    m.classList.add('sin-datos');
    m.innerHTML = `<div class="marcador-txt"><b>Todavía no hay resultados de esta cartelera en la base.</b>
      <p>La base local llega hasta el ${esc(fechaLarga(d.repeticion.base_hasta))}. El pronóstico se lee igual; para ver cómo
      terminó cada pelea, corre "Actualizar todo" en Mantenimiento y vuelve a repetirla.</p></div>`;
    return;
  }
  m.classList.remove('sin-datos');
  const solidas = resueltas.filter(p => ['fuerte', 'buena'].includes(p.confianza));
  const metodos = peleas.map(aciertoMetodo).filter(Boolean);
  const okMetodo = metodos.filter(m => m.acierto).length;
  const okSolidas = solidas.filter(p => p.resultado.acierto).length;
  const margen = Math.round(50 / Math.sqrt(n));
  m.innerHTML = `
    <div class="marcador-cifra" aria-hidden="true"><b data-num="marcador:ok">${ok}</b><span>de ${n}</span></div>
    <div class="marcador-txt"><b>El modelo acertó ${ok} de ${n} peleas (${fmt(ok / n * 100, 0)}${NBSP_FINO}%)</b>
      <p>${solidas.length ? `En los pronósticos de 65${NBSP_FINO}% o más: ${okSolidas} de ${solidas.length}. ` : ''}${
        metodos.length ? `Cómo terminaba (el método más probable): ${okMetodo} de ${metodos.length}. ` : ''}Una noche no
      mide un modelo: con ${n} peleas el margen es de ±${margen} puntos. Sobre miles de peleas acierta 66-69${NBSP_FINO}% solo y ~70${NBSP_FINO}% con la cuota.</p></div>
    <ol class="marcador-tira" aria-label="Pelea por pelea">${peleas.map((p, i) => {
      const e = estadoResultado(p);
      const txt = `${p.a} vs ${p.b}: ${e.texto.toLowerCase()}`;
      return `<li><a class="mt-${e.clave}" href="#pelea-${esc(p.id)}" title="${esc(txt)}" aria-label="${esc(txt)}"><small>${String(i + 1).padStart(2, '0')}</small>${ico(e.clave === 'si' ? 'ok' : e.clave === 'no' ? 'no' : 'duda')}</a></li>`;
    }).join('')}</ol>`;
  m.querySelectorAll('.marcador-tira a').forEach(a => a.onclick = () => {
    const combate = document.getElementById(a.hash.slice(1))?.querySelector('[data-combate]');
    if (combate) alternarCombate(combate, true);
  });
}

function pintarCartelera(d, mov) {
  const raiz = $('#cartelera-contenido');
  S.repeticion = d.repeticion || null;
  const antes = S.otraCartelera ? new Map() : capturarCifras(raiz);
  const analisisAbiertos = S.otraCartelera ? null : new Set(
    $$('#peleas [data-analisis][open]').filter(e => !e.hasAttribute('data-cerrando')).map(e => e.dataset.analisis));
  const combatesAbiertos = new Set(S.otraCartelera ? [] :
    $$('#peleas [data-combate][open]').filter(e => !e.hasAttribute('data-cerrando')).map(e => e.dataset.combate));
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
    (S.repeticion ? '<span class="repe">Repetición</span>' : '') +
    esc([ev.fecha, ev.liga || origen].filter(Boolean).join(' · '));
  $('#evento-titulo').textContent = ev.nombre;

  /* ---- avisos ---- */
  // Gravedad: err (bloquea o invalida), warn (cuidado), info (dato). La marca
  // de la izquierda la dice sin depender del color.
  const av = [];
  if (S.repeticion) {
    const r = S.repeticion;
    const modelo = r.modelo === 'reentrenado'
      ? `un modelo reentrenado solo con las ${miles(r.modelo_peleas)} peleas anteriores (la última, del ${esc(fechaLarga(r.modelo_hasta))})`
      : `el modelo de siempre, que entrenó hasta el ${esc(fechaLarga(r.modelo_hasta))}: ya era anterior al corte`;
    av.push(['info', 'repetir', `<b>Repetición con los datos que había antes del ${esc(fechaLarga(r.fecha))}.</b>
      Estadísticas, récord, ELO y rivales se recalcularon solo con las peleas anteriores, y predice ${modelo}.
      Lo único que no se recorta son los dos calibradores que mezclan modelo y cuota: dos números ajustados con todo el historial, que no pueden aprender una pelea puntual.${
      r.ajustada ? ` El corte se adelantó del ${esc(fechaCorta(r.pedida))} al ${esc(fechaCorta(r.fecha))} porque UFCStats fecha el evento ese día.` : ''}`]);
    if (r.base_hasta && r.fecha > r.base_hasta) av.push(['warn', 'alerta',
      `La base local llega hasta el <b>${esc(fechaLarga(r.base_hasta))}</b>: lo que pasó entre esa fecha y el corte no está en los datos, y tampoco el resultado de esta cartelera. Para completarla, corre "Actualizar todo" en Mantenimiento.`]);
  }
  if (!d.modelo_real) av.push(['err','alerta',
    'No hay un modelo entrenado, así que estas probabilidades son una aproximación gruesa. Ve a Mantenimiento y ejecuta "Solo reentrenar el modelo".']);
  if (d.con_cuotas && !d.calibrador) av.push(['err','alerta',
    'Hay cuotas pero falta el calibrador, que es lo que permite combinar el modelo con el mercado. Ve a Mantenimiento → "Recalcular el calibrador de ganador". Sin él las señales de valor no son de fiar.']);
  const sosp = d.peleas.filter(p => (p.metodo6 || []).some(o => o.sospechoso));
  if (sosp.length) av.push(['err','prohibido',
    `Las cuotas de método de ${sosp.length} pelea(s) son <b>demasiado generosas para ser reales</b>. Suelen indicar números escritos a mano en vez de bajados de la casa. Como el valor se calcula con el precio, esas peleas mostrarían valor falso, así que quedan bloqueadas.`]);
  if (!d.con_cuotas) av.push(['warn','info', S.repeticion
    ? 'No hay cuotas guardadas de esta cartelera, así que la repetición usa solo el modelo: sin la casa acierta ~3 puntos menos y no se puede calcular valor.'
    : 'Esta cartelera no trae cuotas, así que se predice pero no se puede decir dónde hay valor ni armar combinadas. Bajarla desde Betano suma cuotas y ~3 puntos de acierto.']);
  // Caso muy frecuente y que sin explicación se lee como si el sistema fallara:
  // hay cuotas de ganador pero Betano todavía no abrió el mercado de método, que
  // es justo el único con ventaja demostrada. Sin este aviso el usuario ve una
  // pantalla entera de "sin ventaja clara" y no sabe si es culpa del modelo.
  const hayMetodo = d.patas.some(p => p.mercado !== 'ganador');
  if (d.con_cuotas && !hayMetodo && !S.repeticion) av.push(['warn','info',
    '<b>Betano todavía no abre el mercado de método para esta cartelera.</b> Por ahora solo publica "Ganador", que es precisamente el mercado donde las pruebas <b>no</b> encontraron ventaja; por eso todas las selecciones salen como <i>sin ventaja clara</i>. No es un fallo del modelo ni falta de datos. Los mercados de método (KO / sumisión / decisión) suelen abrirse en los días previos al evento: vuelve a refrescar más cerca de la fecha y aparecerán las selecciones <i>probadas</i>.']);
  if (d.missing.length) av.push(['warn','duda',
    `No encontré datos de estos peleadores en las fuentes consultadas: <b>${d.missing.map(esc).join(', ')}</b>. Sus peleas se omiten en vez de inventar datos.`]);
  const conDebut = d.peleas.filter(p => debutantesPelea(p).length);
  if (conDebut.length) {
    const nombres = [...new Set(conDebut.flatMap(debutantesPelea))];
    av.push(['warn','alerta', `<b>Debut en UFC: ${nombres.map(esc).join(', ')}.</b> ${conDebut.length === 1
      ? 'Una pelea incluye' : `${conDebut.length} peleas incluyen`} debutantes. Revisa el aviso sobre cada combate: el pronóstico tiene menos antecedentes en UFC.`]);
  }
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
    <div class="kpi"><div class="v"><span data-num="kpi:peleas">${d.peleas.length}</span></div><div class="k">peleas analizadas</div></div>
    <div class="kpi"><div class="v"><span data-num="kpi:solidas">${solidas}</span></div><div class="k">pronósticos sólidos (65${NBSP_FINO}%+)</div></div>
    <div class="kpi"><div class="v ${noFiables ? 'neg' : ''}"><span data-num="kpi:nofiables">${noFiables}</span></div>
      <div class="k">sin datos suficientes</div></div>
    <div class="kpi"><div class="v ${validas.length ? 'pos' : ''}"><span data-num="kpi:apuestas">${validas.length}</span></div>
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
          <div class="z-que"><b>${esc(a.que)}</b><span>${esc(a.pelea)}${resultadoApuesta(a)}</span></div>
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
    ? (S.repeticion ? 'Las probabilidades combinan el modelo con las cuotas de cierre de ese día, que es la versión más certera (~70% de acierto).'
      : 'Las probabilidades combinan el modelo con las cuotas de la casa, que es la versión más certera (~70% de acierto).')
    : 'Probabilidades del modelo solo, sin cuotas. Con cuotas acertaría ~3 puntos más.';

  const textos = S.textosEvento || [d.titulo];
  const desdeBetano = S.origen === 'betano' || textos.some(t => /^betano_/i.test(String(t || '')));
  const { peleas, idEstelar, idCo } = ordenarCartelera(d.peleas, textos, desdeBetano);
  pintarMarcador(d, peleas);
  // La estelar y los combates confirmados por el título usan el octágono.
  // La tabla sigue el mismo orden: estelar, coestelar y preliminares.
  const pelea = (p, i) => {
    const tipo = p.id === idEstelar ? 'estelar' : p.id === idCo ? 'coestelar' : '';
    const abierta = analisisAbiertos?.has(p.id) === true;
    return vistaPelea(p, mov, tipo, esJuez(), i + 1, peleas.length)
      + analisisPelea(p, abierta);
  };
  $('#peleas').innerHTML = `<nav class="pelea-indice" aria-label="Ir a una pelea">${peleas.map((p,i) =>
    `<a href="#pelea-${esc(p.id)}"><span>${String(i + 1).padStart(2,'0')}</span>${esc(p.a.split(' ').pop())} <small>vs</small> ${esc(p.b.split(' ').pop())}</a>`).join('')}</nav>
    <div class="peleas-lista">${peleas.map((p,i) => {
      const tipo = p.id === idEstelar ? 'estelar' : p.id === idCo ? 'coestelar' : '';
      const cinturon = p.es_titulo === true;
      return `<section class="combate ${usaOctagono(p, tipo) ? 'combate-principal' : ''} ${cinturon ? 'combate-cinturon' : ''}" id="pelea-${esc(p.id)}" aria-label="${esc(p.a)} vs ${esc(p.b)}">${avisoDebut(p)}${combatePlegable(p, pelea(p,i), tipo, combatesAbiertos.has(p.id))}</section>`;
    }).join('')}</div>`;
  cargarFotos($('#peleas'));
  $$('#peleas .pelea-indice a').forEach(a => a.onclick = () => {
    const combate = document.getElementById(a.hash.slice(1))?.querySelector('[data-combate]');
    if (combate) alternarCombate(combate, true);
  });
  $$('#peleas [data-combate]').forEach(detalle => detalle.querySelector(':scope > summary').addEventListener('click', evento => {
    evento.preventDefault();
    alternarCombate(detalle, !(transicionesCombate.get(detalle)?.abierto ?? detalle.open));
  }));
  // El análisis se despliega igual que su combate: antes se abría y se cerraba
  // de golpe, y al cerrarlo todo lo de abajo saltaba hacia arriba. Cierra más
  // rápido de lo que abre: al cerrar, el usuario ya terminó de mirarlo.
  $$('#peleas [data-analisis]').forEach(detalle => detalle.querySelector(':scope > summary').addEventListener('click', evento => {
    evento.preventDefault();
    desplegarCombate(detalle, !(transicionesCombate.get(detalle)?.abierto ?? detalle.open), { cerrar: 220 });
  }));
  $$('#peleas [data-analisis]').forEach(detalle => detalle.addEventListener('toggle', () => {
    if (!detalle.open || reducir() || porTeclado) return;
    detalle.querySelector('.analisis-contenido')?.animate(
      [{opacity:0, transform:'translateY(6px)'},{opacity:1, transform:'none'}], {duration:240, easing:EASE_OUT});
    // Sus barras se llenan al abrirlo, que es cuando se ven.
    detalle.querySelectorAll('.analisis-barra span').forEach((b, i) => llenarDesde(b, 'left', 120 + Math.min(i, 8) * 30));
  }));
  $$('#peleas [data-explica]').forEach(b => b.onclick = () => {
    const p = d.peleas.find(x => x.id === b.dataset.explica);
    modal(`<h2>${esc(p.a)} vs ${esc(p.b)}</h2>
      <p><span class="pill ${claseConf(p.confianza)}">${p.confianza}</span></p>
      <p>${p.por_que_confianza}</p>`);
  });
  $$('#peleas [data-historial-id]').forEach(b => b.onclick = () => {
    const p = d.peleas.find(x => x.id === b.dataset.historialId);
    const lado = b.dataset.historialLado;
    if (b.dataset.historialTodo === 'true') {
      const ultimas = p?.['info_' + lado]?.ultimas_peleas?.slice(0, 5);
      if (!ultimas?.length) return;
      modal(`<h2>${esc(p[lado])} · Últimas cinco</h2><p>De la más reciente a la anterior.</p><ol class="historial-detalle">${ultimas.map(anterior =>
        `<li class="${resultadoHistorial(anterior.resultado).clase}"><b>${resultadoHistorial(anterior.resultado).texto}</b>${anterior.rival ? ` frente a ${esc(anterior.rival)}` : ''}<span>${esc(anterior.metodo || 'Método no registrado')}${anterior.fecha ? ` · ${esc(anterior.fecha)}` : ''}</span></li>`).join('')}</ol>`);
      return;
    }
    const anterior = p?.['info_' + lado]?.ultimas_peleas?.[Number(b.dataset.historialIndice)];
    if (!anterior) return;
    modal(`<h2>${esc(p[lado])}</h2><p><b>${resultadoHistorial(anterior.resultado).texto}</b>${anterior.rival ? ` frente a ${esc(anterior.rival)}` : ''}</p>
      <p>Método: <b>${esc(anterior.metodo || 'No registrado')}</b></p>${anterior.fecha ? `<p>Fecha: ${esc(anterior.fecha)}</p>` : ''}`);
  });

  tabla('#tabla-principal',
    ['Pelea','Ganador','Probabilidad','Cuotas','Confianza','Termina por','No llega a tarjetas','Comparado con lo normal',
      ...(S.repeticion ? ['Resultado real'] : [])],
    peleas.map(p => {
      const pg = Math.max(p.p_a, p.p_b);
      const m = p.mercado;
      const r = p.resultado;
      return [`<span class="tabla-peleador" data-lado="a">${esc(p.a)}</span> <small>vs</small> <span class="tabla-peleador" data-lado="b">${esc(p.b)}</span>` + etiquetaTitulo(p) + etiquetaDebut(p), esc(p.ganador), td(`<span data-num="t:${p.id}:p">${pct(pg)}</span>`),
        td(m ? `<span data-num="t:${p.id}:cA">${cuota(m.cuota_a)}${flecha(mov, p.id, 'A')}</span> / <span data-num="t:${p.id}:cB">${cuota(m.cuota_b)}${flecha(mov, p.id, 'B')}</span>` : 'sin cuotas'),
        `<span class="pill ${claseConf(p.confianza)}">${p.confianza}</span>`,
        mejorMetodo(p.metodo), td(pct(p.p_finish,0)), esc(p.tendencia),
        ...(S.repeticion ? [`${pillResultado(p)}${r ? ` <small>${esc(textoResultado(r, true).titulo)}${r.como ? ' · ' + esc(r.como) : ''}</small>` : ''}`] : [])];
    }), peleas.map(p => p.es_titulo === true ? 'fila-titulo' : ''));

  if (S.otraCartelera) { revelarCombates(); entradaCartelera(); entradaMarcador(); abrirPeleaElegida(peleas); }
  else { resaltarCambios(raiz, antes); moverBarras(S.previo); }
}

// Abrir un combate es el momento de mostrarlo: ahí cada barra se llena desde
// su esquina (la de A desde la izquierda, la de B desde la derecha). Antes se
// llenaban al pintar la cartelera, pero los combates empiezan plegados y la
// animación corría sin que nadie la viera. Con teclado o con movimiento
// reducido, el combate se abre quieto.
const llenarDesde = (el, origen, delay, duration = 420) => {
  if (!el) return;
  el.style.transformOrigin = origen;
  el.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
    { duration, delay, easing: EASE_OUT, fill: 'backwards' });
};
// Lo que hace el usuario al abrir o cerrar un combate. Solo al abrir uno que
// estaba cerrado se arma su entrada: invertir un cierre a medio camino no
// vuelve a armar la jaula.
function alternarCombate(detalle, abierto) {
  const venia = transicionesCombate.get(detalle);
  const cerrado = !venia && !detalle.open;
  desplegarCombate(detalle, abierto);
  if (abierto && cerrado) animarApertura(detalle);
}
function animarApertura(detalle) {
  if (porTeclado) return;
  const art = detalle.querySelector('[data-pelea]');
  if (!art) return;
  // Con movimiento reducido no hay desplazamientos ni escalas, pero el
  // contenido tampoco aparece de golpe: se funde, sin moverse.
  if (reducir()) {
    art.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: 'ease' });
    return;
  }
  if (art.querySelector('.jaula')) { entradaJaula(art); return; }
  const [a, b] = art.querySelectorAll('.duelo-barra i');
  llenarDesde(a, 'left', 120); llenarDesde(b, 'right', 120);
  art.querySelectorAll('.metodo .mbar i').forEach((m, i) => llenarDesde(m, 'left', 180 + i * 50));
  // Tarjeta del juez: el timbre cae sobre el papel y después el lápiz
  // encierra al ganador.
  const timbre = art.querySelector('.ac-timbre .pill');
  if (timbre) timbre.animate(
    [{ opacity: 0, transform: 'rotate(-4deg) scale(1.35)' }, { opacity: 1, transform: 'rotate(-4deg) scale(1)' }],
    { duration: 220, delay: 160, easing: EASE_OUT, fill: 'backwards' });
  trazar(art.querySelector('.ac-lapiz path'), { duration: 450, delay: 300, easing: EASE_OUT });
  revelarResultado(art, 420);
}

// Dibuja un trazo SVG de punta a punta. El largo se mide en píxeles de
// pantalla: con vector-effect="non-scaling-stroke" el guion se calcula en la
// pantalla y no en el viewBox, así que el truco de pathLength="1" no sirve.
// Antes lo usaba y Chrome repartía el guion en trozos sueltos por las
// esquinas; al terminar, la línea completa aparecía de golpe. El largo se
// estima muestreando el trazo con un margen hacia arriba: si sobra, el último
// cuadro igual queda completo, y al quitar la animación no cambia nada.
function trazar(geom, opciones) {
  const svg = geom?.ownerSVGElement;
  if (!svg || typeof geom.getTotalLength !== 'function') return;
  const caja = svg.getBoundingClientRect();
  const vista = svg.viewBox.baseVal;
  if (!caja.width || !vista?.width) return;
  const sx = caja.width / vista.width, sy = caja.height / vista.height;
  const total = geom.getTotalLength();
  let largo = 0, previo = geom.getPointAtLength(0);
  for (let i = 1; i <= 96; i++) {
    const pt = geom.getPointAtLength(total * i / 96);
    largo += Math.hypot((pt.x - previo.x) * sx, (pt.y - previo.y) * sy);
    previo = pt;
  }
  const L = Math.ceil(largo * 1.02) + 2;
  geom.animate([{ strokeDasharray: `${L}px ${L}px`, strokeDashoffset: `${L}px` },
    { strokeDasharray: `${L}px ${L}px`, strokeDashoffset: '0px' }], { fill: 'backwards', ...opciones });
}

// EL momento de la cartelera: abrir la estelar es entrar a la jaula. Se arma
// de afuera hacia adentro, en tres tiempos como en la transmisión:
//   1. La estructura (0-550 ms): la reja y la baranda se asientan y los ocho
//      postes caen en sentido horario.
//   2. La lona (160-760 ms): la línea se pinta alrededor, de un solo trazo.
//   3. La pelea (300-900 ms): cada peleador entra desde su esquina, después
//      su nombre, su historial y su porcentaje, y lo último en asentarse es la
//      barra que se llena desde los dos lados. En una repetición, al final se
//      estampa cómo terminó.
// Antes todo arrancaba en los primeros 300 ms, lo de adentro (rótulos y
// porcentajes) se veía desde el primer cuadro, y la línea, la cuenta y la
// barra aterrizaban juntas con un salto: "pum, se armó". Los finales van
// escalonados para que el armado se asiente en vez de golpear. Solo
// transform y opacity (más el trazo): nada mueve el layout.
function entradaJaula(art) {
  const j = art.querySelector('.jaula');
  const anim = (el, frames, opciones) => el?.animate(frames, { easing: EASE_OUT, fill: 'backwards', ...opciones });
  const entra = (el, delay, duracion = 260) =>
    anim(el, [{ opacity: 0, translate: '0 6px' }, { opacity: 1, translate: '0 0' }], { duration: duracion, delay });
  // 1. Estructura. Nada nace de escala cero: la reja ya está casi en su sitio.
  anim(j.querySelector('.reja'), [{ opacity: 0, scale: .97 }, { opacity: 1, scale: 1 }], { duration: 320 });
  anim(j.querySelector('.baranda'), [{ opacity: 0, scale: .97 }, { opacity: 1, scale: 1 }], { duration: 320, delay: 40 });
  j.querySelectorAll('.poste').forEach((poste, i) =>
    anim(poste, [{ opacity: 0, scale: .6 }, { opacity: 1, scale: 1 }], { duration: 220, delay: 120 + i * 30 }));
  // 2. La lona. El polígono parte junto al primer poste y gira como ellos.
  trazar(j.querySelector('.lona-linea polygon'), { duration: 600, delay: 160, easing: EASE_IN_OUT });
  // La marca impresa se funde hasta SU opacidad tenue (7 %, menos con la placa
  // del resultado), leída del CSS, y nunca más allá: así al terminar no hay
  // salto. Antes subía a 1 (en la caja y después en el dibujo, que según el
  // navegador se componía aparte e ignoraba la opacidad de la caja): la "I"
  // se veía a todo color y al terminar desaparecía de golpe. La escala va en
  // el dibujo: la caja ya usa transform para centrarse.
  const impresion = j.querySelector('.lona-impresion');
  if (impresion) {
    impresion.getAnimations().forEach(a => a.cancel());   // reabrir a medio fundido
    anim(impresion, [{ opacity: 0 }, { opacity: getComputedStyle(impresion).opacity }], { duration: 600, delay: 260 });
    anim(impresion.querySelector('.lona-marca'), [{ scale: .9 }, { scale: 1 }], { duration: 600, delay: 260 });
  }
  // 3. La pelea. Los retratos entraban además con clip-path, que se repinta
  // en cada cuadro; el desplazamiento desde su esquina ya cuenta de dónde vienen.
  anim(j.querySelector('.retrato.a'), [{ opacity: 0, translate: '-8% 0' }, { opacity: 1, translate: '0 0' }], { duration: 420, delay: 300 });
  anim(j.querySelector('.retrato.b'), [{ opacity: 0, translate: '8% 0' }, { opacity: 1, translate: '0 0' }], { duration: 420, delay: 300 });
  j.querySelectorAll('.j-nombre, .j-vs').forEach((n, i) => entra(n, 380 + i * 30, 300));
  entra(j.querySelector('.historial-lona .historial-cab'), 440);
  j.querySelectorAll('.historial-lona .historial-ausente').forEach((n, i) => entra(n, 460 + i * 30));
  j.querySelectorAll('.historial-lona .historial-cuadro').forEach((c, i) =>
    anim(c, [{ opacity: 0, scale: .9 }, { opacity: 1, scale: 1 }], { duration: 220, delay: 460 + (i % 5) * 35 }));
  j.querySelectorAll('.j-pct').forEach(n => entra(n, 460));
  j.querySelectorAll('.j-pct [data-num]').forEach(cifra => contar(cifra, 460, 400));
  const [a, b] = j.querySelectorAll('.duelo-barra i');
  llenarDesde(a, 'left', 480, 420); llenarDesde(b, 'right', 480, 420);
  art.querySelectorAll('.estelar-datos .mbar i').forEach((m, i) => llenarDesde(m, 'left', 420 + i * 40));
  revelarResultado(art, 950);
}

// Una cifra corre de 0 a su valor, con las mismas comas y decimales que va a
// tener. Las cifras son tabulares: los dígitos no bailan mientras corren. Y
// mientras tiene menos dígitos que al final se rellena por la izquierda con
// ceros invisibles, que miden exactamente un dígito tabular: sin eso "9,8 %"
// medía 112 px y "21,1 %" 140, y todo lo centrado se corría al cruzar el 10.
// (El espacio de cifra U+2007 no sirve: Barlow no lo trae y el de la fuente
// de respaldo es más angosto.)
function contar(el, delay, duracion) {
  const final = el.textContent;
  const valor = parseFloat(final.replace(/[^\d,]/g, '').replace(',', '.'));
  if (!Number.isFinite(valor)) return;
  const decimales = (final.split(',')[1] || '').replace(/\D/g, '').length;
  const sufijo = final.includes('%') ? NBSP_FINO + '%' : '';
  const pintar = (v) => {
    const t = fmt(v, decimales) + sufijo;
    const falta = final.length - t.length;
    if (falta > 0) el.innerHTML = `<span class="cifra-relleno" aria-hidden="true">${'0'.repeat(falta)}</span>${t}`;
    else el.textContent = t;
  };
  const inicio = performance.now() + delay;
  pintar(0);
  const paso = (t) => {
    if (!el.isConnected) return;
    const x = Math.min(1, Math.max(0, (t - inicio) / duracion));
    if (x >= 1) el.textContent = final; else pintar(valor * (1 - Math.pow(1 - x, 4)));
    if (x < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

// El resultado entra como el zócalo de la tele después de la pelea: se
// descubre de izquierda a derecha y el sello cae al final.
function revelarResultado(art, delay) {
  const r = art.querySelector('.resultado-real');
  if (!r) return;
  r.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
    { duration: 380, delay, easing: EASE_OUT, fill: 'backwards' });
  r.querySelector('.rr-sello')?.animate([{ opacity: 0, scale: 1.3 }, { opacity: 1, scale: 1 }],
    { duration: 220, delay: delay + 240, easing: EASE_OUT, fill: 'backwards' });
  // Después del ganador, el veredicto del método: segundo timbre, más chico.
  r.querySelector('.rr-metodo')?.animate([{ opacity: 0, translate: '-6px 0' }, { opacity: 1, translate: '0 0' }],
    { duration: 260, delay: delay + 420, easing: EASE_OUT, fill: 'backwards' });
}

// Una cartelera nueva entra como la presentación de la noche: las cifras de la
// barra de información corren hasta su valor y los zócalos de "Qué apostar"
// se descubren de izquierda a derecha, uno tras otro. Una vez por cartelera:
// los refrescos de EN VIVO no la repiten.
function entradaCartelera() {
  if (reducir()) return;
  $$('#tarjetas-kpi [data-num]').forEach(cifra => contar(cifra, 60, 520));
  $$('#resumen .zocalo, #resumen .sin-apuestas').forEach((z, i) =>
    z.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
      { duration: 420, delay: 140 + Math.min(i, 6) * 70, easing: EASE_OUT, fill: 'backwards' }));
}

// El marcador de una repetición: la tira se completa pelea por pelea, como
// las tarjetas que se van anotando. Una sola vez, al llegar la cartelera.
function entradaMarcador() {
  const m = $('#marcador');
  if (reducir() || m.classList.contains('oculto')) return;
  const cifra = m.querySelector('.marcador-cifra b');
  if (cifra) contar(cifra, 120, 600);
  m.querySelectorAll('.marcador-tira a').forEach((a, i) =>
    a.animate([{ opacity: 0, scale: .7 }, { opacity: 1, scale: 1 }],
      { duration: 220, delay: 160 + Math.min(i, 14) * 35, easing: EASE_OUT, fill: 'backwards' }));
}

// Al elegir una pelea anterior se carga toda su cartelera; la elegida se abre
// sola para no tener que buscarla.
function abrirPeleaElegida(peleas) {
  if (!S.abrirPelea) return;
  const elegida = new Set(S.abrirPelea.map(plano));
  S.abrirPelea = null;
  const p = peleas.find(x => elegida.has(plano(x.a)) && elegida.has(plano(x.b)));
  const detalle = p && document.getElementById('pelea-' + p.id)?.querySelector('[data-combate]');
  if (!detalle) return;
  // Directo y no en requestAnimationFrame: el DOM ya está pintado, y rAF no
  // corre si la pestaña está en segundo plano mientras termina la carga.
  detalle.closest('.combate').scrollIntoView({ block: 'start', behavior: reducir() ? 'auto' : 'smooth' });
  alternarCombate(detalle, true);
}

// Los combates entran cuando llegan a la pantalla. No se oculta contenido:
// incluso sin IntersectionObserver o con movimiento reducido sigue visible.
let observadorCombates;
function revelarCombates() {
  observadorCombates?.disconnect();
  if (reducir() || !('IntersectionObserver' in window)) return;
  observadorCombates = new IntersectionObserver(entradas => entradas.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.animate([{opacity:.25, transform:'translateY(18px)'}, {opacity:1, transform:'none'}],
      {duration:450, easing:EASE_OUT});
    observadorCombates.unobserve(e.target);
  }), {threshold:.08});
  $$('#peleas .combate').forEach(e => observadorCombates.observe(e));
}

// EN VIVO: si cambió la probabilidad de una pelea, la barra viaja del reparto
// viejo al nuevo (escala, no ancho: el ancho mueve el layout).
function moverBarras(previo) {
  if (!previo || reducir()) return;
  const antes = new Map(previo.peleas.map(p => [p.id, p.p_a]));
  $$('#peleas [data-pelea]').forEach(art => {
    const p = S.datos.peleas.find(x => x.id === art.dataset.pelea);
    const viejo = antes.get(art.dataset.pelea);
    if (!p || viejo == null || Math.abs(viejo - p.p_a) < 1e-4) return;
    const [a, b] = art.querySelectorAll('.duelo-barra i');
    const mover = (el, de, a_, origen) => {
      if (!el || !a_) return;
      el.style.transformOrigin = origen;
      el.animate([{ transform: `scaleX(${de / a_})` }, { transform: 'scaleX(1)' }],
        { duration: 280, easing: EASE_IN_OUT });
    };
    mover(a, viejo, p.p_a, 'left'); mover(b, 1 - viejo, p.p_b, 'right');
  });
}

function recolectarApuestas(d) {
  const out = [];
  d.peleas.forEach(p => {
    // La decisión es la misma apuesta en el mercado de 7 y de 5 vías.
    [...(p.metodo6 || []), ...(p.metodo5 || [])]
      .filter(o => o.apostar && o.clase.endsWith('DEC')).forEach(o =>
      out.push({ orden:0, tier:'A', pelea:`${p.a} vs ${p.b}`,
        que:`${o.clase[0]==='A'?p.a:p.b} gana por decisión`, lado:o.clase[0], decision:true, resultado:p.resultado,
        cuota:o.cuota_decimal, ev:o.ev, kelly:o.kelly, pocos:p.pocos }));
    const m = p.mercado;
    if (m && m.lado && m.ev > 0)
      out.push({ orden:1, tier:'B', pelea:`${p.a} vs ${p.b}`,
        que:`Gana ${m.lado==='A'?p.a:p.b}`, lado:m.lado, decision:false, resultado:p.resultado,
        cuota:m.cuota, ev:m.ev, kelly:m.kelly, pocos:p.pocos });
  });
  return out.sort((x,y) => x.orden - y.orden || y.ev - x.ev);
}

// Betano entrega la cartelera de preliminares a estelar. Los CSV manuales
// conservan sus rótulos; el nombre del evento ayuda cuando no hay segmento.
const plano = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
function principalDeFuente(peleas, desdeFinal) {
  // El índice original evita ascender otra pelea si la principal fue omitida.
  if (peleas.some(p => Number.isInteger(p.orden_cartelera) && Number.isInteger(p.total_cartelera))) {
    const candidatas = peleas.filter(p => p.orden_cartelera === p.total_cartelera - 1 - desdeFinal);
    return candidatas.length === 1 ? candidatas[0].id : null;
  }
  return peleas[peleas.length - 1 - desdeFinal]?.id ?? null;
}
function estelar(peleas, textos, desdeBetano = false) {
  const porSegmento = peleas.filter(p => /^\s*(estelar|main event)\b/i.test(p.segmento || ''));
  if (porSegmento.length) return porSegmento.length === 1 ? porSegmento[0].id : null;
  if (desdeBetano) return principalDeFuente(peleas, 0);
  const palabras = new Set(plano(textos.join(' ')).split(' '));
  const apellido = (n) => plano(n).split(' ').pop();
  const cand = peleas.filter(p => palabras.has(apellido(p.a)) && palabras.has(apellido(p.b)));
  return cand.length === 1 ? cand[0].id : null;
}

// En un CSV sin rótulos solo se infiere una vecina si la estelar está en una punta.
const esCoSegmento = (p) => /^\s*co[\s-]?(estelar|main)/i.test(p.segmento || '');
function coestelar(peleas, idEstelar, desdeBetano = false) {
  const porSegmento = peleas.filter(p => p.id !== idEstelar && esCoSegmento(p));
  if (porSegmento.length) return porSegmento.length === 1 ? porSegmento[0].id : null;
  if (desdeBetano) {
    const id = principalDeFuente(peleas, 1);
    return id !== idEstelar ? id : null;
  }
  const i = peleas.findIndex(p => p.id === idEstelar);
  if (i < 0 || peleas.length < 2) return null;
  if (i === 0) return peleas[1].id;
  if (i === peleas.length - 1) return peleas[i - 1].id;
  return null;
}
function ordenarCartelera(fuente, textos, desdeBetano = false) {
  const idEstelar = estelar(fuente, textos, desdeBetano);
  const idCo = coestelar(fuente, idEstelar, desdeBetano);
  const invertir = desdeBetano || (fuente.length > 1 && fuente[fuente.length - 1].id === idEstelar);
  const orden = invertir ? fuente.slice().reverse() : fuente.slice();
  const principales = [idEstelar, idCo].map(id => fuente.find(p => p.id === id)).filter(Boolean);
  const peleas = [...principales, ...orden.filter(p => p.id !== idEstelar && p.id !== idCo)];
  return { peleas, idEstelar, idCo };
}

const claseConf = (c) => c.toLowerCase().replace(/\s+/g,'');
// "2026-08-08" -> "sáb 8 ago", como el título del evento.
const fechaCorta = (iso) => {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso || '';
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString('es-CL',
    { weekday:'short', day:'numeric', month:'short' }).replace(',', '');
};

// "2025-11-15" -> "sáb 15 nov 2025": las repeticiones necesitan el año.
const fechaLarga = (iso) => {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso || '';
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString('es-CL',
    { weekday:'short', day:'numeric', month:'short', year:'numeric' }).replace(',', '');
};
const hoyISO = () => new Date().toLocaleDateString('sv-SE');

// Las vistas de la repetición dependen del dato y no de un estado global: en
// una repetición cada pelea trae la clave `resultado` (null si la base todavía
// no la tiene). Una cartelera normal no la trae.
const enRepeticion = (p) => Object.prototype.hasOwnProperty.call(p, 'resultado');
const apellidoDe = (n) => String(n || '').trim().split(/\s+/).pop();
function estadoResultado(p) {
  const r = p.resultado;
  if (!r) return { clave: 'nd', texto: 'Sin resultado' };
  if (r.acierto === true) return { clave: 'si', texto: 'Acertó' };
  if (r.acierto === false) return { clave: 'no', texto: 'Falló' };
  return { clave: 'nd', texto: r.ganador ? 'Sin resultado' : r.como === 'sin resultado' ? 'Sin resultado' : 'Empate' };
}
// corto = la placa de la lona, que tiene que caber entre las dos diagonales.
function textoResultado(r, corto = false) {
  const asalto = !r.asalto ? '' : corto ? `R${r.asalto}${r.tiempo ? ' ' + r.tiempo : ''}`
    : `asalto ${r.asalto}${r.tiempo ? ' · ' + r.tiempo : ''}`;
  const como = corto ? String(r.como || '').replace(/^decisión/, 'dec.') : r.como;
  const detalle = [como, asalto].filter(Boolean).join(' · ');
  if (!r.ganador) return { titulo: r.como === 'sin resultado' ? (corto ? 'Sin resultado' : 'Sin resultado (no contest)') : 'Empate', detalle };
  return { titulo: `Ganó ${corto ? apellidoDe(r.ganador) : r.ganador}`, detalle };
}
// El zócalo del resultado, en la tarjeta y como placa en la lona del octágono.
function resultadoReal(p, enLona = false) {
  if (!enRepeticion(p)) return '';
  const est = estadoResultado(p);
  const r = p.resultado;
  const t = r ? textoResultado(r, enLona)
    : { titulo: 'Todavía no está en la base', detalle: 'Se agrega al actualizar la base en Mantenimiento.' };
  const icono = est.clave === 'si' ? 'ok' : est.clave === 'no' ? 'no' : 'duda';
  // El sello habla del ganador; el método va aparte, con su propio veredicto.
  const am = aciertoMetodo(p);
  const metodo = !am ? '' : `<span class="rr-metodo" data-metodo="${am.acierto ? 'si' : 'no'}">${ico(am.acierto ? 'ok' : 'no')}${
    am.acierto ? 'Acertó el método' : `Falló el método${enLona ? '' : `: veía ${esc(METODOS.find(([k]) => k === am.top)[1].toLowerCase())}`}`}</span>`;
  return `<div class="resultado-real${enLona ? ' j-todo j-resultado' : ''}" data-acierto="${est.clave}">
    <span class="rr-sello">${ico(icono)}${esc(est.texto)}</span>
    <span class="rr-que"><small>Resultado real${r && !enLona ? ' · ' + esc(fechaCorta(r.fecha)) : ''}</small><b${r?.lado ? ` data-lado="${r.lado}"` : ''}>${esc(t.titulo)}</b>${t.detalle ? `<span>${esc(t.detalle)}</span>` : ''}${metodo}</span>
  </div>`;
}
// En el encabezado plegable: se sabe cómo terminó sin abrir el combate, el
// ganador y también el método.
function pillResultado(p) {
  if (!enRepeticion(p)) return '';
  const e = estadoResultado(p);
  if (e.clave === 'nd') return `<span class="pill res res-nd">${esc(e.texto.toLowerCase())}</span>`;
  const am = aciertoMetodo(p);
  return `<span class="pill res res-${e.clave}">${ico(e.clave === 'si' ? 'ok' : 'no')}${esc(e.texto.toLowerCase())}</span>${!am ? ''
    : `<span class="pill res res-${am.acierto ? 'si' : 'no'} res-met" title="${am.acierto ? 'Acertó' : 'Falló'} el método">${ico(am.acierto ? 'ok' : 'no')}método</span>`}`;
}
const td = (t) => `<td class="num">${t}</td>`;
function flecha(mov, id, lado) {
  const m = mov[`${id}:ML:${lado}`];
  if (!m || m.antes === m.ahora) return '';
  return `<span class="mov" title="antes ${cuota(m.antes)}">${m.ahora > m.antes ? '▲' : '▼'}</span>`;
}
const peleasUFC = (info) => {
  if (!info) return '';
  const confirmado = info.historial_ufc_confirmado === true;
  const dato = confirmado ? info.n_peleas_ufc : info.n_peleas_hist;
  if (dato == null) return 'Historial no disponible';
  const n = Number(dato);
  if (!Number.isInteger(n) || n < 0) return 'Historial no disponible';
  if (confirmado)
    return n === 0 ? 'sin peleas registradas en UFC' : `${n} pelea${n === 1 ? '' : 's'} en UFC`;
  return n === 0 ? 'sin peleas con estadísticas' : `${n} pelea${n === 1 ? '' : 's'} con estadísticas`;
};

// Las filas en espejo: lo mismo para cada esquina, enfrentado por el medio.
function espejo(p, mov) {
  const m = p.mercado;
  if (!m) return '';
  const fila = (k, a, lbl, b) => `<div><b data-lado="a" data-num="${p.id}:${k}:A">${a}</b><span>${lbl}</span><b class="r" data-lado="b" data-num="${p.id}:${k}:B">${b}</b></div>`;
  return `<div class="espejo">
    ${fila('cuota', cuota(m.cuota_a) + flecha(mov, p.id, 'A'), 'cuota', cuota(m.cuota_b) + flecha(mov, p.id, 'B'))}
    ${fila('casa', pct(m.p_mercado_a), 'le da la casa', pct(1 - m.p_mercado_a))}
    ${fila('modelo', pct(m.p_modelo_a), 'el modelo solo', pct(1 - m.p_modelo_a))}
  </div>`;
}

function barraDuelo(p) {
  const favA = p.p_a >= p.p_b;
  return `<div class="duelo-barra" role="img" aria-label="${esc(p.a)} ${pct(p.p_a)}, ${esc(p.b)} ${pct(p.p_b)}">
    <i data-lado="a" class="${favA ? 'fav' : ''}" style="width:${p.p_a * 100}%"></i><i data-lado="b" class="${favA ? '' : 'fav'}" style="width:${p.p_b * 100}%"></i></div>`;
}

const METODOS = [['KO/TKO','KO/TKO'],['Submission','Sumisión'],['Decision','Decisión']];
// En una repetición: ¿terminó como el modelo creía más probable? Solo si la base
// tiene un método claro (un empate o un "sin resultado" no se cuenta).
function aciertoMetodo(p) {
  const real = p.resultado?.metodo;
  if (!enRepeticion(p) || !p.resultado?.ganador || !METODOS.some(([k]) => k === real)) return null;
  const top = METODOS.reduce((a, [k]) => (p.metodo[k] || 0) > (p.metodo[a] || 0) ? k : a, 'KO/TKO');
  return { real, acierto: top === real, top };
}
function metodoFila(p) {
  const maxMet = Math.max(...METODOS.map(([k]) => p.metodo[k] || 0));
  const am = aciertoMetodo(p);
  const nombre = (k) => METODOS.find(([m]) => m === k)[1].toLowerCase();
  const veredicto = !am ? '' : `<p class="metodo-veredicto" data-acierto="${am.acierto ? 'si' : 'no'}">${ico(am.acierto ? 'ok' : 'no')}<span>${am.acierto
    ? `<b>Acertó el método:</b> terminó por ${nombre(am.real)}, lo que veía más probable.`
    : `<b>Falló el método:</b> terminó por ${nombre(am.real)} (le daba ${fmt((p.metodo[am.real] || 0) * 100, 0)}${NBSP_FINO}%); lo más probable era ${nombre(am.top)}.`}</span></p>`;
  return `<div class="metodo${am ? ' con-real' : ''}">${METODOS.map(([k, lbl]) => {
    const v = p.metodo[k] || 0;
    return `<div class="${v === maxMet ? 'top' : ''}${am?.real === k ? ' real' : ''}"><span class="mv" data-num="${p.id}:met:${k}">${fmt(v * 100, 0)}${NBSP_FINO}%</span><span class="mk">${lbl}</span>${
      am?.real === k ? '<span class="metodo-real">Así terminó</span>' : ''}
      <span class="mbar"><i style="width:${v * 100}%"></i></span></div>`;
  }).join('')}</div>${veredicto}`;
}

// Cada dato conserva su columna; la ayuda es una acción independiente.
function piePelea(p) {
  const m = p.mercado;
  return `<div class="pelea-pie${m ? '' : ' sin-cuotas'}">
    <div class="pelea-fin"><span class="pelea-meta">No llega a tarjetas</span><b data-num="${esc(p.id)}:finish">${pct(p.p_finish,0)}</b></div>
    <div class="pelea-tendencia"><span class="pelea-meta">Tendencia del combate</span><span>${p.tendencia === 'pelea promedio'
      ? 'Nada la distingue de una pelea promedio'
      : `Más propensa a terminar así que lo normal: <b>${esc(p.tendencia)}</b>`}</span></div>
    ${m ? `<div class="pelea-comision"><span class="pelea-meta">Comisión de la casa</span><b data-num="${esc(p.id)}:vig">${pct(m.vig)}</b></div>` : ''}
    ${ayudaPelea(p)}
  </div>`;
}

function ayudaPelea(p) {
  return `<button class="enlace pelea-ayuda" data-explica="${esc(p.id)}" aria-label="Explicar el pronóstico de ${esc(p.a)} frente a ${esc(p.b)}">¿Cómo leer este pronóstico?</button>`;
}
const etiquetaDebut = (p) => {
  const n = debutantesPelea(p).length;
  return n ? `<span class="pelea-debut">${n === 1 ? 'Pelea de un debutante' : 'Pelea de debutantes'}</span>` : '';
};
const debutantesPelea = (p) => Array.isArray(p.debutantes) ? p.debutantes :
  [[p.a,p.info_a],[p.b,p.info_b]].filter(([,info]) => info?.debut_ufc_confirmado === true).map(([n]) => n);
function avisoDebut(p) {
  const nombres = debutantesPelea(p);
  if (!nombres.length) return '';
  return `<header class="debut-cab">${ico('alerta')}<div><b>${nombres.length === 2 ? 'Ambos debutan en UFC' : 'Debut en UFC'} · ${nombres.map(esc).join(' y ')}</b>
    <span>${nombres.length === 2 ? 'Ninguno tiene peleas previas registradas en UFC.' : 'Este peleador todavía no tiene peleas previas registradas en UFC.'} Interpreta la predicción con más cautela.</span></div></header>`;
}

function resultadoHistorial(resultado) {
  return ({W: {clase: 'victoria', texto: 'Victoria', marca: 'V'},
    L: {clase: 'derrota', texto: 'Derrota', marca: 'P'},
    D: {clase: 'neutral', texto: 'Empate', marca: 'E'},
    NC: {clase: 'neutral', texto: 'Sin resultado', marca: 'NC'}})[resultado]
    || {clase: 'neutral', texto: 'Resultado no registrado', marca: '—'};
}
// corto: las casillas de la lona miden ~27 px y "KO/TKO" no entraba (se
// cortaba en "KO/TK"). El detalle completo sigue en el título y en el modal.
function metodoHistorial(metodo, corto = false) {
  const texto = String(metodo || '').trim();
  if (/KO\s*\/\s*TKO/i.test(texto)) return corto ? 'KO' : 'KO/TKO';
  if (/TKO/i.test(texto)) return 'TKO';
  if (/KO/i.test(texto)) return 'KO';
  if (/sub|sumisi/i.test(texto)) return 'SUB';
  if (/dec|decision|decisión/i.test(texto)) return 'DEC';
  if (/DQ|disqual/i.test(texto)) return 'DQ';
  if (/no contest|\bC?NC\b/i.test(texto)) return 'NC';
  return texto ? 'OTRO' : '—';
}
function historialReciente(p, enLona = false) {
  const lado = (clave) => {
    const peleas = p['info_' + clave]?.ultimas_peleas;
    const ultimas = Array.isArray(peleas) ? peleas.slice(0, 5) : [];
    if (enLona) {
      const resumen = ultimas.map(pelea => {
        const resultado = resultadoHistorial(pelea.resultado);
        return `<span class="historial-cuadro ${resultado.clase}"><small>${resultado.marca}</small><span>${metodoHistorial(pelea.metodo, true)}</span></span>`;
      }).join('');
      return `<div class="historial-lado">${ultimas.length
        ? `<button class="historial-resumen" type="button" data-historial-id="${esc(p.id)}" data-historial-lado="${clave}" data-historial-todo="true" title="Ver las últimas ${ultimas.length} peleas de ${esc(p[clave])}" aria-label="Ver las últimas ${ultimas.length} peleas de ${esc(p[clave])}"><span class="historial-cuadros" aria-hidden="true">${resumen}</span></button>`
        : `<span class="historial-ausente" aria-label="${esc(p[clave])}: historial reciente no disponible">Sin historial reciente</span>`}</div>`;
    }
    return `<div class="historial-lado">${ultimas.length
      ? `<ol class="historial-cuadros" aria-label="Últimas ${ultimas.length} peleas de ${esc(p[clave])}, más reciente primero">${ultimas.map((pelea, i) => {
        const resultado = resultadoHistorial(pelea.resultado);
        const detalle = `${resultado.texto}${pelea.rival ? ' frente a ' + pelea.rival : ''} · ${pelea.metodo || 'Método no registrado'}${pelea.fecha ? ' · ' + pelea.fecha : ''}`;
        return `<li><button class="historial-cuadro ${resultado.clase}" type="button" data-historial-id="${esc(p.id)}" data-historial-lado="${clave}" data-historial-indice="${i}" title="${esc(detalle)}" aria-label="${esc(detalle)}"><small>${resultado.marca}</small><span>${metodoHistorial(pelea.metodo)}</span></button></li>`;
      }).join('')}</ol>`
      : `<span class="historial-ausente" aria-label="${esc(p[clave])}: historial reciente no disponible">Historial reciente no disponible</span>`}</div>`;
  };
  return `<section class="historial-reciente ${enLona ? 'historial-lona j-todo' : ''}" aria-label="Resultados recientes"><div class="historial-cab"><span>Últimas cinco${enLona ? ' · reciente → anterior' : ''}</span>${enLona ? '' : '<small>Más reciente → anterior</small>'}</div><div class="historial-duelo">${lado('a')}${lado('b')}</div></section>`;
}

function etiquetaTitulo(p) {
  return p.es_titulo === true ? '<span class="pelea-cinturon">Por el título</span>' : '';
}

function combatePlegable(p, contenido, tipo = '', abierto = false) {
  const titulo = p.es_titulo === true;
  const etiqueta = tipo === 'estelar' ? 'Pelea estelar' : tipo === 'coestelar' ? 'Co-estelar' : p.segmento;
  return `<details class="combate-desplegable ${titulo ? 'combate-titulo' : ''}" data-combate="${esc(p.id)}"${abierto ? ' open' : ''}>
    <summary class="combate-cab"><span class="combate-rotulo"><span class="combate-nombres"><b data-lado="a">${esc(p.a)}</b><small>vs</small><b data-lado="b">${esc(p.b)}</b></span>
      ${etiqueta || p.es_titulo === true ? `<span class="combate-etiquetas">${esc(etiqueta || '')}${p.es_titulo === true ? `${etiqueta ? ' · ' : ''}Por el título` : ''}</span>` : ''}</span>
      <span class="pill ${claseConf(p.confianza)}">${esc(p.confianza)}</span>${pillResultado(p)}<svg class="combate-flecha" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg>
    </summary><div class="combate-contenido">${contenido}</div></details>`;
}

// La altura se anima en ambos sentidos. Al cerrar, details permanece abierto
// hasta terminar; al cambiar de dirección se parte de la altura que se ve.
// Sirve para cualquier <details> desplegable: combates, resultados del inicio
// y el análisis de cada pelea.
const transicionesCombate = new WeakMap();
function desplegarCombate(detalle, abierto, { abrir = 340, cerrar = 340 } = {}) {
  const anterior = transicionesCombate.get(detalle);
  if (!anterior && detalle.open === abierto) return;
  if (abierto) detalle.querySelectorAll('[data-analisis]').forEach(analisis => { analisis.open = false; });
  const desde = detalle.getBoundingClientRect().height;
  anterior?.animacion.cancel();
  transicionesCombate.delete(detalle);
  detalle.style.height = '';
  detalle.style.overflow = '';
  detalle.removeAttribute('data-cerrando');
  if (reducir() || typeof detalle.animate !== 'function') {
    detalle.open = abierto;
    return;
  }
  detalle.open = true;
  // Cerrado mide lo que su summary más el borde y el relleno del details. Antes
  // era "summary − 1", que no calzaba con ninguno (1 px en los combates, 2 en
  // el análisis, 4 en los resultados del inicio): al terminar de cerrar, la
  // fila daba un saltito hasta su altura real.
  const cs = getComputedStyle(detalle);
  const hasta = abierto ? detalle.getBoundingClientRect().height
    : detalle.querySelector(':scope > summary').getBoundingClientRect().height +
      ['borderTopWidth', 'borderBottomWidth', 'paddingTop', 'paddingBottom'].reduce((s, k) => s + parseFloat(cs[k]), 0);
  if (!abierto) detalle.setAttribute('data-cerrando', '');
  detalle.style.height = desde + 'px';
  detalle.style.overflow = 'hidden';
  const animacion = detalle.animate([{height:desde + 'px'}, {height:hasta + 'px'}],
    {duration:abierto ? abrir : cerrar, easing:EASE_OUT, fill:'forwards'});
  transicionesCombate.set(detalle, {animacion, abierto});
  animacion.onfinish = () => {
    detalle.open = abierto;
    detalle.style.height = '';
    detalle.style.overflow = '';
    detalle.removeAttribute('data-cerrando');
    transicionesCombate.delete(detalle);
    animacion.cancel();
  };
}

function usaOctagono(p, tipo = '') {
  return tipo === 'estelar' || p.es_titulo === true;
}

function vistaPelea(p, mov, tipo, juez = false, n = 1, total = 1) {
  return usaOctagono(p, tipo) ? jaula(p, mov, tipo)
    : juez ? actaPelea(p, mov, tipo, n, total) : tarjetaPelea(p, mov, tipo);
}

function tarjetaPelea(p, mov, tipo = '') {
  const favA = p.p_a >= p.p_b;
  return `
  <article class="pelea" data-pelea="${p.id}">
    <div class="cara">
      ${retrato(p.a, 'a')}
      <div class="centro">
        <div class="vs-nombres"><span class="n" data-lado="a">${esc(p.a)}</span><span class="x">vs</span><span class="n b" data-lado="b">${esc(p.b)}</span></div>
        <div class="vs-sub"><span>${peleasUFC(p.info_a)}</span><span>${peleasUFC(p.info_b)}</span></div>
        ${historialReciente(p)}
        <div class="pcts"><span class="${favA ? '' : 'menos'}" data-lado="a" data-num="${p.id}:pA">${pct(p.p_a)}</span><span class="${favA ? 'menos' : ''}" data-lado="b" data-num="${p.id}:pB">${pct(p.p_b)}</span></div>
        ${barraDuelo(p)}
        ${espejo(p, mov)}
      </div>
      ${retrato(p.b, 'b')}
    </div>
    ${resultadoReal(p)}
    ${metodoFila(p)}
    ${piePelea(p)}
    ${p.confianza === 'NO FIABLE' ? `<div class="explica alerta">${ico('alerta')}<div>${p.por_que_confianza}</div></div>` : ''}
  </article>`;
}

// La línea pintada a un paso de la reja, paralela a ella: es un octágono
// regular, con el corte un poco menor porque la línea va metida hacia adentro
// (misma cuenta que los recortes de las capas en el CSS).
function lineaLona(p) {
  const k = ((29.29 - 1.16 - 0.414 * 2) / (100 - 5.6 - 4) * 100).toFixed(2);
  const pts = `${k},0.5 ${100 - k},0.5 99.5,${k} 99.5,${100 - k} ${100 - k},99.5 ${k},99.5 0.5,${100 - k} 0.5,${k}`;
  const metal = p?.es_titulo === true;
  const id = 'oro-lona-' + Array.from(String(p?.id || '')).map(c => c.codePointAt(0).toString(16)).join('-');
  return `<svg class="lona-linea" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
    ${metal ? `<defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#f4df9b"/><stop offset=".28" stop-color="#bd9138"/><stop offset=".53" stop-color="#f3dfa4"/><stop offset=".78" stop-color="#9b7126"/><stop offset="1" stop-color="#dfbd68"/></linearGradient></defs>` : ''}
    <polygon points="${pts}" fill="none" stroke="${metal ? `url(#${id})` : 'currentColor'}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

// Las cifras de la jaula, en espejo: el valor de cada peleador bajo su
// columna y el rótulo en el lomo del medio.
function datosJaula(p, mov) {
  return p.mercado ? `<section class="estelar-comparativa" aria-label="Comparación del modelo y las cuotas"><h3>Cuotas y modelo</h3><div class="estelar-datos-nombres"><span data-lado="a">${esc(p.a)}</span><span data-lado="b">${esc(p.b)}</span></div>${espejo(p, mov)}</section>` : '';
}

// Solo el glifo: el texto "UFC PREDICTOR" quedaba justo detrás de las casillas
// del historial y se leía a pedazos entre ellas ("PREDI").
function marcaLona() {
  return `<svg class="lona-marca" viewBox="56 6 128 128" aria-hidden="true">
    <path d="M96 12h48l34 34v48l-34 34H96L62 94V46z" fill="none" stroke="currentColor" stroke-width="5"/>
    <path d="M111 36h20l-10 68h-20z" fill="currentColor"/></svg>`;
}

// Los retratos y el historial comparten la lona. La zona superior tiene
// margen suficiente para que las cabezas no alcancen los bordes diagonales.
function jaula(p, mov, tipo) {
  const favA = p.p_a >= p.p_b;
  const postes = [1,2,3,4,5,6,7,8].map(n => `<i class="poste p${n}"></i>`).join('');
  return `
  <article class="estelar ${p.es_titulo === true ? 'estelar-titulo' : ''}" data-pelea="${p.id}">
    <div class="estelar-distribucion"><div class="jaula-escena"><div class="jaula">
      <div class="reja-sombra"><div class="reja"></div></div><div class="baranda"></div>${postes}
      <div class="lona">
        ${lineaLona(p)}
        <div class="lona-impresion" aria-hidden="true">${marcaLona()}</div>
        ${retrato(p.a, 'a').replace('class="retrato"', 'class="retrato a"')}
        ${retrato(p.b, 'b').replace('class="retrato"', 'class="retrato b"')}
        <div class="j-a j-nombre" data-lado="a">${esc(p.a)}<small>${peleasUFC(p.info_a)}</small></div>
        <div class="j-lomo j-vs">vs</div>
        <div class="j-b j-nombre" data-lado="b">${esc(p.b)}<small>${peleasUFC(p.info_b)}</small></div>
        ${historialReciente(p, true)}
        <div class="j-a j-pct ${favA ? '' : 'menos'}" data-lado="a"><span data-lado="a" data-num="${p.id}:pA">${pct(p.p_a)}</span></div>
        <div class="j-b j-pct ${favA ? 'menos' : ''}" data-lado="b"><span data-lado="b" data-num="${p.id}:pB">${pct(p.p_b)}</span></div>
        <div class="j-todo j-barra">${barraDuelo(p)}</div>
        ${resultadoReal(p, true)}
      </div>
    </div></div>
    <aside class="estelar-datos" aria-label="Estadísticas del combate">
      ${datosJaula(p, mov)}
      <section class="estelar-metodos" aria-label="Métodos de finalización"><h3>Cómo puede terminar</h3>${metodoFila(p)}</section>
      ${piePelea(p)}
    </aside></div>
    ${p.confianza === 'NO FIABLE' ? `<div class="explica alerta">${ico('alerta')}<div>${p.por_que_confianza}</div></div>` : ''}
  </article>`;
}

/* ===================== ESTILO C: TARJETA DEL JUEZ ===================== */
// Cada pelea es la tarjeta que llena un juez: casilleros con su rótulo
// impreso, las cifras escritas a máquina en filas como los asaltos, la forma
// de terminar como casillas marcadas, el pronóstico encerrado con lápiz y la
// confianza como un timbre. Son los mismos datos y las mismas claves data-num
// que la tarjeta de transmisión, así que EN VIVO anima igual.

// El trazo del lápiz alrededor del nombre: a mano, sin cerrar del todo.
const LAPIZ = `<svg class="ac-lapiz" viewBox="0 0 200 64" preserveAspectRatio="none" aria-hidden="true">
  <path d="M16 38C8 20 50 7 102 6c54-1 90 10 92 27 2 19-46 27-100 26C40 58 6 49 8 32 9 21 38 12 72 9"
        fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
// Un juez no encierra un ganador en una pelea pareja ni sin datos: ahí el
// nombre queda escrito pero sin el círculo (el timbre ya dice por qué).
const SIN_LAPIZ = ['moneda', 'NO FIABLE'];

function actaPelea(p, mov, tipo, n, total) {
  const favA = p.p_a >= p.p_b;
  const m = p.mercado;
  const titulo = tipo === 'estelar' ? 'Pelea estelar' : (tipo === 'coestelar' ? 'Co-estelar' : '');
  const segmento = [titulo, p.segmento && p.segmento !== titulo ? p.segmento : ''].filter(Boolean).join(' · ');
  // menos: el lado que la fila no favorece (en la probabilidad, el no favorito).
  const fila = (k, lbl, a, b, clase = '', menos = '') => `<div class="ac-fila ${clase}">
      <span class="ac-v a ${menos === 'a' ? 'menos' : ''}" data-lado="a" data-num="${p.id}:${k}:A">${a}</span><span class="ac-rot">${lbl}</span><span class="ac-v b ${menos === 'b' ? 'menos' : ''}" data-lado="b" data-num="${p.id}:${k}:B">${b}</span></div>`;
  const peleador = (lado, nombre, info, fav) => `
      <div class="ac-peleador ${lado} ${fav ? 'fav' : ''}" data-lado="${lado}">
        <div class="ac-foto">${retrato(nombre, lado)}${tipo === 'estelar' ? `<span class="ac-clip">${ico('clip')}</span>` : ''}</div>
        <div class="ac-id"><small>Peleador</small><b data-lado="${lado}">${esc(nombre)}</b><span>${peleasUFC(info) || '&nbsp;'}</span></div>
      </div>`;
  const conLapiz = !SIN_LAPIZ.includes(p.confianza);
  const tendencia = p.tendencia === 'pelea promedio'
    ? 'Nada la distingue de una pelea promedio.'
    : `Más propensa a terminar así que lo normal: <b>${esc(p.tendencia)}</b>.`;
  return `
  <article class="acta ${tipo === 'estelar' ? tipo : ''}" data-pelea="${p.id}">
    <header class="ac-cab">
      <div class="ac-campo ac-n"><small>Pelea</small><b>${n} de ${total}</b></div>
      <div class="ac-campo ac-seg"><small>Segmento</small><b>${esc(segmento)}</b></div>
    </header>
    <div class="ac-cuerpo">
      ${peleador('a', p.a, p.info_a, favA)}
      ${peleador('b', p.b, p.info_b, !favA)}
      ${historialReciente(p)}
      <div class="ac-filas">
        ${fila('p', 'probabilidad de ganar', pct(p.p_a), pct(p.p_b), 'ac-prob', favA ? 'b' : 'a')}
        <div class="ac-barra">${barraDuelo(p)}</div>
        ${m ? fila('cuota', 'cuota', cuota(m.cuota_a) + flecha(mov, p.id, 'A'), cuota(m.cuota_b) + flecha(mov, p.id, 'B'))
            + fila('casa', 'le da la casa', pct(m.p_mercado_a), pct(1 - m.p_mercado_a))
            + fila('modelo', 'el modelo solo', pct(m.p_modelo_a), pct(1 - m.p_modelo_a))
            : '<p class="ac-sin">Sin cuotas: solo la probabilidad del modelo.</p>'}
      </div>
    </div>
    <div class="ac-metodo"><small class="ac-tit">Cómo termina</small>${metodoFila(p)}</div>
    <div class="ac-pronostico">
      <div class="ac-campo"><small>Pronóstico</small>
        <span class="ac-gana ${conLapiz ? 'con-lapiz' : ''}">${esc(p.ganador)}${conLapiz ? LAPIZ : ''}</span></div>
      <div class="ac-campo"><small>No llega a las tarjetas</small><b data-num="${p.id}:fin">${pct(p.p_finish, 0)}</b></div>
    </div>
    ${resultadoReal(p)}
    <div class="ac-obs"><small>Observaciones</small>
      <p>${tendencia}${m ? ` Comisión de la casa: <b>${pct(m.vig)}</b>.` : ''}</p>
      ${p.confianza === 'NO FIABLE' ? `<p class="ac-alerta">${ico('alerta')}<span>${p.por_que_confianza}</span></p>` : ''}
      ${ayudaPelea(p)}
    </div>
    <footer class="ac-pie"><span>UFC Predictor · tarjeta de pronóstico</span><span>Estimación del modelo, no una tarjeta oficial</span></footer>
  </article>`;
}

function mejorMetodo(m) {
  const k = Object.keys(m).reduce((a,b) => m[a] > m[b] ? a : b);
  const n = {'KO/TKO':'KO/TKO','Submission':'sumisión','Decision':'decisión'}[k];
  return `${n} (${fmt(m[k]*100, 0)}${NBSP_FINO}%)`;
}
function tabla(sel, cab, filas, clases = []) {
  $(sel).innerHTML =
    `<thead><tr>${cab.map(h=>`<th>${h}</th>`).join('')}</tr></thead>` +
    `<tbody>${filas.map((f,i)=>`<tr${clases[i] ? ` class="${esc(clases[i])}"` : ''}>${f.map(c =>
      String(c).startsWith('<td') ? c : `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

/* ============================== PARLAY ================================ */
function pintarTiers(tiers) {
  if (!tiers) return;
  const orden = ['A','B','C'];
  const nombres = {A:'Probado', B:'Sin ventaja clara', C:'Ruido'};
  $('#explica-tiers').innerHTML = orden.map(k => `
    <div class="tier-mini">
      <div class="tier-mini-cab"><span class="pill t${k}">${nombres[k]}</span>
        <b>${esc(tiers[k].resumen || '')}</b></div>
      <p>${esc(tiers[k].detalle)}</p>
    </div>`).join('');
}

$$('.filtro-tier').forEach(c => c.onchange = pintarPatas);
$('#solo-positivo').onchange = pintarPatas;
$('#btn-limpiar').onclick = () => quitarDelBoleto(S.elegidas.slice());
$('#btn-sugerir').onclick = () => {
  const nuevas = (S.datos?.sugerencia || []).slice();
  S.entrantes = nuevas.filter(id => !S.elegidas.includes(id));
  S.elegidas = nuevas;
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

// Sacar patas del boleto: primero salen (más rápido de lo que entraron), y recién
// después se repinta. Si se repintara antes, desaparecerían de golpe.
function quitarDelBoleto(ids) {
  const quitar = () => {
    S.elegidas = S.elegidas.filter(x => !ids.includes(x));
    pintarPatas(); evaluarParlay();
  };
  const items = ids.map(id => $(`#boleto [data-b="${CSS.escape(id)}"]`)).filter(Boolean);
  if (!items.length || porTeclado) return quitar();
  items.forEach(el => { el.style.pointerEvents = 'none'; });
  // Sale por donde entró (hacia arriba, fundiéndose).
  const anims = items.map(el => el.animate(reducir()
    ? [{ opacity: 1 }, { opacity: 0 }]
    : [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(-6px)' }],
    { duration: 140, easing: EASE_OUT, fill: 'forwards' }));
  const fin = () => {
    // Las que se quedan suben a su nuevo lugar en vez de saltar (FLIP): se
    // anota dónde estaban, se repinta y cada una viaja desde ahí.
    const antes = new Map($$('#boleto [data-b]').map(el => [el.dataset.b, el.getBoundingClientRect().top]));
    quitar();
    if (reducir()) return;
    $$('#boleto [data-b]').forEach(el => {
      const dy = (antes.get(el.dataset.b) ?? 0) - el.getBoundingClientRect().top;
      if (Math.abs(dy) > 0.5) el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }],
        { duration: 200, easing: EASE_IN_OUT });
    });
  };
  Promise.all(anims.map(a => a.finished)).then(fin, fin);
}

function pintarPatas() {
  const raizP = $('#parlay-contenido');
  const antes = S.otraCartelera ? null : capturarCifras(raizP);
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

  // El veredicto lleva su palabra y su ícono: el color nunca es la única señal.
  const V = { si:['si','ok','Conviene'], quizas:['quizas','aprox','Se puede'], no:['no','no','No conviene'] };

  const tarjeta = p => {
    const on = S.elegidas.includes(p.id);
    const bl = bloqueo[p.id];
    const [k, icono, lbl] = V[p.veredicto] || V.no;
    const aviso = bl
      ? `<div class="choque">${bl.tipo === 'excluyente'
          ? `${ico('prohibido')}<span>Imposible junto con lo que ya elegiste: no pueden pasar las dos.</span>`
          : `${ico('aprox')}<span>Se solapa con lo que ya elegiste: Betano casi no sube la cuota al combinarlas.</span>`}</div>`
      : '';
    const estado = on ? ico('ok') : bl ? ico('candado') : ico('mas');
    return `<div class="pata ${on?'elegida':''} ${bl?'bloqueada':''}" data-id="${p.id}" role="button" tabindex="0"
        aria-pressed="${on}" ${bl ? 'aria-disabled="true"' : ''}>
      <div class="pata-top">
        <div class="pata-sel">
          <b class="sel">${esc(p.seleccion)}</b>
          <div class="meta">
            <span class="pill n-${p.nivel}" title="${esc(p.nivel_detalle)}">${esc(p.nivel)}</span>
            <span class="pill t${p.tier}" title="Esto habla del PRECIO, no de la probabilidad: ${esc(p.tier_detalle)}">${esc(p.tier_nombre)}</span>
          </div>
        </div>
        <div class="precio">
          <span class="cuota" data-num="pata:${p.id}">${cuota(p.cuota)}</span>
          <span class="ev ${cls(p.ev)}" data-num="ev:${p.id}">${sgn(p.ev)}</span>
        </div>
        <span class="pata-estado" aria-hidden="true">${estado}</span>
      </div>
      <div class="probs">
        <span title="Lo que dice el modelo por su cuenta, sin mirar la cuota">
          modelo <b>${p.p_modelo != null ? pct(p.p_modelo) : 'sin dato'}</b></span>
        <span title="El modelo combinado con la línea de la casa. Es la estimación más certera de las dos (~70% de acierto contra 67%).">
          con la cuota <b>${pct(p.p)}</b></span>
      </div>
      <div class="porque"><b class="${k}">${ico(icono)}${lbl}.</b> ${esc(p.por_que)}</div>
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
        <h4 class="pelea-grupo-cab">${esc(ps[0].pelea)}</h4>
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

  $('#lista-patas').innerHTML = secciones || `<p class="lista-vacia">No hay selecciones con
    esos filtros. Prueba activando más categorías arriba.</p>`;

  // Con teclado también: cada pata es un botón (Enter o Espacio).
  $$('#lista-patas .pata').forEach(el => el.onkeydown = (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); el.click(); }
  });
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
    if (S.elegidas.includes(id)) { quitarDelBoleto([id]); return; }
    if (S.elegidas.length >= 13) { barra('Betano acepta un máximo de 13 selecciones.'); return; }
    S.elegidas.push(id);
    S.entrantes = [id];
    pintarPatas(); evaluarParlay();
  });

  $('#cuenta-patas').textContent = `${S.elegidas.length}/13`;
  const byId = Object.fromEntries(S.patas.map(p => [p.id,p]));
  $('#boleto').innerHTML = S.elegidas.length
    ? S.elegidas.map(id => { const p = byId[id];
        return `<div class="boleto-item" data-b="${id}">
          <div class="bi-que"><b>${esc(p.seleccion)}</b><span class="sub">${esc(p.pelea)}</span></div>
          <span class="bi-cuota" data-num="bol:${id}">${cuota(p.cuota)}</span>
          <button data-q="${id}" title="Quitar" aria-label="Quitar ${esc(p.seleccion)}">${ico('no')}</button>
        </div>`; }).join('')
    : `<div class="boleto-vacio">${ico('boleto')}<span>Toca una selección de la izquierda para agregarla.</span></div>`;
  $$('#boleto button').forEach(b => b.onclick = (ev) => {
    ev.stopPropagation();
    quitarDelBoleto([b.dataset.q]);
  });

  // Lo que acaba de entrar al boleto baja desde arriba, con un desfase corto si
  // entraron varias ("Armar la mejor"). La cuenta es una cifra más: si cambió,
  // la anima resaltarCambios como a las demás.
  (porTeclado ? [] : S.entrantes || []).forEach((id, i) => {
    const el = $(`#boleto [data-b="${CSS.escape(id)}"]`);
    if (el) el.animate(reducir()
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }],
      { duration: 200, delay: Math.min(i, 6) * 40, easing: EASE_OUT, fill: 'backwards' });
  });
  S.entrantes = [];
  if (antes) resaltarCambios(raizP, antes);
}

async function evaluarParlay() {
  const out = $('#parlay-resultado');
  if (S.elegidas.length < 2) {
    out.innerHTML = `<p class="boleto-nota"><b>Elige al menos 2 selecciones.</b>
      Recuerda que una combinada <b>multiplica el error</b> de cada pronóstico:
      si cada uno está un poco inflado, juntos pueden estarlo mucho. Por eso este
      sistema prefiere apuestas simples y combinadas cortas.</p>`;
    return;
  }
  try {
    const r = await post('/api/parlay', {
      ids:S.elegidas, bankroll: parseFloat($('#bankroll').value) || 100 });
    if (!r.ok) { out.innerHTML = `<div class="aviso err"><span class="ai">${ico('prohibido')}</span>
      <div>${esc(r.error)}</div></div>`; return; }

    out.innerHTML = `
      <div class="veredicto ${r.nivel}"><span class="ai">${ico(
        {bueno:'ok', aceptable:'info', flojo:'alerta', malo:'prohibido'}[r.nivel] || 'info')}</span>
        <div>${esc(r.veredicto)}</div></div>
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
  } catch (e) { out.innerHTML = `<div class="aviso err"><span class="ai">${ico('alerta')}</span>
    <div>${esc(e.message)}</div></div>`; }
}

/* ============================== INICIO ================================ */
// La portada: noticias de UFC al centro, las peleas que vienen y los eventos al
// costado (/api/inicio). Responde desde la caché del servidor; si estaba
// vencida, el servidor la refresca aparte y acá se vuelve a pedir una vez.
const INI = { datos:null, modo:'estelar', pedido:null, mostrada:false, reintento:null };
// 24 h: "21:00" y no "09:00 p. m.", que en una columna angosta se partía en dos.
const horaLocal = (ts) => new Date(ts * 1000).toLocaleTimeString('es-CL', { hour:'2-digit', minute:'2-digit', hourCycle:'h23' });
const diaLocal = (ts) => new Date(ts * 1000).toLocaleDateString('es-CL', { weekday:'short', day:'numeric', month:'short' }).replace(',', '');
const isoLocal = (ts) => new Date(ts * 1000).toLocaleDateString('sv-SE');
// "1d 4h", "3h 12m", "8m"; desde que empieza y por 6 h, EN VIVO.
function cuentaRegresiva(ts) {
  const s = ts - Date.now() / 1000;
  if (s <= 0) return s > -6 * 3600 ? null : 'terminó';
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${Math.max(1, m)}m`;
}
const pintarCuenta = (ts) => {
  const c = cuentaRegresiva(ts);
  return c === null ? '<span class="vivo-bug">En vivo</span>' : esc(c);
};
const selloEvento = (e) => {
  const n = String(e.nombre || '').match(/UFC (\d+)$/);
  return n ? `<span class="ev-sello">${n[1]}</span>`
    : `<span class="ev-sello fn">${/road to ufc/i.test(e.nombre) ? 'RTU' : 'FN'}</span>`;
};
const imagenNota = (n) => n.imagen ? `/api/inicio/imagen/${encodeURIComponent(n.id)}` : '';
function haceCuanto(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 60) return `hace ${Math.max(1, min)} min`;
  if (min < 24 * 60) return `hace ${Math.round(min / 60)} h`;
  return fechaCorta(new Date(iso).toLocaleDateString('sv-SE'));
}

async function cargarInicio({ forzar = false } = {}) {
  if (INI.pedido && !forzar) return INI.pedido;
  if (!forzar) cargarResultados();
  INI.pedido = (async () => {
    try {
      const d = await api('/api/inicio');
      const primera = !INI.datos;
      INI.datos = d;
      pintarInicio(d, primera);
      clearTimeout(INI.reintento);
      if (d.actualizando) INI.reintento = setTimeout(() => cargarInicio({ forzar: true }), 12000);
    } catch (e) {
      if (!INI.datos) $('#noticias').innerHTML = `<div class="aviso err"><span class="ai">${ico('alerta')}</span><div>${esc(e.message)}</div></div>`;
    } finally { INI.pedido = null; }
  })();
  return INI.pedido;
}

function pintarInicio(d, primera) {
  // La cartelera que ya está cargada, arriba, para volver a ella.
  const actual = $('#inicio-actual');
  actual.classList.toggle('oculto', !d.actual);
  if (d.actual) {
    const ev = S.evento || evento({ titulo: d.actual.titulo });
    actual.innerHTML = `<small>${d.actual.corte ? 'Repetición cargada' : 'Cartelera cargada'}</small>
      <b>${esc(ev.nombre)}</b><small>${d.actual.peleas} peleas</small>
      <button class="secundario" data-ir="cartelera">Ver pronósticos${ico('ir')}</button>`;
    actual.querySelector('[data-ir]').onclick = () => irA('cartelera');
  }
  pintarNoticias(d);
  pintarProximas(d);
  pintarEventos(d);
  ['#noticias', '#proximas', '#eventos'].forEach(s => $(s).removeAttribute('aria-busy'));
  if (primera && !INI.mostrada) { INI.mostrada = true; entradaInicio(); }
}

function pintarNoticias(d) {
  const notas = d.noticias || [];
  $('#noticias-estado').textContent = d.sin_conexion ? 'sin conexión'
    : d.actualizando ? 'actualizando…' : d.consultado ? `al día · ${horaLocal(d.consultado)}` : '';
  if (!notas.length) {
    $('#noticias').innerHTML = `<p class="ev-vacio">${d.sin_conexion
      ? 'No se pudo consultar UFC y todavía no hay noticias guardadas. Se completan solas cuando haya internet; el resto de la aplicación funciona igual.'
      : 'Todavía no hay noticias.'}</p>`;
    return;
  }
  const [portada, ...resto] = notas;
  const destacadas = resto.filter(n => n.imagen).slice(0, 2);
  const lista = notas.filter(n => n !== portada && !destacadas.includes(n));
  const enlace = (n) => `href="${esc(n.url)}" target="_blank" rel="noopener noreferrer"`;
  let html = `<a class="nota-portada" ${enlace(portada)}>
      ${portada.imagen ? `<img src="${imagenNota(portada)}" alt="" decoding="async">` : ''}
      <span class="np-texto"><span class="np-cuando">${esc(haceCuanto(portada.fecha))}</span>
        <b>${esc(portada.titulo)}</b>${portada.autor ? `<span>${esc(portada.autor)}</span>` : ''}</span></a>`;
  if (destacadas.length) html += `<div class="notas-destacadas">${destacadas.map(n => `
    <a class="nota-destacada" ${enlace(n)}><span class="nd-imagen"><img src="${imagenNota(n)}" alt="" loading="lazy" decoding="async"></span>
      <span class="nd-texto"><small>${esc(haceCuanto(n.fecha))}</small><b>${esc(n.titulo)}</b></span></a>`).join('')}</div>`;
  // Por día, como en la portada de un sitio de liga: hoy y ayer con su rótulo.
  const hoy = hoyISO(), ayer = new Date(Date.now() - 864e5).toLocaleDateString('sv-SE');
  const dias = new Map();
  lista.forEach(n => {
    const dia = new Date(n.fecha).toLocaleDateString('sv-SE');
    if (!dias.has(dia)) dias.set(dia, []);
    dias.get(dia).push(n);
  });
  dias.forEach((ns, dia) => {
    const tag = dia === hoy ? '<span class="dia-tag hoy">Hoy</span>' : dia === ayer ? '<span class="dia-tag">Ayer</span>' : '';
    html += `<h3 class="dia">${esc(fechaLarga(dia))}${tag}</h3><ul class="titulares">${ns.map(n => `
      <li><a class="titular" ${enlace(n)}><span class="titular-hora">${esc(horaLocal(new Date(n.fecha) / 1000))}</span>
        <span class="titular-texto">${esc(n.titulo)}</span>${ico('ir')}</a></li>`).join('')}</ul>`;
  });
  $('#noticias').innerHTML = html;
  $$('#noticias img').forEach(img => img.onerror = () => img.remove());
}

function pintarProximas(d) {
  // Las próximas cuatro carteleras: más allá, la columna sería un listado eterno.
  const eventos = (d.proximos || []).slice(0, 4);
  if (!eventos.length) {
    $('#proximas').innerHTML = `<p class="ev-vacio">${d.sin_conexion ? 'Sin conexión con UFC y sin carteleras guardadas.' : 'UFC no tiene carteleras anunciadas.'}</p>`;
    return;
  }
  const todas = INI.modo === 'todas';
  $('#proximas').innerHTML = eventos.map(e => {
    const peleas = (e.peleas || []).filter(p => todas || p.seccion === 'estelar');
    const fila = (p) => {
      const ts = e.inicio[p.seccion] || e.inicio.estelar;
      const peso = [p.peso, p.seccion !== 'estelar' ? (p.seccion === 'early' ? 'early' : 'prelim.') : ''].filter(Boolean).join(' · ');
      return `<li class="pp${p.titulo ? ' titulo' : ''}">
        <span class="pp-n" data-lado="a"><i aria-hidden="true"></i><span>${esc(p.a)}</span>${p.rango_a ? `<small>${esc(p.rango_a)}</small>` : ''}</span>
        <span class="pp-n" data-lado="b"><i aria-hidden="true"></i><span>${esc(p.b)}</span>${p.rango_b ? `<small>${esc(p.rango_b)}</small>` : ''}</span>
        <span class="pp-meta"><b class="pp-cuenta" data-ts="${ts}">${pintarCuenta(ts)}</b>${
          p.titulo ? '<span class="pp-titulo">Por el título</span>' : ''}<small>${esc(peso)}</small></span></li>`;
    };
    // Las carteleras lejanas todavía no se bajan pelea por pelea: su estelar sale
    // del titular del evento.
    const cuerpo = peleas.length ? peleas.map(fila).join('')
      : `<li class="pp-solo"><span>${esc(e.titular)}</span><b class="pp-cuenta" data-ts="${e.inicio.estelar}">${pintarCuenta(e.inicio.estelar)}</b></li>`;
    return `<div class="prox-evento"><b>${esc(e.nombre)}</b><span>${esc(diaLocal(e.inicio.estelar))} · ${esc(horaLocal(e.inicio.estelar))}</span></div>
      <ul class="prox-lista">${cuerpo}</ul>`;
  }).join('');
}

function pintarEventos(d) {
  const ahora = Date.now() / 1000;
  const proximos = d.proximos || [];
  const enVivo = proximos.filter(e => (e.inicio.early || e.inicio.preliminares || e.inicio.estelar) <= ahora);
  const siguientes = proximos.filter(e => !enVivo.includes(e)).slice(0, 6);
  // Sin peleas publicadas no hay nada que predecir: la fila informa y no es botón.
  const filaProxima = (e) => !e.peleas?.length
    ? `<div class="ev">${selloEvento(e)}<span class="ev-que">${esc(e.nombre)}<small>${esc(e.titular)}</small></span>
        <span class="ev-datos"><span class="ev-chip">${esc(diaLocal(e.inicio.estelar))}</span><span class="ev-nota">cartelera sin publicar</span></span></div>`
    : `<button type="button" class="ev" data-ufc="${esc(e.id)}" aria-label="Predecir ${esc(e.nombre)}, ${esc(e.titular)}">
      ${selloEvento(e)}<span class="ev-que">${esc(e.nombre)}<small>${esc(e.titular)}</small></span>
      <span class="ev-datos"><span class="ev-chip">${esc(diaLocal(e.inicio.estelar))}</span>${
        e.ciudad || e.pais ? `<span class="ev-chip lugar">${esc(e.ciudad || e.pais)}</span>` : ''}</span>
      <span class="ev-ir">${ico('ir')}<span>Predecir</span></span></button>`;
  const filaReciente = (e) => e.en_base
    ? `<button type="button" class="ev" data-evento="${esc(e.en_base.evento)}" data-fecha="${esc(e.en_base.fecha)}"
        aria-label="Repetir ${esc(e.nombre)}, ${esc(e.titular)}">
        ${selloEvento(e)}<span class="ev-que">${esc(e.nombre)}<small>${esc(e.titular)}</small></span>
        <span class="ev-datos"><span class="ev-chip">${esc(diaLocal(e.inicio.estelar))}</span></span>
        <span class="ev-ir">${ico('repetir')}<span>Repetir</span></span></button>`
    : `<div class="ev apagado">${selloEvento(e)}<span class="ev-que">${esc(e.nombre)}<small>${esc(e.titular)}</small></span>
        <span class="ev-datos"><span class="ev-chip">${esc(diaLocal(e.inicio.estelar))}</span><span class="ev-nota">aún no está en tu base</span></span></div>`;
  // Lo que la base local sí tiene: siempre se puede repetir.
  const yaListados = new Set((d.recientes || []).filter(e => e.en_base).map(e => e.en_base.evento));
  const base = (d.en_base || []).filter(p => !yaListados.has(p.evento)).slice(0, 4);
  const filaBase = (p) => {
    const n = String(p.evento).match(/^UFC (\d+)/);
    return `<button type="button" class="ev" data-evento="${esc(p.evento)}" data-fecha="${esc(p.fecha)}" data-a="${esc(p.a)}" data-b="${esc(p.b)}"
      aria-label="Repetir ${esc(p.evento)}">
      <span class="ev-sello ${n ? '' : 'fn'}">${n ? n[1] : 'FN'}</span><span class="ev-que">${esc(apellidoDe(p.a))} vs ${esc(apellidoDe(p.b))}<small>${esc(p.evento.replace(/:.*/, ''))}</small></span>
      <span class="ev-datos"><span class="ev-chip">${esc(fechaCorta(p.fecha))}</span></span>
      <span class="ev-ir">${ico('repetir')}<span>Repetir</span></span></button>`;
  };
  const grupo = (titulo, filas) => filas ? `<div class="ev-grupo"><h3>${titulo}</h3><div class="ev-lista">${filas}</div></div>` : '';
  $('#eventos').innerHTML =
    grupo('En vivo', enVivo.map(filaProxima).join(''))
    + grupo('Próximos', siguientes.map(filaProxima).join(''))
    + grupo('Terminados', (d.recientes || []).slice(0, 4).map(filaReciente).join(''))
    + grupo('En tu base', base.map(filaBase).join(''))
    || `<p class="ev-vacio">Sin eventos para mostrar.</p>`;
  $$('#eventos button.ev[data-ufc]').forEach(b => b.onclick = () => accionEvento(b,
    () => post('/api/cartelera/ufc', { id: b.dataset.ufc })));
  $$('#eventos button.ev[data-evento]').forEach(b => b.onclick = () => accionEvento(b, async () => {
    await post('/api/cartelera/anterior', { evento: b.dataset.evento, fecha: b.dataset.fecha });
    if (b.dataset.a) S.abrirPelea = [b.dataset.a, b.dataset.b];
  }));
}
async function accionEvento(b, accion) {
  if (b.classList.contains('cargando')) return;
  b.classList.add('cargando');
  const txt = b.querySelector('.ev-ir span'), antes = txt.textContent;
  txt.textContent = 'Preparando…';
  try { await accion(); irA('cartelera'); await tick(); }
  catch (e) { barra(e.message, 'error'); }
  finally { b.classList.remove('cargando'); txt.textContent = antes; }
}

/* ------------------ resultados de las últimas carteleras ------------------ */
// El pronóstico de ese día contra cómo terminó, cartelera por cartelera
// (/api/inicio/resultados). Cada una es un plegable como los combates: la
// primera vez están todas cerradas y después se recuerda cuál dejaste abierta.
// Mientras el servidor predice las que faltan, se vuelve a preguntar y solo se
// reemplaza la fila que cambió: la que tienes abierta no se cierra sola.
const RES = { datos:null, pedido:null, reintento:null, mostrada:false };
const METODO_TXT = { 'KO/TKO': 'KO/TKO', 'Submission': 'sumisión', 'Decision': 'decisión' };
const claveRes = (c) => `${c.fecha}|${c.evento}`;
function abiertosRes() {
  try { return new Set(JSON.parse(leer('resultados-abiertos') || '[]')); } catch { return new Set(); }
}
function recordarRes(clave, abierto) {
  const s = abiertosRes();
  if (abierto) s.add(clave); else s.delete(clave);
  guardar('resultados-abiertos', s.size ? JSON.stringify([...s]) : null);
}

async function cargarResultados() {
  if (RES.pedido) return RES.pedido;
  RES.pedido = (async () => {
    try {
      const d = await api('/api/inicio/resultados');
      RES.datos = d;
      pintarResultados(d);
      clearTimeout(RES.reintento);
      if (d.calculando) RES.reintento = setTimeout(cargarResultados, 5000);
    } catch (e) {
      if (!RES.datos) $('#resultados-lista').innerHTML = `<p class="ev-vacio">${esc(e.message)}</p>`;
    } finally {
      RES.pedido = null;
      $('#resultados-lista').removeAttribute('aria-busy');
    }
  })();
  return RES.pedido;
}

// "UFC 322: Della Maddalena vs. Makhachev" -> sello 322 y el titular aparte.
function partesEvento(evento) {
  const [nombre, ...resto] = String(evento).split(':');
  const n = nombre.match(/^UFC (\d+)\s*$/);
  return { nombre: nombre.trim(), titular: resto.join(':').trim().replace(/\bvs\.\s/gi, 'vs '),
    sello: n ? `<span class="ev-sello">${n[1]}</span>` : '<span class="ev-sello fn">FN</span>' };
}
const estadoRes = (v) => v === true ? 'si' : v === false ? 'no' : 'nd';
function selloRes(v, que) {
  const e = estadoRes(v);
  const txt = e === 'nd' ? `${que}: sin dato` : `${e === 'si' ? 'Acertó' : 'Falló'} ${que.toLowerCase()}`;
  return `<span class="res-sello" data-acierto="${e}" title="${esc(txt)}">${ico(e === 'si' ? 'ok' : e === 'no' ? 'no' : 'duda')}<span>${esc(que)}</span></span>`;
}

function filaResultado(p, i) {
  const r = p.resultado;
  const pick = (lado) => p.ganador === p[lado] ? ' class="pick"' : '';
  const real = !r ? '<b>Todavía no está en la base</b>'
    : `<b>${r.ganador ? `Ganó ${esc(apellidoDe(r.ganador))}` : r.como === 'sin resultado' ? 'Sin resultado' : 'Empate'}</b>
       <span>${esc([r.como, r.asalto ? `R${r.asalto}${r.tiempo ? ' ' + r.tiempo : ''}` : ''].filter(Boolean).join(' · '))}</span>`;
  return `<li class="res-pelea${p.es_titulo ? ' titulo' : ''}" data-acierto="${estadoRes(p.acierto)}">
    <span class="res-n">${String(i + 1).padStart(2, '0')}</span>
    <span class="res-vs"><span><b${pick('a')}>${esc(p.a)}</b> <small>vs</small> <b${pick('b')}>${esc(p.b)}</b></span>${
      p.es_titulo ? '<span class="res-cinturon">Por el título</span>' : p.estelar ? '<span class="res-cinturon estelar">Estelar</span>' : ''}</span>
    <span class="res-col res-pron"><small>Pronóstico</small><b>${esc(apellidoDe(p.ganador))} <i>${pct(p.p, 0)}</i></b>
      <span>por ${esc(METODO_TXT[p.metodo] || p.metodo)}${p.p_metodo != null ? ` (${pct(p.p_metodo, 0)})` : ''}</span></span>
    <span class="res-col res-real"><small>Resultado</small>${real}</span>
    <span class="res-sellos">${selloRes(p.acierto, 'Ganador')}${selloRes(p.acierto_metodo, 'Método')}</span>
  </li>`;
}

function itemResultado(c, i, abiertos) {
  const ev = partesEvento(c.evento);
  const cab = `${ev.sello}<span class="res-nombre"><b>${esc(ev.nombre)}</b><small>${esc([ev.titular, fechaCorta(c.fecha)].filter(Boolean).join(' · '))}</small></span>`;
  if (c.pendiente) return `<div class="res-ev pendiente" data-clave="${esc(claveRes(c))}" data-estado="pendiente">
    <div class="res-cab">${cab}<span class="res-espera">${ico('reloj')}Prediciendo con los datos de ese día…</span></div></div>`;
  if (c.error) return `<div class="res-ev con-error" data-clave="${esc(claveRes(c))}" data-estado="error">
    <div class="res-cab">${cab}<span class="res-espera">${ico('alerta')}No se pudo predecir: ${esc(c.error)}</span></div></div>`;
  const marca = (ok, n, que) => `<span class="res-marca"><span class="res-marca-n"><b data-num="res:${i}:${que}">${ok}</b><small>/${n}</small></span><span>${que}</span></span>`;
  return `<details class="res-ev" data-clave="${esc(claveRes(c))}" data-estado="listo"${abiertos.has(claveRes(c)) ? ' open' : ''}>
    <summary class="res-cab">${cab}
      <ol class="res-tira" aria-hidden="true">${c.peleas.map(p => `<li data-acierto="${estadoRes(p.acierto)}"></li>`).join('')}</ol>
      <span class="res-marcas" aria-label="Acertó ${c.aciertos} de ${c.resueltas} ganadores y ${c.aciertos_metodo} de ${c.metodos} métodos">
        ${marca(c.aciertos, c.resueltas, 'ganador')}${marca(c.aciertos_metodo, c.metodos, 'método')}</span>
      <svg class="res-flecha" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg>
    </summary>
    <div class="res-cuerpo">
      <ol class="res-peleas">${c.peleas.map(filaResultado).join('')}</ol>
      <div class="res-pie">
        <p>Predicha con lo que se sabía ese día${c.con_cuotas ? ' y las cuotas de cierre' : ', sin cuotas'}. Una
          noche no mide un modelo: con ${c.resueltas} peleas el margen es de ±${Math.round(50 / Math.sqrt(Math.max(1, c.resueltas)))} puntos.</p>
        <button type="button" class="secundario res-repetir" data-evento="${esc(c.evento)}" data-fecha="${esc(c.fecha)}">${ico('repetir')}<span>Ver la repetición completa</span></button>
      </div>
    </div>
  </details>`;
}

function pintarResultados(d) {
  const lista = $('#resultados-lista');
  const estado = $('#resultados-estado');
  if (d.sin_base || !d.carteleras?.length) {
    estado.textContent = '';
    lista.innerHTML = `<p class="ev-vacio">Cuando la base local tenga resultados (Mantenimiento → <b>Resultados de UFCStats</b>),
      acá aparece cómo le fue al modelo en las últimas tres carteleras, pelea por pelea.</p>`;
    return;
  }
  const listas = d.carteleras.filter(c => c.peleas);
  const suma = (k) => listas.reduce((s, c) => s + (c[k] || 0), 0);
  estado.textContent = d.calculando ? 'calculando…'
    : `ganador ${suma('aciertos')}/${suma('resueltas')} · método ${suma('aciertos_metodo')}/${suma('metodos')}`;
  // Solo se reemplaza la fila cuyo estado cambió (la que estaba calculándose).
  const abiertos = abiertosRes();
  const previas = new Map($$('#resultados-lista [data-clave]').map(el => [el.dataset.clave, el]));
  const nuevas = [];
  const primera = !RES.mostrada;
  lista.querySelector(':scope > .ev-vacio')?.remove();
  d.carteleras.forEach((c, i) => {
    const html = itemResultado(c, i, abiertos);
    const estadoNuevo = c.pendiente ? 'pendiente' : c.error ? 'error' : 'listo';
    let el = previas.get(claveRes(c));
    if (!el || el.dataset.estado !== estadoNuevo) {
      const t = document.createElement('template');
      t.innerHTML = html.trim();
      const nuevo = t.content.firstElementChild;
      if (el) { el.replaceWith(nuevo); if (!primera) nuevas.push(nuevo); }
      el = nuevo;
      prepararResultado(el);
    }
    previas.delete(claveRes(c));
    lista.append(el);                         // en el orden de la respuesta
  });
  previas.forEach(el => el.remove());
  if (primera) { RES.mostrada = true; entradaResultados(); }
  nuevas.forEach(revelarResultadoListo);
}

function prepararResultado(el) {
  if (el.tagName !== 'DETAILS') return;
  el.querySelector(':scope > summary').addEventListener('click', evento => {
    evento.preventDefault();
    const abrir = !(transicionesCombate.get(el)?.abierto ?? el.open);
    const cerrado = !transicionesCombate.get(el) && !el.open;
    desplegarCombate(el, abrir);
    recordarRes(el.dataset.clave, abrir);
    if (abrir && cerrado) abrirResultado(el);
  });
  const b = el.querySelector('.res-repetir');
  b.onclick = () => conCarga(b, b.querySelector('span'), async () => {
    await post('/api/cartelera/anterior', { evento: b.dataset.evento, fecha: b.dataset.fecha });
    irA('cartelera');
    await tick();
  });
}

// Al abrir una cartelera, sus peleas bajan una tras otra como las líneas del
// resultado oficial y los sellos se estampan al final de cada fila.
function abrirResultado(el) {
  if (reducir() || porTeclado) return;
  el.querySelectorAll('.res-pelea').forEach((fila, i) => {
    const delay = 60 + Math.min(i, 12) * 40;
    fila.animate([{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }],
      { duration: 280, delay, easing: EASE_OUT, fill: 'backwards' });
    fila.querySelectorAll('.res-sello').forEach((s, k) => s.animate(
      [{ opacity: 0, transform: 'scale(1.35)' }, { opacity: 1, transform: 'none' }],
      { duration: 200, delay: delay + 160 + k * 70, easing: EASE_OUT, fill: 'backwards' }));
  });
  el.querySelector('.res-pie')?.animate([{ opacity: 0 }, { opacity: 1 }],
    { duration: 300, delay: 220, easing: EASE_OUT, fill: 'backwards' });
}

// La primera vez: cada cartelera entra desde abajo, su tira se completa pelea
// por pelea y los marcadores corren hasta su valor.
function entradaResultados() {
  if (reducir()) return;
  $$('#resultados-lista .res-ev').forEach((ev, i) => {
    ev.animate([{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }],
      { duration: 380, delay: 80 + i * 90, easing: EASE_OUT, fill: 'backwards' });
    animarTira(ev, 220 + i * 90);
  });
}
function animarTira(ev, delay) {
  ev.querySelectorAll('.res-tira li').forEach((c, k) => c.animate(
    [{ opacity: 0, transform: 'scaleY(0)' }, { opacity: 1, transform: 'none' }],
    { duration: 220, delay: delay + Math.min(k, 14) * 28, easing: EASE_OUT, fill: 'backwards' }));
  ev.querySelectorAll('.res-marca [data-num]').forEach(cifra => contar(cifra, delay, 520));
}
// La cartelera que terminó de calcularse se descubre de izquierda a derecha.
function revelarResultadoListo(ev) {
  if (reducir()) return;
  ev.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
    { duration: 460, easing: EASE_OUT });
  animarTira(ev, 160);
}

// La portada entra una vez por visita: la nota de portada se descubre como el
// cartel de apertura (la foto se asienta y el titular se barre de izquierda a
// derecha) y las columnas se completan fila por fila.
function entradaInicio() {
  if (reducir()) return;
  const anim = (el, frames, op) => el?.animate(frames, { easing: EASE_OUT, fill: 'backwards', ...op });
  anim($('.nota-portada img'), [{ scale: 1.1, opacity: .4 }, { scale: 1, opacity: 1 }], { duration: 900 });
  anim($('.np-cuando'), [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], { duration: 320, delay: 200 });
  anim($('.np-texto b'), [{ clipPath: 'inset(0 100% 0 0)', translate: '-12px 0' }, { clipPath: 'inset(0 0 0 0)', translate: '0 0' }], { duration: 520, delay: 280 });
  $$('.nota-destacada').forEach((n, i) => anim(n, [{ opacity: 0, translate: '0 10px' }, { opacity: 1, translate: '0 0' }], { duration: 360, delay: 380 + i * 80 }));
  [...$$('#noticias .dia, #noticias .titulares li')].slice(0, 14).forEach((n, i) =>
    anim(n, [{ opacity: 0, translate: '0 6px' }, { opacity: 1, translate: '0 0' }], { duration: 260, delay: 480 + i * 30 }));
  [...$$('#proximas .prox-evento, #proximas .prox-lista li')].slice(0, 16).forEach((n, i) =>
    anim(n, [{ opacity: 0, translate: '8px 0' }, { opacity: 1, translate: '0 0' }], { duration: 260, delay: 160 + i * 30 }));
  $$('#eventos .ev').forEach((n, i) =>
    anim(n, [{ opacity: 0, translate: '8px 0' }, { opacity: 1, translate: '0 0' }], { duration: 260, delay: 240 + Math.min(i, 10) * 35 }));
}

// Las cuentas regresivas avanzan solas; la que cambia sube como las cifras de EN VIVO.
setInterval(() => {
  if (!INI.datos || !$('#tab-inicio').classList.contains('activa')) return;
  $$('#tab-inicio .pp-cuenta[data-ts]').forEach(el => {
    const nuevo = pintarCuenta(Number(el.dataset.ts));
    if (el.innerHTML === nuevo) return;
    el.innerHTML = nuevo;
    if (!reducir()) el.animate([{ opacity: 0, transform: 'translateY(35%)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: EASE_OUT });
  });
}, 30000);

$$('.seg[data-prox]').forEach(b => b.onclick = () => {
  $$('.seg[data-prox]').forEach(x => x.classList.toggle('activa', x === b));
  INI.modo = b.dataset.prox;
  if (!INI.datos) return;
  pintarProximas(INI.datos);
  if (!reducir() && !porTeclado) [...$$('#proximas .prox-evento, #proximas .prox-lista li')].slice(0, 20).forEach((n, i) =>
    n.animate([{ opacity: 0, translate: '6px 0' }, { opacity: 1, translate: '0 0' }],
      { duration: 220, delay: i * 20, easing: EASE_OUT, fill: 'backwards' }));
});

/* ============================== CARGAR ================================ */
$('#btn-refresh').onclick = async () => {
  try { await post('/api/refrescar'); await tick(); }
  catch (e) { barra(e.message,'error'); }
};

// Carteleras de Betano: se listan SOLAS al entrar a la pestaña y cada una
// predice con un clic. Antes había que apretar un botón, leer los nombres y
// escribir el nombre a mano en el campo de abajo: tres pasos para algo que
// Betano ya nos está diciendo.
let carterasCargadas = false;

// Una fila de lista entra desde abajo y, si tiene cara a cara, cada retrato
// llega desde su esquina. Solo las filas nuevas; con menos movimiento, nada.
function entrarFilas(filas, { paso = 35, max = 8, retratos = false } = {}) {
  if (reducir()) return;
  filas.forEach((fila, i) => {
    const delay = Math.min(i, max) * paso;
    fila.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
      { duration: 280, delay, easing: EASE_OUT, fill: 'backwards' });
    if (!retratos) return;
    fila.querySelectorAll('.ant-retrato').forEach(r => {
      const desde = r.dataset.lado === 'a' ? '-40%' : '40%';
      r.animate([{ opacity: 0, translate: `${desde} 0`, clipPath: `inset(0 ${r.dataset.lado === 'a' ? '100% 0 0' : '0 0 100%'})` },
                 { opacity: 1, translate: '0 0', clipPath: 'inset(0 0 0 0)' }],
        { duration: 420, delay: delay + 90, easing: EASE_OUT, fill: 'backwards' });
    });
    fila.querySelectorAll('.ant-n').forEach(n => n.animate([{ opacity: 0 }, { opacity: 1 }],
      { duration: 260, delay: delay + 160, easing: EASE_OUT, fill: 'backwards' }));
  });
}
// La fila elegida queda marcando que carga (una franja la recorre por abajo)
// y su acción dice "Preparando…" hasta que la cartelera llega.
async function conCarga(fila, etiqueta, accion) {
  if (fila.classList.contains('cargando')) return;
  fila.classList.add('cargando');
  const antes = etiqueta?.textContent;
  if (etiqueta) etiqueta.textContent = 'Preparando…';
  try { await accion(); }
  catch (e) { barra(e.message, 'error'); }
  finally { fila.classList.remove('cargando'); if (etiqueta) etiqueta.textContent = antes; }
}

/* -------------------------- peleas anteriores -------------------------- */
// La lista del boceto: cada pelea con su fecha, su evento y el cara a cara.
// Elegirla carga su cartelera con los datos de ese día (/api/cartelera/anterior).
const ANT = { q:'', limite:16, pedido:0, cargadas:false, hayMas:false };
const retratoMini = (nombre, lado) => {
  const url = FOTOS.get(nombre);
  return `<span class="retrato ant-retrato" data-lado="${lado}" data-foto="${esc(nombre)}">${
    url ? `<img src="${url}" alt="" decoding="async">` : SILUETA}</span>`;
};
const filaAnterior = (p) => `<button type="button" class="anterior${p.titulo ? ' titulo' : ''}" data-evento="${esc(p.evento)}" data-fecha="${esc(p.fecha)}"
    data-a="${esc(p.a)}" data-b="${esc(p.b)}" data-clave="${esc(p.fecha + '|' + p.a + '|' + p.b)}"
    aria-label="Repetir ${esc(p.a)} contra ${esc(p.b)}, ${esc(p.evento)}, ${esc(fechaLarga(p.fecha))}">
  <span class="ant-cab"><span class="ant-fecha">${esc(fechaLarga(p.fecha))}</span><span class="ant-evento">${esc(p.evento)}</span>${
    p.titulo ? '<span class="ant-titulo">Por el título</span>' : p.estelar ? '<span class="ant-estelar">Estelar</span>' : ''}</span>
  <span class="ant-duelo">
    ${retratoMini(p.a, 'a')}
    <b class="ant-n" data-lado="a">${esc(p.a)}</b>
    <span class="ant-vs" aria-hidden="true"><span class="ant-vs-txt">vs</span><span class="ant-ir">${ico('repetir')}<span class="ant-ir-txt">Repetir</span></span></span>
    <b class="ant-n" data-lado="b">${esc(p.b)}</b>
    ${retratoMini(p.b, 'b')}
  </span>
</button>`;
// Las fotos se piden solo al acercarse a la pantalla: el servidor las baja de a
// una, y una lista larga las pediría todas juntas.
let observadorFotos;
function fotosAlVerse(raiz) {
  if (!('IntersectionObserver' in window)) { cargarFotos(raiz); return; }
  observadorFotos ??= new IntersectionObserver(entradas => entradas.forEach(e => {
    if (!e.isIntersecting) return;
    observadorFotos.unobserve(e.target);
    cargarFotos(e.target);
  }), { rootMargin: '200px 0px' });
  raiz.querySelectorAll('.anterior').forEach(fila => observadorFotos.observe(fila));
}
async function listarAnteriores({ forzar = false } = {}) {
  const div = $('#lista-anteriores');
  if (ANT.cargadas && !forzar) return;
  ANT.cargadas = true;
  const pedido = ++ANT.pedido;
  if (!div.querySelector('.anterior:not(.esqueleto)'))
    div.innerHTML = `<div class="anterior esqueleto" aria-hidden="true"><span class="ant-cab"></span><span class="ant-duelo"></span></div>`.repeat(2)
      + '<p class="sr">buscando peleas en la base…</p>';
  else div.setAttribute('aria-busy', 'true');
  try {
    const r = await api(`/api/anteriores?q=${encodeURIComponent(ANT.q)}&limite=${ANT.limite}`);
    if (pedido !== ANT.pedido) return;          // ya hay una búsqueda más nueva
    $('#anteriores-rango').textContent = r.hasta ? `base hasta el ${fechaLarga(r.hasta)}` : '';
    ANT.hayMas = r.peleas.length < r.total && ANT.limite < 240;
    if (!r.peleas.length) {
      div.innerHTML = `<p class="lista-vacia">${ANT.q
        ? `Ninguna pelea de la base coincide con «${esc(ANT.q)}». Prueba con el apellido, o con el número del evento.`
        : 'La base local todavía no tiene peleas. Corre "Resultados de UFCStats" en Mantenimiento.'}</p>`;
      return;
    }
    const antes = new Set($$('#lista-anteriores .anterior').map(b => b.dataset.clave));
    div.innerHTML = r.peleas.map(filaAnterior).join('') + `<p class="anteriores-fin">${
      ANT.hayMas ? 'Cargando más peleas…' : ANT.q ? `${r.total} pelea${r.total === 1 ? '' : 's'} en la base`
      : `La base empieza en ${r.desde?.slice(0, 4) || '2013'}`}</p>`;
    fotosAlVerse(div);
    seguirFinAnteriores(div);
    // Las filas nuevas entran como lista, con los retratos llegando desde su
    // esquina; las que ya estaban, quietas.
    entrarFilas($$('#lista-anteriores .anterior').filter(f => !antes.has(f.dataset.clave)),
      { paso: 40, retratos: true });
    div.querySelectorAll('.anterior').forEach(b => b.onclick = () => repetirAnterior(b));
  } catch (e) {
    if (pedido !== ANT.pedido) return;
    div.innerHTML = `<div class="aviso err"><span class="ai">${ico('alerta')}</span><div>${esc(e.message)}</div></div>`;
    ANT.cargadas = false;                         // que se pueda reintentar
  } finally {
    if (pedido === ANT.pedido) div.removeAttribute('aria-busy');
  }
}
// La lista se completa sola al llegar al final de su propio scroll, y el
// difuminado de abajo solo está mientras queda lista por ver.
let observadorFinAnteriores;
function seguirFinAnteriores(div) {
  observadorFinAnteriores?.disconnect();
  const fin = div.querySelector('.anteriores-fin');
  marcarHayMas();
  if (!fin || !ANT.hayMas || !('IntersectionObserver' in window)) return;
  observadorFinAnteriores = new IntersectionObserver(entradas => {
    if (entradas.some(e => e.isIntersecting)) cargarMasAnteriores();
  }, { root: div, rootMargin: '0px 0px 120px 0px' });
  observadorFinAnteriores.observe(fin);
}
function cargarMasAnteriores() {
  if (!ANT.hayMas || $('#lista-anteriores').hasAttribute('aria-busy')) return;
  observadorFinAnteriores?.disconnect();
  ANT.hayMas = false;                 // una sola petición por llegada al final
  ANT.limite = Math.min(240, ANT.limite + 16);
  listarAnteriores({ forzar: true });
}
// También por el scroll mismo: el observador no corre si la pestaña está en
// segundo plano, y una lista que no crece parece rota.
function marcarHayMas() {
  const div = $('#lista-anteriores');
  const falta = div.scrollHeight - div.scrollTop - div.clientHeight;
  div.classList.toggle('hay-mas', falta > 8);
  if (falta < 160) cargarMasAnteriores();
}
$('#lista-anteriores').addEventListener('scroll', marcarHayMas, { passive: true });

async function repetirAnterior(b) {
  if (b.classList.contains('cargando')) return;
  b.classList.add('cargando');
  b.querySelector('.ant-ir-txt').textContent = 'Preparando…';
  try {
    await post('/api/cartelera/anterior', { evento: b.dataset.evento, fecha: b.dataset.fecha });
    S.abrirPelea = [b.dataset.a, b.dataset.b];
    irA('cartelera'); await tick();
  } catch (e) { barra(e.message, 'error'); }
  finally {
    b.classList.remove('cargando');
    b.querySelector('.ant-ir-txt').textContent = 'Repetir';
  }
}
let esperaBusqueda;
$('#buscar-anterior').addEventListener('input', (e) => {
  clearTimeout(esperaBusqueda);
  esperaBusqueda = setTimeout(() => {
    ANT.q = e.target.value.trim(); ANT.limite = 16;
    $('#lista-anteriores').scrollTop = 0;
    listarAnteriores({ forzar: true });
  }, 260);
});

async function listarCarteleras(forzar) {
  const div = $('#lista-carteleras');
  if (carterasCargadas && !forzar) return;
  carterasCargadas = true;
  $('#btn-listar').classList.add('girando');
  $('.caja-betano').classList.add('consultando');
  // Mientras Betano responde, dos filas con la forma de las de verdad.
  div.innerHTML = `<div class="cart esqueleto" aria-hidden="true"><span></span><span></span></div>
    <div class="cart esqueleto" aria-hidden="true"><span></span><span></span></div>
    <p class="sr">consultando Betano…</p>`;
  try {
    const r = await api('/api/betano/carteleras');
    // El modelo solo conoce UFC: las carteleras de otras ligas se dejan fuera,
    // y se dice cuántas para que no parezca que Betano no las tiene.
    const ocultas = r.ocultas ? `<p class="cart-ocultas">${ico('info')}Se ocultaron ${r.ocultas}
      cartelera${r.ocultas === 1 ? '' : 's'} de otras ligas: el modelo solo conoce peleadores de UFC.</p>` : '';
    if (!r.carteleras.length) {
      div.innerHTML = '<p class="lista-vacia">Betano no está listando carteleras de UFC ahora mismo.</p>' + ocultas;
      return;
    }
    div.innerHTML = r.carteleras.map(c => {
      const d = c.dias;
      const cuando = d === null || d === undefined ? ''
        : d === 0 ? 'HOY' : d === 1 ? 'MAÑANA' : d > 0 ? `en ${d} días` : 'ya pasó';
      // Betano abre algunas carteleras con solo un par de peleas montadas.
      // Avisarlo evita la sorpresa de bajar una cartelera "vacía".
      const parcial = c.peleas && c.peleas <= 4
        ? `<span class="cart-parcial">${ico('alerta')}solo ${c.peleas} peleas montadas todavía</span>` : '';
      return `<button class="cart ${d === 0 ? 'hoy' : ''} ${c.titulo ? 'titulo' : ''}" data-q="${esc(c.query || c.name)}"
                      data-fecha="${esc(c.fecha || '')}">
        <span class="cart-cuando">${esc(cuando)}</span>
        <span class="cart-cuerpo">
          <b>${esc(c.estelar || c.name)}</b>
          <span class="cart-meta">${esc(c.name)}${c.peleas ? ` · ${c.peleas} peleas` : ''}${
            c.fecha ? ` · ${esc(fechaCorta(c.fecha))}` : ''}</span>
          ${c.titulo ? '<span class="cart-titulo">Por el título</span>' : ''}${parcial}
        </span>
        <span class="cart-ir"><span class="cart-ir-txt">Predecir</span>${ico('ir')}</span>
      </button>`;
    }).join('') + ocultas;
    entrarFilas($$('#lista-carteleras .cart, #lista-carteleras .cart-ocultas'), { paso: 45 });
    // El rótulo de cuándo se descubre de izquierda a derecha, como el zócalo.
    if (!reducir()) $$('#lista-carteleras .cart-cuando').forEach((c, i) =>
      c.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
        { duration: 360, delay: 120 + Math.min(i, 8) * 45, easing: EASE_OUT, fill: 'backwards' }));

    div.querySelectorAll('.cart').forEach(b => b.onclick = () => conCarga(b, b.querySelector('.cart-ir-txt'), async () => {
      await post('/api/cartelera/betano', { query: b.dataset.q, fecha: b.dataset.fecha || null });
      irA('cartelera');
      await tick();
    }));
  } catch (e) {
    div.innerHTML = `<div class="aviso err"><span class="ai">${ico('alerta')}</span>
      <div>${esc(e.message)}</div></div>`;
    carterasCargadas = false;   // que se pueda reintentar
  } finally {
    $('#btn-listar').classList.remove('girando');
    $('.caja-betano').classList.remove('consultando');
  }
}

$('#btn-listar').onclick = () => listarCarteleras(true);

$('#btn-cargar-betano').onclick = async () => {
  const q = $('#query').value.trim();
  if (!q) { barra('Escribe parte del nombre de la cartelera, o toca "Ver qué carteleras hay".','error'); return; }
  try {
    await post('/api/cartelera/betano', { query:q });
    irA('cartelera'); await tick();
  } catch (e) { barra(e.message,'error'); }
};

// El input de archivo va escondido detrás de un cuadro propio: al elegir uno,
// el cuadro dice cuál quedó elegido.
$('#archivo').onchange = () => {
  const f = $('#archivo').files[0];
  $('#archivo-nombre').textContent = f ? f.name : 'Elegir un archivo .csv';
  $('.elegir-archivo').classList.toggle('con-archivo', !!f);
};

$('#btn-subir').onclick = async () => {
  const f = $('#archivo').files[0];
  if (!f) { barra('Primero elige un archivo .csv','error'); return; }
  const fd = new FormData(); fd.append('archivo', f);
  try {
    await api('/api/cartelera/subir', { method:'POST', body:fd });
    irA('cartelera'); await tick();
  } catch (e) { barra(e.message,'error'); }
};

let CSVS_MOSTRADOS = false;
async function cargarCSVs() {
  try {
    const r = await api('/api/cards');
    // Una cartelera con fecha ya pasada se puede repetir con los datos de ese
    // día. Las que arma "Peleas anteriores" solo se repiten: analizarlas con
    // los datos de hoy sería mirar el resultado.
    const hoy = hoyISO();
    $('#lista-csvs').innerHTML = r.cards.length
      ? r.cards.slice(0,12).map(c => {
          const dia = c.nombre.match(/(\d{4}-\d{2}-\d{2})/)?.[1];
          const pasada = dia && dia < hoy;
          const historica = /^historico_/i.test(c.nombre);
          return `<div class="guardado">
          ${ico('csv')}
          <div class="guardado-que"><b>${esc(c.nombre)}</b>
            <span class="sub">${new Date(c.modificado*1000).toLocaleString('es-CL',
              { day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' })}</span></div>
          <div class="guardado-acciones">
            ${historica && pasada ? '' : `<button class="secundario" data-n="${esc(c.nombre)}">Analizar</button>`}
            ${pasada ? `<button class="secundario repetir" data-n="${esc(c.nombre)}" data-corte="${dia}"
              title="Predecirla con los datos que había antes del ${esc(fechaLarga(dia))}">${ico('repetir')}Repetir</button>` : ''}
          </div></div>`;
        }).join('')
      : '<p class="lista-vacia">Todavía no hay ninguna cartelera guardada.</p>';
    // Entran como lista una sola vez; al volver a la pestaña ya están.
    if (!CSVS_MOSTRADOS) { CSVS_MOSTRADOS = true; entrarFilas($$('#lista-csvs .guardado'), { paso: 30, max: 10 }); }
    $$('#lista-csvs button').forEach(b => b.onclick = () => conCarga(b.closest('.guardado'), null, async () => {
      b.textContent = 'Preparando…';
      await post('/api/cartelera/csv', { nombre:b.dataset.n, corte:b.dataset.corte || null });
      S.abrirPelea = null;
      irA('cartelera'); await tick();
    }).finally(() => cargarCSVs()));
  } catch (e) { $('#lista-csvs').innerHTML = `<div class="aviso err"><span class="ai">${ico('alerta')}</span>
    <div>${esc(e.message)}</div></div>`; }
}

/* =========================== MANTENIMIENTO ============================ */
const NOMBRES_SALUD = {
  modelo_ganador:'modelo de ganador', modelo_metodo:'modelo de método',
  modelo_metodo6:'mercado de método', calibrador_mercado:'calibrador de ganador',
  calibrador_metodo:'calibrador de método', features:'base de datos',
};

// La que hay que correr una vez al mes: la única con el botón principal. Con
// nueve botones rojos iguales no había forma de saber por dónde empezar.
const TAREA_DEL_MES = 'actualizar_bd';

// Los ítems de salud que cambiaron dejan el mismo destello que una cifra EN
// VIVO, y su luz entra apenas desde más chica. La primera vez que se pinta el
// tablero no hay nada con qué comparar y no se marca nada.
function marcarSaludCambiada(previo) {
  if (!previo.size) return;
  $$('#salud .estado[data-k]').forEach(e => {
    const antes = previo.get(e.dataset.k);
    if (antes == null || antes === e.dataset.firma) return;
    e.querySelector(':scope > div')?.classList.add('destello');
    if (!reducir()) e.querySelector('.luz')?.animate(
      [{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: EASE_OUT });
  });
}

async function cargarTareas() {
  const [t,s] = await Promise.all([api('/api/tareas'), api('/api/salud')]);
  const fechaArchivo = (ts) => ts ? new Date(ts * 1000).toLocaleDateString('es-CL',
    { day:'numeric', month:'short', year:'numeric' }) : '';
  // Lo que decía cada ítem antes de repintar: al terminar una tarea se marca
  // solo lo que cambió (pasó de "falta" a "listo", o se rehízo con otra fecha).
  const previo = new Map($$('#salud .estado[data-k]').map(e => [e.dataset.k, e.dataset.firma]));
  $('#salud').innerHTML = `<div class="tablero">${
    Object.entries(NOMBRES_SALUD).map(([k,lbl]) => {
      const hay = s[k]?.existe;
      return `<div class="estado ${hay?'hay':'falta'}" data-k="${esc(k)}" data-firma="${hay ? 1 : 0}:${esc(s[k]?.modificado ?? '')}">
        <span class="luz">${ico(hay ? 'ok' : 'no')}</span>
        <div><b>${lbl}</b><span class="sub">${hay
          ? `listo · ${fechaArchivo(s[k].modificado)}` : 'falta: se crea con una tarea de abajo'}</span></div>
      </div>`;
    }).join('')}</div>
    <div class="ajustes">
      <div><span class="v">${s.ventana_anios}${NBSP_FINO}años</span><span class="k">de historia para entrenar</span></div>
      <div><span class="v">${miles(s.simulaciones)}</span><span class="k">simulaciones por pelea</span></div>
    </div>`;
  marcarSaludCambiada(previo);

  $('#lista-tareas').innerHTML = t.recetas.map(r => `
    <div class="tarea ${r.id === TAREA_DEL_MES ? 'del-mes' : ''}">
      <div class="tarea-txt">
        <h4>${esc(r.nombre)}</h4>
        <p>${esc(r.descripcion)}</p>
        <span class="tiempo">${ico('reloj')}${esc(r.minutos)}${r.pasos>1?` · ${r.pasos} pasos`:''}</span>
      </div>
      <button class="${r.id === TAREA_DEL_MES ? 'primario' : 'secundario'}" data-r="${r.id}" ${t.ocupado?'disabled':''}>${ico('play')}Ejecutar</button>
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
            j.estado==='ok' ? '' : 'error', 8000);
    }
  } catch { S.job = null; }
}

$('#btn-cancelar').onclick = () => S.job && post(`/api/tareas/${S.job}/cancelar`);

/* La Combinada mide lo que la ventana menos la cabecera. Se mide la cabecera
   una vez (y al cambiar el tamaño) y no su estado escondido/visible: si no, la
   combinada crecería y se encogería cada vez que la barra entra o sale. */
function medirCabecera() {
  document.documentElement.style.setProperty('--alto-cab', $('#barra-superior').offsetHeight + 'px');
}
medirCabecera();
addEventListener('resize', medirCabecera);

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
    // Lo que flota bajo la barra (el aviso, el índice de la Guía) sube con ella.
    // Con una clase y translate, no moviendo "top": eso recalcula el layout.
    document.documentElement.classList.toggle('cab-oculta', ocultar);
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
    document.documentElement.classList.remove('cab-oculta');
    ultimo = 0;
  }));
})();

/* =============================== GUÍA ================================= */
// La sección sigue vigente hasta que el título siguiente llega bajo la cabecera.
// Observar solo títulos visibles dejaba una selección vieja en los tramos largos.
(() => {
  const panel = $('#tab-guia');
  const barra = $('#barra-superior');
  const titulos = $$('.guia h2[id]');
  const enlaces = new Map($$('.guia-indice a').map(a => [a.getAttribute('href').slice(1), a]));
  let pendiente = false;

  const actualizar = () => {
    pendiente = false;
    if (!panel.classList.contains('activa')) return;
    // Es el mismo margen de los enlaces: ocultar la barra no cambia de apartado.
    const linea = barra.offsetHeight + 22;
    let actual = titulos[0];
    for (const h of titulos) {
      if (h.getBoundingClientRect().top > linea + 1) break;
      actual = h;
    }
    // El último apartado puede ser demasiado corto para alcanzar esa línea.
    if (window.scrollY > 0 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2)
      actual = titulos[titulos.length - 1];
    enlaces.forEach((a, id) => {
      const activo = id === actual.id;
      a.classList.toggle('activo', activo);
      if (activo) a.setAttribute('aria-current', 'location');
      else a.removeAttribute('aria-current');
    });
  };
  const programar = () => {
    if (pendiente || !panel.classList.contains('activa')) return;
    pendiente = true;
    requestAnimationFrame(actualizar);
  };
  addEventListener('scroll', programar, { passive: true });
  addEventListener('resize', programar);
  barra.addEventListener('transitionend', programar);
  panel.addEventListener('animationend', programar);
  new ResizeObserver(programar).observe(panel);
  $$('.tab').forEach(t => t.addEventListener('click', programar));
  programar();
})();

/* ============================== ARRANQUE ============================== */
tick();
reloj();
cargarInicio();
