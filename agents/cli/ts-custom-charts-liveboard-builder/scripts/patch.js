// Sandbox side of liveboard-pack.mjs. Never run by hand: liveboard-pack.mjs prints this file with PAYLOAD and
// MODE filled in, and the result is pasted as the `code` of execute-thoughtspot-code.
//
// The target Liveboard is its own store. Each run:
//   1. checks every chart it carries against its sha256 (a mistyped paste is refused, nothing is written);
//   2. exports the Liveboard and indexes its tiles by the slug marker in their code
//      (tiles imported before markers existed are matched by tab and grid position);
//   3. builds the whole Liveboard from the spec: charts in this payload replace their tile, every other tile
//      keeps the code it already has, spec tiles with no code yet are left out and reported;
//   4. imports (VALIDATE_ONLY or ALL_OR_NONE), and after a commit exports again and proves every tile
//      carries the code that was composed.
// It creates no other object in ThoughtSpot.
const MODE = '__MODE__'; // 'validate' | 'commit' | 'check'
const P = __PAYLOAD__;

const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
const unb64 = (s) => decodeURIComponent(escape(atob(s)));
const sha256 = async (s) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))].map((b) => b.toString(16).padStart(2, '0')).join('');
const END_JS = '/* ==== end amuzing core ==== */', END_CSS = '/* ==== end amuzing core css ==== */';
const MARK = /\/\* amuzing-slug: ([\w-]+) \*\//;

// 1. checksums
const badSha = [];
for (const [slug, t] of Object.entries(P.tiles)) for (const k of Object.keys(t.sha)) if ((await sha256(t.f[k])) !== t.sha[k]) badSha.push(slug + '.' + k);
if (P.core) for (const k of ['js', 'css']) if ((await sha256(P.core[k])) !== P.core.sha[k]) badSha.push('core.' + k);
if (badSha.length) return { refused: 'CHECKSUM MISMATCH - nothing written, resend this block unchanged', badSha };

// 2. current Liveboard
const spec = P.spec, LB = spec.liveboard, model = LB.model;
const ex0 = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
if (ex0.status !== 200 || !ex0.body || !ex0.body[0] || !ex0.body[0].edoc) return { refused: 'Liveboard ' + LB.guid + ' not found or not exportable; create it first (an empty Liveboard is enough)', http: ex0.status };
const doc0 = JSON.parse(ex0.body[0].edoc).liveboard;
const bySlug = {}, byPos = {};
const vizById = {}; (doc0.visualizations || []).forEach((v) => { vizById[v.id] = v; });
for (const tab of ((doc0.layout && doc0.layout.tabs) || [])) for (const tl of tab.tiles || []) {
  const v = vizById[tl.visualization_id]; if (!v || !v.answer || !v.answer.chart || !v.answer.chart.custom_visual_props) continue;
  const code = JSON.parse(JSON.parse(v.answer.chart.custom_visual_props).clientState).playground.code;
  const c = { js: unb64(code.jsCodeBase64), css: unb64(code.cssCodeBase64), html: unb64(code.htmlCodeBase64) };
  const m = MARK.exec(c.js); if (m) bySlug[m[1]] = c;
  byPos[tab.name + '|' + tl.x + '|' + tl.y] = c;
}
const core = P.core ? { js: P.core.js, css: P.core.css } : null; // every block carries the (trimmed) shared core
const bodyOf = (c) => ({ js: c.js.slice(c.js.indexOf(END_JS) + END_JS.length), css: c.css.slice(c.css.indexOf(END_CSS) + END_CSS.length) });

// read-only drift check: live tile body against the local body
if (MODE === 'check') {
  const stale = [], missing = [], ok = [];
  for (const tab of spec.tabs) for (const t of tab.tiles) {
    const want = P.bodySha[t.slug]; if (!want) continue;
    const c = bySlug[t.slug] || byPos[tab.name + '|' + t.x + '|' + t.y];
    if (!c) { missing.push(t.slug); continue; }
    const b = bodyOf(c);
    // tiles imported before this scheme had their CSS comments (and so the core marker) stripped: compare whole CSS
    const h16 = async (x) => (await sha256(x)).slice(0, 16);
    const legacy = c.css.indexOf(END_CSS) < 0;
    const got = { js: await h16(b.js.replace(MARK, '').trim()), css: legacy ? await h16(c.css) : await h16(b.css.trim()), html: await h16(c.html) };
    if (legacy) want.css = want.cssLegacy;
    const diff = ['js', 'css', 'html'].filter((k) => got[k] !== want[k]);
    if (diff.length) stale.push(t.slug + ' (' + diff.join(',') + (bySlug[t.slug] ? '' : ', matched by position') + ')'); else ok.push(t.slug);
  }
  return { stale, missing, ok: ok.length };
}

// 3. compose
const MEASURE = /^(Total|Average|Unique Number|Max|Min|Count|Sum)\b/i;
const CSV2 = JSON.stringify({ version: 'V4DOT2', chartProperties: { chartSpecific: { dataFieldArea: 'column' } }, columnProperties: [], axisProperties: [] });
const COLS = {}, vizzes = [], tabs = [], report = [], excluded = [];
for (const tab of spec.tabs) {
  const tiles = [];
  for (const t of tab.tiles) {
    let code, from;
    if (P.tiles[t.slug]) { const f = P.tiles[t.slug].f; code = { js: core.js + '\n' + f.js, css: core.css + '\n' + f.css, html: f.html }; from = 'payload'; }
    else if (bySlug[t.slug]) { code = bySlug[t.slug]; from = 'kept'; }
    else if (byPos[tab.name + '|' + t.x + '|' + t.y]) { code = byPos[tab.name + '|' + t.x + '|' + t.y]; from = 'kept (position)'; }
    else { report.push({ slug: t.slug, from: 'MISSING - not on the Liveboard and not in this payload' }); continue; }
    if (!(t.search in COLS)) {
      const q = await ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: model.guid, query_string: t.search, record_size: 1 });
      COLS[t.search] = q.status === 200 && q.body.contents && q.body.contents[0] ? q.body.contents[0].column_names : null;
    }
    const cols = COLS[t.search];
    if (!cols) { report.push({ slug: t.slug, from: 'SEARCH FAILED: ' + t.search }); continue; }
    const ordered = [...cols.filter((c) => !MEASURE.test(c)), ...cols.filter((c) => MEASURE.test(c))];
    const cvp = JSON.stringify({
      clientState: JSON.stringify({ version: 1, playground: { version: 'v1', code: { jsCodeBase64: b64(code.js), cssCodeBase64: b64(code.css), htmlCodeBase64: b64(code.html) }, splitSizes: [55], editorConsoleSplitSizes: [99] } }),
      axisVisualProps: {}, columnVisualProps: {}, dataLabelVisualProps: {}, tooltipVisualProps: {}, legendVisualProps: {}, displayVisualProps: {}
    });
    const answer = {
      name: t.title, tables: [{ id: model.name, name: model.name, fqn: model.guid }], search_query: t.search,
      answer_columns: cols.map((c) => ({ name: c })),
      table: { table_columns: cols.map((c) => ({ column_id: c })), ordered_column_ids: cols, client_state: '', client_state_v2: JSON.stringify({ tableVizPropVersion: 'V1' }) },
      chart: { type: 'MUZE_STUDIO', chart_columns: cols.map((c) => ({ column_id: c })), client_state: '', client_state_v2: CSV2, custom_chart_config: [{ key: 'basic', dimensions: [{ key: 'fields', columns: ordered, mode: 'COLUMN_DRIVEN' }] }], custom_visual_props: cvp },
      display_mode: 'CHART_MODE'
    };
    if (t.description) answer.description = t.description;
    const id = 'Viz_' + (vizzes.length + 1);
    vizzes.push({ id, answer });
    if (t.filters === false) excluded.push(id);
    tiles.push({ visualization_id: id, x: t.x, 'y': t.y, height: t.h, width: t.w });
    report.push({ slug: t.slug, from, js: (await sha256(code.js)).slice(0, 12), css: (await sha256(code.css)).slice(0, 12) });
  }
  tabs.push({ name: tab.name, description: tab.description || '', tiles });
}
const filters = (spec.filters || []).map((f) => {
  const o = { column: [f.column], is_mandatory: false, is_single_value: !!f.single, display_name: f.label || '' };
  if (excluded.length && f.applyToNarrative === false) o.excluded_visualizations = excluded;
  if (f.date) o.date_filter = f.date;
  return o;
});
const text = JSON.stringify({ guid: LB.guid, liveboard: { name: LB.name, description: LB.description || '', visualizations: vizzes, filters, layout: { tabs }, ordered_chips: (spec.filters || []).map((f) => ({ name: f.column, type: 'FILTER' })), style: { style_properties: spec.style || [] } } });
const summary = {
  mode: MODE, tmlKB: Math.round(text.length / 1024), tiles: vizzes.length,
  replaced: report.filter((r) => r.from === 'payload').map((r) => r.slug),
  keptByPosition: report.filter((r) => r.from === 'kept (position)').length,
  problems: report.filter((r) => /MISSING|FAILED/.test(r.from))
};
if (summary.tmlKB > 2000) summary.warning = 'TML over 2 MB; imports near 2.8 MB have reset the connection';

// 4. import and prove
const imp = await ts.post('/api/rest/2.0/metadata/tml/import', { metadata_tmls: [text], import_policy: MODE === 'commit' ? 'ALL_OR_NONE' : 'VALIDATE_ONLY', create_new: false });
const r0 = imp.body && imp.body[0] && imp.body[0].response;
summary.import = r0 && r0.status;
if (!r0 || !r0.status || r0.status.status_code !== 'OK') { summary.raw = JSON.stringify(imp.body).slice(0, 1200); return summary; }
if (MODE === 'commit') {
  const ex = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
  const back = [];
  for (const v of JSON.parse(ex.body[0].edoc).liveboard.visualizations) {
    if (!v.answer || !v.answer.chart) continue;
    const code = JSON.parse(JSON.parse(v.answer.chart.custom_visual_props).clientState).playground.code;
    back.push({ js: (await sha256(unb64(code.jsCodeBase64))).slice(0, 12), css: (await sha256(unb64(code.cssCodeBase64))).slice(0, 12) });
  }
  const built = report.filter((r) => r.js); // ThoughtSpot may renumber viz ids, so compare in order
  summary.roundTripAllOk = built.length === back.length && built.every((r, i) => back[i] && back[i].js === r.js && back[i].css === r.css);
  if (!summary.roundTripAllOk) summary.roundTripFailed = built.filter((r, i) => !back[i] || back[i].js !== r.js || back[i].css !== r.css).map((r) => r.slug);
}
return summary;
