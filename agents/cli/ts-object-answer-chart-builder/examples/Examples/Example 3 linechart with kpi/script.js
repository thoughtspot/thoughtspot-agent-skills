

// ── ThoughtSpot context ──
// Uncomment the line below when pasting into ThoughtSpot:
 const { muze, getDataFromSearchQuery } = viz;

const { DataModel } = muze;

// ── Column Name Constants ──
const YEAR_FIELD      = 'Year(Year)';
const SCENARIO_FIELD  = 'Scenario';
const VALUE_FIELD     = 'Total Value';

const SCENARIO_HISTORICAL = 'Historical';
const SCENARIO_CURRENT    = 'Current Policies Scenario';
const SCENARIO_STATED     = 'Stated Policies Scenario';

// ── Schema ──
const schema = [
  { name: 'Year(Year)',  type: 'dimension' },
  { name: 'Scenario',    type: 'dimension' },
  { name: 'Total Value', type: 'dimension' }
];

// ── Hardcoded fallback data (standalone only) ──
const fallbackData = [
  { 'Year(Year)': 2024, Scenario: 'Historical',                'Total Value': '74.4K'  },
  { 'Year(Year)': 2035, Scenario: 'Current Policies Scenario', 'Total Value': '75.07K' },
  { 'Year(Year)': 2050, Scenario: 'Current Policies Scenario', 'Total Value': '73.58K' },
  { 'Year(Year)': 2035, Scenario: 'Stated Policies Scenario',  'Total Value': '68.63K' },
  { 'Year(Year)': 2050, Scenario: 'Stated Policies Scenario',  'Total Value': '57.48K' }
];

// ── Load DataModel ──
let dm;
if (typeof getDataFromSearchQuery === 'function') {
  dm = getDataFromSearchQuery();
} else {
  const formattedData = DataModel.loadDataSync(fallbackData, schema);
  dm = new DataModel(formattedData);
}

// ── Extract rows ──
const result   = dm.getData();
const colNames = result.schema.map(s => s.name);
const rawRows  = result.data.map(row => {
  const obj = {};
  colNames.forEach((col, i) => { obj[col] = row[i]; });
  return obj;
});

// ── Helper: normalize Year ──
function toYear(val) {
  const n = Number(val);
  if (n > 10000) return new Date(n).getUTCFullYear();
  return n;
}

// ── Helper: normalize Value ──
function toKValue(val) {
  if (val === null || val === undefined) return NaN;
  const str = String(val).trim();
  if (str.toUpperCase().endsWith('K')) return parseFloat(str.slice(0, -1));
  const num = parseFloat(str);
  return isNaN(num) ? NaN : +(num / 1000).toFixed(2);
}

// ── Normalize rows ──
const dmRows = rawRows.map(r => ({
  year:     toYear(r[YEAR_FIELD]),
  scenario: String(r[SCENARIO_FIELD] || '').trim(),
  value:    toKValue(r[VALUE_FIELD])
}));

// ── Build anchor lookup ──
const anchors = {};
dmRows.forEach(r => {
  if (!anchors[r.scenario]) anchors[r.scenario] = {};
  anchors[r.scenario][r.year] = r.value;
});

// ── Extract anchor values ──
const hist2024 = anchors[SCENARIO_HISTORICAL]?.[2024];
const cur2035  = anchors[SCENARIO_CURRENT]?.[2035];
const cur2050  = anchors[SCENARIO_CURRENT]?.[2050];
const sta2035  = anchors[SCENARIO_STATED]?.[2035];
const sta2050  = anchors[SCENARIO_STATED]?.[2050];

// ── Damped Hermite interpolation ──
const DAMPING = 0.1;

function smoothInterp(y0, v0, y1, v1, y2, v2, yr) {
  if (yr <= y1) {
    const t  = (yr - y0) / (y1 - y0);
    const t2 = t * t;
    const t3 = t2 * t;
    const h00 =  2*t3 - 3*t2 + 1;
    const h10 =    t3 - 2*t2 + t;
    const h01 = -2*t3 + 3*t2;
    const h11 =    t3 -   t2;
    const m0  = 0;
    const m1  = DAMPING * (v2 - v0) / 2;
    return +(h00*v0 + h10*(y1-y0)*m0 + h01*v1 + h11*(y1-y0)*m1).toFixed(3);
  } else {
    const t  = (yr - y1) / (y2 - y1);
    const t2 = t * t;
    const t3 = t2 * t;
    const h00 =  2*t3 - 3*t2 + 1;
    const h10 =    t3 - 2*t2 + t;
    const h01 = -2*t3 + 3*t2;
    const h11 =    t3 -   t2;
    const m0  = DAMPING * (v2 - v0) / 2;
    const m1  = 0;
    return +(h00*v1 + h10*(y2-y1)*m0 + h01*v2 + h11*(y2-y1)*m1).toFixed(3);
  }
}

// ── Dense year array ──
const allYears   = Array.from({ length: 27 }, (_, i) => 2024 + i);
const milestones = new Set([2024, 2035, 2050]);

const historicalVals = allYears.map(y => y === 2024 ? hist2024 : null);
const currentVals    = allYears.map(y => smoothInterp(2024, hist2024, 2035, cur2035, 2050, cur2050, y));
const statedVals     = allYears.map(y => smoothInterp(2024, hist2024, 2035, sta2035, 2050, sta2050, y));

// ── Build KPI cards ──
const reduction = +(hist2024 - sta2050).toFixed(2);
const kpiCards = [
  { label: 'Historical (2024)',       value: `${hist2024}K`,   labelColor: '#888',    valueColor: '#222'    },
  { label: 'Current policies (2050)', value: `${cur2050}K`,    labelColor: '#b45309', valueColor: '#222'    },
  { label: 'Stated policies (2050)',  value: `${sta2050}K`,    labelColor: '#166534', valueColor: '#222'    },
  { label: 'Reduction by 2050',       value: `−${reduction}K`, labelColor: '#166534', valueColor: '#166534' }
];

const metricsRow = document.getElementById('metricsRow');
if (metricsRow) {
  kpiCards.forEach(card => {
    const div = document.createElement('div');
    div.className = 'metric-card';
    div.innerHTML =
      `<div class="metric-label" style="color:${card.labelColor};">${card.label}</div>` +
      `<div class="metric-value" style="color:${card.valueColor};">${card.value}</div>`;
    metricsRow.appendChild(div);
  });
}

// ── Load Chart.js ──
const cjsScript = document.createElement('script');
cjsScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
await new Promise((resolve, reject) => {
  cjsScript.onload = resolve;
  cjsScript.onerror = reject;
  document.head.appendChild(cjsScript);
});

// ── Render Chart ──
// No manual height calculation needed — CSS flex handles it.
// The canvas is position:absolute filling .chart-wrap which is flex:1,
// so Chart.js measures the wrapper and sizes itself correctly.
const fanChart = document.getElementById('fanChart');
if (!fanChart) throw new Error('Canvas #fanChart not found — check HTML tab is saved');
const ctx = fanChart.getContext('2d');

new Chart(ctx, {
  type: 'line',
  data: {
    labels: allYears,
    datasets: [
      {
        label: SCENARIO_HISTORICAL,
        data: historicalVals,
        borderColor: '#555',
        borderWidth: 3,
        pointRadius: allYears.map(y => y === 2024 ? 6 : 0),
        pointBackgroundColor: '#555',
        tension: 0,
        fill: false,
        spanGaps: false
      },
      {
        label: SCENARIO_CURRENT,
        data: currentVals,
        borderColor: '#b45309',
        borderWidth: 2.5,
        pointRadius: allYears.map(y => milestones.has(y) ? 5 : 0),
        pointBackgroundColor: '#b45309',
        tension: 0,
        fill: false
      },
      {
        label: SCENARIO_STATED,
        data: statedVals,
        borderColor: '#166534',
        borderWidth: 2.5,
        borderDash: [6, 3],
        pointRadius: allYears.map(y => milestones.has(y) ? 5 : 0),
        pointBackgroundColor: '#166534',
        tension: 0,
        fill: '-1',
        backgroundColor: 'rgba(22, 101, 52, 0.10)'
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#fff',
        borderColor: 'rgba(0,0,0,0.08)',
        borderWidth: 1,
        titleColor: '#222',
        bodyColor: '#555',
        filter: item => milestones.has(allYears[item.dataIndex]),
        callbacks: {
          label: c => {
            if (c.parsed.y === null) return null;
            return `  ${c.dataset.label}: ${c.parsed.y.toFixed(2)}K`;
          }
        }
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: {
          color: '#666',
          font: { size: 11 },
          autoSkip: false,
          maxRotation: 0,
          callback: (v, i) =>
            [2024, 2030, 2035, 2040, 2045, 2050].includes(allYears[i]) ? allYears[i] : ''
        },
        border: { display: false }
      },
      y: {
        min: 50,
        max: 80,
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: {
          color: '#666',
          font: { size: 11 },
          callback: v => v + 'K'
        },
        border: { display: false },
        title: {
          display: true,
          text: 'Total CO₂ value',
          color: '#999',
          font: { size: 11 }
        }
      }
    }
  }
});

 viz.events.emitRenderCompletedEvent();