/**
 * Available Columns:
 * "home_team"            // ATTRIBUTE
 * "away_team"            // ATTRIBUTE
 * "tournament"           // ATTRIBUTE
 * "city"                 // ATTRIBUTE
 * "country"              // ATTRIBUTE
 * "neutral"              // ATTRIBUTE (TRUE/FALSE)
 * "date"                 // ATTRIBUTE (full match date — REQUIRED for per-match granularity)
 * "Year"                 // ATTRIBUTE (4-digit year, e.g. 1877 — derived, display only)
 * "Total home_score"     // MEASURE
 * "Total away_score"     // MEASURE
 * "total goals"          // MEASURE
 * --- END ---
 *
 * IMPORTANT — data granularity:
 *   This scoreboard treats EACH ROW as one match. The TS search MUST therefore
 *   return one row per match. Group the search by the full match `date` (not just
 *   `Year`): e.g. `home_team away_team tournament date home_score away_score`.
 *   If you group only by Year, SUM(home_score)/SUM(away_score) collapse every
 *   same-year/tournament fixture into a single row — undercounting matches and
 *   producing wrong win/draw verdicts and goal totals.
 */

// ── Column Name Constants (update to match the TS data) ──
const COL_HOME_TEAM  = 'home_team';
const COL_AWAY_TEAM  = 'away_team';
const COL_TOURNAMENT = 'tournament';
// Prefer the full match date (per-match granularity); fall back to a Year column.
const COL_DATE       = 'date';
const COL_HOME_SCORE = 'Total home_score';
const COL_AWAY_SCORE = 'Total away_score';

// ── Default teams shown on first render ──
const DEFAULT_TEAM_1 = 'England';
const DEFAULT_TEAM_2 = 'Germany';

// ── Flag emoji lookup (181 entries; teams without a flag fall back to 🏳) ──
const FLAGS = {
  "Afghanistan": "🇦🇫", "Albania": "🇦🇱", "Algeria": "🇩🇿", "Andorra": "🇦🇩", "Angola": "🇦🇴",
  "Antigua and Barbuda": "🇦🇬", "Argentina": "🇦🇷", "Armenia": "🇦🇲", "Australia": "🇦🇺",
  "Austria": "🇦🇹", "Azerbaijan": "🇦🇿", "Bahamas": "🇧🇸", "Bahrain": "🇧🇭", "Bangladesh": "🇧🇩",
  "Barbados": "🇧🇧", "Belarus": "🇧🇾", "Belgium": "🇧🇪", "Belize": "🇧🇿", "Benin": "🇧🇯",
  "Bhutan": "🇧🇹", "Bolivia": "🇧🇴", "Bosnia and Herzegovina": "🇧🇦", "Botswana": "🇧🇼", "Brazil": "🇧🇷",
  "Brunei": "🇧🇳", "Bulgaria": "🇧🇬", "Burkina Faso": "🇧🇫", "Burundi": "🇧🇮", "Cambodia": "🇰🇭",
  "Cameroon": "🇨🇲", "Canada": "🇨🇦", "Cape Verde": "🇨🇻", "Central African Republic": "🇨🇫",
  "Chad": "🇹🇩", "Chile": "🇨🇱", "China": "🇨🇳", "Colombia": "🇨🇴", "Comoros": "🇰🇲", "Congo": "🇨🇬",
  "Costa Rica": "🇨🇷", "Croatia": "🇭🇷", "Cuba": "🇨🇺", "Cyprus": "🇨🇾", "Czech Republic": "🇨🇿",
  "Czechia": "🇨🇿", "DR Congo": "🇨🇩", "Denmark": "🇩🇰", "Djibouti": "🇩🇯", "Dominican Republic": "🇩🇴",
  "Ecuador": "🇪🇨", "Egypt": "🇪🇬", "El Salvador": "🇸🇻", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
  "Equatorial Guinea": "🇬🇶", "Eritrea": "🇪🇷", "Estonia": "🇪🇪", "Eswatini": "🇸🇿", "Ethiopia": "🇪🇹",
  "Fiji": "🇫🇯", "Finland": "🇫🇮", "France": "🇫🇷", "Gabon": "🇬🇦", "Gambia": "🇬🇲", "Georgia": "🇬🇪",
  "Germany": "🇩🇪", "Ghana": "🇬🇭", "Greece": "🇬🇷", "Guatemala": "🇬🇹", "Guinea": "🇬🇳",
  "Guinea-Bissau": "🇬🇼", "Guyana": "🇬🇾", "Haiti": "🇭🇹", "Honduras": "🇭🇳", "Hong Kong": "🇭🇰",
  "Hungary": "🇭🇺", "Iceland": "🇮🇸", "India": "🇮🇳", "Indonesia": "🇮🇩", "Iran": "🇮🇷", "Iraq": "🇮🇶",
  "Israel": "🇮🇱", "Italy": "🇮🇹", "Ivory Coast": "🇨🇮", "Jamaica": "🇯🇲", "Japan": "🇯🇵",
  "Jordan": "🇯🇴", "Kazakhstan": "🇰🇿", "Kenya": "🇰🇪", "Kosovo": "🇽🇰", "Kuwait": "🇰🇼",
  "Kyrgyzstan": "🇰🇬", "Laos": "🇱🇦", "Latvia": "🇱🇻", "Lebanon": "🇱🇧", "Lesotho": "🇱🇸",
  "Liberia": "🇱🇷", "Libya": "🇱🇾", "Liechtenstein": "🇱🇮", "Lithuania": "🇱🇹", "Luxembourg": "🇱🇺",
  "Madagascar": "🇲🇬", "Malawi": "🇲🇼", "Malaysia": "🇲🇾", "Maldives": "🇲🇻", "Mali": "🇲🇱",
  "Malta": "🇲🇹", "Mauritania": "🇲🇷", "Mauritius": "🇲🇺", "Mexico": "🇲🇽", "Moldova": "🇲🇩",
  "Mongolia": "🇲🇳", "Montenegro": "🇲🇪", "Morocco": "🇲🇦", "Mozambique": "🇲🇿", "Myanmar": "🇲🇲",
  "Namibia": "🇳🇦", "Nepal": "🇳🇵", "Netherlands": "🇳🇱", "New Zealand": "🇳🇿", "Nicaragua": "🇳🇮",
  "Niger": "🇳🇪", "Nigeria": "🇳🇬", "North Korea": "🇰🇵", "North Macedonia": "🇲🇰",
  "Northern Ireland": "🇬🇧", "Norway": "🇳🇴", "Oman": "🇴🇲", "Pakistan": "🇵🇰", "Palestine": "🇵🇸",
  "Panama": "🇵🇦", "Papua New Guinea": "🇵🇬", "Paraguay": "🇵🇾", "Peru": "🇵🇪", "Philippines": "🇵🇭",
  "Poland": "🇵🇱", "Portugal": "🇵🇹", "Qatar": "🇶🇦", "Republic of Ireland": "🇮🇪", "Romania": "🇷🇴",
  "Russia": "🇷🇺", "Rwanda": "🇷🇼", "Saudi Arabia": "🇸🇦", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Senegal": "🇸🇳",
  "Serbia": "🇷🇸", "Sierra Leone": "🇸🇱", "Singapore": "🇸🇬", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮",
  "Somalia": "🇸🇴", "South Africa": "🇿🇦", "South Korea": "🇰🇷", "South Sudan": "🇸🇸", "Spain": "🇪🇸",
  "Sri Lanka": "🇱🇰", "Sudan": "🇸🇩", "Suriname": "🇸🇷", "Sweden": "🇸🇪", "Switzerland": "🇨🇭",
  "Syria": "🇸🇾", "Taiwan": "🇹🇼", "Tajikistan": "🇹🇯", "Tanzania": "🇹🇿", "Thailand": "🇹🇭",
  "Togo": "🇹🇬", "Trinidad and Tobago": "🇹🇹", "Tunisia": "🇹🇳", "Turkey": "🇹🇷", "Turkmenistan": "🇹🇲",
  "Uganda": "🇺🇬", "Ukraine": "🇺🇦", "United Arab Emirates": "🇦🇪", "United States": "🇺🇸",
  "Uruguay": "🇺🇾", "Uzbekistan": "🇺🇿", "Venezuela": "🇻🇪", "Vietnam": "🇻🇳", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
  "Yemen": "🇾🇪", "Zambia": "🇿🇲", "Zimbabwe": "🇿🇼",
};
const flag = name => FLAGS[name] || '🏳';

// ── Sample dataset for standalone / preview mode ──
// Commented out: in ThoughtSpot the data comes from viz.getDataFromSearchQuery().
// Uncomment if you want a standalone (no-TS) preview.
// const SAMPLE = {
//   schema: [
//     { name: COL_HOME_TEAM,  type: 'ATTRIBUTE' },
//     { name: COL_AWAY_TEAM,  type: 'ATTRIBUTE' },
//     { name: COL_TOURNAMENT, type: 'ATTRIBUTE' },
//     { name: COL_DATE,       type: 'ATTRIBUTE' },
//     { name: COL_HOME_SCORE, type: 'MEASURE'   },
//     { name: COL_AWAY_SCORE, type: 'MEASURE'   },
//   ],
//   data: [
//     // England vs Germany
//     ['Germany','England','Friendly','1930',3,3],
//     ['England','Germany','Friendly','1935',3,0],
//     ['Germany','England','Friendly','1938',6,3],
//     ['England','Germany','Friendly','1954',3,1],
//     ['Germany','England','Friendly','1956',3,1],
//     ['England','Germany','FIFA World Cup','1966',4,2],
//     ['Germany','England','UEFA Euro','1972',3,1],
//     ['England','Germany','FIFA World Cup','1990',1,1],
//     ['Germany','England','UEFA Euro','1996',1,1],
//     ['England','Germany','FIFA World Cup qualification','2000',0,1],
//     ['Germany','England','FIFA World Cup qualification','2001',1,5],
//     ['Germany','England','FIFA World Cup','2010',4,1],
//     ['England','Germany','Friendly','2013',0,1],
//     ['Germany','England','UEFA Euro','2021',0,2],
//     ['Germany','England','UEFA Nations League','2022',3,3],
//
//     // England vs Scotland
//     ['Scotland','England','Friendly','1872',0,0],
//     ['England','Scotland','Friendly','1873',4,2],
//     ['Scotland','England','British Home Championship','1884',1,0],
//     ['England','Scotland','British Home Championship','1890',1,1],
//     ['Scotland','England','FIFA World Cup qualification','1950',0,1],
//     ['England','Scotland','UEFA Euro','1996',2,0],
//     ['Scotland','England','UEFA Euro qualification','1999',2,0],
//
//     // Brazil vs Argentina
//     ['Argentina','Brazil','Copa America','1937',1,0],
//     ['Brazil','Argentina','Copa America','1946',2,0],
//     ['Argentina','Brazil','FIFA World Cup qualification','1957',3,0],
//     ['Brazil','Argentina','FIFA World Cup','1990',0,1],
//     ['Argentina','Brazil','Copa America','2004',2,2],
//     ['Brazil','Argentina','Copa America','2007',3,0],
//     ['Argentina','Brazil','Friendly','2012',4,3],
//     ['Brazil','Argentina','FIFA World Cup qualification','2016',0,3],
//     ['Argentina','Brazil','Copa America','2021',1,0],
//     ['Brazil','Argentina','FIFA World Cup qualification','2023',0,1],
//
//     // Germany vs France
//     ['Germany','France','Friendly','1931',1,0],
//     ['France','Germany','FIFA World Cup','1958',3,6],
//     ['Germany','France','FIFA World Cup','1982',3,3],
//     ['France','Germany','FIFA World Cup','1986',0,2],
//     ['Germany','France','Friendly','2005',0,0],
//     ['France','Germany','FIFA World Cup','2014',0,1],
//     ['Germany','France','UEFA Euro','2016',0,2],
//     ['France','Germany','UEFA Nations League','2018',2,1],
//     ['Germany','France','UEFA Euro','2021',0,1],
//
//     // Spain vs Italy
//     ['Italy','Spain','Friendly','1920',2,0],
//     ['Spain','Italy','FIFA World Cup','1934',1,1],
//     ['Italy','Spain','UEFA Euro','2008',0,0],
//     ['Spain','Italy','UEFA Euro','2012',4,0],
//     ['Italy','Spain','UEFA Euro','2016',2,0],
//     ['Spain','Italy','UEFA Nations League','2021',1,2],
//     ['Italy','Spain','UEFA Euro','2024',0,1],
//
//     // Netherlands vs Belgium
//     ['Belgium','Netherlands','Friendly','1905',1,4],
//     ['Netherlands','Belgium','FIFA World Cup qualification','1949',2,1],
//     ['Belgium','Netherlands','UEFA Euro','2000',0,2],
//     ['Netherlands','Belgium','Friendly','2018',1,1],
//     ['Belgium','Netherlands','UEFA Nations League','2022',1,4],
//   ],
// };

// ── Read data: TS viz only ──
function readData() {
  try {
    if (typeof viz !== 'undefined' && viz?.getDataFromSearchQuery) {
      const dm = viz.getDataFromSearchQuery();
      const { schema, data } = dm.getData();
      return { schema, data };
    }
  } catch (e) {
    console.warn('[scoreboard] viz read failed:', e);
  }
  // No sample fallback — re-enable SAMPLE above to preview standalone.
  return { schema: [], data: [] };
}

// ── Resolve a schema column by exact name → case-insensitive → fuzzy keywords ──
function resolveCol(schema, exact, ...fuzzyKeywords) {
  let i = schema.findIndex(c => c.name === exact);
  if (i >= 0) return i;
  const low = exact.toLowerCase();
  i = schema.findIndex(c => c.name.toLowerCase() === low);
  if (i >= 0) return i;
  for (const kw of fuzzyKeywords) {
    const re = new RegExp(kw, 'i');
    i = schema.findIndex(c => re.test(c.name));
    if (i >= 0) return i;
  }
  return -1;
}

// ── Normalize raw [schema, data] into objects keyed by column name ──
function toRows({ schema, data }) {
  const iHome  = resolveCol(schema, COL_HOME_TEAM,  'home.*team', '^home$');
  const iAway  = resolveCol(schema, COL_AWAY_TEAM,  'away.*team', '^away$');
  const iTour  = resolveCol(schema, COL_TOURNAMENT, 'tournament');
  const iDate  = resolveCol(schema, COL_DATE,       'month.*date', '^date$', 'month', 'year');
  const iHS    = resolveCol(schema, COL_HOME_SCORE, 'home.*score', '^home_score');
  const iAS    = resolveCol(schema, COL_AWAY_SCORE, 'away.*score', '^away_score');

  console.log('[scoreboard] schema columns:', schema.map(c => c.name));
  console.log('[scoreboard] resolved indexes:', { iHome, iAway, iTour, iDate, iHS, iAS });
  if (data?.[0]) console.log('[scoreboard] sample row:', data[0], 'date value:', data[0][iDate]);

  return data.map(r => ({
    home:      iHome >= 0 ? String(r[iHome] ?? '') : '',
    away:      iAway >= 0 ? String(r[iAway] ?? '') : '',
    tour:      iTour >= 0 ? String(r[iTour] ?? '') : '',
    date:      iDate >= 0 ? r[iDate] : undefined,
    homeScore: iHS   >= 0 ? Number(r[iHS] ?? 0) : 0,
    awayScore: iAS   >= 0 ? Number(r[iAS] ?? 0) : 0,
  }));
}

// ── Tournament filter classifier ──
// This dataset only contains World Cup tournaments and their qualifiers
// (e.g. "fifa world cup", "fifa 75th anniversary cup", "fifa world cup qualification").
// "World Cup" = any finals/tournament match (everything that is NOT qualification);
// "Qualifiers" = qualification matches.
function matchFilter(tour, filter) {
  const t = (tour || '').toLowerCase();
  switch (filter) {
    case 'wc':   return !t.includes('qualification');
    case 'qual': return t.includes('qualification');
    case 'all':
    default:     return true;
  }
}

// ── Build H2H summary for a pair (t1,t2) under the chosen tournament filter ──
function buildH2H(rows, t1, t2, filter) {
  let t1_wins = 0, t2_wins = 0, draws = 0, t1_goals = 0, t2_goals = 0;
  const history = [];

  for (const m of rows) {
    if (!matchFilter(m.tour, filter)) continue;
    let s1, s2;
    if (m.home === t1 && m.away === t2)      { s1 = m.homeScore; s2 = m.awayScore; }
    else if (m.home === t2 && m.away === t1) { s1 = m.awayScore; s2 = m.homeScore; }
    else continue;

    t1_goals += s1; t2_goals += s2;
    if      (s1 > s2) t1_wins++;
    else if (s2 > s1) t2_wins++;
    else              draws++;
    history.push({ date: formatDate(m.date), tournament: m.tour, t1_score: s1, t2_score: s2 });
  }

  return { t1_wins, t2_wins, draws, t1_goals, t2_goals, games: history.length, history };
}

// ── Convert "Monthly date" raw → year label.
// Handles: epoch ms, Date instances, display strings ("Mar 1877"), ISO strings,
// bare years, and wrapped TS value objects ({value, formattedValue, v, ...}).
function formatDate(d) {
  if (d == null) return '';
  if (d instanceof Date) {
    const y = d.getFullYear();
    return isNaN(y) ? '' : String(y);
  }
  if (typeof d === 'number') {
    if (!isFinite(d)) return '';
    if (Math.abs(d) > 1e10) return String(new Date(d).getFullYear()); // epoch ms (incl. pre-1970)
    return String(d);                                                  // already a year
  }
  if (typeof d === 'string') {
    const m = d.match(/\b(1[89]\d{2}|20\d{2}|21\d{2})\b/);
    if (m) return m[1];
    const n = Number(d);
    if (!isNaN(n) && Math.abs(n) > 1e10) return String(new Date(n).getFullYear());
    return d;
  }
  if (typeof d === 'object') {
    // TS sometimes wraps cells as { value, formattedValue } or similar.
    return formatDate(d.value ?? d.v ?? d.formattedValue ?? d.year ?? d.toString?.());
  }
  return String(d);
}

// ── Unique sorted team list from the raw rows ──
function extractTeams(rows) {
  const set = new Set();
  for (const m of rows) { if (m.home) set.add(m.home); if (m.away) set.add(m.away); }
  return Array.from(set).sort();
}

// ── Teams that appear in ≥1 match under `filter` (reuses matchFilter). ──
function teamsUnderFilter(filter) {
  const set = new Set();
  for (const m of ROWS) {
    if (!matchFilter(m.tour, filter)) continue;
    if (m.home) set.add(m.home);
    if (m.away) set.add(m.away);
  }
  return set;
}

// ── Distinct opponents `team` has faced under `filter`. ──
function opponentsOf(team, filter) {
  const set = new Set();
  for (const m of ROWS) {
    if (!matchFilter(m.tour, filter)) continue;
    if (m.home === team && m.away)      set.add(m.away);
    else if (m.away === team && m.home) set.add(m.home);
  }
  return set;
}

// ── State ──
const raw = readData();
const ROWS = toRows(raw);
const TEAMS = extractTeams(ROWS);
let selected = [null, null];
let activeFilter = 'wc';

// ── Renderers ──
function renderScoreboard() {
  const sb = document.getElementById('scoreboard');
  const [t1, t2] = selected;
  if (!t1 || !t2) { sb.innerHTML = '<div class="no-data">Select two teams above</div>'; return; }
  if (t1 === t2)  { sb.innerHTML = '<div class="no-data">Select two different teams</div>'; return; }

  const s = buildH2H(ROWS, t1, t2, activeFilter);
  if (s.games === 0) {
    sb.innerHTML = `<div class="no-data">No ${activeFilter === 'all' ? '' : activeFilter + ' '}matches found between ${t1} and ${t2}</div>`;
    return;
  }

  const total = s.games;
  const w1 = Math.round(s.t1_wins / total * 100);
  const wd = Math.round(s.draws  / total * 100);
  const w2 = 100 - w1 - wd;

  // sort sample matches by date desc when comparable, else keep insertion order; cap at 5
  const sample = s.history.slice(-5);
  const pills = sample.map(h => {
    const cls = h.t1_score > h.t2_score ? 'fp-t1' : h.t1_score < h.t2_score ? 'fp-t2' : 'fp-draw';
    return `<span class="fp ${cls}">${h.date} &middot; ${h.t1_score}&ndash;${h.t2_score}</span>`;
  }).join('');

  sb.innerHTML = `
    <div class="record-row">
      <div class="team-block">
        <span class="team-flag">${flag(t1)}</span>
        <span class="team-name blue">${t1}</span>
      </div>
      <div class="score-center">
        <div class="big-score"><span class="s1">${s.t1_wins}</span><span class="ssep">&ndash;</span><span class="s2">${s.t2_wins}</span></div>
        <div class="score-label">Wins &middot; ${total} matches</div>
      </div>
      <div class="team-block right">
        <span class="team-flag">${flag(t2)}</span>
        <span class="team-name orange">${t2}</span>
      </div>
    </div>
    <div class="stats-row">
      <div class="stat-cell"><div class="stat-val sv-blue">${s.t1_goals}</div><div class="stat-label">${t1} goals</div></div>
      <div class="stat-cell"><div class="stat-val sv-green">${s.draws}</div><div class="stat-label">Draws</div></div>
      <div class="stat-cell"><div class="stat-val sv-orange">${s.t2_goals}</div><div class="stat-label">${t2} goals</div></div>
    </div>
    <div class="bar-row">
      <div class="bar-label"><span>${t1} ${w1}%</span><span>Draw ${wd}%</span><span>${w2}% ${t2}</span></div>
      <div class="bar-track"><div class="bar-t1" style="width:${w1}%"></div><div class="bar-draw" style="width:${wd}%"></div><div class="bar-t2"></div></div>
    </div>
    ${pills ? `<div class="recent-row"><div class="recent-label">Sample matches</div><div class="form-pills">${pills}</div></div>` : ''}
  `;
}

function renderFooter() {
  const totalMatches = ROWS.length;
  let minY = Infinity, maxY = -Infinity;
  for (const m of ROWS) {
    const y = Number(formatDate(m.date));
    if (Number.isFinite(y)) {
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
  const range = (Number.isFinite(minY) && Number.isFinite(maxY))
    ? `${minY}&ndash;${maxY} &middot; ` : '';
  // TS caps custom-chart payloads at 20k rows by default. If we hit it exactly,
  // surface the truncation rather than pretending it's the full total.
  const capped = totalMatches >= 20000;
  const countLabel = capped
    ? `${totalMatches.toLocaleString()}+ matches (capped by TS)`
    : `${totalMatches.toLocaleString()} matches`;
  document.getElementById('footer').innerHTML =
    `${countLabel} &middot; ${range}all tournaments`;
}

// Registered dropdown re-render callbacks; refreshDropdowns() re-runs them all
// (each with its current search text) so filter/selection changes update both lists.
const renderers = [];
function refreshDropdowns() { renderers.forEach(fn => fn()); }

function buildDropdown(ddId, inputId, searchId, listId, myIdx) {
  const dd     = document.getElementById(ddId);
  const input  = document.getElementById(inputId);
  const search = document.getElementById(searchId);
  const list   = document.getElementById(listId);
  const wrapId = 'wrap' + (myIdx + 1);
  const otherId = myIdx === 0 ? 'dd2' : 'dd1';
  const otherIdx = myIdx === 0 ? 1 : 0;

  function renderList(filterText) {
    list.innerHTML = '';
    const f = filterText.toLowerCase();
    // Follow the active filter: only teams present under it. Grey (not remove)
    // teams the other selected team has never played under that filter.
    const present = teamsUnderFilter(activeFilter);
    const anchor  = selected[otherIdx];
    const faced   = anchor ? opponentsOf(anchor, activeFilter) : null;

    TEAMS.filter(t => t.toLowerCase().includes(f) && present.has(t)).forEach(t => {
      const disabled = !!faced && !faced.has(t); // includes anchor itself → can't pick same team
      const div = document.createElement('div');
      div.className = disabled ? 'dropdown-item disabled' : 'dropdown-item';
      div.innerHTML = `<span class="dd-flag">${flag(t)}</span><span>${t}</span>`;
      if (!disabled) {
        div.addEventListener('mousedown', e => {
          e.preventDefault();
          selected[myIdx] = t;
          input.value = t;
          dd.classList.remove('open');
          search.value = '';
          renderList('');
          refreshDropdowns();   // update the opposite list's grey-out
          renderScoreboard();
        });
      }
      list.appendChild(div);
    });
  }

  renderers.push(() => renderList(search.value));
  renderList('');

  input.addEventListener('click', () => {
    dd.classList.toggle('open');
    document.getElementById(otherId).classList.remove('open');
    if (dd.classList.contains('open')) setTimeout(() => search.focus(), 50);
  });

  search.addEventListener('input', () => renderList(search.value));
  search.addEventListener('keydown', e => {
    if (e.key === 'Escape') { dd.classList.remove('open'); search.value = ''; renderList(''); }
  });

  document.addEventListener('click', e => {
    if (!document.getElementById(wrapId).contains(e.target)) {
      dd.classList.remove('open');
      search.value = '';
      renderList('');
    }
  });
}

buildDropdown('dd1', 'input1', 'search1', 'list1', 0);
buildDropdown('dd2', 'input2', 'search2', 'list2', 1);

document.querySelectorAll('.filter-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    refreshDropdowns();   // re-apply present/grey-out under the new filter
    renderScoreboard();
  });
});

// ── Initial state: prefer the configured defaults if present in the data ──
const initialT1 = TEAMS.includes(DEFAULT_TEAM_1) ? DEFAULT_TEAM_1 : TEAMS[0] ?? null;
const initialT2 = TEAMS.includes(DEFAULT_TEAM_2) ? DEFAULT_TEAM_2 : TEAMS[1] ?? null;
selected = [initialT1, initialT2];
if (initialT1) document.getElementById('input1').value = initialT1;
if (initialT2) document.getElementById('input2').value = initialT2;

renderFooter();
renderScoreboard();

// ── Signal TS render-complete (no-op when not in TS) ──
try { viz.events.emitRenderCompletedEvent(); } catch {}
