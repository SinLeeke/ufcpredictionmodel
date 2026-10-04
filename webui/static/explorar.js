/* Rankings importados y catálogo local. La navegación no consume los scrapers. */
const EXP = { rankings: null, division: 0, q: '', offset: 0, request: 0, cuotas: null };
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
  const url = FOTOS.get(nombre);
  return `<span class="rk-oct" aria-hidden="true"><span class="rk-lona"><span class="retrato rk-foto" data-foto="${esc(nombre)}">${
    url ? `<img src="${url}" alt="" decoding="async">` : SILUETA}</span></span></span>`;
};
const rotuloCampeon = c => c ? `Campeón${c.interino ? ' interino' : ''}` : '';

// En el P4P la categoría viene de las divisiones de esta misma captura. Si
// aparecen dos, se dicen las dos: ni el orden ni un combate antiguo permiten
// adivinar cuál es la actual. No se cruza de nuevo por nombre en el navegador.
function categoriasRanking(p) {
  const divisiones = p.division ? [p.division] : Array.isArray(p.divisiones) ? p.divisiones : [];
  return divisiones.length ? divisiones.map(d => pesoTitulo(d)).join(' / ') : 'División no disponible';
}

function filaRanking(p, d) {
  const p4p = esP4P(d);
  // Estrella: el campeón de una división y el número uno del libra por libra.
  const estrella = p4p ? p.puesto === 1 : p.puesto === 0;
  const oro = !!p.campeon || (!p4p && p.puesto === 0);
  const puesto = !p4p && p.puesto === 0 ? 'C' : esc(p.puesto);
  // En el libra por libra el rótulo dice de qué división es campeón; en la
  // división sobra, porque ya se está mirando esa división.
  let rotulo = '';
  if (p4p && p.campeon) rotulo = rotuloCampeon(p.campeon);
  else if (!p4p && p.puesto === 0) rotulo = rotuloCampeon(p.campeon) || 'Campeón';
  else if (estrella) rotulo = 'Número uno libra por libra';
  const href = p.id ? '#peleador-' + esc(p.id) : '#buscar-' + encodeURIComponent(p.nombre);
  return `<li class="rk-fila${estrella ? ' rk-estrella' : ''}${oro ? ' rk-oro' : ''}">
    <span class="rk-num"${puesto === 'C' ? ' aria-hidden="true"' : ''}>${puesto}</span>
    ${estrella ? fotoCampeon(p.nombre) : ''}
    <div class="rk-txt"><div class="rk-identidad"><a class="rk-nombre" href="${href}"><span class="rk-nombre-txt">${esc(p.nombre)}</span>${banderaRanking(p)}</a>${p4p ? `<span class="rk-categoria">${esc(categoriasRanking(p))}</span>` : ''}</div>${rotulo ? `<small class="rk-rotulo">${rotulo}</small>` : ''}</div>
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
    $('#rankings-fecha').innerHTML = `Captura del ${esc(fechaExplorar(EXP.rankings.fecha))} · <a href="https://www.ufc.com/rankings" target="_blank" rel="noopener">Fuente oficial UFC</a>. Las posiciones corresponden a esa fecha.`;
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

// Cambiar de categoría: el título se descubre de izquierda a derecha como un
// zócalo, las filas suben 8 px una tras otra (28 ms, se corta en la fila 12
// para que la cola no se sienta lenta) y el marco dorado del campeón se asienta
// girando desde 22,5°, como la jaula que se arma. Todo con transform, opacity
// y clip-path. Al volver a pintar, el HTML viejo se reemplaza y sus
// animaciones mueren con él: nada queda a medias. Con teclado no se anima;
// con menos movimiento quedan solo los fundidos.
function entrarRanking(caja) {
  if (porTeclado) return;
  const quieto = reducir();
  // El cuadro final lleva solo las propiedades que se animan: un clip-path
  // de más en el final recortaría lo que se sale de la fila a mitad de camino.
  const FINAL = {opacity: 1, transform: 'none', clipPath: 'inset(0 0 0 0)'};
  const fundido = (el, desde, opts) => el && el.animate(quieto ? [{opacity: 0}, {opacity: 1}]
    : [desde, Object.fromEntries(Object.keys(desde).map(k => [k, FINAL[k]]))], {easing: EASE_OUT, fill: 'backwards', ...opts,
      ...(quieto ? {duration: 150, delay: 0} : {})});
  fundido(caja.querySelector('.rk-cab h2'), {opacity: 0, transform: 'translateX(-6px)'}, {duration: 240});
  fundido(caja.querySelector('.rk-genero'), {opacity: 0, transform: 'translateX(-8px)'}, {duration: 220, delay: 120});
  caja.querySelectorAll('.rk-fila').forEach((li, i) =>
    fundido(li, {opacity: 0, transform: 'translateY(8px)'}, {duration: 240, delay: (quieto ? 0 : Math.min(i, 12) * 28)}));
  const estrella = caja.querySelector('.rk-estrella');
  if (!estrella) return;
  // Cambiar de categoría se repite: el campeón acompaña a las filas sin
  // quedarse animando después de que la persona ya empezó a leerlas.
  fundido(estrella.querySelector('.rk-oct'), {opacity: 0, transform: 'scale(.95)'}, {duration: 240, delay: 40});
  fundido(estrella.querySelector('.rk-foto'), {opacity: 0, transform: 'translateY(4px)'}, {duration: 220, delay: 60});
  fundido(estrella.querySelector('.rk-nombre-txt'), {opacity: 0, transform: 'translateX(-6px)'}, {duration: 220, delay: 40});
}

function abrirCatalogo() {
  $('#catalogo-vista').classList.remove('oculto'); $('#perfil-vista').classList.add('oculto');
}

function filaCatalogo(p) {
  const categoria = p.homonimo ? 'Nombre compartido: historiales sin separar' : p.peso || 'División no disponible';
  const registro = p.peleas == null
    ? `<span class="catalogo-ausente">${p.nacimiento ? 'Nació el ' + esc(fechaExplorar(p.nacimiento)) : 'Nacimiento no disponible'}</span>`
    : `<b>${miles(p.peleas)}</b><span>${p.peleas === 1 ? 'pelea en UFC' : 'peleas en UFC'}</span>`;
  return `<li class="catalogo-fila"><div class="catalogo-identidad">${perfilEnlace(p.nombre,p.id,p.identidad_visual)}<small>${esc(categoria)}</small></div>
    <div class="catalogo-registro">${registro}${p.ultima ? `<small>Última: ${esc(fechaExplorar(p.ultima))}</small>` : ''}</div>
    <span class="catalogo-ir" aria-hidden="true">${ico('ir')}</span></li>`;
}

// Llegar a una ficha o ampliar la lista es ocasional: el fundido con 6 px une
// el cambio de superficie, sin contar cifras desde cero ni mover lo leído.
// La búsqueda escrita y las acciones de teclado son instantáneas.
function entrarExploracion(elementos, { escalonar = true } = {}) {
  if (porTeclado) return;
  const quieto = reducir();
  Array.from(elementos).slice(0, 8).forEach((el, i) => el.animate(quieto
    ? [{opacity:0}, {opacity:1}] : [{opacity:0, transform:'translateY(6px)'}, {opacity:1, transform:'none'}],
    {duration:quieto ? 100 : 220, delay:quieto || !escalonar ? 0 : i * 30, easing:EASE_OUT, fill:'backwards'}));
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
    if (mas) $('#catalogo-lista ul').insertAdjacentHTML('beforeend',rows);
    else $('#catalogo-lista').innerHTML = rows ? `<ul class="catalogo-lista">${rows}</ul>` : '<p>No encontré ese nombre. Prueba con el apellido.</p>';
    EXP.offset += d.peleadores.length;
    EXP.catalogoCargado = true;
    $('#catalogo-total').textContent = `${miles(d.total)} ${d.total === 1 ? 'peleador encontrado' : 'peleadores encontrados'}`;
    $('#catalogo-mas').classList.toggle('oculto', EXP.offset >= d.total);
    const nuevas = Array.from(lista.querySelectorAll('.catalogo-fila')).slice(anteriores);
    entrarExploracion(nuevas);
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
      <p class="perfil-division">${d.peso ? `${esc(d.peso)} <small>· última división registrada</small>` : 'División no disponible'}</p>
      ${bio ? `<dl class="perfil-bio">${bio}</dl>` : ''}${record}
      <p class="nota perfil-procedencia">${d.actualizado ? 'Última pelea: ' + esc(fechaExplorar(d.actualizado)) : 'Sin fecha de última pelea'}${b.fighter_url ? ` · <a href="${esc(b.fighter_url)}" target="_blank" rel="noopener">Ficha fuente UFCStats</a>` : ''}</p></div>
      ${d.homonimo ? '' : `<div class="perfil-retrato">${retrato(d.nombre)}</div>`}</header>
      ${d.homonimo ? `<p class="perfil-aviso">Hay varias fichas llamadas ${esc(d.nombre)}. El historial antiguo usa nombres y no permite separar sus peleas: no se mezcla ni se atribuye aquí.</p>` : ''}
      <p class="nota perfil-fuente">${esc(d.metricas_fuente)}${d.muestra ? ' · ' + miles(d.muestra) + ' peleas en la muestra' : ''}. Una raya significa que no hay datos suficientes.</p>
      <div class="perfil-estadisticas"><section><h2>Golpeo</h2>${listaMetricas(m,[['slpm','Conectados','Significativos por minuto'],['sapm','Recibidos','Significativos por minuto'],['str_acc','Precisión','Golpes conectados / intentados',true],['str_def','Defensa','Golpes del rival evitados',true],['kd_avg','Knockdowns','Por 15 minutos']])}
      <h3>Dónde conecta</h3>${repartoPerfil(d.zonas,{head:'Cabeza',body:'Cuerpo',leg:'Piernas'})}</section>
      <section><h2>Grappling</h2>${listaMetricas(m,[['td_avg','Derribos','Completados por 15 minutos'],['td_acc','Precisión','Derribos completados / intentados',true],['td_def','Defensa','Derribos del rival evitados',true],['sub_avg','Sumisiones','Intentos por 15 minutos'],['ctrl_avg','Control','Minutos de control por 15 minutos']])}
      <h3>Posición del golpeo</h3>${repartoPerfil(d.posiciones,{distance:'Distancia',clinch:'Clinch',ground:'Suelo'})}</section></div>
      <section class="perfil-historial">${historial.length ? `<details class="perfil-desplegable" open><summary><h2>Historial en UFC</h2><span>${historial.length} ${historial.length === 1 ? 'pelea' : 'peleas'}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg></summary><div class="perfil-historial-contenido"><div class="tabla-scroll"><table><thead><tr><th scope="col">Fecha / evento</th><th scope="col">Rival</th><th scope="col">Resultado</th><th scope="col">Método</th><th scope="col">Asalto / tiempo</th></tr></thead><tbody>${historial.map(p=>`<tr><td>${esc(fechaExplorar(p.fecha))}<small>${esc(p.evento)}</small></td><td>${perfilEnlace(p.rival,p.rival_id)}</td><td><span class="perfil-res res-${esc(p.resultado)}">${{V:'Victoria',P:'Derrota',E:'Empate',NC:'Sin resultado','?':'Por confirmar'}[p.resultado] || 'Por confirmar'}</span></td><td>${esc(p.metodo)}</td><td>${esc(p.asalto)} · ${esc(p.tiempo)}</td></tr>`).join('')}</tbody></table></div></div></details>` : '<h2>Historial en UFC</h2><p class="nota">No hay peleas que se puedan atribuir a esta ficha con certeza.</p>'}</section>`;
}

function volverPeleadores() {
  EXP.perfilObs?.disconnect();
  history.replaceState(null,'',location.pathname);
  abrirCatalogo();
  if (!EXP.catalogoCargado) { buscarPeleadores(); return; }
  if (EXP.vuelta?.isConnected) EXP.vuelta.focus({preventScroll:true});
  window.scrollTo({top:EXP.scrollCatalogo || 0, behavior:'auto'});
}

function activarPerfil() {
  const perfil = $('#perfil-vista');
  EXP.perfilObs?.disconnect();
  $('#perfil-volver').onclick = volverPeleadores;
  cargarFotos(perfil);
  entrarExploracion(perfil.querySelectorAll('.perfil-cab, .perfil-fuente'), {escalonar:false});
  const secciones = perfil.querySelectorAll('.perfil-estadisticas > section, .perfil-historial');
  if ('IntersectionObserver' in window && !porTeclado) {
    const observador = new IntersectionObserver(entradas => entradas.forEach(entrada => {
      if (!entrada.isIntersecting) return;
      entrarExploracion([entrada.target], {escalonar:false});
      observador.unobserve(entrada.target);
    }), {threshold:.08});
    EXP.perfilObs = observador;
    secciones.forEach(sec => observador.observe(sec));
  }
  const detalle = perfil.querySelector('.perfil-desplegable');
  detalle?.querySelector('summary').addEventListener('click', e => {
    e.preventDefault();
    desplegarCombate(detalle, !(transicionesCombate.get(detalle)?.abierto ?? detalle.open), {abrir:220, cerrar:160});
  });
  detalle?.addEventListener('toggle', () => {
    if (detalle.open && !detalle.hasAttribute('data-cerrando')) entrarExploracion([detalle.querySelector('.perfil-historial-contenido')], {escalonar:false});
  });
}

async function abrirPerfil(id) {
  if ($('#tab-peleadores').classList.contains('activa') && !$('#catalogo-vista').classList.contains('oculto')) {
    EXP.vuelta = document.activeElement?.closest?.('#catalogo-vista .enlace-peleador');
    EXP.scrollCatalogo = window.scrollY;
  } else if (!location.hash.startsWith('#peleador-') || !$('#perfil-vista h1')) { EXP.vuelta = null; EXP.scrollCatalogo = 0; }
  ++EXP.request; irA('peleadores');
  $('#catalogo-vista').classList.add('oculto'); $('#perfil-vista').classList.remove('oculto');
  $('#perfil-vista').innerHTML = '<p class="nota perfil-cargando" role="status">Cargando ficha local…</p>';
  const seq = ++EXP.request;
  try {
    const d = await api('/api/peleadores/' + encodeURIComponent(id));
    if (seq !== EXP.request) return;
    $('#perfil-vista').innerHTML = vistaPerfil(d);
    activarPerfil();
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
