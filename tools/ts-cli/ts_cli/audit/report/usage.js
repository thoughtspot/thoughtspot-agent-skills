/* ── Usage (corpus.usage and each Model's usage, ts_cli/audit/usage.py) ──
   D.C.us is the reading: {o Org name, oi Org id, pr 1 Primary / 0 another / null not read,
   w window days, at read at, hs/he history's first and last query (epoch seconds), b rows
   dropped for a blank Model ID, g [[guid, queries, users, last query]] or null}. It is
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

/* One Model's last use, as {text, title}: "Not read" when usage was fetched and not read,
   "No query" when the history holds none, "<n> days ago" otherwise. */
function usageLastUsed(cm){
  var state = usageState();
  if(state === "not_read") return {text: USAGE_NOT_READ,
    title: "Usage could not be read for this audit, so it is not known whether this Model was queried"};
  var us = cm && cm.us;
  if(state !== "read" || !us) return {text: "", title: ""};
  var w = D.C.us.w || 180;
  var counts = usagePlural(us.q, "query", "queries")+" by "+usagePlural(us.u, "user")+" in the last "+w+" days";
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

/* The header line naming the Org whose usage the report shows and when it was read, and
   a note when that is not the Primary Org's usage. "" when usage is absent. */
function usageHeaderHtml(){
  var state = usageState();
  if(state === "absent") return "";
  if(state === "not_read") return '<span class="meta-item usage-meta">Usage: <strong>'+
    USAGE_NOT_READ+'</strong></span>';
  return '<span class="meta-item usage-meta">Usage of <strong>'+esc(usageOrgName())+
    '</strong>, read on '+esc(usageDate(D.C.us.at))+'</span>';
}

function usageOrgNoteHtml(){
  if(usageState() !== "read" || D.C.us.pr === 1) return "";
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
  if(state === "read") return "";
  if(state === "not_read") return "Not read: the audit could not read usage, so this rule judged no Model.";
  return NOT_COLLECTED;
}
/* A Cross-Model group's count: "<n> finding(s)", or for a usage rule that judged
   nothing, why ("Not read", "Not collected"), never "0 findings". */
function usageGroupCount(ci, n){
  if(n === 0 && usageUnjudged(ci)) return usageUnjudgedLabel(ci);
  return n+" finding"+(n !== 1 ? "s" : "");
}
function usageUnjudgedLabel(ci){
  if(!usageUnjudged(ci)) return "";
  return usageState() === "not_read" ? USAGE_NOT_READ : "Not collected";
}
