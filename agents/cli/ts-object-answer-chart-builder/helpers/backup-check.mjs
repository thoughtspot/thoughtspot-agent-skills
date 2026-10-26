// Checks a backup file before a commit that changes something the skill did not create (a Liveboard with
// content the skill does not own, or an existing answer). Used by answer-pack.mjs and liveboard-pack.mjs, on
// disk, because the MCP sandbox cannot see files. Returns { file, bytes, sha, vizIds | search } for the block
// (checksummed there, and compared with the live object), or exits 2.
//
// The file must be a TML export of THAT object: its top-level guid is the guid (JSON from the REST export,
// the REST response itself, or YAML / JSON from `ts tml export`), and it has the object's type key. It must be
// under a day old (and not dated in the future), and its real path must sit outside any git working tree.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// What a TML export holds, whatever form it was saved in: JSON from the REST export, the REST response itself
// ([{ edoc }]), or YAML / JSON from `ts tml export` or Export TML in ThoughtSpot. For each document: its top-level
// guid, its type keys, and the parts the commit checks against the live object: a Liveboard's visualization
// ids, an answer's search.
function docs(txt) {
  const fromObj = (o) => {
    const lb = o && o.liveboard, an = o && o.answer;
    return { guid: o && o.guid, keys: o && typeof o === "object" ? Object.keys(o) : [],
      vizIds: lb && Array.isArray(lb.visualizations) ? lb.visualizations.map((v) => v && v.id).filter(Boolean) : null,
      search: an && typeof an.search_query === "string" ? an.search_query : null, hasTables: !!(an && Array.isArray(an.tables) && an.tables.length) };
  };
  let j;
  try { j = JSON.parse(txt); } catch { j = undefined; }
  if (j !== undefined) {
    const out = [];
    for (const x of Array.isArray(j) ? j : [j]) {
      if (x && typeof x.edoc === "string") { let e; try { e = JSON.parse(x.edoc); } catch { e = undefined; } if (e !== undefined) out.push(fromObj(e)); else out.push(...docs(x.edoc)); }
      else out.push(fromObj(x));
    }
    return out;
  }
  // YAML. Top-level keys start at column 0; several documents may be separated by ---.
  return txt.split(/^---\s*$/m).map((doc) => {
    const lines = doc.split("\n");
    const g = /^guid:\s*["']?([0-9a-fA-F-]{36})["']?\s*$/m.exec(doc);
    const keys = [...doc.matchAll(/^([a-z_]+):/gm)].map((m) => m[1]);
    // visualizations: a list under the liveboard key; each item starts "- id: <id>" at the list's indent.
    let vizIds = null;
    const vi = lines.findIndex((l) => /^\s+visualizations:\s*$/.test(l));
    if (vi >= 0) {
      const ind = lines[vi].search(/\S/);
      vizIds = [];
      for (let i = vi + 1; i < lines.length; i++) {
        const l = lines[i]; if (!l.trim()) continue;
        const at = l.search(/\S/);
        if (at < ind || (at === ind && !l.trimStart().startsWith("- "))) break;
        const m = /^\s*- id:\s*["']?([^"'\s]+)["']?\s*$/.exec(l);
        if (m && (at === ind || at === ind + 2)) vizIds.push(m[1]);
      }
    }
    const sq = /^\s{2}search_query:\s*(.+)$/m.exec(doc);
    return { guid: g && g[1], keys, vizIds, search: sq ? sq[1].trim().replace(/^["']|["']$/g, "") : null, hasTables: /^\s{2}tables:\s*$/m.test(doc) };
  });
}

export function checkBackup(file, guid, type) {
  const stop = (m) => { console.error("--backup" + (file ? " " + file : "") + ": " + m); process.exit(2); };
  if (!file) stop("missing; export the " + type + "'s TML first (ts tml export, or Export TML in ThoughtSpot) to ~/.cache/ts-charts/backups/");
  let f;
  try { f = fs.realpathSync(path.resolve(file)); } catch { stop("does not exist"); }
  const st = fs.statSync(f);
  if (!st.isFile() || !st.size) stop("is empty or not a file");
  const age = Date.now() - st.mtimeMs;
  if (age > 24 * 3600 * 1000) stop("is more than a day old; export it again");
  if (age < -5 * 60 * 1000) stop("is dated in the future; export it again");
  const txt = fs.readFileSync(f, "utf8");
  const d = docs(txt).find((h) => String(h.guid || "").toLowerCase() === guid.toLowerCase() && h.keys.includes(type));
  if (!d) stop("is not a TML export of " + type + " " + guid + " (its top-level guid and '" + type + ":' must match)");
  // A stub (just the guid and the type key) or a cut-off export is not a backup: it must hold the content.
  if (type === "liveboard" && !(d.vizIds && d.vizIds.length)) stop("holds no visualizations; a Liveboard backup must be the full export (a stub or a cut-off file is not a backup)");
  if (type === "answer" && !(d.search && d.hasTables)) stop("holds no search or tables; an answer backup must be the full export");
  for (let d = path.dirname(f); ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, ".git"))) stop("is inside the git working tree " + d + "; keep backups out of repos (~/.cache/ts-charts/backups)");
    if (d === path.dirname(d)) break;
  }
  // What the sandbox checks against the live object, so a backup of an older state is refused there.
  const out = { file: path.basename(f), bytes: txt.length, sha: crypto.createHash("sha256").update(txt).digest("hex").slice(0, 16) };
  if (type === "liveboard") out.vizIds = d.vizIds; else out.search = d.search;
  return out;
}
