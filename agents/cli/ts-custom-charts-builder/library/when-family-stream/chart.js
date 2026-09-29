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

// Search: [sales] [item type] [date].quarterly
// Streamgraph of the five product families over time (item types summed into families, an editorial grouping).
// Toggle Stream / Stacked / 100%. Hover a quarter for every series. Click a family band or its label to drill into that
// family's item types (the layout morphs); Back, the crumb or Escape returns. The swatch beside a label isolates a series.
let mode = 'stream', pinned = null, level = null;

AZ.boot({
  need: 'sales, item type and date at quarterly grain, e.g. [sales] [item type] [date].quarterly',
  render: async ({ el, rows, schema }) => {
    await AZ.loadScript(['https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js', 'https://unpkg.com/d3@7.9.0/dist/d3.min.js'], () => !!window.d3, 8000);
    const d3 = window.d3;
    const iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|quarter/i), sK = AZ.col(schema, /sales/i);
    const ORDER = ['Outerwear', 'Tops and dresses', 'Bottoms', 'Swim and basics', 'Accessories'];
    const byQ = new Map(), itemTot = {};
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]), it = r[iK], f = AZ.familyOf(it), v = AZ.num(r[sK]);
      if (!isFinite(t) || ORDER.indexOf(f) < 0) return;
      if (!byQ.has(t)) byQ.set(t, { t: t });
      const o = byQ.get(t); o[f] = (o[f] || 0) + v; o['i:' + it] = (o['i:' + it] || 0) + v;
      itemTot[it] = (itemTot[it] || 0) + v;
    });
    const Q = Array.from(byQ.values()).sort((a, b) => a.t - b.t);
    if (!Q.length) { AZ.paint(el, '<div class="az-empty"><b>No quarters in the result</b><span>The search needs [sales] [item type] [date].quarterly</span></div>'); return; }
    const fams = ORDER.filter((f) => Q.some((q) => q[f] > 0));
    const famItems = (f) => Object.keys(itemTot).filter((i) => AZ.familyOf(i) === f && itemTot[i] > 0).sort((a, b) => itemTot[b] - itemTot[a]);
    const allKeys = fams.concat(Object.keys(itemTot).map((i) => 'i:' + i));
    Q.forEach((q) => { allKeys.forEach((f) => { q[f] = q[f] || 0; }); q.total = fams.reduce((a, f) => a + q[f], 0); });
    if (pinned && level && !famItems(level).some((i) => 'i:' + i === pinned)) pinned = null;
    if (level && fams.indexOf(level) < 0) { level = null; pinned = null; }
    if (pinned && !level && fams.indexOf(pinned) < 0) pinned = null;
    const qLbl = (t) => 'Q' + (Math.floor(new Date(t).getUTCMonth() / 3) + 1) + ' ' + AZ.year(t);
    const partialAt = (i) => Q.length > 2 && ((i === 0 && Q[0].total < 0.5 * Q[1].total) || (i === Q.length - 1 && Q[i].total < 0.5 * Q[i - 1].total));
    const pFirst = partialAt(0), pLast = partialAt(Q.length - 1);
    const tint = (hex, a) => { const n = parseInt(hex.slice(1), 16); return 'rgb(' + [n >> 16 & 255, n >> 8 & 255, n & 255].map((v) => Math.round(v + (255 - v) * a)).join(',') + ')'; };
    const seriesFor = (lvl) => {
      if (!lvl) return fams.map((f) => ({ key: f, label: f, color: AZ.T.family[f] }));
      const its = famItems(lvl);
      return its.map((i, k) => ({ key: 'i:' + i, label: i, color: tint(AZ.T.family[lvl], its.length < 2 ? 0 : 0.04 + 0.6 * k / (its.length - 1)) }));
    };
    const stot = (q, ser) => ser.reduce((a, s) => a + q[s.key], 0);
    const share = (q, s, ser) => { const t = stot(q, ser); return t ? q[s.key] / t : 0; };

    // Header line for the current level.
    const subFor = (lvl) => {
      const ser = seriesFor(lvl), noun = lvl ? lvl + ' item type' : 'family', scope = lvl ? lvl + ' sales' : 'sales';
      const big = (q) => ser.reduce((b, s) => (q[s.key] > q[b.key] ? s : b), ser[0]);
      const q0 = Q[0], q1 = Q[Q.length - 1], b0 = big(q0), b1 = big(q1);
      let sub;
      if (Q.length < 2) sub = 'One quarter in the current filter: ' + AZ.esc(b0.label) + ' is ' + AZ.pct(share(q0, b0, ser), 0) + ' of ' + scope + ' in ' + qLbl(q0.t);
      else if (b0.key === b1.key) {
        const ss = Q.map((q) => share(q, b0, ser)), lo = Math.min.apply(null, ss), hi = Math.max.apply(null, ss);
        const still = Math.abs(share(q1, b0, ser) - share(q0, b0, ser)) < 0.02;
        sub = '<b>' + AZ.esc(b0.label) + '</b> is the largest ' + noun + ' at both ends: ' + AZ.pct(share(q0, b0, ser), 1) + ' of ' + scope + ' in ' + qLbl(q0.t) + ' and ' + AZ.pct(share(q1, b0, ser), 1) + ' in ' + qLbl(q1.t)
          + (still ? '. The mix is flat from end to end' + (hi - lo > 0.05 ? ', but its share ranges from ' + AZ.pct(lo, 0) + ' to ' + AZ.pct(hi, 0) + ' in between.' : '.') : '.');
      } else sub = '<b>' + AZ.esc(b0.label) + '</b> led ' + noun + 's in ' + qLbl(q0.t) + ' at ' + AZ.pct(share(q0, b0, ser), 1) + '; <b>' + AZ.esc(b1.label) + '</b> leads in ' + qLbl(q1.t) + ' at ' + AZ.pct(share(q1, b1, ser), 1) + '.';
      if (lvl && q1.total) sub += ' ' + AZ.esc(lvl) + ' is ' + AZ.pct(q1[lvl] / q1.total, 0) + ' of all sales in ' + qLbl(q1.t) + '.';
      return sub;
    };

    const seg = [['stream', 'Stream'], ['stack', 'Stacked'], ['pct', '100%']].map((k) => '<button type="button" data-k="' + k[0] + '" class="' + (k[0] === mode ? 'on' : '') + '">' + k[1] + '</button>').join('');
    el.innerHTML = '<div class="fs-top"><div class="fs-title"></div><div class="fs-seg" role="group" aria-label="Layout">' + seg + '</div></div><div class="fs-crumbrow"></div><div class="fs-sub"></div><div class="fs-plot" id="fs-plot"></div>';
    const titleEl = el.querySelector('.fs-title'), crumbEl = el.querySelector('.fs-crumbrow'), subEl = el.querySelector('.fs-sub');
    const flash = (n) => { n.classList.remove('fs-fade'); void n.offsetWidth; n.classList.add('fs-fade'); };
    let goTo = () => {};
    const head = (fade) => {
      titleEl.textContent = level ? 'Sales by ' + level + ' item type, by quarter' : 'Sales by product family, by quarter';
      crumbEl.innerHTML = level ? AZ.crumbs(['All families', level]) + '<button type="button" class="fs-back">Back</button>' : '<span class="fs-hint">Click a band or label to open its item types</span>';
      AZ.wireCrumbs(crumbEl, () => goTo(null));
      const bk = crumbEl.querySelector('.fs-back'); if (bk) bk.addEventListener('click', () => goTo(null));
      subEl.innerHTML = subFor(level);
      if (fade) { flash(crumbEl); flash(subEl); flash(titleEl); }
    };
    head(false);

    const box = document.getElementById('fs-plot'), W = Math.max(200, box.clientWidth), H = Math.max(120, box.clientHeight);
    const labNames = fams.concat(Object.keys(itemTot));
    const m = { l: 42, r: Math.min(W * 0.4, Math.max.apply(null, labNames.map((f) => f.length + 4)) * 6.8 + 28), t: 10, b: 24 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const DRAW = Q.length < 2 ? [Object.assign({}, Q[0], { t: Q[0].t - 864e5 * 45 }), Object.assign({}, Q[0], { t: Q[0].t + 864e5 * 45 })] : Q;
    const x = d3.scaleTime().domain(Q.length < 2 ? [Q[0].t - 864e5 * 360, Q[0].t + 864e5 * 360] : [DRAW[0].t, DRAW[DRAW.length - 1].t]).range([m.l, m.l + iw]);
    const xs = DRAW.map((d) => x(d.t));
    const xi = (i) => x(Q[i].t);
    const li = DRAW.length - 1;

    const layoutFor = (ser) => {
      const keys = ser.map((s) => s.key);
      const stack = d3.stack().keys(keys).order(mode === 'stream' ? d3.stackOrderInsideOut : d3.stackOrderNone)
        .offset(mode === 'stream' ? d3.stackOffsetWiggle : mode === 'pct' ? d3.stackOffsetExpand : d3.stackOffsetNone);
      const layers = stack(DRAW);
      const y0 = d3.min(layers, (l) => d3.min(l, (d) => d[0])) || 0;
      let y1 = d3.max(layers, (l) => d3.max(l, (d) => d[1])) || 1; if (!(y1 > y0)) y1 = y0 + 1;
      const y = d3.scaleLinear().domain([y0, y1]).range([m.t + ih, m.t]);
      const geo = {};
      layers.forEach((l, k) => { geo[keys[k]] = { a: l.map((d) => y(d[0])), b: l.map((d) => y(d[1])) }; });
      return { ser, keys, layers, y, y0, y1, geo, mode, level };
    };
    const areaGen = d3.area().x((d, i) => xs[i]).y0((d) => d.a).y1((d) => d.b).curve(d3.curveMonotoneX);

    const svg = d3.select(box).append('svg').attr('viewBox', '0 0 ' + W + ' ' + H).attr('role', 'img').attr('aria-label', 'Streamgraph of sales by product family');
    const axLayer = svg.append('g');
    // time axis (constant)
    const yrs = []; Q.forEach((q, i) => { if (new Date(q.t).getUTCMonth() < 3 || i === 0) yrs.push({ i, lab: new Date(q.t).getUTCMonth() < 3 ? String(AZ.year(q.t)) : qLbl(q.t) }); });
    const step0 = Math.ceil(yrs.length / Math.max(2, Math.floor(iw / 62)));
    yrs.forEach((yy, k) => {
      if (k % step0 && !(yy.i === 0 && step0 === 1)) return;
      if (yy.i === 0 && yrs.length > 1 && yrs[1].i < 3 && step0 > 1) return;
      svg.append('line').attr('x1', xi(yy.i)).attr('x2', xi(yy.i)).attr('y1', m.t + ih).attr('y2', m.t + ih + 4).attr('stroke', AZ.T.muted);
      svg.append('text').attr('class', 'fs-ax').attr('x', xi(yy.i)).attr('y', H - 6).attr('text-anchor', yy.i === 0 ? 'start' : 'middle').text(yy.lab);
    });
    const bandG = svg.append('g');
    const partial = (i0, i1) => {
      const xa = xi(i0), xb = xi(i1);
      svg.append('rect').attr('x', Math.min(xa, xb)).attr('y', m.t).attr('width', Math.abs(xb - xa)).attr('height', ih).attr('fill', '#fff').attr('opacity', 0.55).attr('pointer-events', 'none');
      svg.append('line').attr('x1', xb).attr('x2', xb).attr('y1', m.t).attr('y2', m.t + ih).attr('stroke', AZ.T.muted).attr('stroke-dasharray', '3 3').attr('pointer-events', 'none');
    };
    if (pFirst) partial(0, 1);
    if (pLast) partial(Q.length - 2, Q.length - 1);
    if (pFirst) svg.append('text').attr('class', 'fs-note').attr('x', xi(0) + 4).attr('y', m.t + 11).text('partial');
    const sbG = svg.append('g').attr('pointer-events', 'none').attr('opacity', 0);
    const labG = svg.append('g');

    // ---- state that survives an interrupted morph ------------------------------------------
    let cur = null, T = null, cancelT = null, axCur = null, axOld = null, leaving = [];
    const els = {}, labs = {};
    const opOf = (key) => (pinned && pinned !== key ? 0.18 : 1);
    const isFam = (key) => key.indexOf('i:') !== 0;
    const famOfKey = (key) => (isFam(key) ? key : AZ.familyOf(key.slice(2)));

    const onPick = (s) => { if (!level) goTo(s.key); else { pinned = pinned === s.key ? null : s.key; update(true, 320); } };
    const onPin = (s) => { pinned = pinned === s.key ? null : s.key; update(true, 320); };

    function spreadLabels(L) {
      const arr = L.ser.map((s) => ({ key: s.key, y: (L.geo[s.key].a[li] + L.geo[s.key].b[li]) / 2 }));
      arr.sort((a, b) => a.y - b.y);
      for (let k = 1; k < arr.length; k++) if (arr[k].y - arr[k - 1].y < 15) arr[k].y = arr[k - 1].y + 15;
      const over = arr.length ? arr[arr.length - 1].y - (m.t + ih) : 0;
      if (over > 0) arr.forEach((a) => { a.y -= over; });
      const o = {}; arr.forEach((a) => { o[a.key] = a.y; }); return o;
    }
    function buildAxis(L) {
      const g = axLayer.append('g').attr('opacity', 0);
      L.y.ticks(4).forEach((tk) => {
        g.append('line').attr('x1', m.l).attr('x2', m.l + iw).attr('y1', L.y(tk)).attr('y2', L.y(tk)).attr('stroke', AZ.T.grid);
        g.append('text').attr('class', 'fs-ax').attr('x', m.l - 6).attr('y', L.y(tk) + 4).attr('text-anchor', 'end').text(L.mode === 'pct' ? Math.round(tk * 100) + '%' : AZ.money(tk, 0));
      });
      return g;
    }
    function buildScale(L) {
      sbG.selectAll('*').remove();
      const span = L.y1 - L.y0, p10 = Math.pow(10, Math.floor(Math.log10(span / 2))), unit = p10 * ([1, 2, 5].find((n) => n * p10 >= span / 4) || 5);
      const bx = m.l + 2, bh = Math.abs(L.y(0) - L.y(unit)), by0 = m.t + 20 + bh;
      sbG.append('line').attr('x1', bx).attr('x2', bx).attr('y1', by0).attr('y2', by0 - bh).attr('stroke', AZ.T.ink).attr('stroke-width', 2);
      sbG.append('text').attr('class', 'fs-note').attr('x', bx + 6).attr('y', by0 - bh / 2 + 4).text(AZ.money(unit, 0) + ' per quarter');
    }
    function mkBand(s) {
      const p = bandG.append('path').attr('class', 'fs-band').attr('data-f', s.label).attr('stroke', '#fff').attr('stroke-width', 0.75).attr('opacity', 0)
        .on('click', () => onPick(s));
      els[s.key] = p; return p;
    }
    function mkLabel(s, y) {
      const gg = labG.append('g').attr('class', 'fs-lab').attr('tabindex', 0).attr('role', 'button').attr('aria-label', s.label).style('opacity', 0);
      gg.append('rect').attr('class', 'fs-hitl').attr('x', m.l + iw + 4).attr('y', -8).attr('width', m.r - 4).attr('height', 16).attr('fill', 'transparent');
      gg.append('rect').attr('class', 'fs-sw').attr('x', m.l + iw + 8).attr('y', -5).attr('width', 9).attr('height', 9).attr('rx', 2);
      gg.append('rect').attr('class', 'fs-swhit').attr('x', m.l + iw + 4).attr('y', -8).attr('width', 18).attr('height', 16).attr('fill', 'transparent');
      gg.append('text').attr('x', m.l + iw + 22).attr('y', 4);
      gg.on('click', () => onPick(s));
      gg.select('.fs-swhit').on('click', (e) => { e.stopPropagation(); onPin(s); });
      gg.on('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(s); } });
      gg.attr('transform', 'translate(0,' + y + ')');
      labs[s.key] = { g: gg, y: y };
      return labs[s.key];
    }

    function update(animate, ms) {
      if (cancelT) { cancelT(); cancelT = null; }
      leaving.forEach((k) => { if (els[k]) { els[k].remove(); delete els[k]; } if (labs[k]) { labs[k].g.remove(); delete labs[k]; } });
      leaving = [];
      if (axOld) { axOld.remove(); axOld = null; }
      const ser = seriesFor(level), L = layoutFor(ser);
      T = L;
      const prev = animate && cur ? cur : null;
      const start = {};
      ser.forEach((s) => {
        const tg = L.geo[s.key];
        let st = null;
        if (prev) {
          if (prev.geo[s.key]) st = { a: prev.geo[s.key].a.slice(), b: prev.geo[s.key].b.slice(), col: prev.col[s.key], op: prev.op[s.key] };
          else if (prev.level === null && level !== null && prev.geo[level]) {
            const pg = prev.geo[level], a = [], b = [];
            for (let i = 0; i < tg.a.length; i++) {
              let fmin = 1e9, fmax = -1e9;
              ser.forEach((c) => { fmin = Math.min(fmin, L.geo[c.key].b[i]); fmax = Math.max(fmax, L.geo[c.key].a[i]); });
              const den = fmax - fmin;
              const f0 = den > 1e-6 ? (tg.b[i] - fmin) / den : 0, f1 = den > 1e-6 ? (tg.a[i] - fmin) / den : 1;
              b.push(pg.b[i] + f0 * (pg.a[i] - pg.b[i])); a.push(pg.b[i] + f1 * (pg.a[i] - pg.b[i]));
            }
            st = { a, b, col: prev.col[level], op: 1 };
          } else if (prev.level !== null && level === null) {
            const kids = prev.keys.filter((k) => !isFam(k) && famOfKey(k) === s.key);
            if (kids.length) {
              const a = [], b = [];
              for (let i = 0; i < tg.a.length; i++) { a.push(Math.max.apply(null, kids.map((k) => prev.geo[k].a[i]))); b.push(Math.min.apply(null, kids.map((k) => prev.geo[k].b[i]))); }
              st = { a, b, col: prev.col[kids[0]], op: 1 };
            }
          }
        }
        if (!st) { const mid = tg.a.map((v, i) => (v + tg.b[i]) / 2); st = { a: mid.slice(), b: mid.slice(), col: s.color, op: prev ? 0 : 1 }; }
        if (!prev) st = { a: tg.a.slice(), b: tg.b.slice(), col: s.color, op: 1 };
        start[s.key] = st;
      });
      // series that leave: the drilled family and the children of a family we leave are replaced at once; the rest fade
      const goneKeys = prev ? prev.keys.filter((k) => !ser.some((s) => s.key === k)) : [];
      const fadeKeys = [];
      goneKeys.forEach((k) => {
        const swallowed = (level !== null && k === level) || (prev.level !== null && level === null);
        if (swallowed) { if (els[k]) { els[k].remove(); delete els[k]; } if (labs[k]) { labs[k].g.remove(); delete labs[k]; } } else { fadeKeys.push(k); }
      });
      leaving = fadeKeys.slice();
      // label targets
      const ly = spreadLabels(L);
      const lstart = {};
      ser.forEach((s) => {
        if (labs[s.key]) lstart[s.key] = { y: labs[s.key].y, op: parseFloat(labs[s.key].g.style('opacity')) || 0 };
        else { const st = start[s.key]; lstart[s.key] = { y: prev ? Math.max(m.t, Math.min(m.t + ih, (st.a[li] + st.b[li]) / 2)) : ly[s.key], op: 0, isNew: true }; }
      });
      ser.forEach((s) => { if (!els[s.key]) mkBand(s); if (!labs[s.key]) mkLabel(s, lstart[s.key].y); });
      const lfrom = {}; fadeKeys.forEach((k) => { lfrom[k] = labs[k] ? parseFloat(labs[k].g.style('opacity')) || 1 : 0; });
      ser.forEach((s) => {
        const lb = labs[s.key];
        lb.g.select('.fs-sw').attr('fill', s.color);
        lb.g.select('text').html(AZ.esc(s.label) + ' <tspan class="v">' + AZ.pct(share(Q[Q.length - 1], s, ser), 0) + '</tspan>');
      });
      // axis + scale bar
      const axWasOp = axCur ? parseFloat(axCur.attr('opacity')) || 0 : 0;
      axOld = axCur; axCur = mode !== 'stream' ? buildAxis(L) : null;
      const sbFrom = parseFloat(sbG.attr('opacity')) || 0, sbTo = mode === 'stream' ? 1 : 0;
      if (sbTo) buildScale(L);
      // current geometry record (valid at any moment if interrupted)
      cur = { level, keys: ser.map((s) => s.key), geo: {}, col: {}, op: {}, mode };
      ser.forEach((s) => { const st = start[s.key]; cur.geo[s.key] = { a: st.a.slice(), b: st.b.slice() }; cur.col[s.key] = st.col; cur.op[s.key] = st.op; });
      const fromOp = {}; fadeKeys.forEach((k) => { fromOp[k] = prev.op[k]; });
      const fadeGeo = {}; fadeKeys.forEach((k) => { fadeGeo[k] = prev.geo[k]; });
      const frame = (k) => {
        ser.forEach((s) => {
          const st = start[s.key], tg = L.geo[s.key], g = cur.geo[s.key], pts = [];
          for (let i = 0; i < tg.a.length; i++) { g.a[i] = AZ.lerp(st.a[i], tg.a[i], k); g.b[i] = AZ.lerp(st.b[i], tg.b[i], k); pts.push({ a: g.a[i], b: g.b[i] }); }
          const c = d3.interpolateRgb(st.col, s.color)(k), o = AZ.lerp(st.op, opOf(s.key), k);
          cur.col[s.key] = c; cur.op[s.key] = o;
          els[s.key].attr('d', areaGen(pts)).attr('fill', c).attr('opacity', o);
          const lb = labs[s.key], ls = lstart[s.key], yy = AZ.lerp(ls.y, ly[s.key], k);
          lb.y = yy; lb.g.attr('transform', 'translate(0,' + yy + ')').style('opacity', AZ.lerp(ls.op, pinned && pinned !== s.key ? 0.35 : 1, k));
        });
        fadeKeys.forEach((key) => {
          if (els[key]) { els[key].attr('opacity', fromOp[key] * (1 - k)); if (k === 0 || !els[key].attr('d')) els[key].attr('d', areaGen(fadeGeo[key].a.map((v, i) => ({ a: v, b: fadeGeo[key].b[i] })))); }
          if (labs[key]) labs[key].g.style('opacity', lfrom[key] * (1 - k));
        });
        if (axOld) axOld.attr('opacity', axWasOp * (1 - k));
        if (axCur) axCur.attr('opacity', k);
        sbG.attr('opacity', AZ.lerp(sbFrom, sbTo, k));
      };
      cancelT = AZ.tween(animate ? (ms || 500) : 0, frame, () => {
        cancelT = null;
        leaving.forEach((k) => { if (els[k]) { els[k].remove(); delete els[k]; } if (labs[k]) { labs[k].g.remove(); delete labs[k]; } });
        leaving = [];
        if (axOld) { axOld.remove(); axOld = null; }
      }, AZ.EASE.inOut);
    }

    goTo = (lvl) => {
      if (lvl === level) return;
      level = lvl; pinned = null; head(true); update(true, 520);
    };
    const onKey = (e) => { if (e.key === 'Escape' && level) { e.preventDefault(); goTo(null); } };
    document.addEventListener('keydown', onKey);
    el.querySelectorAll('.fs-seg button').forEach((b) => b.addEventListener('click', () => {
      mode = b.getAttribute('data-k');
      el.querySelectorAll('.fs-seg button').forEach((o) => o.classList.toggle('on', o === b));
      update(true, 520);
    }));
    update(false);

    // hover
    const guide = svg.append('line').attr('y1', m.t).attr('y2', m.t + ih).attr('stroke', AZ.T.ink).attr('stroke-width', 1).attr('opacity', 0).attr('pointer-events', 'none');
    const dots = svg.append('g').attr('pointer-events', 'none');
    const tip = AZ.tip(box);
    const move = (e) => {
      const b = box.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W, py = (e.clientY - b.top) / b.height * H;
      if (px < m.l - 4 || px > m.l + iw + 4 || py < m.t || py > m.t + ih) { guide.attr('opacity', 0); dots.selectAll('*').remove(); tip.hide(); return; }
      let k = 0, bd = 1e9; Q.forEach((q, i) => { const d = Math.abs(xi(i) - px); if (d < bd) { bd = d; k = i; } });
      const q = Q[k], L = T;
      guide.attr('x1', xi(k)).attr('x2', xi(k)).attr('opacity', 0.4);
      dots.selectAll('*').remove();
      let h = '<b>' + qLbl(q.t) + (partialAt(k) ? ' (partial)' : '') + '</b>';
      L.ser.forEach((s, j) => {
        const l = L.layers[j][k];
        dots.append('circle').attr('cx', xi(k)).attr('cy', L.y((l[0] + l[1]) / 2)).attr('r', 3.5).attr('fill', '#fff').attr('stroke', s.color).attr('stroke-width', 2).attr('opacity', opOf(s.key) < 1 ? 0.25 : 1);
        h += AZ.row(s.label, AZ.money(q[s.key], 1) + '  ' + AZ.pct(share(q, s, L.ser), 0), s.color);
      });
      h += AZ.row(level ? 'All ' + level : 'All families', AZ.money(stot(q, L.ser), 1));
      tip.show(h, e.clientX - b.left, e.clientY - b.top);
    };
    box.addEventListener('mousemove', move);
    box.addEventListener('mouseleave', () => { guide.attr('opacity', 0); dots.selectAll('*').remove(); tip.hide(); });
    return () => { if (cancelT) cancelT(); document.removeEventListener('keydown', onKey); };
  }
});
