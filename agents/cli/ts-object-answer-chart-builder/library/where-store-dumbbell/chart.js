// Search: [sales] [store] [date].quarterly. Each store's sales this year against last, same quarters, up to the latest full quarter (a part quarter is left out).
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js'; const SRI = 'sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK';
const derive = (d, v = (c) => c?.value?.() ?? c?.value ?? c, ix = (re) => d?.schema.findIndex((c) => re.test(c.name)), S = ix(/store/i), Q = ix(/date|quarter/i), V = ix(/sales/i), k = (t) => t.getUTCFullYear() * 4 + Math.floor(t.getUTCMonth() / 3)) => {
  const rows = (d?.data ?? []).map((r) => ({ s: String(v(r[S])), t: new Date(v(r[Q])), y: Number(v(r[V])) })).filter((r) => isFinite(r.t) && isFinite(r.y)), tot = {};
  rows.forEach((r) => { tot[k(r.t)] = (tot[k(r.t)] || 0) + r.y; });
  const ks = Object.keys(tot).map(Number).sort((a, b) => a - b), p = ks.slice(-4, -1).map((x) => tot[x]).sort((a, b) => a - b);
  let last = ks[ks.length - 1]; if (p.length && tot[last] < 0.6 * p[Math.floor(p.length / 2)]) last = ks[ks.length - 2];
  const ly = Math.floor(last / 4), lq = last % 4, T = {}, win = rows.filter((r) => { const y = Math.floor(k(r.t) / 4); return (y === ly || y === ly - 1) && k(r.t) % 4 <= lq; });
  win.forEach((r) => { const o = (T[r.s] ??= { c: 0, p: 0 }); o[r.t.getUTCFullYear() === ly ? 'c' : 'p'] += r.y; });
  const keep = Object.keys(T).filter((s) => T[s].c > 0 && T[s].p > 0), up = keep.filter((s) => T[s].c >= T[s].p).length;
  return { n: keep.length, up, ly, lq, table: { schema: [{ name: 'store' }, { name: 'Year' }, d?.schema[V]], data: win.filter((r) => keep.includes(r.s)).sort((a, b) => a.t - b.t).map((r) => [r.s, String(r.t.getUTCFullYear()), r.y]) } };
};
const go = () => { const d = derive(viz?.getDataFromSearchQuery?.()?.getData()), n = d.n; maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => d.n ? d.table : undefined }) },
  { type: 'dumbbell', x: 'store', series: 'Year', y: 'Total sales', horizontal: true, zero: false, sort: 'change', select: 'multi', colors: { [d.ly - 1]: '#B4BDC9', [d.ly]: 'light-dark(#1E1E24, #E6EDF3)' },
    subtitle: n ? 'Q1' + (d.lq ? ' to Q' + (d.lq + 1) : '') + ' ' + d.ly + ' against ' + (d.ly - 1) + ', biggest gain first. Axis does not start at zero.' : '',
    titles: { store: 'Store', 'Total sales': 'Sales' }, format: { 'Total sales': { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 } }, text: { noData: 'No year-on-year rows yet: bind [sales] [store] [date].quarterly' } }); };
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
