// Quest.esc, Quest.fill and Quest.wording: escaping, and the pack's wording (strings.yaml).
// core/ is plain scripts, not modules: each adds to one Quest global, so the classic page can
// inline them all in one <script> and the explore page can load them one by one.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // {name} filled once from the values given (own properties only, never constructor or toString).
  const fill = (t, v) => t.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(v, k) ? String(v[k]) : m));
  Q.esc = esc;
  Q.fill = fill;
  // S() is plain text; H() is HTML: the text escaped, then *word* highlighted, **word** bold and
  // [text](https://…) linked, then {name} filled in escaped.
  Q.wording = strings => ({
    S: (k, v = {}) => fill(strings[k], v),
    H: (k, v = {}) => fill(esc(strings[k]).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/\*(.+?)\*/g, '<span class="hot">$1</span>')
      .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>'),
      Object.fromEntries(Object.entries(v).map(([k, x]) => [k, esc(x)])))
  });
})(Quest);
