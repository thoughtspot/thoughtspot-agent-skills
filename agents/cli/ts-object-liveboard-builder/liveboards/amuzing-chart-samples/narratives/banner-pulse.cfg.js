const CFG = {
  kind: 'banner', tab: '02  Pulse', question: 'How are we doing?',
  need: 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly',
  prompts: ['Monthly sales and average selling price, last 24 months', 'Which month had the largest drop in units?', 'Sales year to date against the same months last year'],
  next: 'Then: 03 Where',
  build: function (rows, schema) {
    const M = monthly(rows, schema);
    if (M.length < 24) return { lead: 'Widen the date filter to at least 24 months to compare the start, the peak and today.', stats: [] };
    const avg = (a) => sum(a.map((r) => r.s)) / a.length;
    const asp = (a) => { const u = sum(a.map((r) => r.u)); return u ? sum(a.map((r) => r.s)) / u : 0; };
    const first = M.slice(0, 12), last = M.slice(-12);
    let best = 0, bi = 0;
    for (let i = 0; i + 12 <= M.length; i++) { const v = avg(M.slice(i, i + 12)); if (v > best) { best = v; bi = i; } }
    const a0 = avg(first), a1 = avg(last), p0 = asp(first), p1 = asp(last);
    return {
      lead: 'Sales sat near ' + money(a0) + ' a month, peaked at ' + money(best) + ' a month from ' + AZ.monthLabel(M[bi].t) + ', and now run near ' + money(a1) + '. Price per unit went from $' + p0.toFixed(2) + ' to $' + p1.toFixed(2) + ' over the same span.',
      stats: [
        { v: (best / a0).toFixed(1) + 'x', k: 'Best 12 months against the first 12', note: 'Average monthly sales of the best 12 consecutive months (' + money(best) + ') divided by the first 12 months in this view (' + money(a0) + ').' },
        { v: pct(a1 / best - 1, 0, true), k: 'Latest 12 months against the best 12', note: 'Average monthly sales of the latest 12 months (' + money(a1) + ') against the best 12 (' + money(best) + ').' },
        { v: pct(p1 / p0 - 1, 0, true), k: 'Price per unit, latest 12 against first 12', note: 'Sales divided by units: $' + p1.toFixed(2) + ' in the latest 12 months against $' + p0.toFixed(2) + ' in the first 12.' }
      ]
    };
  }
};
