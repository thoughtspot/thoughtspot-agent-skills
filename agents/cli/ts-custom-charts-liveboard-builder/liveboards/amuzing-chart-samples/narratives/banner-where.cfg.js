const CFG = {
  kind: 'banner', tab: '03  Where', question: 'Where does it sell?',
  need: 'sales by region and state, e.g. [sales] [region] [state]',
  prompts: ['Show sales by state and region', 'Highest-selling store in each state', 'How many stores does each state have?'],
  next: 'Then: 04 What',
  build: function (rows, schema) {
    const rK = AZ.col(schema, /^region$/i), sK = AZ.col(schema, /^state$/i), vK = AZ.col(schema, /sales/i);
    const reg = groupSum(rows, rK, vK), st = groupSum(rows, sK, vK), tot = sum(st.map((x) => x.v));
    if (!tot) return { lead: 'No sales in this view.', stats: [] };
    const two = st.length > 1 ? st[0].v + st[1].v : st[0].v;
    const lead = reg[0].k + ' is the largest region at ' + pct(reg[0].v / tot, 0) + ' of sales. '
      + (st.length > 1 ? st[0].k + ' and ' + st[1].k + ' together make ' + pct(two / tot, 0) + ', ahead of the other ' + (st.length - 2) + ' state' + (st.length - 2 === 1 ? '' : 's') + '.' : st[0].k + ' is the only state in this view.');
    return {
      lead: lead,
      stats: [
        { v: pct(reg[0].v / tot, 0), k: reg[0].k + ', the largest region', note: 'Sales of the ' + reg[0].k + ' region (' + money(reg[0].v) + ') as a share of all sales in this view (' + money(tot) + ').' },
        { v: pct(two / tot, 0), k: 'Top two states together', note: (st.length > 1 ? st[0].k + ' (' + money(st[0].v) + ') and ' + st[1].k + ' (' + money(st[1].v) + ')' : st[0].k) + ' as a share of sales in this view.' },
        { v: String(st.length), k: 'States with sales, in ' + reg.length + ' region' + (reg.length === 1 ? '' : 's'), note: 'Count of distinct states in the current filter.' }
      ]
    };
  }
};
