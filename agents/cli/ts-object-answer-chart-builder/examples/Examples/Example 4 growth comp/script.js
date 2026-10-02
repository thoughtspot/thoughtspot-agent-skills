

// ThoughtSpot: Uncomment the block below before pasting into ThoughtSpot

const { muze, getDataFromSearchQuery } = viz;


const { DataModel } = muze;

// ── Column Name Constants ──
const YEAR_FIELD = 'Year';
const SCENARIO_FIELD = 'Scenario';
const VALUE_FIELD = 'Total Value';

// ── Schema (standalone fallback only) ──
const schema = [
  { name: YEAR_FIELD, type: 'dimension', subtype: 'temporal', format: '%m/%d/%Y' },
  { name: SCENARIO_FIELD, type: 'dimension' },
  { name: VALUE_FIELD, type: 'measure', defAggFn: 'sum' }
];

// ── Sample data (standalone fallback only) ──
const sampleData = [
  { Year: '01/01/2010', Scenario: 'Historical', 'Total Value': 32.06 },
  { Year: '01/01/2024', Scenario: 'Historical', 'Total Value': 2072.56 }
];

// ── Load DataModel ──
let dm;
if (typeof viz !== 'undefined' && typeof getDataFromSearchQuery === 'function') {
  const tsData = await getDataFromSearchQuery();
  dm = new DataModel(tsData);
} else {
  const formattedData = DataModel.loadDataSync(sampleData, schema);
  dm = new DataModel(formattedData);
}

// ── Extract rows ──
const result = dm.getData();
const colNames = result.schema.map(s => s.name);
const rows = result.data.map(row => {
  const obj = {};
  colNames.forEach((col, i) => { obj[col] = row[i]; });
  return obj;
});

// ── Sort by Year ascending ──
// ThoughtSpot may return epoch ms numbers or date strings — handle both
rows.sort((a, b) => {
  const da = new Date(a[YEAR_FIELD]);
  const db = new Date(b[YEAR_FIELD]);
  return da - db;
});

const startRow = rows[0];
const endRow   = rows[rows.length - 1];

// ── Derive values ──
const startValue = startRow[VALUE_FIELD];
const endValue   = endRow[VALUE_FIELD];

// ── Use getUTCFullYear() to avoid timezone-off-by-one errors ──
const startYear    = new Date(startRow[YEAR_FIELD]).getUTCFullYear();
const endYear      = new Date(endRow[YEAR_FIELD]).getUTCFullYear();
const yearSpan     = endYear - startYear;
const growthFactor = Math.round(endValue / startValue);

const startDisplay = startValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const endDisplay   = endValue.toLocaleString('en-US',   { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ── Render function ──
function render(containerW) {

  const endR   = 26;
  const glowR  = endR + 8;
  const startR = 5;

  const padLeft  = 50;
  const padRight = 70;
  const padTop   = 50;
  const MID_Y    = padTop;

  const startCx  = padLeft;
  const endCx    = containerW - padRight;

  const lineX1   = startCx + startR + 6;
  const lineX2   = endCx - glowR - 4;
  const lineMidX = (lineX1 + lineX2) / 2;

  const startYearY  = MID_Y - startR - 10;
  const startValueY = MID_Y + startR + 14;
  const startUnitY  = startValueY + 13;

  const endYearY  = MID_Y + glowR + 16;
  const endValueY = endYearY + 18;
  const endUnitY  = endValueY + 13;

  const connLabelY = MID_Y - 10;
  const connSubY   = MID_Y + 16;
  const svgH       = endUnitY + 10;

  const container = document.getElementById('chart');
  let svg = container.querySelector('svg');

  if (!svg) {
    container.innerHTML = `
      <div class="kpi-card">
        <svg xmlns="http://www.w3.org/2000/svg"
             style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; overflow:visible;">
          <line   id="kpi-line"/>
          <text   id="kpi-growth-label"/>
          <text   id="kpi-growth-sub"/>
          <circle id="kpi-start-circle"/>
          <text   id="kpi-start-year"/>
          <text   id="kpi-start-value"/>
          <text   id="kpi-start-unit"/>
          <circle id="kpi-end-glow"/>
          <circle id="kpi-end-circle"/>
          <text   id="kpi-end-year"/>
          <text   id="kpi-end-value"/>
          <text   id="kpi-end-unit"/>
        </svg>
      </div>`;
    svg = container.querySelector('svg');

    document.getElementById('kpi-growth-label').textContent = `${growthFactor}× growth`;
    document.getElementById('kpi-growth-sub').textContent   = `${yearSpan} years`;
    document.getElementById('kpi-start-year').textContent   = startYear;
    document.getElementById('kpi-start-value').textContent  = startDisplay;
    document.getElementById('kpi-start-unit').textContent   = 'TWh';
    document.getElementById('kpi-end-year').textContent     = endYear;
    document.getElementById('kpi-end-value').textContent    = endDisplay;
    document.getElementById('kpi-end-unit').textContent     = 'TWh';

    const gl = document.getElementById('kpi-growth-label');
    gl.setAttribute('text-anchor', 'middle');
    gl.setAttribute('font-size', '13');
    gl.setAttribute('font-weight', '500');
    gl.setAttribute('fill', '#BA7517');

    const gs = document.getElementById('kpi-growth-sub');
    gs.setAttribute('text-anchor', 'middle');
    gs.setAttribute('font-size', '10');
    gs.setAttribute('fill', '#999');

    const sy = document.getElementById('kpi-start-year');
    sy.setAttribute('text-anchor', 'middle');
    sy.setAttribute('font-size', '11');
    sy.setAttribute('fill', '#999');

    const sv = document.getElementById('kpi-start-value');
    sv.setAttribute('text-anchor', 'middle');
    sv.setAttribute('font-size', '13');
    sv.setAttribute('font-weight', '500');
    sv.setAttribute('fill', '#666');

    const su = document.getElementById('kpi-start-unit');
    su.setAttribute('text-anchor', 'middle');
    su.setAttribute('font-size', '10');
    su.setAttribute('fill', '#999');

    const ey = document.getElementById('kpi-end-year');
    ey.setAttribute('text-anchor', 'middle');
    ey.setAttribute('font-size', '11');
    ey.setAttribute('font-weight', '500');
    ey.setAttribute('fill', '#854F0B');

    const ev = document.getElementById('kpi-end-value');
    ev.setAttribute('text-anchor', 'middle');
    ev.setAttribute('font-size', '16');
    ev.setAttribute('font-weight', '500');
    ev.setAttribute('fill', '#BA7517');

    const eu = document.getElementById('kpi-end-unit');
    eu.setAttribute('text-anchor', 'middle');
    eu.setAttribute('font-size', '10');
    eu.setAttribute('fill', '#999');

    document.getElementById('kpi-start-circle').setAttribute('fill', '#D3D1C7');
    document.getElementById('kpi-start-circle').setAttribute('r', startR);
    document.getElementById('kpi-end-glow').setAttribute('fill', '#FAC775');
    document.getElementById('kpi-end-glow').setAttribute('opacity', '0.45');
    document.getElementById('kpi-end-glow').setAttribute('r', glowR);
    document.getElementById('kpi-end-circle').setAttribute('fill', '#BA7517');
    document.getElementById('kpi-end-circle').setAttribute('r', endR);

    const line = document.getElementById('kpi-line');
    line.setAttribute('stroke', 'rgba(0,0,0,0.12)');
    line.setAttribute('stroke-width', '1');
  }

  svg.setAttribute('viewBox', `0 0 ${containerW} ${svgH}`);
  svg.setAttribute('width', containerW);
  svg.setAttribute('height', svgH);

  document.getElementById('kpi-line').setAttribute('x1', lineX1);
  document.getElementById('kpi-line').setAttribute('y1', MID_Y);
  document.getElementById('kpi-line').setAttribute('x2', lineX2);
  document.getElementById('kpi-line').setAttribute('y2', MID_Y);

  document.getElementById('kpi-growth-label').setAttribute('x', lineMidX);
  document.getElementById('kpi-growth-label').setAttribute('y', connLabelY);
  document.getElementById('kpi-growth-sub').setAttribute('x', lineMidX);
  document.getElementById('kpi-growth-sub').setAttribute('y', connSubY);

  document.getElementById('kpi-start-circle').setAttribute('cx', startCx);
  document.getElementById('kpi-start-circle').setAttribute('cy', MID_Y);
  document.getElementById('kpi-start-year').setAttribute('x', startCx);
  document.getElementById('kpi-start-year').setAttribute('y', startYearY);
  document.getElementById('kpi-start-value').setAttribute('x', startCx);
  document.getElementById('kpi-start-value').setAttribute('y', startValueY);
  document.getElementById('kpi-start-unit').setAttribute('x', startCx);
  document.getElementById('kpi-start-unit').setAttribute('y', startUnitY);

  document.getElementById('kpi-end-glow').setAttribute('cx', endCx);
  document.getElementById('kpi-end-glow').setAttribute('cy', MID_Y);
  document.getElementById('kpi-end-circle').setAttribute('cx', endCx);
  document.getElementById('kpi-end-circle').setAttribute('cy', MID_Y);
  document.getElementById('kpi-end-year').setAttribute('x', endCx);
  document.getElementById('kpi-end-year').setAttribute('y', endYearY);
  document.getElementById('kpi-end-value').setAttribute('x', endCx);
  document.getElementById('kpi-end-value').setAttribute('y', endValueY);
  document.getElementById('kpi-end-unit').setAttribute('x', endCx);
  document.getElementById('kpi-end-unit').setAttribute('y', endUnitY);
}

// ── Initial render ──
const container = document.getElementById('chart');
render(container.offsetWidth || 480);

// ── ResizeObserver with requestAnimationFrame ──
let rafId = null;
const resizeObserver = new ResizeObserver(() => {
  if (rafId) cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(() => {
    const w = container.offsetWidth;
    if (w > 0) render(w);
    rafId = null;
  });
});
resizeObserver.observe(container);

// ── Signal render completion (ThoughtSpot only) ──
if (typeof viz !== 'undefined' && viz.events) {
  viz.events.emitRenderCompletedEvent();
}