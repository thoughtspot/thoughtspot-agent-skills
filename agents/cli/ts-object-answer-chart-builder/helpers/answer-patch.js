// Sandbox side of answer-pack.mjs. Never run by hand: answer-pack.mjs prints this file with PAYLOAD and MODE
// filled in, and the result is pasted as the `code` of execute-thoughtspot-code.
//
// Each run:
//   1. checks the three chart files against their sha256 (a mistyped paste is refused, nothing is written);
//   2. resolves the model, and runs the search once for its column names;
//   3. builds one answer TML with a MUZE_STUDIO chart carrying the files. With a guid it merges into that
//      answer's exported TML. It sets the search, the chart type and code, and the column lists; it keeps
//      everything else: formulas, parameters, the per-column settings (formats) of columns still in the
//      search, the table view's settings, the tables when they include the model, and other top-level keys.
//      The summary lists what was kept (`kept`) and what was replaced (`replaced`), so nothing goes silently;
//   4. imports (VALIDATE_ONLY, then ALL_OR_NONE for a commit; an update commits only with a backup named by
//      answer-pack --backup), and after a commit exports the answer and proves it carries exactly the files
//      that were sent and still has every formula and parameter it had.
// It creates nothing but the answer the user asked for.
const MODE = '__MODE__'; // 'validate' | 'commit'
const P = __PAYLOAD__;

const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
const unb64 = (s) => decodeURIComponent(escape(atob(s)));
const sha256 = async (s) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))].map((b) => b.toString(16).padStart(2, '0')).join('');

// 1. checksums
const badSha = [];
for (const k of ['html', 'css', 'js']) if ((await sha256(P.f[k])) !== P.sha[k]) badSha.push(k);
if (P.backup && (await sha256(JSON.stringify(P.backup))) !== P.backupSha) badSha.push('backup');
if (badSha.length) return { refused: 'CHECKSUM MISMATCH - nothing written, resend this block unchanged', badSha };

// 2. model and columns
const ms = await ts.post('/api/rest/2.0/metadata/search', { metadata: [{ type: 'LOGICAL_TABLE', identifier: P.model }], record_size: 2 });
if (ms.status !== 200 || !ms.body || !ms.body.length) return { refused: 'model not found: ' + P.model, http: ms.status };
const model = { guid: ms.body[0].metadata_id, name: ms.body[0].metadata_name };
const q = await ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: model.guid, query_string: P.search, record_size: 1 });
const cn = q.status === 200 && q.body && q.body.contents && q.body.contents[0] && q.body.contents[0].column_names;
const cols = Array.isArray(cn) && cn.length ? cn : null; // no columns is a failed search, not an empty chart
if (!cols) return { refused: 'search failed on ' + model.name + ': ' + P.search, raw: JSON.stringify(q.body).slice(0, 600) };
let old = null;
if (P.guid) {
  const ex0 = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: P.guid, type: 'ANSWER' }], edoc_format: 'JSON' });
  if (ex0.status !== 200 || !ex0.body || !ex0.body[0] || !ex0.body[0].edoc) return { refused: 'answer ' + P.guid + ' not found or not exportable', http: ex0.status };
  old = JSON.parse(ex0.body[0].edoc).answer;
}

// 3. compose
const MEASURE = /^(Total|Average|Unique Number|Max|Min|Count|Sum)\b/i;
const ordered = [...cols.filter((c) => !MEASURE.test(c)), ...cols.filter((c) => MEASURE.test(c))];
const cvp = JSON.stringify({
  clientState: JSON.stringify({ version: 1, playground: { version: 'v1', code: { jsCodeBase64: b64(P.f.js), cssCodeBase64: b64(P.f.css), htmlCodeBase64: b64(P.f.html) }, splitSizes: [55], editorConsoleSplitSizes: [99] } }),
  axisVisualProps: {}, columnVisualProps: {}, dataLabelVisualProps: {}, tooltipVisualProps: {}, legendVisualProps: {}, displayVisualProps: {}
});
const answer = {
  name: P.name, tables: [{ id: model.name, name: model.name, fqn: model.guid }], search_query: P.search,
  answer_columns: cols.map((c) => ({ name: c })),
  table: { table_columns: cols.map((c) => ({ column_id: c })), ordered_column_ids: cols, client_state: '', client_state_v2: JSON.stringify({ tableVizPropVersion: 'V1' }) },
  chart: {
    type: 'MUZE_STUDIO', chart_columns: cols.map((c) => ({ column_id: c })), client_state: '',
    client_state_v2: JSON.stringify({ version: 'V4DOT2', chartProperties: { chartSpecific: { dataFieldArea: 'column' } }, columnProperties: [], axisProperties: [] }),
    custom_chart_config: [{ key: 'basic', dimensions: [{ key: 'fields', columns: ordered, mode: 'COLUMN_DRIVEN' }] }], custom_visual_props: cvp
  },
  display_mode: 'CHART_MODE'
};
if (P.description) answer.description = P.description;
// Updating: start from what the answer already has. Chart settings carry over only from a custom chart; a
// native chart's axes would not fit this one (they are listed under `replaced`).
let merged = answer;
const kept = [], replaced = [];
if (old) {
  const byName = (xs, k) => Object.fromEntries((xs || []).map((x) => [x[k], x]));
  const oldCols = byName(old.answer_columns, 'name');
  const keepCols = cols.filter((c) => oldCols[c] && Object.keys(oldCols[c]).length > 1);
  const oldTable = old.table || null, oldTc = byName(oldTable && oldTable.table_columns, 'column_id');
  const oldChart = old.chart && old.chart.type === 'MUZE_STUDIO' ? old.chart : null;
  const oldCc = byName(oldChart && oldChart.chart_columns, 'column_id');
  // The old tables are kept only when they point at this model: by fqn when they have one, by name otherwise.
  const tablesOk = (old.tables || []).some((t) => (t.fqn ? t.fqn === model.guid : t.id === model.name || t.name === model.name));
  merged = {
    ...old, ...answer,
    name: answer.name, search_query: answer.search_query,
    tables: tablesOk ? old.tables : answer.tables,
    answer_columns: cols.map((c) => oldCols[c] || { name: c }),
    table: oldTable ? { ...oldTable, table_columns: cols.map((c) => oldTc[c] || { column_id: c }), ordered_column_ids: cols } : answer.table,
    chart: { ...(oldChart || {}), ...answer.chart, chart_columns: cols.map((c) => oldCc[c] || { column_id: c }), custom_visual_props: answer.chart.custom_visual_props }
  };
  if (oldChart && oldChart.client_state_v2) merged.chart.client_state_v2 = oldChart.client_state_v2;
  for (const k of Object.keys(old)) if (!(k in answer)) kept.push(k);
  if (keepCols.length) kept.push('answer_columns settings: ' + keepCols.join(', '));
  if (oldTable) kept.push('table settings');
  if (tablesOk) kept.push('tables');
  if (oldChart) kept.push('custom chart settings');
  const gone = (old.answer_columns || []).map((c) => c.name).filter((n) => !cols.includes(n));
  if (gone.length) replaced.push('columns no longer in the search: ' + gone.join(', '));
  if (old.search_query !== answer.search_query) replaced.push('search_query');
  if (old.name !== answer.name) replaced.push('name');
  if (!tablesOk && old.tables) replaced.push('tables (the model changed)');
  if (old.chart && !oldChart) replaced.push('chart: a native ' + old.chart.type + ' chart and its settings');
  if (old.display_mode && old.display_mode !== answer.display_mode) replaced.push('display_mode ' + old.display_mode);
  if (oldChart) {
    // The old custom chart's code and visual settings (columns, legend, labels...) and its field mapping.
    if (oldChart.custom_visual_props && oldChart.custom_visual_props !== answer.chart.custom_visual_props) replaced.push('custom chart code and visual settings (custom_visual_props)');
    if (oldChart.custom_chart_config && JSON.stringify(oldChart.custom_chart_config) !== JSON.stringify(answer.chart.custom_chart_config)) replaced.push('custom chart field mapping (custom_chart_config)');
  }
  if (P.description !== undefined && old.description && old.description !== P.description) replaced.push('description');
}
const tml = P.guid ? { guid: P.guid, answer: merged } : { answer };
const text = JSON.stringify(tml);
const summary = { mode: MODE, model: model.name, columns: cols, tmlKB: Math.round(text.length / 1024) };
if (old) { summary.kept = kept; summary.replaced = replaced; }

// 4. import and prove. A commit validates first in the same call, so one paste does both.
const importAs = async (policy) => {
  const imp = await ts.post('/api/rest/2.0/metadata/tml/import', { metadata_tmls: [text], import_policy: policy, create_new: !P.guid });
  return { r: imp.body && imp.body[0] && imp.body[0].response, raw: imp.body };
};
const v = await importAs('VALIDATE_ONLY');
summary.validate = v.r && v.r.status;
if (!v.r || !v.r.status || v.r.status.status_code !== 'OK') { summary.raw = JSON.stringify(v.raw).slice(0, 1200); return summary; }
if (MODE !== 'commit') return summary;
if (P.guid && !P.backup) { summary.refused = 'NOT COMMITTED - updating an answer needs a backup of it first: export its TML and build the block with --backup <file>'; return summary; }
// The backup must be of the answer as it is now.
if (P.guid && P.backup.search !== (old.search_query || '')) { summary.refused = 'NOT COMMITTED - the backup ' + P.backup.file + ' is not of this answer as it is now (its search differs); export it again'; return summary; }
const c = await importAs('ALL_OR_NONE');
const r0 = c.r;
summary.import = r0 && r0.status;
if (!r0 || !r0.status || r0.status.status_code !== 'OK') { summary.raw = JSON.stringify(c.raw).slice(0, 1200); return summary; }
if (MODE === 'commit') {
  const guid = (r0.header && (r0.header.id_guid || r0.header.id)) || P.guid;
  summary.guid = guid;
  let back;
  try {
    const ex = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: guid, type: 'ANSWER' }], edoc_format: 'JSON' });
    back = JSON.parse(ex.body[0].edoc).answer;
  } catch (e) {
    summary.roundTripOk = false;
    summary.roundTripError = 'the commit landed but the answer could not be exported to check it (' + String(e && e.message || e).slice(0, 200) + '); open it, and restore from the backup if anything is wrong';
    return summary;
  }
  const failed = [];
  let code = null;
  try { code = JSON.parse(JSON.parse(back.chart.custom_visual_props).clientState).playground.code; } catch (e) { failed.push('chart code unreadable'); }
  if (code) {
    const got = { html: await sha256(unb64(code.htmlCodeBase64 || '')), css: await sha256(unb64(code.cssCodeBase64 || '')), js: await sha256(unb64(code.jsCodeBase64 || '')) };
    for (const k of ['html', 'css', 'js']) if (got[k] !== P.sha[k]) failed.push(k);
  }
  summary.chartType = back.chart && back.chart.type;
  // What the update kept must come back as it was sent: formulas, parameters, the settings of kept columns, the
  // table view's settings. Fields ThoughtSpot adds on re-export are allowed, and key order never matters.
  const covers = (b, a) => {
    if (b === null || typeof b !== 'object') return b === a || b === undefined;
    if (Array.isArray(b)) return Array.isArray(a) && a.length === b.length && b.every((x, i) => covers(x, a[i]));
    return !!a && typeof a === 'object' && !Array.isArray(a) && Object.keys(b).every((k) => b[k] === undefined || covers(b[k], a[k]));
  };
  const byName = (a, k) => Object.fromEntries(((a && a[k]) || []).map((x) => [x.name || x.id || x.column_id, x]));
  for (const k of ['formulas', 'parameters']) {
    const want = byName(old, k), have = byName(back, k);
    const miss = Object.keys(want).filter((n) => !(n in have)), diff = Object.keys(want).filter((n) => n in have && !covers(want[n], have[n]));
    if (miss.length) failed.push(k + ' lost: ' + miss.join(', '));
    if (diff.length) failed.push(k + ' changed: ' + diff.join(', '));
  }
  if (old) {
    const sentCols = byName(merged, 'answer_columns'), backCols = byName(back, 'answer_columns');
    const badCols = Object.keys(sentCols).filter((n) => !covers(sentCols[n], backCols[n]));
    if (badCols.length) failed.push('column settings changed: ' + badCols.join(', '));
    if (merged.table && !covers({ ...merged.table, table_columns: undefined, ordered_column_ids: undefined }, back.table)) failed.push('table settings changed');
  }
  summary.roundTripOk = !failed.length;
  if (failed.length) summary.roundTripFailed = failed;
}
return summary;
