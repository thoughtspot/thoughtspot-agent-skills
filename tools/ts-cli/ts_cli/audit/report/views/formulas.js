/* ── Formulas: each Model's formula dependency tree (audit v2 roadmap PR 3.2) ──
   The data is the corpus Model's `ft` (ts_cli/audit/formula_tree.py, compacted in
   report.py): nodes {n name, k kind, h hidden, b used_by, u uses} where a use is
   [0, node index] or [1, column ref], and `r` the roots, the formulas nothing uses.
   Children are built only when a node is opened, since a formula many others use would
   otherwise be drawn once per path; a node already on the path is a circular reference. */
var FORMULA_EXPAND_ALL_CAP = 2000;

function formulaModels(){
  if(!D.C || !D.C.m) return [];
  return D.C.m.filter(function(cm){ return cm.ft && cm.ft.n && cm.ft.n.length; })
    .map(function(cm){ return {guid: D.L[cm.mi] ? D.L[cm.mi].g : "", cm: cm}; });
}

function buildFormulasPicker(c){
  var models = formulaModels();
  if(!models.length){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">ƒ</div>'+
      '<div class="ph-text">No formulas in the audited Models</div>'+
      '<div class="ph-sub">A Model with formulas shows how they build on each other here.</div></div>';
    return;
  }
  var html = '<div class="ftree-intro">How each Model’s formulas build on each other: '+
    'every tree starts at a formula nothing else uses and opens down to the table columns. '+
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
  var html = '<span class="ftree-toggle" aria-hidden="true"></span>'+
    '<span class="ftree-name">'+esc(node.n)+'</span>';
  if(node.k) html += '<span class="ftree-tag ftree-kind" data-kind="'+esc(node.k)+'">'+esc(node.k)+'</span>';
  if(node.h) html += '<span class="ftree-tag ftree-hidden" title="Hidden from search, or surfaced by no column: '+
    'it exists to feed other formulas">hidden helper</span>';
  html += '<span class="ftree-used">used by '+node.b+'</span>';
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
        } else if(here.indexOf(use[1]) !== -1){
          ul.appendChild(formulaLeaf('<span class="ftree-cycle">↻ circular reference to '+
            esc(tree.n[use[1]].n)+'</span>', "ftree-cycleleaf"));
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

/* Open every node under `root`, stopping once the tree holds `cap` rows. */
function expandAll(root, budget, cap){
  var stack = Array.prototype.slice.call(root.querySelectorAll("li.ftree-node.collapsed"));
  while(stack.length && budget.rows < cap){
    var li = stack.shift();
    if(!li._open || !li.classList.contains("collapsed")) continue;
    li._open();
    stack = stack.concat(Array.prototype.slice.call(
      li.querySelectorAll(":scope > ul > li.ftree-node.collapsed")));
  }
  return budget.rows >= cap;
}

function buildFormulaTree(c, guid){
  var cm = findCorpusModel(guid);
  var tree = cm && cm.ft;
  if(!tree){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">ƒ</div>'+
      '<div class="ph-text">No formulas in this Model</div></div>';
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
    note.textContent = capped ? "Stopped at "+FORMULA_EXPAND_ALL_CAP+" rows: open the rest by hand." : "";
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
