/* ── Usage view (#usage): which audited Models are used, idle or never queried ──
   One row per audited Model from its usage (D.C.m[].us, ../usage.js): status (`s`, set by
   ts_cli/audit/usage_triage.py from H17's reading), last use, queries and users over the
   window, dependents (`dp`: [total, Liveboards, Answers, Sets, other, visible, not read];
   total null when not read in full — Sets not read, or the Model's own dependents reading
   incomplete — so `visible` is then a lower bound; `dc` 0 when completeness is not known,
   a snapshot from before ts-cli 0.225.0), owner (`ow`)
   and creation date (`cr`). The quadrant (../usage_quadrant.js) draws the rows the table
   shows; the export (../usage_export.js) writes the selected rows. A sidebar link only when
   the run fetched usage; "Not read" when it was fetched and not read, never an empty table
   that reads as "no idle Models". */
var usageView = null;

/* The table's rows, one per audited Model. */
function usageRows(){
  var worst = {};
  (D.F || []).forEach(function(f){
    var m = D.L[f.mi];
    if(m) (worst[m.g] = worst[m.g] || []).push(f);
  });
  return (D.C.m || []).map(function(cm){
    var m = D.L[cm.mi] || {}, us = cm.us || {}, dp = us.dp || [0, 0, 0, 0, 0, 0, []];
    var notRead = dp[6] || [];
    return {guid: m.g || "", name: m.n || "", cm: cm, status: us.s || "not_judged",
      days: typeof us.d === "number" ? us.d : null, never: !!us.n, last: us.l,
      queries: us.q || 0, users: us.u || 0, deps: typeof dp[5] === "number" ? dp[5] : (dp[0] || 0),
      total: typeof dp[0] === "number" ? dp[0] : null, notRead: notRead,
      complete: notRead.length ? false : (us.dc === 0 ? null : true),
      lb: dp[1] || 0, an: dp[2] || 0, sets: typeof dp[3] === "number" ? dp[3] : null,
      other: dp[4] || 0, owner: us.ow || null,
      created: us.cr || null, worst: worstSev(worst[m.g] || [])};
  });
}

/* Retire candidates first (idle or never queried, no dependents, read in full), then
   idle with dependents or dependents not fully read, too new, not judged, active; within
   each, the most idle first. `deps` is the visible count: a lower bound when not complete. */
function usageNoDependents(r){ return r.deps === 0 && r.complete !== false; }
var USAGE_GROUP = {idle: 1, never: 1, too_new: 2, not_judged: 3, active: 4};
function usageIdleness(r){
  if(r.never) return Infinity;
  return typeof r.days === "number" ? r.days : -1;
}
function usageDefaultOrder(a, b){
  var ga = USAGE_GROUP[a.status] - (USAGE_GROUP[a.status] === 1 && usageNoDependents(a) ? 1 : 0);
  var gb = USAGE_GROUP[b.status] - (USAGE_GROUP[b.status] === 1 && usageNoDependents(b) ? 1 : 0);
  return ga - gb || usageIdleness(b) - usageIdleness(a) || a.name.localeCompare(b.name);
}

/* The sortable columns: [key, header, first direction, value]. */
var USAGE_COLUMNS = [
  ["name", "Model", 1, function(r){ return r.name.toLowerCase(); }],
  ["status", "Status", 1, function(r){ return USAGE_STATUS_ORDER.indexOf(r.status); }],
  ["last", "Last used", -1, usageIdleness],
  ["queries", "Queries", -1, function(r){ return r.queries; }],
  ["users", "Users", -1, function(r){ return r.users; }],
  ["dependents", "Dependents", -1, function(r){ return r.deps; }],
  ["owner", "Owner", 1, function(r){ return (r.owner || "￿").toLowerCase(); }],
  ["created", "Created", -1, function(r){ return r.created || ""; }],
  ["worst", "Worst finding", 1, function(r){ var i = SEV_ORDER[r.worst]; return i === undefined ? 99 : i; }]
];

function usageSorted(rows, sort){
  var list = rows.slice();
  if(!sort) return list.sort(usageDefaultOrder);
  var col = USAGE_COLUMNS.filter(function(c){ return c[0] === sort.key; })[0];
  return list.sort(function(a, b){
    var va = col[3](a), vb = col[3](b);
    var c = va < vb ? -1 : va > vb ? 1 : 0;
    return c * sort.dir || usageDefaultOrder(a, b);
  });
}

function usageShown(r, st){
  if(!st.on[r.status]) return false;
  if(st.nodeps && !usageNoDependents(r)) return false;  /* not read in full is not none */
  var q = st.q.trim().toLowerCase();
  return !q || r.name.toLowerCase().indexOf(q) !== -1 ||
    (r.owner || "").toLowerCase().indexOf(q) !== -1;
}

function usageDepsTitle(r){
  var parts = [usagePlural(r.lb, "Liveboard"), usagePlural(r.an, "Answer"),
    r.sets === null ? "Sets not read" : usagePlural(r.sets, "Set"), r.other+" other"];
  return parts.join(", ")+(r.complete === false ? ": "+usageNotReadText(r)+", so "+r.deps+
    " is a lower bound, not the total" : "");
}

/* What was not read in full: "Sets not read", "dependents not fully read", or both. */
var USAGE_NOT_READ_LABEL = {sets: "Sets not read", dependents: "dependents not fully read"};
function usageNotReadText(r){
  return r.notRead.map(function(k){ return USAGE_NOT_READ_LABEL[k] || k; }).join("; ");
}
function usageDepsText(r){
  return r.complete === false ? r.deps+"+ ("+usageNotReadText(r)+")" : String(r.deps);
}

function usageStatusTitle(r, idleDays){
  if(r.status === "too_new") return "Never queried, and created on "+(r.created || "?")+
    ", less than "+idleDays+" days before the usage was read: H17 does not judge it";
  if(r.status === "not_judged") return r.never
    ? "Never queried, but the usage history starts on "+usageDate(D.C.us.hs)+", under "+
      idleDays+" days before the read: too short to say"
    : "The history holds this Model but no query time";
  if(r.status === "idle") return "No query in "+idleDays+" days or more (H17)";
  if(r.status === "never") return "No query in the usage history (H17)";
  return "Queried in the last "+idleDays+" days";
}

function usageRowHtml(r, idleDays){
  var st = USAGE_STATUS[r.status] || USAGE_STATUS.not_judged, lu = usageLastUsed(r.cm);
  return '<tr data-guid="'+esc(r.guid)+'"><td><input type="checkbox" class="usage-check" data-guid="'+
    esc(r.guid)+'" aria-label="Select '+esc(r.name)+'"></td>'+
    '<td><a href="#model/'+esc(r.guid)+'">'+esc(r.name)+'</a></td>'+
    '<td title="'+esc(usageStatusTitle(r, idleDays))+'"><span class="usage-swatch" style="background:'+
    st.color+'"></span>'+esc(st.label)+'</td>'+
    '<td title="'+esc(lu.title)+'">'+esc(lu.text)+'</td>'+
    '<td>'+r.queries+'</td><td>'+r.users+'</td>'+
    '<td title="'+esc(usageDepsTitle(r))+'">'+esc(usageDepsText(r))+'</td>'+
    '<td>'+(r.owner ? esc(r.owner) : '<span class="usage-none" title="Not recorded">—</span>')+'</td>'+
    '<td>'+esc(r.created || "")+'</td>'+
    '<td>'+(r.worst === "NONE" ? "" : severityPill(r.worst))+'</td></tr>';
}

function usageTableHtml(rows, idleDays){
  var span = usageSpanLabel();
  var heads = USAGE_COLUMNS.map(function(c){
    var label = c[0] === "queries" || c[0] === "users" ? c[1]+" ("+span+")" : c[1];
    return '<th data-sort="'+c[0]+'" aria-sort="none" tabindex="0" role="columnheader">'+esc(label)+'</th>';
  }).join("");
  return '<div style="overflow-x:auto"><table class="cleanup-table usage-table"><thead><tr>'+
    '<th style="width:32px"><span class="visually-hidden">Select</span></th>'+heads+
    '</tr></thead><tbody>'+rows.map(function(r){ return usageRowHtml(r, idleDays); }).join("")+
    '</tbody></table></div>';
}

/* Show what the state says: the table's order and rows, the chart, the counts. */
function usageApply(){
  var v = usageView, st = v.state, tbody = $(".usage-table tbody", v.el);
  var order = usageSorted(v.rows, st.sort), shown = [];
  order.forEach(function(r){
    var tr = v.tr[r.guid], on = usageShown(r, st);
    tbody.appendChild(tr);
    tr.style.display = on ? "" : "none";
    if(on) shown.push(r);
  });
  v.shown = shown;
  $(".usage-chart", v.el).innerHTML = usageQuadrantSvg(shown, v.idleDays, st.sel);
  v.bar._total("Showing "+shown.length+" of "+usagePlural(v.rows.length, "Model"));
  $$("th[data-sort]", v.el).forEach(function(th){
    var k = th.getAttribute("data-sort");
    th.setAttribute("aria-sort", st.sort && st.sort.key === k
      ? (st.sort.dir === 1 ? "ascending" : "descending") : "none");
  });
  usageSyncSelection();
}

function usageSyncSelection(){
  var v = usageView, n = Object.keys(v.state.sel).filter(function(g){ return v.state.sel[g]; }).length;
  $(".usage-selected-count", v.el).textContent = n+" selected";
  $(".usage-export-csv", v.el).disabled = !n;
  $(".usage-export-json", v.el).disabled = !n;
  $$(".usage-check", v.el).forEach(function(cb){ cb.checked = !!v.state.sel[cb.getAttribute("data-guid")]; });
  $$("circle.usage-dot", v.el).forEach(function(c){
    c.classList.toggle("selected", !!v.state.sel[c.getAttribute("data-guid")]);
  });
}

function usageSelectedRows(){
  var v = usageView;
  return usageSorted(v.rows, v.state.sort).filter(function(r){ return v.state.sel[r.guid]; });
}

/* "Not collected" (no selected rule fetched usage), "Not read", or a report from before
   the view: a note in place of the view, never an empty table. */
function usageViewNote(c){
  var state = usageState(), text;
  if(state === "absent") text = NOT_COLLECTED;
  else if(state === "not_read") text = USAGE_NOT_READ+": the audit could not read usage, so it "+
    "cannot say which Models are used, idle or never queried.";
  else text = "This report predates the Usage view (ts-cli 0.225.0): re-run `ts audit run` for it.";
  c.innerHTML = '<div class="usage-head"><h2>Usage</h2></div>';
  c.appendChild(mutedNote(text, "empty-state usage-view-note"));
}

function usageHeadHtml(rows, idleDays){
  var u = D.C.us, whose = usageWhose();
  var html = '<div class="usage-head"><h2>Usage</h2><p class="usage-sub">'+
    esc(usagePlural(rows.length, "audited Model"))+'. '+esc(whose.charAt(0).toUpperCase()+
    whose.slice(1))+', read on '+esc(usageDate(u.at))+'. Idle means no query in '+
    idleDays+' days or more (H17); a Liveboard, an Answer or a Set on a Model counts as a '+
    'dependent. Dependents are those the audit\'s user can see in this Org; "5+" is a lower '+
    'bound, where they were not read in full. The grey band holds Models too new to judge, '+
    'with too short a history, no query time recorded, or idle with no visible dependents '+
    'whose dependents are not fully known. Check what depends on a Model before removing it.</p></div>';
  if(u.dk === false) html += '<div class="unread usage-note" role="note">'+esc("This audit "+
    "predates the check for dependents hidden from the audit's user (ts-cli 0.225.0), so a "+
    "dependent count may miss some: run the audit again to check.")+'</div>';
  if(usageHistoryShort(idleDays)) html += '<div class="unread usage-note" role="note">'+
    esc("The usage history starts on "+usageDate(u.hs)+", "+usagePlural(u.hd, "day")+
    " before the read, under the "+idleDays+" days a never-queried Model needs: those read Not judged.")+'</div>';
  return html + usageOrgNoteHtml();
}

function usageControls(v){
  var counts = {};
  v.rows.forEach(function(r){ counts[r.status] = (counts[r.status] || 0) + 1; });
  v.bar = filterBar({label: "Filter the Models by status", on: v.state.on,
    chips: USAGE_STATUS_ORDER.map(function(s){
      return {f: s, label: USAGE_STATUS[s].label, count: counts[s] || 0};
    }),
    search: {cls: "usage-search", placeholder: "Search Models or owners", aria: "Search Models or owners"}},
    usageApply, function(q){ v.state.q = q; usageApply(); });
  var nodeps = v.rows.filter(usageNoDependents).length;
  var narrow = el("div", "fbar usage-narrow",
    '<span class="fbar-label">Only</span><button type="button" class="fbar-chip" data-f="nodeps" '+
    'aria-pressed="false" title="Only Models nothing depends on"'+(nodeps ? '' : ' disabled')+
    '>No dependents <span class="fbar-count">'+nodeps+'</span></button>');
  narrow.setAttribute("role", "group");
  narrow.setAttribute("aria-label", "Narrow the Models");
  narrow.addEventListener("click", function(e){
    var b = e.target.closest && e.target.closest(".fbar-chip");
    if(!b || b.disabled) return;
    v.state.nodeps = !v.state.nodeps;
    b.setAttribute("aria-pressed", v.state.nodeps ? "true" : "false");
    usageApply();
  });
  var panel = el("div", "fbar-panel usage-filters");
  panel.appendChild(v.bar);
  panel.appendChild(narrow);
  return panel;
}

function usageActionsHtml(){
  return '<div class="usage-actions"><button type="button" class="select-toggle usage-select-shown">'+
    'Select all shown</button><button type="button" class="select-toggle usage-clear">Clear</button>'+
    '<span class="usage-selected-count" aria-live="polite">0 selected</span>'+
    '<button type="button" class="copy-btn usage-export-csv" disabled>Export CSV</button>'+
    '<button type="button" class="copy-btn usage-export-json" disabled>Export JSON</button></div>';
}

/* A dot's click selects (or clears) its row, and brings the row into view. */
function usageDotClick(v, e){
  var dot = e.target.closest && e.target.closest("circle.usage-dot");
  if(!dot) return;
  var g = dot.getAttribute("data-guid"), tr = v.tr[g];
  v.state.sel[g] = !v.state.sel[g];
  usageSyncSelection();
  if(!tr) return;
  if(tr.scrollIntoView) tr.scrollIntoView({block: "nearest"});
  tr.classList.add("usage-flash");
  setTimeout(function(){ tr.classList.remove("usage-flash"); }, 1200);
}

function usageSortBy(v, k){
  var s = v.state.sort, col = USAGE_COLUMNS.filter(function(x){ return x[0] === k; })[0];
  v.state.sort = s && s.key === k ? {key: k, dir: -s.dir} : {key: k, dir: col[2]};
  usageApply();
}

function usageWire(v){
  var c = v.el;
  c.addEventListener("change", function(e){
    if(!e.target.classList.contains("usage-check")) return;
    v.state.sel[e.target.getAttribute("data-guid")] = e.target.checked;
    usageSyncSelection();
  });
  $(".usage-chart", c).addEventListener("click", function(e){ usageDotClick(v, e); });
  $$("th[data-sort]", c).forEach(function(th){
    var k = th.getAttribute("data-sort");
    th.addEventListener("click", function(){ usageSortBy(v, k); });
    th.addEventListener("keydown", function(e){
      if(e.key === "Enter" || e.key === " "){ e.preventDefault(); usageSortBy(v, k); }
    });
  });
  $(".usage-select-shown", c).addEventListener("click", function(){
    v.shown.forEach(function(r){ v.state.sel[r.guid] = true; });
    usageSyncSelection();
  });
  $(".usage-clear", c).addEventListener("click", function(){ v.state.sel = {}; usageSyncSelection(); });
  $(".usage-export-csv", c).addEventListener("click", function(){
    usageDownload(usageCandidatesCsv(usageSelectedRows()), "text/csv;charset=utf-8",
                  "ts-audit-candidates.csv");
  });
  $(".usage-export-json", c).addEventListener("click", function(){
    usageDownload(usageCandidatesJson(usageSelectedRows(), v.idleDays), "application/json",
                  "ts-audit-candidates.json");
  });
}

function buildUsageView(){
  var c = document.getElementById("v-usage");
  c.innerHTML = "";
  var models = (D.C && D.C.m) || [];
  if(usageState() !== "read" || !models.some(function(cm){ return cm.us && cm.us.s; })){
    usageViewNote(c);
    return;
  }
  var on = {};
  USAGE_STATUS_ORDER.forEach(function(s){ on[s] = true; });
  var v = usageView = {el: c, rows: usageRows(), idleDays: D.C.us.si || D.C.us.id, tr: {},
    shown: [], state: {on: on, nodeps: false, q: "", sort: null, sel: {}}};
  c.innerHTML = usageHeadHtml(v.rows, v.idleDays)+usageLegendHtml(v.rows)+'<div class="usage-chart"></div>';
  c.appendChild(usageControls(v));
  c.insertAdjacentHTML("beforeend", usageActionsHtml()+usageTableHtml(v.rows, v.idleDays));
  $$(".usage-table tbody tr", c).forEach(function(tr){ v.tr[tr.getAttribute("data-guid")] = tr; });
  usageWire(v);
  usageApply();
}

/* ── Route registration: a sidebar link only when the run fetched usage ── */
var usageBuilt = false;
registerView({id: "usage", routes: ["usage"],
  nav: usageState() === "absent" ? null : {hash: "#usage", icon: "◷", label: "Usage"},
  show: function(route){
    if(!usageBuilt){ buildUsageView(); usageBuilt = true; }
    return {crumbs: ["Usage"], links: []};
  }});
