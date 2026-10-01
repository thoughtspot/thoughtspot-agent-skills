// Sandbox side of liveboard-pack.mjs. Never run by hand: liveboard-pack.mjs prints this file with PAYLOAD and
// MODE filled in, and the result is pasted as the `code` of execute-thoughtspot-code.
//
// The target Liveboard is its own store. Each run:
//   1. checks every chart it carries against its sha256 (a mistyped paste is refused, nothing is written);
//   2. exports the Liveboard and finds the tiles the skill owns: custom charts whose code carries the owner
//      marker naming THIS Liveboard (`ts-lb-owner: <guid>`), written by the skill when it composed them. A
//      chart that only carries the shared core (a copy pinned from an answer, a tile from another Liveboard)
//      is not owned. A user's copy of an owned tile carries the same marker; when a slug is marked twice the
//      tile at the spec position is the skill's, and with no tile there the block refuses to commit.
//      Tiles written before the marker existed are taken over only with --adopt;
//   3. merges into the exported TML: charts in this payload replace their tile, owned tiles keep the code
//      they have, owned tiles no longer in the spec are removed. Everything else on the Liveboard (native
//      charts, notes, other custom charts, tabs, filters, parameters, style, its name) is kept as it is;
//   4. imports VALIDATE_ONLY, and a commit (ALL_OR_NONE) only when nothing is wrong: any problem (a failed
//      search, a missing tile, an ownership conflict, an untabbed Liveboard, no backup of content the skill
//      does not own) refuses the commit. After a commit it exports again and proves every owned tile carries
//      the code that was composed, every visualization it does not own is still there, and the tabs hold the
//      tiles they were given.
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
const hasCore = (c) => !!c && c.js.indexOf(END_JS) >= 0;
const OWNER = /\/\* ts-lb-owner: ([\w-]+) \*\/\n?/;
// Guids compare in lower case: a spec guid typed in upper case must not turn every tile into "not ours".
const ownerOf = (c) => { const m = c && OWNER.exec(c.js); return m ? m[1].toLowerCase() : null; };
const strip = (js) => js.replace(MARK, '').replace(OWNER, '');

// 1. checksums
const badSha = [];
for (const [slug, t] of Object.entries(P.tiles)) if (t.sha) for (const k of Object.keys(t.sha)) if ((await sha256(t.f[k])) !== t.sha[k]) badSha.push(slug + '.' + k);
// The spec sets every title, search and position on the Liveboard, so a slip in it is checked like chart code.
if (P.specSha && (await sha256(JSON.stringify(P.spec))) !== P.specSha) badSha.push('spec');
// The backup's summary (name, size, checksum, the visualization ids it holds) is checked like the code.
if (P.backup && (await sha256(JSON.stringify(P.backup))) !== P.backupSha) badSha.push('backup');
if (P.core && !P.core.ref) for (const k of ['js', 'css']) if ((await sha256(P.core[k])) !== P.core.sha[k]) badSha.push('core.' + k);
if (badSha.length) return { refused: 'CHECKSUM MISMATCH - nothing written, resend this block unchanged', badSha };

// 2. current Liveboard
const spec = P.spec, LB = spec.liveboard, model = LB.model, LBG = String(LB.guid).toLowerCase();
const ex0 = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
if (ex0.status !== 200 || !ex0.body || !ex0.body[0] || !ex0.body[0].edoc) return { refused: 'Liveboard ' + LB.guid + ' not found or not exportable; create it first (an empty Liveboard is enough)', http: ex0.status };
const doc0 = JSON.parse(ex0.body[0].edoc).liveboard;
const vizById = {}; (doc0.visualizations || []).forEach((v) => { vizById[v.id] = v; });
const conflicts = [];
// A Liveboard laid out without tabs keeps its tiles in layout.tiles; the skill writes tabs, and merging the two
// would orphan those tiles, so it stops. That includes a layout that has both.
if (doc0.layout && (doc0.layout.tiles || []).length) return { refused: 'NOT COMMITTED - this Liveboard lays tiles out without tabs (layout.tiles' + ((doc0.layout.tabs || []).length ? ', next to tabs' : '') + '); add a tab in ThoughtSpot and move every tile into tabs first, or build on a new Liveboard. Nothing was written' };
// Every custom chart that carries the core, with where it sits.
const specPos = {}; for (const tab of spec.tabs) for (const t of tab.tiles) specPos[tab.name + '|' + t.x + '|' + t.y] = t.slug;
const specSlugs = new Set(Object.values(specPos));
// Only tabs the spec names hold the skill's tiles. A marked tile on any other tab is the user's (a copy they
// moved to a tab of their own) and is never touched.
const specTabNames = new Set(spec.tabs.map((t) => t.name));
const cands = [];
for (const tab of ((doc0.layout && doc0.layout.tabs) || []).filter((t) => specTabNames.has(t.name))) for (const tl of tab.tiles || []) {
  const c = codeOf(vizById[tl.visualization_id]);
  if (!hasCore(c)) continue;
  const m = MARK.exec(c.js), pos = tab.name + '|' + tl.x + '|' + tl.y;
  cands.push({ id: tl.visualization_id, c, pos, slug: m ? m[1] : null, owner: ownerOf(c), title: vizById[tl.visualization_id].answer.name });
}
// Owned: marked with this Liveboard's guid. Adoptable: no owner marker, and its slug (or, unmarked, its
// position) is in the spec; taken over only with --adopt, otherwise the commit is refused so nothing is doubled.
const owned = new Set(), bySlug = {}, idBySlug = {}, byPos = {}, idByPos = {}, adoptable = [];
const take = (k) => { owned.add(k.id); const s = k.slug || specPos[k.pos]; bySlug[s] = k.c; idBySlug[s] = k.id; byPos[k.pos] = k.c; idByPos[k.pos] = k.id; };
const groups = {};
for (const k of cands) {
  const mine = k.owner === LBG, legacy = !k.owner && (k.slug ? specSlugs.has(k.slug) : !!specPos[k.pos]);
  if (!mine && !legacy) continue; // another Liveboard's tile, or a chart pinned from an answer: not ours
  // --adopt takes over tiles with a slug marker; a tile matched only by its position (it could be a chart the
  // user pinned there) needs --adopt-by-position as well.
  if (legacy && !(k.slug ? P.adopt : P.adoptByPosition)) { adoptable.push((k.slug || specPos[k.pos]) + ' (' + k.title + (k.slug ? '' : ', matched by position only') + ')'); continue; }
  const s = k.slug || specPos[k.pos];
  // An owned tile whose slug comment was removed and that sits off every spec position cannot be placed:
  // stop rather than remove it.
  if (!s) { conflicts.push('the tile "' + k.title + '" at ' + k.pos + ' carries this Liveboard\'s owner marker but no slug marker and is not at a spec position; restore its "amuzing-slug" comment, move it back to its spec position, or remove its owner marker to make it yours'); continue; }
  (groups[s] = groups[s] || []).push(k);
}
for (const [s, ks] of Object.entries(groups)) {
  if (ks.length === 1) { take(ks[0]); continue; }
  // Two tiles marked with one slug: a user copied the skill's tile. The one at the spec position is the
  // skill's; the copies are the user's and are kept. With none at the spec position there is no telling.
  const at = ks.filter((k) => specPos[k.pos] === s);
  if (at.length === 1) take(at[0]);
  else conflicts.push(s + ': ' + ks.length + ' tiles carry its marker (' + ks.map((k) => k.title + ' at ' + k.pos).join('; ') + ') and none sits at its spec position; remove the copy or move the original back');
}
if (adoptable.length) conflicts.push('tiles that look like this skill\'s but carry no owner marker (written before markers, or pinned from an answer): ' + adoptable.join(', ') + '. If they are the skill\'s, send this block again built with --adopt (and --adopt-by-position for tiles matched by position only); otherwise move them off the spec positions');
// The shared core travels in the block, or (core.ref) is taken from any tile already on this Liveboard whose
// core matches the checksum, which saves pasting it again in every block after the first.
let core = P.core && !P.core.ref ? { js: P.core.js, css: P.core.css } : null;
if (P.core && P.core.ref) {
  let js = null, css = null;
  for (const c of [...Object.values(bySlug), ...Object.values(byPos), ...cands.map((k) => k.c)]) {
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
    const ok = cssOk && (await sha256(strip(b.js).trim())) === t.ref.js && (await sha256(c.html)) === t.ref.html;
    if (!ok) { needCode.push(slug + ' (differs from the library)'); delete P.tiles[slug]; continue; }
    // A legacy tile keeps its whole CSS; the JS body gets the slug marker so the next patch finds it by slug.
    const rest = strip(b.js);
    P.tiles[slug] = { body: { js: '\n/* amuzing-slug: ' + slug + ' */\n/* ts-lb-owner: ' + LBG + ' */' + (rest.startsWith('\n') ? '' : '\n') + rest, css: legacyCss ? null : b.css, cssWhole: legacyCss ? c.css : null, html: c.html } };
  }
}

// read-only drift check: live tile body against the local body
if (MODE === 'check') {
  const stale = [], missing = [], ok = [];
  for (const tab of spec.tabs) for (const t of tab.tiles) {
    const want = P.bodySha[t.slug]; if (!want) continue;
    const pos = tab.name + '|' + t.x + '|' + t.y;
    const k = cands.find((x) => x.slug === t.slug && x.pos === pos) || cands.find((x) => x.slug === t.slug) || cands.find((x) => !x.slug && x.pos === pos);
    const c = bySlug[t.slug] || byPos[pos] || (k && k.c);
    if (!c) { missing.push(t.slug); continue; }
    const b = bodyOf(c);
    // tiles imported before this scheme had their CSS comments (and so the core marker) stripped: compare whole CSS
    const h16 = async (x) => (await sha256(x)).slice(0, 16);
    const legacy = c.css.indexOf(END_CSS) < 0;
    const got = { js: await h16(strip(b.js).trim()), css: legacy ? await h16(c.css) : await h16(b.css.trim()), html: await h16(c.html) };
    if (legacy) want.css = want.cssLegacy;
    const diff = ['js', 'css', 'html'].filter((k) => got[k] !== want[k]);
    if (diff.length) stale.push(t.slug + ' (' + diff.join(',') + (bySlug[t.slug] ? '' : ', matched by position') + ')'); else ok.push(t.slug);
  }
  const r = { stale, missing, ok: ok.length };
  if (conflicts.length) r.conflicts = conflicts;
  return r;
}

// 3. compose: the owned tiles, merged into everything else the Liveboard already has
const OWNER_LINE = '/* ts-lb-owner: ' + LBG + ' */';
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
    // The owner marker names this Liveboard, so the next patch knows the tile is the skill's (and a copy of it
    // on another Liveboard is not). Older kept tiles get it too.
    const mark = (js) => js.indexOf(OWNER_LINE) >= 0 ? js : js.replace(MARK, (m) => m + '\n' + OWNER_LINE);
    if (P.tiles[t.slug] && P.tiles[t.slug].body) { const bd = P.tiles[t.slug].body; code = { js: core.js + bd.js, css: bd.cssWhole || core.css + bd.css, html: bd.html }; from = 'payload'; }
    else if (P.tiles[t.slug]) { const f = P.tiles[t.slug].f; code = { js: core.js + '\n' + mark(f.js), css: core.css + '\n' + f.css, html: f.html }; from = 'payload'; }
    else if (bySlug[t.slug]) { code = bySlug[t.slug]; from = 'kept'; }
    else if (byPos[pos]) { code = byPos[pos]; from = 'kept (position)'; }
    else { report.push({ slug: t.slug, from: (P.pending || []).includes(t.slug) ? 'pending' : 'MISSING - not on the Liveboard and not in this payload' }); continue; }
    if (from !== 'payload' && !ownerOf(code)) {
      code = { ...code, js: MARK.test(code.js) ? mark(code.js) : code.js.replace(END_JS, END_JS + '\n/* amuzing-slug: ' + t.slug + ' */\n' + OWNER_LINE) };
      from = 'kept, marked';
    }
    if (!(t.search in COLS)) {
      const q = await ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: model.guid, query_string: t.search, record_size: 1 });
      const cn = q.status === 200 && q.body && q.body.contents && q.body.contents[0] && q.body.contents[0].column_names;
      COLS[t.search] = Array.isArray(cn) && cn.length ? cn : null; // no columns is a failed search, not an empty tile
    }
    const cols = COLS[t.search];
    // A failed search never costs the tile: an existing one stays exactly as it is, and the commit is refused.
    const prevId = [idBySlug[t.slug], idByPos[pos]].find((x) => x && !taken.has(x));
    if (!cols) {
      report.push({ slug: t.slug, from: 'SEARCH FAILED: ' + t.search });
      if (prevId) { taken.add(prevId); vizzes.push(vizById[prevId]); tiles.push({ visualization_id: prevId, x: t.x, 'y': t.y, height: t.h, width: t.w }); }
      continue;
    }
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
    const id = prevId || freshId();
    taken.add(id);
    vizzes.push({ id, answer });
    if (t.filters === false) excluded.push(id);
    tiles.push({ visualization_id: id, x: t.x, 'y': t.y, height: t.h, width: t.w });
    report.push({ slug: t.slug, from, id, js: (await sha256(code.js)).slice(0, 12), css: (await sha256(code.css)).slice(0, 12) });
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

// Filters: a filter the Liveboard already has on a spec column is the user's and keeps everything it has
// (values, label, mandatory, single value, its exclusions of tiles the skill does not own); the spec only
// decides which of the skill's own tiles it skips. A spec column with no filter yet gets a new one.
const mineIds = new Set(vizzes.map((v) => v.id));
const specF = (spec.filters || []).map((f) => {
  const o = { column: [f.column], is_mandatory: false, is_single_value: !!f.single, display_name: f.label || '' };
  if (f.date) o.date_filter = f.date;
  o.skip = f.applyToNarrative === false ? excluded : [];
  return o;
});
const col = (f) => (f.column || [])[0];
const oldF = doc0.filters || [];
const withEx = (f, skip) => {
  const ex = [...(f.excluded_visualizations || []).filter((id) => finalIds.has(id) && !mineIds.has(id)), ...skip];
  const o = { ...f }; delete o.skip;
  if (ex.length) o.excluded_visualizations = ex; else delete o.excluded_visualizations;
  return o;
};
const filters = [...oldF.map((f) => { const s = specF.find((x) => col(x) === col(f)); return withEx(f, s ? s.skip : (f.excluded_visualizations || []).filter((id) => mineIds.has(id))); }),
  ...specF.filter((s) => !oldF.some((f) => col(f) === col(s))).map((s) => withEx(s, s.skip))];
const chips = [...(doc0.ordered_chips || [])];
for (const f of spec.filters || []) if (!chips.some((c) => c.type === 'FILTER' && c.name === f.column)) chips.push({ name: f.column, type: 'FILTER' });
const styleProps = [...((doc0.style && doc0.style.style_properties) || [])];
for (const sp of spec.style || []) { const i = styleProps.findIndex((x) => x.name === sp.name); if (i >= 0) styleProps[i] = sp; else styleProps.push(sp); }

// The Liveboard keeps its own name and description; the spec's are only for one that has none.
const layout = { ...(doc0.layout || {}), tabs: layoutTabs }; delete layout.tiles;
const lb = { ...doc0, name: doc0.name || LB.name, description: doc0.description || LB.description || '', visualizations: [...others, ...vizzes],
  filters, layout, style: { ...(doc0.style || {}), style_properties: styleProps } };
if (chips.length) lb.ordered_chips = chips;
const text = JSON.stringify({ guid: LB.guid, liveboard: lb });
const summary = {
  mode: MODE, tmlKB: Math.round(text.length / 1024), tiles: vizzes.length, kept: others.length,
  replaced: report.filter((r) => r.from === 'payload').map((r) => r.slug),
  keptByPosition: report.filter((r) => r.from === 'kept (position)').length,
  marked: report.filter((r) => r.from === 'kept, marked').map((r) => r.slug),
  problems: [...report.filter((r) => /MISSING|FAILED/.test(r.from)), ...conflicts.map((c) => ({ from: c }))],
  pending: report.filter((r) => r.from === 'pending').map((r) => r.slug)
};
if (removed.length) summary.removed = removed;
if (droppedTabs.length) summary.droppedTabs = droppedTabs;
if (shifted.length) summary.shiftedBelowCharts = shifted;
if (needCode.length) summary.needCode = needCode;
if (!summary.replaced.length && !removed.length && !summary.marked.length && !summary.problems.length) { summary.skipped = 'nothing in this block to write; send the needCode charts without --reuse'; return summary; }
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
// A commit writes only a state with nothing wrong in it.
if (summary.problems.length) { summary.refused = 'NOT COMMITTED - fix the problems above; the Liveboard is unchanged'; return summary; }
// Content the skill does not own is only touched with a backup of it on disk (liveboard-pack --backup).
if (others.length && !P.backup) { summary.refused = 'NOT COMMITTED - this Liveboard holds ' + others.length + ' visualization(s) the skill does not own; export a backup and build the block with --backup <file>'; return summary; }
// The backup must be of the Liveboard as it is now: every visualization it holds is in the backup.
if (P.backup) {
  const inBackup = new Set(P.backup.vizIds || []);
  const missing = (doc0.visualizations || []).filter((v) => !inBackup.has(v.id)).map((v) => (v.answer ? v.answer.name : v.id));
  if (missing.length) { summary.refused = 'NOT COMMITTED - the backup ' + P.backup.file + ' is not of this Liveboard as it is now (it lacks ' + missing.slice(0, 5).join(', ') + (missing.length > 5 ? ' and ' + (missing.length - 5) + ' more' : '') + '); export it again'; return summary; }
}
const c = await importAs('ALL_OR_NONE');
const r0 = c.r;
summary.import = r0 && r0.status;
if (!r0 || !r0.status || r0.status.status_code !== 'OK') { summary.raw = JSON.stringify(c.raw).slice(0, 1200); return summary; }
// The proof. ThoughtSpot may renumber visualization ids, so it compares contents:
//   - every composed chart comes back exactly once with the code that was composed;
//   - every visualization the skill did not own BEFORE the patch comes back unchanged (the whole tile, keys
//     sorted, id aside), so a loss or an edit shows even when the count is right;
//   - the Liveboard's name, description, parameters and filters are what was sent; each tab holds the tiles it
//     was given and every tile points at a visualization that exists; layout.tiles is unset.
// If the export after the commit fails, the commit has landed: say so instead of throwing.
const stable = (x) => Array.isArray(x) ? '[' + x.map(stable).join(',') + ']' : x && typeof x === 'object' ? '{' + Object.keys(x).filter((k) => x[k] !== undefined).sort().map((k) => JSON.stringify(k) + ':' + stable(x[k])).join(',') + '}' : JSON.stringify(x);
// `after` still holds everything `before` had, with the same values. Fields ThoughtSpot adds on re-export (a
// default display_mode, say) are allowed; anything lost or changed is not. Key order never matters.
const covers = (before, after) => {
  if (before === null || typeof before !== 'object') return before === after || (before === undefined);
  if (Array.isArray(before)) return Array.isArray(after) && after.length === before.length && before.every((x, i) => covers(x, after[i]));
  return !!after && typeof after === 'object' && !Array.isArray(after) && Object.keys(before).every((k) => before[k] === undefined || covers(before[k], after[k]));
};
const label = (v) => v ? (v.answer ? 'A|' + v.answer.name + '|' + ((v.answer.chart && v.answer.chart.type) || '') : v.note_tile ? 'N' : 'O') : 'MISSING';
let back;
try {
  const ex = await ts.post('/api/rest/2.0/metadata/tml/export', { metadata: [{ identifier: LB.guid, type: 'LIVEBOARD' }], edoc_format: 'JSON' });
  back = JSON.parse(ex.body[0].edoc).liveboard;
} catch (e) {
  summary.roundTripAllOk = false;
  summary.roundTripError = 'the commit landed but the Liveboard could not be exported to check it (' + String(e && e.message || e).slice(0, 200) + '); run --check, and restore from the backup if anything is wrong';
  return summary;
}
// A tile counts as composed when its code is what was composed, matched by its id first and by code alone when
// ThoughtSpot renumbered it (not by its marker: a user's copy of a skill tile carries the marker, and even the
// same code, and is the user's).
const want = {}, wantById = {};
for (const r of report.filter((x) => x.js)) { const k = r.js + '|' + r.css; want[k] = (want[k] || 0) + 1; wantById[r.id] = k; }
const got = {}, rest = [], othersBack = [];
let othersAfter = 0;
const keyOf = async (bv) => { const bc = codeOf(bv); return bc ? (await sha256(bc.js)).slice(0, 12) + '|' + (await sha256(bc.css)).slice(0, 12) : null; };
for (const bv of back.visualizations || []) {
  const k = await keyOf(bv);
  if (k && wantById[bv.id] === k && (got[k] || 0) < want[k]) got[k] = (got[k] || 0) + 1; else rest.push([bv, k]);
}
for (const [bv, k] of rest) {
  if (k && (got[k] || 0) < (want[k] || 0)) { got[k] = (got[k] || 0) + 1; continue; }
  othersAfter++;
  othersBack.push(bv);
}
const failed = report.filter((r) => r.js).filter((r) => { const k = r.js + '|' + r.css; if ((got[k] || 0) > 0) { got[k]--; return false; } return true; }).map((r) => r.slug);
const lost = [];
// Each visualization the skill did not own comes back covering what it was, matched by id first.
const pool = [...othersBack];
for (const v of (doc0.visualizations || []).filter((x) => !owned.has(x.id))) {
  const bare = { ...v, id: undefined };
  let i = pool.findIndex((b) => b.id === v.id && covers(bare, b));
  if (i < 0) i = pool.findIndex((b) => covers(bare, b));
  if (i >= 0) pool.splice(i, 1); else lost.push(v.answer ? v.answer.name : v.note_tile ? 'a note (' + v.id + ')' : v.id);
}
const extra = othersAfter - (others.length - lost.length); // anything back that was neither composed nor kept
const layoutBad = [];
const backIds = new Set((back.visualizations || []).map((v) => v.id));
if (back.layout && (back.layout.tiles || []).length) layoutBad.push('layout.tiles is set');
// Each tab holds the same tiles, by what they are and where they sit (ids may be renumbered).
const sentById = {}; for (const v of lb.visualizations) sentById[v.id] = v;
const backById = {}; for (const v of back.visualizations || []) backById[v.id] = v;
const place = (byId) => (x) => label(byId[x.visualization_id]) + '@' + x.x + ',' + x.y + ',' + x.width + 'x' + x.height;
for (const t of layoutTabs) {
  const bt = ((back.layout && back.layout.tabs) || []).find((x) => x.name === t.name);
  if (!bt) { layoutBad.push(t.name + ' (tab missing)'); continue; }
  if ((bt.tiles || []).some((x) => !backIds.has(x.visualization_id))) layoutBad.push(t.name + ' (a tile points at a missing visualization)');
  else if (stable(t.tiles.map(place(sentById)).sort()) !== stable((bt.tiles || []).map(place(backById)).sort())) layoutBad.push(t.name + ' (tiles moved, swapped or missing)');
}
// Filters compare on what the user sees (column, operator, values, label, mandatory, single value); ids in
// their exclusions may be renumbered, so only their count is compared.
const fKey = (f) => stable({ c: f.column, o: f.oper, v: f.values, d: f.display_name, m: f.is_mandatory, s: f.is_single_value, df: f.date_filter, n: (f.excluded_visualizations || []).length });
const settingsBad = [];
if (stable((lb.filters || []).map(fKey).sort()) !== stable((back.filters || []).map(fKey).sort())) settingsBad.push('filters');
if (!covers(lb.parameters || [], back.parameters || [])) settingsBad.push('parameters');
if (!covers(lb.style || {}, back.style || {})) settingsBad.push('style');
if (!covers(lb.ordered_chips || [], back.ordered_chips || [])) settingsBad.push('ordered_chips');
if (lb.name !== back.name) settingsBad.push('name');
if ((lb.description || '') !== (back.description || '')) settingsBad.push('description');
summary.roundTripAllOk = !failed.length && !extra && !lost.length && !layoutBad.length && !settingsBad.length;
if (failed.length) summary.roundTripFailed = failed;
if (extra) summary.roundTripUnexpected = extra;
if (lost.length) summary.roundTripLost = lost;
if (layoutBad.length) summary.roundTripLayout = layoutBad;
if (settingsBad.length) summary.roundTripChanged = settingsBad;
return summary;
