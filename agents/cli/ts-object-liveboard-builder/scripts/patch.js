// Sandbox side of liveboard-pack.mjs. Never run by hand: liveboard-pack.mjs prints this file with PAYLOAD and
// MODE filled in, and the result is pasted as the `code` of execute-thoughtspot-code.
//
// The target Liveboard is its own store. Each run:
//   1. checks every chart it carries against its sha256 (a mistyped paste is refused, nothing is written);
//   2. exports the Liveboard and indexes its tiles by the slug marker in their code
//      (tiles imported before markers existed are matched by tab and grid position);
//   3. merges into the exported TML. The skill owns only the custom-chart tiles that carry the amuzing core:
//      charts in this payload replace their tile, owned tiles keep the code they have, owned tiles no longer
//      in the spec are removed, spec tiles with no code yet are left out and reported. Everything else on the
//      Liveboard (native charts, notes, other custom charts, tabs, filters, parameters, style) is kept as it is;
//   4. imports (VALIDATE_ONLY or ALL_OR_NONE), and after a commit exports again and proves every owned tile
//      carries the code that was composed and every other visualization is still there.
// It creates no other object in ThoughtSpot.
const MODE = '__MODE__'; // 'validate' | 'commit' | 'check'
const P = __PAYLOAD__;

const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
const unb64 = (s) => decodeURIComponent(escape(atob(s)));
const sha256 = async (s) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))].map((b) => b.toString(16).padStart(2, '0')).join('');
const END_JS = '/* ==== end amuzing core ==== */', END_CSS = '/* ==== end amuzing core css ==== */';
const MARK = /\/\* amuzing-slug: ([\w-]+) \*\//;
// Chart code of a custom-chart visualization, or null for anything else (native chart, note, unreadable props).
const codeOf = (v) => {
  const p = v && v.answer && v.answer.chart && v.answer.chart.custom_visual_props;
  if (!p) return null;
  try {
    const code = JSON.parse(JSON.parse(p).clientState).playground.code;
    return { js: unb64(code.jsCodeBase64 || ''), css: unb64(code.cssCodeBase64 || ''), html: unb64(code.htmlCodeBase64 || '') };
  } catch (e) { return null; }
};
const owns = (c) => !!c && c.js.indexOf(END_JS) >= 0;

// 1. checksums
const badSha = [];
for (const [slug, t] of Object.entries(P.tiles)) if (t.sha) for (const k of Object.keys(t.sha)) if ((await sha256(t.f[k])) !== t.sha[k]) badSha.push(slug + '.' + k);
// The spec sets every title, search and position on the Liveboard, so a slip in it is checked like chart code.
if (P.specSha && (await sha256(JSON.stringify(P.spec))) !== P.specSha) badSha.push('spec');
if (P.core && !P.core.ref) for (const k of ['js', 'css']) if ((await sha256(P.core[k])) !== P.core.sha[k]) badSha.push('core.' + k);
if (badSha.length) return { refused: 'CHECKSUM MISMATCH - nothing written, resend this block unchanged', badSha };

// 2. current Liveboard
const spec = P.spec, LB = spec.liveboard, model = LB.model;
const ex0 = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
if (ex0.status !== 200 || !ex0.body || !ex0.body[0] || !ex0.body[0].edoc) return { refused: 'Liveboard ' + LB.guid + ' not found or not exportable; create it first (an empty Liveboard is enough)', http: ex0.status };
const doc0 = JSON.parse(ex0.body[0].edoc).liveboard;
const bySlug = {}, byPos = {}, idBySlug = {}, idByPos = {}, owned = new Set();
const vizById = {}; (doc0.visualizations || []).forEach((v) => { vizById[v.id] = v; });
for (const v of doc0.visualizations || []) if (owns(codeOf(v))) owned.add(v.id);
for (const tab of ((doc0.layout && doc0.layout.tabs) || [])) for (const tl of tab.tiles || []) {
  if (!owned.has(tl.visualization_id)) continue;
  const c = codeOf(vizById[tl.visualization_id]);
  const m = MARK.exec(c.js); if (m) { bySlug[m[1]] = c; idBySlug[m[1]] = tl.visualization_id; }
  byPos[tab.name + '|' + tl.x + '|' + tl.y] = c; idByPos[tab.name + '|' + tl.x + '|' + tl.y] = tl.visualization_id;
}
// The shared core travels in the block, or (core.ref) is taken from any tile already on this Liveboard whose
// core matches the checksum, which saves pasting it again in every block after the first.
let core = P.core && !P.core.ref ? { js: P.core.js, css: P.core.css } : null;
if (P.core && P.core.ref) {
  let js = null, css = null;
  for (const c of [...Object.values(bySlug), ...Object.values(byPos)]) {
    const i = c.js.indexOf(END_JS), k = c.css.indexOf(END_CSS);
    if (!js && i >= 0) { const x = c.js.slice(0, i + END_JS.length); if ((await sha256(x)) === P.core.sha.js) js = x; }
    if (!css && k >= 0) { const x = c.css.slice(0, k + END_CSS.length); if ((await sha256(x)) === P.core.sha.css) css = x; }
    if (js && css) break;
  }
  if (!js || !css) return { refused: 'core.ref: no tile on this Liveboard carries the current core (' + (js ? '' : 'js ') + (css ? '' : 'css') + '); send this block without --core-ref' };
  core = { js, css };
}
const bodyOf = (c) => ({ js: c.js.slice(c.js.indexOf(END_JS) + END_JS.length), css: c.css.slice(c.css.indexOf(END_CSS) + END_CSS.length) });

// Tiles sent by reference: copy the body from the source Liveboard when it matches the library checksums.
const needCode = [];
const refs = Object.entries(P.tiles).filter(([, t]) => t.ref);
if (refs.length) {
  const same = P.reuse === LB.guid; // reusing from this Liveboard stamps slug markers on older tiles, no paste
  const exR = same ? ex0 : await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: P.reuse, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
  // Tiles are found by slug marker, then (on this Liveboard) by grid position, then by title when it is unique.
  const src = {}, byTitle = {}, dupTitle = {};
  if (exR.status === 200 && exR.body && exR.body[0] && exR.body[0].edoc) for (const v of JSON.parse(exR.body[0].edoc).liveboard.visualizations || []) {
    const c = codeOf(v); if (!c) continue;
    const m = MARK.exec(c.js); if (m) src[m[1]] = c; else { if (byTitle[v.answer.name]) dupTitle[v.answer.name] = true; byTitle[v.answer.name] = c; }
  }
  const posOf = {}; if (same) for (const tab of spec.tabs) for (const x of tab.tiles) posOf[x.slug] = byPos[tab.name + '|' + x.x + '|' + x.y];
  for (const [slug, t] of refs) {
    const c = src[slug] || posOf[slug] || (dupTitle[t.ref.title] ? null : byTitle[t.ref.title]);
    if (!c || c.js.indexOf(END_JS) < 0) { needCode.push(slug + ' (not on ' + P.reuse + ')'); delete P.tiles[slug]; continue; }
    const b = bodyOf(c), legacyCss = c.css.indexOf(END_CSS) < 0; // older tiles lost the CSS core markers when comments were stripped
    const cssOk = legacyCss ? (await sha256(c.css)) === t.ref.cssLegacy : (await sha256(b.css.trim())) === t.ref.css;
    const ok = cssOk && (await sha256(b.js.replace(MARK, '').trim())) === t.ref.js && (await sha256(c.html)) === t.ref.html;
    if (!ok) { needCode.push(slug + ' (differs from the library)'); delete P.tiles[slug]; continue; }
    // A legacy tile keeps its whole CSS; the JS body gets the slug marker so the next patch finds it by slug.
    P.tiles[slug] = { body: { js: '\n/* amuzing-slug: ' + slug + ' */' + (b.js.replace(MARK, '').startsWith('\n') ? '' : '\n') + b.js.replace(MARK, ''), css: legacyCss ? null : b.css, cssWhole: legacyCss ? c.css : null, html: c.html } };
  }
}

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

// 3. compose: the owned tiles, merged into everything else the Liveboard already has
const MEASURE = /^(Total|Average|Unique Number|Max|Min|Count|Sum)\b/i;
const CSV2 = JSON.stringify({ version: 'V4DOT2', chartProperties: { chartSpecific: { dataFieldArea: 'column' } }, columnProperties: [], axisProperties: [] });
const used = new Set(Object.keys(vizById));
let nId = 0;
const freshId = () => { let id; do id = 'Viz_' + (++nId); while (used.has(id)); used.add(id); return id; };
const taken = new Set();
const COLS = {}, vizzes = [], specTabs = [], report = [], excluded = [];
for (const tab of spec.tabs) {
  const tiles = [];
  for (const t of tab.tiles) {
    const pos = tab.name + '|' + t.x + '|' + t.y;
    let code, from;
    if (P.tiles[t.slug] && P.tiles[t.slug].body) { const bd = P.tiles[t.slug].body; code = { js: core.js + bd.js, css: bd.cssWhole || core.css + bd.css, html: bd.html }; from = 'payload'; }
    else if (P.tiles[t.slug]) { const f = P.tiles[t.slug].f; code = { js: core.js + '\n' + f.js, css: core.css + '\n' + f.css, html: f.html }; from = 'payload'; }
    else if (bySlug[t.slug]) { code = bySlug[t.slug]; from = 'kept'; }
    else if (byPos[pos]) { code = byPos[pos]; from = 'kept (position)'; }
    else { report.push({ slug: t.slug, from: (P.pending || []).includes(t.slug) ? 'pending' : 'MISSING - not on the Liveboard and not in this payload' }); continue; }
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
    // An owned tile keeps its visualization id, so filters and anything else that points at it still resolve.
    const prev = [idBySlug[t.slug], idByPos[pos]].find((x) => x && !taken.has(x));
    const id = prev || freshId();
    taken.add(id);
    vizzes.push({ id, answer });
    if (t.filters === false) excluded.push(id);
    tiles.push({ visualization_id: id, x: t.x, 'y': t.y, height: t.h, width: t.w });
    report.push({ slug: t.slug, from, js: (await sha256(code.js)).slice(0, 12), css: (await sha256(code.css)).slice(0, 12) });
  }
  specTabs.push({ name: tab.name, description: tab.description || '', tiles });
}
// Owned tiles the spec no longer places are removed; everything the skill does not own is kept verbatim.
const removed = [...owned].filter((id) => !taken.has(id)).map((id) => vizById[id].answer.name);
const others = (doc0.visualizations || []).filter((v) => !owned.has(v.id));
const finalIds = new Set([...others.map((v) => v.id), ...vizzes.map((v) => v.id)]);

// Tabs: the Liveboard's own order is kept. Tabs the spec names take the slots of existing spec tabs, in spec
// order; new spec tabs go last. A tab left with no tiles is dropped only if removing owned tiles emptied it.
const specNames = new Set(spec.tabs.map((t) => t.name));
const oldTabs = (doc0.layout && doc0.layout.tabs) || [];
const byName = {}, tabs = [], slots = [], shifted = [];
for (const t of oldTabs) {
  const keep = (t.tiles || []).filter((tl) => finalIds.has(tl.visualization_id) && !owned.has(tl.visualization_id));
  if (specNames.has(t.name)) { byName[t.name] = { ...t, tiles: keep }; slots.push(tabs.length); tabs.push(null); }
  else if (keep.length || !(t.tiles || []).length) tabs.push({ ...t, tiles: keep });
}
const merge = (st) => {
  const base = byName[st.name] || {};
  const mine = st.tiles, kept = base.tiles || [];
  const hit = kept.some((a) => mine.some((b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height));
  let moved = kept;
  if (hit) { // the user's tiles move below the skill's, keeping their own arrangement
    const bottom = Math.max(...mine.map((b) => b.y + b.height)), top = Math.min(...kept.map((a) => a.y));
    moved = kept.map((a) => ({ ...a, y: a.y - top + bottom }));
    shifted.push(st.name);
  }
  return { ...base, name: st.name, description: st.description || base.description || '', tiles: [...mine, ...moved] };
};
const inOld = spec.tabs.filter((t) => byName[t.name]).map((t) => specTabs.find((x) => x.name === t.name));
slots.forEach((i, k) => { tabs[i] = merge(inOld[k]); });
for (const st of specTabs) if (!byName[st.name]) tabs.push(merge(st));
const layoutTabs = tabs.filter(Boolean);
const droppedTabs = oldTabs.map((t) => t.name).filter((n) => !layoutTabs.some((t) => t.name === n));

// Filters: a spec filter replaces the one on the same column (its values are kept); other filters stay.
const specF = (spec.filters || []).map((f) => {
  const o = { column: [f.column], is_mandatory: false, is_single_value: !!f.single, display_name: f.label || '' };
  if (excluded.length && f.applyToNarrative === false) o.excluded_visualizations = excluded;
  if (f.date) o.date_filter = f.date;
  return o;
});
const col = (f) => (f.column || [])[0];
const oldF = doc0.filters || [];
const filters = [...oldF.map((f) => { const s = specF.find((x) => col(x) === col(f)); return s ? { ...f, ...s } : f; }),
  ...specF.filter((s) => !oldF.some((f) => col(f) === col(s)))].map((f) => {
  if (!f.excluded_visualizations) return f;
  const ex = f.excluded_visualizations.filter((id) => finalIds.has(id));
  const o = { ...f }; if (ex.length) o.excluded_visualizations = ex; else delete o.excluded_visualizations;
  return o;
});
const chips = [...(doc0.ordered_chips || [])];
for (const f of spec.filters || []) if (!chips.some((c) => c.type === 'FILTER' && c.name === f.column)) chips.push({ name: f.column, type: 'FILTER' });
const styleProps = [...((doc0.style && doc0.style.style_properties) || [])];
for (const sp of spec.style || []) { const i = styleProps.findIndex((x) => x.name === sp.name); if (i >= 0) styleProps[i] = sp; else styleProps.push(sp); }

const lb = { ...doc0, name: LB.name, description: LB.description || doc0.description || '', visualizations: [...others, ...vizzes],
  filters, layout: { ...(doc0.layout || {}), tabs: layoutTabs }, style: { ...(doc0.style || {}), style_properties: styleProps } };
if (chips.length) lb.ordered_chips = chips;
const text = JSON.stringify({ guid: LB.guid, liveboard: lb });
const summary = {
  mode: MODE, tmlKB: Math.round(text.length / 1024), tiles: vizzes.length, kept: others.length,
  replaced: report.filter((r) => r.from === 'payload').map((r) => r.slug),
  keptByPosition: report.filter((r) => r.from === 'kept (position)').length,
  problems: report.filter((r) => /MISSING|FAILED/.test(r.from)),
  pending: report.filter((r) => r.from === 'pending').map((r) => r.slug)
};
if (removed.length) summary.removed = removed;
if (droppedTabs.length) summary.droppedTabs = droppedTabs;
if (shifted.length) summary.shiftedBelowCharts = shifted;
if (needCode.length) summary.needCode = needCode;
if (!summary.replaced.length && !removed.length) { summary.skipped = 'nothing in this block to write; send the needCode charts without --reuse'; return summary; }
if (summary.tmlKB > 2000) summary.warning = 'TML over 2 MB; imports near 2.8 MB have reset the connection';

// 4. import and prove. A commit validates first in the same call, so one paste per block does both.
const importAs = async (policy) => {
  const imp = await ts.post('/api/rest/2.0/metadata/tml/import', { metadata_tmls: [text], import_policy: policy, create_new: false });
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
// ThoughtSpot may renumber visualization ids, so the proof compares contents: every composed chart once, and
// as many other visualizations as were kept.
const ex = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
const bag = {}; let othersBack = 0;
for (const bv of JSON.parse(ex.body[0].edoc).liveboard.visualizations || []) {
  const bc = codeOf(bv);
  if (!owns(bc)) { othersBack++; continue; }
  const k = (await sha256(bc.js)).slice(0, 12) + '|' + (await sha256(bc.css)).slice(0, 12);
  bag[k] = (bag[k] || 0) + 1;
}
const built = report.filter((r) => r.js);
const failed = built.filter((r) => { const k = r.js + '|' + r.css; if (!bag[k]) return true; bag[k]--; return false; }).map((r) => r.slug);
const extra = Object.values(bag).reduce((a, b) => a + b, 0);
summary.roundTripAllOk = !failed.length && !extra && othersBack === others.length;
if (failed.length) summary.roundTripFailed = failed;
if (extra) summary.roundTripUnexpected = extra;
if (othersBack !== others.length) summary.keptAfterImport = othersBack;
return summary;
