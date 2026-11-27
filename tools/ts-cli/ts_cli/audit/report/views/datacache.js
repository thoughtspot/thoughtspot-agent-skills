/* ── Data Cache: which audited Models ThoughtSpot's Data Cache can serve ──
   The data is each corpus Model's `dc` (ts_cli/audit/data_cache.py, compacted in
   report.py): `s` its readiness (ready, blocked, confirm, warning or unknown), `r` the
   reasons [{c rule, b 1 when it blocks, q 1 when it may block (only readings the product
   team is to confirm), l label, i items}], `k` the calendars its columns and formulas
   use [{n column or formula, c calendar, u 1 custom, 0 code-based, 2 unclear (a
   code-based value a custom calendar on the connection is also named), t 1 when set on
   the Table column, f 1 when named in a formula}], `ku` the sources whose TML was not
   read, `cc` the custom calendars registered on its connections [{n connection, k
   calendar names}], or null when they were not fetched, and `na` the checks not made
   for it. The
   readiness is read off the fields the rules P19-P28 judge by, so it says what their
   findings say. JSON written before this view has no `dc`: its Models read "Not
   assessed". #datacache lists every Model; #datacache/<guid> is one Model's page
   (model_nav.js), its row alone under the Model's tabs, with a way back to the list:
   the filter bar, which belongs to the list, is left out there. The list's filter bar is
   the shared one (filter_bar.js): a chip per readiness, multi-select, all on at first,
   switching one off hides its Models; the search narrows what the chips leave. */
var DC_STATES = {
  ready: {label: "Can use", cls: "dc-ready"},
  blocked: {label: "Can’t use", cls: "dc-blocked"},
  confirm: {label: "To confirm", cls: "dc-confirm"},
  warning: {label: "Warning", cls: "dc-warning"},
  unknown: {label: "Not assessed", cls: "dc-unknown"}
};
var DC_ORDER = ["ready", "blocked", "confirm", "warning", "unknown"];
var DC_CHECKS = {P19: "custom calendars", P20: "SQL pass-through", P21: "semantic query",
  P22: "connection calendars", P23: "source types", P24: "connection settings",
  P25: "Table variables", P26: "formula parameters", P27: "SQL Views", P28: "RLS rules"};
var DC_NO_DATA = {s: "unknown", r: [], k: [], cc: null, na: []};
var _dcOn = {ready: true, blocked: true, confirm: true, warning: true, unknown: true};
var _dcSearch = "";

function dcRows(){
  if(!D.C || !D.C.m) return [];
  return D.C.m.map(function(cm){
    var m = D.L[cm.mi] || {n: "", g: ""};
    var dc = cm.dc || DC_NO_DATA;
    return {name: m.n || "", guid: m.g || "", dc: dc,
            state: DC_STATES[dc.s] ? dc.s : "unknown"};
  });
}

/* The calendars a Model's columns and formulas use, one line per calendar: "Retail 445
   (custom): Order Date, Ship Date (from its Table), Week Start (in a formula)". */
function dcCalendarLines(dc){
  var order = [], columns = Object.create(null);
  (dc.k || []).forEach(function(k){
    var key = k.c + (k.u === 2 ? " (code-based or custom, to confirm)" :
      k.u ? " (custom)" : " (code-based)");
    if(!columns[key]){ columns[key] = []; order.push(key); }
    columns[key].push(k.n + (k.t ? " (from its Table)" : k.f ? " (in a formula)" : ""));
  });
  return order.map(function(key){ return key + ": " + columns[key].join(", "); });
}

function dcSearchText(row){
  var parts = [row.name, DC_STATES[row.state].label];
  (row.dc.r || []).forEach(function(r){ parts.push(r.l); parts = parts.concat(r.i || []); });
  (row.dc.k || []).forEach(function(k){ parts.push(k.n, k.c); });
  (row.dc.cc || []).forEach(function(cc){ parts.push(cc.n); parts = parts.concat(cc.k || []); });
  return parts.join(" ").toLowerCase();
}

/* A reason that may block says "to confirm" once: its items name the reading to confirm
   (P21, P24, P28 all do), so the qualifier is added only when none does. */
function dcSaysToConfirm(r){
  return (r.i || []).some(function(i){ return String(i).indexOf("to confirm") !== -1; });
}

function dcReasonsHtml(row){
  var dc = row.dc, html = "";
  (dc.r || []).forEach(function(r){
    html += '<div class="dc-reason'+(r.b ? ' dc-blocks' : '')+(r.q ? ' dc-may-block' : '')+
      '"><span class="dc-rule">'+esc(r.c)+'</span> '+esc(r.l)+': '+
      esc((r.i || []).join(", "))+(r.q && !dcSaysToConfirm(r) ?
        ' <span class="dc-muted">(to confirm)</span>' : '')+
      '</div>';
  });
  /* What was not checked: every check (none ran, or the report predates them), or some
     (a check that could not judge the Model, as when a search failed). */
  var missed = (dc.na || []).map(function(c){ return DC_CHECKS[c] || c; });
  if(row.dc === DC_NO_DATA){
    html += '<div class="dc-muted">This report predates the Data Cache checks: re-run '+
      '`ts audit run` with the Performance angle.</div>';
  } else if(missed.length >= Object.keys(DC_CHECKS).length){
    html += '<div class="dc-muted">The Performance checks that decide it did not run '+
      '(run with --angles P).</div>';
  } else if(missed.length){
    html += '<div class="dc-muted">Not checked: '+esc(missed.join(", "))+'</div>';
  }
  return html || '<span class="dc-muted">None</span>';
}

/* "None set" only when every source's TML was read: a source not read (`ku`) may set a
   calendar on its Table columns that the audit did not see. */
function dcCalendarsHtml(row){
  var lines = dcCalendarLines(row.dc), unread = row.dc.ku || [];
  var html = lines.map(function(line){
    return '<div class="dc-calendar">'+esc(line)+'</div>'; }).join("");
  if(unread.length){
    html += '<div class="dc-muted">Not read: '+unread.length+' source'+
      (unread.length === 1 ? '' : 's')+' ('+esc(unread.join(", "))+
      '), whose Table columns may set a calendar</div>';
  } else if(!lines.length){
    html = '<span class="dc-muted">None set: the default calendar</span>';
  }
  if(row.dc.cc && row.dc.cc.length){
    html += '<div class="dc-muted">On its connections: '+esc(row.dc.cc.map(function(cc){
      return cc.n+" ("+cc.k.join(", ")+")"; }).join("; "))+'</div>';
  }
  return html;
}

function dcRowHtml(row){
  var st = DC_STATES[row.state];
  return '<tr data-state="'+row.state+'">'+
    '<td><a href="#model/'+esc(row.guid)+'">'+esc(row.name || row.guid)+'</a></td>'+
    '<td><span class="dc-state '+st.cls+'">'+st.label+'</span></td>'+
    '<td>'+dcReasonsHtml(row)+'</td>'+
    '<td>'+dcCalendarsHtml(row)+'</td></tr>';
}

/* The list's filter bar: a chip per readiness, with its count, and the search box. */
function dcToolbar(rows, onChange){
  var counts = {};
  rows.forEach(function(r){ counts[r.state] = (counts[r.state] || 0) + 1; });
  var panel = el("div", "fbar-panel dc-filter");
  panel.appendChild(filterBar({label: "Show Models by Data Cache readiness", on: _dcOn,
    chips: DC_ORDER.map(function(f){ return {f: f, label: DC_STATES[f].label, count: counts[f] || 0}; }),
    search: {cls: "dc-search", placeholder: "Search Models, reasons, calendars…",
             aria: "Search Data Cache readiness", value: _dcSearch}},
    onChange, function(value){ _dcSearch = value; onChange(); }));
  return panel;
}

function dcShown(rows){
  var term = _dcSearch.trim().toLowerCase();
  return rows.filter(function(r){
    return _dcOn[r.state] && (!term || dcSearchText(r).indexOf(term) !== -1);
  });
}

/* One Model's page: its tabs, its row, and the way back to every Model. */
function buildDataCacheModel(c, rows, guid){
  var row = rows.filter(function(r){ return r.guid === guid; })[0];
  if(row) c.appendChild(modelTabs(guid, "datacache"));
  var back = el("div", "crossmodel-filter dc-one", row ?
    'Showing 1 Model of '+rows.length+'. <a class="dc-all" href="#datacache">Show all '+rows.length+' Models</a>' :
    'This report has no such Model. <a class="dc-all" href="#datacache">Show all '+rows.length+' Models</a>');
  c.appendChild(back);
  if(!row) return;
  var table = el("table", "cleanup-table dc-table");
  table.innerHTML = '<thead><tr><th>Model</th><th>Data Cache</th><th>Reasons</th>'+
    '<th>Calendars in use</th></tr></thead><tbody>'+dcRowHtml(row)+'</tbody>';
  var wrap = el("div", "crossmodel-wrap");
  wrap.appendChild(table);
  c.appendChild(wrap);
}

function buildDataCache(D, guid){
  var c = document.getElementById("v-datacache");
  c.innerHTML = "";
  var rows = dcRows();
  if(rows.length && guid){ buildDataCacheModel(c, rows, guid); return; }
  if(!rows.length){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">⚡</div>'+
      '<div class="ph-text">No Models in this report</div>'+
      '<div class="ph-sub">Data Cache readiness is assessed per audited Model.</div></div>';
    return;
  }
  c.appendChild(el("div", "ftree-intro", "Which audited Models ThoughtSpot’s Data Cache "+
    "can serve. Any of these stops it: a custom calendar, a SQL pass-through formula, a "+
    "semantic query Model, a source other than Snowflake or Databricks, an OAuth, "+
    "PrivateLink or parameterized connection or Table, a parameter in a formula, a SQL "+
    "View, or an RLS rule beyond its Table\u2019s own columns. A connection that defines "+
    "custom calendars is a warning, since a query that picks one at run time is not cached. "+
    "To confirm: the only reasons are readings the product team is to review (OAuth read "+
    "from client credentials (a client ID or secret), PrivateLink read from the host, a measure only flagged "+
    "pre-aggregated, an RLS rule\u2019s \u201c= null\u201d test, a custom calendar named in "+
    "a formula, a code-based calendar name that a custom calendar also has). Anything "+
    "the audit could not read makes a Model Not assessed, never Can use."));
  var table = el("table", "cleanup-table dc-table");
  table.innerHTML = '<thead><tr><th>Model</th><th>Data Cache</th><th>Reasons</th>'+
    '<th>Calendars in use</th></tr></thead><tbody></tbody>';
  var wrap = el("div", "crossmodel-wrap");
  wrap.appendChild(table);
  var bar = dcToolbar(rows, render);
  function render(){
    var shown = dcShown(rows);
    table.tBodies[0].innerHTML = shown.length ? shown.map(dcRowHtml).join("") :
      '<tr><td colspan="4" class="empty-state">No Models match.</td></tr>';
    $(".fbar", bar)._total(shown.length+" of "+rows.length+" Models shown");
  }
  c.appendChild(bar);
  c.appendChild(wrap);
  render();
}

registerView({id: "datacache", routes: ["datacache"],
  nav: {hash: "#datacache", icon: "⚡", label: "Data Cache"},
  show: function(route){
  buildDataCache(D, route.id);
  if(!route.id || !findCorpusModel(route.id)) return {crumbs: ["Data Cache"], links: []};
  highlightSidebarModel(route.id);
  return modelCrumbs(route.id, "Data Cache");
}});
