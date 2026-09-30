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

// Search: [sales] [item type] [product]
// Sunburst Family > Item type > Product (top 6 products per item type, the rest as "Other").
// Plotly's own sunburst, because its drill is an animated zoom: click a wedge to fly in, click the centre or
// a crumb to fly back out. Family is an editorial grouping (AZ.familyOf), not a model column.
const PLOTLY = ['https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js', 'https://cdn.plot.ly/plotly-2.35.2.min.js'];
const TOPN = 6;
let level = ''; // id of the node the chart is zoomed into ('' = the whole thing)

function mixWhite(hex, k) {
  const n = parseInt(hex.slice(1), 16), r = n >> 16 & 255, g = n >> 8 & 255, b = n & 255;
  const m = (c) => Math.round(c + (255 - c) * k);
  return 'rgb(' + m(r) + ',' + m(g) + ',' + m(b) + ')';
}

AZ.boot({
  need: 'sales by item type and product, e.g. [sales] [item type] [product]',
  render: async ({ el, rows, schema }) => {
    const iK = AZ.col(schema, /item/i), pK = AZ.col(schema, /product/i), sK = AZ.col(schema, /sales/i);
    const R = rows.map((r) => ({ item: String(r[iK]), prod: String(r[pK]), v: AZ.num(r[sK]) })).filter((r) => r.v > 0);
    const total = R.reduce((a, r) => a + r.v, 0);
    if (R.length < 2) { AZ.paint(el, '<div class="az-empty"><b>Not enough products to draw</b><span>The current filter leaves ' + R.length + ' product. Widen the filters, or the search needs: [sales] [item type] [product].</span></div>'); return; }
    await AZ.loadScript(PLOTLY, () => !!window.Plotly, 12000);

    // Flat hierarchy for Plotly: parents must equal the sum of their children (branchvalues: total).
    const N = new Map(); // id -> { id, name, parent, value, fam, lvl, other }
    const add = (id, name, parent, fam, lvl, value, other) => { N.set(id, { id, name, parent, fam, lvl, value: value || 0, other: !!other }); return N.get(id); };
    add('root', 'All sales', '', null, 0, 0);
    const byItem = new Map();
    R.forEach((r) => { if (!byItem.has(r.item)) byItem.set(r.item, []); byItem.get(r.item).push(r); });
    byItem.forEach((ps, item) => {
      const fam = AZ.familyOf(item), fid = 'f:' + fam, iid = fid + '>' + item;
      if (!N.has(fid)) add(fid, fam, 'root', fam, 1);
      add(iid, item, fid, fam, 2);
      ps.sort((a, b) => b.v - a.v);
      ps.slice(0, TOPN).forEach((p) => add(iid + '>' + p.prod, p.prod, iid, fam, 3, p.v));
      const rest = ps.slice(TOPN);
      if (rest.length) add(iid + '>other', 'Other (' + rest.length + ')', iid, fam, 3, rest.reduce((a, p) => a + p.v, 0), true);
    });
    // Roll values up (children first).
    [...N.values()].filter((n) => n.lvl === 3).forEach((n) => { N.get(n.parent).value += n.value; });
    [...N.values()].filter((n) => n.lvl === 2).forEach((n) => { N.get(n.parent).value += n.value; });
    N.get('root').value = [...N.values()].filter((n) => n.lvl === 1).reduce((a, n) => a + n.value, 0);
    const list = [...N.values()];
    if (level && !N.has(level)) level = '';

    const fams = list.filter((n) => n.lvl === 1).sort((a, b) => b.value - a.value);
    const topFam = fams[0];
    const topIt = list.filter((n) => n.parent === topFam.id).sort((a, b) => b.value - a.value)[0];
    const lead = topFam.name + ' is ' + AZ.pct(topFam.value / total, 1) + ' of sales' + (topIt && fams.length && list.filter((n) => n.parent === topFam.id).length > 1 ? ', ' + topIt.name + ' ' + AZ.pct(topIt.value / topFam.value, 0) + ' of it' : '');

    el.innerHTML = '<div class="sb-head"><p class="sb-lead"></p><div class="sb-crumbs"></div></div><div class="sb-plot" id="sb-plot"></div><div class="sb-read"><b class="sb-rn"></b><span class="sb-rv"></span><span class="sb-rs"></span></div>';
    el.querySelector('.sb-lead').textContent = lead;
    const plot = el.querySelector('#sb-plot'), crumbsEl = el.querySelector('.sb-crumbs');
    const rn = el.querySelector('.sb-rn'), rv = el.querySelector('.sb-rv'), rs = el.querySelector('.sb-rs');

    const pathOf = (id) => { const out = []; let n = N.get(id || 'root'); while (n) { out.unshift(n); n = n.parent ? N.get(n.parent) : null; } return out; };
    const drawCrumbs = () => {
      const p = pathOf(level);
      crumbsEl.innerHTML = p.length > 1 ? AZ.crumbs(p.map((n) => n.name)) : '<span class="sb-hint">Click a wedge to zoom in, the centre to zoom out</span>';
      AZ.wireCrumbs(crumbsEl, (i) => { const id = p[i].id === 'root' ? '' : p[i].id; level = id; drawCrumbs(); readout(N.get(id || 'root')); Plotly.restyle(gd, { level: [id] }); });
    };
    const readout = (n) => {
      rn.textContent = n.name; rv.textContent = AZ.money(n.value, 1);
      const par = n.parent ? N.get(n.parent) : null;
      rs.textContent = n.id === 'root' ? '100% of sales' : AZ.pct(n.value / total, 1) + ' of all sales' + (par && par.id !== 'root' ? ', ' + AZ.pct(n.value / par.value, 0) + ' of ' + par.name : '');
    };

    const tint = (n) => (n.id === 'root' ? '#FFFFFF' : n.other ? AZ.T.slate[1] : mixWhite(AZ.T.family[n.fam] || AZ.T.muted, n.lvl === 1 ? 0 : n.lvl === 2 ? 0.28 : 0.55));
    const plotW = Math.max(200, plot.clientWidth), plotH = Math.max(180, plot.clientHeight);
    const trace = {
      type: 'sunburst',
      ids: list.map((n) => n.id), labels: list.map((n) => n.name), parents: list.map((n) => n.parent), values: list.map((n) => n.value),
      branchvalues: 'total', maxdepth: 3, sort: false, rotation: 90, level: level || '',
      marker: { colors: list.map(tint), line: { color: '#FFFFFF', width: 1.5 } },
      textfont: { family: AZ.T.font, size: 11, color: list.map((n) => (n.lvl === 1 ? '#FFFFFF' : AZ.T.ink)) },
      insidetextorientation: 'radial',
      texttemplate: list.map((n) => (n.id === 'root' ? '%{label}<br><b>' + AZ.money(n.value, 1) + '</b>' : '%{label}')),
      hovertemplate: '<b>%{label}</b><br>Sales %{value:$,.3s}<br>%{percentParent:.1%} of parent, %{percentRoot:.1%} of all<extra></extra>',
      hoverlabel: { bgcolor: AZ.T.ink, bordercolor: AZ.T.ink, font: { family: AZ.T.font, size: 12, color: '#FFFFFF' }, align: 'left' }
    };
    const layout = {
      width: plotW, height: plotH, margin: { l: 4, r: 4, t: 4, b: 4 }, paper_bgcolor: '#FFFFFF', plot_bgcolor: '#FFFFFF',
      font: { family: AZ.T.font, color: AZ.T.ink }, showlegend: false,
      transition: { duration: 520, easing: 'cubic-in-out' }
    };
    const gd = await Plotly.newPlot(plot, [trace], layout, { displayModeBar: false, responsive: false });
    drawCrumbs(); readout(N.get(level || 'root'));

    // Entrance: fan the rings in from a quarter turn, once (skipped for reduced motion and on redraws).
    if (!AZ.reduced() && !window.__sbSeen) { window.__sbSeen = 1; try { await Plotly.restyle(gd, { rotation: [0] }); Plotly.animate(gd, { data: [{ rotation: 90 }], traces: [0] }, { transition: { duration: 800, easing: 'cubic-out' }, frame: { duration: 800, redraw: true } }); } catch (e) {} }

    gd.on('plotly_sunburstclick', (ev) => {
      const pt = ev && ev.points && ev.points[0]; if (!pt) return;
      // Plotly zooms into the clicked wedge; clicking the current centre zooms back out to its parent.
      level = (pt.id === level) ? (pt.parent === 'root' ? '' : (pt.parent || '')) : pt.id;
      if (level === 'root') level = '';
      drawCrumbs(); readout(N.get(level || 'root'));
    });
    gd.on('plotly_hover', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && N.has(pt.id)) readout(N.get(pt.id)); });
    gd.on('plotly_unhover', () => readout(N.get(level || 'root')));
    return () => { try { Plotly.purge(plot); } catch (e) {} };
  }
});
