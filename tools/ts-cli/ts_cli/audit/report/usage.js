/* ── Usage (corpus.usage and each Model's usage, ts_cli/audit/usage.py) ──
   D.C.us is the reading: {o Org name, oi Org id, pr 1 Primary / 0 another / null not read,
   w window days, at read at, hs/he history's first and last query (epoch seconds), hd whole
   days the history covers before the read, id the idle days H17 judged by, b rows
   dropped for a blank Model ID, g [[guid, queries, users, last query, orgs]] or null,
   each orgs [[Org id, Org name, last query there]] ([] none recorded, null not read; absent
   before 0.224.0), or 1 Orgs read / 0 not read (absent before 0.224.0), os [[Org id, name,
   used Model IDs]] or null}. It is
   null when the run fetched usage and could not read it, and absent when no selected rule
   needed it (or the JSON predates it). Each Model's `us` is {l last query, d days since,
   q queries, u users, n 1 when never queried}. What was not read says "Not read", never
   that a Model is unused. */
var USAGE_NOT_READ = "Not read";

/* "read" (a reading), "not_read" (fetched, but not read) or "absent" (no column, no section). */
function usageState(){
  if(!D.C) return "absent";
  if(D.C.us) return "read";
  if(D.C.us === null && recorded() && collected("usage")) return "not_read";
  return "absent";
}

function usageDate(epoch){
  if(typeof epoch !== "number") return "";
  return new Date(epoch * 1000).toISOString().slice(0, 10);
}

function usageOrgName(){
  var u = D.C && D.C.us;
  if(!u) return "";
  if(u.o) return "the Org ‘"+u.o+"’";
  if(u.oi !== null && u.oi !== undefined) return "the Org with id "+u.oi;
  return "an Org whose name could not be read";
}

function usagePlural(n, word, many){ return n+" "+(n === 1 ? word : (many || word+"s")); }

/* The span the query and user counts cover: the window ("180 days"), or, when the history
   covers fewer days than the window, the history's own span ("since 2026-10-26"). */
function usageHistoryShort(days){
  var u = D.C && D.C.us;
  return !!u && typeof u.hd === "number" && typeof days === "number" && u.hd < days;
}
function usageSpanLabel(){
  var u = D.C.us, w = u.w || 180;
  return usageHistoryShort(w) ? "since "+usageDate(u.hs) : w+" days";
}
function usageSpanPhrase(){
  var u = D.C.us, w = u.w || 180;
  return usageHistoryShort(w) ? "in the "+usagePlural(u.hd, "day")+" the history holds"
                              : "in the last "+w+" days";
}

/* One Model's last use, as {text, title}: "Not read" when usage was fetched and not read,
   "No query" when the history holds none, "<n> days ago" otherwise. */
function usageLastUsed(cm){
  var state = usageState();
  if(state === "not_read") return {text: USAGE_NOT_READ,
    title: "Usage could not be read for this audit, so it is not known whether this Model was queried"};
  var us = cm && cm.us;
  if(state !== "read" || !us) return {text: "", title: ""};
  var counts = usagePlural(us.q, "query", "queries")+" by "+usagePlural(us.u, "user")+" "+usageSpanPhrase();
  if(us.n){
    var start = usageDate(D.C.us.hs);
    return {text: "No query", title: "No query in the usage history"+
      (start ? ", which starts on "+start : "")+" ("+usageOrgName()+")"};
  }
  if(typeof us.d !== "number") return {text: "Unknown",
    title: "The history holds this Model but no query time; "+counts};
  return {text: us.d === 0 ? "Today" : usagePlural(us.d, "day")+" ago",
          title: "Last queried on "+usageDate(us.l)+"; "+counts+" ("+usageOrgName()+")"};
}

/* How many Orgs the usage names (D.C.us.os); 0 when its Orgs were not read. */
function usageOrgCount(){
  var u = D.C && D.C.us;
  return u && u.os ? u.os.length : 0;
}

/* The header line naming whose usage the report shows and when it was read, and a note
   when that is not the Primary Org's usage. Read from the Primary Org with more than one
   Org in it, that is all Orgs; with more than one Org from another Org, it says the
   count the data shows. "" when usage is absent. */
function usageHeaderHtml(){
  var state = usageState();
  if(state === "absent") return "";
  if(state === "not_read") return '<span class="meta-item usage-meta">Usage: <strong>'+
    USAGE_NOT_READ+'</strong></span>';
  var u = D.C.us, n = usageOrgCount(), on = esc(usageDate(u.at));
  var text = n > 1 && u.pr === 1
    ? 'Usage of <strong>all Orgs</strong> ('+n+' in the usage history), read from the Primary Org on '+on
    : n > 1
    ? 'Usage of <strong>'+n+' Orgs</strong>, read from '+esc(usageOrgName())+' on '+on
    : u.pr === 1 && u.or === 0
    ? 'Usage read from <strong>the Primary Org</strong> on '+on+'; which Orgs it covers was not read'
    : 'Usage of <strong>'+esc(usageOrgName())+'</strong>, read on '+on;
  return '<span class="meta-item usage-meta">'+text+'</span>';
}

function usageOrgNoteHtml(){
  if(usageState() !== "read" || D.C.us.pr === 1 || usageOrgCount() > 1) return "";
  var text = D.C.us.pr === 0
    ? "Usage counts the queries in "+usageOrgName()+" only: this audit ran outside the "+
      "Primary Org, so queries made in other Orgs are not counted."
    : "The Org this usage belongs to could not be read: it is the usage of the Org the "+
      "audit ran in only, and queries made in other Orgs are not counted.";
  return '<div class="unread usage-note" role="note">'+esc(text)+'</div>';
}

/* For a rule that requires usage (D.G.ur, e.g. H17) and has no findings: why it judged
   no Model — "Not read" when the run fetched usage and could not read it, the
   not-collected wording when no selected rule fetched it — so its empty section never
   reads as clean. "" for any other rule, or when usage was read. */
function usageUnjudged(ci){
  var rules = (D.G && D.G.ur) || [];
  if(rules.indexOf(ci) === -1) return "";
  var state = usageState();
  if(state === "read") return usagePartial();
  if(state === "not_read") return "Not read: the audit could not read usage, so this rule judged no Model.";
  return NOT_COLLECTED;
}
/* With usage read: when the history covers fewer days than the idle days H17 needs, it
   judged only the Models the history holds, so its result is partial; "" otherwise. */
function usagePartial(){
  var u = D.C && D.C.us;
  if(!u || !usageHistoryShort(u.id)) return "";
  return "Partly judged: the usage history starts on "+usageDate(u.hs)+", "+
    usagePlural(u.hd, "day")+" before the read, under the "+u.id+" days H17 needs; "+
    "Models with no query in it were not judged.";
}
/* A Cross-Model group's count: "<n> finding(s)", or for a usage rule that judged
   nothing, why ("Not read", "Not collected"), never "0 findings"; a partly judged one
   says so beside its count. */
function usageGroupCount(ci, n){
  var found = n+" finding"+(n !== 1 ? "s" : "");
  if(!usageUnjudged(ci)) return found;
  if(usageState() === "read") return n ? found+" (partly judged)" : "Partly judged";
  return n ? found : usageUnjudgedLabel(ci);
}
function usageUnjudgedLabel(ci){
  if(!usageUnjudged(ci)) return "";
  var state = usageState();
  return state === "not_read" ? USAGE_NOT_READ : state === "read" ? "Partly judged" : "Not collected";
}

/* The not-found Model IDs (D.C.us.g) split by the Org each was queried in:
   {own: [[row, org], ...] (null when the audit's Org was not read), others: [{id, name,
   rows}], the most IDs first, unrecorded: [row, ...] with no Org}. A Model ID queried in
   several Orgs is listed under each, with that Org's last query. */
function usageGoneByOrg(gone){
  var u = D.C.us, mine = u.oi === null || u.oi === undefined ? null : String(u.oi);
  var own = mine === null ? null : [], others = {}, order = [], unrecorded = [];
  gone.forEach(function(g){
    var orgs = g[4] || [];
    if(!orgs.length){ unrecorded.push(g); return; }
    orgs.forEach(function(o){
      var k = String(o[0]);
      if(k === mine){ own.push([g, o]); return; }
      if(!others[k]){ others[k] = {id: k, name: o[1], rows: []}; order.push(k); }
      others[k].rows.push([g, o]);
    });
  });
  var groups = order.map(function(k){ return others[k]; });
  groups.sort(function(a, b){
    return b.rows.length - a.rows.length || a.id.localeCompare(b.id, undefined, {numeric: true});
  });
  return {own: own, others: groups, unrecorded: unrecorded};
}

function usageOrgLabel(id, name){
  return name ? "the Org ‘"+name+"’" : "the Org with id "+id;
}
