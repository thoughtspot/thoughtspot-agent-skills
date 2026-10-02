// Smoke fixture: a mode-C raw-SVG bar chart. It exercises what the preview
// checks — live data, sample fallback, wrapped cells, zero rows, a container
// resize (ResizeObserver) and emitRenderCompletedEvent — with no CDN and no Muze.
const REGION = 'REGION';
const REVENUE = 'REVENUE';

function getViz() {
  try { if (typeof viz !== 'undefined' && viz) return viz; } catch (e) {}
  return null;
}
const viz_ = getViz() || {};

const SAMPLE_DATA = [
  { REGION: 'North', REVENUE: 500 }, { REGION: 'South', REVENUE: 300 },
];

const cellVal = (c) => (c && typeof c === 'object' && typeof c.value === 'function' ? c.value() : c);

function loadRows() {
  try {
    const raw = viz_.getDataFromSearchQuery && viz_.getDataFromSearchQuery().getData();
    if (raw && raw.data && raw.data.length) {
      return { source: 'live', rows: raw.data.map((arr) => {
        const o = {};
        raw.schema.forEach((c, i) => { o[c.name] = cellVal(arr[i]); });
        return o;
      }) };
    }
  } catch (err) { console.warn('[chart] live data unavailable:', err); }
  return { source: 'sample', rows: SAMPLE_DATA };
}

const { source, rows } = loadRows();
const el = document.getElementById('chart') || document.body.appendChild(Object.assign(document.createElement('div'), { id: 'chart' }));
if (source === 'sample') el.classList.add('is-sample');

function draw() {
  const W = el.clientWidth, H = el.clientHeight, pad = 32;
  const max = Math.max(1, ...rows.map((r) => Number(r[REVENUE]) || 0));
  const bw = (W - pad * 2) / Math.max(1, rows.length);
  const bars = rows.map((r, i) => {
    const h = ((Number(r[REVENUE]) || 0) / max) * (H - pad * 2);
    const x = pad + i * bw + bw * 0.15, y = H - pad - h;
    return `<rect x="${x}" y="${y}" width="${bw * 0.7}" height="${h}" fill="#2770ef"/>` +
           `<text x="${x + bw * 0.35}" y="${H - pad + 16}" text-anchor="middle" fill="#555">${r[REGION]}</text>`;
  }).join('');
  el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${bars}</svg>`;
}

draw();
new ResizeObserver(draw).observe(el);
viz_.events && viz_.events.emitRenderCompletedEvent();
