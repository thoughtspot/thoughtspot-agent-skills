/* ── Formulas: each Model's formula dependency tree (audit v2 roadmap PR 3.2) ──
   The data is the corpus Model's `ft` (ts_cli/audit/formula_tree.py, compacted in
   report.py): nodes {n label, f formula name, k kind, h hidden, b used_by, u uses}
   where a use is [0, node index], [1, column ref] or [2, parameter name], and `r` the
   roots, the formulas nothing uses.
   Children are built only when a node is opened, since a formula many others use would
   otherwise be drawn once per path; a node already on the path is a circular reference. */
var FORMULA_EXPAND_ALL_CAP = 2000;
var FORMULA_KINDS = {MEASURE: true, ATTRIBUTE: true};
var FORMULA_PREDATES = "This report\u2019s data predates the Formulas view: re-run `ts audit run` "+
  "to build each Model\u2019s formula tree.";

/* Formulas counted but no tree built: the audit JSON predates this view. */
function predatesTree(cm){ return cm.fc > 0 && !cm.ft; }

function anyPredates(){
  return !!(D.C && D.C.m && D.C.m.some(predatesTree));
}

function formulaModels(){
  if(!D.C || !D.C.m) return [];
  return D.C.m.filter(function(cm){ return cm.ft && cm.ft.n && cm.ft.n.length; })
    .map(function(cm){ return {guid: D.L[cm.mi] ? D.L[cm.mi].g : "", cm: cm}; });
}

function buildFormulasPicker(c){
  var models = formulaModels();
  if(!models.length){
    var predates = anyPredates();
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">ƒ</div>'+
      '<div class="ph-text">'+(predates ? 'No formula trees in this report' : 'No formulas in the audited Models')+'</div>'+
      '<div class="ph-sub">'+esc(predates ? FORMULA_PREDATES :
        'A Model with formulas shows how they build on each other here.')+'</div></div>';
    return;
  }
  var html = '<div class="ftree-intro">How each Model’s formulas build on each other: '+
    'every tree starts at a formula nothing else uses (or where a circular chain is entered) '+
    'and opens down to the table columns and parameters. '+
    'Pick a Model.</div><ul class="ftree-models">';
  models.forEach(function(m){
    html += '<li><a href="#formulas/'+esc(m.guid)+'">'+esc(findModelName(m.guid))+'</a>'+
      '<span class="ftree-count">'+m.cm.ft.n.length+' formula'+(m.cm.ft.n.length === 1 ? '' : 's')+
      '</span></li>';
  });
  c.innerHTML = html + '</ul>';
}

function formulaRow(node){
  var row = el("div","ftree-row");
  var renamed = node.f && node.f !== node.n;
  var html = '<span class="ftree-toggle" aria-hidden="true"></span>'+
    '<span class="ftree-name"'+(renamed ? ' title="Formula: '+esc(node.f)+'"' : '')+'>'+esc(node.n)+'</span>';
  if(FORMULA_KINDS[node.k]) html += '<span class="ftree-tag ftree-kind" data-kind="'+node.k+'">'+node.k+'</span>';
  if(node.h && node.b > 0) html += '<span class="ftree-tag ftree-hidden" title="Hidden from search, or surfaced '+
    'by no column: it feeds the formulas that use it">hidden helper</span>';
  else if(node.h) html += '<span class="ftree-tag ftree-unused" title="Hidden from search, or surfaced by no '+
    'column, and used by no formula: a cleanup candidate">hidden, unused</span>';
  html += '<span class="ftree-used">used by '+node.b+' formula'+(node.b === 1 ? '' : 's')+'</span>';
  row.innerHTML = html;
  return row;
}

function formulaLeaf(text, cls){
  var li = el("li","ftree-leaf "+cls);
  li.innerHTML = '<div class="ftree-row"><span class="ftree-toggle" aria-hidden="true"></span>'+text+'</div>';
  return li;
}

/* One node. `path` is the indices from the root to here; `budget` counts rows built so
   Expand all can stop. Returns the <li>. */
function formulaNode(tree, i, path, budget){
  var node = tree.n[i];
  var li = el("li","ftree-node");
  var row = formulaRow(node);
  li.appendChild(row);
  budget.rows++;
  if(!node.u.length){ li.classList.add("ftree-leafy"); return li; }
  li.classList.add("collapsed");
  row.setAttribute("role","button");
  row.setAttribute("tabindex","0");
  row.setAttribute("aria-expanded","false");
  var here = path.concat([i]);
  function open(){
    if(!li._built){
      var ul = el("ul","ftree-children");
      node.u.forEach(function(use){
        if(use[0] === 1){
          ul.appendChild(formulaLeaf('<code class="ftree-col">'+esc(use[1])+'</code>', "ftree-colleaf"));
          budget.rows++;
        } else if(use[0] === 2){
          ul.appendChild(formulaLeaf('<span class="ftree-tag ftree-param">parameter</span>'+
            '<span class="ftree-name">'+esc(use[1])+'</span>', "ftree-paramleaf"));
          budget.rows++;
        } else if(here.indexOf(use[1]) !== -1){
          ul.appendChild(formulaLeaf('<span class="ftree-cycle">↻ circular reference to '+
            esc(tree.n[use[1]].n)+'</span>', "ftree-cycleleaf"));
          budget.rows++;
        } else {
          ul.appendChild(formulaNode(tree, use[1], here, budget));
        }
      });
      li.appendChild(ul);
      li._built = true;
    }
    li.classList.remove("collapsed");
    row.setAttribute("aria-expanded","true");
  }
  function toggle(){
    if(li.classList.contains("collapsed")) open();
    else { li.classList.add("collapsed"); row.setAttribute("aria-expanded","false"); }
  }
  row.addEventListener("click", toggle);
  row.addEventListener("keydown", function(e){
    if(e.key === "Enter" || e.key === " "){ e.preventDefault(); toggle(); }
  });
  li._open = open;
  return li;
}

/* Open every node under `root`, stopping once THIS expansion has built `cap` rows
   (formulas, columns, parameters and circular references alike); the node being opened
   when it gets there is finished, so a press can overshoot by one formula's uses.
   Returns whether it stopped early. */
function expandAll(root, budget, cap){
  var start = budget.rows;
  var stack = Array.prototype.slice.call(root.querySelectorAll("li.ftree-node.collapsed"));
  while(stack.length && budget.rows - start < cap){
    var li = stack.shift();
    if(!li._open || !li.classList.contains("collapsed")) continue;
    li._open();
    stack = stack.concat(Array.prototype.slice.call(
      li.querySelectorAll(":scope > ul > li.ftree-node.collapsed")));
  }
  return stack.some(function(li){ return li._open && li.classList.contains("collapsed"); });
}

function buildFormulaTree(c, guid){
  var cm = findCorpusModel(guid);
  var tree = cm && cm.ft;
  if(!tree || !tree.n.length){
    var why = !cm ? "This report has no such Model." :
      (predatesTree(cm) ? FORMULA_PREDATES : "This Model has no formulas.");
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">ƒ</div>'+
      '<div class="ph-text">No formula tree</div><div class="ph-sub">'+esc(why)+'</div></div>';
    return;
  }
  var hdr = el("div","ftree-header");
  hdr.innerHTML = '<div class="model-title">'+esc(findModelName(guid))+'</div>'+
    '<div class="ftree-sub">'+tree.n.length+' formula'+(tree.n.length === 1 ? '' : 's')+', '+
    tree.r.length+' at the top. Click a formula to open what it uses.</div>'+
    '<div class="header-actions"><button class="erd-btn ftree-expand">Expand all</button>'+
    '<button class="erd-btn ftree-collapse">Collapse all</button>'+
    '<a class="ts-link-btn" href="#model/'+esc(guid)+'">Model scorecard</a></div>';
  c.appendChild(hdr);
  var note = el("div","ftree-note");
  c.appendChild(note);
  var ul = el("ul","ftree");
  var budget = {rows: 0};
  tree.r.forEach(function(i){
    var li = formulaNode(tree, i, [], budget);
    ul.appendChild(li);
    if(li._open) li._open();  /* roots open one level */
  });
  c.appendChild(ul);
  $(".ftree-expand", hdr).addEventListener("click", function(){
    var capped = expandAll(ul, budget, FORMULA_EXPAND_ALL_CAP);
    note.textContent = capped ? "Stopped after about "+FORMULA_EXPAND_ALL_CAP+" more rows: press Expand all again, "+
      "or open the rest by hand." : "";
  });
  $(".ftree-collapse", hdr).addEventListener("click", function(){
    $$("li.ftree-node", ul).forEach(function(li){
      if(li._open && !li.classList.contains("collapsed")){
        li.classList.add("collapsed");
        li.firstChild.setAttribute("aria-expanded","false");
      }
    });
    note.textContent = "";
  });
}

function buildFormulas(D, guid){
  var c = document.getElementById("v-formulas");
  c.innerHTML = "";
  if(guid) buildFormulaTree(c, guid);
  else buildFormulasPicker(c);
}

/* ── Route registration (core.js's router dispatches by route name) ── */
registerView({id: "formulas", routes: ["formulas"],
  nav: {hash: "#formulas", icon: "ƒ", label: "Formulas"},
  show: function(route){
  buildFormulas(D, route.id);
  if(route.id) return {crumbs: ["Formulas", findModelName(route.id)], links: ["#formulas"]};
  return {crumbs: ["Formulas"], links: []};
}});
