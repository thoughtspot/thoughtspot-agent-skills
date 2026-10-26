// -- helpers shared by the narrative configs ---------------------------------
const sum = (a) => a.reduce((x, y) => x + y, 0);
function groupSum(rows, kKey, vKey) {
  const m = new Map();
  rows.forEach((r) => m.set(r[kKey], (m.get(r[kKey]) || 0) + AZ.num(r[vKey])));
  return [...m.entries()].map((e) => ({ k: e[0], v: e[1] })).sort((a, b) => b.v - a.v);
}
function monthly(rows, schema) {
  const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i, { optional: true });
  return rows.map((r) => ({ t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: uK ? AZ.num(r[uK]) : 0 })).filter((r) => isFinite(r.t)).sort((a, b) => a.t - b.t);
}
const money = AZ.money, pct = AZ.pct;

// __CFG__

// -- renderer ----------------------------------------------------------------
function copyText(text, btn) {
  const ok = () => { btn.classList.add('done'); const t = btn.textContent; btn.textContent = 'Copied. Paste it into Spotter.'; setTimeout(() => { btn.classList.remove('done'); btn.textContent = t; }, 1800); };
  const legacy = () => {
    try {
      const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); const good = document.execCommand('copy'); ta.remove();
      if (good) return ok();
    } catch (e) {}
    const r = document.createRange(); r.selectNodeContents(btn); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  };
  try { if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text).then(ok, legacy); } catch (e) {}
  legacy();
}

const state = { open: -1, fam: null };
AZ.boot({
  need: CFG.need,
  render: async ({ el, rows, schema, redraw }) => {
    const o = CFG.build(rows, schema);
    const H = AZ.esc;
    if (CFG.kind === 'banner') {
      el.innerHTML = '<div class="nv nv-banner">'
        + '<div class="nv-col"><div class="nv-tabno">' + H(CFG.tab) + '</div><h2 class="nv-q">' + H(CFG.question) + '</h2><p class="nv-lead">' + H(o.lead) + '</p></div>'
        + '<div class="nv-col"><div class="nv-h">What the numbers say</div>' + (o.stats.length ? o.stats.map((s, i) => '<div class="nv-stat" data-i="' + i + '" tabindex="0"><span class="nv-sv">' + H(s.v) + '</span><span class="nv-sk">' + H(s.k) + '</span></div>').join('') : '<p class="nv-lead">Not enough data in this view.</p>') + '</div>'
        + '<div class="nv-col"><div class="nv-h">Ask Spotter</div>' + CFG.prompts.map((p, i) => '<button type="button" class="nv-p" data-i="' + i + '">' + H(p) + '</button>').join('') + '<p class="nv-note">' + H(CFG.next) + '</p></div>'
        + '</div>';
      const tip = AZ.tip(el);
      el.querySelectorAll('.nv-stat').forEach((n) => {
        const s = o.stats[Number(n.getAttribute('data-i'))];
        const show = () => { const r = n.getBoundingClientRect(), b = el.getBoundingClientRect(); tip.show('<b>' + H(s.k) + '</b>' + H(s.note || ''), r.left - b.left + 20, r.top - b.top + 10); };
        n.addEventListener('mouseenter', show); n.addEventListener('focus', show);
        n.addEventListener('mouseleave', () => tip.hide()); n.addEventListener('blur', () => tip.hide());
      });
      el.querySelectorAll('.nv-p').forEach((b) => b.addEventListener('click', () => copyText(CFG.prompts[Number(b.getAttribute('data-i'))], b)));
    } else if (CFG.kind === 'about') {
      const open = state.open;
      el.innerHTML = '<div class="nv nv-about">'
        + '<div class="nv-col"><h1 class="nv-title">' + H(CFG.title) + '</h1><p class="nv-sub">' + H(o.sub) + '</p>'
        + '<div class="nv-stakes">' + o.stakes.map((s) => '<div class="nv-stake"><b>' + H(s.v) + '</b><span>' + H(s.k) + '</span></div>').join('') + '</div>'
        + '<p class="nv-body">' + H(o.body) + '</p></div>'
        + '<div class="nv-col"><div class="nv-h">Who it is for</div><ul class="nv-list">' + CFG.people.map((p, i) => '<li><button type="button" class="nv-row' + (open === i ? ' open' : '') + '" data-i="' + i + '"><b>' + H(p.who) + '</b><span>' + H(p.asks) + '</span><span class="more">Start at ' + H(p.start) + '.</span></button></li>').join('') + '</ul>'
        + '<div class="nv-h">Terms</div><ul class="nv-list">' + CFG.terms.map((t, i) => '<li><button type="button" class="nv-row' + (open === 100 + i ? ' open' : '') + '" data-i="' + (100 + i) + '"><b>' + H(t.term) + '</b><span class="more">' + H(t.def) + '</span></button></li>').join('') + '</ul></div>'
        + '</div>';
      el.querySelectorAll('.nv-row').forEach((b) => b.addEventListener('click', () => { const i = Number(b.getAttribute('data-i')); state.open = state.open === i ? -1 : i; redraw(); }));
    } else {
      const items = groupSum(rows, AZ.col(schema, /item/i), AZ.col(schema, /sales/i));
      const fam = {}; items.forEach((x) => { const f = AZ.familyOf(x.k); (fam[f] = fam[f] || { v: 0, items: [] }); fam[f].v += x.v; fam[f].items.push(x); });
      const tot = sum(Object.values(fam).map((f) => f.v)) || 1;
      const names = Object.keys(AZ.T.family).filter((f) => fam[f]).sort((a, b) => fam[b].v - fam[a].v);
      el.innerHTML = '<div class="nv nv-guide">'
        + '<div class="nv-col"><div class="nv-h">' + H(CFG.mapTitle) + '</div><div class="nv-map">' + CFG.tabs.map((t, i) => '<button type="button" class="nv-row' + (state.open === i ? ' open' : '') + '" data-i="' + i + '"><b><i>' + H(t.no) + '</i>' + H(t.name) + '</b><span>' + H(t.q) + '</span><span class="more">' + H(t.how) + '</span></button>').join('') + '</div></div>'
        + '<div class="nv-col"><div class="nv-h">Colour is reserved for product families</div><div class="nv-fam">' + names.map((f) => '<button type="button" class="nv-row' + (state.fam && state.fam !== f ? ' dim' : '') + '" data-f="' + H(f) + '"><span class="sw" style="background:' + AZ.T.family[f] + '"></span><b>' + H(f) + '</b><span class="items">' + fam[f].items.length + ' item types</span><span>' + pct(fam[f].v / tot, 0) + '</span></button>').join('') + '</div><p class="nv-note">Region is never a colour: it is shown by position and label. The grouping into families is editorial, not a column in the model.</p></div>'
        + '</div>';
      el.querySelectorAll('.nv-map .nv-row').forEach((b) => b.addEventListener('click', () => { const i = Number(b.getAttribute('data-i')); state.open = state.open === i ? -1 : i; redraw(); }));
      el.querySelectorAll('.nv-fam .nv-row').forEach((b) => b.addEventListener('click', () => { const f = b.getAttribute('data-f'); state.fam = state.fam === f ? null : f; redraw(); }));
      const tip = AZ.tip(el);
      el.querySelectorAll('.nv-fam .nv-row').forEach((b) => {
        const f = b.getAttribute('data-f');
        b.addEventListener('mouseenter', () => { const r = b.getBoundingClientRect(), bb = el.getBoundingClientRect(); tip.show('<b>' + H(f) + '</b>' + fam[f].items.map((x) => AZ.row(x.k, money(x.v, 1) + ', ' + pct(x.v / tot, 1), AZ.T.family[f])).join(''), r.left - bb.left + 30, r.top - bb.top); });
        b.addEventListener('mouseleave', () => tip.hide());
      });
    }
  }
});
