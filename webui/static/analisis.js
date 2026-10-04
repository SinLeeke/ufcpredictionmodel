/* Gráficos de cada pelea. SVG y HTML locales: también funcionan sin internet.
   El historial y el modelo de seis resultados son fuentes distintas. Si falta
   una distribución completa, se muestra el dato pendiente y no se inventa. */
(function () {
  'use strict';
  const METODOS = [
    { clave: 'KO/TKO', resultado: 'KO', nombre: 'KO / TKO', estilo: 'ko' },
    { clave: 'Submission', resultado: 'SUB', nombre: 'Sumisión', estilo: 'sub' },
    { clave: 'Decision', resultado: 'DEC', nombre: 'Decisión', estilo: 'dec' },
  ];
  const escapar = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const numero = (v) => v != null && v !== '' && typeof v !== 'boolean' &&
    Number.isFinite(Number(v)) ? Number(v) : null;
  const prob = (v) => {
    const n = numero(v);
    return n != null && n >= 0 && n <= 1 ? n : null;
  };
  const porcentaje = (v, d = 1) => Number(v * 100).toLocaleString('es-CL', {
    minimumFractionDigits: d, maximumFractionDigits: d,
  }) + ' %';
  const ancho = (v) => (v * 100).toFixed(4);
  const cifra = (p, clave, texto) => `<span data-num="${escapar(p.id)}:analisis:${clave}">${texto}</span>`;
  const distribucion = (datos, claves, sumaCompleta = true) => {
    if (!datos || typeof datos !== 'object') return null;
    const valores = claves.map(k => prob(datos[k]));
    if (valores.some(v => v == null)) return null;
    const suma = valores.reduce((a, b) => a + b, 0);
    if (suma <= 0 || suma > 1.001 || (sumaCompleta && suma < .999)) return null;
    return Object.fromEntries(claves.map((k, i) => [k, valores[i]]));
  };
  const intervalo = (ci) => Array.isArray(ci) && ci.length === 2 &&
    ci.every(v => prob(v) != null) && Number(ci[0]) <= Number(ci[1])
    ? ci.map(Number) : null;

  function leyendaEsquinas(p) {
    return `<div class="analisis-esquinas"><span class="analisis-esquina esquina-a"><i aria-hidden="true"></i>${escapar(p.a)}</span><span class="analisis-esquina esquina-b"><i aria-hidden="true"></i>${escapar(p.b)}</span></div>`;
  }

  function rangoVictoria(p, lado, valor, ci) {
    return `<div class="analisis-rango esquina-${lado}">
      <div class="analisis-rango-cab"><span>${escapar(p[lado])}</span><strong>${cifra(p, 'victoria-' + lado, valor == null ? 'Sin dato' : porcentaje(valor))}</strong></div>
      ${ci ? `<div class="analisis-rango-pista" title="Rango de incertidumbre al 95 %: ${porcentaje(ci[0])} a ${porcentaje(ci[1])}" aria-hidden="true"><span class="analisis-intervalo" style="left:${ancho(ci[0])}%;width:${ancho(ci[1] - ci[0])}%"></span>${valor == null ? '' : `<span class="analisis-punto" style="left:${ancho(valor)}%"></span>`}</div><div class="analisis-rango-pie">Rango 95 % <span>${cifra(p, 'rango-' + lado, porcentaje(ci[0]) + ' – ' + porcentaje(ci[1]))}</span></div>` : '<p class="analisis-sin-dato">Rango de incertidumbre no disponible.</p>'}
    </div>`;
  }

  function victoria(p) {
    const a = prob(p.p_a), b = prob(p.p_b);
    const valido = a != null && b != null && Math.abs(a + b - 1) < .001;
    const favorito = valido ? (a >= b ? p.a : p.b) : '';
    const ciA = intervalo(p.ci_a);
    const ciB = intervalo(p.ci_b) || (ciA ? [1 - ciA[1], 1 - ciA[0]] : null);
    const ring = valido ? `<div class="analisis-donut-wrap"><svg class="analisis-donut" viewBox="0 0 160 160" role="img" aria-label="Victoria: ${escapar(p.a)} ${porcentaje(a)}; ${escapar(p.b)} ${porcentaje(b)}"><circle class="analisis-donut-base" cx="80" cy="80" r="61" pathLength="100"/><circle class="analisis-donut-a" cx="80" cy="80" r="61" pathLength="100" stroke-dasharray="${ancho(a)} ${ancho(b)}"/><circle class="analisis-donut-b" cx="80" cy="80" r="61" pathLength="100" stroke-dasharray="${ancho(b)} ${ancho(a)}" stroke-dashoffset="-${ancho(a)}"/></svg><div class="analisis-donut-centro"><span>Victoria</span><strong>${cifra(p, 'donut', porcentaje(Math.max(a, b)))}</strong><span>${escapar(favorito)}</span></div></div>` : '<p class="analisis-sin-dato">Probabilidad de victoria no disponible.</p>';
    return `<section class="analisis-panel analisis-victoria"><h4>Probabilidad de victoria</h4><div class="analisis-victoria-cuerpo">${ring}<div class="analisis-rangos">${rangoVictoria(p, 'a', a, ciA)}${rangoVictoria(p, 'b', b, ciB)}</div></div><p class="analisis-ayuda">El rango muestra la incertidumbre de la estimación.</p></section>`;
  }

  function historial(p, lado) {
    const info = p['info_' + lado] || {};
    const claves = METODOS.map(m => m.clave);
    // Los payloads antiguos pueden traer el mismo historial dentro de info.
    // Las tasas de victoria neutras usadas como entrada del modelo no sirven
    // como historial observado y no se usan como respaldo.
    return distribucion(p['metodo_hist_' + lado], claves, false) ||
      distribucion(info.metodo_victorias, claves, false);
  }

  function barraMetodos(p, datos, nombre, clave, fuente) {
    return `<div class="analisis-hist-fila"><div class="analisis-hist-cab"><strong>${escapar(nombre)}</strong>${fuente ? `<span>${escapar(fuente)}</span>` : ''}</div>
      ${datos ? `<div class="analisis-apilada" role="img" aria-label="${escapar(nombre)}: ${METODOS.map(m => m.nombre + ' ' + porcentaje(datos[m.clave])).join('; ')}">${METODOS.map(m => `<span class="analisis-segmento metodo-${m.estilo}" style="width:${ancho(datos[m.clave])}%" title="${escapar(nombre)} · ${m.nombre}: ${porcentaje(datos[m.clave])}">${datos[m.clave] >= .15 ? porcentaje(datos[m.clave], 0) : ''}</span>`).join('')}</div><div class="analisis-hist-valores">${METODOS.map(m => `<span><i class="metodo-${m.estilo}" aria-hidden="true"></i>${m.nombre} <b>${cifra(p, clave + '-' + m.resultado, porcentaje(datos[m.clave]))}</b></span>`).join('')}</div>` : `<p class="analisis-sin-dato">${clave === 'proyeccion' ? 'Proyección del método no disponible.' : 'Historial de victorias por método no disponible.'}</p>`}
    </div>`;
  }

  function metodosHistoricos(p) {
    const claves = METODOS.map(m => m.clave);
    const proyeccion = distribucion(p.metodo, claves);
    return `<section class="analisis-panel analisis-historial"><h4>Cómo puede terminar</h4><p class="analisis-ayuda">Historial de victorias de cada peleador y proyección de este combate.</p>${barraMetodos(p, historial(p, 'a'), p.a, 'hist-a', p.metodo_hist_fuente_a || p.info_a?.metodo_victorias_fuente || '')}${barraMetodos(p, historial(p, 'b'), p.b, 'hist-b', p.metodo_hist_fuente_b || p.info_b?.metodo_victorias_fuente || '')}${barraMetodos(p, proyeccion, 'Este combate', 'proyeccion', 'Proyección del método')}</section>`;
  }

  function resultados(p) {
    const claves = ['A_KO', 'A_SUB', 'A_DEC', 'B_KO', 'B_SUB', 'B_DEC'];
    let datos = distribucion(p.probabilidades_metodo, claves);
    if (!datos && Array.isArray(p.metodo6)) {
      const valores = Object.fromEntries(p.metodo6.filter(v => v && !v.error).map(v => [v.clase, v.p_modelo]));
      datos = distribucion(valores, claves);
    }
    if (!datos) return `<section class="analisis-panel analisis-resultados"><h4>Método de cada peleador</h4><p class="analisis-sin-dato">El modelo por resultado todavía no está disponible para esta pelea.</p></section>`;
    const metodoPrincipal = (lado) => METODOS.reduce((mejor, m) => datos[lado + '_' + m.resultado] > datos[lado + '_' + mejor.resultado] ? m : mejor);
    const barras = (lado) => METODOS.map(m => {
      const v = datos[lado + '_' + m.resultado];
      return `<div class="analisis-metodo-fila"><span>${m.nombre}</span><div class="analisis-barra" title="${escapar(p[lado.toLowerCase()])} gana por ${m.nombre}: ${porcentaje(v)}"><span style="width:${ancho(v)}%"></span></div><strong>${cifra(p, lado + '_' + m.resultado, porcentaje(v))}</strong></div>`;
    }).join('');
    return `<section class="analisis-panel analisis-resultados"><h4>Método de cada peleador</h4><p class="analisis-ayuda">Probabilidad de que cada peleador gane por ese método.</p><div class="analisis-metodos-peleadores">${['A', 'B'].map(lado => `<div class="analisis-metodos-lado esquina-${lado.toLowerCase()}"><div class="analisis-metodos-nombre"><i aria-hidden="true"></i><strong>${escapar(p[lado.toLowerCase()])}</strong></div><p class="analisis-metodo-principal">Más probable: <b>${metodoPrincipal(lado).nombre}</b></p>${barras(lado)}</div>`).join('')}</div><p class="analisis-fuente">Modelo por resultado · Seis resultados posibles. Se calcula de forma independiente al pronóstico combinado de victoria y a la proyección de tres métodos.</p></section>`;
  }

  // El contenido del análisis, sin el desplegable: lo usa la cartelera dentro
  // de su <details> y el modal de una pelea del historial (explorar.js), que
  // muestra las mismas gráficas abiertas. Un solo componente para los dos.
  globalThis.analisisContenido = function analisisContenido(p) {
    return `<div class="analisis-contenido">${leyendaEsquinas(p)}<div class="analisis-graficos">${victoria(p)}${metodosHistoricos(p)}</div>${resultados(p)}</div>`;
  };

  globalThis.analisisPelea = function analisisPelea(p, abierta = false) {
    return `<details class="analisis-pelea" data-analisis="${escapar(p.id)}"${abierta ? ' open' : ''}><summary><span class="analisis-summary-titulo"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 16V9M10 16V4M17 16V7"/></svg>Explorar análisis</span><span class="analisis-summary-datos">Victoria · Historial · Métodos</span><svg class="analisis-flecha" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg></summary>${globalThis.analisisContenido(p)}</details>`;
  };
})();
