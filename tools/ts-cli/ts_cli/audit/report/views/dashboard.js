/* ── Dashboard state ── */
var builtViews = {};
var READINESS_LABEL = {ready:"Ready", needs_work:"Needs work", not_ready:"Not ready"};
function readinessByGuid(){
  var out = {};
  if(D.C && D.C.m) D.C.m.forEach(function(cm){ var m = D.L[cm.mi]; if(m && cm.rs) out[m.g] = cm.rs; });
  return out;
}

/* ── Build Dashboard ── */
function buildDashboard(){
  var c = document.getElementById("v-dashboard");
  var html = "";

  /* Header bar */
  html += '<div class="dash-header">';
  if(D.C){
    if(D.C.u){
      html += '<a class="cluster-url" href="'+D.C.u+'" target="_blank" rel="noopener">'+esc(D.C.u)+' <span class="ext">↗</span></a>';
    }
    if(D.C.p) html += '<span class="meta-item">Profile: <strong>'+esc(D.C.p)+'</strong></span>';
    if(D.C.as) html += '<span class="meta-item">Assessment: <strong>'+esc(D.C.as)+'</strong></span>';
    if(D.C.dt) html += '<span class="meta-item">Date: <strong>'+esc(D.C.dt)+'</strong></span>';
    if(D.C.ar && D.C.ar.length > 0){
      html += '<div class="angles">';
      D.C.ar.forEach(function(code){
        var a = ANGLE_SHORT[code] || code;
        html += '<span class="angle-tag">'+(ANGLE_LABELS[a]||a)+'</span>';
      });
      html += '</div>';
    }
  } else {
    html += '<span class="meta-item">Audit report &mdash; no corpus data</span>';
  }
  html += '</div>';

  /* Items no rule judged: malformed TML (BL-406 item 10). Shown, never silent. */
  if(D.C && D.C.ur && D.C.ur.length > 0){
    html += '<div class="unread" role="note"><strong>Could not be read — '+D.C.ur.length+
      ' item'+(D.C.ur.length === 1 ? '' : 's')+' not judged.</strong> Each one\u2019s own TML, or TML it '+
      'depends on (a Table it uses, the Model an Answer is built on), holds a list or a single '+
      'value where a mapping belongs. Fix the TML each entry names and re-run.<ul>';
    D.C.ur.slice(0, 50).forEach(function(u){ html += '<li><code>'+esc(u)+'</code></li>'; });
    if(D.C.ur.length > 50) html += '<li>…and '+(D.C.ur.length - 50)+' more (see the run’s JSON)</li>';
    html += '</ul></div>';
  }

  /* Severity cards */
  html += '<div class="sev-cards">';
  SEVS.forEach(function(s){
    var count = (D.S && D.S.bs) ? (D.S.bs[s]||0) : 0;
    html += '<div class="sev-card" data-sev="'+s+'" tabindex="0" role="button" aria-label="'+count+' '+s.toLowerCase()+' findings">';
    html += '<div class="sev-count">'+count+'</div>';
    html += '<div class="sev-label" data-count="'+count+'">'+s+'</div>';
    html += '</div>';
  });
  html += '</div>';

  /* Heatmap */
  html += buildHeatmap();

  /* Stats strip */
  html += '<div class="stats-strip">';
  var os = (D.S && D.S.os) || {};
  var stats = [
    {v: os.models || 0, l: "Models", tip: "Number of ThoughtSpot models scanned", hash: "#objectmap/dependencies"},
    {v: os.tables || 0, l: "Tables", tip: "Total tables across all scanned models", hash: "#objectmap/table-reuse"},
    {v: D.S ? (D.S.cr||0) : 0, l: "Checks Run", tip: "Audit checks evaluated across all models", hash: "#crossmodel"},
    {v: D.F ? D.F.length : 0, l: "Total Findings", tip: "Total findings across all severity levels", hash: "#crossmodel"}
  ];
  stats.forEach(function(s){
    html += '<div class="stat-box" data-hash="'+s.hash+'" title="'+s.tip+'" tabindex="0" role="button" style="cursor:pointer;">';
    html += '<div class="stat-value">'+s.v+'</div>';
    html += '<div class="stat-label">'+s.l+'</div>';
    html += '</div>';
  });
  html += '</div>';

  c.innerHTML = html;

  /* Wire up severity card clicks */
  $$(".sev-card",c).forEach(function(card){
    card.addEventListener("click",function(){
      navigate("#crossmodel?severity="+card.getAttribute("data-sev"));
    });
    card.addEventListener("keydown",function(e){
      if(e.key === "Enter" || e.key === " "){
        e.preventDefault();
        navigate("#crossmodel?severity="+card.getAttribute("data-sev"));
      }
    });
  });

  /* Wire up stat box clicks */
  $$(".stat-box",c).forEach(function(box){
    box.addEventListener("click",function(){
      var hash = box.getAttribute("data-hash");
      if(hash) navigate(hash);
    });
    box.addEventListener("keydown",function(e){
      if(e.key === "Enter" || e.key === " "){
        e.preventDefault();
        var hash = box.getAttribute("data-hash");
        if(hash) navigate(hash);
      }
    });
  });

  /* Wire up heatmap cell clicks */
  $$(".heatmap .cell",c).forEach(function(cell){
    cell.addEventListener("click",function(){
      var guid = cell.getAttribute("data-guid");
      var angle = cell.getAttribute("data-angle");
      if(guid && angle) navigate("#model/"+guid+"/"+angle);
    });
  });

  /* Wire up angle column header clicks */
  var angleHeaders = c.querySelectorAll("th.angle-col");
  Array.prototype.slice.call(angleHeaders).forEach(function(th){
    th.style.cursor = "pointer";
    th.addEventListener("click",function(){
      navigate("#crossmodel?angle="+th.getAttribute("data-angle"));
    });
  });

}

/* ── Heatmap builder ── */
function buildHeatmap(){
  if(!D.F || D.F.length === 0){
    return '<div class="heatmap-wrap"><div class="heatmap-title">Cluster Heatmap</div>'+
           '<p style="color:var(--muted);font-size:12px;">No findings to display.</p></div>';
  }

  /* Determine angles present */
  var anglesPresent = {};
  var multiCategory = false;
  D.F.forEach(function(f){
    var fa = findingAngles(f);
    if(fa.length > 1) multiCategory = true;
    fa.forEach(function(a){ anglesPresent[a] = true; });
  });
  var angleKeys = Object.keys(ANGLE_LABELS).filter(function(a){ return anglesPresent[a]; });

  /* Build model GUID set from corpus — heatmap only shows model rows */
  var modelGuids = {};
  if(D.C && D.C.m) D.C.m.forEach(function(cm){ var m = D.L[cm.mi]; if(m) modelGuids[m.g] = {mi: cm.mi, name: m.n}; });

  /* Group findings by model GUID — non-model findings (answers, tables, formulas)
     are rolled up under their parent model via matching GUID, or shown under the
     first model if no match (single-model audits) */
  var byGuid = {};
  var modelGuidList = Object.keys(modelGuids);
  D.F.forEach(function(f){
    var m = D.L[f.mi];
    if(!m) return;
    var guid = m.g;
    if(modelGuids[guid]){
      if(!byGuid[guid]) byGuid[guid] = {mi: modelGuids[guid].mi, name: modelGuids[guid].name, guid: guid, byAngle: {}};
    } else if(modelGuidList.length === 1){
      /* Single-model audit: child-object findings (tables/formulas/answers) roll
         up to the one model. */
      guid = modelGuidList[0];
      if(!byGuid[guid]) byGuid[guid] = {mi: modelGuids[guid].mi, name: modelGuids[guid].name, guid: guid, byAngle: {}};
    } else if(modelGuidList.length === 0){
      if(!byGuid[guid]) byGuid[guid] = {mi: f.mi, name: m.n, guid: guid, byAngle: {}};
    } else {
      /* Multi-model audit: a finding whose object_guid is not a model GUID
         (cross-cutting formula/answer/table findings, or an empty guid) cannot be
         attributed to a specific model. Do NOT roll it up onto the first model —
         that inflated the first model's heatmap severity with findings it does not
         own (e.g. GTM Campaigns showing HIGH Human from 81 cross-answer formula
         findings). Skip it from the model heatmap; it still appears in Cross-Model. */
      return;
    }
    findingAngles(f).forEach(function(a){
      if(!byGuid[guid].byAngle[a]) byGuid[guid].byAngle[a] = [];
      byGuid[guid].byAngle[a].push(f);
    });
  });

  /* Build rows: [{mi, name, guid, worstOverall, cells:{angle:severity}}] */
  var rows = [];
  Object.keys(byGuid).forEach(function(guid){
    var entry = byGuid[guid];
    var cells = {};
    var allFindings = [];
    angleKeys.forEach(function(a){
      var ff = entry.byAngle[a] || [];
      cells[a] = ff.length > 0 ? worstSev(ff) : "NONE";
      allFindings = allFindings.concat(ff);
    });
    rows.push({mi:entry.mi, n:entry.name, g:guid, worst: worstSev(allFindings), cells:cells});
  });

  /* Sort by worst severity descending (critical first) */
  rows.sort(function(a,b){
    return (SEV_ORDER[a.worst]||99) - (SEV_ORDER[b.worst]||99);
  });

  /* Build table */
  var html = '<div class="heatmap-wrap">';
  html += '<div class="heatmap-title">Cluster Heatmap</div>';
  if(multiCategory){
    html += '<p style="color:var(--muted);font-size:12px;">A rule in more than one category is shown under each, so category columns can count more findings than the total.</p>';
  }
  html += '<table class="heatmap"><thead><tr>';
  html += '<th class="model-col">Model</th>';
  var readiness = readinessByGuid();
  var showReadiness = Object.keys(readiness).length > 0;
  /* not an angle-col: that class makes a header a category filter */
  if(showReadiness) html += '<th class="score-col" title="'+esc(READINESS_TITLE)+'">Spotter readiness</th>';
  angleKeys.forEach(function(a){
    html += '<th class="angle-col" data-angle="'+a+'" title="Filter by '+ANGLE_LABELS[a]+'">'+
            ANGLE_LABELS[a]+'</th>';
  });
  html += '</tr></thead><tbody>';

  rows.forEach(function(r){
    html += '<tr>';
    html += '<td class="model-name"><a href="#model/'+r.g+'" title="'+esc(r.n)+'">'+esc(r.n)+'</a></td>';
    if(showReadiness){
      var rs = readiness[r.g];
      html += rs ? '<td><span class="readiness" data-level="'+esc(rs.l)+'" title="'+esc(READINESS_LABEL[rs.l]||rs.l)+'">'+
                   Math.floor(rs.s)+'</span></td>' : '<td></td>';
    }
    angleKeys.forEach(function(a){
      var sev = r.cells[a] || "NONE";
      var cellText = sev === "NONE" ? "" : sev === "PASS" ? "✓" : sev.charAt(0);
      html += '<td><span class="cell" data-severity="'+sev+'" data-guid="'+r.g+'" data-angle="'+a+
              '" title="'+esc(r.n)+' / '+(ANGLE_LABELS[a]||a)+': '+sev+'" role="button" tabindex="0">'+cellText+'</span></td>';
    });
    html += '</tr>';
  });

  html += '</tbody></table></div>';

  return html;
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "dashboard", routes: ["dashboard"], fallback: true,
  nav: {hash: "#dashboard", icon: "▣", label: "Dashboard",
        badge: function(){ var n = countCritHigh(); return n > 0 ? n : null; }},
  show: function(route){
  var breadcrumbParts, breadcrumbLinks;
  breadcrumbParts = ["Dashboard"];
  breadcrumbLinks = [];
  if(!builtViews.dashboard){ buildDashboard(); builtViews.dashboard=true; }
  return {crumbs: breadcrumbParts, links: breadcrumbLinks};
}});
