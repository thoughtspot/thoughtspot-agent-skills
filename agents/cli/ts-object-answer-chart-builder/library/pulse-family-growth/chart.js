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

// Search: [sales] [quantity purchased] [item type] [date].monthly
// Small-multiple cards, one per product family plus All families. Each card splits the sales change against a
// comparison period into a units (volume) effect and a price effect:
//   volume effect = (units_cur - units_prev) x price_prev ; price effect = (price_cur - price_prev) x units_cur
// The two always sum to the sales change. Family is an editorial grouping (AZ.familyOf), not a model column.
// Periods come from the rows: "Year to date" = the months of the latest year up to the latest month in the data,
// against the same months a year earlier; "Latest full year" = the newest year with all 12 months whose prior
// year also has 12 months (part years are skipped).
// Interactions: period toggle (tweens in place); hover a card or a row for the detail; click a card to expand it
// into its item types (the others compress into a strip); click it again or press Escape to close.
let mode = 'fy';
let openKey = null;
let shown = new Map(); // key -> last drawn sales, so a toggle counts from the old value
let firstPaint = true;
const FAMS = ['Outerwear', 'Tops and dresses', 'Bottoms', 'Swim and basics', 'Accessories', 'Other'];

AZ.boot({
  need: 'sales, quantity purchased, item type and date at monthly grain, e.g. [sales] [quantity purchased] [item type] [date].monthly',
  render: async ({ el, rows, schema, w }) => {
    const iK = AZ.col(schema, /item/i), dK = AZ.col(schema, /date|month/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const R = [];
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]), item = r[iK] == null ? '' : String(r[iK]);
      if (!isFinite(t) || !item) return;
      const d = new Date(t);
      R.push({ item, fam: AZ.familyOf(item), y: d.getUTCFullYear(), m: d.getUTCMonth(), t, s: AZ.num(r[sK]), u: AZ.num(r[uK]) });
    });
    if (!R.length) { AZ.paint(el, '<div class="az-empty"><b>No months in the result</b><span>The search needs: [sales] [quantity purchased] [item type] [date].monthly</span></div>'); return; }

    // ---- comparison windows, derived from the rows -------------------------------------------------
    const ym = {};
    let last = -Infinity;
    R.forEach((r) => { (ym[r.y] = ym[r.y] || new Set()).add(r.m); if (r.t > last) last = r.t; });
    const ly = AZ.year(last), lm = new Date(last).getUTCMonth();
    const PER = {};
    const common = [];
    for (let m = 0; m <= lm; m++) if (ym[ly] && ym[ly].has(m) && ym[ly - 1] && ym[ly - 1].has(m)) common.push(m);
    if (common.length) {
      const cs = new Set(common), a = common[0], b = common[common.length - 1];
      const span = a === b ? AZ.MON[a] : AZ.MON[a] + ' to ' + AZ.MON[b];
      const gap = common.length !== b - a + 1 ? ' (' + common.length + ' months both years have)' : '';
      PER.ytd = { ok: true, cur: (r) => r.y === ly && cs.has(r.m), prev: (r) => r.y === ly - 1 && cs.has(r.m), curLab: span + ' ' + ly, prevLab: span + ' ' + (ly - 1), cap: span + ' ' + ly + ' against ' + span + ' ' + (ly - 1) + gap };
    } else {
      PER.ytd = { ok: false, cap: 'No months of ' + (ly - 1) + ' in the filter to set against ' + AZ.monthLabel(last) };
    }
    const years = Object.keys(ym).map(Number).sort((x, y) => x - y);
    const full = years.filter((y) => ym[y].size === 12);
    let Y = null;
    for (let i = full.length - 1; i >= 0; i--) if (full.indexOf(full[i] - 1) >= 0) { Y = full[i]; break; }
    const partAfter = years.filter((y) => ym[y].size < 12 && (Y == null || y > Y));
    const partTxt = partAfter.map((y) => { const ms = Array.from(ym[y]).sort((p, q) => p - q); return y + ' is a part year (' + (ms.length > 1 ? AZ.MON[ms[0]] + ' to ' + AZ.MON[ms[ms.length - 1]] : AZ.MON[ms[0]]) + ')'; }).join(', ');
    if (Y != null) {
      PER.fy = { ok: true, cur: (r) => r.y === Y, prev: (r) => r.y === Y - 1, curLab: String(Y), prevLab: String(Y - 1), cap: 'Full year ' + Y + ' against ' + (Y - 1) + (partTxt ? '; ' + partTxt + ' and is left out' : '') };
    } else {
      PER.fy = { ok: false, cap: 'No two consecutive full years in the filter' + (partTxt ? '; ' + partTxt : '') };
    }
    // Re-resolve the period after a filter: fall back to the one that has a comparison.
    if (!PER[mode].ok) { const other = mode === 'fy' ? 'ytd' : 'fy'; if (PER[other].ok) mode = other; }

    // ---- aggregation and decomposition -------------------------------------------------------------
    const famsHere = FAMS.filter((f) => R.some((r) => r.fam === f));
    const single = famsHere.length === 1;
    const itemsHere = Array.from(new Set(R.map((r) => r.item)));
    const items1 = itemsHere.length === 1 ? itemsHere[0] : null;
    const cardKeys = (single ? [] : ['all']).concat(famsHere.map((f) => 'f:' + f));
    const nameOf = (k) => (k === 'all' ? 'All families' : k.slice(0, 2) === 'f:' ? k.slice(2) : k);
    const colorOf = (k) => (k === 'all' ? AZ.T.ink : k.slice(0, 2) === 'f:' ? (AZ.T.family[k.slice(2)] || AZ.T.muted) : AZ.familyColor(k));
    function aggregate(md) {
      const P = PER[md], by = new Map();
      const get = (k) => { let o = by.get(k); if (!o) { o = { cs: 0, cu: 0, ps: 0, pu: 0 }; by.set(k, o); } return o; };
      R.forEach((r) => {
        const c = P.ok ? P.cur(r) : true, p = P.ok && P.prev(r);
        if (!c && !p) return;
        [r.item, 'f:' + r.fam, 'all'].forEach((k) => { const o = get(k); if (c) { o.cs += r.s; o.cu += r.u; } else { o.ps += r.s; o.pu += r.u; } });
      });
      by.forEach((o) => {
        if (!P.ok || o.pu <= 0 || o.ps <= 0) { o.none = true; return; }
        o.p0 = o.ps / o.pu; o.p1 = o.cu > 0 ? o.cs / o.cu : 0;
        o.chg = o.cs - o.ps; o.v = (o.cu - o.pu) * o.p0; o.p = (o.p1 - o.p0) * o.cu; o.pct = o.chg / o.ps;
        // Float sums of identical months differ by fractions of a cent: treat anything under a millionth of a percent as zero.
        const eps = Math.max(1, o.ps * 1e-8);
        ['chg', 'v', 'p'].forEach((f) => { if (Math.abs(o[f]) < eps) o[f] = 0; });
        o.pct = o.chg / o.ps;
        o.err = o.v + o.p - o.chg; // zero up to float error: the two effects sum to the change
      });
      return by;
    }
    const sm = (v) => (v > 0 ? '+' : '') + AZ.money(v);
    const sp = (v) => AZ.pct(v, Math.abs(v) < 0.1 ? 1 : 0, true);
    const cls = (v) => (v > 0 ? 'up' : v < 0 ? 'dn' : '');
    const share = (o) => { const t = Math.abs(o.v) + Math.abs(o.p); return t ? Math.abs(o.p) / t : 0; };

    function headline(by) {
      const P = PER[mode];
      if (!P.ok) return 'No comparison period in the filter, so the change cannot be split';
      const F = famsHere.map((f) => ({ f, o: by.get('f:' + f) })).filter((x) => x.o && !x.o.none);
      if (!F.length) return 'No family has sales in both periods of the filter';
      const maxAbs = Math.max.apply(null, F.map((x) => Math.abs(x.o.pct)));
      const tot = by.get('all');
      const who = F.length > 1 ? 'every family' : (items1 || F[0].f);
      if (maxAbs === 0) return 'Sales in ' + who + ' match ' + P.prevLab + ' exactly, so there is nothing to split';
      if (maxAbs < 0.02) {
        const ps = F.map((x) => x.o.pct), lo = Math.min.apply(null, ps), hi2 = Math.max.apply(null, ps);
        return (F.length > 1 ? 'Every family moved ' + (AZ.pct(lo, 1, true) === AZ.pct(hi2, 1, true) ? AZ.pct(lo, 1, true) : AZ.pct(lo, 1, true) + ' to ' + AZ.pct(hi2, 1, true)) : who + ' moved ' + AZ.pct(lo, 1, true)) + ' against ' + P.prevLab + ', so there is little change to split';
      }
      if (F.length === 1) { const o = F[0].o; return 'Price accounts for ' + Math.round(share(o) * 100) + '% of the ' + sm(o.chg) + ' change in ' + who + ', units for the rest'; }
      const sh = F.map((x) => ({ f: x.f, o: x.o, s: share(x.o) })).sort((a, b) => b.s - a.s);
      const hi = sh[0].s, lo = sh[sh.length - 1].s;
      if (hi - lo < 0.08) return 'Price explains a similar share of the change in every family, ' + Math.round(lo * 100) + '% to ' + Math.round(hi * 100) + '%; units explain the rest';
      const lead = sh.filter((x) => x.s >= hi - 0.02);
      const names = lead.map((x) => x.f).join(' and ');
      if (tot && !tot.none) return 'Units explain ' + Math.round((1 - share(tot)) * 100) + '% of the change; price does the most in ' + names + ' (' + Math.round(hi * 100) + '%)';
      if (lead.length > 1) return 'Price does the most in ' + names + ', about ' + Math.round(hi * 100) + '% of each change';
      const o = sh[0].o;
      return 'Price does the most in ' + sh[0].f + ': ' + sm(o.p) + ' of its ' + sm(o.chg) + ' change (' + Math.round(hi * 100) + '%)';
    }

    // ---- markup ---------------------------------------------------------------------------------------
    const narrow = w < 420;
    const cols = w < 360 ? 2 : 3;
    const cardW = (w - 28 - (cols - 1) * 8) / cols;
    const compact = cardW < 190;
    el.classList.toggle('fg-cmp', compact);
    el.classList.toggle('fg-nar', narrow);
    const segBtn = (k, long, short) => '<button type="button" data-m="' + k + '"' + (PER[k].ok ? '' : ' disabled title="' + AZ.esc(PER[k].cap) + '"') + '>' + (narrow ? short : long) + '</button>';
    let html = '<div class="fg-head"><div class="fg-t">' + (narrow ? 'Units or price' : 'Sales change by family: units or price') + '</div><div class="fg-seg" role="group" aria-label="Comparison period">'
      + segBtn('ytd', 'Year to date', 'YTD') + segBtn('fy', 'Latest full year', 'Full year') + '</div></div>'
      + '<p class="fg-lead"></p><p class="fg-cap"></p><div class="fg-grid">';
    const bar = (lab) => '<div class="fg-br"><span class="fg-bl">' + lab + '</span><span class="fg-tr"><i class="fg-z"></i><i class="fg-b"></i></span><span class="fg-ba"></span></div>';
    const keys = single ? ['f:' + famsHere[0]] : cardKeys;
    keys.forEach((k) => {
      html += '<div class="fg-card" data-k="' + AZ.esc(k) + '" tabindex="0" role="button" aria-expanded="false">'
        + '<div class="fg-nm"><i style="background:' + colorOf(k) + '"></i><span>' + AZ.esc(nameOf(k)) + '</span><b class="fg-cp"></b></div>'
        + '<div class="fg-val"><span class="fg-s"></span><span class="fg-d"></span><span class="fg-sum"></span><span class="fg-p"></span></div>'
        + '<div class="fg-bars">' + bar('Units') + bar('Price') + '</div>'
        + '<div class="fg-none">No comparison period in the filter</div>'
        + '<div class="fg-det"></div></div>';
    });
    html += '</div>';
    el.innerHTML = html;
    const grid = el.querySelector('.fg-grid');
    const cards = Array.from(grid.querySelectorAll('.fg-card'));
    const tip = AZ.tip(el);
    const go = AZ.animator(), flip = AZ.animator(), gdet = AZ.animator();
    let by = aggregate(mode);

    // Bars share a zero placed by the data: domain [min(0, effects), max(0, effects)], so when every effect has the
    // same sign the bars use the whole track. geo(v, D) -> [left%, width%, zero%]. Tweened from the last drawn geometry.
    const dom = (vals) => { const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); return hi - lo < 1e-9 ? { lo: -1, hi: 1 } : { lo, hi }; };
    const geo = (v, D) => { const span = D.hi - D.lo, z = -D.lo / span * 100; return [z + Math.min(0, v) / span * 100, Math.abs(v) / span * 100, z]; };
    const setBar = (b, g) => { b.style.left = g[0].toFixed(2) + '%'; b.style.width = g[1].toFixed(2) + '%'; const zl = b.parentNode.querySelector('.fg-z'); if (zl) zl.style.left = 'calc(' + g[2].toFixed(2) + '% - ' + (g[2] > 99 ? 1 : 0) + 'px)'; b._g = g; };
    const mix = (a, b, k) => [AZ.lerp(a[0], b[0], k), AZ.lerp(a[1], b[1], k), AZ.lerp(a[2], b[2], k)];
    const effects = (bb, ks) => { const out = []; ks.forEach((k) => { const o = bb.get(k); if (o && !o.none) out.push(o.v, o.p); }); return out; };

    function fill(animate) {
      by = aggregate(mode);
      const P = PER[mode];
      el.querySelectorAll('.fg-seg button').forEach((b) => { const on = b.getAttribute('data-m') === mode; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      el.querySelector('.fg-lead').textContent = headline(by);
      el.querySelector('.fg-cap').textContent = P.ok ? P.cap + '. Family bars share one scale' + (single ? '' : '; All families has its own') : (PER.ytd.ok || PER.fy.ok ? P.cap : PER.ytd.cap) + '. Cards show all sales in the filter.';
      const FD = dom(effects(by, famsHere.map((f) => 'f:' + f)));
      const tasks = [];
      cards.forEach((c) => {
        const k = c.getAttribute('data-k'), o = by.get(k) || { cs: 0, none: true };
        const sEl = c.querySelector('.fg-s');
        const from = shown.has(k) ? shown.get(k) : 0;
        if (animate && from !== o.cs) tasks.push((kk) => { sEl.textContent = AZ.money(AZ.lerp(from, o.cs, kk)); });
        else sEl.textContent = AZ.money(o.cs);
        shown.set(k, o.cs);
        c.classList.toggle('none', !!o.none);
        const d = c.querySelector('.fg-d'), p = c.querySelector('.fg-p'), cp = c.querySelector('.fg-cp');
        d.textContent = o.none ? '' : sm(o.chg); d.className = 'fg-d ' + (o.none ? '' : cls(o.chg));
        p.textContent = o.none ? '' : sp(o.pct); p.className = 'fg-p ' + (o.none ? '' : cls(o.chg));
        cp.textContent = o.none ? 'no prior' : sp(o.pct);
        c.querySelector('.fg-sum').textContent = o.none ? '' : 'Units effect ' + sm(o.v) + ', price effect ' + sm(o.p); cp.className = 'fg-cp ' + (o.none ? '' : cls(o.chg));
        const D = k === 'all' ? dom(effects(by, ['all'])) : FD;
        const bs = c.querySelectorAll('.fg-bars .fg-br');
        [['v', 'Units effect'], ['p', 'Price effect']].forEach((pair, i) => {
          const b = bs[i].querySelector('.fg-b'), amt = bs[i].querySelector('.fg-ba'), val = o.none ? 0 : o[pair[0]];
          b.className = 'fg-b ' + pair[0];
          amt.textContent = o.none ? '' : sm(val);
          const g1 = geo(val, D), g0 = b._g || [g1[2], 0, g1[2]];
          if (animate) tasks.push((kk) => setBar(b, mix(g0, g1, kk))); else setBar(b, g1);
        });
        c.setAttribute('aria-label', nameOf(k) + ', sales ' + AZ.money(o.cs) + (o.none ? ', no comparison period' : ', change ' + sm(o.chg) + ', units effect ' + sm(o.v) + ', price effect ' + sm(o.p)));
      });
      if (tasks.length) go(firstPaint ? 520 : 420, (kk) => tasks.forEach((t) => t(kk)), null, firstPaint ? AZ.EASE.out : AZ.EASE.inOut);
      else go.stop();
      if (openKey) detail(animate);
    }

    // ---- expanded card: that family's item types (All families: the families) --------------------------
    function detail(animate) {
      const c = cards.find((x) => x.getAttribute('data-k') === openKey);
      if (!c) return;
      const box = c.querySelector('.fg-det'), P = PER[mode];
      const subKeys = openKey === 'all' ? famsHere.map((f) => 'f:' + f) : Array.from(new Set(R.filter((r) => 'f:' + r.fam === openKey).map((r) => r.item)));
      const list = subKeys.map((k) => ({ k, o: by.get(k) || { cs: 0, none: true } })).sort((a, b) => b.o.cs - a.o.cs);
      const D = dom(effects(by, list.map((x) => x.k)));
      let h = '<div class="fg-rh"><span>' + (openKey === 'all' ? 'Family' : 'Item type') + '</span><span>Change</span><span>' + (compact ? 'Units' : 'Units effect') + '</span><span>' + (compact ? 'Price' : 'Price effect') + '</span></div>';
      list.forEach((x) => {
        const o = x.o, cell = (v) => '<span class="fg-rc"><span class="fg-tr"><i class="fg-z"></i><i class="fg-b"></i></span><em>' + (o.none ? '' : sm(v)) + '</em></span>';
        h += '<div class="fg-row" data-k="' + AZ.esc(x.k) + '"><span class="fg-rn"><i style="background:' + colorOf(x.k) + '"></i>' + AZ.esc(nameOf(x.k)) + '</span>'
          + '<span class="fg-rd ' + (o.none ? '' : cls(o.chg)) + '">' + (o.none ? 'no prior' : sp(o.pct)) + '</span>' + cell(o.v) + cell(o.p) + '</div>';
      });
      if (!P.ok) h += '<div class="fg-rnote">No comparison period in the filter</div>';
      box.innerHTML = h;
      const bars = [];
      box.querySelectorAll('.fg-row').forEach((row, i) => {
        const o = list[i].o, bs = row.querySelectorAll('.fg-b');
        bs[0].className = 'fg-b v'; bs[1].className = 'fg-b p';
        bars.push([bs[0], geo(o.none ? 0 : o.v, D)], [bs[1], geo(o.none ? 0 : o.p, D)]);
      });
      if (animate) gdet(420, (kk) => bars.forEach((p) => setBar(p[0], mix([p[1][2], 0, p[1][2]], p[1], kk))), null, AZ.EASE.out);
      else bars.forEach((p) => setBar(p[0], p[1]));
    }

    // ---- layout: normal grid, or one card open with the rest compressed into a strip -------------------
    function layout(animate) {
      if (openKey && !cards.some((c) => c.getAttribute('data-k') === openKey)) openKey = null;
      if (single) openKey = keys[0];
      const before = new Map(cards.map((c) => [c, c.getBoundingClientRect()]));
      const isOpen = !!openKey;
      grid.classList.toggle('x', isOpen && !single);
      grid.classList.toggle('solo', single);
      if (single) { grid.style.gridTemplateColumns = '1fr'; grid.style.gridTemplateRows = '1fr'; }
      else if (isOpen) { grid.style.gridTemplateColumns = 'repeat(' + (cards.length - 1) + ', minmax(0, 1fr))'; grid.style.gridTemplateRows = (compact ? 30 : 34) + 'px minmax(0, 1fr)'; }
      else { grid.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))'; grid.style.gridTemplateRows = 'repeat(' + Math.ceil(cards.length / cols) + ', minmax(0, 1fr))'; }
      cards.forEach((c) => {
        const on = c.getAttribute('data-k') === openKey;
        c.classList.toggle('open', on);
        c.setAttribute('aria-expanded', on ? 'true' : 'false');
        c.style.gridColumn = on && !single ? '1 / -1' : '';
        c.style.gridRow = on && !single ? '2' : '';
        if (!on) c.querySelector('.fg-det').innerHTML = '';
      });
      if (!isOpen && !single) {
        const gh = grid.clientHeight, rowsN = Math.ceil(cards.length / cols), ch = (gh - (rowsN - 1) * 8) / rowsN;
        el.style.setProperty('--fg-bh', Math.max(8, Math.min(16, Math.round(ch / 12))) + 'px');
      }
      if (openKey) detail(animate);
      if (!animate || AZ.reduced()) { cards.forEach((c) => { c.style.transform = ''; }); return; }
      cards.forEach((c) => { const a = before.get(c), b = c.getBoundingClientRect(); c._dx = a.left - b.left; c._dy = a.top - b.top; });
      flip(440, (kk) => cards.forEach((c) => { c.style.transform = 'translate(' + (c._dx * (1 - kk)).toFixed(1) + 'px,' + (c._dy * (1 - kk)).toFixed(1) + 'px)'; }), () => cards.forEach((c) => { c.style.transform = ''; }), AZ.EASE.inOut);
    }

    // ---- tooltip -----------------------------------------------------------------------------------------
    function tipHtml(k) {
      const o = by.get(k), P = PER[mode];
      if (!o) return '';
      let t = '<b>' + AZ.esc(nameOf(k)) + '</b>';
      if (o.none) return t + AZ.row(P.ok ? P.curLab : 'Sales in filter', AZ.money(o.cs, 2)) + '<div class="fg-tn">No comparison period in the filter</div>';
      const pr = (v) => '$' + v.toFixed(2);
      t += AZ.row('Sales ' + P.curLab, AZ.money(o.cs, 2)) + AZ.row('Sales ' + P.prevLab, AZ.money(o.ps, 2))
        + AZ.row('Units ' + P.curLab, Math.round(o.cu).toLocaleString('en-US')) + AZ.row('Units ' + P.prevLab, Math.round(o.pu).toLocaleString('en-US'))
        + AZ.row('Price per unit ' + P.curLab, pr(o.p1)) + AZ.row('Price per unit ' + P.prevLab, pr(o.p0))
        + AZ.row('Units effect', sm(o.v)) + AZ.row('Price effect', sm(o.p)) + AZ.row('Change', sm(o.chg) + ' (' + sp(o.pct) + ')');
      if (k === 'all') t += '<div class="fg-tn">The price effect here includes the shift in mix between families</div>';
      return t;
    }
    let hov = null, hl = null;
    const setHov = (n) => { if (hov === n) return; if (hov) hov.classList.remove('hov'); hov = n; if (hov) hov.classList.add('hov'); };
    const setHl = (n) => { if (hl === n) return; if (hl) hl.classList.remove('hl'); hl = n; if (hl) hl.classList.add('hl'); };
    grid.addEventListener('mousemove', (ev) => {
      const n = ev.target.closest('.fg-row') || ev.target.closest('.fg-card');
      setHov(n);
      // the bar row under the pointer (units or price) is emphasised, so feedback follows the pointer inside a card
      let br = null;
      if (n && n.classList.contains('fg-card') && !n.classList.contains('open')) {
        const rs = Array.from(n.querySelectorAll('.fg-br')), y = ev.clientY;
        br = rs.find((r) => { const b = r.getBoundingClientRect(); return b.height && y >= b.top - 3 && y <= b.bottom + 3; }) || null;
      }
      setHl(br);
      if (!n || !by) { tip.hide(); return; }
      const r = el.getBoundingClientRect();
      tip.show(tipHtml(n.getAttribute('data-k')), ev.clientX - r.left, ev.clientY - r.top);
    });
    grid.addEventListener('mouseleave', () => { setHov(null); setHl(null); tip.hide(); });
    const toggle = (k) => { if (single) return; openKey = openKey === k ? null : k; tip.hide(); layout(true); };
    grid.addEventListener('click', (ev) => { const c = ev.target.closest('.fg-card'); if (c) toggle(c.getAttribute('data-k')); });
    grid.addEventListener('keydown', (ev) => {
      const c = ev.target.closest('.fg-card');
      if (c && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); toggle(c.getAttribute('data-k')); }
    });
    const onKey = (ev) => { if (ev.key === 'Escape' && openKey && !single) { openKey = null; layout(true); } };
    window.addEventListener('keydown', onKey);
    el.querySelectorAll('.fg-seg button').forEach((b) => b.addEventListener('click', () => {
      const m = b.getAttribute('data-m');
      if (m === mode || !PER[m].ok) return;
      mode = m; fill(true);
    }));

    layout(false);
    await AZ.settle();
    fill(firstPaint);
    firstPaint = false;
    return () => { window.removeEventListener('keydown', onKey); go.stop(); flip.stop(); gdet.stop(); };
  }
});
