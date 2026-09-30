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

// Search: [sales] [store] [date].quarterly     (columns arrive as "store", "Quarter(date)" and "Total sales")
// A wall of small multiples: one mini area chart per store, quarterly sales. Scale toggle (same scale for all or each its own),
// sort toggle (Sales / Change vs last year / Name). Minis rise in with a stagger; sort and scale changes tween in place.
// Interactions: hover a mini for its numbers at the quarter under the pointer; click a store (Enter or Space when focused)
// and that mini expands (FLIP) to fill the tile as a full quarterly chart against the same quarters a year earlier.
// Crumbs, Back and Escape shrink it back into place. No library, no fetch: plain SVG.
const INK = AZ.T.ink, SLATE = AZ.T.slate;
let scaleMode = 'same';   // 'same' | 'own'
let sortBy = 'sales';     // 'sales' | 'change' | 'name'
let drill = null;         // store name when one store is open
let wallSeen = false;
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const qLabel = (t) => 'Q' + (Math.floor(new Date(t).getUTCMonth() / 3) + 1) + ' ' + AZ.year(t);
const nice = (max) => {
  const raw = (max || 1) / 4, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  const t = []; for (let v = 0; v <= max + step * 0.999; v += step) t.push(v);
  return { ticks: t, top: t[t.length - 1] };
};

AZ.boot({
  need: 'sales by store and quarter, e.g. [sales] [store] [date].quarterly',
  render: async ({ el, rows, schema }) => {
    const sK = AZ.col(schema, /store/i), dK = AZ.col(schema, /date|quarter/i), vK = AZ.col(schema, /sales/i);
    const qset = new Set(), M = new Map();
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]); if (!isFinite(t)) return;
      qset.add(t);
      const n = String(r[sK]);
      if (!M.has(n)) M.set(n, { n: n, m: new Map() });
      const o = M.get(n); o.m.set(t, (o.m.get(t) || 0) + AZ.num(r[vK]));
    });
    const Q = Array.from(qset).sort((a, b) => a - b), nQ = Q.length;
    if (!M.size || !nQ) {
      AZ.paint(el, '<div class="az-empty"><b>No stores to draw</b><span>The current filter returns no store rows. Search: [sales] [store] [date].quarterly</span></div>');
      return;
    }
    const lastT = Q[nQ - 1], lyT = (() => { const d = new Date(lastT); d.setUTCFullYear(d.getUTCFullYear() - 1); return d.getTime(); })();
    const qIdx = new Map(Q.map((t, i) => [t, i])), lyI = qIdx.has(lyT) ? qIdx.get(lyT) : -1;
    const St = Array.from(M.values()).map((o) => {
      o.v = Q.map((t) => (o.m.has(t) ? o.m.get(t) : null));
      o.total = o.v.reduce((a, x) => a + (x || 0), 0);
      o.latest = o.v[nQ - 1]; o.ly = lyI >= 0 ? o.v[lyI] : null;
      o.chg = o.latest != null && o.ly ? o.latest / o.ly - 1 : null;
      o.max = Math.max.apply(null, o.v.map((x) => x || 0)) || 1;
      return o;
    });
    if (drill && !M.has(drill)) drill = null;
    const n = St.length, gmax = Math.max.apply(null, St.map((o) => o.max));
    const qTot = Q.map((t, i) => St.reduce((a, o) => a + (o.v[i] || 0), 0));

    // ---- header text, computed from the rows
    const totLatest = qTot[nQ - 1], totLy = lyI >= 0 ? qTot[lyI] : null;
    const withChg = St.filter((o) => o.chg != null).sort((a, b) => b.chg - a.chg);
    let lineAll = '<b>' + qLabel(lastT) + '</b>: ' + AZ.money(totLatest, 1) + ' across ' + n + (n === 1 ? ' store' : ' stores');
    if (totLy) lineAll += ', ' + AZ.pct(totLatest / totLy - 1, 1, true) + ' on ' + qLabel(lyT);
    if (withChg.length > 1) lineAll += '. Widest gap: ' + AZ.esc(withChg[0].n) + ' ' + AZ.pct(withChg[0].chg, 1, true) + ' to ' + AZ.esc(withChg[withChg.length - 1].n) + ' ' + AZ.pct(withChg[withChg.length - 1].chg, 1, true);
    lineAll += '.';
    const notes = [];
    if (nQ >= 3 && qTot[0] < qTot[1] * 0.5) notes.push('The first quarter (' + qLabel(Q[0]) + ') totals ' + AZ.money(qTot[0], 1) + ' against ' + AZ.money(qTot[1], 1) + ' the next, so it is a part quarter.');
    if (nQ >= 3 && qTot[nQ - 1] < qTot[nQ - 2] * 0.5) notes.push('The latest quarter (' + qLabel(lastT) + ') looks partial.');
    const capAll = (scaleMode === 'same' ? 'Every mini shares one scale, so heights compare across stores.' : 'Each mini has its own scale, so shapes compare, not heights.') + ' The dot marks ' + qLabel(lastT) + '. ' + notes.join(' ');

    el.innerHTML =
      '<div class="sw-top"><div class="sw-title" id="sw-title">Quarterly sales by store</div>'
      + '<div class="sw-ctl" id="sw-ctl"><div class="sw-seg" role="group" aria-label="Scale" id="sw-scale"><button type="button" data-v="same">Same scale</button><button type="button" data-v="own">Each own scale</button></div>'
      + '<div class="sw-seg" role="group" aria-label="Sort" id="sw-sort"><button type="button" data-v="sales">Sales</button><button type="button" data-v="change">Change vs last year</button><button type="button" data-v="name">Name</button></div></div>'
      + '<button type="button" class="sw-back" id="sw-back" style="display:none">Back</button></div>'
      + '<div class="sw-line" id="sw-line"></div>'
      + '<div class="sw-stage" id="sw-stage"><div class="sw-wall" id="sw-wall"><div class="sw-in" id="sw-in"></div></div></div>'
      + '<div class="sw-cap" id="sw-cap"></div>';
    const stage = document.getElementById('sw-stage'), wall = document.getElementById('sw-wall'), inner = document.getElementById('sw-in');
    document.getElementById('sw-line').innerHTML = lineAll; document.getElementById('sw-cap').textContent = capAll;
    await AZ.settle();
    const SW = Math.max(180, stage.clientWidth), SH = Math.max(120, stage.clientHeight - 6), gap = 8;
    let best = { c: 1, s: -1 };
    for (let c = 1; c <= Math.min(10, n); c++) {
      const cw0 = (SW - (c - 1) * gap) / c, rows0 = Math.ceil(n / c), ch0 = (SH - (rows0 - 1) * gap) / rows0;
      const sc = Math.min(cw0 / 1.9, ch0) - (cw0 < 84 ? 100 : 0) - (ch0 < 50 ? 60 : 0);
      if (sc > best.s) best = { c: c, s: sc };
    }
    const cols = best.c, rowsN = Math.ceil(n / cols), cw = Math.floor((SW - (cols - 1) * gap - (rowsN * 60 > SH ? 8 : 0)) / cols), ch = Math.max(50, Math.floor((SH - (rowsN - 1) * gap) / rowsN));
    inner.style.height = (rowsN * ch + (rowsN - 1) * gap) + 'px';
    const cancels = {};
    const cut = (s, px) => {
      const mc = Math.max(4, Math.floor(px / 5.6));
      if (s.length <= mc) return s;
      const m = /^(.*) (\(\d+\))$/.exec(s);
      if (!m) return s.slice(0, mc - 1) + '.';
      const room = mc - m[2].length - 1;
      return room >= 4 ? m[1].slice(0, room - 1) + '. ' + m[2] : s.slice(0, mc - 1) + '.';
    };

    // ---- minis
    const px0 = 6, px1 = cw - 8, py0 = 20, py1 = ch - 5;
    const xq = (i) => (nQ < 2 ? (px0 + px1) / 2 : px0 + (i / (nQ - 1)) * (px1 - px0));
    const showVal = cw >= 120;
    St.forEach((o, i) => {
      const d = document.createElement('div');
      d.className = 'sw-m'; d.tabIndex = 0; d.setAttribute('role', 'button'); d.setAttribute('aria-label', o.n + ': open quarterly chart');
      d.style.width = cw + 'px'; d.style.height = ch + 'px'; d.style.opacity = '0';
      d.innerHTML = '<svg viewBox="0 0 ' + cw + ' ' + ch + '" width="100%" height="100%" preserveAspectRatio="none"><text class="sw-nm" x="6" y="13">' + AZ.esc(cut(o.n, cw - 12 - (showVal ? 44 : 0))) + '</text>'
        + (showVal && o.latest != null ? '<text class="sw-vl" x="' + (cw - 6) + '" y="13" text-anchor="end">' + AZ.money(o.latest, 1) + '</text>' : '')
        + '<path class="sw-ar" fill="' + SLATE[1] + '" fill-opacity=".7"/><path class="sw-ln" fill="none" stroke="' + INK + '" stroke-width="1.4" stroke-linejoin="round"/><circle class="sw-dot" r="3" fill="' + INK + '" stroke="#fff" stroke-width="1.2"/><circle class="sw-hv" r="3" fill="' + SLATE[5] + '" stroke="#fff" stroke-width="1.2" style="display:none"/></svg>';
      inner.appendChild(d);
      o.el = d; o.ar = d.querySelector('.sw-ar'); o.ln = d.querySelector('.sw-ln'); o.dot = d.querySelector('.sw-dot'); o.hv = d.querySelector('.sw-hv');
    });
    const yMaxT = (o) => (scaleMode === 'same' ? gmax : o.max);
    const paintMini = (o, ymax) => {
      const yy = (v) => py1 - (v / ymax) * (py1 - py0);
      const pts = []; o.v.forEach((v, i) => { if (v != null) pts.push([xq(i), yy(v)]); });
      if (pts.length > 1) {
        const ln = 'M' + pts.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('L');
        o.ln.setAttribute('d', ln);
        o.ar.setAttribute('d', ln + 'L' + pts[pts.length - 1][0].toFixed(1) + ' ' + py1 + 'L' + pts[0][0].toFixed(1) + ' ' + py1 + 'Z');
      } else { o.ln.setAttribute('d', ''); o.ar.setAttribute('d', ''); }
      const lp = o.v[nQ - 1] != null ? [xq(nQ - 1), yy(o.v[nQ - 1])] : null;
      if (lp) { o.dot.setAttribute('cx', lp[0].toFixed(1)); o.dot.setAttribute('cy', lp[1].toFixed(1)); o.dot.style.display = ''; } else o.dot.style.display = 'none';
      o.cy = ymax;
    };
    St.forEach((o) => paintMini(o, yMaxT(o)));

    // ---- order and positions
    const cmp = { sales: (a, b) => b.total - a.total, change: (a, b) => (a.chg == null) - (b.chg == null) || (b.chg || 0) - (a.chg || 0), name: (a, b) => a.n.localeCompare(b.n) };
    const place = () => { St.slice().sort(cmp[sortBy]).forEach((o, j) => { o.tx = (j % cols) * (cw + gap); o.ty = Math.floor(j / cols) * (ch + gap); o.rank = j; }); };
    place();
    St.forEach((o) => { o.x = o.tx; o.y = o.ty; o.el.style.left = o.x + 'px'; o.el.style.top = o.y + 'px'; });
    const setBtns = () => {
      document.querySelectorAll('#sw-scale button').forEach((b) => b.classList.toggle('on', b.getAttribute('data-v') === scaleMode));
      document.querySelectorAll('#sw-sort button').forEach((b) => b.classList.toggle('on', b.getAttribute('data-v') === sortBy));
      document.getElementById('sw-cap').textContent = (scaleMode === 'same' ? 'Every mini shares one scale, so heights compare across stores.' : 'Each mini has its own scale, so shapes compare, not heights.') + ' The dot marks ' + qLabel(lastT) + '. ' + notes.join(' ');
    };
    document.querySelectorAll('#sw-scale button').forEach((b) => b.addEventListener('click', () => {
      const v = b.getAttribute('data-v'); if (v === scaleMode || drill) return; scaleMode = v; setBtns();
      if (cancels.scale) cancels.scale();
      const from = St.map((o) => o.cy), to = St.map((o) => yMaxT(o));
      cancels.scale = AZ.tween(450, (k) => St.forEach((o, i) => paintMini(o, AZ.lerp(from[i], to[i], k))), null, AZ.EASE.inOut);
    }));
    document.querySelectorAll('#sw-sort button').forEach((b) => b.addEventListener('click', () => {
      const v = b.getAttribute('data-v'); if (v === sortBy || drill) return; sortBy = v; setBtns(); place();
      if (cancels.sort) cancels.sort();
      const fx = St.map((o) => o.x), fy = St.map((o) => o.y);
      cancels.sort = AZ.tween(500, (k) => St.forEach((o, i) => { o.x = AZ.lerp(fx[i], o.tx, k); o.y = AZ.lerp(fy[i], o.ty, k); o.el.style.left = o.x.toFixed(1) + 'px'; o.el.style.top = o.y.toFixed(1) + 'px'; }), null, AZ.EASE.inOut);
    }));
    setBtns();

    // ---- entrance: fade and rise with a stagger, once per load
    const enter = (t) => St.forEach((o) => {
      const loc = AZ.EASE.out(clamp01((t * 900 - o.rank * 14) / 380));
      o.el.style.opacity = String(loc); o.el.style.transform = loc >= 1 ? '' : 'translateY(' + ((1 - loc) * 10).toFixed(1) + 'px)';
    });
    if (!wallSeen && !drill) { wallSeen = true; enter(0); cancels.enter = AZ.tween(900, enter, null, (t) => t); }
    else { wallSeen = true; enter(1); }

    // ---- hover a mini
    const tip = AZ.tip(el);
    St.forEach((o) => {
      const qAt = (e) => { const r = o.el.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * cw; let bi = -1, bd = 1e9; for (let i = 0; i < nQ; i++) { if (o.v[i] == null) continue; const dd = Math.abs(xq(i) - px); if (dd < bd) { bd = dd; bi = i; } } return bi; };
      o.el.addEventListener('mousemove', (e) => {
        if (drill || busy) return;
        const i = qAt(e), b = el.getBoundingClientRect();
        if (i < 0) { tip.hide(); return; }
        const yy = (v) => py1 - (v / o.cy) * (py1 - py0);
        o.hv.setAttribute('cx', xq(i).toFixed(1)); o.hv.setAttribute('cy', yy(o.v[i]).toFixed(1)); o.hv.style.display = i === nQ - 1 ? 'none' : '';
        const prevI = qIdx.get((() => { const d = new Date(Q[i]); d.setUTCFullYear(d.getUTCFullYear() - 1); return d.getTime(); })());
        const pv = prevI != null ? o.v[prevI] : null;
        tip.show('<b>' + AZ.esc(o.n) + '</b>' + AZ.row(qLabel(Q[i]), AZ.money(o.v[i], 2), '#FFFFFF') + (pv ? AZ.row('vs ' + qLabel(Q[prevI]), AZ.pct(o.v[i] / pv - 1, 1, true)) : '') + AZ.row('All quarters', AZ.money(o.total, 1)) + (o.chg != null ? AZ.row(qLabel(lastT) + ' vs last year', AZ.pct(o.chg, 1, true)) : ''), e.clientX - b.left, e.clientY - b.top);
      });
      o.el.addEventListener('mouseleave', () => { tip.hide(); o.hv.style.display = 'none'; });
      o.el.addEventListener('click', () => { if (!drill && !busy) go(o.n); });
      o.el.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && !drill && !busy) { e.preventDefault(); go(o.n); } });
    });

    // ---- drill: FLIP the mini out to the full tile
    let ov = null, ghost = null, full = null, sel = null, cur = 0, busy = false, src = null;
    const buildDetail = (o) => {
      const dh = document.createElement('div'); dh.className = 'sw-dh';
      const c = o.chg;
      dh.innerHTML = '<span><b>' + qLabel(lastT) + '</b>: ' + (o.latest != null ? AZ.money(o.latest, 1) : 'no sales') + (c != null ? ', ' + AZ.pct(c, 1, true) + ' on ' + qLabel(lyT) : '') + '. All quarters ' + AZ.money(o.total, 1) + '.</span><span class="sw-key"><i></i>Sales<i class="d"></i>Same quarter a year earlier</span>';
      const pl = document.createElement('div'); pl.className = 'sw-plot';
      full.appendChild(dh); full.appendChild(pl);
      const draw = () => {
        const W = Math.max(160, pl.clientWidth), H = Math.max(100, pl.clientHeight), ml = 46, mr = 16, mt = 10, mb = 22, iw = W - ml - mr, ih = H - mt - mb;
        const ly = o.v.map((v, i) => { const d = new Date(Q[i]); d.setUTCFullYear(d.getUTCFullYear() - 1); const j = qIdx.get(d.getTime()); return j != null ? o.v[j] : null; });
        const g = nice(Math.max(o.max, Math.max.apply(null, ly.map((x) => x || 0))));
        const X = (i) => (nQ < 2 ? ml + iw / 2 : ml + (i / (nQ - 1)) * iw), Yv = (v) => mt + ih - (v / g.top) * ih;
        let h = '';
        g.ticks.forEach((v) => { h += '<line class="sw-grid" x1="' + ml + '" x2="' + (W - mr) + '" y1="' + Yv(v).toFixed(1) + '" y2="' + Yv(v).toFixed(1) + '"/><text class="sw-tick" x="' + (ml - 6) + '" y="' + (Yv(v) + 4).toFixed(1) + '" text-anchor="end">' + (v >= 1e6 && v % 1e6 !== 0 ? AZ.money(v, 1) : AZ.money(v, 0)) + '</text>'; });
        const step = Math.max(1, Math.ceil((nQ * 72) / Math.max(1, iw)));
        for (let i = 0; i < nQ; i++) if ((nQ - 1 - i) % step === 0) h += '<text class="sw-tick" x="' + X(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (i === nQ - 1 && nQ > 1 ? 'end' : 'middle') + '">' + qLabel(Q[i]) + '</text>';
        const path = (arr) => { const pts = []; arr.forEach((v, i) => { if (v != null) pts.push([X(i), Yv(v)]); }); return pts; };
        const mine = path(o.v), prev = path(ly);
        const dstr = (p) => 'M' + p.map((a) => a[0].toFixed(1) + ' ' + a[1].toFixed(1)).join('L');
        if (mine.length > 1) h += '<path d="' + dstr(mine) + 'L' + mine[mine.length - 1][0].toFixed(1) + ' ' + (mt + ih) + 'L' + mine[0][0].toFixed(1) + ' ' + (mt + ih) + 'Z" fill="' + SLATE[1] + '" fill-opacity=".55"/>';
        if (prev.length > 1) h += '<path d="' + dstr(prev) + '" fill="none" stroke="' + SLATE[3] + '" stroke-width="1.6" stroke-dasharray="5 4" stroke-linejoin="round"/>';
        if (mine.length > 1) h += '<path d="' + dstr(mine) + '" fill="none" stroke="' + INK + '" stroke-width="2.2" stroke-linejoin="round"/>';
        const lp = mine.length && o.v[nQ - 1] != null ? mine[mine.length - 1] : null;
        if (lp) h += '<circle cx="' + lp[0].toFixed(1) + '" cy="' + lp[1].toFixed(1) + '" r="4" fill="' + INK + '" stroke="#fff" stroke-width="1.5"/>';
        h += '<line id="sw-g" y1="' + mt + '" y2="' + (mt + ih) + '" stroke="' + INK + '" stroke-opacity=".25" style="display:none"/><circle id="sw-gd" r="3.5" fill="' + INK + '" stroke="#fff" stroke-width="1.5" style="display:none"/>';
        pl.innerHTML = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">' + h + '</svg>';
        const sv = pl.firstChild, gl = sv.querySelector('#sw-g'), gd = sv.querySelector('#sw-gd');
        sv.addEventListener('mousemove', (e) => {
          if (busy) return;
          const r = sv.getBoundingClientRect(), px = e.clientX - r.left;
          let bi = -1, bd = 1e9; for (let i = 0; i < nQ; i++) { if (o.v[i] == null) continue; const dd = Math.abs(X(i) - px); if (dd < bd) { bd = dd; bi = i; } }
          if (bi < 0 || px < ml - 8 || px > W - mr + 8) { tip.hide(); gl.style.display = 'none'; gd.style.display = 'none'; return; }
          gl.setAttribute('x1', X(bi)); gl.setAttribute('x2', X(bi)); gl.style.display = ''; gd.setAttribute('cx', X(bi)); gd.setAttribute('cy', Yv(o.v[bi])); gd.style.display = '';
          const pv = ly[bi], b = el.getBoundingClientRect();
          tip.show('<b>' + AZ.esc(o.n) + ' ' + qLabel(Q[bi]) + '</b>' + AZ.row('Sales', AZ.money(o.v[bi], 2), '#FFFFFF') + (pv ? AZ.row('A year earlier', AZ.money(pv, 2), SLATE[3]) + AZ.row('Change', AZ.pct(o.v[bi] / pv - 1, 1, true)) : AZ.row('A year earlier', 'no data')), e.clientX - b.left, e.clientY - b.top);
        });
        sv.addEventListener('mouseleave', () => { tip.hide(); gl.style.display = 'none'; gd.style.display = 'none'; });
      };
      full.style.width = SW + 'px'; full.style.height = SH + 'px';
      return draw;
    };
    const rectOf = (o) => { const a = stage.getBoundingClientRect(), b = o.el.getBoundingClientRect(); return { x: b.left - a.left, y: b.top - a.top, w: b.width, h: b.height }; };
    const makeOverlay = (o) => {
      sel = o; src = rectOf(o);
      ov = document.createElement('div'); ov.className = 'sw-ov';
      ghost = document.createElement('div'); ghost.className = 'sw-gh'; ghost.appendChild(o.el.querySelector('svg').cloneNode(true));
      full = document.createElement('div'); full.className = 'sw-fl'; full.style.opacity = '0';
      ov.appendChild(ghost); ov.appendChild(full); stage.appendChild(ov);
      const draw = buildDetail(o); draw();
    };
    const frame = (k) => {
      cur = k;
      const kk = k;
      ov.style.left = AZ.lerp(src.x, 0, kk).toFixed(1) + 'px'; ov.style.top = AZ.lerp(src.y, 0, kk).toFixed(1) + 'px';
      ov.style.width = AZ.lerp(src.w, SW, kk).toFixed(1) + 'px'; ov.style.height = AZ.lerp(src.h, SH, kk).toFixed(1) + 'px';
      ghost.style.opacity = String(1 - clamp01(k * 3)); full.style.opacity = String(clamp01((k - 0.35) / 0.5));
      St.forEach((o) => { o.el.style.opacity = o === sel ? (k > 0 ? '0' : '1') : String(1 - clamp01(k * 1.4)); });
    };
    const paintHead = () => {
      const t = document.getElementById('sw-title'), l = document.getElementById('sw-line'), ctl = document.getElementById('sw-ctl'), back = document.getElementById('sw-back');
      if (!drill) { t.textContent = 'Quarterly sales by store'; l.innerHTML = lineAll; ctl.style.display = ''; back.style.display = 'none'; }
      else {
        t.innerHTML = AZ.crumbs(['All stores', drill]); AZ.wireCrumbs(t, () => go(null));
        const o = M.get(drill), rk = St.slice().sort(cmp.sales).indexOf(o) + 1;
        l.innerHTML = '<b>' + AZ.esc(drill) + '</b>: ' + AZ.money(o.total, 1) + ' over ' + o.v.filter((x) => x != null).length + ' quarters, ' + (n > 1 ? 'rank ' + rk + ' of ' + n + ' on sales.' : 'the only store in this filter.');
        ctl.style.display = 'none'; back.style.display = '';
      }
    };
    const go = (name) => {
      if (cancels.drill) cancels.drill();
      tip.hide();
      const from = cur;
      if (name) { if (ov) { ov.remove(); ov = null; } makeOverlay(M.get(name)); drill = name; }
      else { drill = null; if (ov && sel) { src = rectOf(sel); } }
      paintHead(); busy = true;
      const to = name ? 1 : 0, start = name ? 0 : from;
      if (name) frame(0);
      cancels.drill = AZ.tween(520, (k) => frame(AZ.lerp(start, to, k)), () => {
        busy = false;
        if (!to && ov) { ov.remove(); ov = null; St.forEach((o) => { o.el.style.opacity = '1'; }); sel = null; cur = 0; }
      }, AZ.EASE.inOut);
    };
    document.getElementById('sw-back').addEventListener('click', () => go(null));
    if (drill) { makeOverlay(M.get(drill)); frame(1); St.forEach((o) => { o.el.style.opacity = '0'; }); }
    paintHead();
    const onKey = (e) => { if (e.key === 'Escape' && drill) go(null); };
    window.addEventListener('keydown', onKey);
    return () => { Object.keys(cancels).forEach((k) => { if (cancels[k]) cancels[k](); }); window.removeEventListener('keydown', onKey); };
  }
});
