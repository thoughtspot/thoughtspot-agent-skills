const CFG = {
  kind: 'banner', tab: '06  Who', question: 'Who leads?',
  need: 'sales by store, e.g. [sales] [store]',
  prompts: ['Top 10 stores by sales', 'Stores below last year, same quarters', 'Top 25 products with units and price'],
  next: 'Then: 07 Next',
  build: function (rows, schema) {
    const st = groupSum(rows, AZ.col(schema, /store/i), AZ.col(schema, /sales/i)), tot = sum(st.map((x) => x.v));
    if (st.length < 3 || !tot) return { lead: 'Include at least three stores to compare leaders and laggards.', stats: [] };
    const n = st.length, top5 = sum(st.slice(0, Math.min(5, n)).map((x) => x.v)), med = st[Math.floor(n / 2)].v, low = st[n - 1];
    const lead = 'The largest ' + Math.min(5, n) + ' of ' + n + ' stores make ' + pct(top5 / tot, 1) + ' of sales. The largest, ' + st[0].k + ', sells ' + (low.v ? (st[0].v / low.v).toFixed(1) : '0') + 'x the smallest and ' + (med ? (st[0].v / med).toFixed(1) : '0') + 'x the median store.';
    return {
      lead: lead,
      stats: [
        { v: pct(top5 / tot, 0), k: 'Share from the largest ' + Math.min(5, n) + ' stores', note: 'Sum of the largest ' + Math.min(5, n) + ' stores (' + money(top5) + ') over all sales in this view (' + money(tot) + ').' },
        { v: (med ? st[0].v / med : 0).toFixed(1) + 'x', k: 'Largest store against the median', note: st[0].k + ' (' + money(st[0].v) + ') against the median store (' + money(med) + ').' },
        { v: String(n), k: 'Stores with sales in this view', note: 'Count of distinct stores in the current filter.' }
      ]
    };
  }
};
