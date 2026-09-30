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

// Search: [sales] [region] [item type]
// Region rows x item-type columns on the slate ramp. Item types run left to right by total sales.
// Family colour appears only as the small bar above each column (editorial grouping, not a model column).
// Interactions: Sales / Share of region toggle; hover a cell; click a row or column header to isolate it (click again to clear).
let mode = 'sales';
let iso = null; // { k: 'r' | 'c', v: name }

AZ.boot({
  need: 'sales by region and item type, e.g. [sales] [region] [item type]',
  render: async ({ el, rows, schema, w, redraw }) => {
    const rK = AZ.col(schema, /region/i), iK = AZ.col(schema, /item/i), sK = AZ.col(schema, /sales/i);
    const cell = new Map(), rt = new Map(), ct = new Map();
    let all = 0;
    rows.forEach((r) => {
      const a = String(r[rK]), b = String(r[iK]), v = AZ.num(r[sK]);
      cell.set(a + '\u0001' + b, (cell.get(a + '\u0001' + b) || 0) + v);
      rt.set(a, (rt.get(a) || 0) + v); ct.set(b, (ct.get(b) || 0) + v); all += v;
    });
    const regs = Array.from(rt.keys()).sort((a, b) => rt.get(b) - rt.get(a));
    const items = Array.from(ct.keys()).sort((a, b) => ct.get(b) - ct.get(a));
    if (!regs.length || !items.length || all <= 0) {
      AZ.paint(el, '<div class="az-empty"><b>No region and item type sales</b><span>The current filter returns no rows. Search: [sales] [region] [item type]</span></div>');
      return;
    }
    if (iso && !(iso.k === 'r' ? rt.has(iso.v) : ct.has(iso.v))) iso = null;
    const key = (a, b) => a + '\u0001' + b;
    const val = (a, b) => cell.get(key(a, b));
    const share = (a, b) => { const v = val(a, b); return v == null ? null : v / rt.get(a); };
    const metric = (a, b) => (mode === 'sales' ? val(a, b) : share(a, b));
    let mx = 0;
    regs.forEach((a) => items.forEach((b) => { const m = metric(a, b); if (m != null && m > mx) mx = m; }));
    const S = AZ.T.slate;
    const bin = (m) => Math.min(S.length - 1, Math.floor((m / mx) * S.length * 0.999));

    // Header line: the biggest cell, and how many regions lead with the same item type
    let best = null;
    regs.forEach((a) => items.forEach((b) => { const v = val(a, b); if (v != null && (!best || v > best.v)) best = { a: a, b: b, v: v }; }));
    const leaders = regs.map((a) => items.reduce((t, b) => ((val(a, b) || 0) > (val(a, t) || 0) ? b : t), items[0]));
    const topItem = items[0], nTop = leaders.filter((x) => x === topItem).length;
    const line = '<b>' + AZ.esc(best.a) + ' ' + AZ.esc(best.b.toLowerCase()) + '</b> is the largest cell: ' + AZ.money(best.v, 1) + ', ' + AZ.pct(best.v / all, 1) + ' of sales. '
      + (regs.length === 1 ? AZ.esc(topItem) + ' is the top item here.' : nTop === regs.length ? AZ.esc(topItem) + ' is the top item in every region.' : AZ.esc(topItem) + ' is the top item in ' + nTop + ' of ' + regs.length + ' regions.');

    const showVals = (w - 28 - 66) / items.length >= 34;
    const cols = '66px repeat(' + items.length + ', minmax(0, 1fr))';
    let g = '<div class="hm-grid" id="hm-grid" style="grid-template-columns:' + cols + ';grid-template-rows:8px 62px repeat(' + regs.length + ', minmax(22px, 1fr))">';
    g += '<span></span>';
    items.forEach((b) => { g += '<span class="hm-fam" data-c="' + AZ.esc(b) + '" style="background:' + AZ.familyColor(b) + '"></span>'; });
    g += '<span></span>';
    items.forEach((b) => { g += '<button type="button" class="hm-ch" data-c="' + AZ.esc(b) + '" title="' + AZ.esc(b) + '">' + AZ.esc(b) + '</button>'; });
    regs.forEach((a) => {
      g += '<button type="button" class="hm-rh" data-r="' + AZ.esc(a) + '">' + AZ.esc(a) + '</button>';
      items.forEach((b) => {
        const m = metric(a, b);
        if (m == null) { g += '<span class="hm-c none" data-r="' + AZ.esc(a) + '" data-c="' + AZ.esc(b) + '" data-n="1"></span>'; return; }
        const k = bin(m), txt = showVals ? (mode === 'sales' ? AZ.money(m, 0) : AZ.pct(m, 0)) : '';
        g += '<span class="hm-c" data-r="' + AZ.esc(a) + '" data-c="' + AZ.esc(b) + '" style="background:' + S[k] + ';color:' + (k >= 4 ? '#fff' : AZ.T.ink) + '">' + txt + '</span>';
      });
    });
    g += '</div>';
    const fams = []; items.forEach((b) => { const f = AZ.familyOf(b); if (fams.indexOf(f) < 0) fams.push(f); });
    el.innerHTML =
      '<div class="hm-top"><div class="hm-title">Sales by region and item type</div>'
      + '<div class="hm-seg" role="group" aria-label="Measure"><button type="button" data-m="sales" class="' + (mode === 'sales' ? 'on' : '') + '">Sales</button><button type="button" data-m="share" class="' + (mode === 'share' ? 'on' : '') + '">Share of region</button></div></div><div class="hm-line">' + line + '</div>'
      + g
      + '<div class="hm-key"><span class="hm-ramp">' + S.map((c) => '<i style="background:' + c + '"></i>').join('') + '</span><span>' + (mode === 'sales' ? '$0 to ' + AZ.money(mx, 0) : '0% to ' + AZ.pct(mx, 0) + ' of a region') + '</span>'
      + fams.map((f) => '<span><i style="background:' + AZ.T.family[f] + '"></i>' + AZ.esc(f) + '</span>').join('')
      + '<button type="button" class="hm-clear" id="hm-clear">Show all</button></div>';
    el.querySelectorAll('.hm-seg button').forEach((b) => b.addEventListener('click', () => { mode = b.getAttribute('data-m'); redraw(); }));

    const grid = document.getElementById('hm-grid'), clear = document.getElementById('hm-clear');
    const paint = () => {
      grid.querySelectorAll('[data-r],[data-c]').forEach((n) => {
        const r = n.getAttribute('data-r'), c = n.getAttribute('data-c');
        let hit = true;
        if (iso) hit = iso.k === 'r' ? (r === iso.v) : (c === iso.v);
        // a row header has only data-r, a column header or swatch only data-c
        n.classList.toggle('hm-dim', !hit);
        if (n.classList.contains('hm-rh')) n.classList.toggle('on', !!iso && iso.k === 'r' && r === iso.v);
        if (n.classList.contains('hm-ch')) n.classList.toggle('on', !!iso && iso.k === 'c' && c === iso.v);
      });
      clear.style.visibility = iso ? 'visible' : 'hidden';
    };
    paint();
    const pick = (k, v) => { iso = iso && iso.k === k && iso.v === v ? null : { k: k, v: v }; paint(); };
    grid.querySelectorAll('.hm-rh').forEach((n) => n.addEventListener('click', () => pick('r', n.getAttribute('data-r'))));
    grid.querySelectorAll('.hm-ch').forEach((n) => n.addEventListener('click', () => pick('c', n.getAttribute('data-c'))));
    clear.addEventListener('click', () => { iso = null; paint(); });

    const tip = AZ.tip(el);
    grid.querySelectorAll('.hm-c').forEach((n) => {
      const a = n.getAttribute('data-r'), b = n.getAttribute('data-c');
      n.addEventListener('mousemove', (e) => {
        const bx = el.getBoundingClientRect(), v = val(a, b);
        const rank = items.slice().sort((x, y) => (val(a, y) || 0) - (val(a, x) || 0)).indexOf(b) + 1;
        const html = '<b>' + AZ.esc(a) + ' / ' + AZ.esc(b) + '</b>'
          + (v == null ? AZ.row('Sales', 'none in this filter') : AZ.row('Sales', AZ.money(v, 2), '#FFFFFF') + AZ.row('Share of ' + a, AZ.pct(v / rt.get(a), 1)) + AZ.row('Share of all sales', AZ.pct(v / all, 1)) + AZ.row('Rank in ' + a, rank + ' of ' + items.length))
          + AZ.row('Family', AZ.familyOf(b), AZ.familyColor(b));
        tip.show(html, e.clientX - bx.left, e.clientY - bx.top);
      });
      n.addEventListener('mouseleave', () => tip.hide());
    });
    grid.querySelectorAll('.hm-rh,.hm-ch').forEach((n) => {
      n.addEventListener('mousemove', (e) => {
        const bx = el.getBoundingClientRect(), r = n.getAttribute('data-r'), c = n.getAttribute('data-c');
        tip.show(r ? '<b>' + AZ.esc(r) + '</b>' + AZ.row('Sales', AZ.money(rt.get(r), 1)) + AZ.row('Share of all sales', AZ.pct(rt.get(r) / all, 1)) + AZ.row('Click', 'isolate this row')
          : '<b>' + AZ.esc(c) + '</b>' + AZ.row('Sales', AZ.money(ct.get(c), 1)) + AZ.row('Share of all sales', AZ.pct(ct.get(c) / all, 1)) + AZ.row('Family', AZ.familyOf(c), AZ.familyColor(c)) + AZ.row('Click', 'isolate this column'), e.clientX - bx.left, e.clientY - bx.top);
      });
      n.addEventListener('mouseleave', () => tip.hide());
    });
  }
});
