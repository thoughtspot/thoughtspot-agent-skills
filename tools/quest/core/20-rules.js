// Quest.rules: gold. Right answers earn it, wrong ones cost some, magic is free.
var Quest = (typeof Quest === "object" && Quest) || {};
(function (Q) {
  "use strict";
  const GOLD_WIN = 10, GOLD_LOSS = 5;
  // Most gold a realm can give: every question answered right first time.
  const questionsIn = r => r.halls.reduce((n, h) => n + h.trials.length, 0) + r.encounters.reduce((n, e) => n + 1 + e.points.length, 0);
  const maxGold = r => questionsIn(r) * GOLD_WIN;
  const open = realms => realms.filter(r => !r.sealed);
  Q.rules = { GOLD_WIN, GOLD_LOSS, questionsIn, maxGold, open,
              courseMax: realms => open(realms).reduce((n, r) => n + maxGold(r), 0) };
})(Quest);
