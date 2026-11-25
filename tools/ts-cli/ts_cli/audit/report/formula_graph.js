/* ── Formulas: the graph mode (route #formulas/<guid>/graph) ──
   One Model's formula lineage drawn left to right: table columns and parameters on the
   left, the formulas built on them to the right, each formula after everything it uses.
   Cytoscape.js draws it and dagre lays it out (vendor/README.md); both travel in the
   data (`D.V`, report.py `render_report`) only when some Model has a formula
   (`has_formulas`), and run the first time a graph opens. Clicking a node opens the same
   definition panel as the tree (views/formulas.js) and highlights everything upstream
   and downstream of it; a link in the panel moves the graph to that node. A Model past
   FORMULA_GRAPH_CAP nodes is drawn one lineage at a time: the selected node, what it
   uses and what depends on it. The type chips (formula_types.js) hide a type's nodes and
   their edges and lay the rest out again; the cap counts only what the chips leave shown,
   so switching columns off can draw a large Model whole. The canvas is not
   keyboard-reachable; the tree is the accessible form of the same data, one click away. */
var FORMULA_GRAPH_CAP = 300;  /* nodes drawn whole; beyond it, one lineage at a time */
var FORMULA_GRAPH_MAX_FIT = 1.2;   /* a small graph is not blown up to fill the canvas */
var FORMULA_GRAPH_MIN_VISIBLE = 120;  /* px of canvas above a narrow screen's sheet */

/* The graph libraries are in this report, and the Model has a formula. */
function graphAvailable(tree){
  return !!(D.V && tree && tree.n.length);
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

/* Where a Model too big to draw whole opens: the root of a type the chips show whose
   lineage is the largest that still fits under the cap, or, when none does, the
   smallest (a click draws any other); with no such root, a formula of a shown type,
   then a shown column or parameter, so the note never names a node that is not drawn. */
function graphStart(tree){
  var best = null, size = -1, smallest = null, least = Infinity;
  tree.r.filter(function(i){ return useShown(tree, [0, i]); }).forEach(function(i){
    var n = Object.keys(graphShownIds(tree, graphLineage(tree, [0, i]))).length;
    if(n <= FORMULA_GRAPH_CAP && n > size){ size = n; best = i; }
    if(n < least){ least = n; smallest = i; }
  });
  if(best !== null || smallest !== null) return [0, best !== null ? best : smallest];
  for(var i = 0; i < tree.n.length; i++) if(useShown(tree, [0, i])) return [0, i];
  for(i = 0; i < tree.n.length; i++){
    var u = tree.n[i].u.filter(function(x){ return x[0] !== 0 && useShown(tree, x); })[0];
    if(u) return u;
  }
  return [0, tree.r[0]];
}

/* dagre puts every node of a rank in one column: many measures over one amount column
   make one rank far taller than the canvas. Wrap each rank of `part` into as many
   columns as bring the part nearest the canvas's shape (`aspect`), in dagre's order,
   ranks still left to right. A part whose tallest rank is short is left as it is. */
function graphWrapRanks(part, aspect){
  var ROW = 36, RANK_GAP = 70, COL_GAP = 16, ranks = {};
  part.nodes().forEach(function(n){ var k = Math.round(n.position("x")); (ranks[k] = ranks[k] || []).push(n); });
  var keys = Object.keys(ranks).map(Number).sort(function(a, b){ return a - b; });
  var tallest = Math.max.apply(null, keys.map(function(k){ return ranks[k].length; }));
  if(tallest < 8) return;
  var colW = {};
  keys.forEach(function(k){
    colW[k] = Math.max.apply(null, ranks[k].map(function(n){ return n.data("w"); })) + COL_GAP;
  });
  function shape(rows){
    var w = RANK_GAP * (keys.length - 1);
    keys.forEach(function(k){ w += Math.ceil(ranks[k].length / rows) * colW[k]; });
    return Math.abs(Math.log(w / (Math.min(tallest, rows) * ROW) / aspect));
  }
  var best = tallest, score = shape(tallest);
  for(var rows = 4; rows < tallest; rows++){ var d = shape(rows); if(d < score){ score = d; best = rows; } }
  if(best >= tallest) return;
  var x = part.boundingBox().x1, top = part.boundingBox().y1;
  keys.forEach(function(k){
    var list = ranks[k].sort(function(a, b){ return a.position("y") - b.position("y"); });
    var high = Math.min(list.length, best) * ROW, off = (best * ROW - high) / 2;
    list.forEach(function(n, i){
      n.position({x: x + Math.floor(i / best) * colW[k] + colW[k] / 2, y: top + off + (i % best) * ROW + ROW / 2});
    });
    x += Math.ceil(list.length / best) * colW[k] + RANK_GAP;
  });
}

/* Lay out the graph: dagre for each connected part on its own, its tall ranks wrapped
   (graphWrapRanks), then the parts, the largest first and lone nodes last, packed in
   rows about the canvas's shape. dagre over the whole graph stacks unconnected parts in
   one tall column (a type switched off can strand most nodes), most of it off screen. */
function graphArrange(cy){
  var gapX = 40, gapY = 14, aspect = (cy.width() && cy.height()) ? cy.width() / cy.height() : 1.6;
  var parts = cy.elements().components().map(function(part){
    if(part.edges().length){
      part.layout({name: "dagre", rankDir: "LR", nodeSep: 10, rankSep: 70, edgeSep: 6}).run();
      graphWrapRanks(part, aspect);
    }
    var bb = part.boundingBox();
    return {part: part, bb: bb, n: part.nodes().length};
  }).sort(function(a, b){ return b.n - a.n || b.bb.h - a.bb.h; });
  if(parts.length < 2) return;
  var area = 0, widest = 0;
  parts.forEach(function(p){ area += (p.bb.w + gapX) * (p.bb.h + gapY); widest = Math.max(widest, p.bb.w); });
  var rowW = Math.max(widest, Math.sqrt(area * aspect)), x = 0, y = 0, rowH = 0;
  parts.forEach(function(p){
    if(x > 0 && x + p.bb.w > rowW){ x = 0; y += rowH + gapY; rowH = 0; }
    var dx = x - p.bb.x1, dy = y - p.bb.y1;
    p.part.nodes().positions(function(node){ var q = node.position(); return {x: q.x + dx, y: q.y + dy}; });
    x += p.bb.w + gapX;
    rowH = Math.max(rowH, p.bb.h);
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
   turn is over. A selected node is then brought into the canvas's visible part with
   `panTo`, which moves nothing when it is already there (it is, unless a narrow
   screen's sheet covers it), so the fit's every-node-in-view holds. */
function graphFit(cy, panTo){
  setTimeout(function(){
    if(!cy || cy.destroyed()) return;  /* the view was rebuilt before this frame */
    cy.stop(true);  /* an animation begun while hidden ends on a pan worked out for no size */
    cy.resize();
    cy.fit(undefined, 24);
    /* every node in view, however small that makes it: the layout (graphArrange) keeps
       common shapes legible, and a shape it cannot (a very long chain) still opens whole */
    if(cy.zoom() > FORMULA_GRAPH_MAX_FIT){ cy.zoom(FORMULA_GRAPH_MAX_FIT); cy.center(); }
    var sel = cy.$(".focus");
    if(sel.length) cy.pan(panTo(sel));
  }, 0);
}

/* The smallest pan that brings `n` into the canvas's visible part, or the current pan
   when it is in it already: on a narrow screen the definition is a sheet fixed over the
   foot of the page (styles.css), which hides the foot of the canvas. Moving no further
   keeps the rest of a fitted graph in view. */
function graphPanTo(cy, box, panel, n){
  var w = cy.width(), h = cy.height(), pan = cy.pan(), M = 12;
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
  var b = n.renderedBoundingBox();
  function shift(lo, hi, size){  /* how far to move [lo, hi] into [M, size - M] */
    if(hi - lo > size - 2 * M) return (size - lo - hi) / 2;  /* too big: centre it */
    return lo < M ? M - lo : hi > size - M ? size - M - hi : 0;
  }
  return {x: pan.x + shift(b.x1, b.x2, w), y: pan.y + shift(b.y1, b.y2, h)};
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
  var hdr = graphHeader(guid), bar = ftypeBar(tree, retype, true, function(){ return cy ? cy.nodes().length : 0; });
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
      style: graphStyle(), minZoom: 0.005, maxZoom: 3, layout: {name: "preset"}});  /* the fit is never capped */
    graphArrange(cy);
    cy.on("tap", "node", function(e){
      box.focus({preventScroll: true});  /* so Escape reaches the view, not <body> */
      view.select(e.target.data("use"));
    });
    cy.on("tap", function(e){ if(e.target === cy) clearHighlight(); });
    /* a click or a drag on the empty canvas leaves focus on <body>: keep Escape working */
    cy.on("tapend", function(){ box.focus({preventScroll: true}); });
    graphFit(cy, panTo);
    bar._recount();  /* the bar counts what is drawn */
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
