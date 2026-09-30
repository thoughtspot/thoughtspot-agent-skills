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

// Search: [sales] [quantity purchased] [item type] [date].quarterly
// Item types as bubbles, area = sales in the year-to-date quarters, colour = editorial product family.
// x = share of sales. y = sales per unit (default) or change on the same quarters a year earlier.
// Interactions: hover for a tooltip, click a bubble or a family key to isolate, toggle the y measure.
let ymode = null;
let sel = null;

const qOf = (t) => Math.floor(new Date(t).getUTCMonth() / 3);
const niceTicks = (lo, hi, n) => {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  const st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, out = [];
  for (let v = Math.ceil(lo / st - 1e-9) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(10));
  return out;
};

AZ.boot({
  need: 'sales, quantity purchased, item type and date at quarterly grain, e.g. [sales] [quantity purchased] [item type] [date].quarterly',
  render: async ({ el, rows, schema, redraw }) => {
    const iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|quarter|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const R = rows.map((r) => ({ item: String(r[iK]), t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: AZ.num(r[uK]) })).filter((r) => isFinite(r.t));
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No rows in the current filter</b><span>Needs: [sales] [quantity purchased] [item type] [date].quarterly</span></div>'); return; }
    const last = Math.max.apply(null, R.map((r) => r.t)), ly = AZ.year(last), lq = qOf(last);
    const cur = R.filter((r) => AZ.year(r.t) === ly && qOf(r.t) <= lq), prev = R.filter((r) => AZ.year(r.t) === ly - 1 && qOf(r.t) <= lq);
    const nq = (a) => new Set(a.map((r) => r.t)).size;
    const comparable = prev.length > 0 && nq(prev) === nq(cur);
    const per = 'Q1 to Q' + (lq + 1) + ' ' + ly;
    const perPrev = 'Q1 to Q' + (lq + 1) + ' ' + (ly - 1);

    const by = {};
    cur.forEach((r) => { const o = by[r.item] = by[r.item] || { item: r.item, s: 0, u: 0, ps: 0, pu: 0 }; o.s += r.s; o.u += r.u; });
    prev.forEach((r) => { if (by[r.item]) { by[r.item].ps += r.s; by[r.item].pu += r.u; } });
    const I = Object.keys(by).map((k) => by[k]).filter((o) => o.s > 0);
    if (I.length < 2) { AZ.paint(el, '<div class="az-empty"><b>Only ' + I.length + ' item type in the current filter</b><span>The matrix needs at least two to compare.</span></div>'); return; }
    const totS = I.reduce((a, o) => a + o.s, 0), totU = I.reduce((a, o) => a + o.u, 0), totPS = I.reduce((a, o) => a + o.ps, 0);
    I.forEach((o) => {
      o.share = o.s / totS; o.ushare = totU ? o.u / totU : 0; o.price = o.u ? o.s / o.u : 0;
      o.chg = comparable && o.ps > 0 ? o.s / o.ps - 1 : null; o.fam = AZ.familyOf(o.item); o.col = AZ.familyColor(o.item);
    });
    const valid = I.filter((o) => o.chg != null), canChange = valid.length >= 2;
    const cLo = canChange ? Math.min.apply(null, valid.map((o) => o.chg)) : 0, cHi = canChange ? Math.max.apply(null, valid.map((o) => o.chg)) : 0;
    const spread = cHi - cLo, bands = canChange && spread >= 0.05;
    const totChg = comparable && totPS > 0 ? totS / totPS - 1 : null;
    if (ymode == null || (ymode === 'change' && !canChange)) ymode = bands ? 'change' : 'price';
    const M = ymode;
    const yOf = (o) => (M === 'price' ? o.price : o.chg);
    const overallPrice = totU ? totS / totU : 0;
    const big = I.slice().sort((a, b) => b.s - a.s)[0];
    const fams = []; I.slice().sort((a, b) => b.s - a.s).forEach((o) => { if (fams.indexOf(o.fam) < 0) fams.push(o.fam); });

    // Header sentences from the rows
    let sub = '<b>' + AZ.esc(big.item) + '</b> carry ' + AZ.pct(big.share, 1) + ' of sales from ' + AZ.pct(big.ushare, 1) + ' of units, at ' + AZ.money(big.price, 2) + ' a unit (' + AZ.money(overallPrice, 2) + ' overall).';
    if (canChange) {
      sub += spread < 0.05
        ? ' Year-to-date change is <b>' + AZ.pct(cLo, 1, true) + '</b> to <b>' + AZ.pct(cHi, 1, true) + '</b> for every type, so price and share are what differ.'
        : ' Year-to-date change runs from <b>' + AZ.pct(cLo, 1, true) + '</b> to <b>' + AZ.pct(cHi, 1, true) + '</b>.';
    }
    const title = M === 'price' ? 'Share of sales against price per unit' : 'Share of sales against year-to-date change';
    const cap = per + (comparable ? ' against ' + perPrev : '') + '. Area is sales; families are editorial.';

    el.innerHTML =
      '<div class="gm-head"><div class="gm-top"><div class="gm-title">' + title + '</div>'
      + '<div class="gm-seg" role="group" aria-label="Vertical measure"><button type="button" data-m="price" class="' + (M === 'price' ? 'on' : '') + '">Price per unit</button>'
      + '<button type="button" data-m="change" class="' + (M === 'change' ? 'on' : '') + '"' + (canChange ? '' : ' disabled title="No matching quarters a year earlier in the current filter"') + '>Change vs last year</button></div></div>'
      + '<div class="gm-sub">' + sub + '</div></div>'
      + '<div class="gm-plot" id="gm-plot"></div>'
      + '<div class="gm-key" id="gm-key">' + fams.map((f) => '<button type="button" data-f="' + AZ.esc(f) + '"><i style="background:' + AZ.T.family[f] + '"></i>' + AZ.esc(f) + '</button>').join('') + '</div>'
      + '<div class="gm-cap">' + AZ.esc(cap) + '</div>';
    el.querySelectorAll('.gm-seg button').forEach((b) => b.addEventListener('click', () => { if (b.disabled) return; ymode = b.getAttribute('data-m'); redraw(); }));

    const box = document.getElementById('gm-plot'), W = Math.max(200, box.clientWidth), H = Math.max(120, box.clientHeight);
    const pl = 46, pr = 12, pt = 20, pb = 28, iw = W - pl - pr, ih = H - pt - pb;
    const maxShare = Math.max.apply(null, I.map((o) => o.share));
    const xMax = maxShare * 1.18, xMin = 0;
    const ys = I.map(yOf).filter((v) => v != null);
    let yMin, yMax;
    if (M === 'price') { yMin = 0; yMax = Math.max.apply(null, ys) * 1.1; const tk = niceTicks(0, yMax, Math.max(3, Math.floor(ih / 52))); if (tk.length > 1) { const st = tk[1] - tk[0]; yMax = Math.ceil(yMax / st - 1e-9) * st; } }
    else { yMin = Math.min(0, Math.min.apply(null, ys)); yMax = Math.max(0, Math.max.apply(null, ys)); const pad = (yMax - yMin || 0.01) * 0.18; yMin -= pad; yMax += pad; }
    const X = (v) => pl + (v - xMin) / (xMax - xMin) * iw, Y = (v) => pt + ih - (v - yMin) / (yMax - yMin) * ih;
    const maxR = Math.max(12, Math.min(28, ih / 7, iw / 14)), maxS = Math.max.apply(null, I.map((o) => o.s));
    const rad = (o) => Math.max(4.5, maxR * Math.sqrt(o.s / maxS));

    const NS = 'http://www.w3.org/2000/svg';
    let g = '';
    const yt = niceTicks(yMin, yMax, Math.max(3, Math.floor(ih / 52)));
    yt.forEach((v) => {
      const lab = M === 'price' ? '$' + Math.round(v) : AZ.pct(v, Math.abs(yMax - yMin) < 0.05 ? 1 : 0, true);
      g += '<line x1="' + pl + '" x2="' + (W - pr) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" stroke="' + (M === 'change' && Math.abs(v) < 1e-9 ? AZ.T.ink2 : AZ.T.grid) + '" stroke-width="1"/>'
        + '<text x="' + (pl - 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="' + AZ.T.muted + '">' + lab + '</text>';
    });
    niceTicks(xMin, xMax, Math.max(3, Math.floor(iw / 80))).forEach((v) => {
      g += '<text x="' + X(v).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11" fill="' + AZ.T.muted + '">' + AZ.pct(v, 0) + '</text>';
    });
    g += '<text x="' + (pl + iw / 2) + '" y="' + (H + 1) + '" text-anchor="middle" font-size="11" fill="' + AZ.T.ink2 + '">Share of sales</text>';
    g += '<text x="' + pl + '" y="' + (pt - 10) + '" font-size="11" fill="' + AZ.T.ink2 + '">' + (M === 'price' ? 'Sales per unit' : 'Change on last year') + '</text>';
    if (M === 'price') { // overall price reference
      g += '<line x1="' + pl + '" x2="' + (W - pr) + '" y1="' + Y(overallPrice).toFixed(1) + '" y2="' + Y(overallPrice).toFixed(1) + '" stroke="' + AZ.T.slate[4] + '" stroke-dasharray="4 4"/>'
        + '<text x="' + (W - pr) + '" y="' + (Y(overallPrice) - 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="' + AZ.T.slate[4] + '">All types ' + AZ.money(overallPrice, 2) + '</text>';
    }
    if (bands && M === 'change') { // quadrant bands only when the spread justifies them
      const eq = 1 / I.length, rx = X(eq), ry = Y(totChg);
      g += '<line x1="' + rx.toFixed(1) + '" x2="' + rx.toFixed(1) + '" y1="' + pt + '" y2="' + (pt + ih) + '" stroke="' + AZ.T.slate[3] + '" stroke-dasharray="4 4"/>'
        + '<line x1="' + pl + '" x2="' + (W - pr) + '" y1="' + ry.toFixed(1) + '" y2="' + ry.toFixed(1) + '" stroke="' + AZ.T.slate[3] + '" stroke-dasharray="4 4"/>'
        + '<text x="' + (W - pr - 4) + '" y="' + (pt + 12) + '" text-anchor="end" font-size="11" fill="' + AZ.T.muted + '">Large and above total</text>'
        + '<text x="' + (pl + 4) + '" y="' + (pt + 12) + '" font-size="11" fill="' + AZ.T.muted + '">Small and above total</text>'
        + '<text x="' + (W - pr - 4) + '" y="' + (pt + ih - 5) + '" text-anchor="end" font-size="11" fill="' + AZ.T.muted + '">Large and below total</text>'
        + '<text x="' + (pl + 4) + '" y="' + (pt + ih - 5) + '" font-size="11" fill="' + AZ.T.muted + '">Small and below total</text>';
    }
    const isOn = (o) => !sel || (sel.k === 'item' ? o.item === sel.v : o.fam === sel.v);
    const drawn = I.filter((o) => yOf(o) != null).sort((a, b) => b.s - a.s);
    drawn.forEach((o) => {
      g += '<g class="gm-bub" data-i="' + AZ.esc(o.item) + '" opacity="' + (isOn(o) ? 1 : 0.25) + '">'
        + '<circle class="gm-c" cx="' + X(o.share).toFixed(1) + '" cy="' + Y(yOf(o)).toFixed(1) + '" r="' + rad(o).toFixed(1) + '" fill="' + o.col + '" fill-opacity=".8" stroke="' + (sel && sel.k === 'item' && sel.v === o.item ? AZ.T.ink : '#fff') + '" stroke-width="' + (sel && sel.k === 'item' && sel.v === o.item ? 2 : 1.5) + '"/>'
        + '<circle cx="' + X(o.share).toFixed(1) + '" cy="' + Y(yOf(o)).toFixed(1) + '" r="' + (rad(o) + 5).toFixed(1) + '" fill="transparent"/></g>';
    });
    // Direct labels: the four largest plus anything isolated; skip a label that would overlap one already placed
    const placed = [], labels = [];
    if (M === 'price') placed.push([W - pr - 104, Y(overallPrice) - 16, 104, 14]);
    const cand = drawn.filter((o) => isOn(o) && (sel ? true : drawn.indexOf(o) < 4));
    cand.forEach((o) => {
      const cx = X(o.share), cy = Y(yOf(o)), r = rad(o), tw = o.item.length * 6.4 + 2;
      const opts = [[cx + r + 4, cy + 4, 'start'], [cx - r - 4, cy + 4, 'end'], [cx, cy - r - 5, 'middle'], [cx, cy + r + 13, 'middle']];
      for (let k = 0; k < opts.length; k++) {
        const x0 = opts[k][2] === 'start' ? opts[k][0] : opts[k][2] === 'end' ? opts[k][0] - tw : opts[k][0] - tw / 2, y0 = opts[k][1] - 11;
        if (x0 < 2 || x0 + tw > W - 2 || y0 < 0 || y0 + 14 > H) continue;
        if (placed.some((b) => x0 < b[0] + b[2] && x0 + tw > b[0] && y0 < b[1] + b[3] && y0 + 14 > b[1])) continue;
        placed.push([x0, y0, tw, 14]);
        labels.push('<text x="' + opts[k][0].toFixed(1) + '" y="' + opts[k][1].toFixed(1) + '" text-anchor="' + opts[k][2] + '" font-size="11" font-weight="600" fill="' + AZ.T.ink + '" stroke="#fff" stroke-width="3" paint-order="stroke" pointer-events="none">' + AZ.esc(o.item) + '</text>');
        break;
      }
    });
    box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + AZ.esc(title) + '"><rect id="gm-bg" x="0" y="0" width="' + W + '" height="' + H + '" fill="transparent"/>' + g + labels.join('') + '</svg>';

    // Key state
    const kb = el.querySelectorAll('.gm-key button');
    kb.forEach((b) => {
      const f = b.getAttribute('data-f'), on = sel && sel.k === 'family' && sel.v === f;
      b.classList.toggle('on', !!on);
      b.classList.toggle('dim', !!sel && !on && !(sel.k === 'item' && AZ.familyOf(sel.v) === f));
      b.addEventListener('click', () => { sel = on ? null : { k: 'family', v: f }; redraw(); });
    });

    const tip = AZ.tip(box), byItem = {}; I.forEach((o) => { byItem[o.item] = o; });
    box.querySelectorAll('.gm-bub').forEach((n) => {
      const o = byItem[n.getAttribute('data-i')], c = n.querySelector('.gm-c');
      const move = (e) => {
        const r = box.getBoundingClientRect();
        let h = '<b>' + AZ.esc(o.item) + '</b>' + AZ.row(o.fam, '', o.col) + AZ.row('Sales', AZ.money(o.s, 1)) + AZ.row('Share of sales', AZ.pct(o.share, 1)) + AZ.row('Units', AZ.int(o.u) + ' (' + AZ.pct(o.ushare, 1) + ')') + AZ.row('Sales per unit', AZ.money(o.price, 2));
        h += o.chg != null ? AZ.row('Change on last year', AZ.pct(o.chg, 1, true)) : AZ.row('Change on last year', 'no comparison');
        tip.show(h, e.clientX - r.left, e.clientY - r.top);
      };
      n.addEventListener('mouseenter', (e) => { c.setAttribute('stroke', AZ.T.ink); c.setAttribute('stroke-width', 2); move(e); });
      n.addEventListener('mousemove', move);
      n.addEventListener('mouseleave', () => { const s = sel && sel.k === 'item' && sel.v === o.item; c.setAttribute('stroke', s ? AZ.T.ink : '#fff'); c.setAttribute('stroke-width', s ? 2 : 1.5); tip.hide(); });
      n.addEventListener('click', (e) => { e.stopPropagation(); sel = sel && sel.k === 'item' && sel.v === o.item ? null : { k: 'item', v: o.item }; redraw(); });
    });
    document.getElementById('gm-bg').addEventListener('click', () => { if (sel) { sel = null; redraw(); } });
  }
});
