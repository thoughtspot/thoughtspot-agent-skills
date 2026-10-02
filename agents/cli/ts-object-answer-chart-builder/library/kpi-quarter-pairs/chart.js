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

/* body */

// Search: [sales] [quantity purchased] [date].monthly
// KPI set, shared prelude (each tile of the set stores this in full).
const NEED = 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly';
const NS = 'http://www.w3.org/2000/svg';
const MET = {
  sales: { tab: 'Sales', label: 'Sales', month: (r) => r.s, agg: (a) => a.reduce((x, r) => x + r.s, 0), fmt: (v) => AZ.money(v, 1), fmtM: (v) => AZ.money(v, 2) },
  units: { tab: 'Units', label: 'Units sold', month: (r) => r.u, agg: (a) => a.reduce((x, r) => x + r.u, 0), fmt: (v) => AZ.int(v), fmtM: (v) => Math.round(v).toLocaleString('en-US') },
  asp: { tab: 'Price', label: 'Price per unit', month: (r) => (r.u ? r.s / r.u : 0), agg: (a) => { const s = a.reduce((x, r) => x + r.s, 0), u = a.reduce((x, r) => x + r.u, 0); return u ? s / u : 0; }, fmt: (v) => '$' + v.toFixed(2), fmtM: (v) => '$' + v.toFixed(2) }
};
const MKEYS = ['sales', 'units', 'asp'];
let met = 'sales';
const CX = [];
const tw = (ms, step, done, ez) => { const c = AZ.tween(ms, step, done, ez); CX.push(c); return c; };
const stop = () => { CX.splice(0).forEach((f) => { try { f(); } catch (e) {} }); };
const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
const S = (tag, a, parent) => { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); if (parent) parent.appendChild(n); return n; };
// The core fades every direct child of #chart in with fill-mode both, which would pin a tooltip at opacity 1: give the tip its own root.
const mkTip = (el) => { const r = document.createElement('div'); r.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none'; el.appendChild(r); return AZ.tip(r); };
const rel = (box, e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
function prep(rows, schema) {
  const dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
  const M = rows.map((r) => ({ t: AZ.ms(r[dK]), s: AZ.num(r[sK]), u: AZ.num(r[uK]) })).filter((r) => isFinite(r.t)).sort((a, b) => a.t - b.t);
  return M.length ? M : null;
}
const emptyMsg = (el) => AZ.paint(el, '<div class="az-empty"><b>No months in this filter</b><span>This tile needs: ' + AZ.esc(NEED) + '</span></div>');
// Year to date against the same months of the year before, from the rows.
function yt(M, m) {
  const last = M[M.length - 1].t, ly = AZ.year(last), lm = new Date(last).getUTCMonth();
  const inY = (r, y) => AZ.year(r.t) === y && new Date(r.t).getUTCMonth() <= lm;
  const cur = M.filter((r) => inY(r, ly)), prev = M.filter((r) => inY(r, ly - 1));
  const ok = prev.length > 0 && prev.length === cur.length;
  const curV = m.agg(cur), prevV = ok ? m.agg(prev) : null;
  return { last, ly, lm, cur, prev, ok, curV, prevV, pc: ok && prevV ? curV / prevV - 1 : null, span: (cur.length && cur[0].t !== last ? AZ.monthShort(cur[0].t) + ' to ' + AZ.monthLabel(last) : AZ.monthLabel(last)) };
}
const dHtml = (y) => (y.pc == null ? 'No prior year in the current filter' : '<b class="' + (y.pc >= 0 ? 'up' : 'dn') + '">' + AZ.pct(y.pc, 1, true) + '</b> YTD vs same months last year');
const segHtml = () => '<div class="kp-seg" role="group" aria-label="Metric">' + MKEYS.map((k) => '<button type="button" data-k="' + k + '" class="' + (k === met ? 'on' : '') + '">' + MET[k].tab + '</button>').join('') + '</div>';
const wireSeg = (el, redraw) => el.querySelectorAll('.kp-seg button').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); met = b.getAttribute('data-k'); redraw(); }));
const sameMonthBefore = (M, t) => { const d = new Date(t); d.setUTCFullYear(d.getUTCFullYear() - 1); return M.find((r) => r.t === d.getTime()) || null; };
const ord = (n) => { const a = n % 100, b = n % 10; return n + (a >= 11 && a <= 13 ? 'th' : b === 1 ? 'st' : b === 2 ? 'nd' : b === 3 ? 'rd' : 'th'); };

// kpi-quarter-pairs: one pair of columns per quarter of the latest year, this year in ink against the same months last year in slate.
// Interactions: metric toggle, hover a pair, click a pair (or arrow keys then Enter) to see its months, Escape or Back to return.
let selQ = null;
AZ.boot({
  need: NEED,
  render: async ({ el, rows, schema, redraw }) => {
    const M = prep(rows, schema);
    if (!M) return emptyMsg(el);
    const m = MET[met], y = yt(M, m);
    const qs = [];
    [0, 1, 2, 3].forEach((q) => {
      const cur = y.cur.filter((r) => Math.floor(new Date(r.t).getUTCMonth() / 3) === q);
      if (!cur.length) return;
      const idx = cur.map((r) => new Date(r.t).getUTCMonth());
      const prev = M.filter((r) => AZ.year(r.t) === y.ly - 1 && idx.indexOf(new Date(r.t).getUTCMonth()) >= 0);
      const okp = prev.length === cur.length;
      qs.push({ q, label: 'Q' + (q + 1) + (cur.length < 3 ? '*' : ''), part: cur.length < 3, a: m.agg(cur), b: okp ? m.agg(prev) : null, months: cur, prevMonths: prev, okp });
    });
    if (selQ != null && !qs.some((z) => z.q === selQ)) selQ = null;
    const onKey = (e) => { if (e.key === 'Escape' && selQ != null) { selQ = null; redraw(); } };
    window.addEventListener('keydown', onKey);
    const off = () => { window.removeEventListener('keydown', onKey); stop(); };
    let tip = null;
    const mk = () => { tip = mkTip(el); };
    const dq = selQ != null ? qs.find((z) => z.q === selQ) : null;

    // items: [{label, a, b, title, aName, bName}]
    const draw = (box, items, onPick) => {
      const W = Math.max(60, box.clientWidth), H = Math.max(50, box.clientHeight), n = items.length, LB = 16, TOP = 16;
      const mx = Math.max.apply(null, items.map((z) => Math.max(z.a, z.b || 0))) || 1, gw = W / n, bw = Math.min(30, gw * 0.3), ch = H - LB - TOP;
      const svg = S('svg', { width: W, height: H, tabindex: 0, 'aria-label': 'Paired columns' }, box);
      S('line', { x1: 0, x2: W, y1: H - LB + 0.5, y2: H - LB + 0.5, stroke: AZ.T.grid }, svg);
      const gs = items.map((z, i) => {
        const g = S('g', {}, svg), cx = gw * (i + 0.5);
        const ra = S('rect', { x: (cx + 1.5).toFixed(1), width: bw, y: H - LB, height: 0, rx: 2, fill: AZ.T.ink }, g);
        const rb = z.b != null ? S('rect', { x: (cx - 1.5 - bw).toFixed(1), width: bw, y: H - LB, height: 0, rx: 2, fill: AZ.T.slate[2] }, g) : null;
        const tx = S('text', { x: cx.toFixed(1), y: H - 3, 'text-anchor': 'middle', 'font-size': 11, fill: AZ.T.muted }, g); tx.textContent = z.label;
        const vt = S('text', { x: cx.toFixed(1), y: H - LB - 4, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 600, fill: AZ.T.ink2, opacity: 0 }, g); vt.textContent = m.fmt(z.a);
        return { g, ra, rb, vt, ha: Math.max(1.5, z.a / mx * ch), hb: z.b != null ? Math.max(1.5, z.b / mx * ch) : 0 };
      });
      const T = 380 + 60 * n;
      tw(T, (k) => gs.forEach((s, i) => {
        const p = AZ.EASE.out(clamp01((k * T - i * 60) / 380)), ha = s.ha * p, hb = s.hb * p;
        s.ra.setAttribute('y', (H - LB - ha).toFixed(1)); s.ra.setAttribute('height', ha.toFixed(1));
        if (s.rb) { s.rb.setAttribute('y', (H - LB - hb).toFixed(1)); s.rb.setAttribute('height', hb.toFixed(1)); }
        const top = H - LB - Math.max(ha, hb) - 4; s.vt.setAttribute('y', top.toFixed(1)); s.vt.setAttribute('opacity', p);
      }), null, (t) => t);
      let hi = -1;
      const light = (i) => { hi = i; gs.forEach((s, j) => s.g.setAttribute('opacity', i < 0 || i === j ? 1 : 0.35)); };
      const show = (i, x, yy) => {
        const z = items[i];
        tip.show('<b>' + AZ.esc(z.title) + '</b>' + AZ.row(z.aName, m.fmtM(z.a), '#FFFFFF') + (z.b != null ? AZ.row(z.bName, m.fmtM(z.b), AZ.T.slate[3]) + (z.b ? AZ.row('Change', AZ.pct(z.a / z.b - 1, 1, true)) : '') : AZ.row('Last year', 'not in this filter')) + (onPick ? '<div class="sb-tk">Click for the months</div>' : ''), x, yy);
      };
      const at = (e) => Math.max(0, Math.min(n - 1, Math.floor(rel(box, e)[0] / gw)));
      box.addEventListener('mousemove', (e) => { const i = at(e), p = rel(el, e); light(i); show(i, p[0], p[1]); });
      box.addEventListener('mouseleave', () => { light(-1); tip.hide(); });
      if (onPick) {
        box.addEventListener('click', (e) => onPick(at(e)));
        svg.addEventListener('keydown', (e) => {
          if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); const i = hi < 0 ? n - 1 : Math.max(0, Math.min(n - 1, hi + (e.key === 'ArrowRight' ? 1 : -1))); light(i); show(i, gw * (i + 0.5), H * 0.3); }
          else if ((e.key === 'Enter' || e.key === ' ') && hi >= 0) { e.preventDefault(); onPick(hi); }
        });
        svg.addEventListener('blur', () => { light(-1); tip.hide(); });
        box.style.cursor = 'pointer';
      }
    };
    const keyHtml = (s1, s2, hint) => '<div class="kp-key"><span><i style="background:' + AZ.T.ink + '"></i>' + s1 + '</span><span><i style="background:' + AZ.T.slate[2] + '"></i>' + s2 + '</span>' + (hint ? '<span class="sb-hint">' + hint + '</span>' : '') + '</div>';

    if (dq) {
      const items = dq.months.map((r) => { const pr = sameMonthBefore(M, r.t); return { label: AZ.monthShort(r.t), a: m.month(r), b: pr ? m.month(pr) : null, title: AZ.monthLabel(r.t), aName: String(y.ly), bName: String(y.ly - 1) }; });
      const back = () => { selQ = null; redraw(); };
      el.innerHTML = '<div class="kp-top"><div class="kp-label">' + AZ.esc(m.label) + '</div><button type="button" class="kp-back" id="qp-back">Back</button></div>'
        + AZ.crumbs(['Quarters', 'Q' + (dq.q + 1) + ' ' + y.ly])
        + '<div class="kp-area" id="qp"></div>' + keyHtml(String(y.ly), String(y.ly - 1), '');
      mk();
      el.querySelector('#qp-back').addEventListener('click', back);
      AZ.wireCrumbs(el, back);
      draw(el.querySelector('#qp'), items, null);
      return off;
    }
    const items = qs.map((z) => ({ label: z.label, a: z.a, b: z.b, title: 'Q' + (z.q + 1) + ' ' + y.ly + (z.part ? ' (' + z.months.map((r) => AZ.monthShort(r.t)).join(', ') + ' only)' : ''), aName: String(y.ly), bName: String(y.ly - 1) }));
    el.innerHTML = '<div class="kp-top"><div class="kp-label">' + AZ.esc(m.label + ' YTD, by quarter') + '</div>' + segHtml() + '</div>'
      + '<div class="kp-hero">' + AZ.esc(m.fmt(y.curV)) + '</div><div class="kp-delta">' + dHtml(y) + '</div>'
      + '<div class="kp-area" id="qp"></div>' + keyHtml(String(y.ly), String(y.ly - 1), qs.some((z) => z.part) ? '* part quarter' : 'Click a pair');
    wireSeg(el, redraw);
    mk();
    draw(el.querySelector('#qp'), items, (i) => { selQ = qs[i].q; redraw(); });
    return off;
  }
});
