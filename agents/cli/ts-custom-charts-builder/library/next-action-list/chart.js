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
// A short list of moves, each written in JS from the rows with its evidence number.
// Interactions: click a move to open or close its evidence, hover an evidence bar for the numbers.
let openIdx = 0;
const qOf = (t) => Math.floor(new Date(t).getUTCMonth() / 3);

AZ.boot({
  need: 'sales, quantity purchased, item type and date at quarterly grain, e.g. [sales] [quantity purchased] [item type] [date].quarterly',
  render: async ({ el, rows, schema }) => {
    const iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|quarter|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const R = rows.map((r) => ({ item: String(r[iK]), t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: AZ.num(r[uK]) })).filter((r) => isFinite(r.t));
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No rows in the current filter</b><span>Needs: [sales] [quantity purchased] [item type] [date].quarterly</span></div>'); return; }
    const last = Math.max.apply(null, R.map((r) => r.t)), ly = AZ.year(last), lq = qOf(last);
    const cur = R.filter((r) => AZ.year(r.t) === ly && qOf(r.t) <= lq), prev = R.filter((r) => AZ.year(r.t) === ly - 1 && qOf(r.t) <= lq);
    const nq = (a) => new Set(a.map((r) => r.t)).size;
    const comparable = prev.length > 0 && nq(prev) === nq(cur);
    const per = 'Q1 to Q' + (lq + 1) + ' ' + ly;

    const by = {};
    cur.forEach((r) => { const o = by[r.item] = by[r.item] || { item: r.item, s: 0, u: 0, ps: 0 }; o.s += r.s; o.u += r.u; });
    prev.forEach((r) => { if (by[r.item]) by[r.item].ps += r.s; });
    const I = Object.keys(by).map((k) => by[k]).filter((o) => o.s > 0 && o.u > 0);
    const totS = I.reduce((a, o) => a + o.s, 0), totU = I.reduce((a, o) => a + o.u, 0);
    I.forEach((o) => { o.share = o.s / totS; o.price = o.s / o.u; o.chg = comparable && o.ps > 0 ? o.s / o.ps - 1 : null; o.col = AZ.familyColor(o.item); });
    const avg = totU ? totS / totU : 0;
    const bar = (frac, col, lo) => '<div class="al-track"><div class="al-bar" style="left:' + (lo || 0).toFixed(1) + '%;width:' + Math.max(1, frac * 100).toFixed(1) + '%;background:' + col + '"></div></div>';
    const tipAttr = (h) => ' data-tip="' + AZ.esc(h) + '"';
    const moves = [];

    // 1. Highest sales per unit
    if (I.length >= 2) {
      const byP = I.slice().sort((a, b) => b.price - a.price), top = byP[0], mx = top.price;
      moves.push({
        h: 'Lead with ' + top.item, ev: AZ.money(top.price, 2),
        d: 'Earns ' + AZ.money(top.price, 2) + ' a unit, ' + (top.price / avg).toFixed(1) + 'x the ' + AZ.money(avg, 2) + ' average, and holds ' + AZ.pct(top.share, 1) + ' of sales.',
        body: byP.slice(0, 5).map((o, i) => '<div class="al-row' + (i ? '' : ' hot') + '"' + tipAttr('<b>' + o.item + '</b>' + AZ.row('Sales per unit', AZ.money(o.price, 2)) + AZ.row('Share of sales', AZ.pct(o.share, 1)) + AZ.row('Units', AZ.int(o.u))) + '><span class="k">' + AZ.esc(o.item) + '</span>' + bar(o.price / mx, o.col) + '<span class="v">' + AZ.money(o.price, 2) + '</span></div>').join('')
          + '<div class="al-note">Sales per unit, ' + per + '. ' + (I.length > 5 ? 'Top five of ' + I.length + ' types.' : 'All ' + I.length + ' types.') + '</div>'
      });
    }
    // 2. Year-to-date change is flat
    const V = I.filter((o) => o.chg != null);
    if (V.length >= 2) {
      const lo = Math.min.apply(null, V.map((o) => o.chg)), hi = Math.max.apply(null, V.map((o) => o.chg)), spread = hi - lo;
      const down = V.filter((o) => o.chg < 0).length, ext = Math.max(Math.abs(lo), Math.abs(hi)) || 0.01;
      const sorted = V.slice().sort((a, b) => a.chg - b.chg);
      const flat = spread < 0.05;
      moves.push({
        h: flat ? 'Do not reallocate on year-to-date trend' : 'Look first at ' + sorted[0].item,
        ev: (spread * 100).toFixed(1) + ' pts',
        d: flat ? down + ' of ' + V.length + ' types are down on last year, none by more than ' + Math.abs(lo * 100).toFixed(1) + '%. The widest gap between any two is ' + (spread * 100).toFixed(1) + ' points.'
          : sorted[0].item + ' is ' + AZ.pct(lo, 1, true) + ' on last year, the weakest of ' + V.length + ' types. The strongest is ' + sorted[V.length - 1].item + ' at ' + AZ.pct(hi, 1, true) + '.',
        body: sorted.map((o, i) => {
          const w = Math.abs(o.chg) / ext * 50, left = o.chg < 0 ? 50 - w : 50;
          return '<div class="al-row' + (i === 0 ? ' hot' : '') + '"' + tipAttr('<b>' + o.item + '</b>' + AZ.row('Change on last year', AZ.pct(o.chg, 1, true)) + AZ.row('Sales', AZ.money(o.s, 1)) + AZ.row('Same quarters last year', AZ.money(o.ps, 1))) + '><span class="k">' + AZ.esc(o.item) + '</span><div class="al-track"><div class="al-zero" style="left:50%"></div>' + '<div class="al-bar" style="left:' + left.toFixed(1) + '%;width:' + Math.max(1, w).toFixed(1) + '%;background:' + AZ.T.slate[4] + '"></div></div><span class="v">' + AZ.pct(o.chg, 1, true) + '</span></div>';
        }).join('') + '<div class="al-note">Sales ' + per + ' against Q1 to Q' + (lq + 1) + ' ' + (ly - 1) + '.</div>'
      });
    }
    // 3. Seasonality in the latest full calendar year
    const yq = {};
    R.forEach((r) => { const y = AZ.year(r.t), o = yq[y] = yq[y] || { q: {}, n: 0 }; if (o.q[qOf(r.t)] == null) { o.q[qOf(r.t)] = 0; o.n++; } o.q[qOf(r.t)] += r.s; });
    const full = Object.keys(yq).filter((y) => yq[y].n === 4).map(Number).sort((a, b) => a - b), fy = full.length ? full[full.length - 1] : null;
    if (fy != null) {
      const q = [0, 1, 2, 3].map((i) => yq[fy].q[i]), tot = q.reduce((a, b) => a + b, 0), pk = q.indexOf(Math.max.apply(null, q)), tr = q.indexOf(Math.min.apply(null, q)), mq = Math.max.apply(null, q);
      moves.push({
        h: 'Plan stock around Q' + (pk + 1), ev: AZ.pct(q[pk] / tot, 0),
        d: 'Q' + (pk + 1) + ' carried ' + AZ.pct(q[pk] / tot, 1) + ' of ' + fy + ' sales, Q' + (tr + 1) + ' only ' + AZ.pct(q[tr] / tot, 1) + '. The peak quarter is ' + (q[pk] / q[tr]).toFixed(2) + 'x the low one.',
        body: q.map((v, i) => '<div class="al-row' + (i === pk ? ' hot' : '') + '"' + tipAttr('<b>Q' + (i + 1) + ' ' + fy + '</b>' + AZ.row('Sales', AZ.money(v, 1)) + AZ.row('Share of year', AZ.pct(v / tot, 1))) + '><span class="k">Q' + (i + 1) + ' ' + fy + '</span>' + bar(v / mq, i === pk ? AZ.T.ink : AZ.T.slate[3]) + '<span class="v">' + AZ.pct(v / tot, 1) + '</span></div>').join('')
          + '<div class="al-note">Share of ' + fy + ' sales by quarter, the latest full year in the data.</div>'
      });
    }
    // 4. Concentration
    if (I.length >= 4) {
      const bs = I.slice().sort((a, b) => b.s - a.s), t3 = bs.slice(0, 3), t3s = t3.reduce((a, o) => a + o.share, 0), n5 = Math.min(5, Math.floor(I.length / 2)), low = bs.slice(-n5), lowS = low.reduce((a, o) => a + o.share, 0);
      let cum = 0;
      moves.push({
        h: 'Protect ' + t3.map((o) => o.item).join(', ').replace(/, ([^,]*)$/, ' and $1'), ev: AZ.pct(t3s, 0),
        d: 'The three largest of ' + I.length + ' types are ' + AZ.pct(t3s, 1) + ' of sales. The smallest ' + n5 + ' together are ' + AZ.pct(lowS, 1) + '.',
        body: bs.slice(0, 6).map((o, i) => { const st = cum; cum += o.share; return '<div class="al-row' + (i < 3 ? ' hot' : '') + '"' + tipAttr('<b>' + o.item + '</b>' + AZ.row('Share of sales', AZ.pct(o.share, 1)) + AZ.row('Running total', AZ.pct(cum, 1))) + '><span class="k">' + AZ.esc(o.item) + '</span>' + bar(o.share / bs[0].share * 0.62, o.col) + '<span class="v">' + AZ.pct(o.share, 1) + '</span></div>'; }).join('')
          + '<div class="al-note">Largest six by sales, ' + per + '. Bars are share of total sales.</div>'
      });
    }
    if (!moves.length) { AZ.paint(el, '<div class="az-empty"><b>Too little data for a recommendation</b><span>The current filter leaves fewer than two item types.</span></div>'); return; }
    if (openIdx >= moves.length) openIdx = 0;

    el.innerHTML = '<div><div class="al-title">' + moves.length + (moves.length === 1 ? ' move' : ' moves') + ' the numbers support</div><div class="al-sub">' + AZ.esc(per) + (comparable ? ' against the same quarters of ' + (ly - 1) : '') + '. Select a move for its evidence.</div></div>'
      + '<div class="al-list" id="al-list">' + moves.map((m, i) =>
        '<div class="al-item' + (i === openIdx ? ' open' : '') + '"><button type="button" class="al-btn" aria-expanded="' + (i === openIdx) + '"><span class="al-n">' + (i + 1) + '</span><span class="al-h">' + AZ.esc(m.h) + '</span><span class="al-ev">' + AZ.esc(m.ev) + '</span><span class="al-d">' + AZ.esc(m.d) + '</span></button><div class="al-body">' + m.body + '</div></div>').join('') + '</div>';
    const list = document.getElementById('al-list'), items = list.querySelectorAll('.al-item');
    items.forEach((it, i) => it.querySelector('.al-btn').addEventListener('click', () => {
      const was = it.classList.contains('open');
      items.forEach((o) => { o.classList.remove('open'); o.querySelector('.al-btn').setAttribute('aria-expanded', 'false'); });
      if (!was) { it.classList.add('open'); it.querySelector('.al-btn').setAttribute('aria-expanded', 'true'); }
      openIdx = was ? -1 : i;
    }));
    const tip = AZ.tip(el);
    list.addEventListener('mousemove', (e) => {
      const r = e.target.closest ? e.target.closest('.al-row') : null;
      if (!r) { tip.hide(); return; }
      const b = el.getBoundingClientRect();
      tip.show(r.getAttribute('data-tip'), e.clientX - b.left, e.clientY - b.top);
    });
    list.addEventListener('mouseleave', () => tip.hide());
  }
});
