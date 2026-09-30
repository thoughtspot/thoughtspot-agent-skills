/**
 * Available Columns:
 * "Year"
 * "Scenario"
 * "Total Value"
 * "Measure names" // If 'measureValues' is enabled.
 * "Measure values" // If 'measureValues' is enabled.
 * --- END --- 
 */

// ── ThoughtSpot context ──
// Uncomment the line below when deploying to ThoughtSpot:
 const { muze, getDataFromSearchQuery } = viz;

const { DataModel } = muze;

// ── Column Name Constants (update these to match your data) ──
const YEAR_FIELD = 'Year';
const SCENARIO_FIELD = 'Scenario';
const TOTAL_VALUE_FIELD = 'Total Value';

// ── Schema (used for standalone mode only) ──
const schema = [
  { name: YEAR_FIELD, type: 'dimension' },
  { name: SCENARIO_FIELD, type: 'dimension' },
  { name: TOTAL_VALUE_FIELD, type: 'measure', defAggFn: 'sum' }
];

// ── DataModel: ThoughtSpot vs Standalone ──
// In ThoughtSpot, getDataFromSearchQuery() returns a DataModel directly.
// In standalone/preview, we build one from sample data.
let dm;
if (typeof getDataFromSearchQuery === 'function') {
  // ── ThoughtSpot mode: dm is already a DataModel ──
  dm = getDataFromSearchQuery();
} else {
  // ── Standalone / preview mode ──
  const sampleData = [
    { [YEAR_FIELD]: '01/01/2024', [SCENARIO_FIELD]: 'Historical', [TOTAL_VALUE_FIELD]: 10800 },
    { [YEAR_FIELD]: '01/01/2050', [SCENARIO_FIELD]: 'Stated Policies Scenario', [TOTAL_VALUE_FIELD]: 4610 }
  ];
  const formattedData = DataModel.loadDataSync(sampleData, schema);
  dm = new DataModel(formattedData);
}

// ── Extract rows from DataModel ──
const result = dm.getData();
const columns = result.schema.map(s => s.name);
const rows = result.data.map(row => {
  const obj = {};
  columns.forEach((col, i) => { obj[col] = row[i]; });
  return obj;
});

const historicalRow = rows.find(r => r[SCENARIO_FIELD] === 'Historical');
const scenarioRow = rows.find(r => r[SCENARIO_FIELD] === 'Stated Policies Scenario');

const baselineValue = historicalRow[TOTAL_VALUE_FIELD];
const scenarioValue = scenarioRow[TOTAL_VALUE_FIELD];

// ── Derived KPI values ──
const changePercent = ((scenarioValue - baselineValue) / baselineValue) * 100;
const absChange = Math.abs(changePercent);
const TARGET_REDUCTION = 80;
const progressFraction = Math.min(absChange / TARGET_REDUCTION, 1);

const formatK = (val) => (val / 1000).toFixed(2) + 'K TWh';

// ── Populate HTML elements ──
document.getElementById('kpi-big-number').textContent = changePercent.toFixed(1) + '%';
document.getElementById('kpi-label-right').textContent =
  absChange.toFixed(1) + ' of ' + TARGET_REDUCTION + '%';
document.getElementById('kpi-baseline').textContent =
  '2024 baseline: ' + formatK(baselineValue);
document.getElementById('kpi-target').textContent =
  'Target: −' + TARGET_REDUCTION + '% by 2050';

// ── Position the tick mark ──
const tickEl = document.getElementById('kpi-tick');
tickEl.style.left = progressFraction * 100 + '%';

// ── Load Chart.js and render progress bar ──
// ThoughtSpot: Remove dynamic loading block and add CDN URL to the HTML tab instead
const cjsScript = document.createElement('script');
cjsScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
await new Promise((resolve, reject) => {
  cjsScript.onload = resolve;
  cjsScript.onerror = reject;
  document.head.appendChild(cjsScript);
});

const ctx = document.getElementById('progressChart').getContext('2d');

new Chart(ctx, {
  type: 'bar',
  data: {
    labels: ['Progress'],
    datasets: [
      {
        data: [progressFraction * 100],
        backgroundColor: '#2e7d32',
        borderRadius: { topLeft: 6, bottomLeft: 6, topRight: 0, bottomRight: 0 },
        borderSkipped: false,
        barThickness: 22
      },
      {
        data: [100 - progressFraction * 100],
        backgroundColor: '#a5d6a7',
        borderRadius: { topLeft: 0, bottomLeft: 0, topRight: 6, bottomRight: 6 },
        borderSkipped: false,
        barThickness: 22
      }
    ]
  },
  options: {
    indexAxis: 'y',
    responsive: false,
    animation: { duration: 800, easing: 'easeInOutQuart' },
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false }
    },
    scales: {
      x: { stacked: true, display: false, min: 0, max: 100 },
      y: { stacked: true, display: false }
    },
    layout: { padding: 0 }
  }
});

// ThoughtSpot: Uncomment to signal render completion
 viz.events.emitRenderCompletedEvent();