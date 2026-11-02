// Checks a backup file before a commit that changes something already in ThoughtSpot (a Liveboard that has
// visualizations, or an existing answer). Used by answer-pack.mjs and liveboard-pack.mjs, on disk, because the
// MCP sandbox cannot see files. Returns { file, bytes, sha, viz } for the block (checksummed there), or exits 2.
//
// The file must be a JSON TML export of THAT object: the REST export response (`ts tml export <guid> --format
// JSON`), the same parsed (`--parse`), or one edoc document. Its top-level guid is the guid and it has the
// object's type key. It must be under a day old (and not dated in the future), and its real path must sit
// outside any git working tree.
//
// `viz` holds one fingerprint per visualization (a Liveboard) or one for the answer: a hash of its name, search,
// chart type, decoded chart code and note. The sandbox computes the same fingerprints from the live object and
// refuses the commit unless the backup holds every one, so a list of ids, a cut-off export, an older export or
// another object's export does not pass: ids alone prove nothing (they are Viz_1, Viz_2 ... on every Liveboard,
// and ThoughtSpot renumbers them on import). patch.js and answer-patch.js carry the same fingerprint code.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const sha256 = (s) => crypto.createHash("sha256").update(s, "utf8").digest("hex");
// The sandbox's decoder, exactly: a payload it cannot decode is null there, so it must be null here too.
const unb64 = (s) => decodeURIComponent(escape(atob(s || "")));
export const stable = (x) => Array.isArray(x) ? "[" + x.map(stable).join(",") + "]" : x && typeof x === "object" ? "{" + Object.keys(x).filter((k) => x[k] !== undefined).sort().map((k) => JSON.stringify(k) + ":" + stable(x[k])).join(",") + "}" : JSON.stringify(x);
const codeOf = (v) => {
  const p = v && v.answer && v.answer.chart && v.answer.chart.custom_visual_props;
  if (!p) return null;
  try {
    const code = JSON.parse(JSON.parse(p).clientState).playground.code;
    return { js: unb64(code.jsCodeBase64), css: unb64(code.cssCodeBase64), html: unb64(code.htmlCodeBase64) };
  } catch { return null; }
};
// A visualization ({ answer } or { note_tile }), or an answer wrapped as { answer }.
export function fingerprint(v) {
  const a = (v && v.answer) || {}, c = codeOf(v);
  return sha256(JSON.stringify([a.name || "", a.search_query || "", (a.chart && a.chart.type) || "", c ? [c.js, c.css, c.html] : null, v && v.note_tile ? stable(v.note_tile) : null])).slice(0, 16);
}

// Every TML document in the file, whatever JSON form it was saved in.
function docs(j) {
  const out = [];
  for (const x of Array.isArray(j) ? j : [j]) {
    if (x && typeof x.edoc === "string") { try { out.push(JSON.parse(x.edoc)); } catch { out.push({ yaml: true }); } }
    else if (x && x.edoc && typeof x.edoc === "object") out.push(x.edoc);
    // `ts tml export --parse`: [{ type, guid, tml, info }], the document under tml
    else if (x && x.tml && typeof x.tml === "object") out.push({ guid: x.guid, ...x.tml });
    else if (x && typeof x === "object") out.push(x);
  }
  return out;
}

export function checkBackup(file, guid, type) {
  const stop = (m) => { console.error("--backup" + (file ? " " + file : "") + ": " + m); process.exit(2); };
  const how = "ts tml export " + guid + " --format JSON --profile <name> > ~/.cache/ts-charts/backups/" + guid + "-$(date +%Y%m%d-%H%M).json";
  if (!file) stop("missing; export the " + type + "'s TML first: " + how);
  let f;
  try { f = fs.realpathSync(path.resolve(file)); } catch { stop("does not exist"); }
  const st = fs.statSync(f);
  if (!st.isFile() || !st.size) stop("is empty or not a file");
  const age = Date.now() - st.mtimeMs;
  if (age > 24 * 3600 * 1000) stop("is more than a day old; export it again");
  if (age < -5 * 60 * 1000) stop("is dated in the future; export it again");
  for (let d = path.dirname(f); ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, ".git"))) stop("is inside the git working tree " + d + "; keep backups out of repos (~/.cache/ts-charts/backups)");
    if (d === path.dirname(d)) break;
  }
  const txt = fs.readFileSync(f, "utf8");
  let j;
  // A cut-off export is not valid JSON, so it stops here.
  try { j = JSON.parse(txt); } catch { stop("is not complete JSON; a backup is the JSON export, in full: " + how); }
  const all = docs(j);
  if (all.some((d) => d.yaml)) stop("holds a YAML edoc; export it as JSON: " + how);
  const d = all.find((h) => h && String(h.guid || "").toLowerCase() === guid.toLowerCase() && h[type] && typeof h[type] === "object");
  if (!d) stop("is not a TML export of " + type + " " + guid + " (its top-level guid and '" + type + "' must match)");
  let viz;
  if (type === "liveboard") {
    if (!Array.isArray(d.liveboard.visualizations) || !d.liveboard.visualizations.length) stop("holds no visualizations; a Liveboard backup must be the full export");
    viz = d.liveboard.visualizations.map(fingerprint);
  } else {
    if (!(typeof d.answer.search_query === "string" && Array.isArray(d.answer.tables) && d.answer.tables.length)) stop("holds no search or tables; an answer backup must be the full export");
    viz = [fingerprint({ answer: d.answer })];
  }
  return { file: path.basename(f), bytes: txt.length, sha: sha256(txt).slice(0, 16), viz };
}
