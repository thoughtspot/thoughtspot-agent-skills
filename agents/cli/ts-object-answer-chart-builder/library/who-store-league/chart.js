// Search: [sales] [store] [region] [date].monthly [date].'this year' [date].'last year'. YTD league with change, places moved and form; a part latest month is left out.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const U = (c) => c?.value?.() ?? c?.value ?? c, MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js', MON = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ');
const derive = (d) => {
  if (!d?.data?.length) return {};
  const [St, D, V] = [/store/i, /month|date/i, /sales/i].map((re) => d.schema.findIndex((c) => re.test(c.name))), S = {}, T = {};
  d.data.forEach((r) => { const t = Number(U(r[D])), x = new Date(t < 1e11 ? t * 1000 : t), m = x.getUTCFullYear() * 12 + x.getUTCMonth(), v = Number(U(r[V])) || 0, o = (S[U(r[St])] ??= {}); o[m] = (o[m] ?? 0) + v; T[m] = (T[m] ?? 0) + v; });
  const keys = Object.keys(T).map(Number).sort((a, b) => a - b), p3 = keys.slice(-4, -1).map((m) => T[m]).sort((a, b) => a - b);
  const partial = p3.length >= 2 && T[keys[keys.length - 1]] < 0.6 * p3[p3.length >> 1], full = partial ? keys.slice(0, -1) : keys, last = full[full.length - 1], Y = Math.floor(last / 12), M = last % 12, F = Math.min(...full.filter((m) => Math.floor(m / 12) === Y).map((m) => m % 12)), fk = full.slice(-5);
  const sum = (o, y) => Object.keys(o).reduce((a, m) => a + (Math.floor(m / 12) === y && m % 12 >= F && m % 12 <= M ? o[m] : 0), 0);
  const all = Object.entries(S).map(([n, o]) => ({ n, o, ty: sum(o, Y), ly: sum(o, Y - 1) })).sort((a, b) => b.ty - a.ty), ly = [...all].sort((a, b) => b.ly - a.ly), has = all.some((s) => s.ly);
  all.forEach((s, i) => { s.mv = s.ly ? ly.indexOf(s) - i : null; s.ch = s.ly ? s.ty / s.ly - 1 : null; s.f = has ? fk.filter((m) => s.o[m - 12] && (s.o[m] ?? 0) > s.o[m - 12] * 1.0005).length : null; });
  const lead = all[0], up = all.filter((s) => s.mv > 0).sort((a, b) => b.mv - a.mv)[0], win = MON[F] + (M > F ? ' to ' + MON[M] : '') + ' ' + Y;
  return { nf: fk.length, table: { schema: [{ name: 'Store', type: 'dimension' }, ...['YTD', 'Change', 'Move', 'Form'].map((name) => ({ name, type: 'measure' }))], data: all.map((s) => [s.n, s.ty, s.ch, s.mv, s.f]) },
    subtitle: 'YTD: ' + win + (has ? ' against the same months of ' + (Y - 1) + '. Move: places gained on last year. Form: of the last ' + fk.length + ' months, how many beat a year earlier' : '; no last-year months, so change, move and form are blank') + (partial ? '. The latest month is partial and left out' : '') };
};
const go = () => { const d = derive(viz?.getDataFromSearchQuery?.()?.getData()); maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => d.table }) },
  { type: 'table', x: 'Store', y: ['YTD', 'Change', 'Move', 'Form'], select: true, subtitle: d.subtitle, titles: { YTD: 'YTD sales', Change: 'vs LY' },
    format: { YTD: { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 }, Change: { style: 'percent', maximumFractionDigits: 1, signDisplay: 'exceptZero' }, Move: { maximumFractionDigits: 0, signDisplay: 'exceptZero' }, Form: { maximumFractionDigits: 0, suffix: ' of ' + d.nf } },
    text: { noData: 'No rows yet: bind [sales] [store] [region] [date].monthly [date].\'this year\' [date].\'last year\'' } }); };
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6', crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
