const CFG = {
  kind: 'banner', tab: '05  When', question: 'When does it sell?',
  need: 'sales by date at monthly grain, e.g. [sales] [date].monthly',
  prompts: ['Monthly sales by year, last 4 years', 'Calendar month with the most units', 'Quarterly sales by item type'],
  next: 'Then: 06 Who',
  build: function (rows, schema) {
    const M = monthly(rows, schema), by = {};
    M.forEach((r) => { const y = AZ.year(r.t); (by[y] = by[y] || []).push(r); });
    const full = Object.keys(by).filter((y) => by[y].length === 12).map(Number).sort((a, b) => a - b);
    if (!full.length) return { lead: 'Widen the date filter to include a full calendar year to read the seasonal shape.', stats: [] };
    const swing = (a) => { const hi = a.reduce((b, r) => (r.s > b.s ? r : b), a[0]), lo = a.reduce((b, r) => (r.s < b.s ? r : b), a[0]); return { hi: hi, lo: lo, x: lo.s ? hi.s / lo.s : 0 }; };
    const y = full[full.length - 1], s = swing(by[y]);
    const first = M.length >= 12 ? swing(M.slice(0, 12)) : null;
    const lead = 'In ' + y + ', sales peaked in ' + AZ.monthShort(s.hi.t) + ' at ' + money(s.hi.s) + ' and bottomed in ' + AZ.monthShort(s.lo.t) + ' at ' + money(s.lo.s) + ', a ' + s.x.toFixed(2) + 'x swing.'
      + (first && M.length >= 24 ? ' The first 12 months in this view swung ' + first.x.toFixed(2) + 'x, so the season is ' + (s.x > first.x ? 'wider' : 'narrower') + ' now.' : '');
    return {
      lead: lead,
      stats: [
        { v: AZ.monthShort(s.hi.t), k: 'Peak month in ' + y, note: money(s.hi.s) + ' in ' + AZ.monthLabel(s.hi.t) + ', the highest of the 12 months.' },
        { v: AZ.monthShort(s.lo.t), k: 'Low month in ' + y, note: money(s.lo.s) + ' in ' + AZ.monthLabel(s.lo.t) + ', the lowest of the 12 months.' },
        { v: s.x.toFixed(2) + 'x', k: 'Peak against low', note: 'Highest month divided by lowest month within ' + y + '.' }
      ]
    };
  }
};
