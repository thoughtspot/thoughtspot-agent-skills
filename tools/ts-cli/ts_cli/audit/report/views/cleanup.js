/* ── Build Cleanup view ── */
var _cleanupSevListener = null;
function buildCleanup(D){
  var c = document.getElementById("v-cleanup");
  c.innerHTML = "";

  if(_cleanupSevListener) document.removeEventListener("sev-filter-changed",_cleanupSevListener);

  var findings = D.F || [];
  /* The rules that feed this view (catalog `views: [cleanup]`), one section each */
  var cleanupIds = viewIds("cleanup");
  var hasAny = findings.some(function(f){ return inView("cleanup", f); });

  if(!hasAny && !D.C){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">✂</div>'+
      '<div class="ph-text">No cleanup actions available</div>'+
      '<div class="ph-sub">No orphan or stale object findings detected.</div></div>';
    return;
  }

  /* Copy button at top */
  var topBar = el("div","","");
  topBar.style.cssText = "display:flex;justify-content:flex-end;margin-bottom:12px;";
  var copyBtn = el("button","copy-btn","Copy Selected");
  copyBtn.addEventListener("click",function(){
    var checked = $$("input.cleanup-check:checked",c);
    if(checked.length === 0) return;
    var lines = checked.map(function(cb){
      return cb.getAttribute("data-name")+" | "+cb.getAttribute("data-guid");
    });
    navigator.clipboard.writeText(lines.join("\n")).then(function(){
      showToast("Copied "+checked.length+" item"+(checked.length!==1?"s":"")+"!");
    });
  });
  topBar.appendChild(copyBtn);
  c.appendChild(topBar);

  cleanupIds.forEach(function(ci){
    var items = findings.filter(function(f){ return f.ci === ci; });
    var title = esc((D.K && D.K[ci] && D.K[ci].d) || ci) + " — " + ci;
    /* A rule reporting on more than one kind of object gets a section per kind */
    var kinds = [];
    items.forEach(function(f){ if(kinds.indexOf(f.ot) === -1) kinds.push(f.ot); });
    if(kinds.length > 1){
      kinds.forEach(function(kind){
        buildCleanupSection(c, title+" ("+esc(kind)+")",
          items.filter(function(f){ return f.ot === kind; }), D, "");
      });
    } else {
      buildCleanupSection(c, title, items, D, "No findings.");
    }
  });

  /* Wire severity filter */
  function applySevFilter(){
    $$("tr[data-severity]",c).forEach(function(tr){
      var sev = tr.getAttribute("data-severity");
      tr.style.display = activeSevs[sev] ? "" : "none";
    });
  }
  _cleanupSevListener = applySevFilter;
  document.addEventListener("sev-filter-changed",_cleanupSevListener);
}

function buildCleanupSection(container, title, items, D, emptyMsg){
  var sec = el("div","cleanup-section");
  sec.innerHTML = '<h3>'+title+' ('+items.length+')</h3>';

  if(items.length === 0){
    sec.innerHTML += '<div class="empty-state">'+emptyMsg+'</div>';
    container.appendChild(sec);
    return;
  }

  /* Actions row */
  var actions = el("div","section-actions");
  var selectToggle = el("button","select-toggle","Select all");
  var allSelected = false;
  selectToggle.addEventListener("click",function(){
    allSelected = !allSelected;
    $$("input.cleanup-check",sec).forEach(function(cb){ cb.checked = allSelected; });
    selectToggle.textContent = allSelected ? "Deselect all" : "Select all";
  });
  actions.appendChild(selectToggle);
  sec.appendChild(actions);

  /* Table */
  var tblWrap = el("div","","");
  tblWrap.style.overflowX = "auto";
  var MAX_VISIBLE = 20;
  var showAll = items.length <= MAX_VISIBLE;
  var tbl = el("table","cleanup-table");

  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  ["","Severity","Name","GUID","Detail"].forEach(function(h){
    var th = el("th","",h);
    if(h==="") th.style.width = "32px";
    hrow.appendChild(th);
  });
  if(D.C && D.C.u){
    hrow.appendChild(el("th","","Link"));
  }
  thead.appendChild(hrow);
  tbl.appendChild(thead);

  var tbody = document.createElement("tbody");
  items.forEach(function(f, idx){
    var tr = document.createElement("tr");
    tr.setAttribute("data-severity",f.s);
    if(!activeSevs[f.s]) tr.style.display = "none";
    if(!showAll && idx >= MAX_VISIBLE) tr.style.display = "none";
    if(!showAll && idx >= MAX_VISIBLE) tr.classList.add("cleanup-overflow");

    var model = D.L[f.mi];
    var name = model ? model.n : "";
    var guid = model ? model.g : "";

    /* Checkbox */
    var tdCb = el("td","");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "cleanup-check";
    cb.setAttribute("data-name",name);
    cb.setAttribute("data-guid",guid);
    tdCb.appendChild(cb);
    tr.appendChild(tdCb);

    /* Severity */
    var tdSev = el("td","");
    tdSev.innerHTML = severityPill(f.s);
    tr.appendChild(tdSev);

    /* Name */
    var tdName = el("td","");
    if(model){
      tdName.innerHTML = '<a href="#model/'+guid+'">'+esc(name)+'</a>';
    } else {
      tdName.textContent = name;
    }
    tr.appendChild(tdName);

    /* GUID */
    var tdGuid = el("td","");
    tdGuid.textContent = guid;
    tdGuid.style.fontFamily = "var(--mono)";
    tdGuid.style.fontSize = "10px";
    tdGuid.style.color = "var(--muted)";
    tr.appendChild(tdGuid);

    /* Detail */
    var tdDetail = el("td","");
    tdDetail.textContent = f.d || "";
    tdDetail.style.maxWidth = "300px";
    tdDetail.style.whiteSpace = "pre-wrap";
    tdDetail.style.wordBreak = "break-word";
    tr.appendChild(tdDetail);

    /* TS Link */
    if(D.C && D.C.u){
      var tdLink = el("td","");
      tdLink.innerHTML = tsLink(D.C.u, guid, "TABLE");
      tr.appendChild(tdLink);
    }

    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  tblWrap.appendChild(tbl);
  sec.appendChild(tblWrap);

  if(!showAll){
    var showBtn = el("button","show-all-btn","Show all "+items.length+" items");
    showBtn.style.cssText = "margin:8px 0 4px;padding:6px 16px;border:1px solid var(--hair);border-radius:6px;background:var(--bg-card);cursor:pointer;font-size:12px;color:var(--accent);";
    showBtn.addEventListener("click",function(){
      $$(".cleanup-overflow",sec).forEach(function(tr){
        tr.classList.remove("cleanup-overflow");
        var sev = tr.getAttribute("data-severity");
        tr.style.display = activeSevs[sev] ? "" : "none";
      });
      showBtn.remove();
    });
    sec.appendChild(showBtn);
  }

  container.appendChild(sec);
}

function showToast(msg){
  var existing = $(".toast");
  if(existing) existing.remove();
  var toast = el("div","toast",msg);
  document.body.appendChild(toast);
  setTimeout(function(){ if(toast.parentNode) toast.remove(); }, 2200);
}

/* ── Build placeholder ── */
function buildPlaceholder(containerId,title,desc){
  var c = document.getElementById(containerId);
  c.innerHTML = '<div class="view-placeholder">'+
    '<div class="ph-icon">⚒</div>'+
    '<div class="ph-text">'+title+'</div>'+
    '<div class="ph-sub">'+desc+' &mdash; view coming soon</div>'+
    '</div>';
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "cleanup", routes: ["cleanup"],
  nav: {hash: "#cleanup", icon: "✂", label: "Cleanup"},
  show: function(route){
  var breadcrumbParts, breadcrumbLinks;
  breadcrumbParts = ["Cleanup"];
  breadcrumbLinks = [];
  buildCleanup(D);
  return {crumbs: breadcrumbParts, links: breadcrumbLinks};
}});
