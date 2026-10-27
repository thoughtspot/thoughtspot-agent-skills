// Search: [sales] [date].monthly. Cumulative sales by month, one line per year; click a line or legend key to pick a year.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const u = (v) => v?.value?.() ?? v?.value ?? v, T = (v) => (u(v) < 1e11 ? u(v) * 1000 : u(v)), MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const cumulative = (d, i = d.schema.findIndex((c) => /date|month/i.test(c.name ?? c)), j = d.schema.findIndex((c) => /sales/i.test(c.name ?? c)), by = {}) => {
  d.data.forEach((r) => { const t = new Date(T(r[i])); (by[t.getUTCFullYear()] ??= [])[t.getUTCMonth()] = (by[t.getUTCFullYear()]?.[t.getUTCMonth()] ?? 0) + u(r[j]); });
  const ys = Object.keys(by).sort().filter((y) => by[y].filter((v) => v != null).length >= 3), cum = {}; ys.forEach((y) => { let c = 0; cum[y] = MON.map((m, k) => (by[y][k] == null ? null : (c += by[y][k]))); });
  return { schema: [{ name: 'Month' }, { name: 'Year' }, { name: 'Sales' }], data: MON.flatMap((m, k) => ys.filter((y) => k === 0 || cum[y][k] != null).map((y) => [m, y, cum[y][k]])) };
};
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js'; const SRI = 'sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK';
const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => { const d = viz?.getDataFromSearchQuery?.()?.getData(); return d && cumulative(d); } }) },
  { type: 'line', x: 'Month', y: 'Sales', series: 'Year', xType: 'category', select: true, subtitle: 'Cumulative sales by month, one line per year', titles: { Sales: 'Sales to date' },
    format: { Sales: { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 0 } }, text: { noData: 'No rows yet. Bind [sales] [date].monthly' } });
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
