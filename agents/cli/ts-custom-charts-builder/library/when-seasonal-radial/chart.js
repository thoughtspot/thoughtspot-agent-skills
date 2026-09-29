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
// Radial chart: 12 months around a clock, one line per calendar year with at least 6 months of data
// (the latest year is always drawn). Hover a spoke for every year's value; click a year in the key to isolate it.
let iso = null;

AZ.boot({
  need: 'sales and date at monthly grain, e.g. [sales] [date].monthly',
  render: async ({ el, rows, schema, redraw }) => {
    const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i);
    const M = rows.map((r) => ({ t: AZ.ms(r[dK]), v: AZ.num(r[sK]) })).filter((r) => isFinite(r.t));
    if (!M.length) { AZ.paint(el, '<div class="az-empty"><b>No months in the result</b><span>The search needs [sales] [date].monthly</span></div>'); return; }

    // year -> 12 slots (null where the month has no data)
    const byY = new Map();
    M.forEach((r) => {
      const y = AZ.year(r.t), m = new Date(r.t).getUTCMonth();
      if (!byY.has(y)) byY.set(y, new Array(12).fill(null));
      byY.get(y)[m] = (byY.get(y)[m] || 0) + r.v;
    });
    const latest = Math.max.apply(null, Array.from(byY.keys()));
    const years = Array.from(byY.keys()).filter((y) => y === latest || byY.get(y).filter((v) => v != null).length >= 6).sort((a, b) => b - a);
    const cnt = (y) => byY.get(y).filter((v) => v != null).length;
    const partial = (y) => cnt(y) < 12;
    const lastMonth = (y) => { const a = byY.get(y); for (let i = 11; i >= 0; i--) if (a[i] != null) return i; return 0; };
    const firstMonth = (y) => byY.get(y).findIndex((v) => v != null);
    const rangeLbl = (y) => AZ.MON[firstMonth(y)] + '-' + AZ.MON[lastMonth(y)];
    if (iso != null && years.indexOf(iso) < 0) iso = null;

    const INK = AZ.T.ink, S = AZ.T.slate;
    const styleOf = (y) => {
      const k = years.indexOf(y);
      if (k === 0) return { c: INK, w: 3.2 };
      const cols = [S[5], S[4], S[3], S[2], S[2], S[2]], ws = [2, 1.7, 1.5, 1.3, 1.3, 1.3];
      if (dashOf(y)) return { c: S[4], w: 1.5 };
      return { c: cols[Math.min(k - 1, 5)], w: ws[Math.min(k - 1, 5)] };
    };
    const dashOf = (y) => (partial(y) && y !== latest ? '5 3' : '');

    // Header: peak and trough months of the latest year, from the rows
    const la = byY.get(latest);
    let pk = -1, tr = -1;
    la.forEach((v, i) => { if (v == null) return; if (pk < 0 || v > la[pk]) pk = i; if (tr < 0 || v < la[tr]) tr = i; });
    const sub = cnt(latest) < 2
      ? AZ.MON[pk] + ' ' + latest + ': ' + AZ.money(la[pk], 1) + ' (one month in the current filter)'
      : '<b>' + latest + '</b>' + (partial(latest) ? ' (' + rangeLbl(latest) + ')' : '') + ': peak in <b>' + AZ.MON[pk] + '</b> at ' + AZ.money(la[pk], 1) + ', low in <b>' + AZ.MON[tr] + '</b> at ' + AZ.money(la[tr], 1);

    const chips = years.map((y) => {
      const st = styleOf(y), on = iso === y, dim = iso != null && !on;
      return '<button type="button" class="rd-chip' + (on ? ' on' : '') + (dim ? ' dim' : '') + '" data-y="' + y + '" aria-pressed="' + on + '" title="Click to isolate ' + y + '">'
        + '<svg viewBox="0 0 18 6"><line x1="0" y1="3" x2="18" y2="3" stroke="' + st.c + '" stroke-width="' + Math.min(st.w, 3.2) + '"' + (dashOf(y) ? ' stroke-dasharray="4 2"' : '') + '/></svg>'
        + y + (partial(y) ? ' (' + rangeLbl(y) + (y === latest ? '' : ', partial') + ')' : '') + '</button>';
    }).join('');

    el.innerHTML = '<div class="rd-head"><div class="rd-title">Monthly sales around the year</div><div class="rd-sub">' + sub + '</div></div>'
      + '<div class="rd-plot" id="rd-plot"></div><div class="rd-key">' + chips + '</div>';
    el.querySelectorAll('.rd-chip').forEach((b) => b.addEventListener('click', () => { const y = Number(b.getAttribute('data-y')); iso = iso === y ? null : y; redraw(); }));

    const box = document.getElementById('rd-plot'), W = Math.max(120, box.clientWidth), H = Math.max(120, box.clientHeight);
    const cx = W / 2, cy = H / 2, R = Math.max(40, Math.min(W, H) / 2 - 24), r0 = R * 0.1;
    let vmax = 0; years.forEach((y) => byY.get(y).forEach((v) => { if (v != null && v > vmax) vmax = v; }));
    const raw = vmax / 4, pw = Math.pow(10, Math.floor(Math.log10(raw))), nice = [1, 2, 2.5, 5, 10].find((n) => n * pw >= raw) * pw;
    const top = nice * 4, rr = (v) => r0 + (R - r0) * (v / top);
    const ang = (m) => (m / 12) * Math.PI * 2 - Math.PI / 2;
    const pt = (m, v) => [cx + rr(v) * Math.cos(ang(m)), cy + rr(v) * Math.sin(ang(m))];

    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Radial chart of monthly sales by year">';
    for (let i = 1; i <= 4; i++) s += '<circle cx="' + cx + '" cy="' + cy + '" r="' + rr(nice * i).toFixed(1) + '" fill="none" stroke="' + AZ.T.grid + '" stroke-width="1"/>';
    for (let m = 0; m < 12; m++) {
      const a = ang(m), lx = cx + (R + 13) * Math.cos(a), ly = cy + (R + 13) * Math.sin(a);
      s += '<line x1="' + (cx + r0 * Math.cos(a)).toFixed(1) + '" y1="' + (cy + r0 * Math.sin(a)).toFixed(1) + '" x2="' + (cx + R * Math.cos(a)).toFixed(1) + '" y2="' + (cy + R * Math.sin(a)).toFixed(1) + '" stroke="' + AZ.T.grid + '" stroke-width="1"/>';
      s += '<text class="rd-lbl" x="' + lx.toFixed(1) + '" y="' + (ly + 4).toFixed(1) + '" text-anchor="middle">' + AZ.MON[m] + '</text>';
    }
    s += '<line id="rd-spoke" x1="0" y1="0" x2="0" y2="0" stroke="' + INK + '" stroke-width="1.5" opacity="0"/>';
    // draw oldest first so the latest year sits on top
    years.slice().reverse().forEach((y) => {
      const a = byY.get(y), st = styleOf(y), dim = iso != null && iso !== y;
      const pts = []; a.forEach((v, m) => { if (v != null) pts.push(pt(m, v)); });
      if (!pts.length) return;
      const closed = !partial(y);
      const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ') + (closed ? ' Z' : '');
      s += '<g opacity="' + (dim ? 0.2 : 1) + '">';
      if (pts.length > 1) s += '<path d="' + d + '" fill="none" stroke="' + st.c + '" stroke-width="' + st.w + '" stroke-linejoin="round"' + (dashOf(y) ? ' stroke-dasharray="' + dashOf(y) + '"' : '') + '/>';
      else s += '<circle cx="' + pts[0][0].toFixed(1) + '" cy="' + pts[0][1].toFixed(1) + '" r="3.5" fill="' + st.c + '"/>';
      s += '</g>';
    });
    s += '<g id="rd-dots"></g>';
    // ring labels last, above the lines, just right of the top spoke
    for (let i = 1; i <= 4; i++) s += '<text class="rd-ringlbl" text-anchor="end" x="' + (cx - 3) + '" y="' + (cy - rr(nice * i) + 11).toFixed(1) + '">' + AZ.money(nice * i, 0) + '</text>';
    s += '</svg>';
    box.innerHTML = s;

    const svg = box.querySelector('svg'), spoke = svg.querySelector('#rd-spoke'), dots = svg.querySelector('#rd-dots'), tip = AZ.tip(box);
    const NS = 'http://www.w3.org/2000/svg';
    const clear = () => { spoke.setAttribute('opacity', 0); dots.innerHTML = ''; tip.hide(); };
    box.addEventListener('mousemove', (e) => {
      const b = box.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W, py = (e.clientY - b.top) / b.height * H;
      const dx = px - cx, dy = py - cy, dist = Math.hypot(dx, dy);
      if (dist > R + 22 || dist < r0 * 0.5) return clear();
      let th = Math.atan2(dx, -dy); if (th < 0) th += Math.PI * 2;
      const m = Math.round(th / (Math.PI * 2 / 12)) % 12, a = ang(m);
      spoke.setAttribute('x1', cx + r0 * Math.cos(a)); spoke.setAttribute('y1', cy + r0 * Math.sin(a));
      spoke.setAttribute('x2', cx + R * Math.cos(a)); spoke.setAttribute('y2', cy + R * Math.sin(a)); spoke.setAttribute('opacity', 0.35);
      dots.innerHTML = '';
      let h = '<b>' + AZ.MON[m] + '</b>';
      years.forEach((y) => {
        const v = byY.get(y)[m];
        if (v == null || (iso != null && iso !== y)) return;
        const st = styleOf(y), p = pt(m, v), c = document.createElementNS(NS, 'circle');
        c.setAttribute('cx', p[0]); c.setAttribute('cy', p[1]); c.setAttribute('r', y === latest ? 4.5 : 3.2); c.setAttribute('fill', '#fff'); c.setAttribute('stroke', st.c); c.setAttribute('stroke-width', 2);
        dots.appendChild(c);
        h += AZ.row(String(y) + (partial(y) && y !== latest ? ' (partial)' : ''), AZ.money(v, 2), y === latest ? '#FFFFFF' : st.c === S[5] || st.c === S[4] ? '#8E9AAB' : st.c === S[2] ? '#B4BDC9' : st.c);
      });
      tip.show(h, e.clientX - b.left, e.clientY - b.top);
    });
    box.addEventListener('mouseleave', clear);
  }
});
