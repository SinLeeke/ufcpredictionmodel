/* Rankings importados y catálogo local. La navegación no consume los scrapers. */
const EXP = { rankings: null, division: 0, q: '', offset: 0, request: 0, cuotas: null, pedidoHistorial: 0,
  perfil: null, origenPerfil: null };
const pesosEs = {"Men's Pound-for-Pound":'Libra por libra · hombres', "Women's Pound-for-Pound":'Libra por libra · mujeres',
  'Flyweight':'Mosca','Bantamweight':'Gallo','Featherweight':'Pluma','Lightweight':'Ligero',
  'Welterweight':'Wélter','Middleweight':'Medio','Light Heavyweight':'Semipesado','Heavyweight':'Pesado',
  "Women's Strawweight":'Paja femenino',"Women's Flyweight":'Mosca femenino',"Women's Bantamweight":'Gallo femenino',
  "Women's Featherweight":'Pluma femenino', 'Peso mosca':'Mosca', 'Peso gallo':'Gallo',
  'Peso pluma':'Pluma', 'Ligero':'Ligero', 'Peso welter':'Wélter', 'Peso medio':'Medio',
  'Peso semipesado':'Semipesado', 'De peso pesado':'Pesado', 'Peso de la mujer':'Paja femenino',
  'Gallo de las mujeres':'Gallo femenino'};
const fechaExplorar = d => d ? new Date(d.length === 10 ? d + 'T12:00:00' : d).toLocaleDateString('es-CL',
  {day:'numeric',month:'short',year:'numeric'}) : 'sin fecha';
const perfilEnlace = (nombre,id,meta=null,ranking=true) => `<a class="enlace-peleador" href="${id ? '#peleador-' + esc(id) : '#buscar-' + encodeURIComponent(nombre)}">${esc(nombre)}${insigniasIdentidad(meta,ranking)}</a>`;

/* ============================== RANKINGS ============================== */
// El menú se nombra por la clave canónica en inglés y no por `nombre`: el
// nombre viene traducido por la página de UFC en español y trae cosas como
// "De peso pesado" o "Peso de la mujer". Dentro de cada grupo basta el peso:
// el título del grupo (Hombres / Mujeres) ya dice el resto.
const PESO_CORTO = {"Men's Pound-for-Pound":'Libra por libra', "Women's Pound-for-Pound":'Libra por libra',
  Flyweight:'Mosca', Bantamweight:'Gallo', Featherweight:'Pluma', Lightweight:'Ligero', Welterweight:'Wélter',
  Middleweight:'Medio', 'Light Heavyweight':'Semipesado', Heavyweight:'Pesado',
  "Women's Strawweight":'Paja', "Women's Flyweight":'Mosca', "Women's Bantamweight":'Gallo', "Women's Featherweight":'Pluma'};
const esP4P = d => d.p4p ?? /pound-for-pound/i.test(d.clave || d.nombre || '');
const esMujeres = d => d.genero ? d.genero === 'F' : /women|mujer/i.test(d.clave || d.nombre || '');
const pesoCorto = d => PESO_CORTO[d.clave] || PESO_CORTO[d.nombre] || (pesosEs[d.nombre] || d.nombre).replace(/ femenino$/, '');
const pesoTitulo = d => esP4P(d) ? 'Libra por libra' : 'Peso ' + pesoCorto(d).toLowerCase();
// Respaldo si el servidor todavía no manda `grupos`: se arman por género en el
// orden en que llegan las divisiones, que ya es el de UFC (libra por libra primero).
function gruposRanking(r) {
  if (Array.isArray(r.grupos) && r.grupos.length) return r.grupos;
  const idx = r.divisiones.map((d,i) => [d,i]);
  return [['Hombres', idx.filter(([d]) => !esMujeres(d))], ['Mujeres', idx.filter(([d]) => esMujeres(d))]]
    .filter(([,l]) => l.length).map(([titulo,l]) => ({titulo, divisiones: l.map(([,i]) => i)}));
}

// La bandera sale solo de `pais` (contrato de datos). Sin país no se dibuja
// nada: ni hueco ni ícono roto. EN / SC / WA también son dos letras.
const banderaRanking = p => p.pais && /^[A-Z]{2}$/.test(String(p.pais.bandera || ''))
  ? `<img class="rk-bandera" src="/api/bandera/${p.pais.bandera}" width="24" height="18" alt="${esc(p.pais.nombre)}" title="${esc(p.pais.nombre)}" loading="lazy" decoding="async">` : '';
// El marco del campeón es el octágono regular de la jaula (corte de 29,29 %)
// con el mismo metal dorado de la baranda de los títulos. La foto la resuelve
// cargarFotos() de app.js: misma caché, misma silueta mientras llega o si no hay.
const fotoCampeon = nombre => {
  const url = FOTOS.get(claveFoto(nombre, true));
  return `<span class="rk-oct" aria-hidden="true"><span class="rk-brillo"></span><span class="rk-lona"><span class="retrato rk-foto" data-foto="${esc(nombre)}" data-calidad="alta">${
    url ? `<img src="${url}" alt="" decoding="async">` : SILUETA}</span></span></span>`;
};
// «Campeón» o «Campeona» según la división (la del cinturón o la que se mira).
// En el libra por libra el rótulo dice además de qué peso: «Campeón peso
// wélter», «Campeona peso mosca». Dentro de la división sobra, ya se está ahí.
function rotuloCampeon(c, d, conPeso) {
  const mujer = c?.clave ? esMujeres({clave: c.clave}) : esMujeres(d);
  const base = (mujer ? 'Campeona' : 'Campeón') + (c?.interino ? (mujer ? ' interina' : ' interino') : '');
  return conPeso && (c?.clave || c?.division)
    ? `${base} peso ${pesoCorto({clave: c.clave, nombre: c.division}).toLowerCase()}` : base;
}

// Divisiones de una fila. El servidor las manda resueltas (division y
// divisiones); si una versión vieja no las trae, se buscan en esta misma
// captura por identidad exacta (ficha UFC o ID de UFCStats), nunca por nombre:
// sin identidad, «División no disponible» antes que el peso de un homónimo.
function divisionesRanking(p) {
  if (p.division) return [p.division];
  if (Array.isArray(p.divisiones) && (p.divisiones.length || 'division' in p)) return p.divisiones;
  const mismo = r => (p.perfil_ufc && r.perfil_ufc) ? r.perfil_ufc === p.perfil_ufc : !!(p.id && r.id === p.id);
  return (EXP.rankings?.divisiones || []).filter(d => !esP4P(d) && (d.peleadores || []).some(mismo));
}
// En el P4P la categoría viene de las divisiones de esta misma captura. Si
// aparecen dos, se dicen las dos: ni el orden ni un combate antiguo permiten
// adivinar cuál es la actual. La del cinturón ya la dice el rótulo de campeón.
function categoriasRanking(p) {
  const divisiones = divisionesRanking(p);
  if (!divisiones.length) return 'División no disponible';
  const resto = p.campeon?.clave ? divisiones.filter(d => d.clave !== p.campeon.clave) : divisiones;
  return resto.map(d => pesoTitulo(d)).join(' / ');
}

function filaRanking(p, d) {
  const p4p = esP4P(d);
  // Estrella: el campeón de una división y el número uno del libra por libra.
  const estrella = p4p ? p.puesto === 1 : p.puesto === 0;
  const oro = !!p.campeon || (!p4p && p.puesto === 0);
  const puesto = !p4p && p.puesto === 0 ? 'C' : esc(p.puesto);
  let rotulo = '';
  if (p4p && p.campeon) rotulo = rotuloCampeon(p.campeon, d, true);
  else if (!p4p && p.puesto === 0) rotulo = rotuloCampeon(p.campeon, d, false);
  else if (estrella) rotulo = 'Número uno libra por libra';
  const categoria = p4p ? categoriasRanking(p) : '';
  const href = p.id ? '#peleador-' + esc(p.id) : '#buscar-' + encodeURIComponent(p.nombre);
  return `<li class="rk-fila${estrella ? ' rk-estrella' : ''}${oro ? ' rk-oro' : ''}">
    <span class="rk-num"${puesto === 'C' ? ' aria-hidden="true"' : ''}>${puesto}</span>
    ${estrella ? fotoCampeon(p.nombre) : ''}
    <div class="rk-txt"><div class="rk-identidad"><a class="rk-nombre" href="${href}"><span class="rk-nombre-txt">${esc(p.nombre)}</span>${banderaRanking(p)}</a>${categoria ? `<span class="rk-categoria">${esc(categoria)}</span>` : ''}</div>${rotulo ? `<small class="rk-rotulo">${rotulo}</small>` : ''}</div>
    <span class="ranking-ir" aria-hidden="true">${ico('ir')}</span></li>`;
}

// Mientras llega el JSON, filas con la forma de las reales y el brillo de los
// esqueletos de Cargar: se ve que algo pasa, no una caja muerta.
const esqueletoRanking = () => `<div class="rk-cab"><h2>Rankings</h2></div><ol class="ranking-aspirantes rk-cargando" aria-label="Cargando rankings guardados">${
  Array.from({length: 7}, (_, i) => `<li class="rk-fila${i ? '' : ' rk-estrella'}"><span class="rk-num"></span>${i ? '' : '<span class="rk-oct"></span>'}<div class="rk-txt"><i></i></div></li>`).join('')}</ol>`;

async function cargarRankings() {
  if (EXP.rankings) return pintarRanking(false);
  $('#ranking-lista').innerHTML = esqueletoRanking();
  try {
    EXP.rankings = await api('/api/rankings');
    $('#rankings-fecha').innerHTML = `<span class="rk-sello">Captura · ${esc(fechaExplorar(EXP.rankings.fecha))}</span>
      <span>Las posiciones son las de esa fecha. <a href="https://www.ufc.com/rankings" target="_blank" rel="noopener">Fuente oficial UFC</a></span>`;
    pintarMenuRanking();
    pintarRanking(true);
  } catch (e) {
    $('#ranking-lista').innerHTML = '<div class="rk-error"><p>No pude abrir los rankings guardados.</p><button type="button" class="secundario" id="rk-reintentar">Reintentar</button></div>';
    $('#rk-reintentar').onclick = cargarRankings;
  }
}

// El menú se pinta una sola vez. Antes se rehacía en cada clic: se perdía el
// foco del teclado y no había nada que pudiera viajar de un peso a otro.
function pintarMenuRanking() {
  const r = EXP.rankings, nav = $('#ranking-pesos');
  const lista = gruposRanking(r).map((g,gi) => `<div class="rk-grupo" role="group" aria-labelledby="rk-grupo-${gi}">
    <p class="rk-grupo-titulo" id="rk-grupo-${gi}">${esc(g.titulo)}</p>${g.divisiones.filter(i => r.divisiones[i]).map(i =>
      `<button type="button" data-division="${i}">${esc(pesoCorto(r.divisiones[i]))}</button>`).join('')}</div>`).join('');
  // La copia es el mismo menú en tinta invertida, recortada a la división
  // activa. Al cambiar, el recorte viaja (clip-path con transición): el color
  // pasa limpio de un botón al otro, sin dos estados encimados, y una
  // transición CSS se reorienta sola si se hace clic de nuevo a medio camino.
  nav.innerHTML = `<div class="rk-menu">${lista}</div><div class="rk-menu rk-copia" aria-hidden="true" inert>${lista.replace(/ id="rk-grupo-\d+"/g, '')}</div>`;
  const elegibles = gruposRanking(r).flatMap(g => g.divisiones);
  if (!r.divisiones[EXP.division] || !elegibles.includes(EXP.division)) EXP.division = elegibles[0] ?? 0;
  nav.querySelectorAll('.rk-menu:not(.rk-copia) button').forEach(b => b.onclick = () => {
    const i = Number(b.dataset.division);
    if (i === EXP.division) return;
    EXP.division = i;
    pintarRanking(true);
  });
  // Si cambia el tamaño (ventana, fuentes del estilo C, tema) el recorte se
  // recoloca en el acto: eso no es un cambio de categoría y no se anima.
  if (!EXP.menuObs && 'ResizeObserver' in window) {
    EXP.menuObs = new ResizeObserver(() => marcarDivision(false));
    EXP.menuObs.observe(nav);
  }
}

// Recorta la copia al botón activo con la inclinación de 12° de la marca en
// el borde derecho (el estilo C la pone en 0°: el papel no se inclina).
function marcarDivision(animar) {
  const nav = $('#ranking-pesos'), copia = nav.querySelector('.rk-copia');
  nav.querySelectorAll('.rk-menu:not(.rk-copia) button').forEach(b => {
    const activo = Number(b.dataset.division) === EXP.division;
    b.classList.toggle('activo', activo); b.setAttribute('aria-pressed', activo);
  });
  // En angosto cada grupo es una fila con scroll propio: el activo se trae a
  // la vista dentro de su fila (sin mover la página), si no quedaba escondido
  // al volver a la pestaña con Mujeres · Gallo elegido.
  const real = nav.querySelector(`.rk-menu:not(.rk-copia) button[data-division="${EXP.division}"]`);
  const fila = real && real.parentElement;
  if (fila && fila.scrollWidth > fila.clientWidth) {
    const rb = real.getBoundingClientRect(), rf = fila.getBoundingClientRect();
    const dx = rb.left < rf.left ? rb.left - rf.left - 8 : rb.right > rf.right ? rb.right - rf.right + 8 : 0;
    if (dx) fila.scrollBy({left: dx, behavior: animar && !porTeclado && !reducir() ? 'smooth' : 'auto'});
  }
  const b = copia && copia.querySelector(`button[data-division="${EXP.division}"]`);
  if (!b || !b.offsetWidth) return;
  const incl = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--incl')) || 0;
  const x0 = b.offsetLeft, y0 = b.offsetTop, x1 = x0 + b.offsetWidth, y1 = y0 + b.offsetHeight;
  const sesgo = Math.tan(incl * Math.PI / 180) * b.offsetHeight;
  const clip = `polygon(${x0}px ${y0}px, ${x1}px ${y0}px, ${x1 - sesgo}px ${y1}px, ${x0}px ${y1}px)`;
  // Con teclado, con menos movimiento o al recolocar, el recorte salta.
  const quieto = !animar || porTeclado || reducir();
  if (quieto) copia.style.transition = 'none';
  copia.style.clipPath = clip;
  if (quieto) { void copia.offsetWidth; copia.style.transition = ''; }
}

function pintarRanking(animar) {
  const r = EXP.rankings, d = r.divisiones[EXP.division];
  marcarDivision(animar);
  const caja = $('#ranking-lista');
  if (!d) { caja.innerHTML = '<div class="rk-vacio"><h2>Rankings todavía no importados</h2><p>Se mostrarán aquí al cargar una captura oficial.</p></div>'; return; }
  const grupo = gruposRanking(r).find(g => g.divisiones.includes(EXP.division));
  caja.innerHTML = `<div class="rk-cab"><h2>${esc(pesoTitulo(d))}</h2>${grupo ? `<span class="rk-genero">${esc(grupo.titulo)}</span>` : ''}</div>${
    d.peleadores.length ? `<ol class="ranking-aspirantes">${d.peleadores.map(p => filaRanking(p, d)).join('')}</ol>`
      : '<p class="nota">Esta división no trae peleadores en la captura guardada.</p>'}`;
  caja.querySelectorAll('img.rk-bandera').forEach(img => img.addEventListener('error', () => img.remove(), {once: true}));
  cargarFotos(caja);
  if (animar) entrarRanking(caja);
}

// Al cargar y al cambiar de categoría: el título se descubre de lado como un
// zócalo y las filas suben MOV.desplaza px una tras otra (MOV.escalon, cortado
// en la fila MOV.escalonMax para que la cola no se sienta lenta). El #1 (el
// campeón, o el número uno del libra por libra) entra primero y con más
// presencia: el marco del octágono se asienta, el sello del puesto se estampa,
// el nombre se barre de izquierda a derecha y, ya quieto el marco, un brillo
// cruza una sola vez el metal dorado (MOV.brillo), como la luz sobre el
// cinturón. Todo es interrumpible: cambiar de peso corta lo anterior (y el
// HTML viejo se va con sus animaciones), una tecla termina la entrada en el
// acto y pasar el mouse por el campeón apaga el brillo. Con teclado no se
// anima; con menos movimiento quedan solo los fundidos, sin brillo.
function cortarRanking() {
  (EXP.animRanking || []).forEach(a => a.finish());
  EXP.brilloRanking?.cancel();
  EXP.animRanking = []; EXP.brilloRanking = null;
}
addEventListener('keydown', () => { if (EXP.animRanking?.length || EXP.brilloRanking) cortarRanking(); }, true);

function entrarRanking(caja) {
  cortarRanking();
  if (porTeclado) return;
  const quieto = reducir();
  // El cuadro final lleva solo las propiedades que se animan: un clip-path
  // de más en el final recortaría lo que se sale de la fila a mitad de camino.
  const FINAL = {opacity: 1, transform: 'none', clipPath: 'inset(0 0 0 0)'};
  const fundido = (el, desde, opts) => {
    if (!el) return;
    const a = el.animate(quieto ? [{opacity: 0}, {opacity: 1}]
      : [desde, Object.fromEntries(Object.keys(desde).map(k => [k, FINAL[k]]))], {easing: EASE_OUT, fill: 'backwards',
        duration: MOV.entrada, ...opts, ...(quieto ? {duration: 150, delay: 0} : {})});
    EXP.animRanking.push(a);
  };
  fundido(caja.querySelector('.rk-cab h2'), {opacity: 0, clipPath: 'inset(0 100% 0 0)'});
  fundido(caja.querySelector('.rk-genero'), {opacity: 0, transform: 'translateX(-8px)'}, {delay: 120});
  const filas = Array.from(caja.querySelectorAll('.rk-fila'));
  const estrella = caja.querySelector('.rk-estrella');
  // El #1 abre la lista; los demás le siguen corridos un escalón.
  filas.forEach((li, i) => li !== estrella && fundido(li, {opacity: 0, transform: `translateY(${MOV.desplaza}px)`},
    {delay: Math.min(i + (estrella ? 1 : 0), MOV.escalonMax) * MOV.escalon}));
  if (!estrella) return;
  fundido(estrella, {opacity: 0});
  fundido(estrella.querySelector('.rk-oct'), {opacity: 0, transform: 'scale(.94)'}, {delay: 40});
  fundido(estrella.querySelector('.rk-foto'), {opacity: 0, transform: 'translateY(6px)'}, {delay: 90});
  fundido(estrella.querySelector('.rk-num'), {opacity: 0, transform: 'scale(.86)'}, {duration: MOV.press, delay: 60});
  fundido(estrella.querySelector('.rk-nombre-txt'), {opacity: 0, clipPath: 'inset(0 100% 0 0)'}, {delay: 80});
  fundido(estrella.querySelector('.rk-rotulo'), {opacity: 0, transform: 'translateY(4px)'}, {delay: 160});
  const brillo = estrella.querySelector('.rk-brillo');
  if (quieto || !brillo) return;
  EXP.brilloRanking = brillo.animate([{transform: 'translateX(-110%)', opacity: 1}, {transform: 'translateX(110%)', opacity: 1}],
    {duration: MOV.brillo, delay: 40 + MOV.entrada, easing: EASE_IN_OUT});
  EXP.brilloRanking.onfinish = () => { EXP.brilloRanking = null; };
  estrella.addEventListener('pointerenter', () => { EXP.brilloRanking?.cancel(); EXP.brilloRanking = null; }, {once: true});
}

function abrirCatalogo() {
  $('#catalogo-vista').classList.remove('oculto'); $('#perfil-vista').classList.add('oculto');
}

// Cada fila con su foto en el cartel (grafito, o dorado si es campeón vigente).
// Un nombre compartido por dos fichas no lleva foto: mejor la silueta que la
// cara de otro. La foto se pide al acercarse a la pantalla (fotosAlVerse).
function filaCatalogo(p) {
  const categoria = p.homonimo ? 'Nombre compartido: historiales sin separar' : p.peso || 'División no disponible';
  const registro = p.peleas == null
    ? `<span class="catalogo-ausente">${p.nacimiento ? 'Nació el ' + esc(fechaExplorar(p.nacimiento)) : 'Nacimiento no disponible'}</span>`
    : `<b>${miles(p.peleas)}</b><span>${p.peleas === 1 ? 'pelea en UFC' : 'peleas en UFC'}</span>`;
  const oro = !!p.campeon && !p.homonimo;
  const foto = p.homonimo ? `<figure class="retrato">${SILUETA}</figure>` : retrato(p.nombre, '', {alta: true});
  return `<li class="catalogo-fila${oro ? ' catalogo-oro' : ''}"${p.id ? ` data-id="${esc(p.id)}"` : ''}>
    <div class="catalogo-foto foto-cartel${oro ? ' oro' : ''}" aria-hidden="true">${foto}</div>
    <div class="catalogo-identidad">${perfilEnlace(p.nombre,p.id,p.identidad_visual)}${oro ? `<small class="catalogo-cinturon">${esc(rotuloCampeon(p.campeon, null, true))}</small>` : ''}<small>${esc(categoria)}</small></div>
    <div class="catalogo-registro">${registro}${p.ultima ? `<small>Última: ${esc(fechaExplorar(p.ultima))}</small>` : ''}</div>
    <span class="catalogo-ir" aria-hidden="true">${ico('ir')}</span></li>`;
}

// Llegar a una ficha o ampliar la lista es ocasional: el fundido con 6 px une
// el cambio de superficie, sin contar cifras desde cero ni mover lo leído.
// La búsqueda escrita y las acciones de teclado son instantáneas.
function entrarExploracion(elementos, { escalonar = true, desde = 0 } = {}) {
  if (porTeclado) return;
  const quieto = reducir();
  Array.from(elementos).forEach((el, i) => el.animate(quieto
    ? [{opacity:0}, {opacity:1}] : [{opacity:0, transform:`translateY(${MOV.desplaza}px)`}, {opacity:1, transform:'none'}],
    {duration:quieto ? 150 : MOV.entrada, delay:quieto || !escalonar ? 0 : desde + Math.min(i, MOV.escalonMax) * MOV.escalon,
     easing:EASE_OUT, fill:'backwards'}));
}

// Una búsqueda nueva hecha con el puntero (Buscar, o un enlace #buscar-):
// las filas que se van se funden donde estaban (una copia encima, que no
// recibe clics), las que siguen viajan de su lugar viejo al nuevo (FLIP) y
// las nuevas entran escalonadas. Lo escrito tecla a tecla no se anima: es
// teclado, y repetido. Otra búsqueda a medio camino termina la anterior.
function medirCatalogo() {
  const lista = $('#catalogo-lista');
  return new Map(Array.from(lista.querySelectorAll('.catalogo-fila[data-id]'), li => [li.dataset.id, li.getBoundingClientRect()]));
}
function reacomodarCatalogo(antes, fantasmas) {
  const lista = $('#catalogo-lista');
  const quieto = reducir();
  const caja = lista.getBoundingClientRect();
  const capa = document.createElement('div');
  capa.className = 'catalogo-fantasmas';
  capa.setAttribute('aria-hidden', 'true');
  const nuevas = [];
  const ahora = new Set();
  lista.querySelectorAll('.catalogo-fila').forEach(li => {
    const r0 = li.dataset.id && antes.get(li.dataset.id);
    if (li.dataset.id) ahora.add(li.dataset.id);
    if (!r0) { nuevas.push(li); return; }
    const dy = r0.top - li.getBoundingClientRect().top;
    if (Math.abs(dy) < 1 || quieto) return;
    li.animate([{transform: `translateY(${dy}px)`}, {transform: 'none'}], {duration: MOV.viaje, easing: EASE_IN_OUT});
  });
  fantasmas.forEach(([id, nodo, r]) => {
    if (ahora.has(id)) return;
    nodo.style.cssText = `position:absolute;left:${r.left - caja.left}px;top:${r.top - caja.top}px;width:${r.width}px;height:${r.height}px;margin:0`;
    capa.append(nodo);
  });
  if (capa.childElementCount) {
    lista.append(capa);
    const salida = capa.animate([{opacity: 1}, {opacity: 0}], {duration: MOV.salida, easing: EASE_OUT});
    salida.onfinish = salida.oncancel = () => capa.remove();
    EXP.salidaCatalogo = salida;
  }
  // Las nuevas esperan a que las viejas empiecen a irse: se lee primero qué se
  // fue y después qué llegó.
  entrarExploracion(nuevas, {desde: capa.childElementCount ? MOV.salida / 2 : 0});
}

async function buscarPeleadores(mas=false) {
  abrirCatalogo();
  if (!mas) EXP.offset = 0;
  EXP.q = $('#buscar-peleador').value.trim();
  const seq = ++EXP.request;
  $('#catalogo-total').textContent = 'Buscando en la base local…';
  $('#catalogo-lista').setAttribute('aria-busy', 'true');
  $('#catalogo-mas').disabled = true;
  try {
    const d = await api(`/api/peleadores?q=${encodeURIComponent(EXP.q)}&offset=${EXP.offset}&limite=40`);
    if (seq !== EXP.request) return;
    const lista = $('#catalogo-lista');
    const anteriores = mas ? lista.querySelectorAll('.catalogo-fila').length : 0;
    const rows = d.peleadores.map(filaCatalogo).join('');
    // Reacomodar solo si ya había una lista a la vista y la búsqueda no vino
    // del teclado; la primera carga y "Ver más" entran escalonadas.
    EXP.salidaCatalogo?.finish();
    const flip = !mas && !porTeclado && !$('#catalogo-vista').classList.contains('oculto')
      && lista.querySelector('.catalogo-fila') && $('#tab-peleadores').classList.contains('activa');
    const antes = flip ? medirCatalogo() : null;
    const fantasmas = flip ? Array.from(lista.querySelectorAll('.catalogo-fila[data-id]'), li =>
      [li.dataset.id, li.cloneNode(true), li.getBoundingClientRect()]) : [];
    if (mas) $('#catalogo-lista ul').insertAdjacentHTML('beforeend',rows);
    else $('#catalogo-lista').innerHTML = rows ? `<ul class="catalogo-lista">${rows}</ul>` : '<p>No encontré ese nombre. Prueba con el apellido.</p>';
    EXP.offset += d.peleadores.length;
    EXP.catalogoCargado = true;
    $('#catalogo-total').textContent = `${miles(d.total)} ${d.total === 1 ? 'peleador encontrado' : 'peleadores encontrados'}`;
    $('#catalogo-mas').classList.toggle('oculto', EXP.offset >= d.total);
    const nuevas = Array.from(lista.querySelectorAll('.catalogo-fila')).slice(anteriores);
    fotosAlVerse(lista, '.catalogo-fila');
    if (flip) reacomodarCatalogo(antes, fantasmas);
    else entrarExploracion(nuevas);
    if (mas && porTeclado) nuevas[0]?.querySelector('a')?.focus();
  } catch(e) { if (seq === EXP.request) $('#catalogo-total').textContent = 'No pude abrir la base. Pulsa Buscar para reintentar.'; }
  finally { if (seq === EXP.request) { $('#catalogo-mas').disabled = false; $('#catalogo-lista').setAttribute('aria-busy', 'false'); } }
}
$('#form-buscar-peleador').onsubmit = e => { e.preventDefault(); buscarPeleadores(); };
let buscarTimer;
$('#buscar-peleador').oninput = () => { clearTimeout(buscarTimer); buscarTimer = setTimeout(() => buscarPeleadores(),250); };
$('#catalogo-mas').onclick = () => buscarPeleadores(true);

const medidaPerfil = (m,k,porcentaje=false) => m?.[k] == null ? '—' : porcentaje ? pct(m[k],0) : fmt(m[k],2);
function listaMetricas(m,items) {
  return `<dl class="perfil-metricas">${items.map(([key,label,desc,percent])=>`<div><dt>${esc(label)}<small>${esc(desc)}</small></dt><dd>${medidaPerfil(m,key,percent)}</dd></div>`).join('')}</dl>`;
}
function repartoPerfil(items,labels) {
  const valores = Object.entries(items || {}).filter(([,n]) => Number.isFinite(n) && n >= 0);
  const total = valores.reduce((a,[,n])=>a+n,0);
  if (!total) return '<p class="nota">Desglose no disponible.</p>';
  return `<dl class="perfil-reparto">${valores.map(([k,n])=>`<div><dt>${esc(labels[k] || k)}</dt><dd><span>${pct(n/total,0)}</span><span class="perfil-barra" aria-hidden="true"><i style="width:${(n/total*100).toFixed(2)}%"></i></span></dd></div>`).join('')}</dl>`;
}
function vistaPerfil(d) {
  const b = d.bio || {}, r = d.record, m = d.metricas || {}, historial = d.historial || [];
  const datos = [['Edad', d.edad != null ? `${d.edad} años` : null],
    ['Altura', b.height_cm ? `${fmt(b.height_cm,1)} cm` : null],
    ['Alcance', b.reach_cm ? `${fmt(b.reach_cm,1)} cm` : null],
    ['Guardia', {Orthodox:'Ortodoxa',Southpaw:'Zurda',Switch:'Cambiante'}[b.stance] || b.stance]];
  const bio = datos.filter(([,v]) => v).map(([etiqueta,valor]) => `<div><dt>${etiqueta}</dt><dd>${esc(valor)}</dd></div>`).join('');
  const record = r ? `<dl class="perfil-record">${[['V','Victorias'],['P','Derrotas'],['E','Empates'],['NC','Sin resultado']].map(([clave,rotulo]) =>
    `<div><dt>${rotulo}</dt><dd>${miles(r[clave] || 0)}</dd></div>`).join('')}</dl><p class="perfil-record-nota">Solo peleas registradas en UFC; no es el récord profesional completo.${r['?'] ? ` ${miles(r['?'])} por confirmar.` : ''}</p>`
    : '<p class="nota">Récord UFC sin atribución verificable.</p>';
  return `<button id="perfil-volver" class="secundario">${ico('ir', 'perfil-retorno-ico')}Volver a peleadores</button>
      <header class="perfil-cab"><div class="perfil-identidad"><h1>${esc(d.nombre)}${insigniasIdentidad(d.identidad_visual)}</h1>
      ${d.campeon ? `<p class="perfil-cinturon">${esc(rotuloCampeon(d.campeon, null, true))}</p>` : ''}
      <p class="perfil-division">${d.peso ? `${esc(d.peso)} <small>· última división registrada</small>` : 'División no disponible'}</p>
      ${bio ? `<dl class="perfil-bio">${bio}</dl>` : ''}${record}
      <p class="nota perfil-procedencia">${d.actualizado ? 'Última pelea: ' + esc(fechaExplorar(d.actualizado)) : 'Sin fecha de última pelea'}${b.fighter_url ? ` · <a href="${esc(b.fighter_url)}" target="_blank" rel="noopener">Ficha fuente UFCStats</a>` : ''}</p></div>
      ${d.homonimo ? '' : `<div class="perfil-retrato foto-cartel${d.campeon ? ' oro' : ''}">${retrato(d.nombre, '', {alta: true})}</div>`}</header>
      ${d.homonimo ? `<p class="perfil-aviso">Hay varias fichas llamadas ${esc(d.nombre)}. El historial antiguo usa nombres y no permite separar sus peleas: no se mezcla ni se atribuye aquí.</p>` : ''}
      <p class="nota perfil-fuente">${esc(d.metricas_fuente)}${d.muestra ? ' · ' + miles(d.muestra) + ' peleas en la muestra' : ''}. Una raya significa que no hay datos suficientes.</p>
      <div class="perfil-estadisticas"><section><h2>Golpeo</h2>${listaMetricas(m,[['slpm','Conectados','Significativos por minuto'],['sapm','Recibidos','Significativos por minuto'],['str_acc','Precisión','Golpes conectados / intentados',true],['str_def','Defensa','Golpes del rival evitados',true],['kd_avg','Knockdowns','Por 15 minutos']])}
      <h3>Dónde conecta</h3>${repartoPerfil(d.zonas,{head:'Cabeza',body:'Cuerpo',leg:'Piernas'})}</section>
      <section><h2>Grappling</h2>${listaMetricas(m,[['td_avg','Derribos','Completados por 15 minutos'],['td_acc','Precisión','Derribos completados / intentados',true],['td_def','Defensa','Derribos del rival evitados',true],['sub_avg','Sumisiones','Intentos por 15 minutos'],['ctrl_avg','Control','Minutos de control por 15 minutos']])}
      <h3>Posición del golpeo</h3>${repartoPerfil(d.posiciones,{distance:'Distancia',clinch:'Clinch',ground:'Suelo'})}</section></div>
      <section class="perfil-historial">${historial.length ? `<details class="perfil-desplegable" open><summary><h2>Historial en UFC</h2><span>${historial.length} ${historial.length === 1 ? 'pelea' : 'peleas'}<small>Elige una para verla como se veía ese día</small></span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg></summary><div class="perfil-historial-contenido"><div class="tabla-scroll"><table><thead><tr><th scope="col">Fecha / evento</th><th scope="col">Rival</th><th scope="col">Resultado</th><th scope="col">Método</th><th scope="col">Asalto / tiempo</th></tr></thead><tbody>${historial.map((p,i)=>`<tr class="hist-fila"><td><button type="button" class="hist-abrir" data-hist="${i}" aria-label="${esc(`Ver ${p.evento} frente a ${p.rival} como se veía ese día`)}">${esc(fechaExplorar(p.fecha))}<small>${esc(p.evento)}</small></button></td><td>${perfilEnlace(p.rival,p.rival_id)}</td><td><span class="perfil-res res-${esc(p.resultado)}">${{V:'Victoria',P:'Derrota',E:'Empate',NC:'Sin resultado','?':'Por confirmar'}[p.resultado] || 'Por confirmar'}</span></td><td>${esc(p.metodo)}</td><td>${esc(p.asalto)} · ${esc(p.tiempo)}</td></tr>`).join('')}</tbody></table></div></div></details>` : '<h2>Historial en UFC</h2><p class="nota">No hay peleas que se puedan atribuir a esta ficha con certeza.</p>'}</section>`;
}

// Al volver, el listado reaparece donde estaba: mismo scroll y el foco en el
// peleador que se había abierto. Un fundido corto (sin desplazar nada) une
// el cambio; con teclado, en el acto.
function volverPeleadores() {
  EXP.perfilObs?.disconnect();
  history.replaceState(null,'',location.pathname);
  abrirCatalogo();
  if (!EXP.catalogoCargado) { buscarPeleadores(); return; }
  if (EXP.vuelta?.isConnected) EXP.vuelta.focus({preventScroll:true});
  window.scrollTo({top:EXP.scrollCatalogo || 0, behavior:'auto'});
  if (!porTeclado) $('#catalogo-vista').animate([{opacity: 0}, {opacity: 1}], {duration: 150, easing: EASE_OUT});
}


// La ficha llega de una vez (una petición), pero no aparece de golpe: el panel
// sube MOV.desplaza px, el contorno del octágono del cartel se asienta y la
// foto entra un instante después desde abajo, y las cifras del récord corren
// hasta su valor con el mismo contar() de la cartelera. Si se llegó desde el
// listado (EXP.origenPerfil), la foto no entra: viaja desde donde estaba
// (FLIP, MOV.viaje con --ease-in-out). Las estadísticas cuentan al entrar en
// pantalla y las filas del historial bajan una tras otra al abrirlo. Con
// teclado nada se anima; con menos movimiento quedan los fundidos, sin conteo.
function activarPerfil(origen = null) {
  const perfil = $('#perfil-vista');
  EXP.perfilObs?.disconnect();
  $('#perfil-volver').onclick = volverPeleadores;
  cargarFotos(perfil);
  perfil.querySelectorAll('.hist-abrir').forEach(b => b.onclick = () => {
    const h = EXP.perfil?.historial?.[Number(b.dataset.hist)];
    if (h) abrirPeleaHistorial(EXP.perfil, h);
  });
  const detalle = perfil.querySelector('.perfil-desplegable');
  detalle?.querySelector('summary').addEventListener('click', e => {
    e.preventDefault();
    desplegarCombate(detalle, !(transicionesCombate.get(detalle)?.abierto ?? detalle.open), {abrir:220, cerrar:160});
  });
  detalle?.addEventListener('toggle', () => {
    if (detalle.open && !detalle.hasAttribute('data-cerrando')) entrarFilasHistorial(detalle);
  });
  if (porTeclado) return;
  const quieto = reducir();
  const entra = (el, desde, opts = {}) => el?.animate(quieto ? [{opacity: 0}, {opacity: 1}] : [desde, {opacity: 1, transform: 'none'}],
    {duration: quieto ? 150 : MOV.entrada, easing: EASE_OUT, fill: 'backwards', ...opts, ...(quieto ? {delay: 0} : {})});
  entra(perfil.querySelector('.perfil-cab'), {opacity: 0, transform: `translateY(${MOV.desplaza}px)`});
  entra(perfil.querySelector('.perfil-fuente'), {opacity: 0}, {delay: 80});
  const cartel = perfil.querySelector('.perfil-retrato');
  if (cartel && !(origen && volarFoto(cartel, origen))) {
    if (!quieto) cartel.animate([{transform: 'scale(.96)'}, {transform: 'none'}],
      {duration: MOV.entrada, easing: EASE_OUT, pseudoElement: '::before', fill: 'backwards'});
    entra(cartel.querySelector('.retrato'), {opacity: 0, transform: 'translateY(10px)'}, {delay: 60});
  }
  if (!quieto) perfil.querySelectorAll('.perfil-record dd').forEach((dd, i) => contar(dd, 120 + i * MOV.escalon, MOV.conteo));
  const secciones = perfil.querySelectorAll('.perfil-estadisticas > section, .perfil-historial');
  if (!('IntersectionObserver' in window)) return;
  const observador = new IntersectionObserver(entradas => entradas.forEach(entrada => {
    if (!entrada.isIntersecting) return;
    observador.unobserve(entrada.target);
    if (porTeclado) return;
    entra(entrada.target, {opacity: 0, transform: `translateY(${MOV.desplaza}px)`});
    if (!reducir()) entrada.target.querySelectorAll('.perfil-metricas dd').forEach((dd, i) =>
      contar(dd, 80 + Math.min(i, MOV.escalonMax) * MOV.escalon, MOV.conteo));
    if (entrada.target.classList.contains('perfil-historial') && detalle?.open) entrarFilasHistorial(detalle);
  }), {threshold: .08});
  EXP.perfilObs = observador;
  secciones.forEach(sec => observador.observe(sec));
}

// Las filas del historial bajan una tras otra, cortadas en la fila 12: la
// tabla se lee de arriba abajo, no como un bloque que aparece entero.
function entrarFilasHistorial(detalle) {
  if (porTeclado) return;
  const quieto = reducir();
  detalle.querySelectorAll('tbody tr').forEach((tr, i) => tr.animate(
    quieto ? [{opacity: 0}, {opacity: 1}] : [{opacity: 0, transform: `translateY(${MOV.desplaza}px)`}, {opacity: 1, transform: 'none'}],
    {duration: quieto ? 150 : MOV.entrada, delay: quieto ? 0 : Math.min(i, MOV.escalonMax) * MOV.escalon, easing: EASE_OUT, fill: 'backwards'}));
}

// FLIP: la foto parte del rectángulo que ocupaba en el listado y llega a su
// lugar en el cartel del perfil. Escala uniforme (la del ancho) y centros
// alineados: así no se deforma aunque la caja chica y la grande tengan otra
// proporción. Devuelve false si no corresponde (otro peleador, sin medidas).
function volarFoto(cartel, origen) {
  const r0 = origen.rect, r1 = cartel.getBoundingClientRect();
  if (!r0?.width || !r1.width || porTeclado) return false;
  if (reducir()) { cartel.animate([{opacity: 0}, {opacity: 1}], {duration: 150, easing: EASE_OUT}); return true; }
  const escala = r0.width / r1.width;
  const dx = (r0.left + r0.width / 2) - (r1.left + r1.width / 2);
  const dy = (r0.top + r0.height / 2) - (r1.top + r1.height / 2);
  cartel.style.zIndex = '5';
  const viaje = cartel.animate([{transform: `translate(${dx}px, ${dy}px) scale(${escala})`}, {transform: 'none'}],
    {duration: MOV.viaje, easing: EASE_IN_OUT});
  const fin = () => { cartel.style.zIndex = ''; };
  viaje.onfinish = fin; viaje.oncancel = fin;
  return true;
}

/* ===================== MODAL: UNA PELEA DEL HISTORIAL ===================== */
// Al elegir una fila del historial se abre la pelea como se veía ESE día
// (GET /api/peleadores/{id}/pelea, webui/historial.py): arriba el octágono de
// la cartelera (escenaJaula, dorado si fue por el título y con las esquinas
// roja y azul si no), abajo las estadísticas con el mismo componente del
// análisis (analisisContenido) y, después y aparte, cómo terminó. El orden de
// las esquinas lo decide el servidor sin mirar el resultado. Mientras está
// abierto, <html> lleva data-historial-abierto (la cabecera esconde Combinada).
const cuerpoHistorial = () => $('#modal-cuerpo .hist-cuerpo');

function cabHistorial(h, perfil) {
  return `<div class="hist"><header class="hist-cab">
    <p class="hist-evento"><span class="hist-sello">${esc(h.evento)}</span><span>${esc(fechaExplorar(h.fecha))}</span></p>
    <h2>${esc(perfil.nombre)} <small>vs</small> ${esc(h.rival)}</h2>
    <p class="hist-nota">Como se veía antes de pelearse: récord, últimas cinco y estadísticas con solo lo que había hasta el día anterior.</p>
  </header><div class="hist-cuerpo" aria-busy="true"><div class="hist-cargando" role="status">
    <span class="hist-oct-esqueleto" aria-hidden="true"></span><p>Reconstruyendo la pelea con los datos de ese día…</p></div></div></div>`;
}

// El resultado real, separado de todo lo anterior. Con modelo de ese día va
// el pie de la repetición (acertó o falló, y el método); sin modelo no hay
// pronóstico contra qué comparar y se dice solo cómo terminó.
function resultadoHistorialPelea(p, r, conModelo) {
  if (!r) return `<p class="hist-sin-res">La base local todavía no tiene el resultado de esta pelea.</p>`;
  if (conModelo) return resultadoReal({...p, resultado: r});
  const t = textoResultado(r);
  return `<div class="resultado-real hist-res" data-acierto="nd" role="group" aria-label="Resultado real">
    <span class="rr-que"><b${r.lado ? ` data-lado="${r.lado}"` : ''}>${esc(t.titulo)}</b>${t.detalle ? `<span>${esc(t.detalle)}</span>` : ''}</span></div>`;
}

function vistaHistorialPelea(d) {
  const p = d.pelea;
  if (!p) return `<div class="hist-aviso">${ico('alerta')}<p>${esc(d.corte?.motivo || 'No se pudo reconstruir esta pelea.')}</p></div>
    <section class="hist-seccion hist-final"><h3>Cómo terminó</h3>${resultadoHistorialPelea({}, d.resultado, false)}</section>`;
  const conModelo = Number.isFinite(p.p_a) && Number.isFinite(p.p_b);
  const corte = d.corte || {};
  const titulo = p.es_titulo === true;
  return `<article class="estelar hist-oct${titulo ? ' estelar-titulo' : ''}" data-pelea="${esc(p.id)}" aria-label="${esc(p.a)} frente a ${esc(p.b)}${titulo ? ', por el título' : ''}">
      ${titulo ? '<p class="hist-cinturon">Por el título</p>' : ''}${escenaJaula(p, {cifras: conModelo, resultado: false})}</article>
    <section class="hist-seccion"><h3>Estadísticas de ese día</h3>
      <p class="hist-corte">Datos hasta el ${esc(fechaExplorar(corte.fecha))}${conModelo
        ? ` · pronóstico de un modelo ${corte.modelo === 'reentrenado' ? 'entrenado solo con las peleas anteriores' : 'que ya había terminado de entrenar antes'}${p.mercado ? ', mezclado con las cuotas de cierre' : ''}.`
        : '.'}</p>
      ${corte.motivo ? `<p class="hist-aviso-modelo">${esc(corte.motivo)}</p>` : ''}
      <div class="analisis-pelea hist-analisis">${analisisContenido(p)}</div></section>
    <section class="hist-seccion hist-final"><h3>Cómo terminó</h3>${resultadoHistorialPelea(p, d.resultado, conModelo)}</section>`;
}

async function abrirPeleaHistorial(perfil, h) {
  const pedido = ++EXP.pedidoHistorial;
  modal(cabHistorial(h, perfil), {clase: 'modal-historial', alCerrar: () => {
    delete raizDoc.dataset.historialAbierto;
    EXP.pedidoHistorial++;                 // una respuesta tardía ya no pinta nada
  }});
  raizDoc.dataset.historialAbierto = '';
  try {
    const d = await api(`/api/peleadores/${encodeURIComponent(perfil.id)}/pelea?fecha=${encodeURIComponent(String(h.fecha).slice(0, 10))}&rival=${encodeURIComponent(h.rival)}`);
    if (pedido !== EXP.pedidoHistorial || !cuerpoHistorial()) return;
    const cuerpo = cuerpoHistorial();
    cuerpo.innerHTML = vistaHistorialPelea(d);
    cuerpo.setAttribute('aria-busy', 'false');
    // Las últimas cinco de la lona abren otro modal en la cartelera; acá ya
    // estamos en uno, así que quedan como lectura.
    cuerpo.querySelectorAll('.historial-resumen').forEach(b => {
      const s = document.createElement('span');
      s.className = b.className; s.innerHTML = b.innerHTML; s.title = b.title;
      b.replaceWith(s);
    });
    cargarFotos(cuerpo);
    entrarHistorialPelea(cuerpo);
  } catch (e) {
    if (pedido !== EXP.pedidoHistorial || !cuerpoHistorial()) return;
    cuerpoHistorial().setAttribute('aria-busy', 'false');
    cuerpoHistorial().innerHTML = `<div class="hist-aviso">${ico('alerta')}<p>${esc(e.message || 'No pude abrir esta pelea.')}</p></div>`;
  }
}

// La pelea llega como la estelar al abrirse: la jaula se arma (entradaJaula,
// la misma de la cartelera), las barras del análisis se llenan desde su
// esquina y el resultado aparece al final, ya separado. Con teclado, quieto;
// con menos movimiento, solo un fundido.
function entrarHistorialPelea(cuerpo) {
  if (porTeclado) return;
  if (reducir()) { cuerpo.animate([{opacity: 0}, {opacity: 1}], {duration: 150, easing: EASE_OUT}); return; }
  const art = cuerpo.querySelector('.hist-oct');
  if (art) entradaJaula(art);
  cuerpo.querySelectorAll('.hist-seccion').forEach((s, i) => s.animate(
    [{opacity: 0, transform: `translateY(${MOV.desplaza}px)`}, {opacity: 1, transform: 'none'}],
    {duration: MOV.entrada, delay: 360 + i * 120, easing: EASE_OUT, fill: 'backwards'}));
  cuerpo.querySelectorAll('.analisis-barra span').forEach((b, i) => llenarDesde(b, 'left', 480 + Math.min(i, 8) * MOV.escalon));
}

// Clic en un peleador del listado: se anota de dónde sale su foto para que
// viaje al perfil (EXP.origenPerfil = {id, rect, foto, oro}) y a quién
// devolverle el foco al volver. Se mide antes de que cambie nada.
$('#catalogo-lista').addEventListener('click', e => {
  const enlace = e.target.closest('.catalogo-fila .enlace-peleador');
  const fila = enlace?.closest('.catalogo-fila');
  if (!fila?.dataset.id) return;
  const foto = fila.querySelector('.catalogo-foto');
  EXP.vuelta = enlace;
  EXP.origenPerfil = {id: fila.dataset.id, rect: foto?.getBoundingClientRect() || null,
    foto: foto?.querySelector('img')?.getAttribute('src') || null, oro: fila.classList.contains('catalogo-oro')};
}, true);

async function abrirPerfil(id) {
  const desdeListado = $('#tab-peleadores').classList.contains('activa') && !$('#catalogo-vista').classList.contains('oculto');
  if (desdeListado) {
    if (!EXP.vuelta?.isConnected) EXP.vuelta = document.activeElement?.closest?.('#catalogo-vista .enlace-peleador');
    EXP.scrollCatalogo = window.scrollY;
  } else if (!location.hash.startsWith('#peleador-') || !$('#perfil-vista h1')) { EXP.vuelta = null; EXP.scrollCatalogo = 0; }
  const seq = ++EXP.request;
  const pedido = api('/api/peleadores/' + encodeURIComponent(id));
  pedido.catch(() => {});
  // Desde el listado ya se está en la pestaña: el listado se funde (MOV.salida)
  // mientras llega la ficha, y recién ahí sube la página. Con teclado o con un
  // enlace de otra parte, el cambio es inmediato como antes.
  if (desdeListado && !porTeclado) {
    await $('#catalogo-vista').animate([{opacity: 1}, {opacity: 0}], {duration: MOV.salida, easing: EASE_OUT}).finished.catch(() => {});
    if (seq !== EXP.request) return;
    window.scrollTo({top: 0});
  } else if (!desdeListado) irA('peleadores');
  else window.scrollTo({top: 0});
  $('#catalogo-vista').classList.add('oculto'); $('#perfil-vista').classList.remove('oculto');
  $('#perfil-vista').innerHTML = '<p class="nota perfil-cargando" role="status">Cargando ficha local…</p>';
  try {
    const d = await pedido;
    if (seq !== EXP.request) return;
    EXP.perfil = d;
    // El origen del viaje solo vale para este peleador y una sola vez.
    const origen = EXP.origenPerfil?.id === id ? EXP.origenPerfil : null;
    EXP.origenPerfil = null;
    $('#perfil-vista').innerHTML = vistaPerfil(d);
    activarPerfil(origen);
    $('#perfil-vista h1').tabIndex = -1; $('#perfil-vista h1').focus({preventScroll:true});
  } catch(e) { if (seq === EXP.request) { $('#perfil-vista').innerHTML = '<p>No encontré esa ficha.</p><button id="perfil-volver" class="secundario">Volver al buscador</button>'; $('#perfil-volver').onclick = volverPeleadores; } }
}
function rutaExplorar() {
  const h = location.hash;
  if (/^#peleador-[a-f0-9]{16}$/.test(h)) abrirPerfil(h.slice(10));
  else if (h.startsWith('#buscar-')) {
    ++EXP.request; irA('peleadores'); $('#buscar-peleador').value = decodeURIComponent(h.slice(8)); buscarPeleadores();
  }
}
window.addEventListener('hashchange',rutaExplorar);
$$('.tab').forEach(b=>b.addEventListener('click',()=>{
  if (b.dataset.tab === 'rankings') cargarRankings();
  if (b.dataset.tab === 'peleadores' && !location.hash.startsWith('#peleador-')) buscarPeleadores();
}));

function pintarCuotas(d) {
  EXP.cuotas = d;
  const completos = d.carteleras || [];
  const lista = completos.length ? completos.map(e=>({...e,oficial:true})) : d.eventos;
  $('#cuotas-historial').classList.add('oculto'); $('#cuotas-lista').classList.remove('oculto');
  $('#cuotas-estado').textContent = `${d.desactualizado ? 'Sin conexión: última captura disponible' : 'Captura guardada'} · ${new Date(d.capturado).toLocaleString('es-CL')} · ${d.cache ? 'reutilizada sin consultar la fuente' : 'consulta completada'}.${d.cartelera_conservada === false ? ' Esta captura solo conserva precios; no tiene la cartelera anunciada de ese día.' : ''}`;
  $('#cuotas-lista').innerHTML = lista.length ? `<label for="evento-cuotas">Cartelera</label><select id="evento-cuotas">${lista.map((e,i)=>`<option value="${i}">${esc(e.titulo)} · ${esc(fechaExplorar(e.fecha))}</option>`).join('')}</select><div id="cuotas-detalle"></div>` : '<p>No hay eventos con cuotas disponibles en esta captura.</p>';
  const detalle = i => {
    const e=lista[i];
    const books = new Map([...new Map(e.peleas.flatMap(p=>Object.entries(p.casas).map(([key,c])=>[key,c.casa])))].sort(([a,na],[b,nb])=>e.peleas.filter(p=>p.casas[b]).length-e.peleas.filter(p=>p.casas[a]).length || na.localeCompare(nb)));
    $('#cuotas-detalle').innerHTML = `<section class="cuotas-evento"><h3>${esc(e.titulo)}</h3><p class="nota">${esc(fechaExplorar(e.fecha))} · ${e.peleas.length} peleas ${e.oficial ? 'anunciadas' : 'con cuotas'}</p>
      <label for="casa-cuotas-${i}">Casa para esta cartelera</label><select id="casa-cuotas-${i}">${[...books].map(([k,n])=>`<option value="${esc(k)}">${esc(n)}</option>`).join('')}<option value="">Solo modelo, sin cuotas</option></select>
      <ul>${e.peleas.map(p=>`<li>${esc(p.a)} <span>vs</span> ${esc(p.b)}</li>`).join('')}</ul>
      <button class="primario" data-predecir-cuotas="${i}">${e.oficial ? 'Predecir cartelera completa' : 'Predecir con estas cuotas'}</button><p class="nota" id="cobertura-cuotas-${i}"></p></section>`;
    cobertura(e,i);
    $(`#casa-cuotas-${i}`).onchange=()=>cobertura(e,i);
    $('#cuotas-detalle button').onclick=()=>predecir(i);
  };
  const cobertura = (e,i) => { const b=$(`#casa-cuotas-${i}`).value; const n=e.peleas.filter(p=>p.casas[b]).length;
    $('#cuotas-detalle ul').innerHTML=e.peleas.map(p=>`<li><div>${esc(p.a)} <span>vs</span> ${esc(p.b)}</div><small>${p.casas[b] ? `${fmt(p.casas[b].a,2)} / ${fmt(p.casas[b].b,2)}` : 'Sin cuota'}</small></li>`).join('');
    $(`#cobertura-cuotas-${i}`).textContent=e.oficial ? `Se muestran las ${e.peleas.length} peleas. ${n} con cuota; ${e.peleas.length-n} solo con el modelo.` : `Esta casa cubre ${n} de ${e.peleas.length} peleas.`; };
  const predecir = async i=>{
    const b=$('#cuotas-detalle button'); b.disabled=true;
    try { await post('/api/cartelera/cuotas',{snapshot:d.snapshot,evento:lista[i].id,casa:$(`#casa-cuotas-${i}`).value,oficial:!!lista[i].oficial}); irA('cartelera'); }
    catch(e) { $('#cuotas-estado').textContent=e.message; } finally { b.disabled=false; }
  };
  if (lista.length) { $('#evento-cuotas').onchange=e=>detalle(Number(e.target.value)); detalle(0); }
}
$('#btn-consultar-cuotas').onclick = async()=>{
  const b=$('#btn-consultar-cuotas'); b.disabled=true; $('#cuotas-estado').textContent='Consultando la fuente…';
  try {
    if ($('#fuente-cuotas').value === 'odds-api') {
      const c=await api('/api/cuotas/configuracion');
      if (!c.odds_api_configurada) { $('#cuotas-estado').textContent='The Odds API requiere una cuenta gratuita. Configura la clave en el servidor para usarla; BestFightOdds funciona sin cuenta.'; return; }
    }
    pintarCuotas(await api('/api/cuotas?proveedor='+encodeURIComponent($('#fuente-cuotas').value)));
  } catch(e) { $('#cuotas-estado').textContent=e.message; } finally { b.disabled=false; }
};
$('#btn-historial-cuotas').onclick = async()=>{
  const b=$('#btn-historial-cuotas'); b.disabled=true;
  try {
    const d=await api('/api/cuotas/historial');
    $('#cuotas-lista').classList.add('oculto'); $('#cuotas-historial').classList.remove('oculto');
    $('#cuotas-historial').innerHTML='<h3>Capturas conservadas</h3><p class="nota">Se abren desde SQLite. Al predecir una captura de otro día, se respeta esa fecha para las estadísticas.</p>' + (d.capturas.length ? '<ul>'+d.capturas.map(c=>`<li><button class="secundario" data-captura="${esc(c.snapshot)}">${esc({bfo:'BestFightOdds','odds-api':'The Odds API',betano:'Betano'}[c.proveedor] || c.proveedor)} · ${esc(new Date(c.capturado).toLocaleString('es-CL'))}${c.fecha_fuente ? ' · histórica' : ''}</button></li>`).join('')+'</ul>' : '<p>Todavía no hay capturas guardadas.</p>');
    $$('[data-captura]').forEach(btn=>btn.onclick=async()=>{
      btn.disabled=true;
      try { pintarCuotas(await api('/api/cuotas/capturas/'+encodeURIComponent(btn.dataset.captura))); }
      catch(e) { $('#cuotas-estado').textContent=e.message; } finally { btn.disabled=false; }
    });
  } catch(e) { $('#cuotas-estado').textContent=e.message; } finally { b.disabled=false; }
};
rutaExplorar();
