const CFG = {
  kind: 'banner', tab: '04  What', question: 'What sells?',
  need: 'sales by item type, e.g. [sales] [item type]',
  prompts: ['Top 10 item types by sales', 'Which products make up 80 percent of sales?', 'Average selling price by item type'],
  next: 'Then: 05 When',
  build: function (rows, schema) {
    const it = groupSum(rows, AZ.col(schema, /item/i), AZ.col(schema, /sales/i)), tot = sum(it.map((x) => x.v));
    if (!tot) return { lead: 'No sales in this view.', stats: [] };
    const fam = {}; it.forEach((x) => { const f = AZ.familyOf(x.k); fam[f] = (fam[f] || 0) + x.v; });
    const fl = Object.entries(fam).sort((a, b) => b[1] - a[1]);
    const top5 = sum(it.slice(0, 5).map((x) => x.v)), last = it[it.length - 1];
    const lead = it.length > 1 ? it[0].k + ' and ' + it[1].k + ' make ' + pct((it[0].v + it[1].v) / tot, 0) + ' of sales. The five largest item types make ' + pct(top5 / tot, 0) + '; the smallest, ' + last.k + ', makes ' + pct(last.v / tot, 1) + '.' : it[0].k + ' is the only item type in this view.';
    return {
      lead: lead,
      stats: [
        { v: pct(fl[0][1] / tot, 0), k: fl[0][0] + ', the largest family', note: 'Families group the 15 item types editorially (not a model column). ' + fl[0][0] + ' holds ' + money(fl[0][1]) + ' of ' + money(tot) + '.' },
        { v: pct(top5 / tot, 0), k: 'Five largest item types', note: 'Sum of the five largest item types (' + it.slice(0, 5).map((x) => x.k).join(', ') + ') over all sales in this view.' },
        { v: String(it.length), k: 'Item types in this view', note: 'Distinct item types in the current filter.' }
      ]
    };
  }
};
