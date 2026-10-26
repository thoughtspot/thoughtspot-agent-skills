// Search: [sales] [quantity purchased] [date].monthly. Every month as a dot; the latest month is the dark dot and the dashed line, grouped above/below it.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const v = (c) => c?.value?.() ?? c?.value ?? c, ms = (t) => (t < 1e11 ? t * 1000 : t), USD = { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 };
const lab = (t) => new Date(t).toLocaleString('en', { month: 'short', year: 'numeric', timeZone: 'UTC' }), ord = (n) => n + (['th', 'st', 'nd', 'rd'][(n % 100 - 20) % 10] || ['th', 'st', 'nd', 'rd'][n % 100] || 'th');
const withGroup = (d, i = d.schema.findIndex((c) => /month|date/i.test(c.name)), j = d.schema.findIndex((c) => /sales/i.test(c.name)), M = d.data.map((r) => [ms(+v(r[i])), +v(r[j])])) => {
  if (!M.length) return d;
  const L = M.reduce((a, r) => (r[0] > a[0] ? r : a), M[0]), above = M.filter((r) => r[1] > L[1]).length;
  Object.assign(S, { subtitle: new Intl.NumberFormat('en', USD).format(L[1]) + '; ' + above + ' month' + (above === 1 ? '' : 's') + ' sit above the dashed line', rules: [{ y: L[1], label: 'Latest' }] });
  return { schema: ['Month', 'Sales', 'Label', 'Group'].map((name) => ({ name })), data: M.map((r) => [r[0], r[1], lab(r[0]), r === L ? 'Latest month' : r[1] > L[1] ? 'Above it' : 'Below it']) };
};
const S = { type: 'scatter', x: 'Month', y: 'Sales', series: 'Group', name: 'Label', select: true, legend: 'bottom', format: { Sales: USD, Month: { month: 'short', year: 'numeric', timeZone: 'UTC' } }, colors: { 'Latest month': 'light-dark(#1E1E24, #E6EDF3)', 'Above it': '#6A7891', 'Below it': '#B4BDC9' }, text: { noData: 'No rows yet. Bind [sales] [quantity purchased] [date].monthly' } };
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js'; const SRI = 'sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK';
const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => { const d = viz?.getDataFromSearchQuery?.()?.getData(); return d && withGroup(d); } }) }, S);
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
