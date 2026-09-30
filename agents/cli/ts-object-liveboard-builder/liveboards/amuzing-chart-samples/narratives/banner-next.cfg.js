const CFG = {
  kind: 'banner', tab: '07  Next', question: 'What should we do?',
  need: 'sales, quantity purchased and date at monthly grain, e.g. [sales] [quantity purchased] [date].monthly',
  prompts: ['Sales and units against last year, by item type', 'Stores below last year, year to date', 'Full year sales using last year for the rest'],
  next: 'Last tab. The filters apply to every tile.',
  build: function (rows, schema) {
    const M = monthly(rows, schema);
    const ys = AZ.ytd(M.map((r) => ({ t: r.t, v: r.s }))), yu = AZ.ytd(M.map((r) => ({ t: r.t, v: r.u })));
    if (!ys || ys.pct == null || !yu || yu.pct == null) return { lead: 'Include the latest months and the same months a year earlier to compare year to date.', stats: [] };
    const ppu = ys.cur / yu.cur / (ys.prev / yu.prev) - 1;
    const level = Math.abs(ys.pct) < 0.03;
    const tail = level ? 'Both are close to level, so the big steps are behind us. What is left to move is item mix and individual stores.' : (ys.pct < 0 ? 'Sales are still below last year, so the decline has not stopped.' : 'Sales are above last year, so the recovery is under way.');
    return {
      lead: 'Year to date through ' + ys.through + ', sales are ' + pct(ys.pct, 1, true) + ' and units ' + pct(yu.pct, 1, true) + ' on the same months a year earlier; price per unit is ' + pct(ppu, 1, true) + '. ' + tail,
      stats: [
        { v: pct(ys.pct, 1, true), k: 'Sales, year to date', note: money(ys.cur) + ' against ' + money(ys.prev) + ' in the same months a year earlier.' },
        { v: pct(yu.pct, 1, true), k: 'Units, year to date', note: AZ.int(yu.cur) + ' against ' + AZ.int(yu.prev) + ' in the same months a year earlier.' },
        { v: pct(ppu, 1, true), k: 'Price per unit, year to date', note: 'Sales per unit this year against the same months a year earlier.' }
      ]
    };
  }
};
