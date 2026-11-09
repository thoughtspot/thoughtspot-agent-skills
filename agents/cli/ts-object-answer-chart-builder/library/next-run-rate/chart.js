// Search: [sales] [date].monthly. Actual sales, then the rest of the year two ways (same months as last year; last 3 full months carried on). A part month (the current one) is not counted as actual: it is projected in full.
document.getElementById('chart')?.style.setProperty('color-scheme', (([r, g, b]) => r * .299 + g * .587 + b * .114 > 140)(getComputedStyle(document.body).color.match(/\d+/g)) ? 'dark' : 'light');
const v = (c) => c?.value?.() ?? c?.value ?? c, ms = (t) => (t < 1e11 ? t * 1000 : t), A = 'Same months as last year', B = 'Last 3 months carried on', at = (y, m) => Date.UTC(y, m, 1);
const $ = (x) => new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }).format(x), pc = (x, s = (x * 100).toFixed(1)) => (+s < 0 ? '' : '+') + s.replace('-0.0', '0.0') + '%', mon = (m) => new Date(at(2000, m)).toLocaleString('en', { month: 'short', timeZone: 'UTC' });
const withScenarios = (d, i = d.schema.findIndex((c) => /date|month/i.test(c.name)), j = d.schema.findIndex((c) => /sales/i.test(c.name)), now = new Date()) => {
  const cm = at(now.getUTCFullYear(), now.getUTCMonth()), all = d.data.map((r) => [ms(+v(r[i])), +v(r[j])]), M = all.filter((r) => r[0] < cm), partV = all.find((r) => r[0] === cm)?.[1], get = new Map(M), g = (y, m) => get.get(at(y, m));
  if (!M.length) return d;
  const last = new Date(Math.max(...M.map((r) => r[0]))), ly = last.getUTCFullYear(), lm = last.getUTCMonth(), T = lm === 11 ? ly + 1 : ly, a3 = M.slice(-3).reduce((s, r) => s + r[1], 0) / 3, pts = [];
  let ytd = 0, ytdP = 0, tA = 0, tB = 0;
  for (let m = 0; m < 12; m++) {
    const act = lm < 11 && m <= lm ? g(T, m) : undefined, prev = g(T - 1, m), a = prev ?? a3;
    if (act != null) { ytd += act; ytdP += prev ?? 0; pts.push(['Actual', act, m]); if (m === lm) pts.push([A, act, m], [B, act, m]); } else { tA += a; tB += a3; pts.push([A, a, m], [B, a3, m]); }
  }
  const py = Array.from({ length: 12 }, (_, m) => g(T - 1, m)), P = py.every((x) => x != null) ? py.reduce((s, x) => s + x, 0) : 0;
  Object.assign(S, { rules: [{ x: at(T, lm), label: 'Projected from here' }], subtitle: (lm < 11 ? 'Actual through ' + mon(lm) + ': ' + $(ytd) + (ytdP ? ', ' + pc(ytd / ytdP - 1) + ' on ' + (T - 1) : '') + '. ' : '') + (partV != null ? mon((lm + 1) % 12) + ' has ' + $(partV) + ' so far (part month), so it is projected in full. ' : '') + (P ? $(P) + ' in all of ' + (T - 1) + ', the scenarios ' + pc((tA + ytd) / P - 1) + ' and ' + pc((tB + ytd) / P - 1) + ' on it. ' : '') + 'A projection, not a forecast.' });
  return { schema: ['Scenario', 'Sales', 'Month'].map((name) => ({ name })), data: pts.map(([s, x, m]) => [s, x, at(T, m)]) };
};
const S = { type: 'line', x: 'Month', y: 'Sales', series: 'Scenario', xType: 'time', zoom: true, dash: [A, B], format: { Sales: { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }, Month: 'month' }, colors: { Actual: 'light-dark(#1E1E24, #E6EDF3)', [A]: '#4A5872', [B]: '#8E9AAB' }, text: { noData: 'No rows yet. Bind [sales] [date].monthly' } };
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.global.js'; const SRI = 'sha384-Z7INdXfgP1H/WUINrm44nlLrtN58MLpFXLi52fr7HiGOGg/J4FAvjgXQM2Wnd9AK';
const go = () => maya.host.thoughtspot({ events: viz?.events, getDataFromSearchQuery: () => ({ getData: () => { const d = viz?.getDataFromSearchQuery?.()?.getData(); return d && withScenarios(d); } }) }, S);
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
