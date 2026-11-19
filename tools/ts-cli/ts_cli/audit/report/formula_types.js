/* ── Formula types: the filter chips and the legend of the Formulas tree and graph ──
   A Model's formula lineage holds four types: table columns, parameters, and formulas,
   each a MEASURE or an ATTRIBUTE (`k` on a tree node). A formula no column surfaces has
   no stated kind: it is filtered with Attribute formulas (the chip's tooltip says how
   many) but drawn with a mark of its own, so the page never claims a kind the TML does
   not state. Each type has one mark, a shape filled and outlined in its colour, used in
   the tree's rows, the graph's nodes (formula_graph.js graphStyle), the chips and the
   legend; the shape carries the type without the colour.
   The chips are the shared filter bar (filter_bar.js), and their state is shared by every
   Model and both modes for the session, in memory only.
   In the graph a switched-off type is hidden, nodes and edges, and the rest laid out
   again. In the tree a row of a switched-off type is hidden, unless something shown is
   under it: a formula row is then kept, dimmed, since the tree reaches a row only
   through the formulas above it. Search results leave out switched-off types and count
   them. Picking something hidden (a link in the definition) still opens its definition,
   and a note under the chips says it is switched off, with a button to show its type. */
var FTYPES = [["column", "Columns"], ["parameter", "Parameters"],
  ["measure", "Measure formulas"], ["attribute", "Attribute formulas"]];
var FTYPE_NAMES = {column: "Table column", parameter: "Parameter", measure: "Measure formula",
  attribute: "Attribute formula", nokind: "Formula of no stated kind (with Attribute formulas)"};
var FTYPE_SHAPES = {
  column: '<rect x="1" y="1" width="14" height="10"/>',
  parameter: '<polygon points="1,1 11,1 15,6 11,11 1,11"/>',
  measure: '<rect x="1" y="1" width="14" height="10" rx="3.5"/>',
  attribute: '<polygon points="4,1 12,1 15,4 15,8 12,11 4,11 1,8 1,4"/>',
  nokind: '<path d="M3.5,1 H12.5 Q16,6 12.5,11 H3.5 Q0,6 3.5,1 Z"/>'};
var _ftypeShown = {column: true, parameter: true, measure: true, attribute: true};

/* A formula node's mark: measure, attribute, or nokind. */
function nodeMark(node){
  return node.k === "MEASURE" ? "measure" : node.k === "ATTRIBUTE" ? "attribute" : "nokind";
}

/* The chip a use (the use encoding) is filtered by. */
function useFtype(tree, use){
  if(use[0] === 1) return "column";
  if(use[0] === 2) return "parameter";
  return nodeMark(tree.n[use[1]]) === "measure" ? "measure" : "attribute";
}

function useShown(tree, use){ return !!_ftypeShown[useFtype(tree, use)]; }

function ftypeKey(){ return FTYPES.map(function(t){ return _ftypeShown[t[0]] ? 1 : 0; }).join(""); }

/* The mark as an inline picture; `labelled` names it for a screen reader (in a row,
   where no text says the type), otherwise it is decoration beside its own text. */
function ftypeIcon(mark, labelled){
  return '<svg class="ftype-ico ftype-'+mark+'" viewBox="0 0 16 12" width="16" height="12" '+
    (labelled ? 'role="img" aria-label="'+FTYPE_NAMES[mark]+'"' : 'aria-hidden="true" focusable="false"')+
    '>'+FTYPE_SHAPES[mark]+'</svg>';
}

/* How many of each type the Model's lineage holds, plus `nokind`. */
function ftypeCounts(tree){
  var n = {column: 0, parameter: 0, measure: 0, attribute: 0, nokind: 0}, seen = {};
  tree.n.forEach(function(node, i){
    n[useFtype(tree, [0, i])]++;
    if(nodeMark(node) === "nokind") n.nokind++;
    node.u.forEach(function(u){
      if(u[0] !== 0 && !seen[useKey(u)]){ seen[useKey(u)] = true; n[useFtype(tree, u)]++; }
    });
  });
  return n;
}

function ftypeLegendHtml(counts, graph){
  var marks = ["column", "parameter", "measure", "attribute"].concat(counts.nokind ? ["nokind"] : []);
  var html = marks.map(function(m){
    return '<span class="ftype-key">'+ftypeIcon(m)+esc(FTYPE_NAMES[m])+'</span>'; }).join("");
  html += graph ? '<span class="ftype-key"><span class="ftype-swatch ftype-sw-hidden"></span>Dashed: hidden</span>'+
    '<span class="ftype-key"><span class="ftype-swatch ftype-sw-single"></span>Amber: hidden, used once (H16)</span>'
    : '<span class="ftype-key"><span class="ftype-swatch ftype-sw-dim"></span>Faded: switched off, kept as the way to a shown formula under it</span>';
  return '<div class="ftype-legend" role="note" aria-label="Legend">'+html+'</div>';
}

/* The filter bar (filter_bar.js: "Show", All, the four type chips, search and the shown
   count), the legend and the note, as one element. `onChange` runs after a chip flips;
   the search box is the view's own (class ftree-search), which wires it.
   `wrap._note(tree, target, visible)` says when `target` is not on screen because its
   type is switched off, or, for a column or parameter, because every formula it sits
   under is (and clears the note otherwise). `shownCount`, when given, counts what the
   view shows (the tree: treeShownCount); without it the graph's count, every item of a
   type switched on, since the graph draws them all. */
function ftypeBar(tree, onChange, graph, shownCount){
  var counts = ftypeCounts(tree), wrap = el("div", "ftype-bar");
  var all = FTYPES.reduce(function(n, t){ return n + counts[t[0]]; }, 0);
  function total(){
    var shown = shownCount ? shownCount() :
      FTYPES.reduce(function(n, t){ return n + (_ftypeShown[t[0]] ? counts[t[0]] : 0); }, 0);
    bar._total(shown+" of "+all+" items shown");
  }
  var bar = filterBar({label: "Show these types", on: _ftypeShown,
    chips: FTYPES.map(function(t){
      return {f: t[0], label: t[1], count: counts[t[0]], icon: ftypeIcon(t[0]),
        title: t[0] === "attribute" && counts.nokind ? "Includes "+counts.nokind+" formula"+
          (counts.nokind === 1 ? "" : "s")+" of no stated kind (no column surfaces it)" : ""};
    }),
    search: {cls: "ftree-search", placeholder: "Find a formula, column or parameter",
             aria: "Find a formula, column or parameter"}},
    function(){ total(); onChange(); }, function(){});
  total();
  wrap.appendChild(bar);
  wrap.insertAdjacentHTML("beforeend", ftypeLegendHtml(counts, graph)+'<div class="ftype-note" role="status"></div>');
  wrap.addEventListener("click", function(e){
    var b = e.target.closest && e.target.closest(".ftype-reveal");
    if(!b) return;
    var types = b.getAttribute("data-ftype").split(",");
    types.forEach(function(type){ _ftypeShown[type] = true; });
    bar._sync();
    total();
    onChange();
    $('.fbar-chip[data-f="'+types[0]+'"]', bar).focus();
  });
  function chipLabel(type){ return FTYPES.filter(function(x){ return x[0] === type; })[0][1]; }
  wrap._note = function(t, target, visible){
    var note = $(".ftype-note", wrap), type = target && useFtype(t, target);
    if(!target || visible){ note.innerHTML = ""; return; }
    if(!_ftypeShown[type]){
      note.innerHTML = esc(useLabel(t, target))+' is not shown: '+esc(chipLabel(type))+' are switched off. '+
        '<button type="button" class="ftype-reveal" data-ftype="'+type+'">Show '+esc(chipLabel(type).toLowerCase())+'</button>';
      return;
    }
    /* a column or parameter of a shown type, every formula it sits under switched off */
    var off = [];
    directUsers(t, target).forEach(function(j){
      var ty = useFtype(t, [0, j]);
      if(!_ftypeShown[ty] && off.indexOf(ty) === -1) off.push(ty);
    });
    if(target[0] === 0 || !off.length){ note.innerHTML = ""; return; }
    var names = off.map(function(ty){ return chipLabel(ty); });
    note.innerHTML = esc(useLabel(t, target))+' is not shown: the formulas it sits under are switched off ('+
      esc(names.join(", "))+'). <button type="button" class="ftype-reveal" data-ftype="'+off.join(",")+'">Show '+
      esc(names.join(" and ").toLowerCase())+'</button>';
  };
  return wrap;
}

/* Per formula index: 2 shown, 1 kept (switched off, but a formula of a shown type is
   under it, so the row stays, faded, as the way down to it), 0 hidden with everything
   under it. A shown column or parameter under a switched-off formula does not keep it:
   switching Measure formulas off must hide the measures, though every one uses a
   column. Worked upward from the shown formulas, so a cycle cannot loop it. */
function treeFtypeStates(tree){
  var reach = {}, queue = [];
  function reached(i){ if(!reach[i]){ reach[i] = true; queue.push(i); } }
  tree.n.forEach(function(node, i){
    if(useShown(tree, [0, i])) directUsers(tree, [0, i]).forEach(reached);
  });
  for(var q = 0; q < queue.length; q++) directUsers(tree, [0, queue[q]]).forEach(reached);
  return tree.n.map(function(node, i){ return useShown(tree, [0, i]) ? 2 : reach[i] ? 1 : 0; });
}

/* treeFtypeStates, worked out once per chip setting. */
function treeStates(tree){
  if(tree._ftKey !== ftypeKey()){ tree._ftStates = treeFtypeStates(tree); tree._ftKey = ftypeKey(); }
  return tree._ftStates;
}

/* How many items the tree shows: the formulas of a shown type, and the columns and
   parameters of a shown type under a formula row the tree shows (a kept, faded row is
   switched off itself, so it is not counted, but what is under it is shown). The tree
   reaches a column only through a formula, so with both formula types off it is 0. */
function treeShownCount(tree){
  var st = treeStates(tree), seen = {}, n = 0;
  tree.n.forEach(function(node, i){
    if(st[i] === 2) n++;
    if(st[i] >= 1) node.u.forEach(function(u){
      if(u[0] !== 0 && useShown(tree, u) && !seen[useKey(u)]){ seen[useKey(u)] = true; n++; }
    });
  });
  return n;
}

/* Why the tree shows nothing, or "" when it shows something. */
function treeEmptyNote(tree, graph){
  if(treeShownCount(tree)) return "";
  if(ftypeKey() === "0000") return "Every type is switched off: switch one back on to see the tree.";
  if(!_ftypeShown.measure && !_ftypeShown.attribute)
    return "Columns and parameters are shown only under a formula: switch a formula type on"+
      (graph ? ", or use the Graph." : ".");
  return "No formula of a type switched on: switch another type on.";
}

/* Hide and fade the built rows under `root` as the chips say. */
function applyTreeFtypes(root, tree){
  var st = treeStates(tree);
  $$("li.ftree-node", root).forEach(function(li){
    var s = st[+li.getAttribute("data-i")];
    li.classList.toggle("ftype-off", s === 0);
    li.classList.toggle("ftree-dimmed", s === 1);
  });
  $$("li.ftree-leaf", root).forEach(function(li){
    var t = li.firstChild && li.firstChild._target;
    li.classList.toggle("ftype-off", !!t && !useShown(tree, t));
  });
}
