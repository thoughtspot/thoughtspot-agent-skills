var _sevFilterListener = null;

/* ── Build scorecard ── */
function buildScorecard(D, guid, filterAngle){
  var c = document.getElementById("v-scorecard");
  c.innerHTML = "";

  /* Remove old listener before rebuilding */
  if(_sevFilterListener) document.removeEventListener("sev-filter-changed", _sevFilterListener);

  /* Model metadata */
  var modelName = findModelName(guid);
  var cm = findCorpusModel(guid);

  /* ── Header ── */
  var hdr = el("div","scorecard-header");
  var titleHtml = '<div class="model-title">'+esc(modelName)+'</div>';
  titleHtml += '<div class="model-guid">'+esc(guid)+'</div>';

  /* Stats from corpus */
  if(cm){
    titleHtml += '<div class="model-stats">';
    var statItems = [
      {v:cm.tc,l:"Tables"},
      {v:cm.cc,l:"Columns"},
      {v:cm.fc,l:"Formulas"},
      {v:cm.jc,l:"Joins"},
      {v:cm.jd,l:"Join Depth"}
    ];
    statItems.forEach(function(s){
      titleHtml += '<div class="stat-item"><div class="stat-val">'+s.v+'</div><div class="stat-lbl">'+s.l+'</div></div>';
    });
    if(cm.rs){
      titleHtml += '<div class="stat-item" title="'+esc(READINESS_TITLE)+'"><div class="stat-val readiness" data-level="'+esc(cm.rs.l)+'">'+
                   Math.floor(cm.rs.s)+'/100</div><div class="stat-lbl">Spotter readiness</div></div>';
    }
    titleHtml += '</div>';
  }

  /* Model description */
  if(cm && cm.ds){
    titleHtml += '<div class="model-desc">'+esc(cm.ds)+'</div>';
  }

  /* Actions */
  titleHtml += '<div class="header-actions">';
  if(D.C && D.C.u){
    titleHtml += '<a class="ts-link-btn" href="'+D.C.u+'/#/data/tables/'+guid+'" target="_blank" rel="noopener">Open in ThoughtSpot ↗</a>';
  }
  titleHtml += '<button class="erd-btn" id="erd-toggle-'+guid+'" data-erd-ready="false">ERD Diagram</button>';
  if(cm && cm.ft) titleHtml += '<a class="ts-link-btn" href="#formulas/'+esc(guid)+'">Formula tree</a>';
  titleHtml += '</div>';

  hdr.innerHTML = titleHtml;
  c.appendChild(hdr);

  /* ── AI Analysis panel ── */
  if(cm && cm.ai){
    var aiPanel = document.createElement("details");
    aiPanel.className = "ai-panel";
    aiPanel.open = true;

    var aiSummary = document.createElement("summary");
    aiSummary.textContent = "Model Analysis";
    aiPanel.appendChild(aiSummary);

    var aiBody = el("div","ai-panel-body");

    if(cm.ai.do){
      var doSec = el("div","ai-sub");
      doSec.innerHTML = '<h4>Model Domain</h4>';
      var doP = document.createElement("p");
      doP.textContent = cm.ai.do;
      doSec.appendChild(doP);
      aiBody.appendChild(doSec);
    }

    if(cm.ai.ob && cm.ai.ob.length > 0){
      var obSec = el("div","ai-sub");
      obSec.innerHTML = '<h4>Key Objectives</h4>';
      var obUl = document.createElement("ul");
      cm.ai.ob.forEach(function(o){
        var li = document.createElement("li");
        li.textContent = o;
        obUl.appendChild(li);
      });
      obSec.appendChild(obUl);
      aiBody.appendChild(obSec);
    }

    if(cm.ai.pe && cm.ai.pe.length > 0){
      var perSec = el("div","ai-sub");
      perSec.innerHTML = '<h4>Audience</h4>';
      var perUl = document.createElement("ul");
      cm.ai.pe.forEach(function(p){
        var li = document.createElement("li");
        li.textContent = p;
        perUl.appendChild(li);
      });
      perSec.appendChild(perUl);
      aiBody.appendChild(perSec);
    }

    if(recorded() && !(cm.ai.qu && cm.ai.qu.length > 0)){
      var qNone = el("div","ai-sub");
      qNone.innerHTML = '<h4>Business Questions</h4>';
      qNone.appendChild(mutedNote(!collected("ai_instructions") ? NOT_COLLECTED
        : cm.ai.rd === false ? "Could not be read — the AI-instructions lookup for this Model failed; `ts audit run` printed the reason as a warning when it ran."
        : "None — no AI instructions on this Model.", "questions-status"));
      aiBody.appendChild(qNone);
    }
    if(cm.ai.qu && cm.ai.qu.length > 0){
      var qSec = el("div","ai-sub");
      qSec.innerHTML = '<h4>Business Questions</h4>';
      var qUl = document.createElement("ul");
      cm.ai.qu.forEach(function(q){
        var li = document.createElement("li");
        li.textContent = q;
        qUl.appendChild(li);
      });
      qSec.appendChild(qUl);
      aiBody.appendChild(qSec);
    }

    aiPanel.appendChild(aiBody);
    c.appendChild(aiPanel);
  }

  /* ── Angle sections ── */
  var angles = (D.C && D.C.ar && D.C.ar.length > 0) ? D.C.ar : CATEGORY_IDS;

  /* Group findings by angle code — match by GUID, not by lookup index,
     because child-object findings (columns, joins, tables, formulas) share
     the model's GUID but have distinct lookup indices. */
  var findingsByAngle = {};
  if(D.F){
    D.F.forEach(function(f){
      var m = D.L[f.mi];
      if(!m || m.g !== guid) return;
      /* Under every category it belongs to (sections may then sum to more than the total). */
      findingCats(f).forEach(function(code){
        if(!findingsByAngle[code]) findingsByAngle[code] = [];
        findingsByAngle[code].push(f);
      });
    });
  }

  angles.forEach(function(angleCode){
    var angleFindings = findingsByAngle[angleCode] || [];
    var ws = worstSev(angleFindings);
    var isExpandDefault = (ws === "CRITICAL" || ws === "HIGH");
    var isFilterMatch = !filterAngle || filterAngle === angleCode;

    var section = document.createElement("details");
    section.className = "angle-section sev-"+(ws||"NONE");
    if((isExpandDefault && isFilterMatch) || (filterAngle === angleCode)){
      section.open = true;
    }

    /* Summary */
    var fullName = ANGLE_FULL_NAMES[angleCode] || angleCode;
    var summaryEl = document.createElement("summary");
    summaryEl.innerHTML = '<span class="angle-name">'+fullName+'</span>'+
      (ws && ws !== "NONE" ? severityPill(ws) : '')+
      '<span class="angle-count">'+angleFindings.length+' finding'+(angleFindings.length!==1?'s':'')+'</span>';
    section.appendChild(summaryEl);

    /* Body */
    var body = el("div","findings-body");

    if(angleFindings.length === 0){
      var noFind = el("div","","");
      noFind.style.cssText = "font-size:12px;color:var(--muted);padding:4px 0;";
      noFind.textContent = "No findings for this angle.";
      body.appendChild(noFind);
    } else {
      angleFindings.forEach(function(f){
        var card = el("div","finding-card");
        card.setAttribute("data-severity",f.s);
        if(!activeSevs[f.s]) card.classList.add("hidden-by-filter");

        /* Card top: check badge + sev pill + child-object label */
        var topHtml = '<div class="card-top">';
        topHtml += '<span class="check-badge">'+f.ci+'</span>';
        topHtml += severityPill(f.s);
        var fLookup = D.L[f.mi];
        if(f.ot && f.ot !== "model" && fLookup && fLookup.n){
          topHtml += '<span class="child-obj-label" title="'+esc(f.ot)+': '+esc(fLookup.n)+'">'+esc(f.ot)+': '+esc(fLookup.n)+'</span>';
        }
        topHtml += '</div>';

        /* Detail text */
        topHtml += '<div class="detail-text">'+esc(f.d)+'</div>';

        /* Metric bar — computed in report.py metric_bar() from the finding's bands
           (direction-aware), or the legacy pass mark for pre-catalog JSON */
        if(f.mb){
          var mbVal = Math.round(f.mb.v * 10) / 10;
          var mbLabel = f.mb.dir === "lower_is_better" ? "limit: " : "target: ";
          topHtml += '<div class="metric-bar-wrap">';
          topHtml += '<div class="metric-bar-label">';
          topHtml += '<span>'+mbVal+esc(f.mb.unit)+'</span>';
          topHtml += '<span>'+mbLabel+f.mb.mark+esc(f.mb.unit)+'</span>';
          topHtml += '</div>';
          topHtml += '<div class="metric-bar"><div class="metric-bar-fill'+(f.mb.ok?' ok':'')+'" style="width:'+f.mb.w+'%"></div></div>';
          topHtml += '</div>';
        }

        /* Recommendation */
        var rec = esc(recommendation(f.ci));
        if(rec){
          topHtml += '<div class="finding-recommendation">'+rec+'</div>';
        }

        card.innerHTML = topHtml;
        body.appendChild(card);
      });
    }

    section.appendChild(body);
    c.appendChild(section);
  });



  /* ── Dependents panel ── */
  var depsPanel = document.createElement("details");
  depsPanel.className = "dependents-panel";
  depsPanel.open = true;

  var deps = (D.C && D.C.dp && D.C.dp[guid]) ? D.C.dp[guid] : [];
  var depSummary = document.createElement("summary");
  depSummary.innerHTML = 'Downstream Consumers <span style="margin-left:auto;font-size:11px;color:var(--muted);font-weight:500;">'+deps.length+' object'+(deps.length!==1?'s':'')+'</span>';
  depsPanel.appendChild(depSummary);

  var depBody = el("div","dependents-body");
  if(!collected("sets")){
    depBody.appendChild(mutedNote("Sets: " + NOT_COLLECTED, "sets-status"));
  }
  if(deps.length === 0){
    var noDeps = el("div","","No downstream consumers found.");
    noDeps.style.cssText = "font-size:12px;color:var(--muted);padding:4px 0;";
    depBody.appendChild(noDeps);
  } else {
    deps.forEach(function(dep){
      var item = el("div","dependent-item");
      var typeHtml = '<span class="dep-type-badge '+esc(dep.t)+'">'+esc(dep.t)+'</span>';
      var nameHtml = '<span class="dep-name" title="'+esc(dep.n)+'">'+esc(dep.n)+'</span>';
      var guidHtml = '<span class="dep-guid">'+esc(dep.g)+'</span>';
      var linkHtml = (D.C && D.C.u) ? tsLink(D.C.u, dep.g, dep.t) : "";
      item.innerHTML = typeHtml + nameHtml + guidHtml + linkHtml;
      depBody.appendChild(item);
    });
  }
  depsPanel.appendChild(depBody);
  c.appendChild(depsPanel);

  /* ── Wire up ERD button ── */
  var erdBtn = document.getElementById("erd-toggle-"+guid);
  if(erdBtn){
    erdBtn.addEventListener("click",function(){
      if(!cm || !cm.ed || !D.E){
        var erd = document.getElementById("erd-"+guid);
        if(erd){
          erd.innerHTML = '<div style="font-size:20px;">⬡</div>'+
            '<div class="erd-msg">ERD data not available</div>'+
            '<div class="erd-sub">Use /ts-object-model-erd for standalone ERD rendering.</div>';
          erd.scrollIntoView({behavior:"smooth",block:"nearest"});
        }
        return;
      }
      var erdData = cm.ed;
      if(cm.ai){erdData.model.ai_analysis={domain:cm.ai.do||"",objectives:cm.ai.ob||[],personas:cm.ai.pe||[],questions:cm.ai.qu||[]};}
      var bundle = {models:[erdData],index:[{
        name:erdData.model.name,guid:erdData.model.guid,
        tables:erdData.tables.length,joins:erdData.joins.length,
        findings:(erdData.findings||[]).length,
        rls:erdData.tables.reduce(function(s,t){return s+(t.rls||[]).length;},0)
      }],dropped:[]};
      var erdHtml = '<!doctype html><html lang="en"><head><meta charset="utf-8">'+
        '<meta name="viewport" content="width=device-width, initial-scale=1">'+
        '<title>ERD: '+esc(erdData.model.name)+'</title>'+
        '<style>'+D.E.css+'</style></head><body>'+D.E.body+
        '<script>window.__ERD_DATA__ = '+JSON.stringify(bundle)+';<\/script>'+
        '<script>'+D.E.js+'<\/script></body></html>';
      var blob = new Blob([erdHtml],{type:'text/html'});
      var url = URL.createObjectURL(blob);
      window.open(url,'_blank');
    });
  }

  /* ── Listen for severity filter changes ── */
  function applySevFilter(){
    $$(".finding-card",c).forEach(function(card){
      var sev = card.getAttribute("data-severity");
      if(activeSevs[sev]){
        card.classList.remove("hidden-by-filter");
      } else {
        card.classList.add("hidden-by-filter");
      }
    });
  }
  _sevFilterListener = applySevFilter;
  document.addEventListener("sev-filter-changed", _sevFilterListener);
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "scorecard", routes: ["model"], pills: true, show: function(route){
  var breadcrumbParts, breadcrumbLinks;
  var modelName = route.id ? findModelName(route.id) : "Model";
  breadcrumbParts = ["Dashboard",modelName];
  breadcrumbLinks = ["#dashboard"];
  if(route.sub) breadcrumbParts.push(ANGLE_FULL_NAMES[route.sub]||ANGLE_LABELS[ANGLE_SHORT[route.sub]]||route.sub);
  /* Highlight sidebar model */
  var mLink = $('[data-route="#model/'+route.id+'"]');
  if(mLink) mLink.classList.add("active");
  /* Always rebuild scorecard — different model = different content */
  buildScorecard(D, route.id, route.sub||null);
  return {crumbs: breadcrumbParts, links: breadcrumbLinks};
}});
