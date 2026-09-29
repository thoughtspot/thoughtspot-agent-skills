/* ==== amuzing core v1 | source: library/_shared/core.js | run helpers/sync-core.mjs, do not edit inside a chart ==== */
const AZ = (function () {
  // -- theme: one palette for the whole Liveboard -------------------------------
  // Families are validated categorical hues (dataviz validator, light surface).
  // Region is never a hue: it is shown by position, label or a slate ramp, so a
  // colour keeps exactly one meaning across every tile.
  const T = {
    ink: '#1E1E24', ink2: '#52525B', muted: '#8A8A94', grid: '#E6E7EA', surface: '#FFFFFF',
    good: '#1F7A4D', bad: '#B3261E',
    slate: ['#EEF0F3', '#D5DAE1', '#B4BDC9', '#8E9AAB', '#6A7891', '#4A5872', '#2F3B54', '#1E293B'],
    family: {
      'Outerwear': '#D1543A', 'Tops and dresses': '#2A6FD0', 'Bottoms': '#0F9D8A',
      'Swim and basics': '#D99A00', 'Accessories': '#C2477A'
    },
    font: "Geist, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
  };
  // Editorial grouping of the model's 15 item types (not a model column).
  const FAMILY_OF = {
    Jackets: 'Outerwear', Vests: 'Outerwear', Sweatshirts: 'Outerwear', Sweaters: 'Outerwear',
    Shirts: 'Tops and dresses', Dresses: 'Tops and dresses',
    Pants: 'Bottoms', Jeans: 'Bottoms', Shorts: 'Bottoms', Skirts: 'Bottoms',
    Swimwear: 'Swim and basics', Underwear: 'Swim and basics', Socks: 'Swim and basics',
    Bags: 'Accessories', Headwear: 'Accessories'
  };
  const familyOf = (item) => FAMILY_OF[item] || FAMILY_OF[String(item || '').replace(/^./, (c) => c.toUpperCase())] || 'Other';
  const familyColor = (item) => T.family[familyOf(item)] || T.muted;

  // -- host access ------------------------------------------------------------
  // Bare viz identifier, never globalThis.viz (see hard-rules.md).
  function host() {
    try { if (typeof viz !== 'undefined' && viz) return viz; } catch (e) {}
    return null;
  }
  const cellVal = (v) => {
    if (v == null || typeof v !== 'object') return v;
    try {
      const raw = typeof v.value === 'function' ? v.value() : v.value;
      return raw ?? v._value ?? v.v ?? v.formatted ?? v.f ?? null;
    } catch (e) { return v._value ?? null; }
  };
  // Live rows as objects keyed by column name, or null when the tile has no data.
  function liveData() {
    try {
      const h = host();
      const dm = h && h.getDataFromSearchQuery && h.getDataFromSearchQuery();
      const raw = dm && dm.getData();
      if (!raw || !raw.data || !raw.data.length) return null;
      const schema = raw.schema || [];
      const rows = raw.data.map((arr) => {
        const o = {};
        schema.forEach((c, i) => { o[c.name] = cellVal(arr[i]); });
        return o;
      });
      return { schema, rows };
    } catch (e) { console.warn('[chart] live data unavailable:', e); return null; }
  }
  // Resolve a column by regex against the schema (the host renames: Total sales, Month(date)).
  function col(schema, re, opt) {
    const c = schema.find((s) => re.test(s.name));
    if (!c && !(opt && opt.optional)) throw new Error('Column not found in the search: ' + re + ' | have: ' + schema.map((s) => s.name).join(', '));
    return c ? c.name : null;
  }
  const num = (v) => { const n = Number(v); return isFinite(n) ? n : 0; };
  // Dates arrive as epoch ms (or seconds from other paths); normalise to ms.
  const ms = (v) => { const n = Number(v); return n < 1e11 ? n * 1000 : n; };

  // -- formatting -------------------------------------------------------------
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const money = (n, d) => {
    const a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(d ?? 2) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(d ?? 1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(d ?? 0) + 'K';
    return s + '$' + a.toFixed(d ?? 0);
  };
  const int = (n) => { const a = Math.abs(n); return a >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : a >= 1e3 ? (n / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'K' : String(Math.round(n)); };
  const pct = (x, d, signed) => (signed && x > 0 ? '+' : '') + (x * 100).toFixed(d ?? 1) + '%';
  // Signed gap in percentage points, e.g. pts(0.009) -> '+0.9 pts'
  const pts = (x, d) => (x > 0 ? '+' : '') + (x * 100).toFixed(d ?? 1) + ' pts';
  const monthLabel = (t) => { const d = new Date(t); return MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); };
  const monthShort = (t) => MON[new Date(t).getUTCMonth()];
  const year = (t) => new Date(t).getUTCFullYear();
  const isoDay = (t) => new Date(t).toISOString().slice(0, 10);

  // -- same-period comparison: latest month in the data drives "YTD" ---------
  // rows: [{t: ms(month start), v: number}] at monthly grain.
  function ytd(rows) {
    if (!rows.length) return null;
    const last = Math.max.apply(null, rows.map((r) => r.t));
    const ly = year(last), lm = new Date(last).getUTCMonth();
    let cur = 0, prev = 0, nCur = 0, nPrev = 0;
    rows.forEach((r) => {
      const d = new Date(r.t), y = d.getUTCFullYear(), m = d.getUTCMonth();
      if (m > lm) return;
      if (y === ly) { cur += r.v; nCur++; } else if (y === ly - 1) { prev += r.v; nPrev++; }
    });
    return { cur, prev, delta: cur - prev, pct: prev ? cur / prev - 1 : null, lastMs: last, year: ly, month: lm, through: monthLabel(last), comparable: nCur === nPrev && nPrev > 0 };
  }

  // -- CDN loader: bounded, with fallback hosts (a hung request fires neither onload nor onerror)
  function loadScript(urls, isReady, timeoutMs) {
    const list = [].concat(urls);
    const tryOne = (i) => new Promise((resolve, reject) => {
      if (isReady()) return resolve();
      if (i >= list.length) return reject(new Error('Library could not be loaded from: ' + list.join(' , ')));
      const s = document.createElement('script');
      let done = false;
      const next = () => { if (done) return; done = true; s.remove(); tryOne(i + 1).then(resolve, reject); };
      const t = setTimeout(next, timeoutMs || 8000);
      s.src = list[i];
      s.onload = () => { if (done) return; done = true; clearTimeout(t); isReady() ? resolve() : tryOne(i + 1).then(resolve, reject); };
      s.onerror = () => { clearTimeout(t); next(); };
      document.head.appendChild(s);
    });
    // The HTML tab may already carry a <script src> for this library: if so, give it a moment to finish before
    // injecting a second copy. If no such tag exists, inject at once (no wait).
    const tagged = list.some((u) => document.querySelector('script[src="' + u + '"]'));
    if (!tagged) return tryOne(0);
    return new Promise((resolve, reject) => {
      let waited = 0;
      const poll = () => { if (isReady()) return resolve(); if ((waited += 100) >= 3000) return tryOne(0).then(resolve, reject); setTimeout(poll, 100); };
      poll();
    });
  }

  // -- mount + boot ------------------------------------------------------------
  function mount() {
    let el = document.getElementById('chart');
    if (!el) { el = document.createElement('div'); el.id = 'chart'; document.body.appendChild(el); }
    return el;
  }
  function paint(el, html) { (el || document.getElementById('chart') || document.body).innerHTML = html; }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function done() {
    try { host().events.emitRenderCompletedEvent(); } catch (e) { console.warn('[chart] emitRenderCompletedEvent unavailable:', e); }
  }

  // -- motion: small, motivated, and off under prefers-reduced-motion ---------
  const reduced = () => { try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; } };
  const EASE = { out: (t) => 1 - Math.pow(1 - t, 3), inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2), spring: (t) => 1 - Math.pow(1 - t, 4) * Math.cos(t * 9) * (1 - t) };
  // tween(ms, step, done, easing): calls step(0..1) each frame; returns a cancel function.
  // With reduced motion it jumps straight to step(1).
  function tween(ms, step, done, easing) {
    const ez = easing || EASE.out;
    if (reduced() || !ms) { step(1); if (done) done(); return () => {}; }
    let raf = 0, t0 = 0, dead = false;
    const f = (t) => { if (dead) return; if (!t0) t0 = t; const k = Math.min(1, (t - t0) / ms); step(ez(k)); if (k < 1) raf = requestAnimationFrame(f); else if (done) done(); };
    raf = requestAnimationFrame(f);
    return () => { dead = true; cancelAnimationFrame(raf); };
  }
  // animator(): a tween runner that cancels its previous run on re-entry, so rapid toggles never fight.
  //   const go = AZ.animator(); go(400, (k) => draw(k), done); go(400, ...) again cancels the first.
  function animator() { let cancel = null; const run = (ms, step, done, easing) => { if (cancel) cancel(); cancel = tween(ms, step, done, easing); return cancel; }; run.stop = () => { if (cancel) cancel(); cancel = null; }; return run; }
  // Count a number up into an element: countUp(node, 142100000, AZ.money, 700)
  function countUp(node, to, fmt, ms, from) {
    const a = from == null ? 0 : from;
    return tween(ms || 700, (k) => { node.textContent = fmt(a + (to - a) * k); });
  }
  // Linear interpolation helper for tweens.
  const lerp = (a, b, k) => a + (b - a) * k;
  // Wait for web fonts and one animation frame so layout is final before you measure an element.
  const settle = () => new Promise((res) => {
    const done = () => requestAnimationFrame(() => requestAnimationFrame(res));
    try { if (document.fonts && document.fonts.ready) { Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 400))]).then(done, done); return; } } catch (e) {}
    done();
  });
  // Breadcrumb for drill-down: crumbs(['All sales', 'Outerwear'], (index) => jumpTo(index)) -> html.
  // Wire clicks with AZ.wireCrumbs(el, onJump). The last crumb is the current level and is not a button.
  const crumbs = (names) => '<nav class="az-crumbs" aria-label="Drill path">' + names.map((n, i) => (i < names.length - 1 ? '<button type="button" class="az-crumb" data-i="' + i + '">' + esc(n) + '</button><span class="az-sep">/</span>' : '<span class="az-crumb now">' + esc(n) + '</span>')).join('') + '</nav>';
  function wireCrumbs(root, onJump) { root.querySelectorAll('.az-crumb[data-i]').forEach((b) => b.addEventListener('click', () => onJump(Number(b.getAttribute('data-i'))))); }

  // boot({ need: 'plain-English list of what the search must return', render(ctx) })
  // ctx = { el, rows, schema, w, h, redraw }; render may be async and may return a cleanup fn.
  function boot(opts) {
    let el = null, cleanup = null, lastW = 0, lastH = 0, timer = null, running = false;
    const run = async (first) => {
      if (running) return; running = true;
      try {
        el = mount();
        const data = liveData();
        if (!data) {
          paint(el, '<div class="az-empty"><b>No data yet</b><span>Attach a search with: ' + esc(opts.need) + '</span></div>');
          return;
        }
        if (typeof cleanup === 'function') { try { cleanup(); } catch (e) {} cleanup = null; }
        const r = el.getBoundingClientRect();
        lastW = Math.round(r.width); lastH = Math.round(r.height);
        cleanup = await opts.render({ el, rows: data.rows, schema: data.schema, w: lastW, h: lastH, redraw: () => run(false) });
        // Smooth entrance on first paint, a soft cross-fade on every redraw (toggle, drill, resize).
        el.classList.remove('az-in', 'az-swap'); void el.offsetWidth; el.classList.add(first ? 'az-in' : 'az-swap');
      } catch (err) {
        console.error('[chart] render failed:', err);
        paint(el, '<pre class="az-err">' + esc(err && err.stack || err) + '</pre>');
      } finally {
        running = false;
        if (first) done();
      }
    };
    run(true);
    if (typeof ResizeObserver !== 'undefined') {
      // Observe the chart container itself: a Liveboard tile resizes while the window does not.
      new ResizeObserver(() => {
        const t = mount(), r = t.getBoundingClientRect();
        if (Math.abs(r.width - lastW) < 2 && Math.abs(r.height - lastH) < 2) return;
        clearTimeout(timer); timer = setTimeout(() => run(false), 120);
      }).observe(mount());
    }
  }

  // -- tooltip: one look for every tile ---------------------------------------
  // const tip = AZ.tip(el); tip.show(html, x, y) with x,y in px relative to el; tip.hide().
  function tip(root) {
    root.style.position = root.style.position || 'relative';
    const d = document.createElement('div');
    d.className = 'az-tip';
    root.appendChild(d);
    return {
      show(html, x, y) {
        d.innerHTML = html; d.style.opacity = '1';
        const rw = root.clientWidth, rh = root.clientHeight, w = d.offsetWidth, h = d.offsetHeight;
        let left = x + 14, top = y - h - 10;
        if (left + w > rw - 4) left = x - w - 14;
        if (left < 4) left = 4;
        if (top < 4) top = Math.min(rh - h - 4, y + 16);
        d.style.left = Math.round(left) + 'px'; d.style.top = Math.round(top) + 'px';
      },
      hide() { d.style.opacity = '0'; },
      el: d
    };
  }
  const row = (k, v, swatch) => '<div class="az-tr"><span class="az-tk">' + (swatch ? '<i style="background:' + swatch + '"></i>' : '') + esc(k) + '</span><span class="az-tv">' + esc(v) + '</span></div>';

  return { tip, row, settle, reduced, EASE, tween, animator, countUp, lerp, crumbs, wireCrumbs, T, FAMILY_OF, familyOf, familyColor, host, cellVal, liveData, col, num, ms, money, int, pct, pts, monthLabel, monthShort, year, isoDay, MON, ytd, loadScript, mount, paint, esc, boot };
})();
/* ==== end amuzing core ==== */

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

const CFG = {
  kind: 'banner', tab: '07  Next', question: 'What should we do?',
  need: 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly',
  prompts: ['Sales and units against last year, by item type', 'Stores below last year, year to date', 'Full year sales using last year for the rest'],
  next: 'Last tab. The filters apply to every tile.',
  build: function (rows, schema) {
    const M = monthly(rows, schema);
    const ys = AZ.ytd(M.map((r) => ({ t: r.t, v: r.s }))), yu = AZ.ytd(M.map((r) => ({ t: r.t, v: r.u })));
    if (!ys || ys.pct == null || !yu || yu.pct == null) return { lead: 'Include the latest months and the same months a year earlier to compare year to date.', stats: [] };
    const ppu = ys.cur / yu.cur / (ys.prev / yu.prev) - 1;
    const level = Math.abs(ys.pct) < 0.03;
    const tail = level ? 'Both are close to level, so the big steps are behind us. What is left to move is item mix and individual stores.' : (ys.pct < 0 ? 'Sales are still below last year, so the decline has not stopped.' : 'Sales are above last year, so the recovery is under way.');
    return {
      lead: 'Year to date through ' + ys.through + ', sales are ' + pct(ys.pct, 1, true) + ' and units ' + pct(yu.pct, 1, true) + ' on the same months a year earlier; price per unit is ' + pct(ppu, 1, true) + '. ' + tail,
      stats: [
        { v: pct(ys.pct, 1, true), k: 'Sales, year to date', note: money(ys.cur) + ' against ' + money(ys.prev) + ' in the same months a year earlier.' },
        { v: pct(yu.pct, 1, true), k: 'Units, year to date', note: AZ.int(yu.cur) + ' against ' + AZ.int(yu.prev) + ' in the same months a year earlier.' },
        { v: pct(ppu, 1, true), k: 'Price per unit, year to date', note: 'Sales per unit this year against the same months a year earlier.' }
      ]
    };
  }
};

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
