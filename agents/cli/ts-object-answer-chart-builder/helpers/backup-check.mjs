// Checks a backup file before a commit that changes something the skill did not create (a Liveboard with
// content the skill does not own, or an existing answer). Used by answer-pack.mjs and liveboard-pack.mjs, on
// disk, because the MCP sandbox cannot see files. Returns { file, bytes, sha } for the block, or exits 2.
//
// The file must be a TML export of THAT object: its top-level guid is the guid (JSON from the REST export,
// the REST response itself, or YAML / JSON from `ts tml export`), and it has the object's type key. It must be
// under a day old (and not dated in the future), and its real path must sit outside any git working tree.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The top-level guid and type keys of a TML export, whatever form it was saved in.
function heads(txt) {
  const out = [];
  try {
    let j = JSON.parse(txt);
    for (const x of Array.isArray(j) ? j : [j]) {
      if (x && typeof x.edoc === "string") { try { const e = JSON.parse(x.edoc); out.push({ guid: e.guid, keys: Object.keys(e) }); } catch { out.push(...heads(x.edoc)); } }
      else if (x && typeof x === "object") out.push({ guid: x.guid, keys: Object.keys(x) });
    }
    return out;
  } catch {
    // YAML: top-level keys start at column 0. Several documents may be separated by ---.
    for (const doc of txt.split(/^---\s*$/m)) {
      const g = /^guid:\s*["']?([0-9a-f-]{36})["']?\s*$/im.exec(doc);
      out.push({ guid: g && g[1], keys: [...doc.matchAll(/^([a-z_]+):/gm)].map((m) => m[1]) });
    }
    return out;
  }
}

export function checkBackup(file, guid, type) {
  const stop = (m) => { console.error("--backup " + file + ": " + m); process.exit(2); };
  if (!file) stop("missing; export the " + type + "'s TML first (ts tml export, or Export TML in ThoughtSpot) to ~/.cache/ts-charts/backups/");
  let f;
  try { f = fs.realpathSync(path.resolve(file)); } catch { stop("does not exist"); }
  const st = fs.statSync(f);
  if (!st.isFile() || !st.size) stop("is empty or not a file");
  const age = Date.now() - st.mtimeMs;
  if (age > 24 * 3600 * 1000) stop("is more than a day old; export it again");
  if (age < -5 * 60 * 1000) stop("is dated in the future; export it again");
  const txt = fs.readFileSync(f, "utf8");
  if (!heads(txt).some((h) => String(h.guid || "").toLowerCase() === guid.toLowerCase() && h.keys.includes(type))) stop("is not a TML export of " + type + " " + guid + " (its top-level guid and '" + type + ":' must match)");
  for (let d = path.dirname(f); ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, ".git"))) stop("is inside the git working tree " + d + "; keep backups out of repos (~/.cache/ts-charts/backups)");
    if (d === path.dirname(d)) break;
  }
  return { file: path.basename(f), bytes: txt.length, sha: crypto.createHash("sha256").update(txt).digest("hex").slice(0, 16) };
}
