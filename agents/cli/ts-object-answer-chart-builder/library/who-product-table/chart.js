// Search: [product] [item type] [sales] [quantity purchased]. Products ranked by sales; price per unit and its gap to the item type average.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const U = (c) => c?.value?.() ?? c?.value ?? c, N = (c) => Number(U(c)) || 0;
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js'; const SRI = 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6';
const derive = (d) => {
  if (!d?.data?.length) return {};
  const [p, t, s, q] = [/product/i, /item/i, /sales/i, /quantity|units/i].map((re) => d.schema.findIndex((c) => re.test(c.name))), ty = {};
  d.data.forEach((r) => { const o = (ty[U(r[t])] ??= [0, 0]); o[0] += N(r[s]); o[1] += N(r[q]); });
  const rows = d.data.map((r) => { const u = N(r[q]), pr = u ? N(r[s]) / u : null, o = ty[U(r[t])], avg = o[1] ? o[0] / o[1] : 0; return [U(r[p]) + ' (' + U(r[t]) + ')', N(r[s]), u, pr, pr != null && avg ? pr / avg - 1 : null]; }).sort((a, b) => b[1] - a[1]);
  const tot = rows.reduce((a, r) => a + r[1], 0), top = rows.slice(0, 25).reduce((a, r) => a + r[1], 0) / tot, m = (v) => '$' + (v / 1e6).toFixed(1) + 'M';
  return { table: { schema: [{ name: 'Product', type: 'dimension' }, ...['Sales', 'Units', 'Price', 'Vs type'].map((name) => ({ name, type: 'measure' }))], data: rows },
    subtitle: rows.length > 25 ? 'The top 25 of ' + rows.length + ' products hold ' + Math.round(top * 100) + '%. Avg price is sales per unit; vs type compares it with the item type average' : '' };
};
const go = () => { const d = derive(viz?.getDataFromSearchQuery?.()?.getData()); maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => d.table }) },
  { type: 'table', x: 'Product', y: ['Sales', 'Units', 'Price', 'Vs type'], sort: 'desc', select: true, subtitle: d.subtitle, titles: { Product: 'Product (item type)', Price: 'Avg price', 'Vs type': 'vs type' },
    format: { Sales: { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }, Units: { notation: 'compact', maximumFractionDigits: 1 }, Price: { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }, 'Vs type': { style: 'percent', maximumFractionDigits: 0, signDisplay: 'exceptZero' } },
    text: { noData: 'No rows yet: bind [product] [item type] [sales] [quantity purchased]' } }); };
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
