/* ── The filter bar: one pattern for the Formulas view, the Data Cache view and the ERD ──
   ONE SPEC, TWO COPIES. The ERD (agents/shared/erd/renderer.js, markup in render.py)
   runs in its own page, standalone or in the report's ERD frame, so it cannot call this
   file; it builds the same markup with the same classes and behaviour, and the CSS
   between the `filter-bar:begin` and `filter-bar:end` markers is byte-identical in
   styles.css and agents/shared/erd/renderer.css (tests/test_audit_filter_bar.py checks
   both). Change one, change the other.
   The markup: <div class="fbar" role="group" aria-label="…">, a <span class="fbar-label">
   reading "Show", an "All" chip (<button class="fbar-chip fbar-all" data-f="all">), then
   one toggle chip per kind (<button class="fbar-chip" data-f="<id>" aria-pressed>, its
   label then <span class="fbar-count">), then the search box (<input class="fbar-search"
   type="search">) and the shown count (<span class="fbar-total">), always in that order.
   The behaviour: every chip starts on; a click flips one chip, and switching a chip off
   HIDES everything it covers (an item a switched-off chip covers is hidden, so chips may
   overlap); "All" is pressed exactly when every chip is on, and a click on it switches
   every chip back on. A chip that covers nothing is disabled. Chips are buttons, so Tab
   reaches them and Enter or Space flips them. */

/* `o`: {label (the group's aria-label), chips: [{f, label, count, icon (HTML), title}],
   on: {f: bool} (the state, kept by the caller, changed in place), search: {cls,
   placeholder, aria, value} or none, total: text or none}. `onChange` runs after a chip
   flips; `onSearch(value)` on each keystroke. Returns the bar; bar._total(text) sets the
   shown count, bar._sync() re-reads `on`. */
function filterBar(o, onChange, onSearch){
  var bar = el("div", "fbar");
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", o.label);
  var total = o.chips.reduce(function(n, c){ return n + c.count; }, 0);
  var html = '<span class="fbar-label">Show</span>'+
    '<button type="button" class="fbar-chip fbar-all" data-f="all" aria-pressed="true">All '+
    '<span class="fbar-count">'+total+'</span></button>';
  o.chips.forEach(function(c){
    html += '<button type="button" class="fbar-chip" data-f="'+esc(c.f)+'" aria-pressed="true"'+
      (c.title ? ' title="'+esc(c.title)+'"' : '')+(c.count ? '' : ' disabled')+'>'+
      (c.icon || '')+esc(c.label)+' <span class="fbar-count">'+c.count+'</span></button>';
  });
  if(o.search) html += '<input class="fbar-search'+(o.search.cls ? ' '+o.search.cls : '')+
    '" type="search" placeholder="'+esc(o.search.placeholder)+'" aria-label="'+esc(o.search.aria)+'">';
  html += '<span class="fbar-total"></span>';
  bar.innerHTML = html;
  var live = o.chips.filter(function(c){ return c.count; });
  bar._sync = function(){
    $$(".fbar-chip", bar).forEach(function(b){
      var f = b.getAttribute("data-f");
      var on = f === "all" ? live.every(function(c){ return o.on[c.f]; }) : !!o.on[f];
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  };
  bar._total = function(text){ $(".fbar-total", bar).textContent = text; };
  bar.addEventListener("click", function(e){
    var b = e.target.closest && e.target.closest(".fbar-chip");
    if(!b || b.disabled) return;
    var f = b.getAttribute("data-f");
    if(f === "all") o.chips.forEach(function(c){ o.on[c.f] = true; });
    else o.on[f] = !o.on[f];
    bar._sync();
    onChange();
  });
  if(o.search){
    var input = $(".fbar-search", bar);
    input.value = o.search.value || "";
    input.addEventListener("input", function(){ onSearch(input.value); });
  }
  if(o.total) bar._total(o.total);
  bar._sync();
  return bar;
}
