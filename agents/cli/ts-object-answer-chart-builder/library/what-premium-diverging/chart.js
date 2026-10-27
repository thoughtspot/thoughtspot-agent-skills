// Search: [sales] [quantity purchased] [item type] [product]. Share of sales minus share of units per item type; click a bar to drill into products.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const u = (c) => c?.value?.() ?? c?.value ?? c; const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js'; const SRI = 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6';
const withGap = (d, ix = (re) => d.schema.findIndex((c) => re.test(c.name))) => {
  const rows = d.data.map((r) => r.map(u)), v = ix(/sales/i), q = ix(/quantity|units/i), S = rows.reduce((a, r) => a + r[v], 0), U = rows.reduce((a, r) => a + r[q], 0);
  return S && U ? { schema: [...d.schema, { name: 'Sales', type: 'measure' }, { name: 'Units', type: 'measure' }, { name: 'Gap', type: 'measure' }], data: rows.map((r) => [...r, r[v] / S, r[q] / U, 100 * (r[v] / S - r[q] / U)]) } : d;
};
const pct = { style: 'percent', maximumFractionDigits: 1 };
const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => { const d = viz?.getDataFromSearchQuery?.()?.getData(); return d?.data?.length ? withGap(d) : d; } }) },
  { type: 'bar', horizontal: true, path: ['item type', 'product'], drill: true, y: 'Gap', sort: 'desc', labels: true, colorBy: 'sign', tooltip: { fields: ['Sales', 'Units'] }, subtitle: 'Share of sales minus share of units. {max.x} leads at {max.y}.',
    format: { Gap: { maximumFractionDigits: 2, signDisplay: 'exceptZero', suffix: ' pts' }, Sales: pct, Units: pct }, titles: { Gap: 'Share of sales minus share of units', Sales: 'Share of sales', Units: 'Share of units', 'item type': 'Item type' },
    text: { positive: 'Premium', negative: 'Volume', noData: 'No rows yet: bind [sales] [quantity purchased] [item type] [product]' } });
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
