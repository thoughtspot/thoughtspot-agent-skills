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

// Search: [sales] [date].monthly
// Full-year outlook: actual months so far (ink, solid) plus the remaining months projected two ways (slate, dashed):
//   same months last year, and the average of the last 3 months carried forward.
// If the latest year is already complete (December present) it projects the next year instead.
// Interactions: scenario toggle, hover a month for actual or projected values.
let scen = 'both';

AZ.boot({
  need: 'sales and date at monthly grain, e.g. [sales] [date].monthly',
  render: async ({ el, rows, schema, redraw }) => {
    const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i);
    const M = rows.map((r) => ({ t: AZ.ms(r[dK]), v: AZ.num(r[sK]) })).filter((r) => isFinite(r.t)).sort((a, b) => a.t - b.t);
    if (M.length < 2) { AZ.paint(el, '<div class="az-empty"><b>Not enough months to project</b><span>Needs at least two months of [sales] [date].monthly.</span></div>'); return; }
    const byKey = {}; M.forEach((r) => { const d = new Date(r.t); byKey[d.getUTCFullYear() + '-' + d.getUTCMonth()] = r.v; });
    const last = M[M.length - 1].t, ly = AZ.year(last), lm = new Date(last).getUTCMonth();
    const complete = lm === 11, T = complete ? ly + 1 : ly, first = complete ? 0 : lm + 1;
    const recent = M.slice(-3), avg3 = recent.reduce((a, r) => a + r.v, 0) / recent.length;
    const get = (y, m) => byKey[y + '-' + m];
    // Per-month series for the target year
    const S = [];
    for (let m = 0; m < 12; m++) {
      const act = complete ? null : (m <= lm ? get(T, m) : null);
      const prevV = get(T - 1, m);
      const o = { m, act, prevV: prevV == null ? null : prevV, isAct: act != null };
      o.gap = !complete && m <= lm && act == null;
      if (!o.isAct && !o.gap) { o.a = prevV != null ? prevV : avg3; o.aFallback = prevV == null; o.b = avg3; }
      S.push(o);
    }
    const ytd = S.filter((o) => o.isAct).reduce((a, o) => a + o.act, 0), ytdPrev = S.filter((o) => o.isAct && o.prevV != null).reduce((a, o) => a + o.prevV, 0);
    const nAct = S.filter((o) => o.isAct).length, nPrevAct = S.filter((o) => o.isAct && o.prevV != null).length;
    const totA = ytd + S.filter((o) => o.a != null).reduce((a, o) => a + o.a, 0), totB = ytd + S.filter((o) => o.b != null).reduce((a, o) => a + o.b, 0);
    const prevYear = S.every((o) => o.prevV != null) ? S.reduce((a, o) => a + o.prevV, 0) : null;
    const showA = scen !== 'b', showB = scen !== 'a';
    const nGap = S.filter((o) => o.gap).length, remain = S.filter((o) => o.a != null).length, anyFb = S.some((o) => o.aFallback);

    const cA = AZ.T.slate[6], cB = AZ.T.slate[3];
    const dchg = !complete && nAct && nPrevAct === nAct && ytdPrev > 0 ? ytd / ytdPrev - 1 : null;
    let sub;
    if (complete) sub = '<b>' + ly + '</b> is complete in the data (' + AZ.money(prevYear != null ? prevYear : M.slice(-12).reduce((a, r) => a + r.v, 0), 1) + '), so this projects <b>' + T + '</b>.';
    else sub = 'Actual through <b>' + AZ.MON[lm] + '</b>: <b>' + AZ.money(ytd, 1) + '</b>' + (dchg != null ? ', ' + AZ.pct(dchg, 1, true) + ' on the same months of ' + (T - 1) : '') + '. ' + remain + ' month' + (remain === 1 ? '' : 's') + ' projected.' + (nGap ? ' ' + nGap + ' earlier month' + (nGap === 1 ? ' is' : 's are') + ' missing from the current filter, so totals cover the months present.' : '');
    const gapPct = totB ? Math.abs(totA - totB) / Math.max(totA, totB) : 0;
    const tail = 'The two scenarios end ' + AZ.money(Math.abs(totA - totB), 1) + ' apart (' + AZ.pct(gapPct, 1) + ').';

    el.innerHTML =
      '<div class="rr-top"><div class="rr-title">' + T + ' year-end outlook</div>'
      + '<div class="rr-seg" role="group" aria-label="Scenario"><button type="button" data-s="both" class="' + (scen === 'both' ? 'on' : '') + '">Both</button><button type="button" data-s="a" class="' + (scen === 'a' ? 'on' : '') + '">Last year</button><button type="button" data-s="b" class="' + (scen === 'b' ? 'on' : '') + '">3-month avg</button></div></div>'
      + '<div class="rr-sub">' + sub + '</div>'
      + '<div class="rr-tot"><div class="rr-t ' + (showA ? (scen === 'a' ? 'on' : '') : 'off') + '"><div class="l"><i style="border-color:' + cA + '"></i>Same months as ' + (T - 1) + '</div><div class="n">' + AZ.money(totA, 1) + '</div><div class="c">' + (prevYear ? AZ.pct(totA / prevYear - 1, 1, true) + ' on all of ' + (T - 1) : anyFb ? 'no ' + (T - 1) + ' months here, uses the average' : 'year-end total') + '</div></div>'
      + '<div class="rr-t ' + (showB ? (scen === 'b' ? 'on' : '') : 'off') + '"><div class="l"><i style="border-color:' + cB + '; border-top-style:dotted"></i>Last 3 months, carried on</div><div class="n">' + AZ.money(totB, 1) + '</div><div class="c">' + (prevYear ? AZ.pct(totB / prevYear - 1, 1, true) + ' on all of ' + (T - 1) : AZ.money(avg3, 1) + ' a month') + '</div></div></div>'
      + '<div class="rr-plot" id="rr-plot"></div>'
      + '<div class="rr-cap">' + AZ.esc(tail) + ' Projection, not a forecast.</div>';
    el.querySelectorAll('.rr-seg button').forEach((b) => b.addEventListener('click', () => { scen = b.getAttribute('data-s'); redraw(); }));

    const box = document.getElementById('rr-plot'), W = Math.max(200, box.clientWidth), H = Math.max(110, box.clientHeight);
    const pl = 40, pr = 40, pt = 14, pb = 20, iw = W - pl - pr, ih = H - pt - pb;
    const all = []; S.forEach((o) => { if (o.isAct) all.push(o.act); else if (!o.gap) { if (showA) all.push(o.a); if (showB) all.push(o.b); } if (complete && o.prevV != null) all.push(o.prevV); });
    let lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    const padY = (hi - lo || hi * 0.1 || 1) * 0.15; lo = Math.max(0, lo - padY); hi += padY;
    const step = (function () { const raw = (hi - lo) / 4, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; })();
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const X = (m) => pl + (m + 0.5) / 12 * iw, Y = (v) => pt + ih - (v - lo) / (hi - lo) * ih;
    let g = '';
    for (let v = lo; v <= hi + 1e-6; v += step) g += '<line x1="' + pl + '" x2="' + (W - pr) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '" stroke="' + AZ.T.grid + '"/><text x="' + (pl - 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="' + AZ.T.muted + '">' + AZ.money(v, 0) + '</text>';
    for (let m = 0; m < 12; m++) if (m % (iw < 300 ? 2 : 1) === 0) g += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle" font-size="11" fill="' + AZ.T.muted + '">' + AZ.MON[m] + '</text>';
    // Projection band
    const bx0 = first === 0 ? pl : (X(first - 1) + X(first)) / 2, bx1 = W - pr;
    g += '<rect x="' + bx0.toFixed(1) + '" y="' + pt + '" width="' + (bx1 - bx0).toFixed(1) + '" height="' + ih + '" fill="' + AZ.T.slate[0] + '" opacity=".85"/>'
      + '<text x="' + ((bx0 + bx1) / 2).toFixed(1) + '" y="' + (pt + 11) + '" text-anchor="middle" font-size="11" font-weight="600" letter-spacing=".08em" fill="' + AZ.T.slate[4] + '">PROJECTION</text>';
    const path = (pts) => pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(' ');
    if (complete) { const gp = S.filter((o) => o.prevV != null).map((o) => [o.m, o.prevV]); if (gp.length > 1) g += '<path d="' + path(gp) + '" fill="none" stroke="' + AZ.T.slate[2] + '" stroke-width="1.5"/><text x="' + (pl + 4) + '" y="' + (Y(gp[0][1]) - 8).toFixed(1) + '" font-size="11" fill="' + AZ.T.slate[4] + '">' + (T - 1) + ' actual</text>'; }
    const act = S.filter((o) => o.isAct).map((o) => [o.m, o.act]), lastAct = act.length ? act[act.length - 1] : null;
    const pa = (lastAct ? [lastAct] : []).concat(S.filter((o) => o.a != null).map((o) => [o.m, o.a])), pb2 = (lastAct ? [lastAct] : []).concat(S.filter((o) => o.b != null).map((o) => [o.m, o.b]));
    if (showA) g += '<path d="' + path(pa) + '" fill="none" stroke="' + cA + '" stroke-width="2" stroke-dasharray="6 4"/>';
    if (showB) g += '<path d="' + path(pb2) + '" fill="none" stroke="' + cB + '" stroke-width="2.25" stroke-dasharray="1 4" stroke-linecap="round"/>';
    if (act.length) g += '<path d="' + path(act) + '" fill="none" stroke="' + AZ.T.ink + '" stroke-width="2.25" stroke-linejoin="round"/><circle cx="' + X(lastAct[0]).toFixed(1) + '" cy="' + Y(lastAct[1]).toFixed(1) + '" r="3.5" fill="' + AZ.T.ink + '"/>';
    // End labels with a simple collision nudge
    const ends = []; if (showA) ends.push([S[11].a, cA]); if (showB) ends.push([S[11].b, cB]);
    ends.sort((p, q) => p[0] - q[0]);
    let prevY = null;
    ends.slice().reverse().forEach((e) => { let y = Y(e[0]); if (prevY != null && y - prevY < 13) y = prevY + 13; prevY = y; g += '<text x="' + (X(11) + 8).toFixed(1) + '" y="' + (y + 4).toFixed(1) + '" font-size="11" font-weight="600" fill="' + e[1] + '">' + AZ.money(e[0], 1) + '</text>'; });
    box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + T + ' outlook"><line id="rr-g" y1="' + pt + '" y2="' + (pt + ih) + '" stroke="' + AZ.T.ink2 + '" stroke-dasharray="2 3" opacity="0"/>' + g + '<g id="rr-d"></g></svg>';

    const tip = AZ.tip(box), guide = box.querySelector('#rr-g'), dots = box.querySelector('#rr-d'), NS = 'http://www.w3.org/2000/svg';
    const dot = (x, y, c, hollow) => { const e = document.createElementNS(NS, 'circle'); e.setAttribute('cx', x); e.setAttribute('cy', y); e.setAttribute('r', 4); e.setAttribute('fill', hollow ? '#fff' : c); e.setAttribute('stroke', c); e.setAttribute('stroke-width', 2); dots.appendChild(e); };
    box.addEventListener('mousemove', (e) => {
      const r = box.getBoundingClientRect(), px = (e.clientX - r.left) / r.width * W;
      const m = Math.max(0, Math.min(11, Math.round((px - pl) / iw * 12 - 0.5))), o = S[m];
      guide.setAttribute('x1', X(m)); guide.setAttribute('x2', X(m)); guide.setAttribute('opacity', 1); dots.innerHTML = '';
      const label = AZ.MON[m] + ' ' + T;
      let h;
      if (o.gap) {
        dots.innerHTML = '';
        h = '<b>' + label + '</b>' + AZ.row('Data', 'none in this filter');
      } else if (o.isAct) {
        dot(X(m), Y(o.act), AZ.T.ink, false);
        h = '<b>' + label + '</b>' + AZ.row('Actual', AZ.money(o.act, 2), '#FFFFFF') + (o.prevV != null ? AZ.row(AZ.MON[m] + ' ' + (T - 1), AZ.money(o.prevV, 2), AZ.T.slate[3]) + AZ.row('Change', AZ.pct(o.act / o.prevV - 1, 1, true)) : '');
      } else {
        h = '<b>' + label + ' (projected)</b>';
        if (showA) { dot(X(m), Y(o.a), cA, true); h += AZ.row('Same month ' + (T - 1) + (o.aFallback ? ' (none, uses 3-month avg)' : ''), AZ.money(o.a, 2), '#B4BDC9'); }
        if (showB) { dot(X(m), Y(o.b), cB, true); h += AZ.row('3-month average', AZ.money(o.b, 2), '#8E9AAB'); }
      }
      tip.show(h, X(m) / W * r.width, e.clientY - r.top);
    });
    box.addEventListener('mouseleave', () => { guide.setAttribute('opacity', 0); dots.innerHTML = ''; tip.hide(); });
  }
});
