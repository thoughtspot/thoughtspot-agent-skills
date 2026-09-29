/**
 * Available Columns:
 * "City"
 * "Average Avg Base Salary"
 * "Average Enps"
 * "Total Headcount"
 * "Measure names" // If 'measureValues' is enabled.
 * "Measure values" // If 'measureValues' is enabled.
 * --- END --- 
 */

// ThoughtSpot: Uncomment the block below before pasting into ThoughtSpot

const { muze, getDataFromSearchQuery } = viz;
const { DataModel } = muze;

// ── Internal field names (what the DataModel + chart draw from) ──
const CITY_FIELD   = "City";
const SALARY_FIELD = "Avg Base Salary";
const ENPS_FIELD   = "eNPS";
const HC_FIELD     = "Headcount";
const BAND_FIELD   = "Salary Band";

// ── ThoughtSpot source column names (update these to match your search) ──
// Note: these differ from the internal names above — TS prefixes the aggregated
// measures ("Average …", "Total …"), and there is no "Salary Band" column, so
// the band is derived from the salary distribution below.
const TS_CITY_COL           = "City";
const TS_SALARY_COL         = "Average Avg Base Salary";
const TS_ENPS_COL           = "Average Enps";
const TS_HC_COL             = "Total Headcount";
const TS_MEASURE_NAMES_COL  = "Measure names";
const TS_MEASURE_VALUES_COL = "Measure values";

const CITY_COLORS = [
  "#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2",
  "#EDC948", "#B07AA1", "#FF9DA7", "#1e6b5e", "#BAB0AC",
];

const MIN_R = 6;
const MAX_R = 24;

// ── Sample data (used only when no search data is available, e.g. local preview) ──
const SAMPLE_DATA = [
  { [CITY_FIELD]: "Dallas",        [SALARY_FIELD]: 111000, [ENPS_FIELD]: 48,   [HC_FIELD]: 18,  [BAND_FIELD]: "Low"  },
  { [CITY_FIELD]: "Austin",        [SALARY_FIELD]: 116000, [ENPS_FIELD]: 45,   [HC_FIELD]: 32,  [BAND_FIELD]: "Low"  },
  { [CITY_FIELD]: "Remote - US",   [SALARY_FIELD]: 109500, [ENPS_FIELD]: 44,   [HC_FIELD]: 45,  [BAND_FIELD]: "Low"  },
  { [CITY_FIELD]: "Atlanta",       [SALARY_FIELD]: 110500, [ENPS_FIELD]: 40,   [HC_FIELD]: 15,  [BAND_FIELD]: "Low"  },
  { [CITY_FIELD]: "Denver",        [SALARY_FIELD]: 118000, [ENPS_FIELD]: 42,   [HC_FIELD]: 18,  [BAND_FIELD]: "Low"  },
  { [CITY_FIELD]: "Chicago",       [SALARY_FIELD]: 121000, [ENPS_FIELD]: 42.5, [HC_FIELD]: 16,  [BAND_FIELD]: "Mid"  },
  { [CITY_FIELD]: "Boston",        [SALARY_FIELD]: 127000, [ENPS_FIELD]: 37,   [HC_FIELD]: 14,  [BAND_FIELD]: "Mid"  },
  { [CITY_FIELD]: "Seattle",       [SALARY_FIELD]: 132000, [ENPS_FIELD]: 40,   [HC_FIELD]: 22,  [BAND_FIELD]: "High" },
  { [CITY_FIELD]: "New York City", [SALARY_FIELD]: 136000, [ENPS_FIELD]: 39.5, [HC_FIELD]: 230, [BAND_FIELD]: "High" },
  { [CITY_FIELD]: "San Francisco", [SALARY_FIELD]: 141000, [ENPS_FIELD]: 41,   [HC_FIELD]: 250, [BAND_FIELD]: "High" },
];

// TS returns no "Salary Band" column, so bucket cities into Low/Mid/High by the
// salary distribution (tertiles) — keeps the tooltip's Salary Band meaningful.
function assignSalaryBands(list) {
  const salaries = list.map((r) => r[SALARY_FIELD]).sort((a, b) => a - b);
  const n = salaries.length;
  if (!n) return list;
  const loCut = salaries[Math.floor(n / 3)];
  const hiCut = salaries[Math.floor((2 * n) / 3)];
  return list.map((r) => ({
    ...r,
    [BAND_FIELD]:
      r[SALARY_FIELD] < loCut ? "Low" : r[SALARY_FIELD] >= hiCut ? "High" : "Mid",
  }));
}

// Reshape ThoughtSpot search data (wide OR folded) into chart rows.
// Returns null when no usable search data is present so the caller can fall back.
function buildRowsFromTS() {
  const res  = getDataFromSearchQuery().getData();
  const cols = (res.schema || []).map((s) => s.name);
  const data = res.data || [];
  const idx  = (name) => cols.indexOf(name);
  if (!data.length) return null;

  const cityI = idx(TS_CITY_COL);
  if (cityI < 0) return null;

  const salaryI = idx(TS_SALARY_COL);
  const enpsI   = idx(TS_ENPS_COL);
  const hcI     = idx(TS_HC_COL);

  let out = [];

  // Wide format: one search row per city with the named measure columns.
  if (salaryI >= 0 || enpsI >= 0 || hcI >= 0) {
    out = data
      .filter((r) => r[cityI] != null)
      .map((r) => ({
        [CITY_FIELD]:   String(r[cityI]),
        [SALARY_FIELD]: salaryI >= 0 ? Number(r[salaryI]) || 0 : 0,
        [ENPS_FIELD]:   enpsI   >= 0 ? Number(r[enpsI])   || 0 : 0,
        [HC_FIELD]:     hcI     >= 0 ? Number(r[hcI])     || 0 : 0,
      }));
  } else {
    // Folded format: (City, Measure names, Measure values) — measureValues on.
    const mnI = idx(TS_MEASURE_NAMES_COL);
    const mvI = idx(TS_MEASURE_VALUES_COL);
    if (mnI < 0 || mvI < 0) return null;
    const byCity = {};
    data.forEach((r) => {
      if (r[cityI] == null) return;
      const key = String(r[cityI]);
      const rec =
        byCity[key] ||
        (byCity[key] = {
          [CITY_FIELD]: key,
          [SALARY_FIELD]: 0,
          [ENPS_FIELD]: 0,
          [HC_FIELD]: 0,
        });
      const val = Number(r[mvI]) || 0;
      if (r[mnI] === TS_SALARY_COL) rec[SALARY_FIELD] = val;
      else if (r[mnI] === TS_ENPS_COL) rec[ENPS_FIELD] = val;
      else if (r[mnI] === TS_HC_COL) rec[HC_FIELD] = val;
    });
    out = Object.values(byCity);
  }

  if (!out.length) return null;
  return assignSalaryBands(out);
}

// Prefer live TS data; fall back to sample data locally or on any shape mismatch.
let rows = SAMPLE_DATA;
try {
  const tsRows = buildRowsFromTS();
  if (tsRows && tsRows.length) rows = tsRows;
} catch (e) {
  console.warn("City bubble chart: falling back to sample data —", e.message);
}

// ── City → color + radius maps ──
const CITY_COLOR_MAP  = {};
const CITY_RADIUS_MAP = {};
const minHC = Math.min(...rows.map((d) => d[HC_FIELD]));
const maxHC = Math.max(...rows.map((d) => d[HC_FIELD]));
rows.forEach((r, i) => {
  CITY_COLOR_MAP[r[CITY_FIELD]]  = CITY_COLORS[i % CITY_COLORS.length];
  const t = maxHC === minHC ? 1 : (r[HC_FIELD] - minHC) / (maxHC - minHC);
  CITY_RADIUS_MAP[r[CITY_FIELD]] = MIN_R + (MAX_R - MIN_R) * Math.sqrt(t);
});

// ── Stats ──
const nc    = rows.length;
const sumX  = rows.reduce((s, d) => s + d[SALARY_FIELD], 0);
const sumY  = rows.reduce((s, d) => s + d[ENPS_FIELD],   0);
const sumXY = rows.reduce((s, d) => s + d[SALARY_FIELD] * d[ENPS_FIELD], 0);
const sumX2 = rows.reduce((s, d) => s + d[SALARY_FIELD] ** 2, 0);
const denom = nc * sumX2 - sumX * sumX;
const slope     = denom !== 0 ? (nc * sumXY - sumX * sumY) / denom : 0;
const intercept = (sumY - slope * sumX) / nc;

const minX       = Math.min(...rows.map((d) => d[SALARY_FIELD]));
const maxX       = Math.max(...rows.map((d) => d[SALARY_FIELD]));
const minY       = Math.min(...rows.map((d) => d[ENPS_FIELD]));
const maxY       = Math.max(...rows.map((d) => d[ENPS_FIELD]));

// CHANGED: padX 0.12 → 0.22 to give San Francisco label room on the right
const padX       = (maxX - minX) * 0.22;
const padY       = (maxY - minY) * 0.18;
const meanSalary = sumX / nc;
const meanENPS   = sumY / nc;

const domainX = [minX - padX, maxX + padX];
const domainY = [minY - padY, maxY + padY];

const cityPixels = {};

// ── DataModel ──
const schema = [
  { name: CITY_FIELD,   type: "dimension" },
  { name: SALARY_FIELD, type: "measure",   defAggFn: "avg" },
  { name: ENPS_FIELD,   type: "measure",   defAggFn: "avg" },
  { name: HC_FIELD,     type: "measure",   defAggFn: "avg" },
  { name: BAND_FIELD,   type: "dimension" },
];
const dm = new DataModel(DataModel.loadDataSync(rows, schema));

// ── Muze Experience standalone (default): ──
//const env = muze();
//const canvas = env.canvas();
// ThoughtSpot: Comment out the 2 lines above and uncomment below:
const canvas = muze.canvas();

canvas
  .data(dm)
  .rows([ENPS_FIELD])
  .columns([SALARY_FIELD])
  .color({ field: CITY_FIELD, range: CITY_COLORS })
  .detail([CITY_FIELD])
  .layers([

    // ── City bubbles ──
    {
      mark: "point",
      className: "city-bubble-layer",
      encoding: {
        x: { field: SALARY_FIELD },
        y: { field: ENPS_FIELD },
        size:    { value: () => 0.3 },
        opacity: { value: () => 0.92 },
        color:   { value: () => "#cccccc" },
      },
      encodingTransform: (points, layer) => {
        const result  = layer.data().getData();
        const cols    = result.schema.map((s) => s.name);
        const cityIdx = cols.indexOf(CITY_FIELD);
        points.forEach((p, i) => {
          const dataRow = result.data[i];
          if (!dataRow) return;
          const city = cityIdx >= 0 ? dataRow[cityIdx] : null;
          if (!city) return;
          const hex = CITY_COLOR_MAP[city] || "#cccccc";
          p.style = Object.assign(p.style || {}, { fill: hex, stroke: "none" });
          cityPixels[city] = { px: p.update.x, py: p.update.y };
        });
        return points;
      },
    },

    // ── City labels ──
    {
      mark: "text",
      encoding: {
        x: { field: SALARY_FIELD },
        y: { field: ENPS_FIELD },
        text: {
          field: CITY_FIELD,
          formatter: (d) => {
            const v = d && typeof d === "object" ? (d.rawValue ?? d.value ?? "") : d;
            return v == null ? "" : String(v);
          },
        },
        color: { value: () => "#333333" },
      },
      encodingTransform: (points, layer) => {
        const result  = layer.data().getData();
        const cols    = result.schema.map((s) => s.name);
        const cityIdx = cols.indexOf(CITY_FIELD);
        points.forEach((p, i) => {
          const dataRow = result.data[i];
          const city    = dataRow && cityIdx >= 0 ? dataRow[cityIdx] : null;
          const hex     = CITY_COLOR_MAP[city]  || "#444444";
          const r       = CITY_RADIUS_MAP[city] || MIN_R;
          p.update.x += r + 6;
          p.update.y -= 4;
          p.style = Object.assign(p.style || {}, {
            "font-size":   "11px",
            "font-weight": "500",
            "text-anchor": "start",
            fill:          hex,
          });
        });
        return points;
      },
      interactive: false,
      calculateDomain: false,
    },

  ])
  .config({
    autoGroupBy: { disabled: true },
    legend: { show: false },
    axes: {
      x: {
        show: true,
        showAxisName: true,
        name: "AVG BASE SALARY",
        showAxisLine: false,
        domain: domainX,
        numberOfTicks: 6,
        tickFormat: (d) => {
          const v = typeof d === "object" ? d.rawValue : d;
          return `$${(Number(v) / 1000).toFixed(0)}K`;
        },
      },
      y: {
        show: true,
        showAxisName: true,
        name: "eNPS",
        showAxisLine: false,
        domain: domainY,
        numberOfTicks: 5,
        tickFormat: (d) => {
          const v = typeof d === "object" ? d.rawValue : d;
          return String(Math.round(Number(v)));
        },
      },
    },
    gridLines: { x: { show: false }, y: { show: true } },
    border: {
      showRowBorders:   { top: false, bottom: false, left: false, right: false },
      showColBorders:   { top: false, bottom: false, left: false, right: false },
      showValueBorders: { top: false, bottom: false, left: false, right: false },
    },
    interaction: {
      tooltip: {
        formatter: (dataStore) => {
          const result = dataStore.getData();
          const cols = result.schema.map((s) => s.name);
          const row  = result.data[0];
          if (!row) return [];
          const obj = {};
          cols.forEach((c, i) => { obj[c] = row[i]; });
          if (!obj[CITY_FIELD]) return [];
          return [
            { data: [{ value: "City",        style: { "font-weight": "bold" } }, String(obj[CITY_FIELD])] },
            { data: [{ value: "Avg Salary",  style: { "font-weight": "bold" } }, `$${Math.round(obj[SALARY_FIELD] / 1000)}K`] },
            { data: [{ value: "eNPS",        style: { "font-weight": "bold" } }, obj[ENPS_FIELD]] },
            { data: [{ value: "Headcount",   style: { "font-weight": "bold" } }, obj[HC_FIELD]] },
            { data: [{ value: "Salary Band", style: { "font-weight": "bold" } }, obj[BAND_FIELD]] },
          ];
        },
      },
    },
  })
  .mount("#chart");

const NS = "http://www.w3.org/2000/svg";

const applyBubbleSizes = () => {
  const layerGroup = document.querySelector("#chart .city-bubble-layer");
  if (!layerGroup) return;

  const pointGroups = Array.from(layerGroup.querySelectorAll("g")).filter(
    (g) => g.querySelector("path") && !g.querySelector("g")
  );

  if (pointGroups.length === 0) {
    const paths = Array.from(layerGroup.querySelectorAll("path"));
    paths.forEach((path, i) => {
      if (i >= rows.length) return;
      const city   = rows[i][CITY_FIELD];
      const r      = CITY_RADIUS_MAP[city] || MIN_R;
      const color  = CITY_COLOR_MAP[city]  || "#cccccc";
      const parentG = path.parentElement;
      const circle  = document.createElementNS(NS, "circle");
      circle.setAttribute("r",  r);
      circle.setAttribute("cx", 0);
      circle.setAttribute("cy", 0);
      circle.style.setProperty("fill",    color,  "important");
      circle.style.setProperty("stroke",  "none", "important");
      circle.style.setProperty("opacity", "0.92", "important");
      parentG.replaceChild(circle, path);
    });
    return;
  }

  pointGroups.forEach((g, i) => {
    if (i >= rows.length) return;
    const city   = rows[i][CITY_FIELD];
    const r      = CITY_RADIUS_MAP[city] || MIN_R;
    const color  = CITY_COLOR_MAP[city]  || "#cccccc";
    const path   = g.querySelector("path");
    if (!path) return;
    const circle = document.createElementNS(NS, "circle");
    circle.setAttribute("r",  r);
    circle.setAttribute("cx", 0);
    circle.setAttribute("cy", 0);
    circle.style.setProperty("fill",    color,  "important");
    circle.style.setProperty("stroke",  "none", "important");
    circle.style.setProperty("opacity", "0.92", "important");
    g.replaceChild(circle, path);
  });
};

const injectOverlays = () => {
  const cityNames = Object.keys(cityPixels);
  if (cityNames.length < 2) return;

  const svg = document.querySelector("#chart svg");
  if (!svg) return;

  const sorted = [...rows].sort((a, b) => a[SALARY_FIELD] - b[SALARY_FIELD]);
  const cityA  = sorted[0][CITY_FIELD];
  const cityB  = sorted[sorted.length - 1][CITY_FIELD];
  if (!cityPixels[cityA] || !cityPixels[cityB]) return;

  const mX = (cityPixels[cityB].px - cityPixels[cityA].px) /
             (sorted[sorted.length - 1][SALARY_FIELD] - sorted[0][SALARY_FIELD]);
  const cX = cityPixels[cityA].px - mX * sorted[0][SALARY_FIELD];
  const mY = (cityPixels[cityB].py - cityPixels[cityA].py) /
             (sorted[sorted.length - 1][ENPS_FIELD] - sorted[0][ENPS_FIELD]);
  const cY = cityPixels[cityA].py - mY * sorted[0][ENPS_FIELD];

  const toPixX = (val) => mX * val + cX;
  const toPixY = (val) => mY * val + cY;

  const allPx = Object.values(cityPixels).map((p) => p.px);
  const allPy = Object.values(cityPixels).map((p) => p.py);
  const pxMin = Math.min(...allPx);
  const pxMax = Math.max(...allPx);
  const pyMin = Math.min(...allPy);
  const pyMax = Math.max(...allPy);

  const pxLeft   = toPixX(minX - padX * 0.5);
  const pxRight  = toPixX(maxX + padX * 0.5);
  const pyTop    = toPixY(maxY + padY * 0.5);
  const pyBottom = toPixY(minY - padY * 0.5);

  const clipMargin = 8;
  svg.querySelectorAll(".muze-overlay").forEach((el) => el.remove());
  const oldClip = svg.querySelector("#muze-ov-clip");
  if (oldClip) oldClip.remove();

  let defs = svg.querySelector("defs");
  if (!defs) {
    defs = document.createElementNS(NS, "defs");
    svg.insertBefore(defs, svg.firstChild);
  }
  const clipPath = document.createElementNS(NS, "clipPath");
  clipPath.setAttribute("id", "muze-ov-clip");
  const clipRect = document.createElementNS(NS, "rect");
  clipRect.setAttribute("x",      pxMin - clipMargin);
  clipRect.setAttribute("y",      pyMin - clipMargin);
  clipRect.setAttribute("width",  (pxMax - pxMin) + clipMargin * 2);
  clipRect.setAttribute("height", (pyMax - pyMin) + clipMargin * 2);
  clipPath.appendChild(clipRect);
  defs.appendChild(clipPath);

  const gLines = document.createElementNS(NS, "g");
  gLines.setAttribute("class",          "muze-overlay");
  gLines.setAttribute("clip-path",      "url(#muze-ov-clip)");
  gLines.setAttribute("pointer-events", "none");

  const line = (x1, y1, x2, y2, stroke, sw, dash) => {
    const el = document.createElementNS(NS, "line");
    el.setAttribute("x1", x1); el.setAttribute("y1", y1);
    el.setAttribute("x2", x2); el.setAttribute("y2", y2);
    el.setAttribute("stroke", stroke);
    el.setAttribute("stroke-width", sw);
    el.setAttribute("stroke-dasharray", dash);
    el.setAttribute("stroke-linecap", "round");
    el.setAttribute("fill", "none");
    return el;
  };

  gLines.appendChild(line(pxLeft, toPixY(meanENPS), pxRight, toPixY(meanENPS), "#cccccc", "1", "5 5"));
  gLines.appendChild(line(toPixX(meanSalary), pyTop, toPixX(meanSalary), pyBottom, "#cccccc", "1", "5 5"));
  gLines.appendChild(line(
    pxLeft,  toPixY(slope * (minX - padX * 0.5) + intercept),
    pxRight, toPixY(slope * (maxX + padX * 0.5) + intercept),
    "#bbbbbb", "1.5", "6 4"
  ));
  svg.appendChild(gLines);

  const gLabel = document.createElementNS(NS, "g");
  gLabel.setAttribute("class", "muze-overlay");
  gLabel.setAttribute("pointer-events", "none");
  const label = document.createElementNS(NS, "text");
  label.setAttribute("x", toPixX(meanSalary));
  label.setAttribute("y", pyMin - 6);
  label.setAttribute("fill", "#aaaaaa");
  label.setAttribute("font-size", "10");
  label.setAttribute("font-style", "italic");
  label.setAttribute("text-anchor", "middle");
  label.setAttribute("font-family", "sans-serif");
  label.setAttribute("pointer-events", "none");
  label.textContent = "company avg";
  gLabel.appendChild(label);
  svg.appendChild(gLabel);
};

const runPostRender = () => {
  applyBubbleSizes();
  injectOverlays();
};

let attempts = 0;
const tryRun = () => {
  const layerGroup = document.querySelector("#chart .city-bubble-layer");
  const hasPaths   = layerGroup && layerGroup.querySelector("path");
  if (hasPaths && Object.keys(cityPixels).length >= 2) {
    runPostRender();
  } else if (attempts < 40) {
    attempts++;
    setTimeout(tryRun, 100);
  }
};

canvas.once("afterRendered", () => {
  tryRun();
  setTimeout(runPostRender, 500);
  setTimeout(runPostRender, 1000);
});
setTimeout(tryRun, 200);