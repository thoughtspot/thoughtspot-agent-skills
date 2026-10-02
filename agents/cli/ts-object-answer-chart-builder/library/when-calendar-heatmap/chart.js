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

// Search: [sales] [quantity purchased] [date].monthly
// Year x month grid on the slate ramp. Toggle Sales / Units / Price per unit (cells re-colour with a tween).
// Hover a cell for its value and the change on the same month a year earlier; click a cell (or a month name)
// to highlight that calendar month across every year. Click a year label to open that year: the grid morphs into
// twelve monthly columns with the previous year as a slate outline. Back, the crumb or Escape returns.
let mode = 'sales', selMonth = null, openYear = null;

const HM = {
  sales: { label: 'Sales', get: (r) => r.s, fmt: (v) => AZ.money(v, 1), fmtL: (v) => AZ.money(v, 1) },
  units: { label: 'Units', get: (r) => r.u, fmt: (v) => AZ.int(v), fmtL: (v) => AZ.int(v) },
  price: { label: 'Price per unit', get: (r) => (r.u ? r.s / r.u : null), fmt: (v) => '$' + v.toFixed(2), fmtL: (v) => '$' + v.toFixed(0) }
};

AZ.boot({
  need: 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly',
  render: async ({ el, rows, schema }) => {
    const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const M = rows.map((r) => ({ t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: AZ.num(r[uK]) })).filter((r) => isFinite(r.t)).sort((a, b) => a.t - b.t);
    if (!M.length) { AZ.paint(el, '<div class="az-empty"><b>No months in the result</b><span>The search needs [sales] [quantity purchased] [date].monthly</span></div>'); return; }
    const key = (y, m) => y * 12 + m;
    const cell = new Map();
    M.forEach((r) => { const d = new Date(r.t), k = key(d.getUTCFullYear(), d.getUTCMonth()); const c = cell.get(k) || { s: 0, u: 0, t: r.t }; c.s += r.s; c.u += r.u; cell.set(k, c); });
    const ys = Array.from(new Set(M.map((r) => AZ.year(r.t)))).sort((a, b) => a - b);
    const S = AZ.T.slate;
    const hex = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
    const rampA = (t) => { const p = Math.max(0, Math.min(1, t)) * (S.length - 1), i = Math.min(S.length - 2, Math.floor(p)), f = p - i, a = hex(S[i]), b = hex(S[i + 1]); return a.map((x, k) => x + (b[k] - x) * f).concat([1]); };
    const rgba = (c) => 'rgba(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ',' + c[3].toFixed(3) + ')';
    if (openYear != null && ys.indexOf(openYear) < 0) openYear = null;
    const anyIn = (m) => ys.some((y) => cell.has(key(y, m)));
    if (selMonth != null && !anyIn(selMonth)) selMonth = null;

    // Everything that depends on the measure.
    const calc = () => {
      const D = HM[mode];
      const val = (y, m) => { const c = cell.get(key(y, m)); return c ? D.get(c) : null; };
      const all = []; ys.forEach((y) => { for (let m = 0; m < 12; m++) { const v = val(y, m); if (v != null) all.push({ y, m, v }); } });
      const lo = Math.min.apply(null, all.map((c) => c.v)), hi = Math.max.apply(null, all.map((c) => c.v));
      const shade = (v) => rampA(hi === lo ? 0.5 : (v - lo) / (hi - lo));
      return { D, val, all, lo, hi, shade };
    };
    const ml = (c) => AZ.MON[c.m] + ' ' + c.y;
    const subFor = (C) => {
      const D = C.D, all = C.all;
      if (!all.length) return '';
      if (openYear != null) {
        const y = openYear, mine = all.filter((c) => c.y === y);
        const top = mine.reduce((b, c) => (c.v > b.v ? c : b), mine[0]), bot = mine.reduce((b, c) => (c.v < b.v ? c : b), mine[0]);
        let s = mine.length < 2 ? D.label + ' in ' + ml(mine[0]) + ': ' + D.fmt(mine[0].v) : '<b>' + y + '</b> ' + D.label.toLowerCase() + ' peaked in <b>' + AZ.MON[top.m] + '</b> at ' + D.fmt(top.v) + ', lowest in <b>' + AZ.MON[bot.m] + '</b> at ' + D.fmt(bot.v) + '.';
        const ms2 = mine.map((c) => c.m), same = ms2.every((m) => cell.has(key(y - 1, m)));
        if (same && ms2.length) {
          const agg = (yy) => { let s1 = 0, u1 = 0; ms2.forEach((m) => { const c = cell.get(key(yy, m)); s1 += c.s; u1 += c.u; }); return mode === 'sales' ? s1 : mode === 'units' ? u1 : (u1 ? s1 / u1 : 0); };
          const a = agg(y), b = agg(y - 1), rng = ms2.length === 12 ? '' : AZ.MON[ms2[0]] + ' to ' + AZ.MON[ms2[ms2.length - 1]] + ' ';
          if (b) s += ' ' + (mode === 'price' ? 'Average price is' : rng ? rng + D.label.toLowerCase() + ' are' : 'Full-year ' + D.label.toLowerCase() + ' is') + ' ' + AZ.pct(a / b - 1, 1, true) + ' against ' + rng + (y - 1) + '.';
        }
        return s;
      }
      const first = all[0], last = all[all.length - 1], top = all.reduce((b, c) => (c.v > b.v ? c : b), all[0]), bot = all.reduce((b, c) => (c.v < b.v ? c : b), all[0]);
      if (all.length < 2) return 'One month in the current filter: ' + ml(first) + ', ' + D.fmt(first.v);
      if (mode === 'price') return 'Price per unit went from <b>' + D.fmt(first.v) + '</b> in ' + ml(first) + ' to <b>' + D.fmt(last.v) + '</b> in ' + ml(last) + ' (' + AZ.pct(last.v / first.v - 1, 0, true) + ')';
      return D.label + ' peaked in <b>' + ml(top) + '</b> at ' + D.fmt(top.v) + ', lowest in <b>' + ml(bot) + '</b> at ' + D.fmt(bot.v);
    };

    const seg = ['sales', 'units', 'price'].map((k) => '<button type="button" data-k="' + k + '" class="' + (k === mode ? 'on' : '') + '">' + HM[k].label + '</button>').join('');
    el.innerHTML = '<div class="hm-top"><div class="hm-title"></div><div class="hm-seg" role="group" aria-label="Measure">' + seg + '</div></div><div class="hm-sub"></div><div class="hm-crumbrow"></div>'
      + '<div class="hm-wrap" id="hm-wrap"></div><div class="hm-leg"></div>';
    const titleEl = el.querySelector('.hm-title'), subEl = el.querySelector('.hm-sub'), crumbEl = el.querySelector('.hm-crumbrow'), legEl = el.querySelector('.hm-leg');
    const wrap = document.getElementById('hm-wrap');
    const flash = (n) => { n.classList.remove('hm-fade'); void n.offsetWidth; n.classList.add('hm-fade'); };
    let goTo = () => {}, C = calc(), update = () => {};
    const head = (fade) => {
      const D = C.D;
      titleEl.textContent = openYear != null ? D.label + ', ' + openYear : D.label + ' by month';
      subEl.innerHTML = subFor(C);
      if (openYear != null) {
        crumbEl.innerHTML = AZ.crumbs(['All years', String(openYear)]) + '<span class="hm-key"><i class="sol"></i>' + openYear + (ys.indexOf(openYear - 1) >= 0 ? ' <i class="out"></i>' + (openYear - 1) : '') + '</span><button type="button" class="hm-back">Back</button>';
        AZ.wireCrumbs(crumbEl, () => goTo(null));
        crumbEl.querySelector('.hm-back').addEventListener('click', () => goTo(null));
      } else crumbEl.innerHTML = '<span class="hm-hint">Click a year to open its months</span>';
      legEl.innerHTML = '<span>' + AZ.esc(D.fmtL(C.lo)) + '</span><div class="hm-ramp" style="background:linear-gradient(90deg,' + S.join(',') + ')"></div><span>' + AZ.esc(D.fmtL(C.hi)) + '</span>'
        + '<span class="hm-hint">' + (selMonth != null ? AZ.MON[selMonth] + ' highlighted, click to clear' : 'Click a cell to compare a month') + '</span>';
      if (fade) { flash(titleEl); flash(subEl); flash(crumbEl); }
    };

    head(false);
    // ---- geometry ----------------------------------------------------------------------------
    const Ww = wrap.clientWidth, Wh = wrap.clientHeight, n = ys.length;
    const X0 = 37, GAP = 3, cw = Math.max(4, (Ww - X0 - 11 * GAP) / 12), HDR = 18, Y0 = HDR + GAP;
    const rowH = Math.max(6, Math.min(52, (Wh - Y0 - GAP * (n - 1)) / n));
    const cx = (m) => X0 + m * (cw + GAP), ry = (i) => Y0 + i * (rowH + GAP);
    const T1 = HDR + GAP + 16, B1 = Math.max(T1 + 20, Wh - 4);
    const showVals = cw >= 34;

    // ---- items: every animated element carries a current record; update() tweens to the new target ----
    const items = [];
    const mk = (cls, html, apply) => { const d = document.createElement('div'); d.className = cls; if (html) d.innerHTML = html; wrap.appendChild(d); const it = { el: d, rec: null, apply, s: null, t: null }; items.push(it); return it; };
    const px = (v) => v.toFixed(2) + 'px';
    const applyCell = (it) => { const r = it.rec, e = it.el.style; e.left = px(r.x); e.top = px(r.y); e.width = px(r.w); e.height = px(r.h); e.backgroundColor = rgba(r.bg); e.opacity = r.op; e.zIndex = r.z || 0; if (!it.blank) e.borderColor = 'rgba(74,88,114,' + r.bd.toFixed(3) + ')'; };
    const applyTxt = (it) => { const r = it.rec, e = it.el.style; e.left = px(r.x); e.top = px(r.y); e.opacity = r.op; };
    const hdrs = [];
    for (let m = 0; m < 12; m++) {
      const it = mk('hm-mh', cw < 24 ? AZ.MON[m].charAt(0) : AZ.MON[m], applyTxt); it.el.setAttribute('data-m', m); it.el.style.width = px(cw); it.mh = m; hdrs.push(it);
      it.el.addEventListener('click', () => toggleMonth(m));
    }
    const yls = {};
    ys.forEach((y) => {
      const it = mk('hm-yh', String(y), applyTxt); it.el.setAttribute('data-y', y); it.el.tabIndex = 0; it.el.setAttribute('role', 'button'); it.el.setAttribute('aria-label', 'Open ' + y);
      it.el.addEventListener('click', () => goTo(y));
      it.el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goTo(y); } });
      yls[y] = it;
    });
    const cells = {};
    ys.forEach((y) => { for (let m = 0; m < 12; m++) { const has = cell.has(key(y, m)); const it = mk('hm-c' + (has ? '' : ' blank'), '', applyCell); it.blank = !has; it.el.setAttribute('data-y', y); it.el.setAttribute('data-m', m); cells[key(y, m)] = it; } });
    const vls = [];
    for (let m = 0; m < 12; m++) vls.push(mk('hm-vl', '', applyTxt));
    const base = mk('hm-base', '', (it) => { const r = it.rec, e = it.el.style; e.left = px(r.x); e.top = px(r.y); e.width = px(r.w); e.opacity = r.op; });
    const axT = mk('hm-ax', '', applyTxt), axB = mk('hm-ax', '0', applyTxt);
    axB.el.style.width = px(X0 - 8);

    // target records for the current state
    const targets = () => {
      const D = C.D, val = C.val, sh = C.shade;
      const T = new Map();
      const dimOp = (m) => (selMonth != null && selMonth !== m ? 0.25 : 1);
      const clear = [0, 0, 0, 0];
      hdrs.forEach((h) => T.set(h, { x: cx(h.mh), y: 0, op: selMonth != null && selMonth !== h.mh ? 0.25 : 1 }));
      const l0 = openYear == null;
      ys.forEach((y, i) => { T.set(yls[y], { x: 0, y: ry(i) + rowH / 2 - 8, op: l0 ? 1 : 0 }); });
      let maxV = 0;
      if (!l0) for (let m = 0; m < 12; m++) [openYear, openYear - 1].forEach((yy) => { const v = val(yy, m); if (v != null && v > maxV) maxV = v; });
      const hOf = (v) => (maxV ? Math.max(1, v / maxV * (B1 - T1)) : 1);
      ys.forEach((y, i) => {
        for (let m = 0; m < 12; m++) {
          const it = cells[key(y, m)], v = val(y, m);
          const flat = { x: cx(m), y: ry(i), w: cw, h: rowH };
          if (l0) {
            if (v == null) T.set(it, Object.assign(flat, { bg: clear, bd: 0, op: 1, z: 0 }));
            else T.set(it, Object.assign(flat, { bg: sh(v), bd: 0, op: dimOp(m), z: 0 }));
          } else if (v != null && y === openYear) {
            const h = hOf(v); T.set(it, { x: cx(m), y: B1 - h, w: cw, h: h, bg: sh(v), bd: 0, op: dimOp(m), z: 1 });
          } else if (v != null && y === openYear - 1) {
            const h = hOf(v); T.set(it, { x: cx(m), y: B1 - h, w: cw, h: h, bg: [255, 255, 255, 0], bd: 1, op: dimOp(m), z: 2 });
          } else T.set(it, Object.assign(flat, { bg: v == null ? clear : sh(v), bd: 0, op: 0, z: 0 }));
        }
      });
      const ay = openYear == null ? ys.length - 1 : ys.indexOf(openYear);
      for (let m = 0; m < 12; m++) {
        const v = l0 ? null : val(openYear, m);
        const vl = vls[m];
        vl.text = v == null ? '' : D.fmtL(v);
        T.set(vl, { x: cx(m) - 6, y: v == null ? ry(ay) : B1 - hOf(v) - 15, op: !l0 && v != null && showVals ? 1 : 0 });
      }
      T.set(base, { x: X0, y: B1, w: 12 * cw + 11 * GAP, op: l0 ? 0 : 1 });
      axT.text = D.fmtL(maxV || 0);
      T.set(axT, { x: 0, y: T1 - 17, op: l0 ? 0 : 1 });
      T.set(axB, { x: 0, y: B1 - 8, op: l0 ? 0 : 1 });
      return T;
    };
    const NUM = (a, b, k) => (Array.isArray(b) ? b.map((v, i) => AZ.lerp(a[i], v, k)) : typeof b === 'number' ? AZ.lerp(a, b, k) : b);
    let cancelT = null;
    update = (animate, ms) => {
      if (cancelT) { cancelT(); cancelT = null; }
      const T = targets();
      items.forEach((it) => {
        it.t = T.get(it);
        if (it.text != null) it.el.textContent = it.text;
        const first = !it.rec;
        it.s = first || !animate ? Object.assign({}, it.t) : Object.assign({}, it.rec);
        if (first) it.rec = Object.assign({}, it.t);
      });
      cancelT = AZ.tween(animate ? (ms || 480) : 0, (k) => {
        items.forEach((it) => {
          const r = {}; Object.keys(it.t).forEach((f) => { r[f] = NUM(it.s[f], it.t[f], k); });
          it.rec = r; it.apply(it);
        });
      }, () => { cancelT = null; }, AZ.EASE.inOut);
      wrap.classList.toggle('open', openYear != null);
    };

    // ---- interaction -------------------------------------------------------------------------
    const toggleMonth = (m) => { selMonth = selMonth === m ? null : m; head(false); update(true, 320); };
    goTo = (y) => { if (y === openYear) return; openYear = y; head(true); update(true, 520); };
    const onKey = (e) => { if (e.key === 'Escape' && openYear != null) { e.preventDefault(); goTo(null); } };
    document.addEventListener('keydown', onKey);
    el.querySelectorAll('.hm-seg button').forEach((b) => b.addEventListener('click', () => {
      mode = b.getAttribute('data-k'); C = calc();
      el.querySelectorAll('.hm-seg button').forEach((o) => o.classList.toggle('on', o === b));
      head(false); flash(subEl); flash(titleEl); update(true, 480);
    }));
    update(false);

    const tip = AZ.tip(wrap);
    let onCell = null;
    const hit = (e) => {
      const b = wrap.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
      if (x < X0 - 2 || y < Y0 - 2) return null;
      const m = Math.max(0, Math.min(11, Math.round((x - X0 - cw / 2) / (cw + GAP))));
      if (openYear != null) return { m, y: openYear, px: x, py: y, b };
      const i = Math.round((y - Y0 - rowH / 2) / (rowH + GAP));
      if (i < 0 || i >= n) return null;
      return { m, y: ys[i], px: x, py: y, b };
    };
    wrap.addEventListener('mousemove', (e) => {
      const h = hit(e);
      if (onCell) { onCell.el.classList.remove('hov'); onCell = null; }
      if (!h) { tip.hide(); return; }
      const v = C.val(h.y, h.m), pv = C.val(h.y - 1, h.m);
      if (v == null && openYear == null) { tip.hide(); return; }
      const c = cells[key(h.y, h.m)];
      if (v != null) { onCell = c; c.el.classList.add('hov'); }
      const D = C.D;
      let t = '<b>' + AZ.MON[h.m] + ' ' + h.y + '</b>' + (v != null ? AZ.row(D.label, D.fmt(v), '#FFFFFF') : AZ.row(D.label, 'no data'));
      if (pv != null) t += AZ.row(AZ.MON[h.m] + ' ' + (h.y - 1), D.fmt(pv), S[3]) + (pv && v != null ? AZ.row('Change', AZ.pct(v / pv - 1, 1, true)) : '');
      else t += AZ.row('A year earlier', 'no data');
      tip.show(t, e.clientX - h.b.left, e.clientY - h.b.top);
    });
    wrap.addEventListener('mouseleave', () => { if (onCell) { onCell.el.classList.remove('hov'); onCell = null; } tip.hide(); });
    wrap.addEventListener('click', (e) => { const h = hit(e); if (h && C.val(h.y, h.m) != null) toggleMonth(h.m); });
    return () => { if (cancelT) cancelT(); document.removeEventListener('keydown', onKey); };
  }
});
