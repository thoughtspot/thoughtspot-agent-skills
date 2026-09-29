/**
 * Available Columns:
 * "Unit Type"                // ATTRIBUTE
 * "Total Staffed Beds"       // MEASURE
 * "Total Occupied Beds"      // MEASURE
 * "Total Available Beds"     // MEASURE
 * "Bed Occupancy Rate"       // MEASURE
 * "Total Flex Beds Open"     // MEASURE
 * --- END ---
 */

// ── Column name constants ──
const COL_UNIT       = 'Unit Type';
const COL_STAFFED    = 'Total Staffed Beds';
const COL_OCCUPIED   = 'Total Occupied Beds';
const COL_AVAILABLE  = 'Total Available Beds';
const COL_RATE       = 'Bed Occupancy Rate';

// Deterministic colors for known unit types.
// Unknown units fall back to PALETTE (the same colors, cycled).
const UNIT_COLORS = {
  'ED':                '#F19BA4',
  'ICU':               '#F47E89',
  'L&D':               '#C9B5F8',
  'Med/Surg':          '#B094F8',
  'Ortho':             '#8C62F5',
  'Outpatient Clinic': '#6A4ABA',
  'Telemetry':         '#422E75',
};
const PALETTE = [
  '#F19BA4', '#F47E89', '#C9B5F8', '#B094F8',
  '#8C62F5', '#6A4ABA', '#422E75',
];

// ── Sample dataset for standalone preview (uncomment to use) ──
// const SAMPLE = {
//   schema: [
//     { name: COL_STAFFED,   type: 'MEASURE' },
//     { name: COL_OCCUPIED,  type: 'MEASURE' },
//     { name: COL_AVAILABLE, type: 'MEASURE' },
//     { name: COL_RATE,      type: 'MEASURE' },
//     { name: 'Total Flex Beds Open', type: 'MEASURE' },
//     { name: COL_UNIT,      type: 'ATTRIBUTE' },
//   ],
//   data: [
//     [62, 48, 14, 0.77, 0, 'Med/Surg'],
//     [64, 52, 12, 0.81, 0, 'ED'],
//     [44, 28, 16, 0.64, 0, 'Ortho'],
//     [38, 34,  4, 0.89, 0, 'ICU'],
//     [50, 38, 12, 0.76, 0, 'Telemetry'],
//     [30, 24,  6, 0.80, 0, 'L&D'],
//     [40, 30, 10, 0.75, 0, 'Outpatient Clinic'],
//   ],
// };

// ── Data read ──
function readData() {
  try {
    if (typeof viz !== 'undefined' && viz?.getDataFromSearchQuery) {
      const dm = viz.getDataFromSearchQuery();
      const { schema, data } = dm.getData();
      return { schema, data };
    }
  } catch (e) {
    console.warn('[waffle] viz read failed:', e);
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

function toUnits({ schema, data }) {
  const iUnit  = resolveCol(schema, COL_UNIT,      'unit.*type', '^unit$', 'ward', 'department');
  const iStaff = resolveCol(schema, COL_STAFFED,   'staffed', 'capacity');
  const iOcc   = resolveCol(schema, COL_OCCUPIED,  'occupied', 'used');
  const iAvail = resolveCol(schema, COL_AVAILABLE, 'available', 'free', 'open');
  const iRate  = resolveCol(schema, COL_RATE,      'occupancy.*rate', 'occupancy', 'utilization');

  console.log('[waffle] schema:', schema.map(c => c.name));
  console.log('[waffle] indexes:', { iUnit, iStaff, iOcc, iAvail, iRate });

  let paletteIdx = 0;
  const units = data.map(r => {
    const name = iUnit >= 0 ? String(r[iUnit] ?? '∅') : '∅';
    let staffed   = iStaff >= 0 ? Number(r[iStaff]) : NaN;
    let occupied  = iOcc   >= 0 ? Number(r[iOcc])   : NaN;
    let available = iAvail >= 0 ? Number(r[iAvail]) : NaN;

    // Fill in any one missing field from the other two.
    if (!Number.isFinite(staffed)   && Number.isFinite(occupied) && Number.isFinite(available)) staffed   = occupied + available;
    if (!Number.isFinite(available) && Number.isFinite(staffed)  && Number.isFinite(occupied))  available = Math.max(0, staffed - occupied);
    if (!Number.isFinite(occupied)  && Number.isFinite(staffed)  && Number.isFinite(available)) occupied  = Math.max(0, staffed - available);

    staffed   = Math.max(0, Math.round(staffed   || 0));
    occupied  = Math.max(0, Math.round(occupied  || 0));
    available = Math.max(0, Math.round(available || 0));
    if (occupied + available !== staffed) staffed = occupied + available;

    let rate = iRate >= 0 ? Number(r[iRate]) : NaN;
    if (!Number.isFinite(rate)) rate = staffed > 0 ? occupied / staffed : 0;
    // Accept both 0–1 and 0–100 inputs.
    if (rate > 1.5) rate = rate / 100;
    const ratePct = Math.round(rate * 100);

    const color = UNIT_COLORS[name] || PALETTE[paletteIdx++ % PALETTE.length];

    return { name, staffed, occupied, available, ratePct, color };
  }).filter(u => u.staffed > 0);

  // Sort by occupancy rate descending (matches the target image).
  units.sort((a, b) => b.ratePct - a.ratePct);
  return units;
}

// ── SVG glyphs ──
function bedOccupied(c) {
  return '<svg viewBox="0 0 32 20" xmlns="http://www.w3.org/2000/svg">'
    + '<path d="M 2.5 3.5 L 5.7 3.5 L 5.7 13 L 12.5 13 L 12.5 8 L 23 8 Q 29 8 29 13 L 29 18.5 L 25.8 18.5 L 25.8 15.8 L 5.7 15.8 L 5.7 18.5 L 2.5 18.5 Z" fill="' + c + '"/>'
    + '<circle cx="9.2" cy="10" r="2.9" fill="' + c + '"/>'
    + '</svg>';
}
function bedAvailable(c) {
  return '<svg viewBox="0 0 32 20" xmlns="http://www.w3.org/2000/svg">'
    + '<path d="M 2.5 3.5 L 5.7 3.5 L 5.7 13 L 12.5 13 L 12.5 11.6 L 24.5 11.6 Q 29 11.6 29 13 L 29 18.5 L 25.8 18.5 L 25.8 15.8 L 5.7 15.8 L 5.7 18.5 L 2.5 18.5 Z" fill="white" stroke="' + c + '" stroke-width="1.2" stroke-linejoin="round"/>'
    + '</svg>';
}

// ── Renderers ──
function renderKpis(units) {
  const totals = units.reduce((acc, u) => {
    acc.staffed   += u.staffed;
    acc.occupied  += u.occupied;
    acc.available += u.available;
    return acc;
  }, { staffed: 0, occupied: 0, available: 0 });
  const occPct = totals.staffed > 0 ? (totals.occupied / totals.staffed) * 100 : 0;
  const avlPct = 100 - occPct;
  const pct    = Math.round(occPct);
  const fmt    = n => Number(n).toLocaleString();

  const kpiEl = document.getElementById('kpis');
  kpiEl.innerHTML =
    '<div class="sum-left">' +
      '<div class="sum-pct">' + pct + '<span class="sum-pct-unit">%</span></div>' +
      '<div class="sum-cap">occupancy</div>' +
    '</div>' +
    '<div class="sum-bar" aria-hidden="true">' +
      '<div class="sum-occ" style="width:' + occPct + '%"></div>' +
      '<div class="sum-avl" style="width:' + avlPct + '%"></div>' +
    '</div>' +
    '<div class="sum-stats">' +
      '<span><span class="sum-num">' + fmt(totals.occupied) + '</span> occupied</span>' +
      '<span class="sum-sep">·</span>' +
      '<span><span class="sum-num">' + fmt(totals.available) + '</span> available</span>' +
      '<span class="sum-sep">·</span>' +
      '<span><span class="sum-num">' + fmt(totals.staffed) + '</span> total</span>' +
    '</div>';
}

function renderUnits(units) {
  const host = document.getElementById('wards');
  host.innerHTML = '';

  units.forEach(u => {
    const card = document.createElement('div');
    card.className = 'unit';

    const head = document.createElement('div');
    head.className = 'unit-head';
    head.innerHTML =
      '<div class="unit-dot" style="background:' + u.color + '"></div>' +
      '<div class="unit-name">' + u.name + '</div>' +
      '<div class="unit-spacer"></div>' +
      '<div class="unit-bar"><div class="unit-bar-fill" style="width:' + u.ratePct + '%;background:' + u.color + '"></div></div>' +
      '<div class="unit-meta">' + u.occupied + '/' + u.staffed + ' · ' + u.ratePct + '%</div>';
    card.appendChild(head);

    const grid = document.createElement('div');
    grid.className = 'unit-grid';
    const frag = document.createDocumentFragment();
    for (let i = 0; i < u.occupied; i++) {
      const d = document.createElement('div');
      d.className = 'bed';
      d.title = u.name + ' · bed ' + (i + 1) + ' · occupied';
      d.innerHTML = bedOccupied(u.color);
      frag.appendChild(d);
    }
    for (let i = 0; i < u.available; i++) {
      const d = document.createElement('div');
      d.className = 'bed';
      d.title = u.name + ' · bed ' + (u.occupied + i + 1) + ' · available';
      d.innerHTML = bedAvailable(u.color);
      frag.appendChild(d);
    }
    grid.appendChild(frag);
    card.appendChild(grid);
    host.appendChild(card);
  });
}

function renderEmpty() {
  document.getElementById('kpis').innerHTML = '';
  document.getElementById('wards').innerHTML = '<div class="empty">No data to display</div>';
}

// ── Boot ──
const raw   = readData();
const UNITS = toUnits(raw);

if (!UNITS.length) {
  renderEmpty();
} else {
  renderKpis(UNITS);
  renderUnits(UNITS);
}

// ── Signal TS render-complete (no-op when not in TS) ──
try { viz.events.emitRenderCompletedEvent(); } catch {}
