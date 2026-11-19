/**
 * Available Columns:
 * "Warehouse State"        // ATTRIBUTE (US state code or full name)
 * "Total Quantity On Hand" // MEASURE
 * --- END ---
 *
 * Chart: US state hex tile cartogram. One hex per state at a fixed
 * pseudo-geographic position. Color encodes the measure. States missing
 * from the data render dim gray. No basemap, no projection, no d3 —
 * the layout is a hardcoded grid.
 */

// ── Column Name Constants ──
const COL_STATE = 'Warehouse State';
const COL_VALUE = 'Total Quantity On Hand';

// ── Color stops (light → dark, blue ramp matching the sample image) ──
const COLOR_STOPS = [
  '#eef5fc', '#bcd9f0', '#73aed9', '#2f7dbf', '#0b4f9c', '#08306b',
];

// Color used for states absent from the data.
const MISSING_FILL = '#f1f3f5';
const MISSING_STROKE = 'rgba(0,0,0,0.06)';

// ── Sample dataset for standalone preview (uncomment to use) ──
// const SAMPLE = {
//   schema: [
//     { name: COL_STATE, type: 'ATTRIBUTE' },
//     { name: COL_VALUE, type: 'MEASURE' },
//   ],
//   data: [
//     ['NJ', 4.57], ['NY', 3.88], ['AZ', 4.14], ['MA', 4.19], ['NV', 4.42],
//     ['WY', 3.37], ['IA', 4.03], ['NH', 3.60], ['GA', 4.48], ['WV', 3.96],
//     ['AR', 4.15], ['FL', 4.92], ['TX', 3.78],
//   ],
// };

// ── US tile-grid layout: state -> [col, row] (row 0 = north) ──
// Pointy-top hex grid with odd-row horizontal offset of 0.5*W.
const GRID = {
  AK:[0,0], ME:[10,0],
  VT:[9,1], NH:[10,1],
  WA:[0,2], ID:[1,2], MT:[2,2], ND:[3,2], MN:[4,2], WI:[5,2], MI:[6,2], NY:[8,2], MA:[9,2], RI:[10,2],
  OR:[0,3], NV:[1,3], WY:[2,3], SD:[3,3], IA:[4,3], IL:[5,3], IN:[6,3], OH:[7,3], PA:[8,3], NJ:[9,3], CT:[10,3],
  CA:[0,4], UT:[1,4], CO:[2,4], NE:[3,4], MO:[4,4], KY:[5,4], WV:[6,4], VA:[7,4], MD:[8,4], DE:[9,4],
  AZ:[1,5], NM:[2,5], KS:[3,5], AR:[4,5], TN:[5,5], NC:[6,5], SC:[7,5], DC:[8,5],
  OK:[3,6], LA:[4,6], MS:[5,6], AL:[6,6], GA:[7,6],
  HI:[0,7], TX:[3,7], FL:[7,7],
};

const STATE_NAMES = {
  AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',CO:'Colorado',
  CT:'Connecticut',DE:'Delaware',FL:'Florida',GA:'Georgia',HI:'Hawaii',ID:'Idaho',
  IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',KY:'Kentucky',LA:'Louisiana',
  ME:'Maine',MD:'Maryland',MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',
  MS:'Mississippi',MO:'Missouri',MT:'Montana',NE:'Nebraska',NV:'Nevada',
  NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',NY:'New York',NC:'North Carolina',
  ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',
  RI:'Rhode Island',SC:'South Carolina',SD:'South Dakota',TN:'Tennessee',TX:'Texas',
  UT:'Utah',VT:'Vermont',VA:'Virginia',WA:'Washington',WV:'West Virginia',
  WI:'Wisconsin',WY:'Wyoming',DC:'D.C.',
};
// Reverse lookup: full name (lowercased) -> code, for tolerant input parsing.
const NAME_TO_CODE = Object.fromEntries(
  Object.entries(STATE_NAMES).map(([code, name]) => [name.toLowerCase(), code])
);

// ── Data read / shaping ──
function readData() {
  try {
    if (typeof viz !== 'undefined' && viz?.getDataFromSearchQuery) {
      const dm = viz.getDataFromSearchQuery();
      const { schema, data } = dm.getData();
      return { schema, data };
    }
  } catch (e) {
    console.warn('[hex-cartogram] viz read failed:', e);
  }
  if (typeof SAMPLE !== 'undefined') return SAMPLE;
  return { schema: [], data: [] };
}

function resolveCol(schema, exact, ...fuzzyKeywords) {
  let i = schema.findIndex(c => c.name === exact);
  if (i >= 0) return i;
  const low = exact.toLowerCase();
  i = schema.findIndex(c => c.name.toLowerCase() === low);
  if (i >= 0) return i;
  for (const kw of fuzzyKeywords) {
    const re = new RegExp(kw, 'i');
    i = schema.findIndex(c => re.test(c.name));
    if (i >= 0) return i;
  }
  return -1;
}

function normalizeStateCode(raw) {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const upper = s.toUpperCase();
  if (GRID[upper]) return upper;
  const named = NAME_TO_CODE[s.toLowerCase()];
  return named || null;
}

function toRows({ schema, data }) {
  const iS = resolveCol(schema, COL_STATE, 'state', 'region', 'warehouse');
  const iV = resolveCol(schema, COL_VALUE, 'quantity.*on.*hand', 'qoh', 'quantity', 'total', '^value$');

  console.log('[hex-cartogram] schema columns:', schema.map(c => c.name));
  console.log('[hex-cartogram] resolved indexes:', { iS, iV });

  // Map of state code -> aggregated value (sum across duplicates).
  const byState = new Map();
  for (const r of data) {
    const code = iS >= 0 ? normalizeStateCode(r[iS]) : null;
    if (!code) continue;
    const v = iV >= 0 ? Number(r[iV]) : NaN;
    if (!Number.isFinite(v)) continue;
    byState.set(code, (byState.get(code) || 0) + v);
  }
  return byState;
}

// ── Value formatting ──
function formatValue(v) {
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  if (abs >= 100) return v.toFixed(0);
  if (abs >= 10)  return v.toFixed(1);
  return v.toFixed(2);
}

// ── Color helpers ──
function hexToRgb(h) {
  return [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ];
}
function rampColor(t, stops) {
  t = Math.max(0, Math.min(1, t));
  const seg = stops.length - 1;
  const pos = t * seg;
  const i = Math.min(Math.floor(pos), seg - 1);
  const f = pos - i;
  const a = hexToRgb(stops[i]);
  const b = hexToRgb(stops[i + 1]);
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}
function luminance(rgb) {
  const m = rgb.match(/\d+/g).map(Number);
  return (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255;
}

// ── Hex geometry (pointy-top) ──
function hexPoints(cx, cy, r) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 180) * (60 * i - 30);
    pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`);
  }
  return pts.join(' ');
}

// ── State ──
const raw = readData();
const VALUES = toRows(raw);
const valueArray = Array.from(VALUES.values());
const HAS_DATA = valueArray.length > 0;
const MIN = HAS_DATA ? Math.min(...valueArray) : 0;
const MAX = HAS_DATA ? Math.max(...valueArray) : 1;

const svg = document.getElementById('hex');
const tipEl = document.getElementById('tip');
const mapWrap = document.querySelector('.map-wrap');
const bar = document.getElementById('bar');
const lmin = document.getElementById('lmin');
const lmax = document.getElementById('lmax');

let didAnimate = false;
let resizeRaf = 0;

function colorFor(value) {
  if (!HAS_DATA || MAX === MIN) return rampColor(0.5, COLOR_STOPS);
  return rampColor((value - MIN) / (MAX - MIN), COLOR_STOPS);
}

function paintLegend() {
  bar.style.background = `linear-gradient(90deg, ${COLOR_STOPS.join(',')})`;
  if (!HAS_DATA) {
    lmin.textContent = '—';
    lmax.textContent = '—';
    return;
  }
  lmin.textContent = formatValue(MIN);
  lmax.textContent = formatValue(MAX);
}

function renderEmpty() {
  svg.innerHTML = '';
  const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  txt.setAttribute('x', '50%');
  txt.setAttribute('y', '50%');
  txt.setAttribute('text-anchor', 'middle');
  txt.setAttribute('dominant-baseline', 'middle');
  txt.setAttribute('fill', '#9ca3af');
  txt.setAttribute('font-family', 'Inter, system-ui, sans-serif');
  txt.setAttribute('font-size', '13');
  txt.setAttribute('letter-spacing', '0.06em');
  txt.textContent = 'NO DATA TO DISPLAY';
  svg.appendChild(txt);
}

function render() {
  if (!mapWrap) return;
  const rect = mapWrap.getBoundingClientRect();
  const Wpx = Math.max(rect.width || 0, 200);
  const Hpx = Math.max(rect.height || 0, 200);

  // Compute the grid extents in "unit hex" coordinates so we can scale R
  // to fit the container — this is what makes the chart responsive.
  // For pointy-top hexes: each column step = W = sqrt(3)*R, row step = 1.5*R.
  // Odd rows shift right by 0.5*W.
  const PAD = 14;
  let cMax = 0, rMax = 0;
  for (const [, [col, row]] of Object.entries(GRID)) {
    if (col > cMax) cMax = col;
    if (row > rMax) rMax = row;
  }
  // Width-bounded R: total width = (cMax + 1 + 0.5) * W + 2*PAD  (the +0.5 is the odd-row offset)
  // Height-bounded R: total height = rMax*1.5*R + 2*R + 2*PAD
  const Rw = (Wpx - 2 * PAD) / ((cMax + 1.5) * Math.sqrt(3));
  const Rh = (Hpx - 2 * PAD) / (rMax * 1.5 + 2);
  const R = Math.max(8, Math.min(Rw, Rh));
  const W = Math.sqrt(3) * R;

  const cells = [];
  let maxX = 0, maxY = 0;
  for (const [code, [col, row]] of Object.entries(GRID)) {
    const cx = PAD + (col + (row % 2) * 0.5) * W + W / 2;
    const cy = PAD + row * 1.5 * R + R;
    cells.push({ code, cx, cy });
    if (cx + W / 2 > maxX) maxX = cx + W / 2;
    if (cy + R > maxY) maxY = cy + R;
  }
  const vbW = maxX + PAD;
  const vbH = maxY + PAD;

  svg.setAttribute('viewBox', `0 0 ${vbW} ${vbH}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.innerHTML = '';

  // Font sizing scales with R but caps reasonably so big screens don't
  // produce comically huge state labels.
  const labelFS = Math.max(9, Math.min(15, R * 0.42));
  const valueFS = Math.max(7, Math.min(11, R * 0.32));

  for (const { code, cx, cy } of cells) {
    const v = VALUES.get(code);
    const present = v !== undefined;
    const fill = present ? colorFor(v) : MISSING_FILL;
    const stroke = present ? '#ffffff' : MISSING_STROKE;
    const textColor = present
      ? (luminance(fill) > 0.6 ? '#1f2937' : '#ffffff')
      : '#9ca3af';

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', 'hexcell');
    g.dataset.code = code;
    g.dataset.value = present ? String(v) : '';
    g.dataset.present = present ? '1' : '0';

    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', hexPoints(cx, cy, R));
    poly.setAttribute('fill', fill);
    poly.setAttribute('stroke', stroke);
    poly.setAttribute('stroke-width', present ? '1' : '1');
    poly.setAttribute('class', 'hex');
    g.appendChild(poly);

    const lab = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lab.setAttribute('x', String(cx));
    lab.setAttribute('y', String(cy - R * 0.05));
    lab.setAttribute('text-anchor', 'middle');
    lab.setAttribute('class', 'lab');
    lab.setAttribute('font-size', String(labelFS));
    lab.setAttribute('fill', textColor);
    lab.textContent = code;
    g.appendChild(lab);

    if (present) {
      const val = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      val.setAttribute('x', String(cx));
      val.setAttribute('y', String(cy + R * 0.42));
      val.setAttribute('text-anchor', 'middle');
      val.setAttribute('class', 'val');
      val.setAttribute('font-size', String(valueFS));
      val.setAttribute('fill', textColor);
      val.textContent = formatValue(v);
      g.appendChild(val);
    }

    svg.appendChild(g);
  }

  wireTooltips();
}

function wireTooltips() {
  svg.querySelectorAll('.hexcell').forEach(g => {
    g.addEventListener('mousemove', e => {
      const code = g.dataset.code;
      const present = g.dataset.present === '1';
      const rect = mapWrap.getBoundingClientRect();
      const name = STATE_NAMES[code] || code;
      if (present) {
        const v = Number(g.dataset.value);
        tipEl.innerHTML =
          `<span class="tip-name">${name}</span>` +
          `<span class="tip-val">${formatValue(v)}</span>`;
      } else {
        tipEl.innerHTML =
          `<span class="tip-name">${name}</span>` +
          `<span class="tip-tag">no data</span>`;
      }
      tipEl.style.left = (e.clientX - rect.left) + 'px';
      tipEl.style.top  = (e.clientY - rect.top)  + 'px';
      tipEl.style.opacity = '1';
    });
    g.addEventListener('mouseleave', () => {
      tipEl.style.opacity = '0';
    });
  });
}

// ── Boot ──
paintLegend();

if (!HAS_DATA) {
  renderEmpty();
} else {
  render();
}

// Trigger the entrance animation once, after the first paint.
requestAnimationFrame(() => {
  if (didAnimate) return;
  didAnimate = true;
  svg.classList.add('is-loaded');
});

// Re-fit on container resize. Coalesce via rAF so rapid resize events don't
// thrash. The animation class is already applied so we don't replay it here.
if (typeof ResizeObserver !== 'undefined' && mapWrap) {
  const ro = new ResizeObserver(() => {
    if (!HAS_DATA) return;
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(render);
  });
  ro.observe(mapWrap);
}

// ── Signal TS render-complete (no-op when not in TS) ──
try { viz.events.emitRenderCompletedEvent(); } catch {}
