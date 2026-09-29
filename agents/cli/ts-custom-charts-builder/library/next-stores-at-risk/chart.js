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

// Search: [sales] [store] [date].quarterly
// Bullet-style rows: each store's sales in the year-to-date quarters against the same quarters a year earlier.
// Bar runs from last year (the zero line) to this year's change; the shaded band is everything below the threshold.
// Interactions: threshold slider flags stores below it, hover for numbers, click a row to pin its detail.
let thr = -0.05;
let pinned = null;

const qOf = (t) => Math.floor(new Date(t).getUTCMonth() / 3);

AZ.boot({
  need: 'sales, store and date at quarterly grain, e.g. [sales] [store] [date].quarterly (quantity purchased is used when present)',
  render: async ({ el, rows, schema }) => {
    const nK = AZ.col(schema, /store/i), dK = AZ.col(schema, /date|quarter|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i, { optional: true });
    const R = rows.map((r) => ({ n: String(r[nK]), t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: uK ? AZ.num(r[uK]) : 0 })).filter((r) => isFinite(r.t));
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No rows in the current filter</b><span>Needs: [sales] [store] [date].quarterly</span></div>'); return; }
    const last = Math.max.apply(null, R.map((r) => r.t)), ly = AZ.year(last), lq = qOf(last);
    const cur = R.filter((r) => AZ.year(r.t) === ly && qOf(r.t) <= lq), prev = R.filter((r) => AZ.year(r.t) === ly - 1 && qOf(r.t) <= lq);
    const per = 'Q1 to Q' + (lq + 1) + ' ' + ly, perP = 'Q1 to Q' + (lq + 1) + ' ' + (ly - 1);
    const by = {};
    cur.forEach((r) => { const o = by[r.n] = by[r.n] || { n: r.n, s: 0, u: 0, ps: 0, pu: 0 }; o.s += r.s; o.u += r.u; });
    prev.forEach((r) => { if (by[r.n]) { by[r.n].ps += r.s; by[r.n].pu += r.u; } });
    const all = Object.keys(by).map((k) => by[k]);
    const S = all.filter((o) => o.ps > 0).map((o) => { o.chg = o.s / o.ps - 1; o.uchg = o.pu > 0 ? o.u / o.pu - 1 : null; return o; }).sort((a, b) => a.chg - b.chg);
    if (!S.length) { AZ.paint(el, '<div class="az-empty"><b>No year-earlier quarters to compare</b><span>The current filter has no ' + perP + ' rows for these stores.</span></div>'); return; }
    const skipped = all.length - S.length;
    const lo = Math.min(S[0].chg, -0.06) - 0.005, hi = Math.max(S[S.length - 1].chg, 0.02) + 0.005;
    const pos = (v) => (v - lo) / (hi - lo) * 100;

    el.innerHTML =
      '<div class="sr-top"><div><div class="sr-title">Stores against last year</div><div class="sr-sub">' + 'Sales, ' + AZ.esc(per) + ' against ' + AZ.esc(perP) + '</div></div>'
      + '<div class="sr-count"><div class="n" id="sr-n">0</div><div class="l" id="sr-l"></div></div></div>'
      + '<div class="sr-ctl"><label for="sr-in">Flag stores below</label><input id="sr-in" type="range" min="-6" max="2" step="0.5" value="' + (thr * 100) + '" aria-label="Threshold, percent change on last year"><span class="sr-val" id="sr-v"></span></div>'
      + '<div class="sr-msg" id="sr-m"></div>'
      + '<div class="sr-list"><div class="sr-rows" id="sr-rows"><div class="sr-overlay"><div class="sr-band" id="sr-band"></div><div class="sr-thr" id="sr-thr"></div></div>'
      + S.map((o, i) => '<div class="sr-row" data-i="' + i + '"><span class="k" title="' + AZ.esc(o.n) + '">' + AZ.esc(o.n) + '</span><div class="sr-track"><div class="sr-zero" style="left:' + pos(0).toFixed(2) + '%"></div><div class="sr-bar" style="left:' + pos(Math.min(0, o.chg)).toFixed(2) + '%;width:' + Math.max(0.8, Math.abs(pos(o.chg) - pos(0))).toFixed(2) + '%"></div></div><span class="v">' + AZ.pct(o.chg, 1, true) + '</span></div>').join('')
      + '</div></div>'
      + '<div class="sr-pinbox" id="sr-pin"></div>';

    const $ = (id) => document.getElementById(id), rowsEl = Array.prototype.slice.call(el.querySelectorAll('.sr-row'));
    const tip = AZ.tip(el);
    const detail = (o) => '<b>' + AZ.esc(o.n) + '</b>: ' + AZ.money(o.s, 2) + ' against ' + AZ.money(o.ps, 2) + ' (' + AZ.pct(o.chg, 1, true) + ')' + (o.uchg != null ? ', units ' + AZ.pct(o.uchg, 1, true) : '') + '.';
    function paintPin() {
      const o = S.find((x) => x.n === pinned);
      $('sr-pin').innerHTML = o ? detail(o) + ' Click the row again to unpin.' : 'Click a store to pin its numbers here.';
      rowsEl.forEach((r) => r.classList.toggle('pin', !!o && S[+r.getAttribute('data-i')].n === o.n));
    }
    function update() {
      const t = thr, flagged = S.filter((o) => o.chg < t - 1e-9);
      $('sr-n').textContent = flagged.length;
      $('sr-l').textContent = (flagged.length === 1 ? 'store' : 'stores') + ' of ' + S.length + ' below ' + AZ.pct(t, 1, true);
      $('sr-v').textContent = AZ.pct(t, 1, true);
      $('sr-in').setAttribute('aria-valuetext', AZ.pct(t, 1, true));
      const worst = S[0];
      $('sr-m').innerHTML = flagged.length
        ? 'Furthest below: <b>' + AZ.esc(worst.n) + '</b> at ' + AZ.pct(worst.chg, 1, true) + '.'
        : 'No store is below ' + AZ.pct(t, 1, true) + '. The lowest is <b>' + AZ.esc(worst.n) + '</b> at ' + AZ.pct(worst.chg, 1, true) + '. Move the slider to explore.'
        + (skipped ? ' ' + skipped + ' with no year-earlier quarters left out.' : '');
      rowsEl.forEach((r) => { const o = S[+r.getAttribute('data-i')], f = o.chg < t - 1e-9; r.classList.toggle('flag', f); });
      $('sr-thr').style.left = pos(t).toFixed(2) + '%';
      $('sr-band').style.width = Math.max(0, pos(t)).toFixed(2) + '%';
    }
    $('sr-in').addEventListener('input', (e) => { thr = Number(e.target.value) / 100; update(); });
    rowsEl.forEach((r) => {
      const o = S[+r.getAttribute('data-i')];
      const move = (e) => {
        const b = el.getBoundingClientRect();
        tip.show('<b>' + AZ.esc(o.n) + '</b>' + AZ.row(per, AZ.money(o.s, 2)) + AZ.row(perP, AZ.money(o.ps, 2)) + AZ.row('Change', AZ.pct(o.chg, 1, true)) + (o.uchg != null ? AZ.row('Units change', AZ.pct(o.uchg, 1, true)) : '') + AZ.row('Against threshold', o.chg < thr - 1e-9 ? 'below' : 'not below'), e.clientX - b.left, e.clientY - b.top);
      };
      r.addEventListener('mousemove', move); r.addEventListener('mouseleave', () => tip.hide());
      r.addEventListener('click', () => { pinned = pinned === o.n ? null : o.n; paintPin(); });
    });
    update(); paintPin();
  }
});
