/**
 * OPPORTUNITY RATE — KPI CARD
 *
 * A KPI card rendered as plain DOM (no Muze canvas — a single-number card
 * doesn't need a plot). Shows a headline rate, a red/green change-vs-prior
 * indicator, and a sentence comparing this period's count to last year's.
 * All numbers come from the ThoughtSpot search; sample data is used only
 * when no search data is available (local preview).
 *
 * Available Columns (ThoughtSpot search):
 * "Opportunity Count"        // MEASURE — opportunities created this period
 * "Prior Opportunity Count"  // MEASURE — same period last year
 * "Opportunity Rate"         // MEASURE (optional) — headline rate, 0–1 or 0–100
 * "Prior Opportunity Rate"   // MEASURE (optional) — same period last year
 * --- END ---
 *
 * If the two rate measures are absent, the headline falls back to the
 * percent change in counts: (current − prior) / prior.
 */

const { getDataFromSearchQuery } = viz;

// ─── Customize: measure names + card text ───
const M_CURRENT = 'Opportunity Count';
const M_PRIOR = 'Prior Opportunity Count';
const M_RATE = 'Opportunity Rate'; // optional
const M_PRIOR_RATE = 'Prior Opportunity Rate'; // optional

const TITLE = 'Opportunity rate';
const INFO_TEXT =
  'Opportunities created this period as a share of qualified leads, compared to the same period last year.';
// {current} and {prior} are replaced with the (bolded) dynamic counts.
const SUBTITLE_TEMPLATE =
  '{current} opportunities created this period compared to {prior} during the same period last year.';

const COLOR_VALUE = '#1E2437';
const COLOR_DOWN = '#B93425';
const COLOR_UP = '#1E7E4D';

// ── Sample data (used when no search data is available, e.g. local preview) ──
let kpi = { current: 0, prior: 3, rate: 0, priorRate: 0.10 };

// ── ThoughtSpot search data: used automatically when present ──
try {
  const tsRaw = getDataFromSearchQuery().getData();
  const idx = (name) => tsRaw.schema.findIndex((s) => s.name === name);
  const sumCol = (name) => {
    const i = idx(name);
    if (i < 0) return null;
    return tsRaw.data.reduce((acc, r) => acc + (Number(r[i]) || 0), 0);
  };
  // A KPI search normally returns one row; if it returns several, counts add
  // up but rates must be averaged.
  const avgCol = (name) => {
    const s = sumCol(name);
    return s == null ? null : s / tsRaw.data.length;
  };
  if (tsRaw.data && tsRaw.data.length && idx(M_CURRENT) >= 0 && idx(M_PRIOR) >= 0) {
    kpi = {
      current: sumCol(M_CURRENT),
      prior: sumCol(M_PRIOR),
      rate: avgCol(M_RATE),
      priorRate: avgCol(M_PRIOR_RATE),
    };
  }
} catch (e) {
  console.warn('Falling back to sample data:', e.message);
}

// Rates may arrive as fractions (0.1) or percents (10) — normalize to fractions.
const asFraction = (v) => (v == null ? null : Math.abs(v) > 1 ? v / 100 : v);
kpi.rate = asFraction(kpi.rate);
kpi.priorRate = asFraction(kpi.priorRate);

// Headline: the rate measure if provided, else percent change in counts.
const headline = kpi.rate != null ? kpi.rate
  : kpi.prior ? (kpi.current - kpi.prior) / kpi.prior : null;

// Delta: change in rate vs prior period (percentage points). Hidden when the
// rate measures aren't in the search — the headline already shows the count
// change in that mode, so repeating it would be noise.
const delta = kpi.rate != null && kpi.priorRate != null ? kpi.rate - kpi.priorRate : null;

const fmtInt = (v) => Math.round(v).toLocaleString('en-US');
const fmtPct = (v) => {
  const p = (Math.abs(v) * 100).toFixed(1);
  return (p.endsWith('.0') ? p.slice(0, -2) : p) + '%';
};

// ── Render (plain DOM) ──
const el = document.getElementById('chart');

const INFO_ICON =
  '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true">' +
  '<circle cx="10" cy="10" r="8.25" stroke="currentColor" stroke-width="1.5"/>' +
  '<circle cx="10" cy="6.3" r="1.1" fill="currentColor"/>' +
  '<rect x="9.1" y="8.9" width="1.8" height="6" rx="0.9" fill="currentColor"/>' +
  '</svg>';

function render() {
  const deltaHtml = delta == null || !isFinite(delta) ? '' :
    '<span class="kpi-delta" style="color:' + (delta < 0 ? COLOR_DOWN : COLOR_UP) + '">' +
      '<span class="kpi-delta-arrow">' + (delta < 0 ? '↓' : '↑') + '</span> ' +
      fmtPct(delta) +
    '</span>';

  const subtitleHtml = SUBTITLE_TEMPLATE
    .replace('{current}', '<b>' + fmtInt(kpi.current) + '</b>')
    .replace('{prior}', '<b>' + fmtInt(kpi.prior) + '</b>');

  el.innerHTML =
    '<div class="kpi-card">' +
      '<div class="kpi-title-row">' +
        '<span class="kpi-title">' + TITLE + '</span>' +
        '<span class="kpi-info" title="' + INFO_TEXT.replace(/"/g, '&quot;') + '">' + INFO_ICON + '</span>' +
      '</div>' +
      '<div class="kpi-value-row">' +
        '<span class="kpi-value" style="color:' + COLOR_VALUE + '">' +
          (headline == null || !isFinite(headline) ? '—' : fmtPct(headline)) +
        '</span>' +
        deltaHtml +
      '</div>' +
      '<div class="kpi-subtitle">' + subtitleHtml + '</div>' +
    '</div>';
}

// Responsive: scale the card's typography with the tile size. Everything in
// the CSS is in em, so one font-size on the card scales the whole layout.
function applySize() {
  const card = el.querySelector('.kpi-card');
  if (!card) return;
  const w = el.clientWidth, h = el.clientHeight;
  if (w <= 0 || h <= 0) return;
  const scale = Math.max(0.6, Math.min(w / 420, h / 250, 1.6));
  card.style.fontSize = (16 * scale).toFixed(2) + 'px';
}

render();
applySize();

let _rafId = null;
new ResizeObserver(() => {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = requestAnimationFrame(() => { applySize(); _rafId = null; });
}).observe(el);

// Signal render completion to ThoughtSpot (no-op in the local preview shim).
viz.events.emitRenderCompletedEvent();
