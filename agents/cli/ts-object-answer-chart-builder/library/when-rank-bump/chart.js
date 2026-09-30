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

// Search: [sales] [item type] [date].yearly
// Bump chart of item-type rank by year (hand-built SVG, no library). Toggle Rank / Sales for the vertical axis.
// Hover a line to highlight it and read year, rank and sales; click to pin it; click empty space to release.
// The first and last year are marked "partial" when their sales are well below the years between them
// (the yearly search carries no month detail, so the exact months cannot be read from the rows).
let mode = 'rank', pinned = null;

AZ.boot({
  need: 'sales, item type and date at yearly grain, e.g. [sales] [item type] [date].yearly',
  render: async ({ el, rows, schema, redraw }) => {
    const iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|year/i), sK = AZ.col(schema, /sales/i);
    const S = new Map(), items = new Set(), yrs = new Set();
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]); if (!isFinite(t)) return;
      const y = AZ.year(t), it = String(r[iK]);
      items.add(it); yrs.add(y);
      S.set(it + '|' + y, (S.get(it + '|' + y) || 0) + AZ.num(r[sK]));
    });
    const Y = Array.from(yrs).sort((a, b) => a - b), I = Array.from(items);
    if (!Y.length) { AZ.paint(el, '<div class="az-empty"><b>No years in the result</b><span>The search needs [sales] [item type] [date].yearly</span></div>'); return; }
    if (pinned && I.indexOf(pinned) < 0) pinned = null;
    const val = (it, y) => (S.has(it + '|' + y) ? S.get(it + '|' + y) : null);
    const tot = (y) => I.reduce((a, it) => a + (val(it, y) || 0), 0);
    // ranks per year
    const rank = new Map();
    Y.forEach((y) => {
      I.filter((it) => val(it, y) != null).sort((a, b) => val(b, y) - val(a, y) || a.localeCompare(b)).forEach((it, k) => rank.set(it + '|' + y, k + 1));
    });
    const R = (it, y) => rank.get(it + '|' + y) || null;
    // partial years: first / last year well under the mean of the years between them
    const interior = Y.slice(1, -1), mean = interior.length ? interior.reduce((a, y) => a + tot(y), 0) / interior.length : 0;
    const isPartial = (y) => mean > 0 && (y === Y[0] || y === Y[Y.length - 1]) && tot(y) < 0.85 * mean;
    const nRank = Math.max(1, Math.max.apply(null, I.map((it) => Math.max.apply(null, Y.map((y) => R(it, y) || 0)))));

    // Header line from the rows: who leads, biggest mover between first and last year
    const y0 = Y[0], y1 = Y[Y.length - 1];
    let sub;
    const both = I.filter((it) => R(it, y0) && R(it, y1));
    const lead0 = I.find((it) => R(it, y0) === 1), lead1 = I.find((it) => R(it, y1) === 1);
    const held = Y.every((y) => I.find((it) => R(it, y) === 1) === lead1);
    if (Y.length < 2) sub = AZ.esc(lead0) + ' ranks first in ' + y0 + ' with ' + AZ.money(val(lead0, y0), 1) + ' of sales';
    else {
      const mv = both.map((it) => ({ it, d: R(it, y0) - R(it, y1) }));
      const up = mv.reduce((b, m) => (m.d > b.d ? m : b), mv[0] || { d: 0 }), dn = mv.reduce((b, m) => (m.d < b.d ? m : b), mv[0] || { d: 0 });
      const changed = mv.filter((m) => m.d !== 0).length;
      sub = (held ? '<b>' + AZ.esc(lead1) + '</b> is first in every year. ' : '<b>' + AZ.esc(lead0) + '</b> led in ' + y0 + ', <b>' + AZ.esc(lead1) + '</b> leads in ' + y1 + '. ')
        + (changed === 0 ? 'No item type changes rank between ' + y0 + ' and ' + y1 + '.'
          : 'Between ' + y0 + ' and ' + y1 + ', ' + (up.d > 0 ? '<b>' + AZ.esc(up.it) + '</b> climbs ' + up.d + (up.d === 1 ? ' place' : ' places') : '') + (up.d > 0 && dn.d < 0 ? ' and ' : '') + (dn.d < 0 ? '<b>' + AZ.esc(dn.it) + '</b> drops ' + (-dn.d) + (dn.d === -1 ? ' place' : ' places') : '') + '.');
    }

    const seg = [['rank', 'Rank'], ['sales', 'Sales']].map((k) => '<button type="button" data-k="' + k[0] + '" class="' + (k[0] === mode ? 'on' : '') + '">' + k[1] + '</button>').join('');
    el.innerHTML = '<div class="rb-top"><div class="rb-title">Item type ' + (mode === 'rank' ? 'rank' : 'sales') + ' by year</div><div class="rb-seg" role="group" aria-label="Vertical axis">' + seg + '</div></div><div class="rb-sub">' + sub + '</div><div class="rb-plot" id="rb-plot"></div>';
    el.querySelectorAll('.rb-seg button').forEach((b) => b.addEventListener('click', () => { mode = b.getAttribute('data-k'); redraw(); }));

    const box = document.getElementById('rb-plot'), W = Math.max(240, box.clientWidth), H = Math.max(140, box.clientHeight);
    const longest = Math.max.apply(null, I.map((it) => it.length)) + 6;
    const ml = mode === 'sales' ? 40 : Math.min(W * 0.28, longest * 6.4 + 30), mr = Math.min(W * 0.3, longest * 6.4 + 34), mt = 8, mb = 38;
    const iw = W - ml - mr, ih = H - mt - mb;
    const xs = (i) => (Y.length < 2 ? ml + iw / 2 : ml + (i * iw) / (Y.length - 1));
    let vmax = 0; I.forEach((it) => Y.forEach((y) => { const v = val(it, y); if (v != null && v > vmax) vmax = v; }));
    const ysr = (r) => mt + 6 + (nRank <= 1 ? (ih - 12) / 2 : ((r - 1) * (ih - 12)) / (nRank - 1));
    const step = (function () { const raw = vmax / 4 || 1, pw = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((n) => n * pw >= raw) * pw; })();
    const top = Math.max(step, Math.ceil(vmax / step) * step);
    const yss = (v) => mt + 6 + (ih - 12) * (1 - v / top);
    const yPos = (it, y) => (mode === 'rank' ? ysr(R(it, y)) : yss(val(it, y)));
    const fam = (it) => AZ.familyColor(it);
    const NS = 'http://www.w3.org/2000/svg';

    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Item type rank by year">';
    // partial year bands and gridlines
    Y.forEach((y, i) => { if (isPartial(y)) s += '<rect x="' + (xs(i) - (Y.length < 2 ? 40 : iw / (Y.length - 1) * 0.28)).toFixed(1) + '" y="' + mt + '" width="' + (Y.length < 2 ? 80 : iw / (Y.length - 1) * 0.56).toFixed(1) + '" height="' + ih + '" fill="' + AZ.T.slate[0] + '" opacity="0.7"/>'; });
    if (mode === 'sales') for (let v = 0; v <= top + 1; v += step) s += '<line x1="' + ml + '" x2="' + (ml + iw) + '" y1="' + yss(v).toFixed(1) + '" y2="' + yss(v).toFixed(1) + '" stroke="' + AZ.T.grid + '"/><text class="rb-gl" x="' + (ml - 4) + '" y="' + (yss(v) - 3).toFixed(1) + '" text-anchor="end" style="display:none">' + AZ.money(v, 0) + '</text>';
    Y.forEach((y, i) => {
      s += '<line x1="' + xs(i).toFixed(1) + '" x2="' + xs(i).toFixed(1) + '" y1="' + mt + '" y2="' + (mt + ih) + '" stroke="' + AZ.T.grid + '"/>';
      s += '<text class="rb-ax" x="' + xs(i).toFixed(1) + '" y="' + (H - 20) + '" text-anchor="middle">' + y + '</text>';
      if (isPartial(y)) s += '<text class="rb-ax2" x="' + xs(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">partial</text>';
    });
    // lines: draw in reverse rank order of the last year so the leaders sit on top
    const order = I.slice().sort((a, b) => (R(b, y1) || 99) - (R(a, y1) || 99));
    order.forEach((it) => {
      const k = AZ.esc(it);
      s += '<g class="rb-line" data-k="' + k + '">';
      for (let i = 0; i < Y.length - 1; i++) {
        if (val(it, Y[i]) == null || val(it, Y[i + 1]) == null) continue;
        const xa = xs(i), xb = xs(i + 1), ya = yPos(it, Y[i]), yb = yPos(it, Y[i + 1]), xm = (xa + xb) / 2;
        const dash = isPartial(Y[i]) || isPartial(Y[i + 1]);
        s += '<path d="M' + xa.toFixed(1) + ' ' + ya.toFixed(1) + ' C' + xm.toFixed(1) + ' ' + ya.toFixed(1) + ' ' + xm.toFixed(1) + ' ' + yb.toFixed(1) + ' ' + xb.toFixed(1) + ' ' + yb.toFixed(1) + '" fill="none" stroke="' + fam(it) + '" stroke-width="2.5" stroke-linecap="round"' + (dash ? ' stroke-dasharray="5 4"' : '') + '/>';
        s += '<path d="M' + xa.toFixed(1) + ' ' + ya.toFixed(1) + ' C' + xm.toFixed(1) + ' ' + ya.toFixed(1) + ' ' + xm.toFixed(1) + ' ' + yb.toFixed(1) + ' ' + xb.toFixed(1) + ' ' + yb.toFixed(1) + '" fill="none" stroke="transparent" stroke-width="12" data-hit="1"/>';
      }
      Y.forEach((y, i) => { if (val(it, y) != null) s += '<circle class="rb-pt" cx="' + xs(i).toFixed(1) + '" cy="' + yPos(it, y).toFixed(1) + '" r="4.5" fill="#fff" stroke="' + fam(it) + '" stroke-width="2.5" data-hit="1"/>'; });
      s += '</g>';
    });
    // end labels, spread so they do not collide
    const spread = (arr) => {
      const lo = mt + 6, hi = mt + ih - 4, gap = 13.5;
      arr.forEach((a) => { a.y0 = a.y; });
      arr.sort((a, b) => a.y - b.y);
      for (let n = 0; n < 60; n++) {
        for (let k = 1; k < arr.length; k++) {
          const d = arr[k].y - arr[k - 1].y;
          if (d < gap) { const m = (gap - d) / 2; arr[k - 1].y -= m; arr[k].y += m; }
        }
        arr.forEach((a) => { a.y = Math.max(lo, Math.min(hi, a.y)); });
      }
      return arr;
    };
    const left = spread(I.filter((it) => val(it, y0) != null).map((it) => ({ it, y: yPos(it, y0) })));
    const right = spread(I.filter((it) => val(it, y1) != null).map((it) => ({ it, y: yPos(it, y1) })));
    if (mode === 'rank') left.forEach((a) => { s += '<text class="rb-lab" data-k="' + AZ.esc(a.it) + '" x="' + (xs(0) - 11) + '" y="' + (a.y + 4).toFixed(1) + '" text-anchor="end">' + AZ.esc(a.it) + '</text>'; });
    right.forEach((a) => {
      if (Math.abs(a.y - a.y0) > 2) s += '<line x1="' + (xs(Y.length - 1) + 6) + '" y1="' + a.y0.toFixed(1) + '" x2="' + (xs(Y.length - 1) + 10) + '" y2="' + a.y.toFixed(1) + '" stroke="' + AZ.T.muted + '" stroke-width="1"/>';
      const v = mode === 'rank' ? '#' + R(a.it, y1) : AZ.money(val(a.it, y1), 1);
      s += '<text class="rb-lab" data-k="' + AZ.esc(a.it) + '" x="' + (xs(Y.length - 1) + 11) + '" y="' + (a.y + 4).toFixed(1) + '">' + AZ.esc(a.it) + ' <tspan class="v">' + v + '</tspan></text>';
    });
    s += '</svg>';
    box.innerHTML = s;
    if (mode === 'sales') box.querySelectorAll('.rb-gl').forEach((t) => { t.style.display = ''; });

    const svg = box.querySelector('svg'), tip = AZ.tip(box);
    const groups = Array.from(svg.querySelectorAll('.rb-line')), labs = Array.from(svg.querySelectorAll('.rb-lab'));
    const apply = (hov) => {
      const act = hov || pinned;
      groups.forEach((g) => { g.style.opacity = act && g.getAttribute('data-k') !== AZ.esc(act) ? 0.15 : 1; });
      labs.forEach((t) => { t.style.opacity = act && t.getAttribute('data-k') !== AZ.esc(act) ? 0.3 : 1; t.style.fontWeight = act && t.getAttribute('data-k') === AZ.esc(act) ? 600 : 400; });
    };
    const unesc = (k) => I.find((it) => AZ.esc(it) === k);
    apply(null);
    svg.addEventListener('mousemove', (e) => {
      const tgt = e.target.closest && e.target.closest('[data-k]');
      if (!tgt) { apply(null); tip.hide(); return; }
      const it = unesc(tgt.getAttribute('data-k'));
      apply(it);
      const b = box.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W;
      let k = 0, bd = 1e9; Y.forEach((y, i) => { const d = Math.abs(xs(i) - px); if (d < bd) { bd = d; k = i; } });
      let yy = Y[k]; if (val(it, yy) == null) { yy = Y.find((y) => val(it, y) != null); }
      let h = '<b>' + AZ.esc(it) + '</b>' + AZ.row('Year', String(yy) + (isPartial(yy) ? ' (partial)' : ''), fam(it)) + AZ.row('Rank', '#' + R(it, yy)) + AZ.row('Sales', AZ.money(val(it, yy), 1));
      const j = Y.indexOf(yy);
      if (j > 0 && R(it, Y[j - 1])) { const d = R(it, Y[j - 1]) - R(it, yy); h += AZ.row('Rank vs ' + Y[j - 1], d === 0 ? 'no change' : (d > 0 ? '+' : '-') + Math.abs(d) + (Math.abs(d) === 1 ? ' place' : ' places')); }
      tip.show(h, e.clientX - b.left, e.clientY - b.top);
    });
    svg.addEventListener('mouseleave', () => { apply(null); tip.hide(); });
    svg.addEventListener('click', (e) => {
      const tgt = e.target.closest && e.target.closest('[data-k]');
      const it = tgt ? unesc(tgt.getAttribute('data-k')) : null;
      pinned = it && it !== pinned ? it : null;
      apply(pinned);
    });
  }
});
