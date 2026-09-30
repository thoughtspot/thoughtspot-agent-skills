/**
 * Available Columns:
 * "Number of Model"
 * "Measure names" // If 'measureValues' is enabled.
 * "Measure values" // If 'measureValues' is enabled.
 * --- END ---
 */

// ThoughtSpot: Uncomment the block below before pasting into ThoughtSpot

const { muze, getDataFromSearchQuery } = viz;


const { DataModel } = muze;

// ── Schema ──
const schema = [
  { name: 'year',       type: 'dimension' },
  { name: 'activity',   type: 'dimension' },
  { name: 'gender',     type: 'dimension' },
  { name: 'age_group',  type: 'dimension' },
  { name: 'rank',       type: 'measure', defAggFn: 'min' },
  { name: 'pct_users',  type: 'measure', defAggFn: 'avg' }
];

// ── Sample Data ──
const data = [
  {"year":2005,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":78.2},
  {"year":2005,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":2,"pct_users":65.4},
  {"year":2005,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":3,"pct_users":52.1},
  {"year":2005,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":48.3},
  {"year":2005,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":44.7},
  {"year":2005,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":6,"pct_users":38.9},
  {"year":2005,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":33.2},
  {"year":2005,"activity":"banking services","gender":"total","age_group":"total 6+","rank":8,"pct_users":28.6},
  {"year":2005,"activity":"job searching","gender":"total","age_group":"total 6+","rank":9,"pct_users":22.1},
  {"year":2005,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":10,"pct_users":17.4},
  {"year":2006,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":79.1},
  {"year":2006,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":2,"pct_users":66.2},
  {"year":2006,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":3,"pct_users":53.8},
  {"year":2006,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":49.5},
  {"year":2006,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":45.3},
  {"year":2006,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":6,"pct_users":39.4},
  {"year":2006,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":34.1},
  {"year":2006,"activity":"banking services","gender":"total","age_group":"total 6+","rank":8,"pct_users":29.8},
  {"year":2006,"activity":"job searching","gender":"total","age_group":"total 6+","rank":9,"pct_users":23.0},
  {"year":2006,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":10,"pct_users":18.2},
  {"year":2007,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":79.8},
  {"year":2007,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":2,"pct_users":66.9},
  {"year":2007,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":3,"pct_users":54.6},
  {"year":2007,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":50.1},
  {"year":2007,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":46.0},
  {"year":2007,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":6,"pct_users":40.2},
  {"year":2007,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":34.9},
  {"year":2007,"activity":"job searching","gender":"total","age_group":"total 6+","rank":8,"pct_users":24.3},
  {"year":2007,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":30.5},
  {"year":2007,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":10,"pct_users":19.1},
  {"year":2008,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":80.1},
  {"year":2008,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":2,"pct_users":56.2},
  {"year":2008,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":3,"pct_users":55.8},
  {"year":2008,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":51.3},
  {"year":2008,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":46.8},
  {"year":2008,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":6,"pct_users":41.2},
  {"year":2008,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":35.6},
  {"year":2008,"activity":"job searching","gender":"total","age_group":"total 6+","rank":8,"pct_users":25.1},
  {"year":2008,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":31.2},
  {"year":2008,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":10,"pct_users":20.3},
  {"year":2008,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":11,"pct_users":16.8},
  {"year":2009,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":80.5},
  {"year":2009,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":2,"pct_users":57.1},
  {"year":2009,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":3,"pct_users":56.3},
  {"year":2009,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":52.0},
  {"year":2009,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":5,"pct_users":47.5},
  {"year":2009,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":6,"pct_users":45.2},
  {"year":2009,"activity":"social networks","gender":"total","age_group":"total 6+","rank":7,"pct_users":38.4},
  {"year":2009,"activity":"health information","gender":"total","age_group":"total 6+","rank":8,"pct_users":36.2},
  {"year":2009,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":32.1},
  {"year":2009,"activity":"job searching","gender":"total","age_group":"total 6+","rank":10,"pct_users":26.0},
  {"year":2009,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":11,"pct_users":19.8},
  {"year":2009,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":12,"pct_users":15.3},
  {"year":2010,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":80.9},
  {"year":2010,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":2,"pct_users":57.8},
  {"year":2010,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":3,"pct_users":56.9},
  {"year":2010,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":4,"pct_users":53.1},
  {"year":2010,"activity":"social networks","gender":"total","age_group":"total 6+","rank":5,"pct_users":50.2},
  {"year":2010,"activity":"online news","gender":"total","age_group":"total 6+","rank":6,"pct_users":48.7},
  {"year":2010,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":7,"pct_users":44.3},
  {"year":2010,"activity":"health information","gender":"total","age_group":"total 6+","rank":8,"pct_users":37.0},
  {"year":2010,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":33.4},
  {"year":2010,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":27.5},
  {"year":2010,"activity":"job searching","gender":"total","age_group":"total 6+","rank":11,"pct_users":24.8},
  {"year":2010,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":12,"pct_users":18.6},
  {"year":2010,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":13,"pct_users":14.1},
  {"year":2011,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.0},
  {"year":2011,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":2,"pct_users":58.3},
  {"year":2011,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":3,"pct_users":57.2},
  {"year":2011,"activity":"social networks","gender":"total","age_group":"total 6+","rank":4,"pct_users":55.6},
  {"year":2011,"activity":"online news","gender":"total","age_group":"total 6+","rank":5,"pct_users":50.3},
  {"year":2011,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":6,"pct_users":45.9},
  {"year":2011,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":7,"pct_users":42.1},
  {"year":2011,"activity":"health information","gender":"total","age_group":"total 6+","rank":8,"pct_users":38.1},
  {"year":2011,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":34.7},
  {"year":2011,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":28.9},
  {"year":2011,"activity":"job searching","gender":"total","age_group":"total 6+","rank":11,"pct_users":25.2},
  {"year":2011,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":12,"pct_users":17.9},
  {"year":2011,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":13,"pct_users":13.5},
  {"year":2012,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.2},
  {"year":2012,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":2,"pct_users":63.1},
  {"year":2012,"activity":"social networks","gender":"total","age_group":"total 6+","rank":3,"pct_users":61.4},
  {"year":2012,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":4,"pct_users":59.8},
  {"year":2012,"activity":"online news","gender":"total","age_group":"total 6+","rank":5,"pct_users":52.7},
  {"year":2012,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":6,"pct_users":47.2},
  {"year":2012,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":7,"pct_users":43.8},
  {"year":2012,"activity":"health information","gender":"total","age_group":"total 6+","rank":8,"pct_users":39.4},
  {"year":2012,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":35.8},
  {"year":2012,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":29.6},
  {"year":2012,"activity":"web archiving","gender":"total","age_group":"total 6+","rank":11,"pct_users":24.3},
  {"year":2012,"activity":"job searching","gender":"total","age_group":"total 6+","rank":12,"pct_users":22.1},
  {"year":2012,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":13,"pct_users":16.4},
  {"year":2012,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":14,"pct_users":12.8},
  {"year":2013,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.3},
  {"year":2013,"activity":"social networks","gender":"total","age_group":"total 6+","rank":2,"pct_users":68.2},
  {"year":2013,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":3,"pct_users":62.4},
  {"year":2013,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":4,"pct_users":60.1},
  {"year":2013,"activity":"online news","gender":"total","age_group":"total 6+","rank":5,"pct_users":53.8},
  {"year":2013,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":6,"pct_users":48.1},
  {"year":2013,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":7,"pct_users":44.2},
  {"year":2013,"activity":"health information","gender":"total","age_group":"total 6+","rank":8,"pct_users":40.1},
  {"year":2013,"activity":"banking services","gender":"total","age_group":"total 6+","rank":9,"pct_users":36.5},
  {"year":2013,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":30.2},
  {"year":2013,"activity":"web archiving","gender":"total","age_group":"total 6+","rank":11,"pct_users":25.0},
  {"year":2013,"activity":"social / political opinions","gender":"total","age_group":"total 6+","rank":12,"pct_users":20.7},
  {"year":2013,"activity":"job searching","gender":"total","age_group":"total 6+","rank":13,"pct_users":21.4},
  {"year":2013,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":14,"pct_users":15.8},
  {"year":2013,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":15,"pct_users":12.1},
  {"year":2014,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.4},
  {"year":2014,"activity":"social networks","gender":"total","age_group":"total 6+","rank":2,"pct_users":70.1},
  {"year":2014,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":3,"pct_users":65.3},
  {"year":2014,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":55.2},
  {"year":2014,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":49.3},
  {"year":2014,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":6,"pct_users":45.1},
  {"year":2014,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":41.0},
  {"year":2014,"activity":"banking services","gender":"total","age_group":"total 6+","rank":8,"pct_users":37.2},
  {"year":2014,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":9,"pct_users":35.8},
  {"year":2014,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":31.0},
  {"year":2014,"activity":"web archiving","gender":"total","age_group":"total 6+","rank":11,"pct_users":25.8},
  {"year":2014,"activity":"social / political opinions","gender":"total","age_group":"total 6+","rank":12,"pct_users":21.2},
  {"year":2014,"activity":"job searching","gender":"total","age_group":"total 6+","rank":13,"pct_users":20.5},
  {"year":2014,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":14,"pct_users":14.9},
  {"year":2014,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":15,"pct_users":11.6},
  {"year":2014,"activity":"online consultations","gender":"total","age_group":"total 6+","rank":16,"pct_users":8.2},
  {"year":2015,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.5},
  {"year":2015,"activity":"social networks","gender":"total","age_group":"total 6+","rank":2,"pct_users":71.4},
  {"year":2015,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":3,"pct_users":66.8},
  {"year":2015,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":56.1},
  {"year":2015,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":50.2},
  {"year":2015,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":6,"pct_users":45.8},
  {"year":2015,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":41.9},
  {"year":2015,"activity":"banking services","gender":"total","age_group":"total 6+","rank":8,"pct_users":38.0},
  {"year":2015,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":9,"pct_users":36.4},
  {"year":2015,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":31.7},
  {"year":2015,"activity":"web archiving","gender":"total","age_group":"total 6+","rank":11,"pct_users":26.3},
  {"year":2015,"activity":"social / political opinions","gender":"total","age_group":"total 6+","rank":12,"pct_users":21.8},
  {"year":2015,"activity":"job searching","gender":"total","age_group":"total 6+","rank":13,"pct_users":20.0},
  {"year":2015,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":14,"pct_users":14.2},
  {"year":2015,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":15,"pct_users":11.1},
  {"year":2015,"activity":"online consultations","gender":"total","age_group":"total 6+","rank":16,"pct_users":8.9},
  {"year":2016,"activity":"e-mail","gender":"total","age_group":"total 6+","rank":1,"pct_users":81.5},
  {"year":2016,"activity":"social networks","gender":"total","age_group":"total 6+","rank":2,"pct_users":72.3},
  {"year":2016,"activity":"consulting wikis","gender":"total","age_group":"total 6+","rank":3,"pct_users":68.9},
  {"year":2016,"activity":"online news","gender":"total","age_group":"total 6+","rank":4,"pct_users":57.0},
  {"year":2016,"activity":"games, films, music","gender":"total","age_group":"total 6+","rank":5,"pct_users":51.1},
  {"year":2016,"activity":"goods / services info","gender":"total","age_group":"total 6+","rank":6,"pct_users":46.5},
  {"year":2016,"activity":"health information","gender":"total","age_group":"total 6+","rank":7,"pct_users":42.7},
  {"year":2016,"activity":"banking services","gender":"total","age_group":"total 6+","rank":8,"pct_users":38.8},
  {"year":2016,"activity":"travel / accommodation","gender":"total","age_group":"total 6+","rank":9,"pct_users":37.1},
  {"year":2016,"activity":"uploading web content","gender":"total","age_group":"total 6+","rank":10,"pct_users":32.3},
  {"year":2016,"activity":"web archiving","gender":"total","age_group":"total 6+","rank":11,"pct_users":26.9},
  {"year":2016,"activity":"social / political opinions","gender":"total","age_group":"total 6+","rank":12,"pct_users":22.4},
  {"year":2016,"activity":"job searching","gender":"total","age_group":"total 6+","rank":13,"pct_users":19.6},
  {"year":2016,"activity":"downloading software","gender":"total","age_group":"total 6+","rank":14,"pct_users":13.8},
  {"year":2016,"activity":"selling goods / services","gender":"total","age_group":"total 6+","rank":15,"pct_users":10.8},
  {"year":2016,"activity":"online consultations","gender":"total","age_group":"total 6+","rank":16,"pct_users":9.4}
];

// ── Column Name Constants (update to match your data) ──
const YEAR_FIELD       = 'year';
const ACTIVITY_FIELD   = 'activity';
const GENDER_FIELD     = 'gender';
const AGE_GROUP_FIELD  = 'age_group';
const RANK_FIELD       = 'rank';
const PCT_USERS_FIELD  = 'pct_users';

// ── Color palette per activity (matches original chart) ──
const ACTIVITY_COLORS = {
  'e-mail':                      '#1FB8CD',
  'social networks':             '#E84855',
  'consulting wikis':            '#D32F4A',
  'online news':                 '#2E9F6B',
  'games, films, music':         '#6BA644',
  'goods / services info':       '#22B8A8',
  'health information':          '#C5C541',
  'banking services':            '#5586C7',
  'travel / accommodation':      '#1a8fa8',
  'uploading web content':       '#3D6B9C',
  'web archiving':               '#F4B5C9',
  'social / political opinions': '#c0392b',
  'job searching':               '#E89249',
  'downloading software':        '#9DA642',
  'selling goods / services':    '#D8472E',
  'online consultations':        '#B57FC9',
};

const DEFAULT_COLOR = '#999999';

// ── Load DataModel ──
const formattedData = DataModel.loadDataSync(data, schema);
const dm = new DataModel(formattedData);

// ── Extract structured data from DataModel ──
const rawResult = dm.getData();
const rawCols   = rawResult.schema.map(s => s.name);
const rawRows   = rawResult.data.map(row => {
  const obj = {};
  rawCols.forEach((col, i) => { obj[col] = row[i]; });
  return obj;
});

// ── Build per-activity series: { activityName -> { year -> { rank, pct } } } ──
const allYears     = [...new Set(rawRows.map(r => r[YEAR_FIELD]))].sort((a, b) => a - b);
const allActivities = [...new Set(rawRows.map(r => r[ACTIVITY_FIELD]))];

const seriesMap = {};
allActivities.forEach(act => { seriesMap[act] = {}; });
rawRows.forEach(r => {
  seriesMap[r[ACTIVITY_FIELD]][r[YEAR_FIELD]] = {
    rank: r[RANK_FIELD],
    pct:  r[PCT_USERS_FIELD]
  };
});

// ── Build Chart.js datasets ──
function buildDatasets(activityNames) {
  return activityNames.map(act => {
    const color = ACTIVITY_COLORS[act] || DEFAULT_COLOR;
    return {
      label: act,
      data: allYears.map(y => (seriesMap[act][y] ? seriesMap[act][y].rank : null)),
      pctData: allYears.map(y => (seriesMap[act][y] ? seriesMap[act][y].pct  : null)),
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2.5,
      tension: 0,
      pointRadius: 3,
      pointHoverRadius: 6,
      spanGaps: false,
    };
  });
}

// ── Endpoint label plugin ──
// Draws activity name + rank badge on the left and right chart edges.
// A series is labeled at an edge only if its line actually reaches that edge —
// series that enter (or drop out) mid-chart would otherwise be drawn at the
// edge on top of another series holding the same rank there.
const endpointLabelPlugin = {
  id: 'endpointLabels',
  afterDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    const datasets = chart.data.datasets;
    const lastSlot = allYears.length - 1;

    // Collect left/right label info
    const leftLabels  = [];
    const rightLabels = [];

    datasets.forEach(ds => {
      const firstIdx = ds.data.findIndex(v => v != null);
      if (firstIdx === -1) return;
      const lastIdx = ds.data.length - 1 - [...ds.data].reverse().findIndex(v => v != null);

      if (firstIdx === 0) {
        leftLabels.push({ name: ds.label, rank: ds.data[0], color: ds.borderColor });
      }
      if (lastIdx === lastSlot) {
        rightLabels.push({ name: ds.label, rank: ds.data[lastIdx], color: ds.borderColor });
      }
    });

    const nameFont  = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const badgeFont = 'bold 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const textColor = '#2C2C2A';
    const badgeGap  = 7; // px between rank badge and activity name

    ctx.save();
    ctx.textBaseline = 'middle';

    // Left labels
    leftLabels.forEach(l => {
      const y = scales.y.getPixelForValue(l.rank);
      // Color swatch
      ctx.fillStyle = l.color;
      ctx.fillRect(chartArea.left - 7, y - 6, 5, 12);
      // Rank badge
      ctx.font = badgeFont;
      const badgeW = ctx.measureText(String(l.rank)).width;
      ctx.textAlign = 'right';
      ctx.fillText(String(l.rank), chartArea.left - 14, y);
      // Activity name — offset by the measured badge width so 2-digit ranks
      // don't run into the name
      ctx.fillStyle = textColor;
      ctx.font = nameFont;
      ctx.fillText(l.name, chartArea.left - 14 - badgeW - badgeGap, y);
    });

    // Right labels
    rightLabels.forEach(l => {
      const y = scales.y.getPixelForValue(l.rank);
      // Color swatch
      ctx.fillStyle = l.color;
      ctx.fillRect(chartArea.right + 2, y - 6, 5, 12);
      // Rank badge
      ctx.font = badgeFont;
      const badgeW = ctx.measureText(String(l.rank)).width;
      ctx.textAlign = 'left';
      ctx.fillText(String(l.rank), chartArea.right + 12, y);
      // Activity name — offset by the measured badge width
      ctx.fillStyle = textColor;
      ctx.font = nameFont;
      ctx.fillText(l.name, chartArea.right + 12 + badgeW + badgeGap, y);
    });

    ctx.restore();
  }
};

// ── Dynamically load Chart.js ──
// ThoughtSpot: Remove the dynamic loading block below and add the CDN URL to the HTML tab instead
const cjsScript = document.createElement('script');
cjsScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
await new Promise((resolve, reject) => {
  cjsScript.onload = resolve;
  cjsScript.onerror = reject;
  document.head.appendChild(cjsScript);
});

// ── Render chart ──
let chartInstance = null;

function renderBumpChart(activityNames) {
  const canvas = document.getElementById('bumpChart');
  if (!canvas) return;

  if (chartInstance) {
    chartInstance.destroy();
    chartInstance = null;
  }

  const maxRank = Math.max(...activityNames.map(act =>
    Math.max(...Object.values(seriesMap[act]).map(v => v.rank))
  ));

  chartInstance = new Chart(canvas, {
    type: 'line',
    data: {
      labels: allYears,
      datasets: buildDatasets(activityNames),
    },
    plugins: [endpointLabelPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: {
        padding: { left: 215, right: 215, top: 8, bottom: 8 }
      },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title:  (items) => `Year ${items[0].label}`,
            label:  (item) => {
              const pct = item.dataset.pctData[item.dataIndex];
              const rank = item.parsed.y;
              if (rank == null) return null;
              return `${item.dataset.label}: rank ${rank}${pct != null ? `  (${pct}% of users)` : ''}`;
            },
            filter: (item) => item.parsed.y != null,
          },
          itemSort: (a, b) => a.parsed.y - b.parsed.y,
        }
      },
      scales: {
        y: {
          reverse: true,
          min: 0.5,
          max: maxRank + 0.5,
          ticks: { display: false, stepSize: 1 },
          grid:   { display: false },
          border: { display: false },
        },
        x: {
          ticks: {
            color: '#5F5E5A',
            font: { size: 12 }
          },
          grid:   { display: false },
          border: { display: false },
        }
      }
    }
  });
}

// ── Initial render with all activities ──
renderBumpChart(allActivities);

// ThoughtSpot: Uncomment the line below to signal render completion
 viz.events.emitRenderCompletedEvent();
