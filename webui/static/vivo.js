/* Mercado en vivo: una lectura de nuestra caché, nunca de las casas.
   Las series conservan las cuotas recibidas: una línea escalonada muestra
   el valor que rigió hasta el siguiente cambio, sin inventar puntos. */
(() => {
  'use strict';

  const INTERVALO = 12000;
  const escapar = texto => String(texto ?? '').replace(/[&<>"']/g, letra =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[letra]));
  const numero = (valor, decimales = 0) => Number(valor).toLocaleString('es-CL',
    {minimumFractionDigits:decimales, maximumFractionDigits:decimales});
  const valido = valor => valor != null && Number.isFinite(Number(valor));
  const americana = valor => valido(valor)
    ? `${Number(valor) < 0 ? '−' : '+'}${numero(Math.abs(Number(valor)))}` : '—';
  const porcentaje = valor => valido(valor) ? `${numero(Number(valor) * 100, 1)} %` : 'Sin dato';
  const probAmericana = prob => {
    if (!valido(prob) || Number(prob) <= 0 || Number(prob) >= 1) return null;
    const p = Number(prob);
    return Math.round(p >= .5 ? -100 * p / (1 - p) : 100 * (1 - p) / p);
  };
  const instante = fecha => typeof fecha === 'string' ? Date.parse(fecha) : NaN;
  const hora = fecha => Number.isFinite(instante(fecha))
    ? new Date(fecha).toLocaleTimeString('es-CL', {hour:'2-digit', minute:'2-digit', hour12:false}) : 'Sin hora';
  const fechaHora = fecha => Number.isFinite(instante(fecha))
    ? new Date(fecha).toLocaleString('es-CL', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false}) : 'Sin hora';
  const claveSerie = serie => JSON.stringify([serie.tipo || 'casa', serie.casa || serie.etiqueta || '']);

  function crearEstado() {
    return {visible:false, paquete:null, pelea_id:null, evento_clave:null,
      series:new Map(), ultimo:null, error:null, ultimo_ok:null};
  }

  function unirPuntos(anteriores, nuevos) {
    const porInstante = new Map();
    for (const punto of [...anteriores, ...nuevos]) {
      const t = instante(punto.t);
      // Un null significa desconocido; convertirlo a cero dibujaría una caída ficticia.
      if (Number.isFinite(t) && valido(punto.pa) && Number(punto.pa) >= 0 && Number(punto.pa) <= 1) {
        porInstante.set(t, {...punto});
      }
    }
    return [...porInstante.entries()].sort((a, b) => a[0] - b[0]).map(([, punto]) => punto);
  }

  function recibirPaquete(anterior, paquete) {
    if (!paquete || typeof paquete.activo !== 'boolean') throw new Error('Respuesta de mercado incompleta');
    if (!paquete.activo) return crearEstado();
    const actual = paquete.actual;
    const eventoClave = JSON.stringify([paquete.evento?.id || paquete.evento?.nombre || '', !!paquete.simulado]);
    const mismaPelea = anterior.pelea_id === actual?.pelea_id && anterior.evento_clave === eventoClave;
    const series = actual?.incremental && mismaPelea ? new Map(anterior.series) : new Map();
    for (const serie of actual?.series || []) {
      const clave = claveSerie(serie);
      const previa = series.get(clave);
      const puntos = unirPuntos(previa?.puntos || [], serie.puntos || []);
      series.set(clave, {...previa, ...serie, puntos,
        hasta:serie.hasta || previa?.hasta || puntos.at(-1)?.t || null});
    }
    let ultimo = null;
    for (const serie of series.values()) {
      const t = serie.puntos.at(-1)?.t;
      if (t && (!ultimo || instante(t) > instante(ultimo))) ultimo = t;
    }
    return {visible:true, paquete, pelea_id:actual?.pelea_id || null, evento_clave:eventoClave,
      series, ultimo, error:null, ultimo_ok:paquete.consultado || anterior.ultimo_ok};
  }

  function registrarFallo(estado) {
    return {...estado, error:estado.visible
      ? 'No pude actualizar el mercado. Se conservan los últimos datos; reintentaré automáticamente.'
      : 'No pude comprobar si hay un evento en vivo. Reintentaré automáticamente.'};
  }

  function urlConsulta(estado, terminadas = []) {
    const parametros = new URLSearchParams();
    if (estado.pelea_id && estado.ultimo) {
      parametros.set('desde', estado.ultimo); parametros.set('pelea_id', estado.pelea_id);
    }
    if (terminadas.length && estado.paquete?.evento?.id) {
      parametros.set('terminadas', JSON.stringify(terminadas));
      parametros.set('evento_id', estado.paquete.evento.id);
    }
    return '/api/mercado/vivo' + (parametros.size ? `?${parametros}` : '');
  }

  function avisoMercado(estado) {
    if (estado.error) return estado.error;
    const mercado = estado.paquete?.mercado || {};
    if (mercado.todas_caidas) return 'Sin cuotas en vivo: ninguna fuente confirma datos recientes. Las últimas cuotas se conservan con su hora.';
    if (!mercado.hay_cuotas) return 'Todavía no hay cuotas publicadas para esta pelea.';
    if (mercado.con_error?.length) return `Fuentes con aviso: ${mercado.con_error.join(', ')}. Revisa la hora de cada cuota.`;
    return '';
  }

  function prepararGrafico(series) {
    const visibles = [...series.values()].filter(serie => serie.puntos.length);
    const puntos = visibles.flatMap(serie => serie.puntos);
    if (!puntos.length) return null;
    let desde = Math.min(...puntos.map(punto => instante(punto.t)));
    let hasta = Math.max(...visibles.map(serie => Math.max(instante(serie.puntos.at(-1).t),
      Number.isFinite(instante(serie.hasta)) ? instante(serie.hasta) : 0)));
    if (desde === hasta) { desde -= 30000; hasta += 30000; }
    const probabilidades = puntos.map(punto => Number(punto.pa));
    const menor = Math.min(...probabilidades), mayor = Math.max(...probabilidades);
    const centro = (menor + mayor) / 2;
    const amplitud = Math.max(.2, mayor - menor + .08);
    const minimo = Math.max(0, Math.floor((centro - amplitud / 2) * 10) / 10);
    const maximo = Math.min(1, Math.ceil((centro + amplitud / 2) * 10) / 10);
    const marcas = [];
    for (let i = 0; i <= 4; i++) marcas.push(minimo + (maximo - minimo) * i / 4);
    return {series:visibles, desde, hasta, minimo, maximo, marcas,
      tiempos:[...new Set(puntos.map(punto => instante(punto.t)))].sort((a, b) => a - b)};
  }

  function trazoEscalones(serie, x, y) {
    if (!serie.puntos.length) return '';
    const redondear = valor => Number(valor.toFixed(2));
    const primero = serie.puntos[0];
    let trazo = `M${redondear(x(instante(primero.t)))} ${redondear(y(Number(primero.pa)))}`;
    for (const punto of serie.puntos.slice(1)) {
      trazo += ` H${redondear(x(instante(punto.t)))} V${redondear(y(Number(punto.pa)))}`;
    }
    const ultimo = serie.puntos.at(-1);
    const fin = Math.max(instante(ultimo.t), Number.isFinite(instante(serie.hasta)) ? instante(serie.hasta) : 0);
    return trazo + ` H${redondear(x(fin))}`;
  }

  function valoresEn(grafico, t) {
    return grafico.series.map(serie => {
      let inferior = 0, superior = serie.puntos.length;
      while (inferior < superior) {
        const medio = (inferior + superior) >>> 1;
        if (instante(serie.puntos[medio].t) <= t) inferior = medio + 1;
        else superior = medio;
      }
      const punto = serie.puntos[inferior - 1];
      const fin = Math.max(instante(serie.puntos.at(-1).t),
        Number.isFinite(instante(serie.hasta)) ? instante(serie.hasta) : 0);
      return punto && t <= fin ? {serie, punto} : {serie, punto:null};
    });
  }

  function tablaCuotas(filas, actual, tipo) {
    const elegidas = (filas || []).filter(fila => fila.tipo === tipo);
    if (!elegidas.length) return `<p class="vivo-vacio">${tipo === 'casa' ? 'Sin cuotas de casas publicadas.' : 'Sin precio de Polymarket para esta pelea.'}</p>`;
    return `<table class="vivo-tabla"><caption>${tipo === 'casa' ? 'Casas de apuestas · cuota americana' : 'Mercado de predicción · precio expresado en americana'}</caption>
      <thead><tr><th scope="col">${tipo === 'casa' ? 'Casa / fuente' : 'Mercado'}</th><th scope="col">${escapar(actual.a?.nombre || 'Esquina A')}</th><th scope="col">${escapar(actual.b?.nombre || 'Esquina B')}</th><th scope="col">Confirmada</th></tr></thead>
      <tbody>${elegidas.map(fila => `<tr><th scope="row"><b>${escapar(fila.casa)}</b><small>${escapar(fila.fuente_nombre || fila.fuente)}</small></th>
        ${['a', 'b'].map(lado => `<td><b>${americana(fila[lado]?.americana)}</b>${tipo === 'casa' && fila[`mejor_${lado}`] ? '<span class="vivo-mejor">Mejor</span>' : ''}</td>`).join('')}
        <td><time datetime="${escapar(fila.visto || '')}" title="${escapar(fechaHora(fila.visto))}">${hora(fila.visto)}</time></td></tr>`).join('')}</tbody></table>`;
  }

  function resolucionMercado(pelea, breve = false) {
    const resuelta = pelea?.resolucion;
    if (!resuelta || !resuelta.ganador || !((resuelta.a === 1 && resuelta.b === 0) ||
      (resuelta.b === 1 && resuelta.a === 0))) return '';
    const fuente = resuelta.fuente === 'polymarket' ? 'Polymarket' : resuelta.fuente;
    return `<span class="vivo-resolucion"><b>${escapar(resuelta.etiqueta || 'Mercado resuelto')} · ${escapar(fuente)}</b>
      <span>${escapar(resuelta.ganador)} · 100 %</span>${breve ? '' : '<small>Resolución del mercado de predicción. No es un resultado oficial ni una probabilidad del modelo.</small>'}</span>`;
  }

  // Las pruebas usan las mismas funciones del navegador sin iniciar el polling.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {crearEstado, recibirPaquete, registrarFallo, urlConsulta, unirPuntos,
      claveSerie, americana, porcentaje, probAmericana, prepararGrafico, trazoEscalones,
      valoresEn, tablaCuotas, avisoMercado, resolucionMercado, hora, fechaHora};
  }
  if (typeof document === 'undefined') return;
  const contenedor = document.getElementById('vivo');
  if (!contenedor) return;

  let estado = crearEstado(), enPeticion = false, temporizador = null, peticion = null;
  let grafico = null, inspeccion = null, firmaGrafico = '', colores = new Map();
  let estadoAnunciado = '', entrada = null, marcas = new Set();
  const coordenadas = {ancho:920, alto:310, izquierda:88, derecha:150, arriba:20, abajo:44};
  const nombresEstado = {en_curso:'En curso · estimado', terminada:'Terminada', por_pelear:'Por pelear'};
  const tituloEstado = pelea => pelea?.motivo_clave === 'manual' ? 'Terminada · marcada por ti' :
    nombresEstado[pelea?.estado] || 'Estado desconocido';

  contenedor.innerHTML = `<div class="vivo-cab"><h2 id="vivo-titulo">Mercado en vivo</h2>
    <span class="vivo-sello" id="vivo-sello">En vivo</span><span class="vivo-evento" id="vivo-evento"></span>
    <button type="button" class="vivo-refrescar" id="vivo-refrescar">Actualizar</button></div>
    <div id="vivo-contenido"><div id="vivo-actual"></div><p id="vivo-motivo" class="vivo-motivo"></p>
      <div class="vivo-marca-controles"><button type="button" id="vivo-marcar" class="vivo-marcar">Marcar terminada</button>
        <button type="button" id="vivo-deshacer" class="vivo-marcar" hidden>Deshacer última marca</button>
        <p>La marca queda en este navegador para este evento. No agrega un resultado ni cambia el modelo.</p></div>
      <p id="vivo-aviso" class="vivo-aviso" hidden></p>
      <figure class="vivo-grafico"><figcaption id="vivo-grafico-titulo"></figcaption>
        <p class="vivo-grafico-nota">Probabilidad de mercado sin margen. Las marcas muestran su equivalente en cuota americana.</p>
        <div id="vivo-trazo" class="vivo-trazo"></div><ul id="vivo-leyenda" class="vivo-leyenda" aria-label="Series del gráfico"></ul>
        <div id="vivo-inspector" class="vivo-inspector" hidden><label for="vivo-tiempo">Inspeccionar la línea</label>
          <input id="vivo-tiempo" type="range" min="0" max="0" value="0" step="1" aria-describedby="vivo-inspector-ayuda">
          <p id="vivo-inspector-ayuda">Arrastra sobre el gráfico o usa las flechas del control. Inicio y Fin van al primer y al último cambio.</p>
          <div id="vivo-lectura" class="vivo-lectura"></div></div>
      </figure>
      <div class="vivo-cuotas"><div id="vivo-casas"></div><div class="vivo-prediccion" id="vivo-prediccion"></div></div>
      <details class="vivo-programa"><summary>Estado de las peleas <span id="vivo-total"></span></summary><ol id="vivo-peleas"></ol></details>
      <p class="vivo-nota" id="vivo-nota"></p><p class="vivo-refresco" id="vivo-refresco"></p></div>
    <p class="vivo-anuncio" id="vivo-anuncio" role="status" aria-live="polite" aria-atomic="true"></p>`;
  const buscar = id => document.getElementById(id);
  const poner = (id, html) => { const nodo = buscar(id); if (nodo.innerHTML !== html) nodo.innerHTML = html; };

  function cargarMarcas(nuevo) {
    let guardadas;
    try { guardadas = JSON.parse(localStorage.getItem(`ufc-mercado-terminadas:${nuevo.evento_clave}`) || '[]'); }
    catch { guardadas = []; }
    const ids = new Set((nuevo.paquete?.peleas || []).map(pelea => pelea.pelea_id));
    return new Set(Array.isArray(guardadas) ? guardadas.filter(id => typeof id === 'string' && ids.has(id)) : []);
  }

  function guardarMarcas() {
    try { localStorage.setItem(`ufc-mercado-terminadas:${estado.evento_clave}`, JSON.stringify([...marcas])); }
    catch { /* Si el navegador no deja guardar, la marca sigue durante esta visita. */ }
  }

  function colorSerie(serie) {
    if (serie.tipo === 'mercado_prediccion') return 'var(--txt)';
    const clave = claveSerie(serie);
    if (!colores.has(clave)) colores.set(clave, colores.size);
    const indice = colores.get(clave);
    return indice < 6 ? `var(--vivo-color-${indice + 1})` : 'var(--tenue)';
  }

  function identidad(peleador, lado) {
    const nombre = peleador?.nombre || `Esquina ${lado.toUpperCase()}`;
    const pais = peleador?.pais;
    const codigo = String(pais?.bandera || pais?.codigo || '').toUpperCase();
    const bandera = /^[A-Z]{2}$/.test(codigo)
      ? `<img class="vivo-bandera" src="/api/bandera/${codigo}" alt="${escapar(pais.nombre || codigo)}" width="24" height="18" loading="lazy" decoding="async">` : '';
    const foto = typeof retrato === 'function' ? retrato(nombre, lado) : '';
    return `<div class="vivo-esquina ${lado}">${foto}<div><span class="vivo-esquina-rotulo">Esquina ${lado.toUpperCase()}</span>
      <h3>${escapar(nombre)}</h3>${bandera}${peleador?.campeon
        ? `<span class="vivo-campeon">${peleador.campeon.interino ? 'Campeón interino' : 'Campeón'} · ${escapar(peleador.campeon.division)}</span>` : ''}</div></div>`;
  }

  function anunciar() {
    const paquete = estado.paquete;
    const texto = estado.visible ? [paquete.simulado ? 'Datos simulados.' : '',
      `${paquete.actual?.a?.nombre || ''} frente a ${paquete.actual?.b?.nombre || ''}.`,
      paquete.actual ? tituloEstado(paquete.actual) : 'Sin pelea identificada.', avisoMercado(estado)].filter(Boolean).join(' ') : '';
    if (texto !== estadoAnunciado) { buscar('vivo-anuncio').textContent = texto; estadoAnunciado = texto; }
  }

  function pintar() {
    if (!estado.visible) {
      entrada?.cancel(); entrada = null;
      contenedor.classList.add('oculto');
      anunciar(); return;
    }
    const aparecio = contenedor.classList.contains('oculto');
    contenedor.classList.remove('oculto');
    const paquete = estado.paquete, actual = paquete.actual;
    poner('vivo-evento', escapar(paquete.evento?.nombre || 'Evento en curso'));
    poner('vivo-sello', paquete.simulado ? 'Datos simulados' : 'En vivo');
    buscar('vivo-sello').classList.toggle('simulado', !!paquete.simulado);
    if (actual) {
      poner('vivo-actual', `<div class="vivo-cara">${identidad(actual.a, 'a')}<div class="vivo-versus" aria-hidden="true">VS</div>${identidad(actual.b, 'b')}</div>
        <div class="vivo-estado"><span>${escapar(tituloEstado(actual))}</span>${actual.peso ? `<span>${escapar(actual.peso)}</span>` : ''}</div>${resolucionMercado(actual)}`);
      poner('vivo-motivo', escapar(actual.motivo || 'Sin señal para precisar el estado de esta pelea.'));
      poner('vivo-casas', tablaCuotas(actual.cotizaciones, actual, 'casa'));
      poner('vivo-prediccion', tablaCuotas(actual.cotizaciones, actual, 'mercado_prediccion') +
        '<p>Polymarket es un mercado de predicción. Su precio es una referencia; no es una cuota de casa ni un precio comprable garantizado.</p>');
    } else {
      poner('vivo-actual', '<p class="vivo-vacio">Hay un evento en curso, pero todavía no pude identificar sus peleas.</p>');
      for (const id of ['vivo-motivo', 'vivo-casas', 'vivo-prediccion']) poner(id, '');
    }
    buscar('vivo-marcar').hidden = !actual || actual.estado === 'terminada';
    buscar('vivo-marcar').setAttribute('aria-label', actual
      ? `Marcar terminada: ${actual.a?.nombre} vs ${actual.b?.nombre}` : 'Marcar terminada');
    buscar('vivo-marcar').disabled = enPeticion;
    buscar('vivo-deshacer').hidden = !marcas.size;
    buscar('vivo-deshacer').disabled = enPeticion;
    const aviso = avisoMercado(estado);
    poner('vivo-aviso', escapar(aviso));
    buscar('vivo-aviso').hidden = !aviso;
    buscar('vivo-aviso').classList.toggle('error', !!estado.error || !!paquete.mercado?.todas_caidas);
    poner('vivo-grafico-titulo', `Línea de ${escapar(actual?.a?.nombre || 'la esquina A')}`);
    const nuevaFirma = JSON.stringify([...estado.series.values()]);
    if (nuevaFirma !== firmaGrafico) { firmaGrafico = nuevaFirma; pintarGrafico(); }
    poner('vivo-total', `· ${numero(paquete.peleas?.length || 0)}${marcas.size ? ` · ${numero(marcas.size)} marcada${marcas.size === 1 ? '' : 's'} por ti` : ''}`);
    poner('vivo-peleas', (paquete.peleas || []).map(pelea => `<li${pelea.pelea_id === actual?.pelea_id ? ' class="actual"' : ''}>
      <b>${escapar(pelea.a?.nombre)} <span>vs</span> ${escapar(pelea.b?.nombre)}</b>
      <span>${escapar(tituloEstado(pelea))}</span><small>${escapar(pelea.motivo || '')}</small>${resolucionMercado(pelea, true)}${marcas.has(pelea.pelea_id)
        ? `<button type="button" class="vivo-marcar" data-deshacer="${escapar(pelea.pelea_id)}">Deshacer marca de ${escapar(pelea.a?.nombre)} vs ${escapar(pelea.b?.nombre)}</button>`
        : pelea.estado !== 'terminada' ? `<button type="button" class="vivo-marcar" data-marcar="${escapar(pelea.pelea_id)}" aria-label="Marcar terminada: ${escapar(pelea.a?.nombre)} vs ${escapar(pelea.b?.nombre)}">Marcar terminada</button>` : ''}</li>`).join(''));
    poner('vivo-nota', escapar(paquete.nota || 'Cuotas del mercado; no son una predicción del modelo ni una recomendación.'));
    poner('vivo-refresco', `Última lectura local: ${hora(estado.ultimo_ok)} · se consulta la caché cada 12 s.`);
    if (typeof cargarFotos === 'function') cargarFotos(contenedor);
    anunciar();
    if (aparecio && typeof contenedor.animate === 'function' && !(typeof porTeclado !== 'undefined' && porTeclado)) {
      const menos = typeof reducir === 'function' && reducir();
      entrada = contenedor.animate([{opacity:0}, {opacity:1}],
        {duration:menos ? 120 : 180, easing:typeof EASE_OUT !== 'undefined' ? EASE_OUT : 'cubic-bezier(0.23, 1, 0.32, 1)'});
    }
  }

  function escalas() {
    const c = coordenadas;
    return {x:t => c.izquierda + (t - grafico.desde) / (grafico.hasta - grafico.desde) * (c.ancho - c.izquierda - c.derecha),
      y:p => c.arriba + (grafico.maximo - p) / (grafico.maximo - grafico.minimo) * (c.alto - c.arriba - c.abajo)};
  }

  function pintarGrafico() {
    grafico = prepararGrafico(estado.series);
    buscar('vivo-inspector').hidden = !grafico;
    if (!grafico) {
      poner('vivo-trazo', '<p class="vivo-vacio">Sin historial de cuotas para dibujar la línea.</p>');
      poner('vivo-leyenda', ''); return;
    }
    const c = coordenadas;
    c.ancho = Math.max(300, Math.round(buscar('vivo-trazo').clientWidth || 920));
    c.alto = c.ancho < 540 ? 280 : 310;
    c.izquierda = c.ancho < 540 ? 68 : 88;
    c.derecha = c.ancho < 540 ? 16 : 150;
    const {x, y} = escalas();
    // La paleta sigue el orden de casas del contrato; nunca cambia de color
    // cuando una casa pasa a ser favorita o se cruzan sus líneas.
    grafico.series.forEach(colorSerie);
    const nombres = grafico.series.map(serie => serie.etiqueta || serie.casa).join(', ');
    let svg = `<svg viewBox="0 0 ${c.ancho} ${c.alto}" aria-labelledby="vivo-svg-titulo vivo-svg-descripcion" role="img">
      <title id="vivo-svg-titulo">Probabilidad de mercado sin margen para ${escapar(estado.paquete.actual?.a?.nombre)}</title>
      <desc id="vivo-svg-descripcion">Líneas escalonadas de ${escapar(nombres)}. Usa el control Inspeccionar la línea para leer cada cambio con teclado o toque.</desc>`;
    for (const marca of grafico.marcas) {
      const altura = y(marca);
      svg += `<g class="vivo-eje"><line x1="${c.izquierda}" x2="${c.ancho - c.derecha}" y1="${altura}" y2="${altura}"/>
        <text x="${c.izquierda - 10}" y="${altura - 2}" text-anchor="end">${numero(marca * 100, Number.isInteger(marca * 100) ? 0 : 1)} %</text>
        <text class="vivo-eje-cuota" x="${c.izquierda - 10}" y="${altura + 13}" text-anchor="end">${americana(probAmericana(marca))}</text></g>`;
    }
    for (let i = 0; i <= 3; i++) {
      const t = grafico.desde + (grafico.hasta - grafico.desde) * i / 3;
      svg += `<text class="vivo-hora" x="${x(t)}" y="${c.alto - 15}" text-anchor="middle">${hora(new Date(t).toISOString())}</text>`;
    }
    const etiquetas = grafico.series.map(serie => ({serie, altura:y(Number(serie.puntos.at(-1).pa))})).sort((a, b) => a.altura - b.altura);
    // Las etiquetas directas se separan sin mover la línea ni su valor real.
    for (let i = 0; i < etiquetas.length; i++) {
      etiquetas[i].etiquetaY = Math.max(c.arriba + 5, etiquetas[i].altura, i ? etiquetas[i - 1].etiquetaY + 17 : 0);
    }
    for (let i = etiquetas.length - 1; i >= 0; i--) {
      etiquetas[i].etiquetaY = Math.min(c.alto - c.abajo - 3, etiquetas[i].etiquetaY,
        i < etiquetas.length - 1 ? etiquetas[i + 1].etiquetaY - 17 : Infinity);
    }
    for (const {serie, altura, etiquetaY} of etiquetas) {
      const color = colorSerie(serie), punteada = serie.tipo === 'mercado_prediccion';
      const ultimo = serie.puntos.at(-1);
      const fin = Math.max(instante(ultimo.t), Number.isFinite(instante(serie.hasta)) ? instante(serie.hasta) : 0);
      const finX = x(fin);
      svg += `<path class="vivo-linea${punteada ? ' prediccion' : ''}" style="stroke:${color}" d="${trazoEscalones(serie, x, y)}"/>`;
      if (c.ancho >= 540) {
        const nombre = String(serie.etiqueta || serie.casa);
        const etiqueta = nombre.length > 18 ? nombre.slice(0, 17) + '…' : nombre;
        svg += `<path class="vivo-conector" style="stroke:${color}" d="M${finX} ${altura} L${c.ancho - c.derecha + 8} ${etiquetaY}"/>
          <text class="vivo-directa" x="${c.ancho - c.derecha + 12}" y="${etiquetaY + 4}"><title>${escapar(nombre)}</title>${escapar(etiqueta)}</text>`;
      }
    }
    svg += `<line id="vivo-cursor" class="vivo-cursor" x1="0" x2="0" y1="${c.arriba}" y2="${c.alto - c.abajo}" visibility="hidden"/></svg>`;
    poner('vivo-trazo', svg);
    poner('vivo-leyenda', grafico.series.map(serie => `<li><span class="vivo-muestra${serie.tipo === 'mercado_prediccion' ? ' punteada' : ''}" style="border-color:${colorSerie(serie)}" aria-hidden="true"></span>
      <span>${escapar(serie.etiqueta || serie.casa)}${serie.tipo === 'mercado_prediccion' ? ' · predicción' : ''}</span></li>`).join(''));
    const rango = buscar('vivo-tiempo');
    rango.max = String(grafico.tiempos.length - 1);
    if (inspeccion == null) rango.value = rango.max;
    else rango.value = String(grafico.tiempos.reduce((mejor, t, i) => Math.abs(t - inspeccion) < Math.abs(grafico.tiempos[mejor] - inspeccion) ? i : mejor, 0));
    leerGrafico(grafico.tiempos[Number(rango.value)], false);
  }

  function leerGrafico(t, fijar = true) {
    if (!grafico) return;
    if (fijar) inspeccion = t;
    const cursor = buscar('vivo-cursor'), {x} = escalas();
    cursor.setAttribute('x1', String(x(t))); cursor.setAttribute('x2', String(x(t)));
    cursor.setAttribute('visibility', 'visible');
    const valores = valoresEn(grafico, t);
    poner('vivo-lectura', `<time datetime="${new Date(t).toISOString()}">${fechaHora(new Date(t).toISOString())}</time>
      <ul>${valores.map(({serie, punto}) => `<li><b>${escapar(serie.etiqueta || serie.casa)}</b><span>${punto ? porcentaje(punto.pa) : 'Sin dato a esta hora'}</span>
        <span>${punto ? americana(punto.a) : '—'}</span></li>`).join('')}</ul>`);
    buscar('vivo-tiempo').setAttribute('aria-valuetext', `${hora(new Date(t).toISOString())}; ${valores.map(({serie, punto}) =>
      `${serie.etiqueta || serie.casa}: ${punto ? porcentaje(punto.pa) : 'sin dato'}`).join('; ')}`);
  }

  buscar('vivo-tiempo').addEventListener('input', evento => {
    leerGrafico(grafico?.tiempos[Number(evento.target.value)]);
  });
  const trazo = buscar('vivo-trazo');
  function inspeccionarPuntero(evento) {
    if (!grafico) return;
    const svg = trazo.querySelector('svg');
    const rectangulo = svg.getBoundingClientRect(), c = coordenadas;
    const posicion = (evento.clientX - rectangulo.left) / rectangulo.width * c.ancho;
    const proporcion = Math.max(0, Math.min(1, (posicion - c.izquierda) / (c.ancho - c.izquierda - c.derecha)));
    const t = grafico.desde + proporcion * (grafico.hasta - grafico.desde);
    const indice = grafico.tiempos.reduce((mejor, valor, i) => Math.abs(valor - t) < Math.abs(grafico.tiempos[mejor] - t) ? i : mejor, 0);
    buscar('vivo-tiempo').value = String(indice);
    leerGrafico(grafico.tiempos[indice]);
  }
  trazo.addEventListener('pointerdown', evento => { trazo.setPointerCapture?.(evento.pointerId); inspeccionarPuntero(evento); });
  trazo.addEventListener('pointermove', evento => { if (evento.pointerType === 'mouse' || evento.buttons) inspeccionarPuntero(evento); });

  function programar() {
    clearTimeout(temporizador);
    temporizador = document.hidden ? null : setTimeout(consultar, INTERVALO);
  }

  async function consultar() {
    if (document.hidden || enPeticion) return;
    clearTimeout(temporizador);
    enPeticion = true;
    buscar('vivo-refrescar').disabled = true;
    buscar('vivo-marcar').disabled = true;
    buscar('vivo-deshacer').disabled = true;
    peticion = new AbortController();
    const limite = setTimeout(() => peticion?.abort(), 10000);
    try {
      const pedir = async url => {
        const respuesta = await fetch(url, {signal:peticion.signal, cache:'no-store'});
        if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
        return respuesta.json();
      };
      const anteriorPelea = estado.pelea_id, anteriorEvento = estado.evento_clave;
      let siguiente = recibirPaquete(estado, await pedir(urlConsulta(estado, [...marcas])));
      if (siguiente.visible && siguiente.evento_clave !== anteriorEvento) {
        marcas = cargarMarcas(siguiente);
        // Después de recargar el navegador, la primera respuesta descubre el
        // evento; la segunda aplica sus marcas antes de mostrar una pelea vieja.
        if (marcas.size) siguiente = recibirPaquete(siguiente,
          await pedir(urlConsulta(siguiente, [...marcas])));
      }
      estado = siguiente;
      if (estado.pelea_id !== anteriorPelea || estado.evento_clave !== anteriorEvento) {
        colores = new Map(); inspeccion = null; firmaGrafico = '';
      }
      pintar();
    } catch (error) {
      // Al ocultar la pestaña abortamos; ese gesto no es una caída de la fuente.
      if (!document.hidden) { estado = registrarFallo(estado); pintar(); }
    } finally {
      clearTimeout(limite);
      peticion = null; enPeticion = false;
      buscar('vivo-refrescar').disabled = false;
      buscar('vivo-marcar').disabled = false;
      buscar('vivo-deshacer').disabled = false;
      programar();
    }
  }
  buscar('vivo-refrescar').addEventListener('click', consultar);
  function marcar(id) {
    if (!id || enPeticion || !estado.paquete?.peleas?.some(pelea => pelea.pelea_id === id)) return;
    marcas.add(id); guardarMarcas(); consultar();
  }
  buscar('vivo-marcar').addEventListener('click', () => marcar(estado.pelea_id));
  function deshacer(id) {
    if (!id || enPeticion) return;
    marcas.delete(id); guardarMarcas(); consultar();
  }
  buscar('vivo-deshacer').addEventListener('click', () => deshacer([...marcas].at(-1)));
  buscar('vivo-peleas').addEventListener('click', evento => {
    const boton = evento.target.closest('[data-deshacer], [data-marcar]');
    if (boton?.dataset.deshacer) deshacer(boton.dataset.deshacer);
    else if (boton?.dataset.marcar) marcar(boton.dataset.marcar);
  });
  let anchoAnterior = 0;
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(entradas => {
    const ancho = Math.round(entradas[0].contentRect.width);
    if (ancho > 0 && ancho !== anchoAnterior) { anchoAnterior = ancho; if (grafico) pintarGrafico(); }
  }).observe(trazo);
  document.addEventListener('visibilitychange', () => {
    clearTimeout(temporizador);
    if (document.hidden) peticion?.abort();
    else consultar();
  });
  // El primer pedido corre aparte de Inicio: una fuente caída no demora la portada.
  consultar();
})();
