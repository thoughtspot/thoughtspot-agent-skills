var _sevFilterListener = null;

/* ── Header: the Model, its counts, description and the link to ThoughtSpot ── */
function scorecardHeader(guid, cm){
  var modelName = findModelName(guid);
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

  /* Actions: the ERD and the Formulas are tabs (model_nav.js) */
  if(D.C && D.C.u){
    titleHtml += '<div class="header-actions">'+
      '<a class="ts-link-btn" href="'+D.C.u+'/#/data/tables/'+guid+'" target="_blank" rel="noopener">Open in ThoughtSpot ↗</a></div>';
  }
  hdr.innerHTML = titleHtml;
  return hdr;
}

/* ── The Model's ERD, drawn inline (agents/shared/erd, carried in D.E) ── */
function erdPageHtml(cm){
  var erdData = cm.ed;
  if(cm.ai){erdData.model.ai_analysis={domain:cm.ai.do||"",objectives:cm.ai.ob||[],personas:cm.ai.pe||[],questions:cm.ai.qu||[]};}
  var bundle = {models:[erdData],index:[{
    name:erdData.model.name,guid:erdData.model.guid,
    tables:erdData.tables.length,joins:erdData.joins.length,
    findings:(erdData.findings||[]).length,
    rls:erdData.tables.reduce(function(s,t){return s+(t.rls||[]).length;},0)
  }],dropped:[]};
  return '<!doctype html><html lang="en"><head><meta charset="utf-8">'+
    '<meta name="viewport" content="width=device-width, initial-scale=1">'+
    '<title>ERD: '+esc(erdData.model.name)+'</title>'+
    '<style>'+D.E.css+'</style></head><body>'+D.E.body+
    /* every < and > escaped, as report.py escapes the report's own data: a name holding
       a closing script tag, or a comment opener before an opening one, must not end or
       swallow the script. id="erd-data" is
       what the ERD's Share HTML reads (renderer.js shareHTML). */
    '<script id="erd-data">window.__ERD_DATA__ = '+
    JSON.stringify(bundle).replace(/</g, "\\u003c").replace(/>/g, "\\u003e")+';<\/script>'+
    '<script>'+D.E.js+'<\/script></body></html>';
}

/* A section holding the ERD, drawn in a frame the first time it is opened; `open`
   (route #model/<guid>/erd) opens it and scrolls to it. */
function erdSection(guid, cm, open){
  var sec = document.createElement("details");
  sec.className = "erd-panel";
  sec.id = "erd-"+guid;
  sec.innerHTML = '<summary>ERD</summary><div class="erd-panel-body"></div>';
  var body = sec.lastChild;
  function fill(){
    if(body.firstChild) return;
    if(!cm || !cm.ed || !D.E){
      body.innerHTML = '<div class="erd-container"><div style="font-size:20px;">⬡</div>'+
        '<div class="erd-msg">ERD data not available</div>'+
        '<div class="erd-sub">Use /ts-object-model-erd for standalone ERD rendering.</div></div>';
      return;
    }
    var page = erdPageHtml(cm);
    var frame = document.createElement("iframe");
    frame.className = "erd-frame";
    frame.title = "ERD of "+findModelName(guid);
    frame.srcdoc = page;
    var tab = el("button", "ts-link-btn erd-newtab", "Open in a new tab ↗");
    tab.type = "button";
    tab.addEventListener("click", function(){
      window.open(URL.createObjectURL(new Blob([page], {type: "text/html"})), "_blank");
    });
    body.appendChild(tab);
    body.appendChild(frame);
  }
  sec.addEventListener("toggle", function(){ if(sec.open) fill(); });
  /* open it and bring it into view; after this turn, as the router shows the view once
     it is built */
  sec._show = function(){
    sec.open = true;
    fill();
    setTimeout(function(){ sec.scrollIntoView({block: "start"}); }, 0);
  };
  if(open) sec._show();
  return sec;
}

/* ── AI Analysis panel ── */
function scorecardAiPanel(cm){
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
  return aiPanel;
}

/* ── Dependents panel: what uses the Model downstream ── */
function scorecardDependents(guid){
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
  return depsPanel;
}

/* ── Build scorecard ── */
function buildScorecard(D, guid, filterAngle, showErd){
  var c = document.getElementById("v-scorecard");
  c.innerHTML = "";

  /* Remove old listener before rebuilding */
  if(_sevFilterListener) document.removeEventListener("sev-filter-changed", _sevFilterListener);

  var cm = findCorpusModel(guid);
  if(knownModel(guid)) c.appendChild(modelTabs(guid, showErd ? "erd" : "scorecard"));
  c.appendChild(scorecardHeader(guid, cm));
  var erd = erdSection(guid, cm, showErd);
  c.appendChild(erd);
  /* on #model/<guid>/erd the ERD tab's link is the page itself, so following it changes
     nothing: open the section again (it may have been closed) instead */
  var erdTab = $('.model-tabs a[data-tab="erd"]', c);
  if(erdTab) erdTab.addEventListener("click", function(e){
    if(location.hash === erdTab.getAttribute("href")){ e.preventDefault(); erd._show(); }
  });
  if(cm && cm.ai) c.appendChild(scorecardAiPanel(cm));

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
        topHtml += '<div class="detail-text">'+esc(f.d)+nameMatchTag(f)+'</div>';

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



  c.appendChild(scorecardDependents(guid));

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
/* #model/<guid> the scorecard, #model/<guid>/erd with its ERD open, #model/<guid>/<category>
   with that category's findings open (the Dashboard heatmap's cells). */
registerView({id: "scorecard", routes: ["model"], pills: true, show: function(route){
  var erd = route.sub === "erd", angle = erd ? null : route.sub;
  highlightSidebarModel(route.id);
  /* Always rebuild scorecard — different model = different content */
  buildScorecard(D, route.id, angle, erd);
  if(erd) return modelCrumbs(route.id, "ERD");
  return modelCrumbs(route.id, "Scorecard",
    angle ? (ANGLE_FULL_NAMES[angle]||ANGLE_LABELS[angle]||ANGLE_LABELS[ANGLE_SHORT[angle]]||angle) : null);
}});
