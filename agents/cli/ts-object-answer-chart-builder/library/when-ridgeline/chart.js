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
// Ridgeline: one overlapping filled area per year, Jan to Dec on x. Hover a month for every year; click a ridge
// (or its year label) to lift it to the front and open its monthly detail below, with the previous year as an outline.
let sel = null, entered = false;
const D3URLS = ['https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js', 'https://unpkg.com/d3@7/dist/d3.min.js'];

AZ.boot({
  need: 'sales and date at monthly grain, e.g. [sales] [date].monthly',
  render: async ({ el, rows, schema, w, h }) => {
    await AZ.loadScript(D3URLS, () => !!window.d3, 8000);
    const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i);
    const M = rows.map((r) => ({ t: AZ.ms(r[dK]), v: AZ.num(r[sK]) })).filter((r) => isFinite(r.t));
    if (!M.length) { AZ.paint(el, '<div class="az-empty"><b>No months in the result</b><span>The search needs [sales] [date].monthly</span></div>'); return; }

    const byY = new Map();
    M.forEach((r) => {
      const y = AZ.year(r.t), m = new Date(r.t).getUTCMonth();
      if (!byY.has(y)) byY.set(y, new Array(12).fill(null));
      byY.get(y)[m] = (byY.get(y)[m] || 0) + r.v;
    });
    const years = Array.from(byY.keys()).sort((a, b) => a - b);
    const latest = years[years.length - 1], N = years.length;
    const cnt = (y) => byY.get(y).filter((v) => v != null).length;
    const firstM = (y) => byY.get(y).findIndex((v) => v != null);
    const lastM = (y) => { const a = byY.get(y); for (let i = 11; i >= 0; i--) if (a[i] != null) return i; return 0; };
    const rangeLbl = (y) => AZ.MON[firstM(y)] + '-' + AZ.MON[lastM(y)];
    const partial = (y) => cnt(y) < 12;
    if (sel != null && years.indexOf(sel) < 0) sel = null;

    const INK = AZ.T.ink, S = AZ.T.slate;
    // latest year ink, older years slate with decreasing opacity
    const styleOf = (y) => {
      if (y === latest) return { c: INK, fo: 0.9, so: 1, w: 1.8 };
      const k = latest - y, i = years.indexOf(y);
      const back = N - 1 - i;
      return { c: back <= 1 ? S[6] : back <= 3 ? S[5] : S[4], fo: Math.max(0.16, 0.5 - 0.08 * (back - 1)), so: 1, w: 1.7 };
    };

    // Sub line: same-months change of the latest year and the seasonal peak of full years
    const full = years.filter((y) => !partial(y));
    const seas = new Array(12).fill(0);
    full.forEach((y) => byY.get(y).forEach((v, m) => { seas[m] += v || 0; }));
    let pkm = 0; seas.forEach((v, m) => { if (v > seas[pkm]) pkm = m; });
    const yt = AZ.ytd(M);
    let sub;
    if (yt && yt.comparable && yt.pct != null) {
      sub = '<b>' + AZ.MON[firstM(latest)] + '-' + AZ.MON[yt.month] + ' ' + latest + '</b> is ' + AZ.pct(yt.pct, 1, true) + ' on the same months of ' + (latest - 1)
        + (full.length ? '; full years peak in <b>' + AZ.MON[pkm] + '</b>' : '');
    } else if (cnt(latest) < 2) {
      sub = 'Only ' + cnt(latest) + ' month in ' + latest + ' under the current filter';
    } else {
      sub = '<b>' + latest + '</b> covers ' + rangeLbl(latest) + ': ' + AZ.money(byY.get(latest).reduce((a, v) => a + (v || 0), 0), 1) + ' in total';
    }

    const dhFull = Math.max(130, Math.round(h * 0.4));
    el.innerHTML = '<div class="rl-head"><div class="rl-title">Monthly sales, one ridge per year</div><div class="rl-sub">' + sub + '</div></div>'
      + '<div class="rl-plot" id="rl-plot"></div>'
      + '<div class="rl-detail" id="rl-detail" style="height:0"><div class="rl-dbar" id="rl-dbar"></div><div class="rl-dplot" id="rl-dplot"></div></div>';
    const plot = el.querySelector('#rl-plot'), det = el.querySelector('#rl-detail'), dbar = el.querySelector('#rl-dbar'), dplot = el.querySelector('#rl-dplot');
    const tip = AZ.tip(el);
    const NS = 'http://www.w3.org/2000/svg';
    const ML = 50, MR = 18;

    // animated state: k = detail openness, op / lift per year, ent = entrance progress per year
    const target = (s) => { const o = {}, l = {}; years.forEach((y) => { o[y] = s == null ? 1 : (y === s ? 1 : 0.22); l[y] = y === s ? 1 : 0; }); return { op: o, lift: l, k: s == null ? 0 : 1 }; };
    let cur = target(sel);
    let ent = {}; years.forEach((y) => { ent[y] = entered ? 1 : 0; });
    let hoverM = -1, hoverY = null, cancel = () => {}, cancelE = () => {};

    const order = () => { const o = years.slice(); if (sel != null) { o.splice(o.indexOf(sel), 1); o.push(sel); } return o; };
    let geo = null;

    function drawPlot() {
      const W = Math.max(120, plot.clientWidth), H = Math.max(80, plot.clientHeight);
      const top = 8, bot = 20, usable = H - top - bot;
      let vmax = 0; years.forEach((y) => byY.get(y).forEach((v) => { if (v != null && v > vmax) vmax = v; }));
      // scale so the tallest ridge just fits: baselines are 0.5 of the tallest ridge apart
      const ymax = years.map((y) => Math.max.apply(null, byY.get(y).map((v) => (v == null ? 0 : v))));
      const RATIO = 0.5;
      let B1 = 0; ymax.forEach((v, i) => { B1 = Math.max(B1, v - i * RATIO * vmax); });
      const sc = usable / ((B1 + (N - 1) * RATIO * vmax) || 1), step = RATIO * vmax * sc, rh = vmax * sc, B = B1 * sc, pw = W - ML - MR;
      const xm = (m) => ML + m / 11 * pw;
      const base = {}; years.forEach((y, i) => { base[y] = top + B + i * step - cur.lift[y] * Math.min(8, step * 0.4); });
      geo = { W, H, xm, base, sc, rh, step, pw };
      let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Ridgeline of monthly sales by year">';
      for (let m = 0; m < 12; m++) {
        const show = W > 420 || m % 2 === 0;
        s += '<line x1="' + xm(m).toFixed(1) + '" y1="' + top + '" x2="' + xm(m).toFixed(1) + '" y2="' + (H - bot) + '" stroke="' + AZ.T.grid + '" stroke-width="1"/>';
        if (show) s += '<text class="rl-mlbl" x="' + xm(m).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + AZ.MON[m] + '</text>';
      }
      s += '<line id="rl-guide" x1="0" y1="' + top + '" x2="0" y2="' + (H - bot) + '" stroke="' + INK + '" stroke-width="1.2" opacity="0"/>';
      order().forEach((y) => {
        const st = styleOf(y), a = byY.get(y), e = ent[y], op = cur.op[y];
        const pts = []; a.forEach((v, m) => { if (v != null) pts.push([m, v]); });
        if (!pts.length) return;
        const b = base[y];
        s += '<g class="rl-ridge" data-y="' + y + '" opacity="' + op.toFixed(3) + '">';
        if (pts.length === 1) {
          const hh = pts[0][1] * sc * e;
          s += '<line x1="' + xm(pts[0][0]) + '" y1="' + b + '" x2="' + xm(pts[0][0]) + '" y2="' + (b - hh) + '" stroke="' + st.c + '" stroke-width="5" stroke-linecap="round"/>';
        } else {
          const ar = d3.area().x((p) => xm(p[0])).y0(b).y1((p) => b - p[1] * sc * e).curve(d3.curveMonotoneX)(pts);
          const ln = d3.line().x((p) => xm(p[0])).y((p) => b - p[1] * sc * e).curve(d3.curveMonotoneX)(pts);
          s += '<path d="' + ar + '" fill="#fff"/><path d="' + ar + '" fill="' + st.c + '" fill-opacity="' + st.fo + '"/>'
            + '<path d="' + ln + '" fill="none" stroke="#fff" stroke-width="' + ((y === sel ? 2.4 : st.w) + 2.4) + '" stroke-linejoin="round"/><path class="rl-top" d="' + ln + '" fill="none" stroke="' + (y === latest ? '#fff' : st.c) + '" stroke-width="' + (y === sel ? 2.4 : st.w) + '" stroke-linejoin="round"/>';
        }
        s += '<line x1="' + ML + '" y1="' + b.toFixed(1) + '" x2="' + (W - MR) + '" y2="' + b.toFixed(1) + '" stroke="' + st.c + '" stroke-opacity=".35" stroke-width="1"/>';
        s += '</g>';
      });
      years.forEach((y) => {
        const b = base[y];
        s += '<text class="rl-ylbl' + (y === sel ? ' on' : '') + '" tabindex="0" role="button" data-y="' + y + '" aria-label="Open ' + y + ' monthly detail" x="' + (ML - 8) + '" y="' + (b - 3).toFixed(1) + '" text-anchor="end" opacity="' + cur.op[y].toFixed(2) + '">' + y + '</text>';
        if (partial(y) && W > 300) s += '<text class="rl-part" x="' + (ML - 8) + '" y="' + (b - 15).toFixed(1) + '" text-anchor="end" opacity="' + cur.op[y].toFixed(2) + '">' + rangeLbl(y) + '</text>';
      });
      s += '<g id="rl-dots"></g></svg>';
      plot.innerHTML = s;
      plot.querySelectorAll('.rl-ylbl').forEach((t) => {
        const y = Number(t.getAttribute('data-y'));
        t.addEventListener('click', (ev) => { ev.stopPropagation(); pick(y); });
        t.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(y); } });
      });
      if (hoverM >= 0) showHover(hoverM, null);
    }

    // value of ridge y at fractional month x, or null outside its months
    const valueAt = (y, fm) => {
      const a = byY.get(y), m0 = Math.floor(fm), m1 = Math.ceil(fm);
      if (m0 < 0 || m1 > 11 || a[m0] == null || a[m1] == null) return a[Math.round(fm)] != null && Math.abs(fm - Math.round(fm)) < 0.3 ? a[Math.round(fm)] : null;
      return a[m0] + (a[m1] - a[m0]) * (fm - m0);
    };
    function rowAt(px, py) {
      if (!geo) return null;
      const fm = Math.max(0, Math.min(11, (px - ML) / geo.pw * 11));
      const o = order().reverse();
      for (const y of o) {
        const v = valueAt(y, fm); if (v == null) continue;
        const b = geo.base[y];
        if (py <= b + 2 && py >= b - v * geo.sc - 3) return y;
      }
      let best = null, bd = 1e9;
      years.forEach((y) => { const d = Math.abs(py - geo.base[y]); if (d < bd && valueAt(y, fm) != null) { bd = d; best = y; } });
      return bd <= geo.step * 0.6 + 4 ? best : null;
    }
    function showHover(m, e) {
      if (!geo) return;
      const svg = plot.querySelector('svg'), g = svg.querySelector('#rl-guide'), dots = svg.querySelector('#rl-dots');
      g.setAttribute('x1', geo.xm(m)); g.setAttribute('x2', geo.xm(m)); g.setAttribute('opacity', 0.4);
      dots.innerHTML = '';
      let html = '<b>' + AZ.MON[m] + '</b>';
      years.slice().reverse().forEach((y) => {
        const v = byY.get(y)[m]; if (v == null) return;
        const st = styleOf(y), c = document.createElementNS(NS, 'circle');
        c.setAttribute('cx', geo.xm(m)); c.setAttribute('cy', geo.base[y] - v * geo.sc); c.setAttribute('r', y === latest ? 4 : 3);
        c.setAttribute('fill', '#fff'); c.setAttribute('stroke', st.c); c.setAttribute('stroke-width', 2); c.setAttribute('opacity', cur.op[y]);
        dots.appendChild(c);
        html += AZ.row(y + (partial(y) ? ' (' + rangeLbl(y) + ')' : ''), AZ.money(v, 2), y === latest ? '#FFFFFF' : S[3]);
      });
      if (e) { const b = el.getBoundingClientRect(); tip.show(html, e.clientX - b.left, e.clientY - b.top); }
    }
    function clearHover() {
      hoverM = -1;
      const svg = plot.querySelector('svg'); if (!svg) return;
      svg.querySelector('#rl-guide').setAttribute('opacity', 0); svg.querySelector('#rl-dots').innerHTML = ''; tip.hide();
      plot.querySelectorAll('.rl-ridge').forEach((g) => g.classList.remove('hov'));
    }
    const onMove = (e) => {
      if (!geo) return;
      const b = plot.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * geo.W, py = (e.clientY - b.top) / b.height * geo.H;
      if (px < ML - 10 || px > geo.W - MR + 10) { plot.style.cursor = ''; return clearHover(); }
      const m = Math.max(0, Math.min(11, Math.round((px - ML) / geo.pw * 11)));
      hoverM = m; showHover(m, e);
      const y = rowAt(px, py);
      plot.style.cursor = y != null ? 'pointer' : '';
      plot.querySelectorAll('.rl-ridge').forEach((g) => g.classList.toggle('hov', y != null && Number(g.getAttribute('data-y')) === y));
    };
    const onClick = (e) => {
      const b = plot.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * geo.W, py = (e.clientY - b.top) / b.height * geo.H;
      const y = rowAt(px, py);
      if (y != null) pick(y);
    };
    plot.addEventListener('mousemove', onMove); plot.addEventListener('mouseleave', clearHover); plot.addEventListener('click', onClick);

    // ---- detail: columns for the selected year, previous year as outline
    function drawDetail() {
      if (sel == null) { dbar.innerHTML = ''; dplot.innerHTML = ''; return; }
      const a = byY.get(sel), pa = byY.get(sel - 1);
      const tot = a.reduce((x, v) => x + (v || 0), 0);
      let ptot = 0, both = 0, ctot = 0;
      if (pa) a.forEach((v, m) => { if (v != null && pa[m] != null) { ctot += v; ptot += pa[m]; both++; } });
      let pk = -1; a.forEach((v, m) => { if (v != null && (pk < 0 || v > a[pk])) pk = m; });
      const txt = '<b>' + sel + '</b>' + (partial(sel) ? ' (' + rangeLbl(sel) + ')' : '') + ': ' + AZ.money(tot, 1) + ', peak in ' + AZ.MON[pk] + ' at ' + AZ.money(a[pk], 1)
        + (pa && both ? '. ' + AZ.pct(ptot ? ctot / ptot - 1 : 0, 1, true) + ' on ' + (sel - 1) + (both < cnt(sel) ? ' for the ' + both + ' shared months' : '') : '. No ' + (sel - 1) + ' in this view to compare');
      dbar.innerHTML = AZ.crumbs(['All years', String(sel)]) + '<button type="button" class="rl-back" id="rl-back">Back</button><div class="rl-dsub">' + txt + '</div>';
      AZ.wireCrumbs(dbar, () => pick(null));
      dbar.querySelector('#rl-back').addEventListener('click', () => pick(null));
      const W = Math.max(120, dplot.clientWidth), H = Math.max(50, dplot.clientHeight), top = 6, bot = 18, pw = W - ML - MR, xm = (m) => ML + m / 11 * pw;
      let vmax = 0; a.forEach((v) => { if (v != null && v > vmax) vmax = v; }); if (pa) pa.forEach((v) => { if (v != null && v > vmax) vmax = v; });
      const sc = (H - top - bot) / (vmax || 1), bw = Math.max(6, pw / 11 * 0.5), st = styleOf(sel);
      let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Monthly sales for ' + sel + '">';
      s += '<line x1="' + ML + '" y1="' + (H - bot) + '" x2="' + (W - MR) + '" y2="' + (H - bot) + '" stroke="' + AZ.T.grid + '"/>';
      s += '<text class="rl-mlbl" x="' + (ML - 8) + '" y="' + (top + 8) + '" text-anchor="end">' + AZ.money(vmax, 0) + '</text>';
      for (let m = 0; m < 12; m++) {
        const v = a[m], pv = pa ? pa[m] : null;
        if (W > 420 || m % 2 === 0) s += '<text class="rl-mlbl" x="' + xm(m).toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle">' + AZ.MON[m] + '</text>';
        if (v != null) s += '<rect class="rl-bar" data-m="' + m + '" x="' + (xm(m) - bw / 2).toFixed(1) + '" y="' + (H - bot - v * sc).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + (v * sc).toFixed(1) + '" fill="' + st.c + '" fill-opacity="' + (sel === latest ? 0.9 : 0.75) + '" rx="1"/>';
        if (pv != null) s += '<rect class="rl-prev" x="' + (xm(m) - bw / 2 - 2).toFixed(1) + '" y="' + (H - bot - pv * sc).toFixed(1) + '" width="' + (bw + 4).toFixed(1) + '" height="' + (pv * sc).toFixed(1) + '" fill="none" stroke="' + S[3] + '" stroke-width="1.5" stroke-dasharray="3 2"/>';
      }
      s += '</svg>';
      dplot.innerHTML = s;
      if (cur.k < 1) dplot.querySelectorAll('.rl-bar').forEach((r) => { r.style.transformOrigin = '50% 100%'; r.style.transformBox = 'fill-box'; r.style.transform = 'scaleY(' + Math.max(0.001, cur.k) + ')'; });
    }
    const dOver = (e) => {
      if (sel == null) return;
      const b = dplot.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * Math.max(120, dplot.clientWidth);
      const pw = Math.max(120, dplot.clientWidth) - ML - MR, m = Math.max(0, Math.min(11, Math.round((px - ML) / pw * 11)));
      const v = byY.get(sel)[m]; if (v == null) return dOut();
      const pv = byY.get(sel - 1) ? byY.get(sel - 1)[m] : null;
      dplot.querySelectorAll('.rl-bar').forEach((r) => r.classList.toggle('hov', Number(r.getAttribute('data-m')) === m));
      const eb = el.getBoundingClientRect();
      tip.show('<b>' + AZ.MON[m] + ' ' + sel + '</b>' + AZ.row('Sales', AZ.money(v, 2)) + (pv != null ? AZ.row(AZ.MON[m] + ' ' + (sel - 1), AZ.money(pv, 2)) + AZ.row('Change', AZ.pct(pv ? v / pv - 1 : 0, 1, true)) : ''), e.clientX - eb.left, e.clientY - eb.top);
    };
    const dOut = () => { tip.hide(); dplot.querySelectorAll('.rl-bar').forEach((r) => r.classList.remove('hov')); };
    dplot.addEventListener('mousemove', dOver); dplot.addEventListener('mouseleave', dOut);

    // ---- state changes: lift and open, or close, as one tween
    function apply() {
      det.style.height = Math.round(cur.k * dhFull) + 'px';
      det.style.opacity = String(Math.min(1, cur.k * 1.4));
      drawPlot();
    }
    function pick(y) {
      const next = (y === sel) ? null : y;
      cancel(); clearHover();
      const from = { op: Object.assign({}, cur.op), lift: Object.assign({}, cur.lift), k: cur.k };
      sel = next;
      const to = target(sel);
      drawDetail();
      cancel = AZ.tween(450, (e) => {
        years.forEach((yy) => { cur.op[yy] = AZ.lerp(from.op[yy], to.op[yy], e); cur.lift[yy] = AZ.lerp(from.lift[yy], to.lift[yy], e); });
        cur.k = AZ.lerp(from.k, to.k, e);
        apply();
        if (sel != null) dplot.querySelectorAll('.rl-bar').forEach((r) => { r.style.transformOrigin = '50% 100%'; r.style.transformBox = 'fill-box'; r.style.transform = 'scaleY(' + Math.max(0.001, cur.k) + ')'; });
      }, () => { if (sel == null) { dbar.innerHTML = ''; dplot.innerHTML = ''; } apply(); });
    }
    const onKey = (e) => { if (e.key === 'Escape' && sel != null) pick(null); };
    window.addEventListener('keydown', onKey);

    // initial paint (detail is laid out at its final height first so the plot measures correctly)
    det.style.height = Math.round(cur.k * dhFull) + 'px';
    det.style.opacity = cur.k ? '1' : '0';
    drawDetail();
    if (!entered && !AZ.reduced()) {
      drawPlot();
      const total = 560, dur = 260, gap = N > 1 ? (total - dur) / (N - 1) : 0;
      cancelE = AZ.tween(total, (e) => {
        const t = e * total;
        years.forEach((y, i) => { ent[y] = AZ.EASE.out(Math.max(0, Math.min(1, (t - i * gap) / dur))); });
        drawPlot();
      }, () => { years.forEach((y) => { ent[y] = 1; }); drawPlot(); }, (x) => x);
    } else { years.forEach((y) => { ent[y] = 1; }); drawPlot(); }
    entered = true;

    return () => { cancel(); cancelE(); window.removeEventListener('keydown', onKey); };
  }
});
