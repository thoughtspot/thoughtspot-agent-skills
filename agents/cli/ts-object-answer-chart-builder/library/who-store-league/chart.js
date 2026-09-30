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


// Search: [sales] [store] [region] [date].monthly [date].'this year' [date].'last year'
// Store league table: position, movement against last year's position over the same year-to-date window, region,
// YTD sales, YTD change and a form strip (the last 5 complete months, each against the same month last year).
// Interactions: region chips filter (rows glide), click a header to sort (rows glide), hover a row or a form square
// for a tooltip, click a row to open its monthly bars this year against last year. Escape closes.
let sortKey = 'pos', sortDir = 1, regs = new Set(), openKey = null, soloShut = false;

AZ.boot({
  need: 'sales, store, region and month over this year and last year, e.g. [sales] [store] [region] [date].monthly [date].\'this year\' [date].\'last year\'',
  render: async ({ el, rows, schema, w }) => {
    const sK = AZ.col(schema, /^store$|store/i), rK = AZ.col(schema, /region/i, { optional: true });
    const dK = AZ.col(schema, /month|date/i), vK = AZ.col(schema, /sales/i);
    const UP = String.fromCharCode(8593), DN = String.fromCharCode(8595), SP = String.fromCharCode(160);
    const mKey = (y, m) => y * 12 + m;
    const ST = new Map(), TOT = new Map();
    rows.forEach((r) => {
      const t = AZ.ms(r[dK]); if (!isFinite(t)) return;
      const d = new Date(t), k = mKey(d.getUTCFullYear(), d.getUTCMonth()), v = AZ.num(r[vK]), name = String(r[sK]);
      const s = ST.get(name) || { store: name, region: rK ? String(r[rK] == null ? '' : r[rK]) : '', m: new Map() };
      s.m.set(k, (s.m.get(k) || 0) + v); ST.set(name, s);
      TOT.set(k, (TOT.get(k) || 0) + v);
    });
    if (!ST.size) {
      el.innerHTML = '<div class="az-empty"><b>No stores in the result</b><span>The filters leave no rows. Search: [sales] [store] [region] [date].monthly</span></div>';
      return;
    }
    const keys = Array.from(TOT.keys()).sort((a, b) => a - b);
    const latest = keys[keys.length - 1];
    // Part month: the latest month is partial when its total is far below the median of the three before it.
    const prev3 = keys.filter((k) => k < latest).slice(-3).map((k) => TOT.get(k)).sort((a, b) => a - b);
    const partial = prev3.length >= 2 && TOT.get(latest) < 0.6 * prev3[Math.floor(prev3.length / 2)];
    const full = keys.filter((k) => !partial || k !== latest);
    const lastFull = full.length ? full[full.length - 1] : latest;
    const Y = Math.floor(lastFull / 12), M = lastFull % 12;
    const lab = (k) => AZ.MON[k % 12] + ' ' + Math.floor(k / 12);
    // The window starts at the first month of this year in the result (a date filter may cut it), and LY uses the same months.
    const F = Math.min(...keys.filter((k) => Math.floor(k / 12) === Y && k <= lastFull).map((k) => k % 12));
    const inWin = (mo) => mo >= F && mo <= M;
    const hasLY = keys.some((k) => Math.floor(k / 12) === Y - 1 && inWin(k % 12));
    const formKeys = full.filter((k) => k <= lastFull).slice(-5);

    const all = Array.from(ST.values());
    all.forEach((s) => {
      s.key = s.store; s.ty = 0; s.ly = 0;
      s.m.forEach((v, k) => { const y = Math.floor(k / 12), mo = k % 12; if (!inWin(mo)) return; if (y === Y) s.ty += v; else if (y === Y - 1) s.ly += v; });
      s.chg = hasLY && s.ly > 0 ? s.ty / s.ly - 1 : null;
      s.form = formKeys.map((k) => {
        const cur = s.m.get(k), pv = s.m.get(k - 12);
        if (cur == null || pv == null || !pv) return { k, st: 'n', cur, pv };
        const p = cur / pv - 1;
        return { k, st: p > 0.0005 ? 'w' : p < -0.0005 ? 'l' : 'e', cur, pv, p };
      });
      s.wins = s.form.filter((f) => f.st === 'w').length;
      s.losses = s.form.filter((f) => f.st === 'l').length;
      s.fsum = s.form.reduce((a, f) => a + (f.p || 0), 0);
      s.fscore = s.wins - s.losses + s.fsum / 100;
    });
    all.sort((a, b) => b.ty - a.ty || a.store.localeCompare(b.store)).forEach((s, i) => { s.pos = i + 1; });
    if (hasLY) all.slice().filter((s) => s.ly > 0).sort((a, b) => b.ly - a.ly || a.store.localeCompare(b.store)).forEach((s, i) => { s.lyPos = i + 1; s.move = s.lyPos - s.pos; });
    all.forEach((s) => { if (s.move == null) s.move = null; });
    const maxV = Math.max(1, ...all.map((s) => Math.max(s.ty, s.ly)));
    const anyForm = all.some((s) => s.form.some((f) => f.st !== 'n'));

    // Headline: leader, biggest climber, best form, all computed from the rows.
    const lead = all[0];
    const climber = all.filter((s) => s.move > 0).sort((a, b) => b.move - a.move || a.pos - b.pos)[0];
    const inForm = anyForm ? all.slice().sort((a, b) => b.fscore - a.fscore || a.pos - b.pos)[0] : null;
    const ytdLabel = AZ.MON[F] + (M > F ? ' to ' + AZ.MON[M] : '') + ' ' + Y;
    const solo = all.length === 1;
    let head = '<b>' + AZ.esc(lead.store) + '</b> ' + (solo ? 'sold ' + AZ.money(lead.ty, 2) + ' in ' + ytdLabel : 'leads ' + ytdLabel + ' with ' + AZ.money(lead.ty, 2)) + (lead.chg == null ? '' : ' (' + AZ.pct(lead.chg, 1, true) + ' on last year)') + '.';
    const formTxt = inForm && inForm.wins > 0 ? 'beat last year in ' + inForm.wins + ' of the last ' + formKeys.length + ' months' : '';
    const upTxt = climber ? 'climbed most, up ' + climber.move + ' place' + (climber.move === 1 ? '' : 's') : '';
    if (all.length > 1 && hasLY && climber && formTxt && climber === inForm) head += ' <b>' + AZ.esc(climber.store) + '</b> ' + upTxt + ', and ' + formTxt + '.';
    else {
      if (all.length > 1 && hasLY) head += climber ? ' <b>' + AZ.esc(climber.store) + '</b> ' + upTxt + '.' : ' No store moved up on last year.';
      if (formTxt) head += solo ? ' It ' + formTxt + '.' : ' <b>' + AZ.esc(inForm.store) + '</b> ' + formTxt + '.';
      else if (anyForm) head += ' No store beat last year in any of the last ' + formKeys.length + ' months.';
    }

    const regNames = Array.from(new Set(all.map((s) => s.region).filter((r) => r))).sort();
    regs = new Set(Array.from(regs).filter((r) => regNames.indexOf(r) >= 0));
    const showChips = regNames.length > 1;
    const narrow = w < 560, tiny = w < 400, micro = w < 330;
    const COLS = [
      { k: 'pos', t: tiny ? '#' : 'Pos', w: tiny ? 30 : 42, num: 1, dir: 1 },
      { k: 'move', t: 'Move', w: 44, num: 1, dir: -1, hide: micro },
      { k: 'store', t: 'Store', w: 0, dir: 1 },
      { k: 'region', t: 'Region', w: 78, dir: 1, hide: narrow || !rK },
      { k: 'ty', t: 'YTD sales', w: 74, num: 1, dir: -1, hide: tiny },
      { k: 'bar', t: '', w: 110, nosort: 1, hide: narrow },
      { k: 'chg', t: 'vs LY', w: 58, num: 1, dir: -1 },
      { k: 'form', t: 'Form', w: formKeys.length * 13 + 12, dir: -1 }
    ].filter((c) => !c.hide);

    const notes = [];
    notes.push(hasLY ? 'YTD: ' + ytdLabel + ' vs the same months of ' + (Y - 1) + '.' : 'No months of ' + (Y - 1) + ' in this result, so change, movement and form show - (widen the date filter to include last year).');
    if (anyForm) notes.push('Form: ' + (Math.floor(formKeys[0] / 12) === Math.floor(formKeys[formKeys.length - 1] / 12) ? AZ.MON[formKeys[0] % 12] : lab(formKeys[0])) + ' to ' + lab(formKeys[formKeys.length - 1]) + '.');
    if (partial) notes.push(lab(latest) + ' looks partial (' + AZ.money(TOT.get(latest), 1) + ' so far) and is left out of YTD and form.');

    el.classList.toggle('lg-micro', micro);
    el.innerHTML =
      '<div class="lg-head">' + head + '</div>'
      + (showChips ? '<div class="lg-chips" role="group" aria-label="Filter by region">' + regNames.map((r) => '<button type="button" class="lg-chip" data-r="' + AZ.esc(r) + '" aria-pressed="' + (regs.has(r) ? 'true' : 'false') + '">' + AZ.esc(r) + '</button>').join('') + '</div>' : '')
      + '<div class="lg-wrap" tabindex="0" aria-label="Store league table, scrollable"><table class="lg"><colgroup>' + COLS.map((c) => '<col' + (c.w ? ' style="width:' + c.w + 'px"' : '') + '>').join('') + '</colgroup><thead><tr>'
      + COLS.map((c) => '<th class="' + (c.num ? 'num' : '') + (c.k === 'form' ? ' fm' : '') + '" data-k="' + c.k + '">' + (c.nosort ? '' : '<button type="button" data-k="' + c.k + '">' + AZ.esc(c.t) + '<span class="ar"></span></button>') + '</th>').join('')
      + '</tr></thead><tbody></tbody></table></div>'
      + '<div class="lg-foot">' + (anyForm ? '<span class="lg-key"><i class="sq w"></i>above LY<i class="sq l"></i>below<i class="sq e"></i>level</span>' : '') + (hasLY && !narrow ? '<span class="lg-key"><i class="kb"></i>YTD<i class="kt"></i>same months LY</span>' : '') + '<span class="lg-note">' + AZ.esc(notes.join(' ')) + '</span></div>';
    const body = el.querySelector('tbody'), wrap = el.querySelector('.lg-wrap');

    const val = (s, k) => (k === 'form' ? (anyForm ? s.fscore : null) : s[k]);
    const cmp = (a, b) => {
      const A = val(a, sortKey), B = val(b, sortKey);
      if (A == null && B == null) return a.pos - b.pos; if (A == null) return 1; if (B == null) return -1;
      const d = typeof A === 'string' ? A.localeCompare(B) : A - B;
      return d ? d * sortDir : a.pos - b.pos;
    };
    const moveHTML = (s) => {
      if (s.move == null) return '<span class="mv na">-</span>';
      if (s.move === 0) return '<span class="mv eq">=</span>';
      return '<span class="mv ' + (s.move > 0 ? 'up' : 'dn') + '">' + (s.move > 0 ? UP + SP + '+' + s.move : DN + SP + '-' + (-s.move)) + '</span>';
    };
    const chgHTML = (s) => (s.chg == null ? '<span class="na">-</span>' : '<span class="' + (s.chg > 0 ? 'up' : s.chg < 0 ? 'dn' : '') + '">' + AZ.pct(s.chg, 1, true) + '</span>');
    const formHTML = (s) => '<span class="fs">' + s.form.map((f, j) => '<i class="sq ' + f.st + '" data-j="' + j + '"></i>').join('') + '</span>';

    let shown = [], cancels = [];
    const stop = () => { cancels.forEach((c) => c()); cancels = []; };
    const detailHTML = (s) => {
      const yrs = [Y - 1, Y], mx = Math.max(1, ...Array.from(s.m.values()));
      let h = '<div class="lg-d"><div class="lg-dh"><b>' + AZ.esc(s.store) + '</b> by month: <span class="k ty"></span>' + Y + ' <span class="k ly"></span>' + (Y - 1)
        + (s.chg == null ? '' : '. YTD ' + AZ.money(s.ty, 2) + ' against ' + AZ.money(s.ly, 2) + ' (' + AZ.pct(s.chg, 1, true) + ')') + (s.move == null ? '' : ', position ' + s.lyPos + ' last year, ' + s.pos + ' now') + '.</div><div class="lg-bars">';
      for (let mo = 0; mo < 12; mo++) {
        h += '<div class="lg-slot" data-mo="' + mo + '"><div class="lg-pair">';
        yrs.forEach((y) => {
          const k = mKey(y, mo), v = s.m.get(k);
          const cls = (y === Y ? 'ty' : 'ly') + (partial && k === latest ? ' part' : '');
          h += '<span class="lg-b ' + cls + '" data-h="' + (v == null ? 0 : (v / mx * 100).toFixed(2)) + '"></span>';
        });
        h += '</div><em>' + (tiny ? AZ.MON[mo].charAt(0) : AZ.MON[mo]) + '</em></div>';
      }
      return h + '</div></div>';
    };
    const openDetail = (tr, s, animate) => {
      const d = document.createElement('tr'); d.className = 'lg-detail'; d.setAttribute('data-for', s.key);
      d.innerHTML = '<td colspan="' + COLS.length + '"><div class="lg-dw">' + detailHTML(s) + '</div></td>';
      tr.parentNode.insertBefore(d, tr.nextSibling);
      const dw = d.querySelector('.lg-dw'), bars = Array.from(d.querySelectorAll('.lg-b'));
      const setH = (k) => bars.forEach((b, i) => { const kk = Math.max(0, Math.min(1, k * 1.6 - (i % 24) * 0.025)); b.style.height = (parseFloat(b.getAttribute('data-h')) * kk).toFixed(2) + '%'; });
      if (!animate) { setH(1); return; }
      setH(0); const H = dw.scrollHeight; dw.style.height = '0px';
      const sc0 = wrap.scrollTop, need = tr.offsetTop + tr.offsetHeight + H - (sc0 + wrap.clientHeight), sc1 = need > 0 ? Math.min(sc0 + need, Math.max(0, tr.offsetTop - 28)) : sc0;
      cancels.push(AZ.tween(380, (k) => { dw.style.height = (H * k).toFixed(1) + 'px'; if (sc1 !== sc0) wrap.scrollTop = AZ.lerp(sc0, sc1, k); }, () => { dw.style.height = 'auto'; }, AZ.EASE.inOut));
      cancels.push(AZ.tween(620, setH, () => setH(1), AZ.EASE.out));
    };
    const closeDetail = (d, animate) => {
      if (!d) return;
      const dw = d.querySelector('.lg-dw'), H = dw.offsetHeight;
      if (!animate) { d.remove(); return; }
      dw.style.height = H + 'px';
      cancels.push(AZ.tween(280, (k) => { dw.style.height = (H * (1 - k)).toFixed(1) + 'px'; }, () => d.remove(), AZ.EASE.inOut));
    };
    const rowFor = (key) => Array.from(body.querySelectorAll('tr[data-key]')).find((t) => t.getAttribute('data-key') === key);
    const toggle = (s) => {
      const old = body.querySelector('.lg-detail');
      el.querySelectorAll('tr[aria-expanded="true"]').forEach((t) => t.setAttribute('aria-expanded', 'false'));
      closeDetail(old, true);
      if (openKey === s.key) { openKey = null; if (solo) soloShut = true; return; }
      openKey = s.key;
      const tr = rowFor(s.key); if (!tr) return;
      tr.setAttribute('aria-expanded', 'true'); openDetail(tr, s, true);
    };

    const tipRoot = document.createElement('div'); tipRoot.className = 'az-tip-root'; tipRoot.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none';
    el.appendChild(tipRoot);
    const tip = AZ.tip(tipRoot);
    const byKey = new Map(all.map((s) => [s.key, s]));
    const ths = Array.from(el.querySelectorAll('thead th'));
    // Position-dependent hover: the row under the pointer, its column header and the form square.
    const clearHot = () => { el.querySelectorAll('.hot, tr.on').forEach((q) => q.classList.remove('hot', 'on')); };
    body.addEventListener('mousemove', (e) => {
      const b = el.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
      const slot = e.target.closest && e.target.closest('.lg-slot');
      if (slot) {
        clearHot(); slot.classList.add('hot');
        const s = byKey.get(slot.closest('tr').getAttribute('data-for')), mo = Number(slot.getAttribute('data-mo'));
        const cur = s.m.get(mKey(Y, mo)), pv = s.m.get(mKey(Y - 1, mo));
        return tip.show('<b>' + AZ.esc(s.store) + ', ' + AZ.MON[mo] + '</b>' + AZ.row(String(Y) + (partial && mKey(Y, mo) === latest ? ' (partial)' : ''), cur == null ? '-' : AZ.money(cur, 1)) + AZ.row(String(Y - 1), pv == null ? '-' : AZ.money(pv, 1)) + AZ.row('Change', cur != null && pv ? AZ.pct(cur / pv - 1, 1, true) : '-'), x, y);
      }
      const tr = e.target.closest && e.target.closest('tr[data-i]'), s = tr && shown[Number(tr.getAttribute('data-i'))];
      if (!s) { clearHot(); return tip.hide(); }
      clearHot();
      tr.classList.add('on');
      const td = e.target.closest('td'), ci = td ? Array.prototype.indexOf.call(tr.children, td) : -1;
      if (ci >= 0 && ths[ci]) ths[ci].classList.add('hot');
      const sq = e.target.closest('.sq');
      if (sq) {
        sq.classList.add('hot');
        const f = s.form[Number(sq.getAttribute('data-j'))];
        const verdict = f.st === 'w' ? 'Above last year' : f.st === 'l' ? 'Below last year' : f.st === 'e' ? 'Level with last year' : 'No month last year to compare';
        return tip.show('<b>' + AZ.esc(s.store) + ', ' + lab(f.k) + '</b>' + AZ.row(lab(f.k), f.cur == null ? '-' : AZ.money(f.cur, 1)) + AZ.row(lab(f.k - 12), f.pv == null ? '-' : AZ.money(f.pv, 1)) + AZ.row(verdict, f.p == null ? '-' : AZ.pct(f.p, 1, true)), x, y);
      }
      const ck = ci >= 0 && COLS[ci] ? COLS[ci].k : '';
      const HINT = {
        pos: 'Position by YTD sales among all ' + all.length + ' stores',
        move: s.move == null ? 'No last-year position to compare' : 'Places gained on the same months last year',
        store: 'Click the row to see its months',
        region: 'Region filters sit above the table',
        ty: 'Sales ' + ytdLabel,
        bar: 'Bar: YTD. Tick: same months last year',
        chg: 'YTD against the same months last year'
      };
      const hint = HINT[ck] ? '<div class="lg-th">' + AZ.esc(HINT[ck]) + '</div>' : '';
      const mv = s.move == null ? '-' : s.move === 0 ? 'Same as last year (' + s.pos + ')' : s.lyPos + ' to ' + s.pos + ' (' + (s.move > 0 ? 'up ' : 'down ') + Math.abs(s.move) + ')';
      tip.show('<b>' + AZ.esc(s.store) + '</b>' + (s.region ? AZ.row('Region', s.region) : '') + AZ.row('Position', s.pos + ' of ' + all.length) + AZ.row('YTD ' + Y, AZ.money(s.ty, 2)) + AZ.row('Same months ' + (Y - 1), s.ly ? AZ.money(s.ly, 2) : '-') + AZ.row('Change', s.chg == null ? '-' : AZ.pct(s.chg, 1, true)) + AZ.row('Position change', mv) + (anyForm ? AZ.row('Form', s.wins + ' above, ' + s.losses + ' below') : '') + hint, x, y);
    });
    body.addEventListener('mouseleave', () => { tip.hide(); clearHot(); });
    body.addEventListener('click', (e) => { const tr = e.target.closest && e.target.closest('tr[data-i]'); if (tr) toggle(shown[Number(tr.getAttribute('data-i'))]); });
    body.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('tr[data-i]')) { e.preventDefault(); toggle(shown[Number(e.target.getAttribute('data-i'))]); } });
    const onKey = (e) => { if (e.key === 'Escape' && openKey) { const s = byKey.get(openKey); if (s) { e.preventDefault(); toggle(s); } } };
    document.addEventListener('keydown', onKey);

    function paint(anim) {
      stop();
      const before = {};
      if (anim) body.querySelectorAll('tr[data-key]').forEach((t) => { before[t.getAttribute('data-key')] = t.getBoundingClientRect().top; });
      const list = all.filter((s) => !regs.size || regs.has(s.region)).sort(cmp);
      body.innerHTML = list.map((s, i) => '<tr data-i="' + i + '" data-key="' + AZ.esc(s.key) + '" tabindex="0" aria-expanded="false">' + COLS.map((c) => {
        if (c.k === 'pos') return '<td class="num ps">' + s.pos + '</td>';
        if (c.k === 'move') return '<td class="num">' + moveHTML(s) + '</td>';
        if (c.k === 'store') return '<td class="sn" title="' + AZ.esc(s.store) + '">' + AZ.esc(s.store) + '</td>';
        if (c.k === 'region') return '<td class="rg">' + AZ.esc(s.region) + '</td>';
        if (c.k === 'ty') return '<td class="num">' + AZ.money(s.ty, s.ty >= 1e6 ? 2 : 0) + '</td>';
        if (c.k === 'bar') return '<td class="br"><span class="bw"><span class="yb" style="width:' + (s.ty / maxV * 100).toFixed(1) + '%"></span>' + (s.ly ? '<span class="lt" style="left:' + (s.ly / maxV * 100).toFixed(1) + '%"></span>' : '') + '</span></td>';
        if (c.k === 'chg') return '<td class="num">' + chgHTML(s) + '</td>';
        return '<td class="fm">' + formHTML(s) + '</td>';
      }).join('') + '</tr>').join('') || '<tr><td colspan="' + COLS.length + '" class="lg-none">No store in the selected regions.</td></tr>';
      shown = list;
      if (openKey && !list.some((s) => s.key === openKey)) openKey = null;
      if (openKey) { const tr = rowFor(openKey); if (tr) { tr.setAttribute('aria-expanded', 'true'); openDetail(tr, byKey.get(openKey), false); } }
      if (anim) {
        const mv = [];
        body.querySelectorAll('tr[data-key]').forEach((t) => { const k = t.getAttribute('data-key'); if (before[k] == null) mv.push({ t, dy: 0, fresh: true }); else { const dy = before[k] - t.getBoundingClientRect().top; if (Math.abs(dy) > 1) mv.push({ t, dy, fresh: false }); } });
        mv.forEach((m) => { m.t.style.position = 'relative'; if (m.fresh) m.t.style.opacity = 0; else m.t.style.transform = 'translateY(' + m.dy + 'px)'; });
        if (mv.length) cancels.push(AZ.tween(420, (k) => mv.forEach((m) => { if (m.fresh) m.t.style.opacity = k; else m.t.style.transform = 'translateY(' + (m.dy * (1 - k)).toFixed(1) + 'px)'; }), () => mv.forEach((m) => { m.t.style.transform = ''; m.t.style.opacity = ''; m.t.style.position = ''; }), AZ.EASE.inOut));
      }
      el.querySelectorAll('th[data-k]').forEach((th) => {
        const on = th.getAttribute('data-k') === sortKey;
        if (on) th.setAttribute('aria-sort', sortDir < 0 ? 'descending' : 'ascending'); else th.removeAttribute('aria-sort');
        const ar = th.querySelector('.ar'); if (ar) ar.textContent = on ? (sortDir < 0 ? DN : UP) : '';
      });
    }
    el.querySelectorAll('th button').forEach((b) => b.addEventListener('click', () => {
      const k = b.getAttribute('data-k'), c = COLS.find((x) => x.k === k);
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = c.dir; }
      wrap.scrollTop = 0; paint(true);
    }));
    el.querySelectorAll('.lg-chip').forEach((b) => b.addEventListener('click', () => {
      const r = b.getAttribute('data-r'); if (regs.has(r)) regs.delete(r); else regs.add(r);
      b.setAttribute('aria-pressed', regs.has(r) ? 'true' : 'false'); wrap.scrollTop = 0; paint(true);
    }));
    if (!COLS.some((c) => c.k === sortKey)) { sortKey = 'pos'; sortDir = 1; }
    // One store in the result: open its months so the tile is not a single line.
    if (solo && !soloShut) openKey = lead.key;
    paint(false);
    if (openKey) { const tr = rowFor(openKey); if (tr) wrap.scrollTop = Math.max(0, tr.offsetTop - 28); }
    // Entrance: the form squares fill in left to right, once.
    const sqs = Array.from(body.querySelectorAll('.sq'));
    if (sqs.length && !AZ.reduced()) {
      sqs.forEach((q) => { q.style.opacity = 0; });
      cancels.push(AZ.tween(480, (k) => sqs.forEach((q) => { const j = Number(q.getAttribute('data-j')); q.style.opacity = Math.max(0, Math.min(1, k * 2.2 - j * 0.28)).toFixed(3); }), () => sqs.forEach((q) => { q.style.opacity = ''; })));
    }
    return () => { stop(); document.removeEventListener('keydown', onKey); };
  }
});
