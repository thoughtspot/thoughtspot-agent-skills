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


// Search: [sales] [quantity purchased] [region] [state] [item type]
// Pivot table: regions (expand to states) down, product families (expand to item types) across, with a Total
// column and a Total row. Measure toggle: Sales / Units / Price per unit. Price per unit is sum(sales) / sum(units)
// at every level (cells, subtotals, grand total), never an average of ratios, so every total matches ThoughtSpot.
// Interactions: hover a cell (row and column highlight, tooltip with shares and price against the region); click a
// region row to show its states; click a family header to show its item types; Expand all / Collapse all; measure
// toggle tweens the share bars. Expand and measure state live in module scope and survive redraw and filters.
let measure = 'sales', openRegs = null, openFams = new Set(), userRegs = false;

AZ.boot({
  need: 'sales, quantity purchased, region, state and item type, e.g. [sales] [quantity purchased] [region] [state] [item type]',
  render: async ({ el, rows, schema, w }) => {
    const rK = AZ.col(schema, /^region/i), stK = AZ.col(schema, /state/i), tK = AZ.col(schema, /item type|type/i);
    const sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const add = (o, it, s, u) => { const c = o[it] || (o[it] = { s: 0, u: 0 }); c.s += s; c.u += u; };
    const REG = new Map(), grand = {}, itemS = {};
    rows.forEach((r) => {
      const R = String(r[rK] == null ? '(blank)' : r[rK]), st = String(r[stK] == null ? '(blank)' : r[stK]), it = String(r[tK] == null ? '(blank)' : r[tK]);
      const s = AZ.num(r[sK]), u = AZ.num(r[uK]);
      let g = REG.get(R); if (!g) { g = { name: R, items: {}, states: new Map() }; REG.set(R, g); }
      let x = g.states.get(st); if (!x) { x = { name: st, items: {} }; g.states.set(st, x); }
      add(g.items, it, s, u); add(x.items, it, s, u); add(grand, it, s, u); itemS[it] = (itemS[it] || 0) + s;
    });
    const tot = (items, list) => { let s = 0, u = 0; (list || Object.keys(items)).forEach((k) => { const c = items[k]; if (c) { s += c.s; u += c.u; } }); return { s, u }; };
    const price = (v) => (v.u ? v.s / v.u : null);
    const G = tot(grand);
    if (!REG.size || (!G.s && !G.u)) { el.innerHTML = '<div class="az-empty"><b>Nothing to pivot</b><span>The search returned no sales. Search: [sales] [quantity purchased] [region] [state] [item type]</span></div>'; return; }

    // Families in the Liveboard's fixed order; item types inside a family by sales.
    const famOrder = Object.keys(AZ.T.family).concat(['Other']);
    const FAM = {};
    Object.keys(itemS).forEach((it) => { const f = AZ.familyOf(it); (FAM[f] || (FAM[f] = [])).push(it); });
    const fams = famOrder.filter((f) => FAM[f]).map((f) => ({ name: f, color: AZ.T.family[f] || AZ.T.muted, items: FAM[f].sort((a, b) => itemS[b] - itemS[a]) }));
    const regs = Array.from(REG.values()).map((g) => ({ name: g.name, items: g.items, t: tot(g.items), states: Array.from(g.states.values()).map((x) => ({ name: x.name, items: x.items, t: tot(x.items) })).sort((a, b) => b.t.s - a.t.s) })).sort((a, b) => b.t.s - a.t.s);

    // Re-resolve UI state against the rows in hand (a filter may have removed a region or a family).
    if (userRegs && openRegs != null) openRegs = new Set(Array.from(openRegs).filter((n) => regs.some((g) => g.name === n)));
    openFams = new Set(Array.from(openFams).filter((n) => fams.some((f) => f.name === n)));

    // Headline: price per unit by region, highest against lowest; then the family spread.
    const pr = regs.filter((g) => g.t.u).map((g) => ({ name: g.name, p: g.t.s / g.t.u })).sort((a, b) => b.p - a.p);
    const fp = fams.map((f) => { const v = tot(grand, f.items); return { name: f.name, p: price(v) }; }).filter((f) => f.p != null).sort((a, b) => b.p - a.p);
    const $p = (v) => '$' + v.toFixed(2);
    const narrow = w < 460, tiny = w < 360;
    let head;
    if (pr.length >= 2) {
      const hi = pr[0], lo = pr[pr.length - 1];
      head = '<b>' + AZ.esc(hi.name) + '</b> sells at ' + $p(hi.p) + ' per unit, ' + AZ.pct(hi.p / lo.p - 1, 1) + ' above <b>' + AZ.esc(lo.name) + '</b> (' + $p(lo.p) + ').';
    } else {
      head = '<b>' + AZ.esc(regs[0].name) + '</b>: ' + AZ.money(G.s, 1) + ' of sales at ' + (G.u ? $p(G.s / G.u) : '-') + ' per unit.';
    }
    if (!narrow && fp.length >= 2) head += ' Price per unit by family runs from ' + $p(fp[fp.length - 1].p) + ' (' + AZ.esc(fp[fp.length - 1].name) + ') to ' + $p(fp[0].p) + ' (' + AZ.esc(fp[0].name) + ').';

    const MEAS = [{ k: 'sales', t: 'Sales' }, { k: 'units', t: 'Units' }, { k: 'price', t: narrow ? 'Price' : 'Price per unit' }];
    el.innerHTML =
      '<div class="pv-head">' + head + '</div>'
      + '<div class="pv-ctl"><div class="pv-seg" role="group" aria-label="Measure">' + MEAS.map((m) => '<button type="button" data-m="' + m.k + '" aria-pressed="' + (measure === m.k) + '">' + m.t + '</button>').join('') + '</div>'
      + '<span class="pv-sp"></span>' + (tiny ? '<button type="button" class="pv-btn" data-a="flip"></button>' : '<button type="button" class="pv-btn" data-a="open" aria-label="Show the states of every region">' + (narrow ? 'Expand' : 'Expand all') + '</button><button type="button" class="pv-btn" data-a="close" aria-label="Hide all states and item types">' + (narrow ? 'Collapse' : 'Collapse all') + '</button>') + '</div>'
      + '<div class="pv-wrap" tabindex="0" aria-label="Pivot table, scrollable"></div>'
      + '<div class="pv-foot"></div>';
    const wrap = el.querySelector('.pv-wrap'), foot = el.querySelector('.pv-foot');
    const tipRoot = document.createElement('div'); tipRoot.className = 'pv-tiproot'; tipRoot.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:6'; el.appendChild(tipRoot);
    const tip = AZ.tip(tipRoot);
    await AZ.settle();
    const W = wrap.clientWidth;
    const firstW = W >= 600 ? 138 : W >= 400 ? 112 : 92;
    const nBase = fams.length + 1;
    const colW = Math.max(narrow ? 72 : 66, Math.min(nBase <= 3 ? 180 : 170, Math.floor((W - firstW - 2) / nBase)));
    const RH = 24;
    // First view: open the largest region when its states fit without scrolling (or when it is the only region).
    if (!userRegs || openRegs == null) openRegs = new Set(regs.length === 1 || wrap.clientHeight >= (regs.length + regs[0].states.length + 1) * RH + 64 ? [regs[0].name] : []);

    const fmt = (v) => {
      if (measure === 'price') return v.u ? $p(v.s / v.u) : '-';
      const n = measure === 'units' ? v.u : v.s;
      if (!n && !v.u) return '-';
      return measure === 'units' ? AZ.int(n) : AZ.money(n, n >= 1e6 ? 1 : 0);
    };
    const vol = (v) => (measure === 'units' ? v.u : v.s); // share-of-row basis (sales in price mode)
    const chev = '<svg class="pv-chev" viewBox="0 0 8 8" aria-hidden="true"><path d="M2.5 1.2 5.6 4 2.5 6.8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    let cols = [], rowsV = [], go = AZ.animator(), timers = [];
    const layout = () => {
      cols = [];
      fams.forEach((f) => {
        cols.push({ key: 'F|' + f.name, kind: 'fam', f, name: f.name, list: f.items, w: colW, open: openFams.has(f.name) });
        if (openFams.has(f.name)) f.items.forEach((it) => cols.push({ key: 'I|' + it, kind: 'item', f, name: it, list: [it], w: colW }));
      });
      cols.push({ key: 'T', kind: 'total', name: 'Total', list: null, w: colW });
      rowsV = [];
      regs.forEach((g) => {
        const open = openRegs.has(g.name);
        rowsV.push({ key: 'R|' + g.name, kind: 'reg', name: g.name, reg: g, items: g.items, t: g.t, open });
        if (open) g.states.forEach((x) => rowsV.push({ key: 'S|' + g.name + '|' + x.name, kind: 'st', name: x.name, reg: g, items: x.items, t: x.t }));
      });
    };
    const cellHTML = (r, c, ci) => {
      const v = tot(r.items, c.list), share = c.kind === 'total' ? null : (vol(r.t) ? vol(v) / vol(r.t) : 0);
      const bw = share == null ? 0 : Math.max(0, Math.min(100, share / maxShare * 100));
      return '<td data-ci="' + ci + '" class="' + c.kind + '"><div class="c" data-k="' + AZ.esc(r.key + '#' + c.key) + '">' + (share == null ? '' : '<span class="b"><i data-w="' + bw.toFixed(2) + '" style="width:' + bw.toFixed(2) + '%"></i></span>') + '<span class="n' + (v.s || v.u ? '' : ' z') + '">' + fmt(v) + '</span></div></td>';
    };
    let maxShare = 1;
    // Keep the swatch on the same line as the first word, so a wrapped name never leaves it alone.
    const famLabel = (f) => '<span class="fk"><i style="background:' + f.color + '"></i>' + chev + '</span><span class="fn">' + AZ.esc(f.name) + '</span>';
    const build = () => {
      layout();
      maxShare = 0;
      rowsV.concat([{ items: grand, t: G }]).forEach((r) => cols.forEach((c) => { if (c.kind !== 'total' && vol(r.t)) maxShare = Math.max(maxShare, vol(tot(r.items, c.list)) / vol(r.t)); }));
      maxShare = maxShare || 1;
      const tw = firstW + cols.reduce((a, c) => a + c.w, 0);
      const anyOpen = cols.some((c) => c.kind === 'item');
      let h = '<table class="pv" style="width:' + tw + 'px"><colgroup><col style="width:' + firstW + 'px">' + cols.map((c) => '<col data-k="' + AZ.esc(c.key) + '" style="width:' + c.w + 'px">').join('') + '</colgroup><thead><tr>'
        + '<th class="rh" rowspan="' + (anyOpen ? 2 : 1) + '"><span>Region / state</span></th>';
      fams.forEach((f) => {
        const open = openFams.has(f.name);
        h += '<th class="fh' + (open ? ' open' : '') + '"' + (open ? ' colspan="' + (f.items.length + 1) + '"' : (anyOpen ? ' rowspan="2"' : '')) + '><button type="button" data-f="' + AZ.esc(f.name) + '" aria-expanded="' + open + '" title="' + (open ? 'Hide' : 'Show') + ' the item types in ' + AZ.esc(f.name) + '">' + famLabel(f) + '</button></th>';
      });
      h += '<th class="th-t"' + (anyOpen ? ' rowspan="2"' : '') + '><span>Total</span></th></tr>';
      if (anyOpen) {
        h += '<tr class="sub">';
        cols.forEach((c) => { if (c.kind === 'fam' && c.open) h += '<th class="sa">All</th>'; else if (c.kind === 'item') h += '<th class="si" title="' + AZ.esc(c.name) + '">' + AZ.esc(c.name) + '</th>'; });
        h += '</tr>';
      }
      h += '</thead><tbody>';
      rowsV.forEach((r, ri) => {
        const lab = r.kind === 'reg'
          ? '<button type="button" class="rb" aria-expanded="' + r.open + '" title="' + (r.open ? 'Hide' : 'Show') + ' the states in ' + AZ.esc(r.name) + '">' + chev + '<span>' + AZ.esc(r.name) + '</span></button>'
          : '<span class="sn" title="' + AZ.esc(r.name) + '">' + AZ.esc(r.name) + '</span>';
        h += '<tr class="' + r.kind + (r.open ? ' open' : '') + '" data-ri="' + ri + '" data-key="' + AZ.esc(r.key) + '"><th class="lh"><div class="c">' + lab + '</div></th>' + cols.map((c, ci) => cellHTML(r, c, ci)).join('') + '</tr>';
      });
      const T = { key: 'G', kind: 'tot', name: 'All regions', items: grand, t: G };
      h += '</tbody><tfoot><tr class="tot" data-ri="-1"><th class="lh"><div class="c"><span>Total</span></div></th>' + cols.map((c, ci) => cellHTML(T, c, ci)).join('') + '</tr></tfoot></table>';
      wrap.innerHTML = h;
      const basisT = measure === 'units' ? 'units' : 'sales';
      foot.textContent = narrow ? 'Bars: share of row ' + basisT + '. Click a region or family to expand.'
        : 'Bars: share of row ' + basisT + ' (longest ' + AZ.pct(maxShare, 0) + '). Click a region for its states, a family for its item types. Families are an editorial grouping.';
      bindHeader();
      if (typeof setFlip === 'function') setFlip();
    };
    const rowOf = (ri) => (ri < 0 ? { key: 'G', kind: 'tot', name: 'All regions', items: grand, t: G } : rowsV[ri]);

    // -- animation helpers: every run has a timer fallback, since a hidden tile may pause animation frames
    const run = (ms, step, fin) => {
      let done = false;
      const end = () => { if (done) return; done = true; step(1); if (fin) fin(); };
      go(ms, step, end, AZ.EASE.inOut);
      timers.push(setTimeout(end, ms + 400));
    };
    const rowCells = (keys) => Array.from(wrap.querySelectorAll('tbody tr')).filter((tr) => keys.has(tr.getAttribute('data-key'))).reduce((a, tr) => a.concat(Array.from(tr.querySelectorAll('.c'))), []);
    const colEls = (keys) => Array.from(wrap.querySelectorAll('col[data-k]')).filter((c) => keys.has(c.getAttribute('data-k')));
    const tableW = () => { const t = wrap.querySelector('table'); if (t) t.style.width = (firstW + Array.from(wrap.querySelectorAll('col[data-k]')).reduce((a, c) => a + parseFloat(c.style.width || 0), 0)) + 'px'; };

    function rebuild(enterRows, enterCols) {
      go.stop(); tip.hide();
      const sl = wrap.scrollLeft, st = wrap.scrollTop;
      build();
      wrap.scrollLeft = sl; wrap.scrollTop = st;
      if (enterRows && enterRows.size) {
        const cs = rowCells(enterRows);
        cs.forEach((c) => { c.style.height = '0px'; c.style.opacity = '0'; });
        run(360, (k) => cs.forEach((c) => { c.style.height = (RH * k).toFixed(1) + 'px'; c.style.opacity = k.toFixed(3); }), () => cs.forEach((c) => { c.style.height = ''; c.style.opacity = ''; }));
      }
      if (enterCols && enterCols.size) {
        const cs = colEls(enterCols), fin = colW;
        const cells = Array.from(wrap.querySelectorAll('td, th')).filter((td) => { const ci = td.getAttribute('data-ci'); return ci != null && enterCols.has(cols[+ci].key); });
        cs.forEach((c) => { c.style.width = '0px'; }); tableW();
        cells.forEach((c) => { c.style.opacity = '0'; });
        run(380, (k) => { cs.forEach((c) => { c.style.width = (fin * k).toFixed(1) + 'px'; }); tableW(); cells.forEach((c) => { c.style.opacity = k.toFixed(3); }); }, () => { cs.forEach((c) => { c.style.width = fin + 'px'; }); cells.forEach((c) => { c.style.opacity = ''; }); tableW(); });
      }
    }
    function collapseRows(keys, after) {
      const cs = rowCells(keys);
      if (!cs.length) return after();
      tip.hide();
      run(300, (k) => cs.forEach((c) => { c.style.height = (RH * (1 - k)).toFixed(1) + 'px'; c.style.opacity = (1 - k).toFixed(3); }), after);
    }
    function collapseCols(keys, after) {
      const cs = colEls(keys);
      if (!cs.length) return after();
      tip.hide();
      run(320, (k) => { cs.forEach((c) => { c.style.width = (colW * (1 - k)).toFixed(1) + 'px'; }); tableW(); }, after);
    }
    const stateKeys = (names) => { const s = new Set(); regs.forEach((g) => { if (names.has(g.name)) g.states.forEach((x) => s.add('S|' + g.name + '|' + x.name)); }); return s; };
    const itemKeys = (names) => { const s = new Set(); fams.forEach((f) => { if (names.has(f.name)) f.items.forEach((it) => s.add('I|' + it)); }); return s; };
    const toggleReg = (name) => {
      userRegs = true;
      if (openRegs.has(name)) { openRegs.delete(name); collapseRows(stateKeys(new Set([name])), () => rebuild()); }
      else { openRegs.add(name); rebuild(stateKeys(new Set([name]))); }
    };
    const toggleFam = (name) => {
      if (openFams.has(name)) { openFams.delete(name); collapseCols(itemKeys(new Set([name])), () => rebuild()); }
      else { openFams.add(name); rebuild(null, itemKeys(new Set([name]))); }
    };
    function bindHeader() {
      wrap.querySelectorAll('th.fh button').forEach((b) => b.addEventListener('click', () => toggleFam(b.getAttribute('data-f'))));
    }
    wrap.addEventListener('click', (e) => {
      const tr = e.target.closest && e.target.closest('tbody tr.reg');
      if (tr) { const r = rowsV[+tr.getAttribute('data-ri')]; if (r) toggleReg(r.name); }
    });
    const flip = el.querySelector('.pv-btn[data-a=flip]');
    const setFlip = () => { if (!flip) return; const any = openRegs.size || openFams.size; flip.textContent = any ? 'Collapse' : 'Expand'; flip.setAttribute('aria-label', any ? 'Hide all states and item types' : 'Show the states of every region'); };
    el.querySelectorAll('.pv-btn').forEach((b) => b.addEventListener('click', () => {
      userRegs = true;
      const a = b.getAttribute('data-a') === 'flip' ? (openRegs.size || openFams.size ? 'close' : 'open') : b.getAttribute('data-a');
      if (a === 'open') {
        const add = new Set(regs.map((g) => g.name).filter((n) => !openRegs.has(n)));
        regs.forEach((g) => openRegs.add(g.name)); rebuild(stateKeys(add));
      } else {
        const rk = stateKeys(openRegs), ck = itemKeys(openFams);
        openRegs = new Set(); openFams = new Set();
        collapseCols(ck, () => collapseRows(rk, () => rebuild()));
      }
    }));
    el.querySelectorAll('.pv-seg button').forEach((b) => b.addEventListener('click', () => {
      const m = b.getAttribute('data-m'); if (m === measure) return;
      const old = {};
      wrap.querySelectorAll('.c[data-k] .b i').forEach((i) => { old[i.parentNode.parentNode.getAttribute('data-k')] = parseFloat(i.style.width); });
      measure = m;
      el.querySelectorAll('.pv-seg button').forEach((x) => x.setAttribute('aria-pressed', String(x.getAttribute('data-m') === measure)));
      rebuild();
      const bars = Array.from(wrap.querySelectorAll('.c[data-k] .b i')).map((i) => ({ i, a: old[i.parentNode.parentNode.getAttribute('data-k')] ?? 0, b: parseFloat(i.getAttribute('data-w')) }));
      const nums = Array.from(wrap.querySelectorAll('td .n'));
      run(420, (k) => { bars.forEach((x) => { x.i.style.width = AZ.lerp(x.a, x.b, k).toFixed(2) + '%'; }); nums.forEach((n) => { n.style.opacity = Math.min(1, 0.15 + k * 1.2).toFixed(3); }); }, () => nums.forEach((n) => { n.style.opacity = ''; }));
    }));

    // -- hover: highlight the row and the column under the pointer, tooltip with shares and price vs region
    let hl = null;
    const clearHl = () => { if (!hl) return; hl.forEach((n) => n.classList.remove('hr', 'hc', 'hx')); hl = null; };
    wrap.addEventListener('mousemove', (e) => {
      const td = e.target.closest && e.target.closest('td[data-ci]');
      if (!td) { clearHl(); tip.hide(); return; }
      const tr = td.parentNode, ri = +tr.getAttribute('data-ri'), ci = +td.getAttribute('data-ci');
      const r = rowOf(ri), c = cols[ci];
      if (!r || !c) return;
      clearHl(); hl = [];
      tr.querySelectorAll('th, td').forEach((n) => { n.classList.add('hr'); hl.push(n); });
      wrap.querySelectorAll('td[data-ci="' + ci + '"]').forEach((n) => { n.classList.add('hc'); hl.push(n); });
      td.classList.add('hx'); hl.push(td);
      const v = tot(r.items, c.list), colT = tot(grand, c.list), p = price(v);
      const rowName = r.kind === 'st' ? r.name + ' (' + r.reg.name + ')' : r.name;
      const basis = measure === 'units' ? 'units' : 'sales', bk = measure === 'units' ? 'u' : 's';
      let refName, refP;
      if (r.kind === 'reg') { if (c.kind === 'total') { refName = 'all regions'; refP = price(G); } else { refName = r.name; refP = price(r.t); } }
      else if (r.kind === 'st') { refName = r.reg.name; refP = price(r.reg.t); }
      else { refName = c.kind === 'total' ? null : 'all families'; refP = price(G); }
      let hh = '<b>' + AZ.esc(rowName) + ' / ' + AZ.esc(c.kind === 'total' ? 'all families' : c.name) + '</b>';
      if (c.kind === 'item') hh += AZ.row('Item type in ' + c.f.name, '', c.f.color);
      hh += AZ.row('Sales', AZ.money(v.s, 2)) + AZ.row('Units', Math.round(v.u).toLocaleString('en-US'));
      if (c.kind !== 'total') hh += AZ.row('Share of row ' + basis, AZ.pct(r.t[bk] ? v[bk] / r.t[bk] : 0, 1));
      if (r.kind !== 'tot') hh += AZ.row('Share of column ' + basis, AZ.pct(colT[bk] ? v[bk] / colT[bk] : 0, 1));
      hh += AZ.row('Price per unit', p == null ? '-' : $p(p));
      if (refName && p != null && refP != null) hh += AZ.row('vs ' + refName + ' (' + $p(refP) + ')', AZ.pct(p / refP - 1, 1, true));
      const b = el.getBoundingClientRect();
      tip.show(hh, e.clientX - b.left, e.clientY - b.top);
    });
    wrap.addEventListener('mouseleave', () => { clearHl(); tip.hide(); });
    wrap.addEventListener('scroll', () => tip.hide(), { passive: true });

    build();
    return () => { go.stop(); timers.forEach(clearTimeout); };
  }
});
