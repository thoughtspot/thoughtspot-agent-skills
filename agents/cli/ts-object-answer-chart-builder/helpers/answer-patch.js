// Sandbox side of answer-pack.mjs. Never run by hand: answer-pack.mjs prints this file with PAYLOAD and MODE
// filled in, and the result is pasted as the `code` of execute-thoughtspot-code.
//
// Each run:
//   1. checks the three chart files against their sha256 (a mistyped paste is refused, nothing is written);
//   2. resolves the model, and runs the search once for its column names;
//   3. builds one answer TML with a MUZE_STUDIO chart carrying the files. With a guid it merges into that
//      answer's exported TML: the search, columns and chart are replaced, and everything else it has (formulas,
//      parameters, other settings) is kept;
//   4. imports (VALIDATE_ONLY or ALL_OR_NONE), and after a commit exports the answer and proves it carries
//      exactly the files that were sent.
// It creates nothing but the answer the user asked for.
const MODE = '__MODE__'; // 'validate' | 'commit'
const P = __PAYLOAD__;

const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
const unb64 = (s) => decodeURIComponent(escape(atob(s)));
const sha256 = async (s) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))].map((b) => b.toString(16).padStart(2, '0')).join('');

// 1. checksums
const badSha = [];
for (const k of ['html', 'css', 'js']) if ((await sha256(P.f[k])) !== P.sha[k]) badSha.push(k);
if (badSha.length) return { refused: 'CHECKSUM MISMATCH - nothing written, resend this block unchanged', badSha };

// 2. model and columns
const ms = await ts.post('/api/rest/2.0/metadata/search', { metadata: [{ type: 'LOGICAL_TABLE', identifier: P.model }], record_size: 2 });
if (ms.status !== 200 || !ms.body || !ms.body.length) return { refused: 'model not found: ' + P.model, http: ms.status };
const model = { guid: ms.body[0].metadata_id, name: ms.body[0].metadata_name };
const q = await ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: model.guid, query_string: P.search, record_size: 1 });
const cols = q.status === 200 && q.body.contents && q.body.contents[0] ? q.body.contents[0].column_names : null;
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
// Updating: start from what the answer already has, so formulas, parameters and other settings survive. Chart
// settings carry over only from a custom chart; a native chart's axes would not fit this one.
const oldChart = old && old.chart && old.chart.type === 'MUZE_STUDIO' ? old.chart : {};
const merged = old ? { ...old, ...answer, chart: { ...oldChart, ...answer.chart } } : answer;
const tml = P.guid ? { guid: P.guid, answer: merged } : { answer };
const text = JSON.stringify(tml);
const summary = { mode: MODE, model: model.name, columns: cols, tmlKB: Math.round(text.length / 1024) };
if (old) summary.keptFromAnswer = Object.keys(old).filter((k) => !(k in answer));

// 4. import and prove. A commit validates first in the same call, so one paste does both.
const importAs = async (policy) => {
  const imp = await ts.post('/api/rest/2.0/metadata/tml/import', { metadata_tmls: [text], import_policy: policy, create_new: !P.guid });
  return { r: imp.body && imp.body[0] && imp.body[0].response, raw: imp.body };
};
const v = await importAs('VALIDATE_ONLY');
summary.validate = v.r && v.r.status;
if (!v.r || !v.r.status || v.r.status.status_code !== 'OK') { summary.raw = JSON.stringify(v.raw).slice(0, 1200); return summary; }
if (MODE !== 'commit') return summary;
const c = await importAs('ALL_OR_NONE');
const r0 = c.r;
summary.import = r0 && r0.status;
if (!r0 || !r0.status || r0.status.status_code !== 'OK') { summary.raw = JSON.stringify(c.raw).slice(0, 1200); return summary; }
if (MODE === 'commit') {
  const guid = (r0.header && (r0.header.id_guid || r0.header.id)) || P.guid;
  summary.guid = guid;
  const ex = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: guid, type: 'ANSWER' }], edoc_format: 'JSON' });
  const back = JSON.parse(ex.body[0].edoc).answer;
  const code = JSON.parse(JSON.parse(back.chart.custom_visual_props).clientState).playground.code;
  const got = { html: await sha256(unb64(code.htmlCodeBase64)), css: await sha256(unb64(code.cssCodeBase64)), js: await sha256(unb64(code.jsCodeBase64)) };
  summary.chartType = back.chart.type;
  summary.roundTripOk = ['html', 'css', 'js'].every((k) => got[k] === P.sha[k]);
  if (!summary.roundTripOk) summary.roundTripFailed = ['html', 'css', 'js'].filter((k) => got[k] !== P.sha[k]);
}
return summary;
