// Сводка «до / после» по report.json обходов: node compare.js
const path = require('path');
const B = require(path.resolve(__dirname, '../before/report.json'));
const A = require(path.resolve(__dirname, '../after/report.json'));
const keys = ['hscroll', 'brokenImg', 'smallN', 'tinyN', 'noNameN', 'placeholderN', 'pluralN', 'truncN', 'errors', 'bad'];
const val = (a, k) => (Array.isArray(a[k]) ? a[k].length : a[k]);
const totals = {};
for (const prof of Object.keys(A.profiles)) {
  for (const [name, a] of Object.entries(A.profiles[prof].pages)) {
    const b = B.profiles[prof]?.pages[name] || {};
    const diff = [];
    for (const k of keys) {
      const vb = val(b, k), va = val(a, k);
      totals[k] = totals[k] || [0, 0];
      totals[k][0] += vb || 0; totals[k][1] += va || 0;
      if (vb !== va) diff.push(`${k} ${vb}→${va}`);
    }
    if (b.title !== a.title) diff.push(`title «${b.title}»→«${a.title}»`);
    if (b.finalUrl !== a.finalUrl) diff.push(`url ${b.finalUrl}→${a.finalUrl}`);
    if (a.csp && a.csp.length) diff.push('CSP: ' + a.csp.join(' | '));
    if (diff.length) console.log(prof, name, '|', diff.join('; '));
  }
}
console.log('\nИтого (до → после):', Object.entries(totals).map(([k, [b, a]]) => `${k} ${b}→${a}`).join(', '));
for (const prof of Object.keys(A.profiles)) {
  const docs = Object.entries(A.profiles[prof].pages).map(([n, a]) => `${n}:${a.status}`).join(' ');
  console.log('статусы после', prof, docs);
  console.log('внешние хосты после', prof, JSON.stringify(A.profiles[prof].external));
}
for (const [n, a] of Object.entries(A.profiles.m390.pages)) if (a.external && a.external.length) console.log('m390 внешние на', n, a.external.join(','));
