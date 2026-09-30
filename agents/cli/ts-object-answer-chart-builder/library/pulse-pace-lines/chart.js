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

// Search: [sales] [date].monthly     (columns arrive as "Total sales" and "Month(date)")
// Cumulative sales by month, one line per year (a year needs at least 3 months). Lines draw on left to right.
// Interactions: hover a month for every year's cumulative value; click a line or its label (Enter or Space when focused)
// to open that year: the other lines fade out while its monthly columns rise against the previous year as an outline.
// Crumbs, Back and Escape return. No library, no fetch: plain SVG.
const INK = AZ.T.ink;
let drill = null;   // year number when a single year is open

const nice = (max) => {
  const raw = max / 4, p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  const t = []; for (let v = 0; v <= max + step * 0.999; v += step) t.push(v);
  return { ticks: t, top: t[t.length - 1] };
};

AZ.boot({
  need: 'sales by date at monthly grain, e.g. [sales] [date].monthly',
  render: async ({ el, rows, schema }) => {
    const dKey = AZ.col(schema, /date|month/i), sKey = AZ.col(schema, /sales/i);
    const byYear = new Map();
    rows.forEach((r) => {
      const t = AZ.ms(r[dKey]); if (!isFinite(t)) return;
      const y = AZ.year(t), m = new Date(t).getUTCMonth();
      if (!byYear.has(y)) byYear.set(y, { y: y, mon: new Array(12).fill(null) });
      const o = byYear.get(y); o.mon[m] = (o.mon[m] || 0) + AZ.num(r[sKey]);
    });
    const all = Array.from(byYear.values()).sort((a, b) => a.y - b.y);
    all.forEach((o) => { let c = 0; o.cum = o.mon.map((v) => (v == null ? null : (c += v))); o.n = o.mon.filter((v) => v != null).length; o.first = o.mon.findIndex((v) => v != null); o.last = o.mon.reduce((a, v, i) => (v != null ? i : a), -1); });
    const Y = all.filter((o) => o.n >= 3);
    if (!Y.length) {
      AZ.paint(el, '<div class="az-empty"><b>Not enough months</b><span>Cumulative lines need at least 3 months of sales in one year. Search: [sales] [date].monthly</span></div>');
      return;
    }
    const latest = Y[Y.length - 1], prevAll = all.find((o) => o.y === latest.y - 1);
    if (drill != null && !Y.some((o) => o.y === drill)) drill = null;
    const yOf = (n) => all.find((o) => o.y === n);
    const shade = (o) => { if (o === latest) return INK; const idx = Y.indexOf(o), span = Math.max(1, Y.length - 2); return AZ.T.slate[2 + Math.round((idx / span) * 3)] || AZ.T.slate[4]; };
    const lineW = (o) => (o === latest ? 2.8 : 1.6);

    // header text, all computed from the rows
    const lm = latest.last;
    const nCur = latest.mon.slice(0, lm + 1).filter((v) => v != null).length;
    const prevSum = prevAll ? prevAll.mon.slice(0, lm + 1).reduce((a, v) => a + (v || 0), 0) : 0;
    const nPrev = prevAll ? prevAll.mon.slice(0, lm + 1).filter((v) => v != null).length : 0;
    const comparable = prevAll && nPrev === nCur && prevSum > 0;
    const leadAll = comparable
      ? latest.y + ' is at ' + AZ.money(latest.cum[lm], 1) + ' through ' + AZ.MON[lm] + ', ' + AZ.pct(latest.cum[lm] / prevSum - 1, 1, true) + ' on ' + prevAll.y + ' to the same month (' + AZ.money(prevSum, 1) + ').'
      : latest.y + ' is at ' + AZ.money(latest.cum[lm], 1) + ' through ' + AZ.MON[lm] + (prevAll ? '; ' + prevAll.y + ' has ' + nPrev + ' of the same ' + nCur + ' months in this filter, so the two are not like for like.' : '.');
    const partial = Y.filter((o) => o.first > 0 && o !== latest).map((o) => o.y + ' starts in ' + AZ.MON[o.first]);
    const subAll = 'Cumulative sales by month, one line per year. Click a year to open its months.' + (partial.length ? ' ' + partial.join('; ') + '.' : '');

    el.innerHTML = '<div class="pp-head"><div class="pp-top"><div class="pp-title" id="pp-title">Sales pace by year</div><button type="button" class="pp-back" id="pp-back" style="display:none">Back</button></div><p class="pp-lead" id="pp-lead"></p><p class="pp-sub" id="pp-sub"></p></div><div class="pp-plot" id="pp-plot"></div>';
    const plot = document.getElementById('pp-plot');
    await AZ.settle();
    const W = Math.max(200, plot.clientWidth), H = Math.max(120, plot.clientHeight);
    const ml = 40, mr = W < 380 ? 70 : 84, mt = 8, mb = 22, iw = W - ml - mr, ih = H - mt - mb, bw = iw / 12;
    const xm = (m) => ml + (m + 0.5) * bw;
    const maxCum = Math.max.apply(null, Y.map((o) => o.cum[o.last]));
    const gA = nice(maxCum), yA = (v) => mt + ih - (v / gA.top) * ih;
    const ns = (a) => a.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');

    // ---- layer A: cumulative lines
    let A = '<g id="pp-A"><g>';
    gA.ticks.forEach((v) => { A += '<line class="pp-grid" x1="' + ml + '" x2="' + (W - mr) + '" y1="' + yA(v).toFixed(1) + '" y2="' + yA(v).toFixed(1) + '"/><text class="pp-tick" x="' + (ml - 6) + '" y="' + (yA(v) + 4).toFixed(1) + '" text-anchor="end">' + (v >= 1e6 && v % 1e6 !== 0 ? AZ.money(v, 1) : AZ.money(v, 0)) + '</text>'; });
    A += '</g>';
    const labY = Y.map((o) => ({ o: o, y: yA(o.cum[o.last]) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labY.length; i++) if (labY[i].y - labY[i - 1].y < 13) labY[i].y = labY[i - 1].y + 13;
    const shift = labY.length && labY[labY.length - 1].y > mt + ih ? labY[labY.length - 1].y - (mt + ih) : 0;
    labY.forEach((l) => { l.y -= shift; });
    Y.slice().sort((a, b) => (a === latest) - (b === latest)).forEach((o) => {
      const pts = []; o.cum.forEach((v, m) => { if (v != null) pts.push([xm(m), yA(v)]); });
      const d = 'M' + pts.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('L');
      A += '<path class="pp-line" data-y="' + o.y + '" d="' + d + '" pathLength="1" fill="none" stroke="' + shade(o) + '" stroke-width="' + lineW(o) + '" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="1" stroke-dashoffset="1"/>';
      A += '<path class="pp-hit" tabindex="0" role="button" aria-label="Open ' + o.y + '" data-y="' + o.y + '" d="' + d + '"/>';
    });
    labY.forEach((l) => {
      const o = l.o, px = xm(o.last);
      A += '<text class="pp-lab" tabindex="0" role="button" data-y="' + o.y + '" x="' + (px + 8).toFixed(1) + '" y="' + (l.y + 4).toFixed(1) + '" fill="' + (o === latest ? INK : AZ.T.slate[5]) + '" font-weight="' + (o === latest ? 600 : 400) + '" opacity="0">' + o.y + ' <tspan font-weight="600">' + AZ.money(o.cum[o.last], 0) + '</tspan></text>';
    });
    A += '<line class="pp-guide" id="pp-guide" y1="' + mt + '" y2="' + (mt + ih) + '" x1="0" x2="0" style="display:none"/><g id="pp-dots"></g></g>';

    // ---- layer B: monthly columns for the open year (built on demand)
    const months = AZ.MON;
    let X = '<g>';
    for (let m = 0; m < 12; m++) X += '<text class="pp-tick" x="' + xm(m).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + (bw < 26 ? months[m].charAt(0) : months[m]) + '</text>';
    X += '</g>';
    plot.innerHTML = '<svg id="pp-svg" viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '">' + X + A + '<g id="pp-B" style="opacity:0"></g></svg>';
    const svg = document.getElementById('pp-svg'), gAel = document.getElementById('pp-A'), gB = document.getElementById('pp-B');
    const lines = Array.from(svg.querySelectorAll('.pp-line')), labs = Array.from(svg.querySelectorAll('.pp-lab')), hits = Array.from(svg.querySelectorAll('.pp-hit'));
    const guide = document.getElementById('pp-guide'), dotsG = document.getElementById('pp-dots');
    const tip = AZ.tip(el);
    const cancels = { draw: null, drill: null };
    let cur = 0, busy = false, B = null;   // cur: 0 all years, 1 open year

    const buildB = (yr) => {
      const o = yOf(yr), p = yOf(yr - 1);
      const mx = Math.max.apply(null, o.mon.concat(p ? p.mon : []).map((v) => v || 0));
      const g = nice(mx), yB = (v) => mt + ih - (v / g.top) * ih;
      let h = '';
      g.ticks.forEach((v) => { h += '<line class="pp-grid" x1="' + ml + '" x2="' + (W - mr) + '" y1="' + yB(v).toFixed(1) + '" y2="' + yB(v).toFixed(1) + '"/><text class="pp-tick" x="' + (ml - 6) + '" y="' + (yB(v) + 4).toFixed(1) + '" text-anchor="end">' + (v >= 1e6 && v % 1e6 !== 0 ? AZ.money(v, 1) : AZ.money(v, 0)) + '</text>'; });
      const bars = [];
      for (let m = 0; m < 12; m++) {
        if (o.mon[m] != null) { h += '<rect class="pp-bar" data-m="' + m + '" x="' + (xm(m) - bw * 0.3).toFixed(1) + '" width="' + (bw * 0.6).toFixed(1) + '" y="' + yB(0).toFixed(1) + '" height="0" rx="2" fill="' + (o === latest ? INK : shade(o)) + '"/>'; bars.push({ m: m, v: o.mon[m] }); }
      }
      const outs = [];
      for (let m = 0; m < 12; m++) {
        if (p && p.mon[m] != null) { h += '<rect class="pp-out" data-m="' + m + '" x="' + (xm(m) - bw * 0.38).toFixed(1) + '" width="' + (bw * 0.76).toFixed(1) + '" y="' + yB(0).toFixed(1) + '" height="0" rx="2" fill="none" stroke="' + AZ.T.slate[3] + '" stroke-width="1.5"/>'; outs.push({ m: m, v: p.mon[m] }); }
      }
      gB.innerHTML = h;
      B = { yr: yr, o: o, p: p, yB: yB, base: yB(0), bars: bars, outs: outs, barEls: Array.from(gB.querySelectorAll('.pp-bar')), outEls: Array.from(gB.querySelectorAll('.pp-out')) };
    };
    const frame = (k) => {
      cur = k;
      const sel = B ? B.yr : null;
      gAel.style.opacity = String(1 - k);
      gAel.style.pointerEvents = k > 0.02 ? 'none' : '';
      gB.style.opacity = String(Math.min(1, k * 2));
      if (B) {
        const kk = AZ.EASE.out(Math.max(0, Math.min(1, (k - 0.1) / 0.9)));
        B.barEls.forEach((r, i) => { const h = (B.base - B.yB(B.bars[i].v)) * kk; r.setAttribute('y', (B.base - h).toFixed(1)); r.setAttribute('height', h.toFixed(1)); });
        B.outEls.forEach((r, i) => { const h = (B.base - B.yB(B.outs[i].v)) * kk; r.setAttribute('y', (B.base - h).toFixed(1)); r.setAttribute('height', h.toFixed(1)); });
      }
      void sel;
    };
    const paintHead = () => {
      const t = document.getElementById('pp-title'), lead = document.getElementById('pp-lead'), sub = document.getElementById('pp-sub'), back = document.getElementById('pp-back');
      if (drill == null) {
        t.textContent = 'Sales pace by year'; lead.textContent = leadAll; sub.textContent = subAll; back.style.display = 'none';
      } else {
        const o = yOf(drill), p = yOf(drill - 1), best = o.mon.reduce((a, v, i) => (v != null && (a < 0 || v > o.mon[a]) ? i : a), -1);
        t.innerHTML = AZ.crumbs(['All years', String(drill)]); AZ.wireCrumbs(t, () => go(null));
        const tot = o.cum[o.last];
        lead.textContent = drill + ': ' + AZ.money(tot, 1) + ' over ' + o.n + ' months, best month ' + AZ.MON[best] + ' at ' + AZ.money(o.mon[best], 1) + '.';
        const same = p ? p.mon.slice(0, o.last + 1).reduce((a, v) => a + (v || 0), 0) : 0, nP = p ? p.mon.slice(0, o.last + 1).filter((v) => v != null).length : 0, nO = o.mon.slice(0, o.last + 1).filter((v) => v != null).length;
        sub.textContent = p && nP === nO && same > 0 ? 'Columns are monthly sales; outlines are ' + p.y + '. Through ' + AZ.MON[o.last] + ' that is ' + AZ.pct(tot / same - 1, 1, true) + ' on ' + p.y + '.' : (p ? 'Columns are monthly sales; outlines are ' + p.y + ', where it has data.' : 'Columns are monthly sales. There is no ' + (drill - 1) + ' in this filter to compare.');
        back.style.display = '';
      }
    };
    const go = (yr) => {
      if (cancels.drill) cancels.drill();
      tip.hide(); guide.style.display = 'none'; dotsG.innerHTML = '';
      const from = cur;
      if (yr != null) { if (!B || B.yr !== yr) buildB(yr); drill = yr; } else drill = null;
      paintHead();
      busy = true;
      const to = yr != null ? 1 : 0;
      cancels.drill = AZ.tween(560, (k) => frame(AZ.lerp(from, to, k)), () => { busy = false; }, AZ.EASE.inOut);
    };
    document.getElementById('pp-back').addEventListener('click', () => go(null));

    // ---- entrance: lines draw on left to right, labels fade in
    const paintDraw = (k) => {
      lines.forEach((l) => l.setAttribute('stroke-dashoffset', String(1 - k)));
      labs.forEach((t) => t.setAttribute('opacity', String(Math.max(0, (k - 0.6) / 0.4))));
    };
    if (drill != null) { buildB(drill); paintDraw(1); frame(1); }
    else {
      paintDraw(0);
      if (typeof window.__azPPSeen === 'undefined') {
        window.__azPPSeen = true;
        cancels.draw = AZ.tween(650, paintDraw, null, AZ.EASE.inOut);
      } else paintDraw(1);
    }
    paintHead();

    // ---- open a year: click a line or label, Enter or Space when focused
    hits.concat(labs).forEach((n) => {
      const yr = Number(n.getAttribute('data-y'));
      n.addEventListener('click', () => { if (drill == null && !busy) go(yr); });
      n.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && drill == null && !busy) { e.preventDefault(); go(yr); } });
    });

    // ---- hover by position, so the gaps between marks still register
    const monthAt = (clientX) => { const r = svg.getBoundingClientRect(); return Math.max(0, Math.min(11, Math.floor((clientX - r.left - ml) / bw))); };
    svg.addEventListener('mousemove', (e) => {
      if (busy) return;
      const r = svg.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
      if (px < ml || px > W - mr + 4 || py < mt - 4 || py > mt + ih + 4) { tip.hide(); guide.style.display = 'none'; dotsG.innerHTML = ''; svg.querySelectorAll('.pp-bar').forEach((b) => b.setAttribute('fill-opacity', '1')); return; }
      const m = monthAt(e.clientX), b = el.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
      if (drill == null) {
        const have = Y.filter((o) => o.cum[m] != null).sort((a, b2) => b2.y - a.y);
        if (!have.length) { tip.hide(); return; }
        guide.setAttribute('x1', xm(m)); guide.setAttribute('x2', xm(m)); guide.style.display = '';
        dotsG.innerHTML = have.map((o) => '<circle cx="' + xm(m).toFixed(1) + '" cy="' + yA(o.cum[m]).toFixed(1) + '" r="' + (o === latest ? 4 : 3) + '" fill="' + shade(o) + '" stroke="#fff" stroke-width="1.5"/>').join('');
        tip.show('<b>Through ' + months[m] + '</b>' + have.map((o) => AZ.row(String(o.y), AZ.money(o.cum[m], 1), shade(o) === INK ? '#FFFFFF' : shade(o))).join(''), x, y);
      } else {
        const o = B.o, p = B.p, v = o.mon[m], pv = p ? p.mon[m] : null;
        guide.style.display = 'none';
        svg.querySelectorAll('.pp-bar').forEach((bar) => bar.setAttribute('fill-opacity', Number(bar.getAttribute('data-m')) === m ? '1' : '0.45'));
        if (v == null && pv == null) { tip.hide(); return; }
        tip.show('<b>' + months[m] + ' ' + o.y + '</b>' + (v != null ? AZ.row(String(o.y), AZ.money(v, 2), '#FFFFFF') : AZ.row(String(o.y), 'no data')) + (pv != null ? AZ.row(String(p.y), AZ.money(pv, 2), AZ.T.slate[3]) : '') + (v != null && pv ? AZ.row('Change', AZ.pct(v / pv - 1, 1, true)) : ''), x, y);
      }
    });
    svg.addEventListener('mouseleave', () => { tip.hide(); guide.style.display = 'none'; dotsG.innerHTML = ''; svg.querySelectorAll('.pp-bar').forEach((b) => b.setAttribute('fill-opacity', '1')); });
    const onKey = (e) => { if (e.key === 'Escape' && drill != null) go(null); };
    window.addEventListener('keydown', onKey);
    return () => { Object.keys(cancels).forEach((k) => { if (cancels[k]) cancels[k](); }); window.removeEventListener('keydown', onKey); };
  }
});
