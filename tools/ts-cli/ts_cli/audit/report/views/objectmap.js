/* ── Build Object Map ── */
var _objectmapSevListener = null;
function buildObjectMap(D, subTab){
  var c = document.getElementById("v-objectmap");
  c.innerHTML = "";

  if(_objectmapSevListener) document.removeEventListener("sev-filter-changed",_objectmapSevListener);

  /* Graceful fallback if no corpus */
  if(!D.C){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">⬡</div>'+
      '<div class="ph-text">Cross-model analysis unavailable</div>'+
      '<div class="ph-sub">Run with the latest ts-cli to enable cross-model analysis.</div></div>';
    return;
  }

  /* Sub-tab navigation */
  var tabs = el("div","object-map-tabs");
  var tabDefs = [
    {id:"overlaps",label:"Overlaps"},
    {id:"duplicates",label:"Duplicates"},
    {id:"table-reuse",label:"Table Reuse"},
    {id:"dependencies",label:"Dependencies"}
  ];
  tabDefs.forEach(function(td){
    var btn = el("button","",td.label);
    if(td.id === subTab) btn.classList.add("active");
    btn.setAttribute("data-subtab",td.id);
    btn.addEventListener("click",function(){
      navigate("#object-map/"+td.id);
    });
    tabs.appendChild(btn);
  });
  c.appendChild(tabs);

  /* Sub-tab content containers */
  tabDefs.forEach(function(td){
    var sec = el("div","om-subtab");
    sec.id = "om-"+td.id;
    if(td.id === subTab) sec.classList.add("active");
    c.appendChild(sec);
  });

  /* Build active sub-tab */
  switch(subTab){
    case "overlaps": buildOverlapsTab(D); break;
    case "duplicates": buildDuplicatesTab(D); break;
    case "table-reuse": buildTableReuseTab(D); break;
    case "dependencies": buildDependenciesTab(D); break;
    default: buildOverlapsTab(D); break;
  }
}

/* ── Overlaps sub-tab ── */
function buildOverlapsTab(D){
  var sec = document.getElementById("om-overlaps");
  if(!sec) return;
  var overlaps = (D.C && D.C.mo) ? D.C.mo : [];

  if(overlaps.length === 0){
    sec.innerHTML = '<div class="om-section"><div class="empty-state">No model overlaps detected.</div></div>';
    return;
  }

  var wrap = el("div","om-section");
  wrap.innerHTML = '<h3>Model Overlaps ('+overlaps.length+' pair'+(overlaps.length!==1?'s':'')+')</h3>';

  var tblWrap = el("div","","");
  tblWrap.style.overflowX = "auto";
  var tbl = el("table","overlap-table");

  /* Sort state */
  var sortCol = "j";
  var sortDir = "desc";

  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  var colDefs = [
    {key:"a",label:"Model A"},
    {key:"b",label:"Model B"},
    {key:"j",label:"Jaccard"},
    {key:"sc",label:"Shared"},
    {key:"t",label:"Classification"},
    {key:"x",label:"Compare"}
  ];
  var thEls = [];
  colDefs.forEach(function(cd){
    var th = el("th","",cd.label);
    th.setAttribute("data-col",cd.key);
    if(cd.key !== "x"){
      th.addEventListener("click",function(){
        if(sortCol===cd.key){ sortDir=sortDir==="asc"?"desc":"asc"; }
        else { sortCol=cd.key; sortDir=cd.key==="j"?"desc":"asc"; }
        renderOverlaps();
      });
    }
    thEls.push(th);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  tbl.appendChild(thead);

  var tbody = document.createElement("tbody");
  tbl.appendChild(tbody);
  tblWrap.appendChild(tbl);
  wrap.appendChild(tblWrap);
  sec.appendChild(wrap);

  function renderOverlaps(){
    var sorted = overlaps.slice().sort(function(a,b){
      var av,bv,cmp=0;
      if(sortCol==="j"){ cmp=a.j-b.j; }
      else if(sortCol==="sc"){ cmp=a.sc-b.sc; }
      else if(sortCol==="a"){ av=a.a.n.toLowerCase();bv=b.a.n.toLowerCase(); cmp=av<bv?-1:(av>bv?1:0); }
      else if(sortCol==="b"){ av=a.b.n.toLowerCase();bv=b.b.n.toLowerCase(); cmp=av<bv?-1:(av>bv?1:0); }
      else if(sortCol==="t"){ av=a.t;bv=b.t; cmp=av<bv?-1:(av>bv?1:0); }
      return sortDir==="asc"?cmp:-cmp;
    });

    /* Update header indicators */
    thEls.forEach(function(th){
      th.classList.remove("sort-asc","sort-desc");
      if(th.getAttribute("data-col")===sortCol){
        th.classList.add(sortDir==="asc"?"sort-asc":"sort-desc");
      }
    });

    tbody.innerHTML = "";
    sorted.forEach(function(o){
      var tr = document.createElement("tr");

      /* Model A */
      var tdA = el("td","");
      tdA.innerHTML = '<a href="#model/'+o.a.g+'">'+esc(o.a.n)+'</a>';
      tr.appendChild(tdA);

      /* Model B */
      var tdB = el("td","");
      tdB.innerHTML = '<a href="#model/'+o.b.g+'">'+esc(o.b.n)+'</a>';
      tr.appendChild(tdB);

      /* Jaccard */
      var tdJ = el("td","");
      tdJ.textContent = Math.round(o.j*100)+"%";
      tdJ.style.fontWeight = "600";
      tdJ.style.fontVariantNumeric = "tabular-nums";
      tr.appendChild(tdJ);

      /* Shared count */
      var tdSC = el("td","");
      tdSC.textContent = o.sc + " / " + o.ta + ", " + o.tb;
      tr.appendChild(tdSC);

      /* Classification badge */
      var tdT = el("td","");
      var badgeLabel = o.t.replace(/_/g," ");
      tdT.innerHTML = '<span class="overlap-badge '+o.t+'">'+badgeLabel+'</span>';
      tr.appendChild(tdT);

      /* Compare details */
      var tdX = el("td","");
      if(o.st && o.st.length > 0){
        var det = document.createElement("details");
        det.className = "overlap-compare";
        var sum = document.createElement("summary");
        sum.textContent = "Show "+o.st.length+" table"+(o.st.length!==1?"s":"");
        det.appendChild(sum);
        var ul = document.createElement("ul");
        o.st.forEach(function(tn){
          var li = document.createElement("li");
          li.textContent = tn;
          ul.appendChild(li);
        });
        det.appendChild(ul);
        tdX.appendChild(det);
      }
      tr.appendChild(tdX);

      tbody.appendChild(tr);
    });
  }

  renderOverlaps();
}

/* ── Duplicates sub-tab ── */
function buildDuplicatesTab(D){
  var sec = document.getElementById("om-duplicates");
  if(!sec) return;

  /* The rules that feed this view (catalog `views: [duplicates]`) */
  var d8 = (D.F||[]).filter(function(f){ return inView("duplicates", f); });

  if(d8.length === 0){
    sec.innerHTML = '<div class="om-section"><div class="empty-state">No duplicate table objects found.</div></div>';
    return;
  }

  /* Group by detail (FQN) */
  var groups = {};
  var groupOrder = [];
  d8.forEach(function(f){
    var key = f.d || "(unknown)";
    if(!groups[key]){ groups[key]=[]; groupOrder.push(key); }
    groups[key].push(f);
  });

  var wrap = el("div","om-section");
  wrap.innerHTML = '<h3>Duplicate Table Objects ('+d8.length+' finding'+(d8.length!==1?'s':'')+')</h3>';

  groupOrder.forEach(function(key){
    var items = groups[key];
    var grp = el("div","","");
    grp.style.cssText = "margin-bottom:12px;padding:10px 12px;background:var(--surface-2);border:1px solid var(--hair-2);border-radius:6px;";
    var hdr = el("div","","");
    hdr.style.cssText = "font-size:12px;font-weight:600;margin-bottom:6px;";
    hdr.textContent = key;
    grp.appendChild(hdr);

    items.forEach(function(f){
      var row = el("div","","");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px;";
      row.setAttribute("data-severity",f.s);
      var model = D.L[f.mi];
      var html = severityPill(f.s);
      if(model){
        html += ' <a href="#model/'+model.g+'">'+esc(model.n)+'</a>';
      }
      row.innerHTML = html;
      grp.appendChild(row);
    });

    wrap.appendChild(grp);
  });

  sec.appendChild(wrap);
}

/* ── Table Reuse sub-tab ── */
function buildTableReuseTab(D){
  var sec = document.getElementById("om-table-reuse");
  if(!sec) return;
  var reuse = (D.C && D.C.tr) ? D.C.tr : [];

  if(reuse.length === 0){
    sec.innerHTML = '<div class="om-section"><div class="empty-state">No tables shared across models.</div></div>';
    return;
  }

  /* Inner sub-tabs */
  var innerTabs = el("div","inner-tabs");
  var innerDefs = [{id:"sankey",label:"Connections"},{id:"detail",label:"Shared Tables ("+reuse.length+")"}];
  innerDefs.forEach(function(td,i){
    var btn = el("button","",td.label);
    if(i===0) btn.classList.add("active");
    btn.addEventListener("click",function(){
      innerTabs.querySelectorAll("button").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      sec.querySelectorAll(".inner-pane").forEach(function(p){p.classList.remove("active");});
      document.getElementById("tr-"+td.id).classList.add("active");
    });
    innerTabs.appendChild(btn);
  });
  sec.appendChild(innerTabs);

  /* Sankey diagram */
  var sankeyPane = el("div","inner-pane active");
  sankeyPane.id = "tr-sankey";
  var sankeyWrap = el("div","om-section");
  sankeyWrap.innerHTML = '<h3>Table-to-Model Connections</h3>';
  var sankeyContainer = el("div","sankey-container");
  buildSankeySVG(sankeyContainer, reuse);
  sankeyWrap.appendChild(sankeyContainer);
  sankeyPane.appendChild(sankeyWrap);
  sec.appendChild(sankeyPane);

  /* Detail table */
  var detailPane = el("div","inner-pane");
  detailPane.id = "tr-detail";
  var tableWrap = el("div","om-section");
  tableWrap.innerHTML = '<h3>Shared Tables ('+reuse.length+')</h3>';

  var sortCol = "mc";
  var sortDir = "desc";

  var tblContainer = el("div","","");
  tblContainer.style.overflowX = "auto";
  var tbl = el("table","reuse-table");

  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  var colDefs = [
    {key:"f",label:"FQN"},
    {key:"n",label:"Table Name"},
    {key:"mc",label:"Model Count"},
    {key:"ms",label:"Models"}
  ];
  var thEls = [];
  colDefs.forEach(function(cd){
    var th = el("th","",cd.label);
    th.setAttribute("data-col",cd.key);
    if(cd.key !== "ms"){
      th.addEventListener("click",function(){
        if(sortCol===cd.key){ sortDir=sortDir==="asc"?"desc":"asc"; }
        else { sortCol=cd.key; sortDir=cd.key==="mc"?"desc":"asc"; }
        renderReuseTable();
      });
    }
    thEls.push(th);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  tbl.appendChild(thead);

  var tbody = document.createElement("tbody");
  tbl.appendChild(tbody);
  tblContainer.appendChild(tbl);
  tableWrap.appendChild(tblContainer);
  detailPane.appendChild(tableWrap);
  sec.appendChild(detailPane);

  function renderReuseTable(){
    var sorted = reuse.slice().sort(function(a,b){
      var av,bv,cmp=0;
      if(sortCol==="mc"){ cmp=a.ms.length-b.ms.length; }
      else if(sortCol==="f"){ av=a.f.toLowerCase();bv=b.f.toLowerCase(); cmp=av<bv?-1:(av>bv?1:0); }
      else if(sortCol==="n"){ av=a.n.toLowerCase();bv=b.n.toLowerCase(); cmp=av<bv?-1:(av>bv?1:0); }
      return sortDir==="asc"?cmp:-cmp;
    });

    thEls.forEach(function(th){
      th.classList.remove("sort-asc","sort-desc");
      if(th.getAttribute("data-col")===sortCol){
        th.classList.add(sortDir==="asc"?"sort-asc":"sort-desc");
      }
    });

    tbody.innerHTML = "";
    sorted.forEach(function(r){
      var tr = document.createElement("tr");

      var tdF = el("td","");
      tdF.textContent = r.f;
      tdF.style.fontFamily = "var(--mono)";
      tdF.style.fontSize = "11px";
      tr.appendChild(tdF);

      var tdN = el("td","");
      tdN.textContent = r.n;
      tr.appendChild(tdN);

      var tdMC = el("td","");
      tdMC.textContent = r.ms.length;
      tdMC.style.fontWeight = "600";
      tr.appendChild(tdMC);

      var tdMS = el("td","");
      var links = r.ms.map(function(m){
        return '<a href="#model/'+m.g+'">'+esc(m.n)+'</a>';
      });
      tdMS.innerHTML = links.join(", ");
      tr.appendChild(tdMS);

      tbody.appendChild(tr);
    });
  }

  renderReuseTable();
}

/* ── Sankey SVG builder ── */
function buildSankeySVG(container, reuse){
  var NS = "http://www.w3.org/2000/svg";

  /* Collect unique tables and models */
  var tables = [];
  var tableSet = {};
  var models = [];
  var modelSet = {};

  reuse.forEach(function(r){
    if(!tableSet[r.f]){ tableSet[r.f]=tables.length; tables.push({f:r.f,n:r.n}); }
    r.ms.forEach(function(m){
      if(!modelSet[m.g]){ modelSet[m.g]=models.length; models.push({n:m.n,g:m.g}); }
    });
  });

  var leftCount = tables.length;
  var rightCount = models.length;
  var nodeH = 20;
  var nodeGap = 6;
  var labelW = 150;
  var chartW = 700;
  var midW = chartW - labelW*2;
  var totalH = Math.max(leftCount, rightCount) * (nodeH + nodeGap) + 20;

  var svg = document.createElementNS(NS,"svg");
  svg.setAttribute("viewBox","0 0 "+chartW+" "+totalH);
  svg.setAttribute("width","100%");
  svg.style.maxWidth = chartW+"px";
  svg.style.minHeight = Math.min(totalH, 600)+"px";

  /* Left nodes (tables) */
  var leftYStart = 10;
  var leftPositions = [];
  tables.forEach(function(t,i){
    var y = leftYStart + i * (nodeH + nodeGap);
    leftPositions.push(y + nodeH/2);

    var rect = document.createElementNS(NS,"rect");
    rect.setAttribute("x","0");
    rect.setAttribute("y",y);
    rect.setAttribute("width",labelW - 10);
    rect.setAttribute("height",nodeH);
    rect.setAttribute("rx","3");
    rect.setAttribute("fill","var(--accent-soft)");
    rect.setAttribute("stroke","var(--accent)");
    rect.setAttribute("stroke-width","1");
    svg.appendChild(rect);

    var text = document.createElementNS(NS,"text");
    text.setAttribute("x","6");
    text.setAttribute("y",y + nodeH/2 + 4);
    text.setAttribute("font-size","10");
    text.setAttribute("fill","var(--ink)");
    text.setAttribute("font-family","var(--sans)");
    text.textContent = t.n.length > 18 ? t.n.substring(0,16)+"..." : t.n;
    svg.appendChild(text);
  });

  /* Right nodes (models) */
  var rightYStart = 10;
  var rightPositions = [];
  models.forEach(function(m,i){
    var y = rightYStart + i * (nodeH + nodeGap);
    rightPositions.push(y + nodeH/2);

    var rect = document.createElementNS(NS,"rect");
    rect.setAttribute("x",chartW - labelW + 10);
    rect.setAttribute("y",y);
    rect.setAttribute("width",labelW - 10);
    rect.setAttribute("height",nodeH);
    rect.setAttribute("rx","3");
    rect.setAttribute("fill","var(--ok-soft)");
    rect.setAttribute("stroke","var(--ok)");
    rect.setAttribute("stroke-width","1");
    svg.appendChild(rect);

    var text = document.createElementNS(NS,"text");
    text.setAttribute("x",chartW - labelW + 16);
    text.setAttribute("y",y + nodeH/2 + 4);
    text.setAttribute("font-size","10");
    text.setAttribute("fill","var(--ink)");
    text.setAttribute("font-family","var(--sans)");
    text.textContent = m.n.length > 18 ? m.n.substring(0,16)+"..." : m.n;
    svg.appendChild(text);
  });

  /* Draw connections */
  var allPaths = [];
  var pathsByTable = {};
  var pathsByModel = {};
  reuse.forEach(function(r){
    var ti = tableSet[r.f];
    var leftY = leftPositions[ti];
    var x1 = labelW - 10;
    var x2 = chartW - labelW + 10;
    var cx1 = x1 + midW * 0.4;
    var cx2 = x2 - midW * 0.4;

    r.ms.forEach(function(m){
      var mi = modelSet[m.g];
      var rightY = rightPositions[mi];
      var path = document.createElementNS(NS,"path");
      path.setAttribute("d","M "+x1+" "+leftY+" C "+cx1+" "+leftY+" "+cx2+" "+rightY+" "+x2+" "+rightY);
      path.setAttribute("fill","none");
      path.setAttribute("stroke","var(--accent)");
      path.setAttribute("stroke-width","2");
      path.setAttribute("stroke-opacity","0.25");
      path.style.transition = "stroke-opacity 0.2s";
      svg.appendChild(path);
      allPaths.push(path);
      (pathsByTable[r.f]=pathsByTable[r.f]||[]).push(path);
      (pathsByModel[m.g]=pathsByModel[m.g]||[]).push(path);
    });
  });

  /* Click-to-highlight: click a node to highlight its connections */
  var highlighted = null;
  function highlightPaths(key, byMap){
    if(highlighted===key){highlighted=null;allPaths.forEach(function(p){p.setAttribute("stroke-opacity","0.25");p.setAttribute("stroke-width","2");});return;}
    highlighted=key;
    allPaths.forEach(function(p){p.setAttribute("stroke-opacity","0.06");p.setAttribute("stroke-width","1.5");});
    (byMap[key]||[]).forEach(function(p){p.setAttribute("stroke-opacity","0.85");p.setAttribute("stroke-width","3");});
  }
  svg.querySelectorAll("rect").forEach(function(rect,i){
    rect.style.cursor="pointer";
    if(i<leftCount){
      rect.addEventListener("click",function(){highlightPaths(tables[i].f,pathsByTable);});
    } else {
      var mi=i-leftCount;
      rect.addEventListener("click",function(){highlightPaths(models[mi].g,pathsByModel);});
    }
  });

  container.appendChild(svg);
}

/* ── Dependencies sub-tab ── */
function buildDependenciesTab(D){
  var sec = document.getElementById("om-dependencies");
  if(!sec) return;

  var corpusModels = (D.C && D.C.m) ? D.C.m : [];
  var reuse = (D.C && D.C.tr) ? D.C.tr : [];

  if(corpusModels.length === 0 && reuse.length === 0){
    sec.innerHTML = '<div class="om-section"><div class="empty-state">No dependency data available.</div></div>';
    return;
  }

  /* Inner sub-tabs */
  var sharedTables = reuse.filter(function(r){ return r.ms.length > 1; });
  var dInnerTabs = el("div","inner-tabs");
  var dInnerDefs = [{id:"tpm",label:"Tables per Model"},{id:"mpt",label:"Models per Table ("+sharedTables.length+")"}];
  dInnerDefs.forEach(function(td,i){
    var btn = el("button","",td.label);
    if(i===0) btn.classList.add("active");
    btn.addEventListener("click",function(){
      dInnerTabs.querySelectorAll("button").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      sec.querySelectorAll(".inner-pane").forEach(function(p){p.classList.remove("active");});
      document.getElementById("dep-"+td.id).classList.add("active");
    });
    dInnerTabs.appendChild(btn);
  });
  sec.appendChild(dInnerTabs);

  /* ── Tables-per-model bar chart ── */
  var tpmPane = el("div","inner-pane active");
  tpmPane.id = "dep-tpm";
  if(corpusModels.length > 0){
    var tpmWrap = el("div","om-section");
    tpmWrap.innerHTML = '<h3>Tables per Model</h3>';
    var tpmChart = el("div","bar-chart");
    buildBarChart(tpmChart, corpusModels.map(function(cm){
      var model = D.L[cm.mi];
      return {label: model ? model.n : "Model "+cm.mi, value: cm.tc, guid: model ? model.g : null};
    }), "var(--accent)");
    tpmWrap.appendChild(tpmChart);

    /* Detail table */
    var tpmTableContainer = el("div","","");
    tpmTableContainer.style.overflowX = "auto";
    var tpmTable = buildSortableDepTable(
      corpusModels.map(function(cm){
        var model = D.L[cm.mi];
        return {
          name: model ? model.n : "Model "+cm.mi,
          guid: model ? model.g : "",
          count: cm.tc,
          extra: cm.cc+" cols, "+cm.fc+" formulas, "+cm.jc+" joins"
        };
      }),
      [{key:"name",label:"Model"},{key:"count",label:"Tables"},{key:"extra",label:"Details"}],
      "count"
    );
    tpmTableContainer.appendChild(tpmTable);
    tpmWrap.appendChild(tpmTableContainer);
    tpmPane.appendChild(tpmWrap);
  }
  sec.appendChild(tpmPane);

  /* ── Models-per-table bar chart ── */
  var mptPane = el("div","inner-pane");
  mptPane.id = "dep-mpt";
  if(sharedTables.length > 0){
    var mptWrap = el("div","om-section");
    mptWrap.innerHTML = '<h3>Models per Table (shared tables only)</h3>';
    var mptChart = el("div","bar-chart");
    buildBarChart(mptChart, sharedTables.map(function(r){
      return {label: r.n, value: r.ms.length, guid: null};
    }), "#8b5cf6"); /* purple */
    mptWrap.appendChild(mptChart);

    /* Detail table */
    var mptTableContainer = el("div","","");
    mptTableContainer.style.overflowX = "auto";
    var mptTable = buildSortableDepTable(
      sharedTables.map(function(r){
        return {
          name: r.n,
          guid: "",
          count: r.ms.length,
          extra: r.ms.map(function(m){ return m.n; }).join(", ")
        };
      }),
      [{key:"name",label:"Table"},{key:"count",label:"Models"},{key:"extra",label:"Used By"}],
      "count"
    );
    mptTableContainer.appendChild(mptTable);
    mptWrap.appendChild(mptTableContainer);
    mptPane.appendChild(mptWrap);
  }
  sec.appendChild(mptPane);
}

/* ── Bar chart SVG builder ── */
function buildBarChart(container, items, fillColor){
  var NS = "http://www.w3.org/2000/svg";

  /* Sort by value descending */
  items = items.slice().sort(function(a,b){ return b.value - a.value; });

  var MAX_BARS = 20;
  var totalItems = items.length;
  var visible = items.slice(0, MAX_BARS);

  var barH = 22;
  var barGap = 4;
  var labelW = 160;
  var valueW = 40;
  var chartW = 600;
  var barAreaW = chartW - labelW - valueW;
  var maxVal = Math.max.apply(null, items.map(function(d){ return d.value; })) || 1;

  function renderBars(show){
    container.innerHTML = "";
    var totalH = show.length * (barH + barGap) + 10;
    var svg = document.createElementNS(NS,"svg");
    svg.setAttribute("viewBox","0 0 "+chartW+" "+totalH);
    svg.setAttribute("width","100%");
    svg.style.maxWidth = chartW+"px";
    svg.style.minHeight = Math.min(totalH, 600)+"px";

    show.forEach(function(item,i){
      var y = 5 + i * (barH + barGap);
      var barW = Math.max(2, (item.value / maxVal) * barAreaW);

      var text = document.createElementNS(NS,"text");
      text.setAttribute("x",labelW - 8);
      text.setAttribute("y",y + barH/2 + 4);
      text.setAttribute("font-size","11");
      text.setAttribute("fill","var(--ink)");
      text.setAttribute("font-family","var(--sans)");
      text.setAttribute("text-anchor","end");
      text.textContent = item.label.length > 22 ? item.label.substring(0,20)+"..." : item.label;
      svg.appendChild(text);

      var rect = document.createElementNS(NS,"rect");
      rect.setAttribute("x",labelW);
      rect.setAttribute("y",y);
      rect.setAttribute("width",barW);
      rect.setAttribute("height",barH);
      rect.setAttribute("rx","3");
      rect.setAttribute("fill",fillColor);
      rect.setAttribute("fill-opacity","0.75");
      svg.appendChild(rect);

      var val = document.createElementNS(NS,"text");
      val.setAttribute("x",labelW + barW + 6);
      val.setAttribute("y",y + barH/2 + 4);
      val.setAttribute("font-size","11");
      val.setAttribute("fill","var(--muted)");
      val.setAttribute("font-family","var(--mono)");
      val.setAttribute("font-weight","600");
      val.textContent = item.value;
      svg.appendChild(val);
    });
    container.appendChild(svg);

    if(totalItems > MAX_BARS && show.length <= MAX_BARS){
      var btn = el("button","show-all-btn","Show all "+totalItems+" items");
      btn.style.cssText = "margin:8px 0;padding:6px 16px;border:1px solid var(--hair);border-radius:6px;background:var(--bg-card);cursor:pointer;font-size:12px;color:var(--accent);";
      btn.addEventListener("click",function(){ renderBars(items); });
      container.appendChild(btn);
    }
  }

  renderBars(visible);
}

/* ── Sortable dependency detail table ── */
function buildSortableDepTable(rows, colDefs, defaultSort){
  var sortCol = defaultSort || colDefs[0].key;
  var sortDir = "desc";

  var tbl = el("table","dep-detail-table");
  var thead = document.createElement("thead");
  var hrow = document.createElement("tr");
  var thEls = [];
  colDefs.forEach(function(cd){
    var th = el("th","",cd.label);
    th.setAttribute("data-col",cd.key);
    th.addEventListener("click",function(){
      if(sortCol===cd.key){ sortDir=sortDir==="asc"?"desc":"asc"; }
      else { sortCol=cd.key; sortDir=cd.key==="count"?"desc":"asc"; }
      render();
    });
    thEls.push(th);
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  tbl.appendChild(thead);

  var tbody = document.createElement("tbody");
  tbl.appendChild(tbody);

  function render(){
    var sorted = rows.slice().sort(function(a,b){
      var av = a[sortCol], bv = b[sortCol];
      var cmp;
      if(typeof av === "number" && typeof bv === "number"){ cmp = av - bv; }
      else { av=(av||"").toString().toLowerCase(); bv=(bv||"").toString().toLowerCase(); cmp=av<bv?-1:(av>bv?1:0); }
      return sortDir==="asc"?cmp:-cmp;
    });

    thEls.forEach(function(th){
      th.classList.remove("sort-asc","sort-desc");
      if(th.getAttribute("data-col")===sortCol){
        th.classList.add(sortDir==="asc"?"sort-asc":"sort-desc");
      }
    });

    tbody.innerHTML = "";
    sorted.forEach(function(r){
      var tr = document.createElement("tr");
      colDefs.forEach(function(cd){
        var td = el("td","");
        if(cd.key === "name" && r.guid){
          td.innerHTML = '<a href="#model/'+r.guid+'">'+esc(r[cd.key])+'</a>';
        } else {
          td.textContent = r[cd.key];
          if(cd.key === "count"){ td.style.fontWeight = "600"; }
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  render();
  return tbl;
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "objectmap", routes: ["object-map", "objectmap"],
  nav: {hash: "#objectmap", icon: "⬡", label: "Object Map"},
  show: function(route){
  var breadcrumbParts, breadcrumbLinks;
  var omSub = route.id || "overlaps";
  breadcrumbParts = ["Object Map", omSub.charAt(0).toUpperCase()+omSub.slice(1)];
  breadcrumbLinks = ["#objectmap"];
  buildObjectMap(D, omSub);
  return {crumbs: breadcrumbParts, links: breadcrumbLinks};
}});
