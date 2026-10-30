var _crossmodelSevListener = null;

/* ── Build Cross-Model view ── */
function buildCrossModel(D, initialFilters){
  var c = document.getElementById("v-crossmodel");
  c.innerHTML = "";

  /* Remove old listener before rebuilding */
  if(_crossmodelSevListener) document.removeEventListener("sev-filter-changed", _crossmodelSevListener);

  initialFilters = initialFilters || {};

  /* Resolve initial filter values */
  var initSev = initialFilters.severity || null;  /* e.g. "HIGH" */
  var initAngle = initialFilters.angle || null;   /* e.g. "D" (short code) or full angle name */

  /* Normalise angle filter: convert short code to full angle name if needed */
  if(initAngle && ANGLE_SHORT[initAngle]){
    initAngle = ANGLE_SHORT[initAngle]; /* "D" → "data_modeling" */
  }

  var findings = D.F || [];

  /* Sort state */
  var sortCol = "s";   /* default: sort by severity */
  var sortDir = "asc"; /* "asc" | "desc" */

  /* ── Filter toolbar ── */
  var toolbar = el("div","crossmodel-filter");
  var searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "Search models, check IDs, details…";
  searchInput.setAttribute("aria-label","Search findings");
  toolbar.appendChild(searchInput);

  var groupLabel = el("label","");
  var groupChk = document.createElement("input");
  groupChk.type = "checkbox";
  groupChk.id = "cm-group-by-check";
  groupLabel.appendChild(groupChk);
  groupLabel.appendChild(document.createTextNode(" Group by check ID"));
  toolbar.appendChild(groupLabel);

  var showAllLabel = el("label","");
  var showAllChk = document.createElement("input");
  showAllChk.type = "checkbox";
  showAllChk.id = "cm-show-all-checks";
  showAllLabel.appendChild(showAllChk);
  showAllLabel.appendChild(document.createTextNode(" Show all checks"));
  showAllLabel.style.display = "none";
  toolbar.appendChild(showAllLabel);

  var countEl = el("span","cm-count","");
  toolbar.appendChild(countEl);
  c.appendChild(toolbar);

  /* ── Table wrapper ── */
  var wrap = el("div","crossmodel-wrap");
  var table = el("table","crossmodel-table");
  table.setAttribute("role","grid");

  /* Header */
  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  var cols = [
    {key:"s",  label:"Severity", cls:"col-sev"},
    {key:"ci", label:"Check",    cls:"col-check"},
    {key:"a",  label:"Angle",    cls:"col-angle"},
    {key:"mi", label:"Model",    cls:"col-model"},
    {key:"ot", label:"Type",     cls:"col-type"},
    {key:"d",  label:"Detail",   cls:"col-detail"}
  ];
  var thEls = [];
  cols.forEach(function(col){
    var th = el("th", col.cls, col.label);
    th.setAttribute("data-col", col.key);
    th.setAttribute("tabindex","0");
    thEls.push(th);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);

  var tbody = document.createElement("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);
  c.appendChild(wrap);

  /* ── Sort function ── */
  function sortFindings(arr){
    return arr.slice().sort(function(a,b){
      var av, bv, cmp = 0;
      if(sortCol === "s"){
        av = SEV_ORDER[a.s] !== undefined ? SEV_ORDER[a.s] : 99;
        bv = SEV_ORDER[b.s] !== undefined ? SEV_ORDER[b.s] : 99;
        cmp = av - bv;
      } else if(sortCol === "ci"){
        av = a.ci || "";
        bv = b.ci || "";
        cmp = av < bv ? -1 : (av > bv ? 1 : 0);
      } else if(sortCol === "a"){
        av = (ANGLE_LABELS[a.a] || a.a || "").toLowerCase();
        bv = (ANGLE_LABELS[b.a] || b.a || "").toLowerCase();
        cmp = av < bv ? -1 : (av > bv ? 1 : 0);
      } else if(sortCol === "mi"){
        av = (D.L[a.mi] ? D.L[a.mi].n : "").toLowerCase();
        bv = (D.L[b.mi] ? D.L[b.mi].n : "").toLowerCase();
        cmp = av < bv ? -1 : (av > bv ? 1 : 0);
      } else if(sortCol === "ot"){
        av = (a.ot || "").toLowerCase();
        bv = (b.ot || "").toLowerCase();
        cmp = av < bv ? -1 : (av > bv ? 1 : 0);
      } else if(sortCol === "d"){
        av = (a.d || "").toLowerCase();
        bv = (b.d || "").toLowerCase();
        cmp = av < bv ? -1 : (av > bv ? 1 : 0);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }

  /* ── Update sort header indicators ── */
  function updateSortHeaders(){
    thEls.forEach(function(th){
      th.classList.remove("sort-asc","sort-desc");
      if(th.getAttribute("data-col") === sortCol){
        th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
      }
    });
  }

  /* ── Check if a row passes text search ── */
  function rowMatchesSearch(f, searchTerm){
    if(!searchTerm) return true;
    var term = searchTerm.toLowerCase();
    var modelName = (D.L[f.mi] ? D.L[f.mi].n : "").toLowerCase();
    var detail = (f.d || "").toLowerCase();
    var checkId = (f.ci || "").toLowerCase();
    var angle = anglesLabel(f).toLowerCase();
    var objectType = (f.ot || "").toLowerCase();
    return modelName.indexOf(term) !== -1
        || detail.indexOf(term) !== -1
        || checkId.indexOf(term) !== -1
        || angle.indexOf(term) !== -1
        || objectType.indexOf(term) !== -1;
  }

  /* ── Build a single data row ── */
  function buildRow(f){
    var tr = document.createElement("tr");
    tr.setAttribute("data-severity", f.s);
    tr.setAttribute("data-angle", f.a);
    var mi = f.mi;
    tr.setAttribute("data-model", mi);
    tr.setAttribute("data-check", f.ci || "");

    /* Severity cell */
    var tdSev = el("td","col-sev");
    tdSev.innerHTML = severityPill(f.s);
    tr.appendChild(tdSev);

    /* Check ID cell */
    var tdCheck = el("td","col-check");
    tdCheck.textContent = f.ci || "";
    tr.appendChild(tdCheck);

    /* Angle cell */
    var tdAngle = el("td","col-angle");
    tdAngle.textContent = anglesLabel(f);
    tr.appendChild(tdAngle);

    /* Model cell */
    var tdModel = el("td","col-model");
    var model = D.L[mi];
    if(model){
      var mHtml = '<a class="model-link" href="#model/'+model.g+'" data-route="#model/'+model.g+'">'+esc(model.n)+'</a>';
      if(D.C && D.C.u){
        mHtml += '<a class="ts-icon" href="'+D.C.u+'/#/data/tables/'+model.g+'" target="_blank" rel="noopener" title="Open in ThoughtSpot">↗</a>';
      }
      tdModel.innerHTML = mHtml;
    } else {
      tdModel.textContent = "(model "+mi+")";
    }
    tr.appendChild(tdModel);

    /* Type cell */
    var tdType = el("td","col-type");
    tdType.textContent = f.ot || "";
    tr.appendChild(tdType);

    /* Detail cell */
    var tdDetail = el("td","col-detail detail-cell");
    tdDetail.textContent = f.d || "";
    tr.appendChild(tdDetail);

    return tr;
  }

  /* ── Render table body ── */
  function renderTable(){
    var searchTerm = searchInput.value;
    var grouped = groupChk.checked;
    var sorted = sortFindings(findings);

    /* Apply initial angle filter */
    var visible = sorted.filter(function(f){
      if(initSev && f.s !== initSev) return false;
      if(initAngle && findingAngles(f).indexOf(initAngle) === -1) return false;
      return true;
    });

    /* Apply text search */
    var filtered = visible.filter(function(f){
      return rowMatchesSearch(f, searchTerm);
    });

    tbody.innerHTML = "";
    var shownCount = 0;

    if(grouped){
      /* Group by check ID */
      var allCheckIds = (D.S && D.S.ac) ? D.S.ac : [];
      var groups = {};
      var groupOrder = [];

      if(showAllChk.checked){
        allCheckIds.forEach(function(cid){
          if(!groups[cid]){ groups[cid] = []; groupOrder.push(cid); }
        });
      }

      filtered.forEach(function(f){
        var key = f.ci || "(no check)";
        if(!groups[key]){ groups[key] = []; groupOrder.push(key); }
        groups[key].push(f);
      });

      groupOrder.forEach(function(key){
        var gFindings = groups[key];
        var checkDesc = (D.K && D.K[key]) ? D.K[key].d : "";
        var checkThresh = (D.K && D.K[key]) ? D.K[key].t : "";
        /* Group header row */
        var ghTr = document.createElement("tr");
        ghTr.className = "group-header";
        var ghTd = document.createElement("td");
        ghTd.colSpan = cols.length;
        var ghHtml = '<span class="gh-id">'+esc(key)+'</span>';
        if(checkDesc) ghHtml += '<span class="gh-desc">'+esc(checkDesc)+'</span>';
        ghHtml += '<span class="gh-count">'+gFindings.length+' finding'+(gFindings.length!==1?'s':'')+'</span>';
        if(checkThresh) ghHtml += '<span class="gh-thresh">'+esc(checkThresh)+'</span>';
        ghTd.innerHTML = ghHtml;
        ghTr.appendChild(ghTd);
        tbody.appendChild(ghTr);

        if(gFindings.length === 0){
          var emptyTr = document.createElement("tr");
          emptyTr.className = "group-empty";
          var emptyTd = document.createElement("td");
          emptyTd.colSpan = cols.length;
          emptyTd.textContent = "No findings — all checks passed";
          emptyTr.appendChild(emptyTd);
          tbody.appendChild(emptyTr);
        } else {
          gFindings.forEach(function(f){
            var tr = buildRow(f);
            if(!activeSevs[f.s]) tr.style.display = "none";
            else shownCount++;
            tbody.appendChild(tr);
          });
        }
      });
    } else {
      filtered.forEach(function(f){
        var tr = buildRow(f);
        if(!activeSevs[f.s]) tr.style.display = "none";
        else shownCount++;
        tbody.appendChild(tr);
      });
    }

    countEl.textContent = shownCount + " finding" + (shownCount !== 1 ? "s" : "");
  }

  /* ── Wire header sort clicks ── */
  thEls.forEach(function(th){
    th.addEventListener("click",function(){
      var col = th.getAttribute("data-col");
      if(sortCol === col){
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortCol = col;
        sortDir = "asc";
      }
      updateSortHeaders();
      renderTable();
    });
    th.addEventListener("keydown",function(e){
      if(e.key === "Enter" || e.key === " "){ e.preventDefault(); th.click(); }
    });
  });

  /* ── Wire search input ── */
  searchInput.addEventListener("input", renderTable);

  /* ── Wire group-by and show-all checkboxes ── */
  groupChk.addEventListener("change", function(){
    showAllLabel.style.display = groupChk.checked ? "" : "none";
    if(!groupChk.checked) showAllChk.checked = false;
    renderTable();
  });
  showAllChk.addEventListener("change", renderTable);

  /* ── Wire severity filter ── */
  function applyCrossmodelSevFilter(){
    $$("tr[data-severity]", tbody).forEach(function(tr){
      var sev = tr.getAttribute("data-severity");
      tr.style.display = activeSevs[sev] ? "" : "none";
    });
    /* Recount visible */
    var shown = $$("tr[data-severity]", tbody).filter(function(tr){ return tr.style.display !== "none"; }).length;
    countEl.textContent = shown + " finding" + (shown !== 1 ? "s" : "");
  }
  _crossmodelSevListener = applyCrossmodelSevFilter;
  document.addEventListener("sev-filter-changed", _crossmodelSevListener);

  /* ── Set initial sort indicator ── */
  updateSortHeaders();

  /* ── Pre-populate search box if angle filter applied (for UX clarity) ── */
  /* Not setting search text — angle filter is structural, not text-based */

  /* ── Initial render ── */
  renderTable();
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "crossmodel", routes: ["crossmodel"], pills: true,
  nav: {hash: "#crossmodel", icon: "≡", label: "Cross-Model"},
  show: function(route){
  var breadcrumbParts, breadcrumbLinks;
  /* Parse query params from hash (e.g. ?severity=HIGH or ?angle=D) */
  var cmFilters = {};
  if(route.query){
    route.query.split("&").forEach(function(part){
      var kv = part.split("=");
      if(kv.length === 2) cmFilters[kv[0]] = decodeURIComponent(kv[1]);
    });
  }
  /* Build descriptive breadcrumb */
  var cmCrumb = "Cross-Model";
  if(cmFilters.severity) cmCrumb = "Cross-Model — "+cmFilters.severity;
  else if(cmFilters.angle){
    var angleLabel = ANGLE_LABELS[ANGLE_SHORT[cmFilters.angle]||cmFilters.angle] || cmFilters.angle;
    cmCrumb = "Cross-Model — "+angleLabel;
  }
  breadcrumbParts = ["Dashboard", cmCrumb];
  breadcrumbLinks = ["#dashboard"];
  /* Always rebuild — filters change on each navigation */
  buildCrossModel(D, cmFilters);
  return {crumbs: breadcrumbParts, links: breadcrumbLinks};
}});
