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

// Search: [product] [item type] [sales] [quantity purchased]
// Sortable, searchable product table with family chips and a share bar.
// Interactions: click a header to sort (rows glide to their new place), type to search product names, family chips filter,
// Show more pages the list. Click a row to open a detail row: sales, units and price against its item type's average,
// and its rank inside the item type, with bars that grow in. One row open at a time; click again or Escape closes.
let sortKey = 'sales', sortDir = -1, query = '', fams = new Set(), limit = 25, openKey = null;

AZ.boot({
  need: 'product, item type, sales and quantity purchased, e.g. [product] [item type] [sales] [quantity purchased]',
  render: async ({ el, rows, schema, w }) => {
    const pK = AZ.col(schema, /product/i), tK = AZ.col(schema, /item type|type/i), sK = AZ.col(schema, /sales/i), uK = AZ.col(schema, /quantity|units/i);
    const agg = new Map();
    rows.forEach((r) => {
      const k = String(r[pK]) + '||' + String(r[tK]);
      const o = agg.get(k) || { product: String(r[pK]), type: String(r[tK]), sales: 0, units: 0 };
      o.sales += AZ.num(r[sK]); o.units += AZ.num(r[uK]); agg.set(k, o);
    });
    const all = Array.from(agg.values());
    if (!all.length) throw new Error('No products in the result. Search: [product] [item type] [sales] [quantity purchased]');
    const total = all.reduce((a, r) => a + r.sales, 0) || 1;
    all.sort((a, b) => b.sales - a.sales);
    all.forEach((r, i) => { r.key = r.product + '||' + r.type; r.rank = i + 1; r.share = r.sales / total; r.fam = AZ.familyOf(r.type); r.color = AZ.familyColor(r.type); r.avg = r.units ? r.sales / r.units : null; });
    // Item-type peers, computed from the same rows.
    const TY = {};
    all.forEach((r) => { const t = TY[r.type] || (TY[r.type] = { n: 0, s: 0, u: 0, list: [] }); t.n++; t.s += r.sales; t.u += r.units; t.list.push(r); });
    Object.keys(TY).forEach((k) => {
      const t = TY[k]; t.avgS = t.s / t.n; t.avgU = t.u / t.n; t.avgP = t.u ? t.s / t.u : null;
      const rk = (f, key) => t.list.slice().sort((a, b) => (f(b) == null ? -1e18 : f(b)) - (f(a) == null ? -1e18 : f(a))).forEach((r, i) => { r[key] = i + 1; });
      rk((r) => r.sales, 'rkS'); rk((r) => r.units, 'rkU'); rk((r) => r.avg, 'rkP');
    });
    const maxShare = all[0].share || 1;
    const top25 = all.slice(0, 25).reduce((a, r) => a + r.share, 0);
    const famNames = Object.keys(AZ.T.family);
    fams = new Set(Array.from(fams).filter((f) => famNames.indexOf(f) >= 0));
    const narrow = w < 560;

    const COLS = [
      { k: 'rank', t: '#', w: 38, num: 1, dir: 1 }, { k: 'product', t: 'Product', w: 0, dir: 1 }, { k: 'type', t: 'Item type', w: narrow ? 100 : 130, dir: 1 },
      { k: 'sales', t: 'Sales', w: 64, num: 1, dir: -1 }, { k: 'share', t: 'Share', w: 52, num: 1, dir: -1 },
      { k: 'units', t: 'Units', w: 62, num: 1, dir: -1, hide: narrow }, { k: 'avg', t: 'Avg price', w: 74, num: 1, dir: -1, hide: narrow },
      { k: 'bar', t: '', w: 84, dir: -1, nosort: 1, hide: narrow }
    ].filter((c) => !c.hide);

    el.innerHTML =
      '<div class="pt-head"><b>' + AZ.esc(all[0].product) + '</b> is the top product at ' + AZ.money(all[0].sales, 1) + ', ' + AZ.pct(all[0].share, 1) + ' of sales.' + (all.length > 25 ? ' The top 25 of ' + all.length + ' products hold ' + AZ.pct(top25, 0) + '.' : (all.length === 1 ? ' It is the only product' : ' These are all ' + all.length + ' products') + ' in the current filter.') + '</div>'
      + '<div class="pt-ctl"><input class="pt-search" type="search" placeholder="Search products" aria-label="Search products by name" value="' + AZ.esc(query) + '">'
      + '<div class="pt-chips" role="group" aria-label="Filter by family">'
      + famNames.map((f) => '<button type="button" class="pt-chip" data-f="' + AZ.esc(f) + '" aria-label="' + AZ.esc(f) + '" title="' + AZ.esc(f) + '" aria-pressed="' + (fams.has(f) ? 'true' : 'false') + '"><i style="background:' + AZ.T.family[f] + '"></i>' + (narrow ? '' : AZ.esc(f)) + '</button>').join('') + '</div></div>'
      + '<div class="pt-wrap" tabindex="0" aria-label="Product table, scrollable"><table class="pt"><colgroup>' + COLS.map((c) => '<col' + (c.w ? ' style="width:' + c.w + 'px"' : '') + '>').join('') + '</colgroup><thead><tr>'
      + COLS.map((c) => '<th class="' + (c.num ? 'num' : '') + '" data-k="' + c.k + '">' + (c.nosort ? '' : '<button type="button" data-k="' + c.k + '">' + AZ.esc(c.t) + '<span class="ar"></span></button>') + '</th>').join('')
      + '</tr></thead><tbody></tbody></table></div>'
      + '<div class="pt-foot"><span class="pt-cnt"></span><button type="button" class="pt-more"></button></div>';
    const body = el.querySelector('tbody'), cnt = el.querySelector('.pt-cnt'), more = el.querySelector('.pt-more'), wrap = el.querySelector('.pt-wrap');

    const cmp = (a, b) => {
      const A = a[sortKey], B = b[sortKey];
      if (A == null && B == null) return 0; if (A == null) return 1; if (B == null) return -1;
      const d = typeof A === 'string' ? A.localeCompare(B) : A - B;
      return (d || a.rank - b.rank) * sortDir;
    };
    let shownRows = [], cancels = [];
    const stop = () => { cancels.forEach((c) => c()); cancels = []; };
    const metrics = (r) => {
      const t = TY[r.type];
      return [
        { name: 'Sales', v: r.sales, a: t.avgS, f: (v) => AZ.money(v, v >= 1e6 ? 2 : 0), rk: r.rkS },
        { name: 'Units', v: r.units, a: t.avgU, f: (v) => Math.round(v).toLocaleString('en-US'), rk: r.rkU },
        { name: 'Price per unit', v: r.avg, a: t.avgP, f: (v) => '$' + v.toFixed(2), rk: r.rkP }
      ];
    };
    const detailHTML = (r) => {
      const t = TY[r.type], ms = metrics(r), solo = t.n < 2;
      let h = '<div class="pt-d"><div class="pt-dh"><i style="background:' + r.color + '"></i><b>' + AZ.esc(r.product) + '</b> in ' + AZ.esc(r.type) + ': '
        + (solo ? 'the only product of this item type in the current result.' : '#' + r.rkS + ' of ' + t.n + ' by sales, #' + r.rkU + ' by units' + (r.rkP ? ', #' + r.rkP + ' by price' : '') + '.') + '</div><div class="pt-dm">';
      ms.forEach((m) => {
        if (m.v == null) return;
        const mx = Math.max(m.v, m.a || 0) || 1;
        h += '<div class="pt-mr"><span class="pt-mn">' + m.name + '</span><div class="pt-bars">'
          + '<div class="pt-bt"><span class="pt-bar me" data-w="' + (m.v / mx * 100).toFixed(2) + '" style="background:' + r.color + '"></span><em>' + AZ.esc(m.f(m.v)) + '</em></div>'
          + '<div class="pt-bt"><span class="pt-bar av" data-w="' + ((m.a || 0) / mx * 100).toFixed(2) + '"></span><em>' + AZ.esc(m.a == null ? '-' : m.f(m.a)) + ' type avg</em></div></div>'
          + '<span class="pt-md">' + (solo || !m.a ? '' : AZ.pct(m.v / m.a - 1, 0, true)) + '</span></div>';
      });
      return h + '</div></div>';
    };
    const openDetail = (tr, r, animate) => {
      const d = document.createElement('tr'); d.className = 'pt-detail';
      d.innerHTML = '<td colspan="' + COLS.length + '"><div class="pt-dw">' + detailHTML(r) + '</div></td>';
      tr.parentNode.insertBefore(d, tr.nextSibling);
      const dw = d.querySelector('.pt-dw'), bars = Array.from(d.querySelectorAll('.pt-bar'));
      const H = dw.scrollHeight, fin = (k) => bars.forEach((b) => { b.style.width = (parseFloat(b.getAttribute('data-w')) * k).toFixed(2) + '%'; });
      if (!animate) { fin(1); return; }
      fin(0); dw.style.height = '0px';
      const sc0 = wrap.scrollTop, need = tr.offsetTop + tr.offsetHeight + H - (sc0 + wrap.clientHeight), sc1 = need > 0 ? Math.min(sc0 + need, Math.max(0, tr.offsetTop - 30)) : sc0;
      cancels.push(AZ.tween(420, (k) => { dw.style.height = (H * k).toFixed(1) + 'px'; if (sc1 !== sc0) wrap.scrollTop = AZ.lerp(sc0, sc1, k); }, () => { dw.style.height = 'auto'; }, AZ.EASE.inOut));
      cancels.push(AZ.tween(620, (k) => fin(k), null, AZ.EASE.out));
    };
    const closeDetail = (d, animate) => {
      if (!d) return;
      const dw = d.querySelector('.pt-dw'), H = dw.offsetHeight;
      if (!animate) { d.remove(); return; }
      dw.style.height = H + 'px';
      cancels.push(AZ.tween(320, (k) => { dw.style.height = (H * (1 - k)).toFixed(1) + 'px'; }, () => d.remove(), AZ.EASE.inOut));
    };
    const rowFor = (key) => Array.from(body.querySelectorAll('tr[data-key]')).find((t) => t.getAttribute('data-key') === key);
    const toggle = (r) => {
      const old = body.querySelector('.pt-detail');
      if (openKey === r.key) { openKey = null; el.querySelectorAll('tr[aria-expanded="true"]').forEach((t) => t.setAttribute('aria-expanded', 'false')); closeDetail(old, true); return; }
      openKey = r.key;
      el.querySelectorAll('tr[aria-expanded="true"]').forEach((t) => t.setAttribute('aria-expanded', 'false'));
      closeDetail(old, true);
      const tr = rowFor(r.key); if (!tr) return;
      tr.setAttribute('aria-expanded', 'true'); openDetail(tr, r, true);
    };
    const tipRoot = document.createElement('div'); tipRoot.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none'; el.style.position = 'relative'; el.appendChild(tipRoot);
    const tip = AZ.tip(tipRoot);
    body.addEventListener('mousemove', (e) => {
      const tr = e.target.closest && e.target.closest('tr[data-i]'), r = tr && shownRows[Number(tr.getAttribute('data-i'))];
      if (!r) return tip.hide();
      const b = el.getBoundingClientRect();
      tip.show('<b>' + AZ.esc(r.product) + '</b>' + AZ.row('Rank by sales', '#' + r.rank + ' of ' + all.length) + AZ.row(r.type + ' (' + r.fam + ')', '', r.color) + AZ.row('Sales', AZ.money(r.sales, 2)) + AZ.row('Share of total', AZ.pct(r.share, 2)) + AZ.row('Units', Math.round(r.units).toLocaleString('en-US')) + AZ.row('Average price', r.avg == null ? '-' : '$' + r.avg.toFixed(2)), e.clientX - b.left, e.clientY - b.top);
    });
    body.addEventListener('mouseleave', () => tip.hide());
    body.addEventListener('click', (e) => { const tr = e.target.closest && e.target.closest('tr[data-i]'); if (tr && shownRows[Number(tr.getAttribute('data-i'))]) toggle(shownRows[Number(tr.getAttribute('data-i'))]); });
    body.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('tr[data-i]')) { e.preventDefault(); toggle(shownRows[Number(e.target.getAttribute('data-i'))]); } });
    const onKey = (e) => { if (e.key === 'Escape' && openKey) { e.preventDefault(); const r = all.find((x) => x.key === openKey); if (r) toggle(r); } };
    document.addEventListener('keydown', onKey);
    function paint(opt) {
      stop();
      const anim = !!(opt && opt.animate), before = {};
      if (anim) body.querySelectorAll('tr[data-key]').forEach((t) => { before[t.getAttribute('data-key')] = t.getBoundingClientRect().top; });
      if (opt && opt.reset) wrap.scrollTop = 0;
      const q = query.trim().toLowerCase();
      const list = all.filter((r) => (!fams.size || fams.has(r.fam)) && (!q || r.product.toLowerCase().indexOf(q) >= 0)).sort(cmp);
      const vis = list.slice(0, limit);
      body.innerHTML = vis.map((r, i) => '<tr data-i="' + i + '" data-key="' + AZ.esc(r.key) + '" tabindex="0" aria-expanded="false">' + COLS.map((c) => {
        if (c.k === 'rank') return '<td class="num rk">' + r.rank + '</td>';
        if (c.k === 'product') return '<td class="pn" title="' + AZ.esc(r.product) + '">' + AZ.esc(r.product) + '</td>';
        if (c.k === 'type') return '<td class="ty"><i style="background:' + r.color + '" title="' + AZ.esc(r.fam) + '"></i>' + AZ.esc(r.type) + '</td>';
        if (c.k === 'sales') return '<td class="num">' + AZ.money(r.sales, r.sales >= 1e6 ? 2 : 0) + '</td>';
        if (c.k === 'share') return '<td class="num">' + AZ.pct(r.share, 1) + '</td>';
        if (c.k === 'units') return '<td class="num">' + Math.round(r.units).toLocaleString('en-US') + '</td>';
        if (c.k === 'avg') return '<td class="num">' + (r.avg == null ? '-' : '$' + r.avg.toFixed(2)) + '</td>';
        return '<td title="' + AZ.pct(r.share, 2) + ' of sales"><span class="sb" style="width:' + Math.max(1, Math.round(r.share / maxShare * 100)) + '%"></span></td>';
      }).join('') + '</tr>').join('') || '<tr><td colspan="' + COLS.length + '" class="pt-none">No product matches. Clear the search or a family chip.</td></tr>';
      shownRows = vis;
      if (openKey && !vis.some((r) => r.key === openKey)) openKey = null;
      if (openKey) { const tr = rowFor(openKey); if (tr) { tr.setAttribute('aria-expanded', 'true'); openDetail(tr, all.find((x) => x.key === openKey), false); } }
      if (anim) {
        const mv = [];
        body.querySelectorAll('tr[data-key]').forEach((t) => { const k = t.getAttribute('data-key'); if (before[k] == null) mv.push({ t, dy: 0, fresh: true }); else { const dy = before[k] - t.getBoundingClientRect().top; if (Math.abs(dy) > 1) mv.push({ t, dy, fresh: false }); } });
        mv.forEach((m) => { m.t.style.position = 'relative'; if (m.fresh) m.t.style.opacity = 0; else m.t.style.transform = 'translateY(' + m.dy + 'px)'; });
        if (mv.length) cancels.push(AZ.tween(380, (k) => mv.forEach((m) => { if (m.fresh) m.t.style.opacity = k; else m.t.style.transform = 'translateY(' + (m.dy * (1 - k)).toFixed(1) + 'px)'; }), () => mv.forEach((m) => { m.t.style.transform = ''; m.t.style.opacity = ''; m.t.style.position = ''; }), AZ.EASE.inOut));
      }
      el.querySelectorAll('th[data-k]').forEach((th) => {
        const on = th.getAttribute('data-k') === sortKey;
        if (on) th.setAttribute('aria-sort', sortDir < 0 ? 'descending' : 'ascending'); else th.removeAttribute('aria-sort');
        const ar = th.querySelector('.ar'); if (ar) ar.textContent = on ? (sortDir < 0 ? String.fromCharCode(8595) : String.fromCharCode(8593)) : '';
      });
      const filt = list.length !== all.length;
      cnt.textContent = 'Showing ' + vis.length + ' of ' + list.length + (filt ? ' matching' : '') + ' products, sorted by ' + (COLS.find((c) => c.k === sortKey) || {}).t.toLowerCase();
      more.style.display = list.length > vis.length ? '' : 'none';
      more.textContent = 'Show ' + Math.min(25, list.length - vis.length) + ' more';
    }
    el.querySelectorAll('th button').forEach((b) => b.addEventListener('click', () => {
      const k = b.getAttribute('data-k'), c = COLS.find((x) => x.k === k);
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = c.dir; }
      limit = 25; paint({ animate: true, reset: true });
    }));
    el.querySelector('.pt-search').addEventListener('input', (e) => { query = e.target.value; limit = 25; paint({ animate: true, reset: true }); });
    el.querySelectorAll('.pt-chip').forEach((b) => b.addEventListener('click', () => {
      const f = b.getAttribute('data-f'); if (fams.has(f)) fams.delete(f); else fams.add(f);
      b.setAttribute('aria-pressed', fams.has(f) ? 'true' : 'false'); limit = 25; paint({ animate: true, reset: true });
    }));
    more.addEventListener('click', () => { limit += 25; paint({ animate: true }); });
    paint();
    return () => { stop(); document.removeEventListener('keydown', onKey); };
  }
});
