/* ── Model pages: one tab bar and one breadcrumb for every page about one Model ──
   Scorecard (#model/<guid>), ERD (#model/<guid>/erd: the scorecard with its ERD open),
   Formulas (#formulas/<guid>, and its graph #formulas/<guid>/graph) and Data Cache
   (#datacache/<guid>: the Data Cache view filtered to the Model). Each of those pages
   puts modelTabs() at its top and returns modelCrumbs() for the breadcrumb, which reads
   "Audit / <Model> / <page>", the Model linking to its scorecard. Formulas is a tab on
   every Model, disabled with the reason when the Model has no formula tree, so the tabs
   stand in the same place from one Model to the next; Data Cache is a tab only when the
   report carries Data Cache readiness, which is all its Models or none. */
var MODEL_TAB_LABELS = {scorecard: "Scorecard", erd: "ERD", formulas: "Formulas", datacache: "Data Cache"};

/* The report lists this Model: only then does a page about it get the tabs. */
function knownModel(guid){
  return !!(D.L && D.L.some(function(m){ return m && m.g === guid; }));
}

/* Whether the run assessed Data Cache readiness: the Performance angle ran (P19 to P28),
   or the report does not record its angles. JSON before 3.23.0 carries no readiness at
   all. The Dashboard's Data Cache column and the Data Cache tab both ask this. */
function dataCacheRan(){
  return D.C && D.C.ar && D.C.ar.length ? D.C.ar.indexOf("P") !== -1 : true;
}

/* Why a Model has no Formulas page, or "" when it has one. */
function noFormulasReason(cm){
  if(!cm) return "This report holds no formula data for this Model.";
  if(cm.ft && cm.ft.n && cm.ft.n.length) return "";
  return predatesTree(cm) ? "This report predates the Formulas view: re-run `ts audit run`."
    : "This Model has no formulas.";
}

/* The tabs, `current` ("scorecard", "erd", "formulas" or "datacache") marked. A caller
   adds them only for a Model the report lists (knownModel). */
function modelTabs(guid, current){
  var cm = findCorpusModel(guid), g = esc(guid);
  var tabs = [["scorecard", "#model/"+g], ["erd", "#model/"+g+"/erd"], ["formulas", "#formulas/"+g]];
  if(cm && cm.dc && dataCacheRan()) tabs.push(["datacache", "#datacache/"+g]);
  var nav = el("nav", "model-tabs");
  nav.setAttribute("aria-label", "Pages for this Model");
  nav.innerHTML = tabs.map(function(t){
    var label = MODEL_TAB_LABELS[t[0]], why = t[0] === "formulas" ? noFormulasReason(cm) : "";
    if(why) return '<span class="model-tab model-tab-off" data-tab="'+t[0]+'" aria-disabled="true" title="'+
      esc(why)+'">'+label+'<span class="visually-hidden"> (unavailable: '+esc(why)+')</span></span>';
    return '<a class="model-tab" data-tab="'+t[0]+'" href="'+t[1]+'"'+
      (t[0] === current ? ' aria-current="page"' : '')+'>'+label+'</a>';
  }).join("");
  return nav;
}

/* The breadcrumb of a Model page: Audit / <Model> / <page>[ / <more>]. */
function modelCrumbs(guid, page, more){
  var crumbs = [findModelName(guid), page], links = ["#model/"+guid];
  if(more){ crumbs.push(more); links.push("#model/"+guid); }
  return {crumbs: crumbs, links: links};
}

/* The Model's link in the sidebar's Models list, shown as the page's place. */
function highlightSidebarModel(guid){
  $$(".sidebar-model-list a").forEach(function(a){
    if(a.getAttribute("href") === "#model/"+guid) a.classList.add("active");
  });
}
