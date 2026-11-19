const CFG = {
  kind: 'about', title: 'Amuzing chart samples',
  need: 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly',
  people: [
    { who: 'Merchandising lead', asks: 'Which item types carry the business, and is price holding?', start: '04 What, then 06 Who' },
    { who: 'Regional operations', asks: 'Which states and stores lead, and which have slipped?', start: '03 Where, then 06 Who' },
    { who: 'Finance partner', asks: 'What happened to the level of sales, and where is the year heading?', start: '02 Pulse, then 07 Next' }
  ],
  terms: [
    { term: 'Same months', def: 'The months of the latest year up to its last month, set against the same months of the year before. It keeps a part-year honest.' },
    { term: 'Price per unit', def: 'Sales divided by units, over the months named. It moves with price and with the mix of what was sold.' },
    { term: 'Family', def: 'An editorial grouping of the 15 item types into five families. It is not a column in the model, and it is the only place colour is used.' },
    { term: 'Step', def: 'A month whose sales differ sharply from the month before. The Liveboard has two large ones.' }
  ],
  build: function (rows, schema) {
    const M = monthly(rows, schema);
    if (M.length < 24) return { sub: 'Widen the date filter to at least 24 months for the full story.', stakes: [], body: '' };
    const tot = sum(M.map((r) => r.s)), units = sum(M.map((r) => r.u));
    const avg = (a) => sum(a.map((r) => r.s)) / a.length, asp = (a) => sum(a.map((r) => r.s)) / (sum(a.map((r) => r.u)) || 1);
    let best = 0, bi = 0; for (let i = 0; i + 12 <= M.length; i++) { const v = avg(M.slice(i, i + 12)); if (v > best) { best = v; bi = i; } }
    let up = null, dn = null; for (let i = 1; i < M.length; i++) { const g = M[i - 1].s ? M[i].s / M[i - 1].s : 1; if (!up || g > up.g) up = { i: i, g: g }; if (!dn || g < dn.g) dn = { i: i, g: g }; }
    const a0 = avg(M.slice(0, 12)), p0 = asp(M.slice(0, 12)), p1 = asp(M.slice(-12));
    return {
      sub: 'Custom charts on ' + money(tot) + ' of apparel sales, ' + AZ.monthLabel(M[0].t) + ' to ' + AZ.monthLabel(M[M.length - 1].t) + ', built one question per tab.',
      stakes: [
        { v: (best / a0).toFixed(1) + 'x', k: 'Monthly average of the best 12 months against the first 12' },
        { v: pct(p1 / p0 - 1, 0, true), k: 'Price per unit, latest 12 months against the first 12' },
        { v: AZ.int(units), k: 'Units sold across the period' }
      ],
      body: 'Sales did not drift, they stepped. In ' + AZ.monthLabel(M[up.i].t) + ' they rose ' + pct(up.g - 1, 0) + ' on the month, and in ' + AZ.monthLabel(M[dn.i].t) + ' they fell ' + pct(1 - dn.g, 0) + '. Price per unit went from $' + p0.toFixed(2) + ' to $' + p1.toFixed(2) + ' over the same span. This Liveboard follows the money from that shape to the states, products, months and stores behind it, and ends on what is left to change.'
    };
  }
};
