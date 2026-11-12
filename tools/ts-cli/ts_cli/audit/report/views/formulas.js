/* ── Formulas: each Model's formula dependency tree (audit v2 roadmap PR 3.2) ──
   The data is the corpus Model's `ft` (ts_cli/audit/formula_tree.py, compacted in
   report.py): nodes {n label, f formula name, k kind, h hidden, b used_by, u uses}
   where a use is [0, node index], [1, column ref] or [2, parameter name], `x` the
   expression as text strings and references in that same encoding (absent from a report
   written before definitions were kept), and `r` the roots, the formulas nothing uses.
   Clicking a formula, column or parameter opens the definition panel beside the tree:
   its expression with every reference a link, what it uses, what uses it and everything
   that depends on it. Following a link opens the tree down to that formula.
   Children are built only when a node is opened, since a formula many others use would
   otherwise be drawn once per path; a node already on the path is a circular reference. */
var FORMULA_EXPAND_ALL_CAP = 2000;
var FORMULA_KINDS = {MEASURE: true, ATTRIBUTE: true};
var FORMULA_NO_DEFS = "This report predates formula definitions: re-run `ts audit run` to see them.";
var FORMULA_SEARCH_CAP = 50;
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

function formulaLeaf(text, cls, target, view){
  var li = el("li","ftree-leaf "+cls);
  li.innerHTML = '<div class="ftree-row"><span class="ftree-toggle" aria-hidden="true"></span>'+text+'</div>';
  if(target) pickable(li.firstChild, view, target);
  return li;
}

/* A row that opens `target` ([kind, value], the use encoding) in the definition panel. */
function pickable(row, view, target, after){
  row.setAttribute("role","button");
  row.setAttribute("tabindex","0");
  row._target = target;
  function go(){ var was = row.classList.contains("ftree-selected");
    view.select(target, row); if(after) after(was); }
  row.addEventListener("click", go);
  row.addEventListener("keydown", function(e){
    if(e.key === "Enter" || e.key === " "){ e.preventDefault(); go(); }
  });
}

/* One node. `path` is the indices from the root to here; `budget` counts rows built so
   Expand all can stop. Returns the <li>. */
function formulaNode(tree, i, path, budget){
  var node = tree.n[i];
  var li = el("li","ftree-node");
  li.setAttribute("data-i", i);
  var row = formulaRow(node);
  li.appendChild(row);
  budget.rows++;
  if(!node.u.length){
    li.classList.add("ftree-leafy");
    pickable(row, tree._view, [0, i]);
    return li;
  }
  li.classList.add("collapsed");
  row.setAttribute("aria-expanded","false");
  var here = path.concat([i]);
  function open(){
    if(!li._built){
      var ul = el("ul","ftree-children");
      if(node.x){  /* the definition, inline; not a row, so Expand all's cap ignores it */
        var line = el("li","ftree-exprline");
        line.innerHTML = '<span class="ftree-eq">= </span>'+exprHtml(tree, node.x);
        ul.appendChild(line);
      }
      node.u.forEach(function(use){
        if(use[0] === 1){
          ul.appendChild(formulaLeaf('<code class="ftree-col">'+esc(use[1])+'</code>', "ftree-colleaf", use, tree._view));
          budget.rows++;
        } else if(use[0] === 2){
          ul.appendChild(formulaLeaf('<span class="ftree-tag ftree-param">parameter</span>'+
            '<span class="ftree-name">'+esc(use[1])+'</span>', "ftree-paramleaf", use, tree._view));
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
  function close(){ li.classList.add("collapsed"); row.setAttribute("aria-expanded","false"); }
  /* A click opens the definition and the node; a second click on the selected row, or
     a click on the arrow, closes it. */
  pickable(row, tree._view, [0, i], function(wasSelected){
    if(li.classList.contains("collapsed")) open();
    else if(wasSelected) close();
  });
  row.firstChild.addEventListener("click", function(e){
    e.stopPropagation();
    if(li.classList.contains("collapsed")) open(); else close();
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


/* ── The definition panel ── */

/* What a reference in the use encoding is called on screen. */
function useLabel(tree, use){ return use[0] === 0 ? tree.n[use[1]].n : String(use[1]); }

function refLink(tree, use){
  return '<a class="fref fref-'+use[0]+'" role="button" tabindex="0" data-k="'+use[0]+'" data-v="'+
    esc(String(use[1]))+'">'+esc(useLabel(tree, use))+'</a>';
}

/* An expression's segments as HTML: text escaped, each reference a link. */
function exprHtml(tree, x){
  return x.map(function(s){ return typeof s === "string" ? esc(s) : refLink(tree, s); }).join("");
}

function sameUse(a, b){ return a[0] === b[0] && String(a[1]) === String(b[1]); }

/* Formula indices that use `target` directly, in formula order. */
function directUsers(tree, target){
  var out = [];
  tree.n.forEach(function(node, j){
    if(node.u.some(function(u){ return sameUse(u, target); })) out.push(j);
  });
  return out;
}

/* Everything that depends on `target`, nearest first; a cycle is listed once. */
function allDependents(tree, target){
  var seen = {}, order = [], queue = directUsers(tree, target);
  if(target[0] === 0) seen[target[1]] = true;
  while(queue.length){
    var j = queue.shift();
    if(seen[j]) continue;
    seen[j] = true; order.push(j);
    queue = queue.concat(directUsers(tree, [0, j]));
  }
  return order;
}

function linkList(tree, cls, uses, none){
  if(!uses.length) return '<div class="'+cls+' fdetail-none">'+esc(none)+'</div>';
  return '<ul class="'+cls+'">'+uses.map(function(u){ return '<li>'+refLink(tree, u)+'</li>'; }).join("")+'</ul>';
}

function detailHtml(tree, target){
  var html = "", users = directUsers(tree, target);
  if(target[0] === 0){
    var node = tree.n[target[1]];
    html += '<div class="fdetail-title">'+esc(node.n)+'</div><div class="fdetail-meta">';
    if(FORMULA_KINDS[node.k]) html += '<span class="ftree-tag ftree-kind" data-kind="'+node.k+'">'+node.k+'</span>';
    if(node.h) html += '<span class="ftree-tag '+(node.b > 0 ? 'ftree-hidden">hidden helper' : 'ftree-unused">hidden, unused')+'</span>';
    if(node.f && node.f !== node.n) html += '<span class="fdetail-fname">Formula: '+esc(node.f)+'</span>';
    html += '</div><div class="fdetail-label">Definition</div>';
    html += node.x ? '<pre class="fdetail-expr">'+exprHtml(tree, node.x)+'</pre>'
      : '<div class="fdetail-note">'+esc(FORMULA_NO_DEFS)+'</div>';
    html += '<div class="fdetail-label">Uses ('+node.u.length+')</div>'+
      linkList(tree, "fdetail-uses", node.u, "No columns, parameters or formulas.");
  } else {
    html += '<div class="fdetail-title'+(target[0] === 1 ? ' fdetail-code' : '')+'">'+esc(String(target[1]))+'</div>'+
      '<div class="fdetail-meta"><span class="ftree-tag ftree-param">'+(target[0] === 1 ? 'column' : 'parameter')+'</span></div>';
  }
  html += '<div class="fdetail-label">Used by ('+users.length+')</div>'+
    linkList(tree, "fdetail-usedby", users.map(function(j){ return [0, j]; }),
      "Nothing uses it: it is at the top of the tree.");
  var all = allDependents(tree, target);
  if(all.length > users.length){
    html += '<details class="fdetail-dependents"><summary>Everything that depends on it ('+all.length+')</summary>'+
      '<ul>'+all.map(function(j){ return '<li>'+refLink(tree, [0, j])+'</li>'; }).join("")+'</ul></details>';
  }
  return html;
}

/* Root-to-`i` formula indices, the shortest way down the tree; null if none. */
function pathTo(tree, i){
  var prev = {}, queue = [];
  tree.r.forEach(function(r){ if(!(r in prev)){ prev[r] = -1; queue.push(r); } });
  while(queue.length){
    var j = queue.shift();
    if(j === i){
      var path = [];
      for(var k = i; k !== -1; k = prev[k]) path.unshift(k);
      return path;
    }
    tree.n[j].u.forEach(function(u){
      if(u[0] === 0 && !(u[1] in prev)){ prev[u[1]] = j; queue.push(u[1]); }
    });
  }
  return null;
}

/* Open the tree down to `target` and return its row (the first, for a column or
   parameter: under the first formula that uses it). */
function revealRow(ul, tree, target){
  var at = target[0] === 0 ? target[1] : directUsers(tree, target)[0];
  if(at === undefined) return null;
  var path = pathTo(tree, at);
  if(!path) return null;
  var scope = ul, li = null;
  for(var p = 0; p < path.length; p++){
    li = $(':scope > li.ftree-node[data-i="'+path[p]+'"]', scope);
    if(!li) return null;
    if(p < path.length - 1 || target[0] !== 0){
      if(li._open) li._open();
      scope = $(':scope > ul.ftree-children', li);
    }
  }
  if(target[0] === 0) return li.firstChild;
  var leaf = $$(':scope > li.ftree-leaf > .ftree-row', scope).filter(function(r){
    return r._target && sameUse(r._target, target); })[0];
  return leaf || null;
}

/* Formulas by name, then formulas by definition, then columns and parameters. */
function searchHits(tree, q){
  q = q.trim().toLowerCase();
  if(!q) return [];
  var byName = [], byDef = [], other = [], seen = {};
  tree.n.forEach(function(node, j){
    if(node.n.toLowerCase().indexOf(q) !== -1 || String(node.f).toLowerCase().indexOf(q) !== -1){
      byName.push([0, j]); return;
    }
    var text = (node.x || []).map(function(s){ return typeof s === "string" ? s : useLabel(tree, s); }).join("");
    if(text.toLowerCase().indexOf(q) !== -1) byDef.push([0, j]);
  });
  tree.n.forEach(function(node){ node.u.forEach(function(u){
    var key = u[0]+":"+u[1];
    if(u[0] !== 0 && !seen[key] && String(u[1]).toLowerCase().indexOf(q) !== -1){ seen[key] = true; other.push(u); }
  }); });
  return byName.concat(byDef, other).slice(0, FORMULA_SEARCH_CAP);
}

/* Clicks and Enter on any reference link inside `root` open it. */
function wireRefLinks(root, view){
  function go(e){
    var a = e.target.closest && e.target.closest("a.fref");
    if(!a || !root.contains(a)) return;
    if(e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    var k = +a.getAttribute("data-k"), v = a.getAttribute("data-v");
    view.select([k, k === 0 ? +v : v]);
  }
  root.addEventListener("click", go);
  root.addEventListener("keydown", go);
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
    tree.r.length+' at the top. Click a formula to see its definition and open what it uses.</div>'+
    '<div class="header-actions"><input class="ftree-search" type="search" '+
    'placeholder="Find a formula, column or parameter" aria-label="Find a formula, column or parameter">'+
    '<button class="erd-btn ftree-expand">Expand all</button>'+
    '<button class="erd-btn ftree-collapse">Collapse all</button>'+
    '<a class="ts-link-btn" href="#model/'+esc(guid)+'">Model scorecard</a></div>';
  c.appendChild(hdr);
  var results = el("div","ftree-results");
  c.appendChild(results);
  var note = el("div","ftree-note");
  c.appendChild(note);
  var layout = el("div","ftree-layout");
  var panel = el("aside","fdetail");
  panel.setAttribute("aria-live","polite");
  panel.innerHTML = '<div class="fdetail-none">Click a formula, column or parameter to see its '+
    'definition, what it uses and what uses it.</div>';
  var ul = el("ul","ftree");
  layout.appendChild(ul);
  layout.appendChild(panel);
  var view = tree._view = {
    select: function(target, row){
      panel.innerHTML = detailHtml(tree, target);
      if(!row) row = revealRow(ul, tree, target);
      $$(".ftree-selected", ul).forEach(function(r){ r.classList.remove("ftree-selected"); });
      if(row) row.classList.add("ftree-selected");
      /* Narrow screens stack the panel above the tree: bring it into view instead. */
      var stacked = window.matchMedia && window.matchMedia("(max-width:900px)").matches;
      var into = stacked ? panel : row;
      if(into && into.scrollIntoView) into.scrollIntoView({block: stacked ? "start" : "nearest"});
    }
  };
  wireRefLinks(layout, view);
  wireRefLinks(results, view);
  var budget = {rows: 0};
  tree.r.forEach(function(i){
    var li = formulaNode(tree, i, [], budget);
    ul.appendChild(li);
    if(li._open) li._open();  /* roots open one level */
  });
  c.appendChild(layout);
  $(".ftree-search", hdr).addEventListener("input", function(e){
    var hits = searchHits(tree, e.target.value);
    results.innerHTML = !e.target.value.trim() ? "" : hits.length ?
      hits.map(function(u){ return refLink(tree, u); }).join("") :
      '<span class="fdetail-none">No formula, column or parameter matches.</span>';
  });
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
