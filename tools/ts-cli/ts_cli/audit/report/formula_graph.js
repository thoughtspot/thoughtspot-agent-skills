/* ── Formulas: the graph mode (route #formulas/<guid>/graph) ──
   One Model's formula lineage drawn left to right: table columns and parameters on the
   left, the formulas built on them to the right, each formula after everything it uses.
   Cytoscape.js draws it and dagre lays it out (vendor/README.md); both travel in the
   data (`D.V`, report.py `render_report`) only when some Model has a formula built on
   another, and run the first time a graph opens. Clicking a node opens the same
   definition panel as the tree (views/formulas.js) and highlights everything upstream
   and downstream of it; a link in the panel moves the graph to that node. A Model past
   FORMULA_GRAPH_CAP nodes is drawn one lineage at a time: the selected node, what it
   uses and what depends on it. The type chips (formula_types.js) hide a type's nodes and
   their edges and lay the rest out again; the cap counts only what the chips leave shown,
   so switching columns off can draw a large Model whole. The canvas is not
   keyboard-reachable; the tree is the accessible form of the same data, one click away. */
var FORMULA_GRAPH_CAP = 300;  /* nodes drawn whole; beyond it, one lineage at a time */
var FORMULA_GRAPH_MIN_ZOOM = 0.7;  /* a wider graph opens at its left edge, panned from there */
var FORMULA_GRAPH_MAX_FIT = 1.2;   /* a small graph is not blown up to fill the canvas */
var FORMULA_GRAPH_MIN_VISIBLE = 120;  /* px of canvas above a narrow screen's sheet */

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

/* Whether node `id` is of a type the chips show. */
function graphIdShown(tree, id){
  var c = id.charAt(0);
  return c === "f" ? useShown(tree, [0, +id.slice(1)]) : !!_ftypeShown[c === "c" ? "column" : "parameter"];
}

/* `keep`'s ids (every id when there is none) less the switched-off types. */
function graphShownIds(tree, keep){
  var out = {};
  Object.keys(keep || graphNodeIds(tree)).forEach(function(id){ if(graphIdShown(tree, id)) out[id] = true; });
  return out;
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
    var cls = "formula " + nodeMark(f) + (f.h ? " hidden" : "") + (singleUse(f) ? " single" : "");
    node("f"+i, f.n, cls, [0, i]);
  });
  /* a column or parameter `keep` names is drawn even when no formula drawn uses it */
  tree.n.forEach(function(f, i){
    f.u.forEach(function(u){
      var id = graphNodeId(u);
      if(u[0] !== 0) node(id, String(u[1]), u[0] === 1 ? "column" : "parameter", u);
      if(keep && !(keep[id] && keep["f"+i])) return;
      edges.push({data: {source: id, target: "f"+i}});  /* Cytoscape names it: no id clash */
    });
  });
  return nodes.concat(edges);
}

/* Each type's shape, fill and outline are formula_types.js's marks (styles.css .ftype-*),
   from the same tokens; hidden (dashed) and H16 (amber outline) mark the border only,
   so the shape and fill still say the type. */
function graphStyle(){
  var css = getComputedStyle(document.documentElement);
  function v(name, fallback){ return (css.getPropertyValue(name) || "").trim() || fallback; }
  var ink = v("--ink", "#1f2328"), muted = v("--muted", "#6b7280"), line = v("--hair", "#d0d7de"),
      card = v("--surface", "#ffffff"), accent = v("--accent", "#2563eb"), warn = v("--warn", "#b5730a");
  function mark(cls, shape, fill, stroke){
    return {selector: "node."+cls, style: {"shape": shape, "background-color": v(fill, card),
      "border-color": v(stroke, line), "border-width": 1.5}};
  }
  return [
    {selector: "node", style: {"shape": "round-rectangle", "width": "data(w)", "height": 26,
      "label": "data(label)", "font-size": 11, "color": ink, "text-valign": "center",
      "text-halign": "center", "background-color": card, "border-width": 1, "border-color": line}},
    mark("measure", "round-rectangle", "--accent-soft", "--accent"),
    mark("attribute", "cut-rectangle", "--ok-soft", "--ok"),
    mark("nokind", "barrel", "--surface", "--muted"),
    mark("column", "rectangle", "--hair-2", "--muted"),
    mark("parameter", "tag", "--surface-2", "--ink"),
    {selector: "node.hidden", style: {"border-style": "dashed"}},
    {selector: "node.single", style: {"border-color": warn, "border-width": 2.5}},
    {selector: "node.column", style: {"color": muted, "font-family": "monospace"}},
    {selector: "node.parameter", style: {"color": muted}},
    {selector: "edge", style: {"width": 1, "line-color": line, "curve-style": "bezier",
      "target-arrow-shape": "triangle", "target-arrow-color": line, "arrow-scale": 0.8}},
    {selector: ".faded", style: {"opacity": 0.18}},
    {selector: "node.focus", style: {"background-color": accent, "color": card}},
    {selector: "edge.lit", style: {"line-color": accent, "target-arrow-color": accent, "width": 2}}
  ];
}

/* `total` counts what the chips show; `off`, what they hide. */
function graphNote(total, tree, target, drawn, off){
  var hid = off ? " ("+off+" more switched off by the type chips)" : "";
  return total > FORMULA_GRAPH_CAP ?
    "This Model has "+total+" formulas, columns and parameters"+hid+", too many to draw at once: showing the lineage of "+
    useLabel(tree, target)+(drawn ? " ("+drawn+" of them)" : "")+
    ". Pick another from the search box or by clicking a node." :
    total+" formulas, columns and parameters"+hid+". Click a node to see its definition and its lineage.";
}

/* Where a Model too big to draw whole opens: the root whose lineage is the largest that
   still fits under the cap, or, when none does, the smallest (a click draws any other). */
function graphStart(tree){
  var best = null, size = -1, smallest = null, least = Infinity;
  tree.r.forEach(function(i){
    var n = Object.keys(graphShownIds(tree, graphLineage(tree, [0, i]))).length;
    if(n <= FORMULA_GRAPH_CAP && n > size){ size = n; best = i; }
    if(n < least){ least = n; smallest = i; }
  });
  return [0, best !== null ? best : smallest];
}

/* Lay out the graph: dagre for the nodes joined by an edge, and the nodes left with
   none (a type switched off can strand most of them) in a grid beside that part, its
   columns chosen so the whole is about the canvas's shape. Without the grid dagre
   stacks them in one tall column, most of it off screen. */
function graphArrange(cy){
  var lone = cy.nodes().filter(function(n){ return n.degree(false) === 0; });
  var linked = cy.elements().not(lone);
  if(linked.length) linked.layout({name: "dagre", rankDir: "LR", nodeSep: 10, rankSep: 70, edgeSep: 6}).run();
  if(!lone.length) return;
  var gap = 40, cellH = 36, cellW = 0;
  lone.forEach(function(n){ cellW = Math.max(cellW, n.data("w") + 16); });
  var bb = linked.length ? linked.boundingBox() : {x1: 0, y1: 0, x2: -gap, w: 0, h: 0};
  var aspect = (cy.width() && cy.height()) ? cy.width() / cy.height() : 1.6;
  var best = 1, bestScore = Infinity;
  for(var cols = 1; cols <= lone.length; cols++){
    var rows = Math.ceil(lone.length / cols);
    var w = bb.w + (bb.w ? gap : 0) + cols * cellW, h = Math.max(bb.h, rows * cellH);
    var score = Math.abs(Math.log(w / h / aspect));
    if(score < bestScore){ bestScore = score; best = cols; }
  }
  var x0 = bb.x2 + gap + cellW / 2, y0 = bb.y1 + cellH / 2;
  lone.forEach(function(n, i){
    n.position({x: x0 + (i % best) * cellW, y: y0 + Math.floor(i / best) * cellH});
  });
}

/* The graph's header: the Model, the note on what is drawn and the way back to the tree.
   The filter bar, with the search box, goes in below (buildFormulaGraph). */
function graphHeader(guid){
  var hdr = el("div","ftree-header");
  hdr.innerHTML = '<div class="model-title">'+esc(findModelName(guid))+'</div>'+
    '<div class="ftree-sub fgraph-sub"></div>'+
    '<div class="header-actions">'+
    '<a class="erd-btn fgraph-mode" href="#formulas/'+esc(guid)+'">Tree</a></div>';
  return hdr;
}

/* The view may be built before its container is shown (the router shows it after, in
   the same turn), when Cytoscape reads a size of nothing: measure and fit once this
   turn is over, then bring the selected node into view with `panTo`. */
function graphFit(cy, panTo){
  setTimeout(function(){
    if(!cy || cy.destroyed()) return;  /* the view was rebuilt before this frame */
    cy.stop(true);  /* an animation begun while hidden ends on a pan worked out for no size */
    cy.resize();
    cy.fit(undefined, 24);
    if(cy.zoom() > FORMULA_GRAPH_MAX_FIT){ cy.zoom(FORMULA_GRAPH_MAX_FIT); cy.center(); }
    if(cy.zoom() < FORMULA_GRAPH_MIN_ZOOM && cy.elements().length){  /* readable labels over seeing it all */
      var bb = cy.elements().boundingBox();
      cy.zoom(FORMULA_GRAPH_MIN_ZOOM);
      cy.pan({x: 24 - bb.x1 * FORMULA_GRAPH_MIN_ZOOM,
              y: cy.container().clientHeight / 2 - (bb.y1 + bb.y2) / 2 * FORMULA_GRAPH_MIN_ZOOM});
    }
    var sel = cy.$(".focus");
    if(sel.length) cy.pan(panTo(sel));
  }, 0);
}

/* The pan that puts `n` in the middle of the canvas's visible part: on a narrow screen
   the definition is a sheet fixed over the foot of the page (styles.css), and a node
   centred in the whole canvas would sit under it. */
function graphPanTo(cy, box, panel, n){
  var w = cy.width(), h = cy.height(), pos = n.position(), z = cy.zoom();
  if(getComputedStyle(panel).position === "fixed" && !panel.classList.contains("fdetail-empty")){
    var sheet = panel.getBoundingClientRect().top, rect = box.getBoundingClientRect();
    if(sheet - rect.top < FORMULA_GRAPH_MIN_VISIBLE){
      /* too little of the canvas above the sheet: scroll it up under the top bar */
      var bar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 0;
      window.scrollBy(0, rect.top - bar - 8);
      rect = box.getBoundingClientRect();
    }
    var under = rect.bottom - sheet;
    if(under > 0) h = Math.max(40, h - under);
  }
  return {x: w / 2 - pos.x * z, y: h / 2 - pos.y * z};
}

/* The canvas and the definition panel beside it. */
function graphLayout(){
  var layout = el("div","ftree-layout"), box = el("div","fgraph");
  box.tabIndex = -1;
  box.setAttribute("role","img");
  box.setAttribute("aria-label","Formula lineage graph; the tree shows the same data and is keyboard-reachable");
  var panel = el("aside","fdetail fdetail-empty");
  panel.setAttribute("aria-label","Definition");
  panel.setAttribute("aria-live","polite");
  layout.appendChild(box);
  layout.appendChild(panel);
  return {layout: layout, box: box, panel: panel};
}

function buildFormulaGraph(c, guid, tree){
  if(!loadGraphLibraries()){
    c.innerHTML += '<div class="view-placeholder"><div class="ph-icon">ƒ</div><div class="ph-text">'+
      'The graph could not be drawn</div><div class="ph-sub">Its libraries did not load: use the tree.</div></div>';
    return;
  }
  var hdr = graphHeader(guid), bar = ftypeBar(tree, retype, true);
  hdr.appendChild(bar);
  c.appendChild(hdr);
  var results = el("div","ftree-results");
  c.appendChild(results);
  var parts = graphLayout(), layout = parts.layout, box = parts.box, panel = parts.panel;
  var EMPTY = '<div class="fdetail-none">Click a node to see its definition, what it uses and what uses it.</div>';
  panel.innerHTML = EMPTY;
  c.appendChild(layout);
  /* `shown`: the lineage drawn past the cap (null: the whole graph); `total` and `off`:
     the nodes the chips show and hide; `partial`: whether the shown ones pass the cap */
  var cy = null, shown = null, total = 0, off = 0, partial = false;
  function count(){
    total = Object.keys(graphShownIds(tree)).length;
    off = Object.keys(graphNodeIds(tree)).length - total;
    partial = total > FORMULA_GRAPH_CAP;
  }
  function panTo(n){ return graphPanTo(cy, box, panel, n); }
  function draw(keep){
    if(cy) cy.destroy();
    cy = c._cy = window.cytoscape({container: box, elements: graphElements(tree, graphShownIds(tree, keep)),
      style: graphStyle(), minZoom: 0.05, maxZoom: 3, layout: {name: "preset"}});
    graphArrange(cy);
    cy.on("tap", "node", function(e){
      box.focus({preventScroll: true});  /* so Escape reaches the view, not <body> */
      view.select(e.target.data("use"));
    });
    cy.on("tap", function(e){ if(e.target === cy) clearHighlight(); });
    /* a click or a drag on the empty canvas leaves focus on <body>: keep Escape working */
    cy.on("tapend", function(){ box.focus({preventScroll: true}); });
    graphFit(cy, panTo);
  }
  function setSub(target){
    $(".fgraph-sub", hdr).textContent = graphNote(total, tree, target, cy.nodes().length, off);
  }
  function clearHighlight(){
    if(cy) cy.elements().removeClass("faded focus lit");
  }
  /* `animate`: glide to the node; otherwise (a redraw, or a view not yet shown)
     graphFit centres it once the canvas has a size. False when the node is not drawn
     (its type is switched off). */
  function highlight(id, animate){
    var n = cy.getElementById(id);
    clearHighlight();
    if(!n.length) return false;
    var reach = n.predecessors().union(n.successors()).union(n);
    cy.elements().addClass("faded");
    reach.removeClass("faded");
    reach.edges().addClass("lit");
    n.addClass("focus");
    if(animate) cy.animate({pan: panTo(n), duration: 200});
    else graphFit(cy, panTo);
    return true;
  }
  var view = tree._view = {
    select: function(target, row, focusPanel){
      tree._selected = target;
      panel.innerHTML = detailHtml(tree, target);
      panel.classList.remove("fdetail-empty");
      layout.classList.add("ftree-has-detail");
      var redrawn = false, lineage = partial && graphLineage(tree, target);
      /* redraw unless the whole lineage is drawn: then what is drawn upstream and
         downstream of the node is exactly its lineage, and nothing else */
      if(partial && !(shown && Object.keys(lineage).every(function(k){ return shown[k]; }))){
        shown = lineage;
        draw(shown);
        redrawn = true;
      }
      setSub(target);
      cy.resize();
      bar._note(tree, target, highlight(graphNodeId(target), !redrawn && box.offsetParent !== null));
      if(focusPanel) $(".fdetail-title", panel).focus();
    }
  };
  /* a chip flipped: count again, draw what is left (a lineage again if it passes the
     cap) and light the selection, if it is still drawn */
  function retype(){
    count();
    var target = tree._selected || (partial ? graphStart(tree) : null);
    shown = partial ? graphLineage(tree, target) : null;
    draw(shown);
    setSub(target || [0, tree.r[0]]);
    if(tree._selected) bar._note(tree, target, highlight(graphNodeId(target), false));
    results.innerHTML = searchResultsHtml(tree, $(".ftree-search", hdr).value);
  }
  function closePanel(){
    var focusLost = panel.contains(document.activeElement);
    panel.innerHTML = EMPTY;
    panel.classList.add("fdetail-empty");
    layout.classList.remove("ftree-has-detail");
    clearHighlight();
    tree._selected = null;
    bar._note(tree, null);
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
    /* the results move the canvas, and Cytoscape keeps its last idea of where the
       canvas is: without this a click lands on the node a row away */
    if(cy) cy.resize();
  });
  count();
  var start = tree._selected || (partial ? graphStart(tree) : null);
  if(partial) shown = graphLineage(tree, start);
  draw(shown);
  setSub(start || [0, tree.r[0]]);
  if(tree._selected) view.select(tree._selected);
}
