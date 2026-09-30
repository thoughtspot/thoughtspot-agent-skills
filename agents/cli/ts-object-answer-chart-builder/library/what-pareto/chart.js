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

// Search: [product] [item type] [sales] [quantity purchased]
// Pareto: products ranked by sales (bars) with the cumulative share of sales (line) and a marker where it reaches 80%.
// Item type chips (top 6 plus All) re-rank the Pareto inside one item type; the bars and the line morph to the new ranking.
// Click a bar to open a detail card (sales, units and price against the item type average, rank in the item type) and an
// animated highlight along the cumulative line up to that product. Top 50 / All toggle. Escape or Close dismisses the card.
let view = 'all';
let scope = null; // item type, or null for all
let pinned = null; // product name
const ECH = ['https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js', 'https://unpkg.com/echarts@5/dist/echarts.min.js'];
const TOPCUT = 50;

AZ.boot({
  need: 'product, item type, sales and quantity purchased, e.g. [product] [item type] [sales] [quantity purchased]',
  render: async ({ el, rows, schema, w }) => {
    const pK = AZ.col(schema, /product/i), tK = AZ.col(schema, /item type|type/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i, { optional: true });
    const agg = new Map();
    rows.forEach((r) => {
      const k = String(r[pK]) + '||' + String(r[tK]);
      const o = agg.get(k) || { name: String(r[pK]), type: String(r[tK]), v: 0, u: 0 };
      o.v += AZ.num(r[sK]); if (uK) o.u += AZ.num(r[uK]); agg.set(k, o);
    });
    const ALL = Array.from(agg.values()).filter((r) => r.v > 0);
    if (ALL.length < 3) { AZ.paint(el, '<div class="az-empty"><b>Not enough products to rank</b><span>The current filter leaves ' + ALL.length + ' product with sales. Widen the filters, or the search needs: [product] [item type] [sales] [quantity purchased].</span></div>'); return; }
    await AZ.loadScript(ECH, () => !!window.echarts, 8000);

    ALL.forEach((r) => { r.color = AZ.familyColor(r.type); r.price = r.u ? r.v / r.u : null; });
    const TY = {};
    ALL.forEach((r) => { const t = TY[r.type] || (TY[r.type] = { n: 0, s: 0, u: 0, list: [] }); t.n++; t.s += r.v; t.u += r.u; t.list.push(r); });
    Object.keys(TY).forEach((k) => {
      const t = TY[k]; t.avgS = t.s / t.n; t.avgU = t.u / t.n; t.avgP = t.u ? t.s / t.u : null;
      const rk = (f, key) => t.list.slice().sort((a, b) => (f(b) == null ? -1e18 : f(b)) - (f(a) == null ? -1e18 : f(a))).forEach((r, i) => { r[key] = i + 1; });
      rk((r) => r.v, 'rkS'); rk((r) => r.u, 'rkU'); rk((r) => r.price, 'rkP');
    });
    const topTypes = Object.keys(TY).sort((a, b) => TY[b].s - TY[a].s).slice(0, 6);
    if (scope && topTypes.indexOf(scope) < 0) scope = null;
    if (pinned && !ALL.some((r) => r.name === pinned)) pinned = null;
    const grand = ALL.reduce((a, r) => a + r.v, 0);
    const overall = ALL.slice().sort((a, b) => b.v - a.v); overall.forEach((r, i) => { r.orank = i + 1; });
    const hasUnits = !!uK;

    el.innerHTML = '<div class="pa-head"><p class="pa-lead"></p>'
      + '<div class="pa-chips" role="group" aria-label="Item type">' + [null].concat(topTypes).map((t) => '<button type="button" class="pa-chip" data-t="' + AZ.esc(t || '') + '" aria-pressed="false">' + (t ? '<i style="background:' + AZ.familyColor(t) + '"></i>' + AZ.esc(t) : 'All') + '</button>').join('') + '</div>'
      + '<div class="pa-sub"><span class="pa-note"></span>'
      + '<div class="pa-seg" role="group" aria-label="Range"><button type="button" data-v="top">Top ' + TOPCUT + '</button><button type="button" data-v="all">All</button></div></div></div>'
      + '<div class="pa-plot" id="pa-plot"><div class="pa-cross"></div><div class="pa-card" role="dialog" aria-label="Product detail"></div></div>';
    const lead = el.querySelector('.pa-lead'), note = el.querySelector('.pa-note'), plot = el.querySelector('#pa-plot'), cx = el.querySelector('.pa-cross'), card = el.querySelector('.pa-card');
    const plotW = Math.max(200, plot.clientWidth), plotH = Math.max(140, plot.clientHeight);

    // ---- data for the current scope ---------------------------------------------------------
    let P = [], D = [], M = 0, N = 0, cross = 0, showN = 0, crossVisible = false;
    const compute = () => {
      P = (scope ? ALL.filter((r) => r.type === scope) : ALL).slice().sort((a, b) => b.v - a.v);
      const total = P.reduce((a, r) => a + r.v, 0) || 1; let run = 0;
      P.forEach((r, i) => { run += r.v; r.rank = i + 1; r.cum = run / total; r.share = r.v / grand; });
      cross = Math.max(0, P.findIndex((r) => r.cum >= 0.8)); N = cross + 1; M = P.length;
      showN = view === 'top' ? Math.min(TOPCUT, M) : M;
      D = P.slice(0, showN); crossVisible = cross < showN;
    };
    compute();

    const chart = echarts.init(plot, null, { renderer: 'svg', width: plotW, height: plotH });
    const font = AZ.T.font, ink = AZ.T.ink, slate = AZ.T.slate[5];
    const barColor = (r) => (pinned && r.name !== pinned ? 'rgba(30,30,36,0.28)' : ink);
    let first = true;
    const idxOfPinned = () => D.findIndex((r) => r.name === pinned);
    const build = () => {
      const interval = showN <= 12 ? 0 : (showN <= 60 ? 9 : Math.max(0, Math.round(showN / 6) - 1));
      const on = !AZ.reduced();
      return {
        animation: on, animationDuration: first ? 450 : 600, animationDurationUpdate: 600, animationEasing: 'cubicOut', animationEasingUpdate: 'cubicInOut',
        textStyle: { fontFamily: font },
        grid: { left: 46, right: 40, top: 12, bottom: 26 },
        xAxis: { type: 'category', data: D.map((r) => r.rank), axisTick: { show: false }, axisLine: { lineStyle: { color: AZ.T.grid } }, axisLabel: { color: AZ.T.muted, fontSize: 11, interval: interval, fontFamily: font } },
        yAxis: [
          { type: 'value', axisLabel: { color: AZ.T.muted, fontSize: 11, fontFamily: font, formatter: (v) => AZ.money(v, 0) }, splitLine: { lineStyle: { color: AZ.T.grid } }, axisLine: { show: false } },
          { type: 'value', min: 0, max: 1, interval: 0.2, axisLabel: { color: AZ.T.muted, fontSize: 11, fontFamily: font, formatter: (v) => Math.round(v * 100) + '%' }, splitLine: { show: false }, axisLine: { show: false } }
        ],
        series: [
          { id: 'bars', type: 'bar', data: D.map((r) => ({ value: r.v, itemStyle: { color: barColor(r) } })), barCategoryGap: showN > 80 ? '0%' : '25%', silent: true, z: 2 },
          {
            id: 'cum', type: 'line', yAxisIndex: 1, data: D.map((r) => r.cum), symbol: 'none', silent: true, z: 3, lineStyle: { color: slate, width: 2 },
            markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: AZ.T.slate[3], type: 'dashed', width: 1 }, data: crossVisible ? [{ yAxis: 0.8 }] : [] },
            markPoint: { silent: true, symbol: 'circle', symbolSize: 13, itemStyle: { color: '#fff', borderColor: ink, borderWidth: 2 },
              label: { show: true, position: 'bottom', distance: 8, color: ink, fontSize: 11, fontWeight: 600, fontFamily: font, formatter: () => '80% at #' + N },
              data: crossVisible ? [{ coord: [cross, P[cross].cum], value: 0 }] : [] }
          },
          { id: 'hl', type: 'line', yAxisIndex: 1, data: [], symbol: 'none', silent: true, z: 4, animation: false, lineStyle: { color: ink, width: 4, cap: 'round' },
            markPoint: { silent: true, animation: false, symbol: 'circle', symbolSize: 14, itemStyle: { color: ink, borderColor: '#fff', borderWidth: 2 }, label: { show: false }, data: [] } }
        ]
      };
    };

    const setText = () => {
      lead.textContent = N + ' of ' + M + ' products make 80% of sales' + (scope ? ' in ' + scope : '');
      if (pinned) { const r = ALL.find((x) => x.name === pinned); const pr = P.find((x) => x.name === pinned); note.innerHTML = 'Open <b>' + (pr ? '#' + pr.rank + ' ' : '') + AZ.esc(r.name) + '</b>, ' + AZ.money(r.v, 1) + (pr ? ', ' + AZ.pct(pr.cum, 1) + ' cumulative' : ', outside this item type'); }
      else note.textContent = crossVisible ? 'Click a bar to open its detail.' : 'The 80% mark is at product ' + N + ', past the top ' + showN + '. Click a bar to open its detail.';
      el.querySelectorAll('.pa-chip').forEach((b) => b.setAttribute('aria-pressed', (b.getAttribute('data-t') || null) === scope ? 'true' : 'false'));
      el.querySelectorAll('.pa-seg button').forEach((b) => b.classList.toggle('on', b.getAttribute('data-v') === view));
    };

    // ---- highlight along the cumulative line -------------------------------------------------
    let kk = 0, cancelHl = null, cancelCard = null, cancelBars = null;
    const drawHl = (k) => {
      const n = Math.max(0, Math.min(showN - 1, k));
      const upto = Math.floor(n), frac = n - upto;
      const head = upto + 1 < showN && frac > 0 ? AZ.lerp(D[upto].cum, D[upto + 1].cum, frac) : D[upto] ? D[upto].cum : 0;
      const dd = D.map((r, i) => (i <= upto ? r.cum : null));
      if (upto + 1 < showN && frac > 0) dd[upto + 1] = head;
      chart.setOption({ series: [{ id: 'hl', data: dd, markPoint: { data: [{ coord: [n, head], value: 0 }] } }] });
    };
    const clearHl = () => { chart.setOption({ series: [{ id: 'hl', data: [], markPoint: { data: [] } }] }); };
    const moveHl = (ms) => {
      if (cancelHl) { cancelHl(); cancelHl = null; }
      const i = pinned ? idxOfPinned() : -1;
      if (i < 0) {
        if (kk > 0 || true) { const k0 = kk; cancelHl = AZ.tween(ms ? 250 : 0, (k) => { if (k >= 1) { kk = 0; clearHl(); } else drawHl(Math.max(0, k0 * (1 - k))); }, null, AZ.EASE.inOut); }
        return;
      }
      const k0 = Math.min(kk, showN - 1);
      cancelHl = AZ.tween(ms || 0, (k) => { kk = AZ.lerp(k0, i, k); drawHl(kk); }, () => { kk = i; drawHl(i); }, AZ.EASE.inOut);
    };

    // ---- detail card -------------------------------------------------------------------------
    const cardHTML = (r) => {
      const t = TY[r.type], solo = t.n < 2;
      const ms = [{ name: 'Sales', v: r.v, a: t.avgS, f: (v) => AZ.money(v, v >= 1e6 ? 2 : 0) }];
      if (hasUnits) ms.push({ name: 'Units', v: r.u, a: t.avgU, f: (v) => Math.round(v).toLocaleString('en-US') }, { name: 'Price', v: r.price, a: t.avgP, f: (v) => '$' + v.toFixed(2) });
      let h = '<div class="pa-ch"><i style="background:' + r.color + '"></i><b>' + AZ.esc(r.name) + '</b><button type="button" class="pa-x">Close</button></div>'
        + '<div class="pa-cs">' + AZ.esc(r.type) + ': ' + (solo ? 'the only product of this item type' : '#' + r.rkS + ' of ' + t.n + ' by sales' + (hasUnits ? ', #' + r.rkU + ' by units' + (r.rkP ? ', #' + r.rkP + ' by price' : '') : '')) + '. Overall #' + r.orank + ' of ' + ALL.length + ', ' + AZ.pct(r.v / grand, 1) + ' of sales.</div>';
      ms.forEach((m) => {
        if (m.v == null) return;
        const mx = Math.max(m.v, m.a || 0) || 1;
        h += '<div class="pa-mr"><span class="pa-mn">' + m.name + '</span><div class="pa-bars">'
          + '<div class="pa-bt"><span class="pa-bar" data-w="' + (m.v / mx * 100).toFixed(2) + '" style="background:' + r.color + '"></span><em>' + AZ.esc(m.f(m.v)) + '</em></div>'
          + '<div class="pa-bt"><span class="pa-bar av" data-w="' + ((m.a || 0) / mx * 100).toFixed(2) + '"></span><em>' + AZ.esc(m.a == null ? '-' : m.f(m.a)) + ' type avg</em></div></div>'
          + '<span class="pa-md">' + (solo || !m.a ? '' : AZ.pct(m.v / m.a - 1, 0, true)) + '</span></div>';
      });
      return h;
    };
    const showCard = (r) => {
      if (cancelCard) { cancelCard(); cancelCard = null; } if (cancelBars) { cancelBars(); cancelBars = null; }
      card.innerHTML = cardHTML(r); card.classList.add('on');
      const bars = Array.from(card.querySelectorAll('.pa-bar')), fin = (k) => bars.forEach((b) => { b.style.width = (parseFloat(b.getAttribute('data-w')) * k).toFixed(2) + '%'; });
      fin(0);
      card.querySelector('.pa-x').addEventListener('click', () => pin(null));
      cancelCard = AZ.tween(300, (k) => { card.style.opacity = k; card.style.transform = 'translateY(' + ((1 - k) * 10).toFixed(1) + 'px)'; }, null, AZ.EASE.out);
      cancelBars = AZ.tween(600, fin, null, AZ.EASE.out);
    };
    const hideCard = () => {
      if (cancelCard) { cancelCard(); cancelCard = null; } if (cancelBars) { cancelBars(); cancelBars = null; }
      const o = parseFloat(card.style.opacity) || 1;
      cancelCard = AZ.tween(200, (k) => { card.style.opacity = o * (1 - k); }, () => { card.classList.remove('on'); cancelCard = null; }, AZ.EASE.out);
    };
    const recolour = () => chart.setOption({ animationDurationUpdate: 300, series: [{ id: 'bars', data: D.map((r) => ({ value: r.v, itemStyle: { color: barColor(r) } })) }] });
    const pin = (name) => {
      pinned = name; setText(); recolour();
      if (name) { showCard(ALL.find((r) => r.name === name)); moveHl(500); } else { hideCard(); moveHl(300); }
    };
    const refresh = () => {
      compute(); setText();
      const inScope = pinned && ALL.find((r) => r.name === pinned);
      if (pinned && scope && inScope && inScope.type !== scope) { pinned = null; hideCard(); setText(); }
      if (cancelHl) { cancelHl(); cancelHl = null; }
      kk = 0; chart.setOption({ series: [{ id: 'hl', data: [], markPoint: { data: [] } }] });
      chart.setOption(build());
      first = false;
      if (pinned) moveHl(650);
    };

    el.querySelectorAll('.pa-seg button').forEach((b) => b.addEventListener('click', () => { view = b.getAttribute('data-v'); refresh(); }));
    el.querySelectorAll('.pa-chip').forEach((b) => b.addEventListener('click', () => { scope = b.getAttribute('data-t') || null; refresh(); }));
    const onKey = (e) => { if (e.key === 'Escape' && pinned) { e.preventDefault(); pin(null); } };
    document.addEventListener('keydown', onKey);
    card.addEventListener('click', (e) => e.stopPropagation());
    card.addEventListener('mousemove', (e) => e.stopPropagation());

    setText();
    chart.setOption(build());
    first = false;
    if (pinned) { const r = ALL.find((x) => x.name === pinned); showCard(r); moveHl(0); }

    const tip = AZ.tip(plot);
    const idxAt = (x, y) => {
      if (!chart.containPixel({ gridIndex: 0 }, [x, y])) return -1;
      const i = Math.round(chart.convertFromPixel({ xAxisIndex: 0 }, x));
      return i >= 0 && i < showN ? i : -1;
    };
    const xOf = (i) => chart.convertToPixel({ xAxisIndex: 0 }, i);
    const at = (e) => { const r = plot.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    plot.addEventListener('mousemove', (e) => {
      const q = at(e), i = idxAt(q[0], q[1]);
      if (i < 0) { cx.style.opacity = 0; tip.hide(); return; }
      const r = D[i];
      cx.style.left = xOf(i) + 'px'; cx.style.opacity = 1;
      tip.show('<b>' + AZ.esc(r.name) + '</b>' + AZ.row('Rank', '#' + r.rank + ' of ' + M) + AZ.row(r.type, '', r.color) + AZ.row('Sales', AZ.money(r.v, 2), '#FFFFFF') + AZ.row('Cumulative share', AZ.pct(r.cum, 1), slate), q[0], q[1]);
    });
    plot.addEventListener('mouseleave', () => { cx.style.opacity = 0; tip.hide(); });
    plot.addEventListener('click', (e) => {
      const q = at(e), i = idxAt(q[0], q[1]);
      if (i < 0) { if (pinned) pin(null); return; }
      pin(pinned === D[i].name ? null : D[i].name);
    });
    return () => { if (cancelHl) cancelHl(); if (cancelCard) cancelCard(); if (cancelBars) cancelBars(); document.removeEventListener('keydown', onKey); try { chart.dispose(); } catch (e) {} };
  }
});
