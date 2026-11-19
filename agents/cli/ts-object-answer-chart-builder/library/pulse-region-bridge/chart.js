// Search: [sales] [region] [state] [date].quarterly. Year to date bridge: last year's quarters to this year's, one step per region. A part quarter (under half the one before) is dropped.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const u = (v) => v?.value?.() ?? v?.value ?? v, T = (v) => (u(v) < 1e11 ? u(v) * 1000 : u(v));
const bridge = (d, f = (re) => d.schema.findIndex((c) => re.test(c.name ?? c)), [g, t, v] = [f(/region/i), f(/date|quarter/i), f(/sales/i)], q = new Map(), s = (m, k, x) => m.set(k, (m.get(k) ?? 0) + x)) => {
  d.data.forEach((r) => s(q, T(r[t]), u(r[v]))); const ts = [...q.keys()].sort((a, b) => a - b), n = ts.length, part = n > 1 && q.get(ts[n - 1]) < q.get(ts[n - 2]) / 2, L = new Date(ts[n - (part ? 2 : 1)]), Y = L.getUTCFullYear(), Q = Math.floor(L.getUTCMonth() / 3), by = new Map(); let a = 0, b = 0;
  d.data.forEach((r) => { const D = new Date(T(r[t])), y = D.getUTCFullYear(), x = u(r[v]); if (Math.floor(D.getUTCMonth() / 3) > Q || (y !== Y && y !== Y - 1) || (y === Y && D > L)) return; s(by, u(r[g]), y === Y ? x : -x); y === Y ? (a += x) : (b += x); });
  const lab = (y) => 'Q1' + (Q ? '-Q' + (Q + 1) : '') + ' ' + y;
  return { schema: [{ name: 'Step' }, { name: 'Change' }], data: a && b ? [[lab(Y - 1), b], ...[...by].sort((x, y) => y[1] - x[1]), [lab(Y), 0]] : [] };
};
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js'; const SRI = 'sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK';
const raw = viz?.getDataFromSearchQuery?.()?.getData(), r = raw && bridge(raw), e = r?.data ?? [], k = e.length - 1, pct = e.length ? e.slice(1, k).reduce((a, x) => a + x[1], 0) / e[0][1] : 0;
const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => r }) },
  { type: 'waterfall', x: 'Step', y: 'Change', totals: e.length ? [e[0][0], e[k][0]] : [], select: 'multi', labels: true, subtitle: e.length ? e[k][0] + ' against ' + e[0][0] + ', by region. Axis does not start at zero.' : '', titles: { Step: 'Region', Change: 'Sales' },
    format: { Change: { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 } }, text: { noData: 'No year-on-year rows. Bind [sales] [region] [state] [date].quarterly' } });
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
