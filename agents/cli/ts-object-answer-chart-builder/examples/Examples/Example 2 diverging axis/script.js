/**
 * DIVERGING BARS — Engagement (left) vs eNPS (right) by Department
 *
 * Available Columns (ThoughtSpot search):
 * "Department"                  // DIMENSION — one bar-pair per department
 * "Average Engagement Score"    // MEASURE  — drawn to the LEFT of zero
 * "Average Enps"                // MEASURE  — drawn to the RIGHT of zero
 * "Measure names"               // If 'measureValues' is enabled (folded format)
 * "Measure values"              // If 'measureValues' is enabled (folded format)
 * --- END ---
 *
 * The chart needs LONG rows { Department, Metric, Value, LabelValue }. TS hands
 * back WIDE rows (the two named measures) or FOLDED rows (Measure names/values),
 * so buildRowsFromTS() reshapes either into the long form. If no search data is
 * present (local preview) it falls back to SAMPLE_DATA.
 */

// ThoughtSpot: Uncomment the block below before pasting into ThoughtSpot

const { muze, getDataFromSearchQuery } = viz;


const { DataModel } = muze;

// ── Internal schema for the DataModel the chart draws from ──
const schema = [
  { name: 'Department', type: 'dimension' },
  { name: 'Metric', type: 'dimension' },
  { name: 'Value', type: 'measure', defAggFn: 'sum' },
  { name: 'LabelValue', type: 'measure', defAggFn: 'sum' }
];

const DEPARTMENT_FIELD = 'Department';
const METRIC_FIELD = 'Metric';
const VALUE_FIELD = 'Value';
const LABEL_VALUE_FIELD = 'LabelValue';

// Metric labels used for color + text (must match the legend/domainRangeMap below)
const ENGAGEMENT_METRIC = 'Engagement';
const ENPS_METRIC = 'eNPS';

// ── TS source column names (update these to match your search) ──
const TS_DEPARTMENT_COL = 'Department';
const TS_ENGAGEMENT_COL = 'Average Engagement Score';
const TS_ENPS_COL = 'Average Enps';
const TS_MEASURE_NAMES_COL = 'Measure names';
const TS_MEASURE_VALUES_COL = 'Measure values';

const ENGAGEMENT_COLOR = '#1e3b2a';
const ENPS_COLOR = '#9a8b5f';

// ── Sample data (used only when no search data is available, e.g. local preview) ──
const SAMPLE_DATA = [
  { Department: 'Sales', Metric: 'Engagement', Value: -76.6, LabelValue: 76.6 },
  { Department: 'Sales', Metric: 'eNPS', Value: 49.7, LabelValue: 49.7 },
  { Department: 'Engineering', Metric: 'Engagement', Value: -82.1, LabelValue: 82.1 },
  { Department: 'Engineering', Metric: 'eNPS', Value: 38.4, LabelValue: 38.4 },
  { Department: 'Marketing', Metric: 'Engagement', Value: -71.3, LabelValue: 71.3 },
  { Department: 'Marketing', Metric: 'eNPS', Value: 55.2, LabelValue: 55.2 },
  { Department: 'HR', Metric: 'Engagement', Value: -68.9, LabelValue: 68.9 },
  { Department: 'HR', Metric: 'eNPS', Value: 42.1, LabelValue: 42.1 },
  { Department: 'Finance', Metric: 'Engagement', Value: -79.4, LabelValue: 79.4 },
  { Department: 'Finance', Metric: 'eNPS', Value: 31.8, LabelValue: 31.8 },
  { Department: 'Operations', Metric: 'Engagement', Value: -74.2, LabelValue: 74.2 },
  { Department: 'Operations', Metric: 'eNPS', Value: 44.6, LabelValue: 44.6 },
  { Department: 'Product', Metric: 'Engagement', Value: -85.3, LabelValue: 85.3 },
  { Department: 'Product', Metric: 'eNPS', Value: 27.9, LabelValue: 27.9 },
  { Department: 'Support', Metric: 'Engagement', Value: -66.1, LabelValue: 66.1 },
  { Department: 'Support', Metric: 'eNPS', Value: 58.3, LabelValue: 58.3 }
];

// Emit one long row per metric: Engagement is negated (left of zero), eNPS stays
// positive (right of zero); LabelValue is always the positive magnitude.
const engagementRow = (dept, v) => ({
  [DEPARTMENT_FIELD]: dept,
  [METRIC_FIELD]: ENGAGEMENT_METRIC,
  [VALUE_FIELD]: -Math.abs(v),
  [LABEL_VALUE_FIELD]: Math.abs(v)
});
const enpsRow = (dept, v) => ({
  [DEPARTMENT_FIELD]: dept,
  [METRIC_FIELD]: ENPS_METRIC,
  [VALUE_FIELD]: v,
  [LABEL_VALUE_FIELD]: v
});

// Reshape ThoughtSpot search data (wide OR folded) into long chart rows.
// Returns null when no usable search data is present so the caller can fall back.
function buildRowsFromTS() {
  const res = getDataFromSearchQuery().getData();
  const cols = (res.schema || []).map((s) => s.name);
  const rows = res.data || [];
  const idx = (name) => cols.indexOf(name);
  if (!rows.length) return null;

  const deptI = idx(TS_DEPARTMENT_COL);
  if (deptI < 0) return null;

  const out = [];

  // Wide format: one search row per department with both named measures.
  const engI = idx(TS_ENGAGEMENT_COL);
  const enpsI = idx(TS_ENPS_COL);
  if (engI >= 0 && enpsI >= 0) {
    rows.forEach((r) => {
      const dept = r[deptI];
      out.push(engagementRow(dept, Number(r[engI]) || 0));
      out.push(enpsRow(dept, Number(r[enpsI]) || 0));
    });
    return out.length ? out : null;
  }

  // Folded format: (Department, Measure names, Measure values) — measureValues on.
  const mnI = idx(TS_MEASURE_NAMES_COL);
  const mvI = idx(TS_MEASURE_VALUES_COL);
  if (mnI >= 0 && mvI >= 0) {
    rows.forEach((r) => {
      const dept = r[deptI];
      const name = r[mnI];
      const val = Number(r[mvI]) || 0;
      if (name === TS_ENGAGEMENT_COL) out.push(engagementRow(dept, val));
      else if (name === TS_ENPS_COL) out.push(enpsRow(dept, val));
    });
    return out.length ? out : null;
  }

  return null;
}

// Prefer live TS data; fall back to sample data locally or on any shape mismatch.
let chartRows = SAMPLE_DATA;
try {
  const tsRows = buildRowsFromTS();
  if (tsRows && tsRows.length) chartRows = tsRows;
} catch (e) {
  console.warn('Diverging bars: falling back to sample data —', e.message);
}

// Derive the x-domain from the data (with headroom for the value labels) so the
// bars fit whatever TS returns. Rounds up to a tidy multiple of 10 — for the
// sample data this resolves to [-100, 70], matching the original fixed domain.
const magnitudes = (metric) =>
  chartRows.filter((r) => r[METRIC_FIELD] === metric).map((r) => Math.abs(r[VALUE_FIELD]));
const niceMax = (v) => Math.max(10, Math.ceil((v * 1.15) / 10) * 10);
const engagementMax = Math.max(0, ...magnitudes(ENGAGEMENT_METRIC));
const enpsMax = Math.max(0, ...magnitudes(ENPS_METRIC));
const X_DOMAIN = [-niceMax(engagementMax), niceMax(enpsMax)];

const formattedData = DataModel.loadDataSync(chartRows, schema);
const dm = new DataModel(formattedData);

// ── Muze Experience standalone (default): ──
//const env = muze();
//const canvas = env.canvas();
// ThoughtSpot: Comment out the 2 lines above and uncomment below:
const canvas = muze.canvas();

canvas
  .data(dm)
  .rows([DEPARTMENT_FIELD])
  .columns([VALUE_FIELD])
  .color(METRIC_FIELD)
  .layers([
    // Bar layer
    {
      mark: 'bar',
      encoding: {
        color: {
          value: (d) => {
            const metric = d && d.datum && d.datum.dataObj
              ? d.datum.dataObj[METRIC_FIELD]
              : null;
            return metric === ENGAGEMENT_METRIC ? ENGAGEMENT_COLOR : ENPS_COLOR;
          }
        }
      },
      transform: { type: 'group' }
    },
    // Text labels — same grouping as bar, aligned via encodingTransform
    {
      mark: 'text',
      encoding: {
        text: {
          field: LABEL_VALUE_FIELD,
          formatter: (d) => {
            const raw = d.rawValue;
            return raw % 1 === 0 ? `${raw}` : `${raw.toFixed(1)}`;
          }
        },
        // Must encode color by same field so Muze groups text identically to bars
        color: {
          value: (d) => {
            const metric = d && d.datum && d.datum.dataObj
              ? d.datum.dataObj[METRIC_FIELD]
              : null;
            return metric === ENGAGEMENT_METRIC ? '#333333' : '#333333';
          }
        }
      },
      transform: { type: 'group' },
      encodingTransform: (points, layer) => {
        points.forEach(p => {
          // Read value directly from the point's x position:
          // negative x (left of zero) = Engagement, positive = eNPS
          const xVal = p.update.x;
          // Get the layer's zero-crossing pixel position
          const axes = layer.axes();
          const xScale = axes && axes.x && axes.x.scale ? axes.x.scale() : null;
          const zeroX = xScale ? xScale(0) : null;

          const isNegative = zeroX !== null ? xVal < zeroX : xVal < (layer.measurement().width / 2);

          if (isNegative) {
            // Engagement bar extends left — label at bar's left tip
            p.update.x = xVal - 6;
            p.style = Object.assign(p.style || {}, {
              'text-anchor': 'end',
              'font-size': '11px',
              'font-weight': '500',
              'fill': '#333333'
            });
          } else {
            // eNPS bar extends right — label at bar's right tip
            p.update.x = xVal + 6;
            p.style = Object.assign(p.style || {}, {
              'text-anchor': 'start',
              'font-size': '11px',
              'font-weight': '500',
              'fill': '#333333'
            });
          }
        });
        return points;
      }
    }
  ])
  .config({
    autoGroupBy: { disabled: false },
    axes: {
      x: {
        showAxisName: false,
        domain: X_DOMAIN,
        tickFormat: (d) => {
          const v = typeof d === 'object' ? d.rawValue : d;
          return `${Math.abs(v)}`;
        },
        showZeroLine: true
      },
      y: {
        showAxisName: false,
        padding: 0.3
      }
    },
    gridLines: {
      x: { show: true },
      y: { show: false }
    },
    legend: {
      show: true,
      position: 'top',
      color: {
        show: true,
        // A single space (truthy) suppresses the legend title. An empty string
        // is falsy, so Muze — and ThoughtSpot's Muze build especially — falls
        // back to the color field name ("Metric") and truncates it to "Me…".
        title: { text: ' ' },
        fields: {
          [METRIC_FIELD]: {
            title: ' ',
            domainRangeMap: {
              [ENGAGEMENT_METRIC]: ENGAGEMENT_COLOR,
              [ENPS_METRIC]: ENPS_COLOR
            }
          }
        }
      }
    },
    border: {
      style: 'none',
      showRowBorders: { top: false, bottom: false, left: false, right: false },
      showColBorders: { top: false, bottom: false, left: false, right: false },
      showValueBorders: { top: false, bottom: true, left: false, right: false }
    }
  })
  .width(680)
  .height(480)
  .mount('#chart');

// Apply rounded corners after render
canvas.once('afterRendered', () => {
  document.querySelectorAll('.muze-layer-bar rect').forEach(rect => {
    rect.setAttribute('rx', 4);
    rect.setAttribute('ry', 4);
  });
});

// Signal render completion to ThoughtSpot (no-op in the local preview shim).
if (viz.events && viz.events.emitRenderCompletedEvent) {
  viz.events.emitRenderCompletedEvent();
}
