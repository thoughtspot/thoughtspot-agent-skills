/* ── Formulas: the graph mode (route #formulas/<guid>/graph) ──
   One Model's formula lineage drawn left to right: table columns and parameters on the
   left, the formulas built on them to the right, each formula after everything it uses.
   Cytoscape.js draws it and dagre lays it out (vendor/README.md); both travel in the
   data (`D.V`, report.py `render_report`) only when some Model has a formula built on
   another, and run the first time a graph opens. Clicking a node opens the same
   definition panel as the tree (views/formulas.js) and highlights everything upstream
   and downstream of it; a link in the panel moves the graph to that node. A Model past
   FORMULA_GRAPH_CAP nodes is drawn one lineage at a time: the selected node, what it
   uses and what depends on it. The canvas is not keyboard-reachable; the tree is the
   accessible form of the same data, one click away. */
var FORMULA_GRAPH_CAP = 300;  /* nodes drawn whole; beyond it, one lineage at a time */
var FORMULA_GRAPH_MIN_ZOOM = 0.7;  /* a wider graph opens at its left edge, panned from there */

/* The graph libraries are in this report, and the Model has a formula built on another. */
function graphAvailable(tree){
  return !!(D.V && tree && tree.n.some(function(node){
    return node.u.some(function(u){ return u[0] === 0; });
  }));
}

/* Run the libraries once; true when Cytoscape is ready. */
function loadGraphLibraries(){
  if(!window.cytoscape && D.V){
    var s = document.createElement("script");
    s.text = D.V;
    document.head.appendChild(s);
  }
  return !!window.cytoscape;
}

function graphNodeId(use){
  return use[0] === 0 ? "f"+use[1] : (use[0] === 1 ? "c:" : "p:")+use[1];
}

/* Every node id the Model's graph has: formulas, and the columns and parameters they use. */
function graphNodeIds(tree){
  var ids = {};
  tree.n.forEach(function(node, i){
    ids["f"+i] = true;
    node.u.forEach(function(u){ ids[graphNodeId(u)] = true; });
  });
  return ids;
}

/* `target`, everything it uses (all the way down) and everything that depends on it. */
function graphLineage(tree, target){
  var keep = {}, stack = target[0] === 0 ? [target[1]] : [];
  keep[graphNodeId(target)] = true;
  while(stack.length){
    var i = stack.pop();
    tree.n[i].u.forEach(function(u){
      var id = graphNodeId(u);
      if(keep[id]) return;
      keep[id] = true;
      if(u[0] === 0) stack.push(u[1]);
    });
  }
  allDependents(tree, target).forEach(function(j){ keep["f"+j] = true; });
  return keep;
}

/* Cytoscape elements for the Model's graph, or the part of it `keep` names. */
function graphElements(tree, keep){
  var nodes = [], edges = [], seen = {};
  function node(id, label, cls, use){
    if(seen[id] || (keep && !keep[id])) return;
    seen[id] = true;
    nodes.push({data: {id: id, label: label, w: Math.max(48, label.length * 7 + 22), use: use},
      classes: cls});
  }
  tree.n.forEach(function(f, i){
    var cls = "formula" + (f.k === "MEASURE" ? " measure" : f.k === "ATTRIBUTE" ? " attribute" : "") +
      (f.h ? " hidden" : "") + (singleUse(f) ? " single" : "");
    node("f"+i, f.n, cls, [0, i]);
  });
  tree.n.forEach(function(f, i){
    if(keep && !keep["f"+i]) return;
    f.u.forEach(function(u){
      var id = graphNodeId(u);
      if(u[0] !== 0) node(id, String(u[1]), u[0] === 1 ? "column" : "parameter", u);
      if(keep && !keep[id]) return;
      edges.push({data: {source: id, target: "f"+i}});  /* Cytoscape names it: no id clash */
    });
  });
  return nodes.concat(edges);
}

function graphStyle(){
  var css = getComputedStyle(document.documentElement);
  function v(name, fallback){ return (css.getPropertyValue(name) || "").trim() || fallback; }
  var ink = v("--ink", "#1f2328"), muted = v("--muted", "#6b7280"), line = v("--hair", "#d0d7de"),
      card = v("--surface", "#ffffff"), accent = v("--accent", "#2563eb"), warn = v("--warn", "#b5730a");
  return [
    {selector: "node", style: {"shape": "round-rectangle", "width": "data(w)", "height": 26,
      "label": "data(label)", "font-size": 11, "color": ink, "text-valign": "center",
      "text-halign": "center", "background-color": card, "border-width": 1, "border-color": line}},
    {selector: "node.measure", style: {"border-color": accent, "border-width": 2}},
    {selector: "node.attribute", style: {"border-color": muted, "border-width": 2}},
    {selector: "node.hidden", style: {"border-style": "dashed"}},
    {selector: "node.single", style: {"border-color": warn, "border-width": 2}},
    {selector: "node.column", style: {"shape": "rectangle", "color": muted, "font-family": "monospace"}},
    {selector: "node.parameter", style: {"shape": "tag", "color": muted}},
    {selector: "edge", style: {"width": 1, "line-color": line, "curve-style": "bezier",
      "target-arrow-shape": "triangle", "target-arrow-color": line, "arrow-scale": 0.8}},
    {selector: ".faded", style: {"opacity": 0.18}},
    {selector: "node.focus", style: {"background-color": accent, "color": card}},
    {selector: "edge.lit", style: {"line-color": accent, "target-arrow-color": accent, "width": 2}}
  ];
}

function graphNote(total, tree, target){
  return total > FORMULA_GRAPH_CAP ?
    "This Model has "+total+" formulas, columns and parameters, too many to draw at once: showing the lineage of "+
    useLabel(tree, target)+". Pick another from the search box or by clicking a node." :
    total+" formulas, columns and parameters. Click a node to see its definition and its lineage.";
}

/* Where a Model too big to draw whole opens: the root whose lineage is the largest that
   still fits under the cap, or, when none does, the smallest (a click draws any other). */
function graphStart(tree){
  var best = null, size = -1, smallest = null, least = Infinity;
  tree.r.forEach(function(i){
    var n = Object.keys(graphLineage(tree, [0, i])).length;
    if(n <= FORMULA_GRAPH_CAP && n > size){ size = n; best = i; }
    if(n < least){ least = n; smallest = i; }
  });
  return [0, best !== null ? best : smallest];
}

function buildFormulaGraph(c, guid, tree){
  if(!loadGraphLibraries()){
    c.innerHTML = '<div class="view-placeholder"><div class="ph-icon">ƒ</div><div class="ph-text">'+
      'The graph could not be drawn</div><div class="ph-sub">Its libraries did not load: use the tree.</div></div>';
    return;
  }
  var total = Object.keys(graphNodeIds(tree)).length;
  var partial = total > FORMULA_GRAPH_CAP;
  var hdr = el("div","ftree-header");
  hdr.innerHTML = '<div class="model-title">'+esc(findModelName(guid))+'</div>'+
    '<div class="ftree-sub fgraph-sub"></div>'+
    '<div class="header-actions"><input class="ftree-search" type="search" '+
    'placeholder="Find a formula, column or parameter" aria-label="Find a formula, column or parameter">'+
    '<a class="erd-btn fgraph-mode" href="#formulas/'+esc(guid)+'">Tree</a>'+
    '<a class="ts-link-btn" href="#model/'+esc(guid)+'">Model scorecard</a></div>';
  c.appendChild(hdr);
  var results = el("div","ftree-results");
  c.appendChild(results);
  var layout = el("div","ftree-layout");
  var box = el("div","fgraph");
  box.setAttribute("role","img");
  box.setAttribute("aria-label","Formula lineage graph; the tree shows the same data and is keyboard-reachable");
  var panel = el("aside","fdetail fdetail-empty");
  panel.setAttribute("aria-label","Definition");
  panel.setAttribute("aria-live","polite");
  var EMPTY = '<div class="fdetail-none">Click a node to see its definition, what it uses and what uses it.</div>';
  panel.innerHTML = EMPTY;
  layout.appendChild(box);
  layout.appendChild(panel);
  c.appendChild(layout);
  var cy = null, shown = null;
  function draw(keep){
    if(cy) cy.destroy();
    cy = c._cy = window.cytoscape({container: box, elements: graphElements(tree, keep),
      style: graphStyle(), minZoom: 0.05, maxZoom: 3,
      layout: {name: "dagre", rankDir: "LR", nodeSep: 10, rankSep: 70, edgeSep: 6}});
    cy.on("tap", "node", function(e){ view.select(e.target.data("use")); });
    cy.on("tap", function(e){ if(e.target === cy) clearHighlight(); });
    fit();
  }
  /* The view may be built before its container is shown (the router shows it after,
     in the same turn), when Cytoscape reads a size of nothing: measure and fit again
     once this turn is over. */
  function fit(){
    setTimeout(function(){
      if(!cy || cy.destroyed()) return;  /* the view was rebuilt before this frame */
      cy.stop(true);  /* an animation begun while hidden ends on a pan worked out for no size */
      cy.resize();
      cy.fit(undefined, 24);
      if(cy.zoom() < FORMULA_GRAPH_MIN_ZOOM){  /* readable labels over seeing it all */
        var bb = cy.elements().boundingBox();
        cy.zoom(FORMULA_GRAPH_MIN_ZOOM);
        cy.pan({x: 24 - bb.x1 * FORMULA_GRAPH_MIN_ZOOM,
                y: box.clientHeight / 2 - (bb.y1 + bb.y2) / 2 * FORMULA_GRAPH_MIN_ZOOM});
      }
      var sel = cy.$(".focus");
      if(sel.length) cy.center(sel);
    }, 0);
  }
  function clearHighlight(){
    if(cy) cy.elements().removeClass("faded focus lit");
  }
  /* `animate`: glide to the node; otherwise (a redraw, or a view not yet shown) fit()
     centres it once the canvas has a size. */
  function highlight(id, animate){
    var n = cy.getElementById(id);
    if(!n.length) return;
    var reach = n.predecessors().union(n.successors()).union(n);
    clearHighlight();
    cy.elements().addClass("faded");
    reach.removeClass("faded");
    reach.edges().addClass("lit");
    n.addClass("focus");
    if(animate) cy.animate({center: {eles: n}, duration: 200});
    else fit();
  }
  var view = tree._view = {
    select: function(target, row, focusPanel){
      tree._selected = target;
      panel.innerHTML = detailHtml(tree, target);
      panel.classList.remove("fdetail-empty");
      layout.classList.add("ftree-has-detail");
      var id = graphNodeId(target), redrawn = false;
      if(partial && !(shown && shown[id])){
        shown = graphLineage(tree, target);
        draw(shown);
        redrawn = true;
      }
      $(".fgraph-sub", hdr).textContent = graphNote(total, tree, target);
      cy.resize();
      highlight(id, !redrawn && box.offsetParent !== null);
      if(focusPanel) $(".fdetail-title", panel).focus();
    }
  };
  function closePanel(){
    var focusLost = panel.contains(document.activeElement);
    panel.innerHTML = EMPTY;
    panel.classList.add("fdetail-empty");
    layout.classList.remove("ftree-has-detail");
    clearHighlight();
    tree._selected = null;
    if(cy) cy.resize();
    if(focusLost) $(".ftree-search", hdr).focus();  /* not lost to <body> */
  }
  panel.addEventListener("click", function(e){ if(e.target.closest(".fdetail-close")) closePanel(); });
  layout.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !panel.classList.contains("fdetail-empty")){ e.preventDefault(); closePanel(); }
  });
  wireRefLinks(layout, view);
  wireRefLinks(results, view);
  $(".ftree-search", hdr).addEventListener("input", function(e){
    results.innerHTML = searchResultsHtml(tree, e.target.value);
  });
  var start = tree._selected || (partial ? graphStart(tree) : null);
  if(partial) shown = graphLineage(tree, start);
  draw(shown);
  $(".fgraph-sub", hdr).textContent = graphNote(total, tree, start || [0, tree.r[0]]);
  if(tree._selected) view.select(tree._selected);
}
