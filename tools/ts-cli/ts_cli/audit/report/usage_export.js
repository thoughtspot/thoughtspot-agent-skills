/* ── The Usage view's candidates export (views/usage.js) ──
   The selected rows as CSV or as the ts-audit-candidates/1 JSON, built in the browser
   and handed to the viewer as a download (a Blob and an <a download>): no network.
   The JSON is the file a later ts-dependency-manager list mode reads (BL-628), so its
   shape is fixed: ts-audit SKILL.md "Candidates file" documents it. A field is added,
   never renamed or removed, without a new format version. */
var USAGE_OBJECT_FIELDS = ["guid", "name", "type", "status", "last_used", "days_since_last_use",
  "queries_180d", "users_180d", "dependents_total", "liveboards", "answers", "sets", "owner",
  "created"];
var USAGE_CSV_FIELDS = USAGE_OBJECT_FIELDS.concat(["usage_scope", "cluster_url", "audit_read_date"]);
var USAGE_FORMAT = "ts-audit-candidates/1";

/* One row as the file's object: dates as YYYY-MM-DD, null where not known. */
function usageExportObject(r){
  return {guid: r.guid, name: r.name, type: "MODEL", status: r.status,
    last_used: typeof r.last === "number" ? usageDate(r.last) : null,
    days_since_last_use: typeof r.days === "number" ? r.days : null,
    queries_180d: r.queries, users_180d: r.users, dependents_total: r.deps,
    liveboards: r.lb, answers: r.an, sets: r.sets, owner: r.owner, created: r.created};
}

/* An ISO time to the second, "2026-11-25T00:00:00Z". */
function usageIsoSecond(date){ return date.toISOString().replace(/\.\d{3}Z$/, "Z"); }

/* One CSV cell. A value starting = + - @ (or a tab or carriage return) is prefixed with a
   single quote, so a spreadsheet does not run it as a formula; a cell holding a comma, a
   quote or a line break is quoted, its quotes doubled. Null is empty. */
function usageCsvCell(v){
  if(v === null || v === undefined) return "";
  var s = String(v);
  if(/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function usageCandidatesCsv(rows){
  var scope = usageWhose(), cluster = (D.C && D.C.u) || "", read = usageDate(D.C.us.at);
  var lines = [USAGE_CSV_FIELDS.join(",")];
  rows.forEach(function(r){
    var o = usageExportObject(r);
    o.usage_scope = scope; o.cluster_url = cluster; o.audit_read_date = read;
    lines.push(USAGE_CSV_FIELDS.map(function(f){ return usageCsvCell(o[f]); }).join(","));
  });
  return lines.join("\r\n") + "\r\n";
}

function usageCandidatesJson(rows, idleDays){
  var u = D.C.us;
  return JSON.stringify({
    format: USAGE_FORMAT,
    generated: usageIsoSecond(new Date()),
    cluster: (D.C && D.C.u) || "",
    usage: {scope: usageWhose(), org: {id: u.oi === undefined ? null : u.oi, name: u.o || null},
            read_at: typeof u.at === "number" ? usageIsoSecond(new Date(u.at * 1000)) : null,
            idle_days: idleDays, window_days: u.w || null},
    objects: rows.map(usageExportObject)
  }, null, 2) + "\n";
}

/* Hand `text` to the viewer as a file named `name`. */
function usageDownload(text, type, name){
  var url = URL.createObjectURL(new Blob([text], {type: type}));
  var a = document.createElement("a");
  a.href = url;
  a.setAttribute("download", name);
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function(){ URL.revokeObjectURL(url); }, 0);
}
