/* ── The Usage view's quadrant (views/usage.js): one dot per Model shown in its table ──
   Inline SVG, no library. x is the days since the Model's last query on a log scale, with
   the idle days (H17's) as a dashed vertical line; a Model never queried sits in a band of
   its own at the right, and one not judged (too new, or a history too short to say) in a
   grey band beyond it. y is the Model's dependents, 0 in a band of its own at the foot,
   1 and more on a log scale above. The table is the source of truth: the chart draws the
   rows the table shows, and a click on a dot selects that row. Dots carry `data-guid` and
   `data-quadrant` ("active", "retire", "check" or "unjudged") and a <title> to hover. */
var USAGE_STATUS = {
  active:     {label: "Active",        color: "#2E8B62"},
  idle:       {label: "Idle",          color: "#C98A0B"},
  never:      {label: "Never queried", color: "#B0302A"},
  too_new:    {label: "Too new",       color: "#1E6FA8"},
  not_judged: {label: "Not judged",    color: "#8A939E"}
};
var USAGE_STATUS_ORDER = ["active", "idle", "never", "too_new", "not_judged"];
var UQ = {w: 760, h: 350, l: 52, r: 12, t: 34, b: 44, zero: 60};

/* Which quadrant a row falls in. Active stays active. Idle or never queried: "check"
   with a dependent visible (at least that many, whether or not read in full), "retire"
   with none and the dependents read in full, else "unjudged" — none visible but not read
   in full is undecidable, never the retire zone. Too new or not judged: "unjudged". */
function usageQuadrant(r){
  if(r.status === "active") return "active";
  if(r.status === "idle" || r.status === "never"){
    if(r.deps) return "check";
    return r.complete === false ? "unjudged" : "retire";
  }
  return "unjudged";
}

/* The x regions: days [l, xd], the never band [xd, xn], the not-judged band [xn, w-r]. */
function usageRegions(){
  var right = UQ.w - UQ.r, span = right - UQ.l;
  return {x0: UQ.l, xd: UQ.l + span * 0.72, xn: UQ.l + span * 0.86, x1: right};
}

function usageXScale(rows, idleDays){
  var g = usageRegions(), max = Math.max(idleDays * 2, 365);
  rows.forEach(function(r){ if(typeof r.days === "number") max = Math.max(max, r.days); });
  var top = Math.log(max + 1);
  return function(d){ return g.x0 + 6 + Math.log(Math.max(0, d) + 1) / top * (g.xd - g.x0 - 12); };
}

function usageYScale(rows){
  var max = 10;
  rows.forEach(function(r){ max = Math.max(max, r.deps || 0); });
  var top = Math.log(max), y1 = UQ.h - UQ.b - UQ.zero - 6, y0 = UQ.t + 6;
  return function(n){
    if(!n) return UQ.h - UQ.b - 20;  /* the band's foot: its top holds the quadrant label */
    return y1 - Math.log(n) / top * (y1 - y0);
  };
}

/* A small stable offset for a guid, in [-1, 1]: spreads dots that share a place. */
function usageJitter(guid, salt){
  var h = salt || 7;
  for(var i = 0; i < guid.length; i++) h = (h * 31 + guid.charCodeAt(i)) % 100003;
  return (h % 2001) / 1000 - 1;
}

function usageDotTitle(r){
  var st = USAGE_STATUS[r.status] || USAGE_STATUS.not_judged;
  var last = usageLastUsed(r.cm).text || "";
  return r.name+" — "+st.label+"\nLast used: "+last+"\n"+
    usagePlural(r.queries, "query", "queries")+" by "+usagePlural(r.users, "user")+
    " ("+usageSpanLabel()+")\n"+(r.complete === false
      ? r.deps+"+ dependents ("+usageNotReadText(r)+")" : usagePlural(r.deps, "dependent"));
}

function usageDotXY(r, sx, sy){
  var g = usageRegions(), q = usageQuadrant(r), y = sy(r.deps);
  y += r.deps ? usageJitter(r.guid, 3) * 4 : usageJitter(r.guid, 3) * 12;
  /* none visible and not read in full: mid-height in the grey band, never at a known 0 */
  if(q === "unjudged" && !r.deps && r.complete === false)
    y = (UQ.t + UQ.h - UQ.b - UQ.zero) / 2 + usageJitter(r.guid, 3) * 12;
  var x;
  if(q === "unjudged") x = (g.xn + g.x1) / 2 + usageJitter(r.guid) * ((g.x1 - g.xn) / 2 - 8);
  else if(r.status === "never") x = (g.xd + g.xn) / 2 + usageJitter(r.guid) * ((g.xn - g.xd) / 2 - 8);
  else x = sx(r.days || 0) + usageJitter(r.guid) * 3;
  return [x, y];
}

/* The grid, bands, idle line, axes and quadrant labels, as SVG markup. */
function usageQuadrantFrame(rows, idleDays, sx){
  var g = usageRegions(), top = UQ.t, foot = UQ.h - UQ.b, split = foot - UQ.zero;
  var lx = sx(idleDays), out = "";
  out += '<rect class="uq-retire" x="'+lx+'" y="'+split+'" width="'+(g.xn - lx)+'" height="'+UQ.zero+'"/>';
  out += '<rect class="uq-band" x="'+g.xn+'" y="'+top+'" width="'+(g.x1 - g.xn)+'" height="'+(foot - top)+'"/>';
  out += '<line class="uq-axis" x1="'+g.x0+'" y1="'+foot+'" x2="'+g.x1+'" y2="'+foot+'"/>';
  out += '<line class="uq-axis" x1="'+g.x0+'" y1="'+top+'" x2="'+g.x0+'" y2="'+foot+'"/>';
  out += '<line class="uq-split" x1="'+g.x0+'" y1="'+split+'" x2="'+g.xn+'" y2="'+split+'"/>';
  [g.xd, g.xn].forEach(function(x){
    out += '<line class="uq-sep" x1="'+x+'" y1="'+top+'" x2="'+x+'" y2="'+foot+'"/>';
  });
  out += '<line class="usage-idle-line" x1="'+lx+'" y1="'+(top - 6)+'" x2="'+lx+'" y2="'+foot+'"/>';
  out += usageText(lx + 4, top - 8, idleDays+" days (idle)", "uq-idle-lbl", "start");
  out += usageText(g.x0 + 6, top + 12, "Active", "uq-q", "start");
  out += usageText(lx + 6, top + 12, "Idle, has dependents — check first", "uq-q", "start");
  out += usageText(lx + 6, split + 14, "Idle, no dependents — retire candidates", "uq-q", "start");
  out += usageText((g.xd + g.xn) / 2, top - 8, "Never queried", "uq-band-lbl", "middle");
  out += usageText((g.xn + g.x1) / 2, top - 8, "Not judged", "uq-band-lbl", "middle");
  [0, 7, 30, 90, 180, 365, 730, 1460].forEach(function(d){
    var x = sx(d);
    if(x > g.xd - 4 || (d === idleDays)) return;
    out += '<line class="uq-tick" x1="'+x+'" y1="'+foot+'" x2="'+x+'" y2="'+(foot + 4)+'"/>'+
      usageText(x, foot + 16, d === 0 ? "today" : d+"d", "uq-tick-lbl", "middle");
  });
  out += usageText((g.x0 + g.xd) / 2, foot + 34, "Days since last query (log scale)", "uq-axis-lbl", "middle");
  return out + usageYTicks(rows);
}

function usageYTicks(rows){
  var sy = usageYScale(rows), max = 0, out = "";
  rows.forEach(function(r){ max = Math.max(max, r.deps || 0); });
  [0, 1, 10, 100, 1000].forEach(function(n){
    if(n > Math.max(10, max)) return;
    out += usageText(UQ.l - 6, sy(n) + 4, String(n), "uq-tick-lbl", "end");
  });
  return out + '<text class="uq-axis-lbl" transform="translate(13,'+((UQ.t + UQ.h - UQ.b) / 2)+
    ') rotate(-90)" text-anchor="middle">Dependents</text>';
}

function usageText(x, y, text, cls, anchor){
  return '<text class="'+cls+'" x="'+x+'" y="'+y+'" text-anchor="'+anchor+'">'+esc(text)+'</text>';
}

/* The chart for `rows` (the table's shown rows), `selected` {guid: true}. */
function usageQuadrantSvg(rows, idleDays, selected){
  var sx = usageXScale(rows, idleDays), sy = usageYScale(rows), counts = {};
  var dots = rows.map(function(r){
    var q = usageQuadrant(r), xy = usageDotXY(r, sx, sy);
    counts[q] = (counts[q] || 0) + 1;
    var st = USAGE_STATUS[r.status] || USAGE_STATUS.not_judged;
    var partial = r.complete === false;  /* hollow, dashed: a lower bound, not a count */
    return '<circle class="usage-dot'+(partial ? ' partial' : '')+(selected[r.guid] ? ' selected' : '')+
      '" data-guid="'+esc(r.guid)+'" data-quadrant="'+q+'" cx="'+xy[0].toFixed(1)+'" cy="'+
      xy[1].toFixed(1)+'" r="5" fill="'+st.color+'"'+(partial ? ' stroke="'+st.color+'"' : '')+
      '><title>'+esc(usageDotTitle(r))+'</title></circle>';
  }).join("");
  var label = "Models by days since their last query and their dependents: "+
    (counts.retire || 0)+" retire candidates, "+(counts.check || 0)+" idle with dependents, "+
    (counts.active || 0)+" active, "+(counts.unjudged || 0)+" not judged. The table below lists each one.";
  return '<svg class="usage-quadrant" viewBox="0 0 '+UQ.w+' '+UQ.h+'" role="img" aria-label="'+
    esc(label)+'">'+usageQuadrantFrame(rows, idleDays, sx)+'<g class="uq-dots">'+dots+'</g></svg>';
}

/* The legend: each status with its colour, its label and how many Models it has. */
function usageLegendHtml(rows){
  return '<div class="usage-legend" aria-hidden="true">'+USAGE_STATUS_ORDER.map(function(s){
    var n = rows.filter(function(r){ return r.status === s; }).length;
    return '<span class="usage-legend-item"><span class="usage-swatch" style="background:'+
      USAGE_STATUS[s].color+'"></span>'+esc(USAGE_STATUS[s].label)+' '+n+'</span>';
  }).join("")+'</div>';
}
