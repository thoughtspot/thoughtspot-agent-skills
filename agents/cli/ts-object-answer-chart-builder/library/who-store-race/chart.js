// Search: [sales] [store] [date].quarterly. Cumulative sales by store, one frame per quarter (bars re-rank as it builds); a part latest quarter is left out.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js'; const SRI = 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6';
const un = (c) => c?.value?.() ?? c?.value ?? c, ms = (v) => (v < 1e11 ? v * 1000 : v), qn = (t) => 'Q' + (Math.floor(new Date(t).getUTCMonth() / 3) + 1) + ' ' + new Date(t).getUTCFullYear(), money = { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 };
const derive = (d) => {
  if (!d?.data?.length) return { table: d };
  const ix = (re) => d.schema.findIndex((c) => re.test(c.name)), [s, t, v] = [/store/i, /quarter|date/i, /sales/i].map(ix), tot = new Map(), cell = new Map(), run = new Map();
  d.data.forEach((r) => { const k = ms(un(r[t])), x = Number(un(r[v])) || 0; tot.set(k, (tot.get(k) ?? 0) + x); cell.set(un(r[s]) + '|' + k, x); });
  const ks = [...tot.keys()].sort((a, b) => a - b), p3 = ks.slice(-4, -1).map((k) => tot.get(k)).sort((x, y) => x - y), keep = ks.length > 3 && tot.get(ks.at(-1)) < 0.6 * p3[1] ? ks.slice(0, -1) : ks, names = [...new Set(d.data.map((r) => un(r[s])))];
  return { first: keep[0], last: keep.at(-1), table: { schema: [{ name: 'store' }, { name: 'Quarter' }, { name: 'Cumulative' }, { name: 'Quarter sales' }], data: keep.flatMap((k) => names.map((n) => { const x = cell.get(n + '|' + k) ?? 0; run.set(n, (run.get(n) ?? 0) + x); return [n, qn(k), run.get(n), x]; })) } };
};
const go = () => { const d = derive(viz?.getDataFromSearchQuery?.()?.getData()); maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => d.table }) },
  { type: 'bar', horizontal: true, x: 'store', y: 'Cumulative', frame: 'Quarter', sort: 'desc', limit: 10, other: false, labels: true, select: 'multi', tooltip: { fields: ['Quarter sales'] }, subtitle: d.last ? '{max.x} leads with {max.y} since ' + qn(d.first) + ', through ' + qn(d.last) + '; Play replays the build' : '',
    titles: { store: 'Store', Cumulative: 'Cumulative sales' }, format: { Cumulative: money, 'Quarter sales': money }, text: { noData: 'No rows yet: bind [sales] [store] [date].quarterly' } }); };
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
