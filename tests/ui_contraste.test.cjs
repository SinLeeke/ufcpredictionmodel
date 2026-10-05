const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Contraste AA (>= 4,5:1, WCAG 2.x) de los textos de 11-13 px del consenso del
// mercado: la etiqueta .cons-etq y la línea .cab-mercado. Los valores salen de
// style.css y no se copian aquí, así que si alguien cambia un token o el color
// de un selector sin mirar el contraste, esta prueba lo caza.
const css = fs.readFileSync(path.join(__dirname, '../webui/static/style.css'), 'utf8');

// Cuerpo de la regla cuyo selector es EXACTAMENTE `sel` (llaves balanceadas).
function bloque(sel, desde = 0) {
  const re = new RegExp('(^|[}\\s])' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{', 'g');
  re.lastIndex = desde;
  const m = re.exec(css);
  assert.ok(m, `no encuentro la regla ${sel}`);
  const ini = m.index + m[0].length;
  let nivel = 1, i = ini;
  while (nivel && i < css.length) { if (css[i] === '{') nivel++; else if (css[i] === '}') nivel--; i++; }
  return css.slice(ini, i - 1);
}
function tokens(cuerpo) {
  const t = {};
  for (const m of cuerpo.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b/g)) t[m[1]] = m[2];
  return t;
}

// Los cuatro temas reales: base claro/oscuro y el estilo "juez" encima de cada uno.
const claro = tokens(bloque(':root'));
const oscuro = tokens(bloque(':root[data-tema="oscuro"]'));
const juezClaro = { ...claro, ...tokens(bloque(':root[data-estilo="juez"]')) };
const juezOscuro = { ...oscuro, ...tokens(bloque(':root[data-estilo="juez"][data-tema="oscuro"]')) };
// Sin atributo, el oscuro llega por prefers-color-scheme: tiene que ser el mismo.
const oscuroMedia = tokens(bloque(':root:not([data-tema="claro"])', css.indexOf('@media (prefers-color-scheme: dark)')));
const TEMAS = { claro, oscuro, 'juez claro': juezClaro, 'juez oscuro': juezOscuro };

const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const hex = c => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
// color-mix(in srgb, a p%, b)
const mezcla = (a, p, b) => hex(rgb(a).map((v, i) => v * p + rgb(b)[i] * (1 - p)));
const lum = h => {
  const [r, g, b] = rgb(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contraste = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// Fondos reales: página, tarjeta, fila de tabla al pasar el mouse, cabecera de
// combate con hover (.combate-cab:hover) y cabecera de título (5% de tinta).
const fondos = t => ({
  bg: t.bg, sup: t.sup, sup2: t.sup2,
  'cab:hover': mezcla(t.sup2, 0.4, t.sup),
  'cab titulo': mezcla(t.txt, 0.05, t.sup),
});

// Cada selector con el token de color que declara su regla en style.css.
const SELECTORES = [
  '.cons-etq[data-etq="favorito"]', '.cons-etq[data-etq="underdog"]', '.cons-etq[data-etq="pareja"]',
  '.cab-mercado', '.cab-mercado .cons-rot', '.cab-mercado b', '.cab-mercado .cons-vacio',
];
function tokenDe(sel) {
  const cuerpo = bloque(sel);
  const m = cuerpo.match(/(?:^|;)\s*color\s*:\s*var\(--([\w-]+)\)/);
  assert.ok(m, `${sel} no declara color con var(--token)`);
  return m[1];
}

test('el oscuro por prefers-color-scheme usa los mismos valores que data-tema="oscuro"', () => {
  for (const k of ['bg', 'sup', 'sup2', 'txt', 'txt2', 'tenue']) assert.equal(oscuroMedia[k], oscuro[k], k);
});

for (const [tema, t] of Object.entries(TEMAS)) {
  test(`contraste AA en ${tema}`, () => {
    for (const sel of SELECTORES) {
      const tok = tokenDe(sel);
      assert.ok(t[tok], `${tok} no existe en ${tema}`);
      for (const [nombre, fondo] of Object.entries(fondos(t))) {
        const c = contraste(t[tok], fondo);
        assert.ok(c >= 4.5, `${tema}: ${sel} (--${tok} ${t[tok]}) sobre ${nombre} ${fondo} = ${c.toFixed(2)}:1`);
      }
    }
  });
}
