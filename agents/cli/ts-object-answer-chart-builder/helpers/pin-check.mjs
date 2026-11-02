// pin-check.mjs — the CDN half of library-contract.md's hard contract, for every chart in any library:
// a script loaded from a URL names one exact release (x.y.z, never `d3@7` or `@latest`) and carries its
// subresource integrity, so a CDN file that changes, or a package release that goes bad, refuses to run
// instead of running next to the user's data. Used by answer-pack.mjs, liveboard-pack.mjs and lean-lint.mjs.
//
// Covered: <script src> tags (protocol-relative too), inline <script> bodies, and URLs in chart.js. An ES module
// import from a URL (`import ... from 'https://...'`, `import('https://...')`) cannot carry integrity, so it is
// refused outright: load the library's script build instead.

// A URL in quotes, absolute or protocol-relative.
const QUOTED_URL = /["'`]((?:https?:)?\/\/[^"'`\s]+)["'`]/g;
// Hosts that serve npm packages by version; everywhere else the release must appear somewhere in the path.
const NPM_HOST = /\/\/(?:cdn\.jsdelivr\.net\/npm|unpkg\.com|esm\.sh|cdn\.skypack\.dev|esm\.run)\//;
const isScript = (u) => /\.m?js(?:[?#]|$)/.test(u) || NPM_HOST.test(u) || /\/\+esm\b/.test(u);
const exact = (u) => (NPM_HOST.test(u) ? /@\d+\.\d+\.\d+(?:[/?#]|$)/.test(u) : /\d+\.\d+\.\d+/.test(u));
const ESM_IMPORT = /\bimport\s*(?:\(\s*|[^;()]*?\bfrom\s*)["'`]((?:https?:)?\/\/[^"'`\s]+)["'`]|\bimport\s*["'`]((?:https?:)?\/\/[^"'`\s]+)["'`]/g;
const SRI = /["']sha384-[A-Za-z0-9+/=]{40,}["']/;

function scriptProblems(code, where) {
  const bad = [];
  for (const m of code.matchAll(ESM_IMPORT)) bad.push(where + " imports an ES module from " + (m[1] || m[2]) + ", which cannot carry integrity; load the library's script build with <script src> and integrity");
  for (const m of code.matchAll(QUOTED_URL)) {
    const u = m[1];
    if (!isScript(u)) continue;
    if (!exact(u)) bad.push(where + " loads " + u + " without an exact x.y.z version");
    // An integrity value next to each URL (the same object or the next lines), not merely somewhere in the file;
    // a URL held in a constant (MAYA = '...') counts when the integrity sits beside a use of that constant.
    const around = (i, n) => code.slice(Math.max(0, i - 300), i + n + 300);
    const name = (/(\w+)\s*=\s*$/.exec(code.slice(Math.max(0, m.index - 80), m.index)) || [])[1];
    const uses = name ? [...code.matchAll(new RegExp("\\b" + name + "\\b", "g"))].map((x) => around(x.index, name.length)) : [];
    if (![around(m.index, m[0].length), ...uses].some((t) => SRI.test(t))) bad.push(where + " loads " + u + " without an integrity value (sha384-...) beside it");
  }
  return bad;
}

// Problems with the chart's script loads, as strings; empty when it pins and checks everything it loads.
export function cdnProblems(html, js) {
  const bad = [];
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const [, attrs, body] = m;
    const src = (/\bsrc=["']([^"']+)["']/i.exec(attrs) || [])[1];
    if (src && /^(?:https?:)?\/\//.test(src)) {
      if (!exact(src)) bad.push("chart.html loads " + src + " without an exact x.y.z version");
      if (!/\bintegrity=["']sha384-[A-Za-z0-9+/=]+["']/.test(attrs) || !/\bcrossorigin=["']anonymous["']/i.test(attrs)) bad.push("chart.html loads " + src + ' without integrity="sha384-..." crossorigin="anonymous"');
    }
    if (body.trim()) bad.push(...scriptProblems(body, "an inline script in chart.html"));
  }
  bad.push(...scriptProblems(js, "chart.js"));
  return [...new Set(bad)];
}

// The MayaCharts pin in a file (a tile, or the shared core's loader) against the skill's (env.mjs MAYA).
export function mayaPinProblems(text, MAYA, where) {
  const bad = [];
  for (const m of text.matchAll(/mayacharts@([^/"'\s]+)\//g)) if (m[1] !== MAYA.version) bad.push(where + " pins MayaCharts " + m[1] + "; the skill pins " + MAYA.version + " (env.mjs MAYA)");
  for (const [f, sri] of Object.entries(MAYA.sri)) {
    const re = new RegExp("['\"]" + f.replace(/\./g, "\\.") + "['\"]\\s*:\\s*['\"](sha384-[^'\"]+)['\"]");
    const m = re.exec(text);
    if (m && m[1] !== sri) bad.push(where + " carries an integrity for " + f + " that is not the skill's recorded one");
  }
  return [...new Set(bad)];
}
