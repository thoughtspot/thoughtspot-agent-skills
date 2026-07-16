"""TWB → TML migration fidelity verifier.

Backs ``ts tableau verify <file> <dir>``. Parses a Tableau workbook (via the
canonical :func:`ts_cli.commands.tableau.parse_twb`) and the generated TML
output directory, then diffs them across four dimensions:

  1. Structural completeness — datasources/models, physical tables, custom-SQL
     relations → sql_views, joins, formulas all accounted for.
  2. Formula equivalence — per-datasource, token-level comparison of each raw
     Tableau formula against its ThoughtSpot TML translation (LCS similarity).
  3. TML validity — YAML parse, required fields, banned functions, join enums.
  4. Limitation coverage — untranslatable formulas detected vs documented.

This catches silent drops and structural-fidelity gaps that a server-side
VALIDATE_ONLY import cannot (an import gate sees only what was emitted; it
cannot know what the TWB contained and the migration dropped).

Pure functions only — no network, no live ThoughtSpot connection. The TWB side
reuses the canonical parser so `verify` and `parse` never diverge.
"""

from __future__ import annotations

import html
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Constants — untranslatable patterns run against the RAW Tableau formula
# ---------------------------------------------------------------------------

# Genuinely no ThoughtSpot equivalent — these are always omitted.
UNTRANSLATABLE_PATTERNS = [
    (re.compile(r'\bLOOKUP\s*\(', re.I), 'LOOKUP table calculation (no TS equivalent)'),
    (re.compile(r'\bINDEX\s*\(\s*\)', re.I), 'INDEX table calculation (no TS equivalent)'),
    (re.compile(r'\bFIRST\s*\(\s*\)', re.I), 'FIRST table calculation (no TS equivalent)'),
    (re.compile(r'\bLAST\s*\(\s*\)', re.I), 'LAST table calculation (no TS equivalent)'),
    (re.compile(r'\bSIZE\s*\(\s*\)', re.I), 'SIZE table calculation (no TS equivalent)'),
    (re.compile(r'\bPREVIOUS_VALUE\s*\(', re.I), 'PREVIOUS_VALUE (no TS equivalent)'),
    (re.compile(r'\bSCRIPT_\w+\s*\(', re.I), 'External SCRIPT_ call (no TS equivalent)'),
    (re.compile(r'\bRAWSQL\w*\s*\(', re.I), 'RAWSQL passthrough (no TS equivalent)'),
    (re.compile(r'\bISMEMBEROF\s*\(', re.I), 'ISMEMBEROF (no TS equivalent)'),
    (re.compile(r'\bDATENAME\s*\(', re.I), 'DATENAME (only the weekday variant maps; review)'),
    (re.compile(r'\[(?!Parameters\])[^\]]+\]\.\[[^\]]+\]'), 'Cross-datasource reference (no TS equivalent — TS cannot reference columns from other models)'),
]

# Translatable, but ThoughtSpot's equivalents (cumulative_*, moving_*, rank,
# group_aggregate) are QUERY-TIME functions — valid in an answer/Spotter, NOT
# storable in model.formulas. So these are EXPECTED to be absent from the model
# TML; their omission is correct, not a silent drop. (Per the TS formula
# reference and tableau-formula-translation.md.)
QUERY_TIME_PATTERNS = [
    (re.compile(r'\bWINDOW_(SUM|AVG|MAX|MIN|COUNT|MEDIAN|PERCENTILE|STDEV|VAR)\s*\(', re.I),
     'WINDOW_* → moving_* (query-time; lives in the answer, not the model)'),
    (re.compile(r'\bRUNNING_(SUM|AVG|COUNT|MAX|MIN)\s*\(', re.I),
     'RUNNING_* → cumulative_* (query-time; lives in the answer, not the model)'),
    (re.compile(r'\bRANK(_DENSE|_MODIFIED|_PERCENTILE|_UNIQUE)?\s*\(', re.I),
     'RANK → rank/rank_percentile (query-time; lives in the answer, not the model)'),
    (re.compile(r'\bTOTAL\s*\(', re.I),
     'TOTAL → group_aggregate(...query_filters()) (query-time/percent-of-total)'),
]

# LOD expressions are translatable (→ group_aggregate) but flagged for review.
LOD_PATTERN = re.compile(r'\{\s*(FIXED|INCLUDE|EXCLUDE)\b', re.I)

BANNED_TS_FUNCTIONS = {'trim', 'split', 'split_part', 'replace', 'upper', 'lower',
                       'ltrim', 'rtrim', 'reverse', 'repeat', 'lpad', 'rpad', 'translate'}

VALID_TS_DATA_TYPES = {'VARCHAR', 'INT64', 'DOUBLE', 'FLOAT', 'BOOL', 'DATE',
                       'DATETIME', 'TIME', 'BIGINT'}
VALID_JOIN_TYPES = {'INNER', 'LEFT_OUTER', 'RIGHT_OUTER', 'OUTER', 'FULL_OUTER'}
VALID_CARDINALITIES = {'ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_ONE', 'MANY_TO_MANY'}

# Tableau function/keyword → ThoughtSpot, used only to normalize the RAW
# Tableau formula for token comparison (mirrors the parser's translation map).
TABLEAU_TO_TS_FUNCTIONS: dict[str, str] = {
    'elseif': 'else if', 'end': '',
    'datediff': 'diff', 'datetrunc': 'date', 'dateadd': 'add',
    'today': 'today', 'now': 'now',
    'countd': 'unique_count', 'count': 'count', 'sum': 'sum',
    'avg': 'average', 'min': 'min', 'max': 'max',
    'zn': 'ifnull', 'ifnull': 'ifnull', 'isnull': 'isnull',
    'abs': 'abs', 'ceil': 'ceil', 'floor': 'floor', 'round': 'round',
    'len': 'strlen', 'datename': 'day_of_week',
}


# ---------------------------------------------------------------------------
# Data classes (TML side only — TWB side stays as the canonical parser dict)
# ---------------------------------------------------------------------------

@dataclass
class TMLFormula:
    id: str
    name: str
    expr: str


@dataclass
class TMLModel:
    name: str
    tables: list[str] = field(default_factory=list)
    formulas: list[TMLFormula] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    joins: list[dict] = field(default_factory=list)
    obj_id: str = ''


@dataclass
class TMLTable:
    name: str
    db: str = ''
    schema: str = ''
    columns: list[dict] = field(default_factory=list)


@dataclass
class TMLSqlView:
    name: str
    sql_query: str = ''
    columns: list[dict] = field(default_factory=list)


@dataclass
class Issue:
    category: str
    severity: str  # ERROR, WARNING, INFO
    message: str


# ---------------------------------------------------------------------------
# TML parsing
# ---------------------------------------------------------------------------

def parse_model_tml(path: str) -> TMLModel:
    data = yaml.safe_load(open(path)) or {}
    m = data.get('model', data) or {}
    model = TMLModel(name=str(m.get('name', '')), obj_id=str(data.get('obj_id', '')))
    for mt in m.get('model_tables', []) or []:
        if mt.get('name'):
            model.tables.append(mt['name'])
        for j in mt.get('joins', []) or []:
            model.joins.append({
                'with': j.get('with', ''),
                'on': j.get('on', ''),
                'type': j.get('type', ''),
                'cardinality': j.get('cardinality', ''),
            })
    for f in m.get('formulas', []) or []:
        model.formulas.append(TMLFormula(
            id=str(f.get('id', '')), name=str(f.get('name', '')),
            expr=str(f.get('expr', '')),
        ))
    model.columns = list(m.get('columns', []) or [])
    return model


def parse_table_tml(path: str) -> TMLTable:
    data = yaml.safe_load(open(path)) or {}
    t = data.get('table', data) or {}
    return TMLTable(
        name=str(t.get('name', '')), db=str(t.get('db', '')),
        schema=str(t.get('schema', '')), columns=list(t.get('columns', []) or []),
    )


def parse_sql_view_tml(path: str) -> TMLSqlView:
    data = yaml.safe_load(open(path)) or {}
    sv = data.get('sql_view', data) or {}
    sql = ''
    # sql_query may be a top-level string or a list of statement fragments
    q = sv.get('sql_query', '')
    if isinstance(q, list):
        sql = '\n'.join(str(x) for x in q)
    else:
        sql = str(q)
    return TMLSqlView(
        name=str(sv.get('name', '')), sql_query=sql,
        columns=list(sv.get('columns', []) or []),
    )


def load_tml_dir(tml_dir: str):
    """Load every *.tml in a directory, bucketed by object type."""
    models: list[TMLModel] = []
    tables: list[TMLTable] = []
    sql_views: list[TMLSqlView] = []
    bad_yaml: list[Issue] = []
    for f in sorted(Path(tml_dir).glob('*.tml')):
        try:
            if f.name.endswith('.model.tml'):
                models.append(parse_model_tml(str(f)))
            elif f.name.endswith('.table.tml'):
                tables.append(parse_table_tml(str(f)))
            elif f.name.endswith('.sql_view.tml'):
                sql_views.append(parse_sql_view_tml(str(f)))
        except yaml.YAMLError as e:
            bad_yaml.append(Issue('VALIDITY', 'ERROR', f'YAML parse error in {f.name}: {e}'))
    return models, tables, sql_views, bad_yaml


# ---------------------------------------------------------------------------
# TWB helpers (operate on the canonical parse_twb dict)
# ---------------------------------------------------------------------------

def _non_param(parsed: dict) -> list[dict]:
    return [d for d in parsed.get('datasources', []) if not d.get('is_parameters')]


def is_untranslatable(raw_formula: str) -> tuple[bool, str]:
    """RAW Tableau formula with NO ThoughtSpot equivalent. (untranslatable, reason)."""
    for pat, reason in UNTRANSLATABLE_PATTERNS:
        if pat.search(raw_formula):
            return True, reason
    return False, ''


def is_query_time(raw_formula: str) -> tuple[bool, str]:
    """RAW Tableau formula whose TS equivalent is query-time only (answer/Spotter
    level), so it is expected to be absent from model.formulas. (query_time, reason)."""
    for pat, reason in QUERY_TIME_PATTERNS:
        if pat.search(raw_formula):
            return True, reason
    return False, ''


def classify(raw_formula: str) -> tuple[str, str]:
    """Return ('untranslatable'|'query_time'|'translatable', reason).

    Untranslatable is checked first (LOOKUP etc. win over any aggregate inside);
    then query-time (WINDOW_/RUNNING_/RANK/TOTAL); else translatable.
    """
    un, r = is_untranslatable(raw_formula)
    if un:
        return 'untranslatable', r
    qt, r = is_query_time(raw_formula)
    if qt:
        return 'query_time', r
    return 'translatable', ''


def is_lod(raw_formula: str) -> bool:
    return bool(LOD_PATTERN.search(raw_formula))


def _real_physical_tables(ds: dict) -> list[str]:
    """Real physical table names for a datasource — excludes extract snapshots,
    sqlproxy, and custom-SQL relations (those become sql_views)."""
    out = []
    for t in ds.get('tables', []):
        if t.get('sql_query'):
            continue  # custom SQL → sql_view, not a physical table
        phys = t.get('physical_table') or ''
        if not phys or phys.startswith('[Extract]') or phys == '[sqlproxy]':
            continue
        name = phys.strip('[]').split('].[')[-1]
        if name:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Formula normalization & comparison
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""\[[^\]]+\] | '(?:[^'\\]|\\.)*' | "(?:[^"\\]|\\.)*" | \d+\.?\d* |
        [a-zA-Z_]\w* | [<>=!]+ | [(),+\-*/] | \S""",
    re.VERBOSE,
)


def _tokenize(expr: str) -> list[str]:
    return _TOKEN_RE.findall(expr)


# ThoughtSpot writes some multi-word function names with spaces in the formula
# editor (`unique count`, `group aggregate`) while the docs spell them with
# underscores (`unique_count`, `group_aggregate`). Collapse the space form to the
# underscore form on BOTH token streams so similarity is independent of which
# spelling the migration emitted.
_SPACED_FUNCS = {
    ('unique', 'count'): 'unique_count',
    ('group', 'aggregate'): 'group_aggregate',
    ('cumulative', 'sum'): 'cumulative_sum',
    ('cumulative', 'average'): 'cumulative_average',
    ('moving', 'sum'): 'moving_sum',
    ('moving', 'average'): 'moving_average',
}


def _canonicalize_funcs(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        pair = (tokens[i].lower(), tokens[i + 1].lower()) if i + 1 < len(tokens) else None
        if pair in _SPACED_FUNCS:
            out.append(_SPACED_FUNCS[pair])
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def _strip_col_ref(ref: str) -> str:
    inner = ref[1:-1]
    if inner.lower().startswith('formula_'):
        return f'[formula::{inner[8:].strip().lower()}]'
    if '::' in inner:
        return f'[{inner.split("::", 1)[1].strip().lower()}]'
    return f'[{inner.strip().lower()}]'


def _norm_literal(tok: str) -> str:
    inner = tok[1:-1]
    try:
        float(inner)
        return inner
    except ValueError:
        return tok.lower()


def normalize_tableau_formula(raw: str, calc_id_to_caption: Optional[dict] = None) -> list[str]:
    f = re.sub(r'//[^\n]*', '', html.unescape(raw)).strip()
    out: list[str] = []
    for tok in _tokenize(f):
        low = tok.lower()
        if low == 'end':
            continue
        if low == 'elseif':
            out.extend(['else', 'if'])
            continue
        if low in TABLEAU_TO_TS_FUNCTIONS:
            mapped = TABLEAU_TO_TS_FUNCTIONS[low]
            if mapped:
                out.extend(mapped.split())
            continue
        if tok.startswith('[') and tok.endswith(']'):
            inner = tok[1:-1]
            if calc_id_to_caption and inner in calc_id_to_caption:
                out.append(f'[formula::{calc_id_to_caption[inner].strip().lower()}]')
            else:
                out.append(_strip_col_ref(tok))
            continue
        if tok[:1] in "'\"":
            out.append(_norm_literal(tok))
            continue
        out.append(low)
    return _canonicalize_funcs(out)


def normalize_ts_formula(expr: str) -> list[str]:
    out: list[str] = []
    for tok in _tokenize(expr):
        if tok.startswith('[') and tok.endswith(']'):
            out.append(_strip_col_ref(tok))
        elif tok[:1] in "'\"":
            out.append(_norm_literal(tok))
        else:
            out.append(tok.lower())
    return _canonicalize_funcs(out)


def formula_similarity(a: list[str], b: list[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    if m > 500 or n > 500:  # LCS too costly — fall back to Jaccard
        sa, sb = set(a), set(b)
        return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if a[i - 1] == b[j - 1] else max(dp[i - 1][j], dp[i][j - 1])
    return (2.0 * dp[m][n]) / (m + n)


# ---------------------------------------------------------------------------
# Datasource ↔ model matching
# ---------------------------------------------------------------------------

def _normalize_name(s: str) -> str:
    """Collapse punctuation and whitespace for fuzzy name matching."""
    return re.sub(r'[\s/\\._-]+', ' ', s).strip().lower()


def match_ds_to_model(parsed: dict, models: list[TMLModel]) -> dict[str, Optional[TMLModel]]:
    by_name = {m.name.strip().lower(): m for m in models}
    by_name_norm = {_normalize_name(m.name): m for m in models}
    by_table = {}
    for m in models:
        for t in m.tables:
            by_table.setdefault(t.strip().lower(), m)

    by_obj_prefix: dict[str, TMLModel] = {}
    for m in models:
        if m.obj_id:
            prefix = re.sub(r'-[a-f0-9]{8}$', '', m.obj_id).strip().lower()
            if prefix:
                by_obj_prefix[prefix] = m

    result: dict[str, Optional[TMLModel]] = {}
    for ds in _non_param(parsed):
        cap = ds.get('caption', '')
        m = by_name.get(cap.strip().lower())
        if m is None:
            m = by_name_norm.get(_normalize_name(cap))
        if m is None:
            m = by_table.get(cap.strip().lower())
        if m is None:
            cand = [t.get('relation_name', '') for t in ds.get('tables', [])]
            cand += _real_physical_tables(ds)
            for c in cand:
                if c and c.strip().lower() in by_table:
                    m = by_table[c.strip().lower()]
                    break
        if m is None and by_obj_prefix:
            cap_clean = re.sub(r'\s*\([^)]*\)\s*$', '', cap).strip().lower()
            m = by_obj_prefix.get(cap_clean)
            if m is None:
                for prefix, candidate in by_obj_prefix.items():
                    if cap_clean.startswith(prefix) or prefix.startswith(cap_clean):
                        m = candidate
                        break
        result[cap] = m
    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_structural(parsed, models, tables, sql_views, ds_map):
    issues: list[Issue] = []
    stats: dict = {}
    nds = _non_param(parsed)

    stats['datasources_in_twb'] = len(nds)
    stats['models_generated'] = len(models)
    for ds in nds:
        if ds_map.get(ds.get('caption')) is None:
            issues.append(Issue('STRUCTURAL', 'ERROR',
                                f'Datasource "{ds.get("caption")}" has no matching model TML'))

    # physical tables (real) vs table TMLs
    twb_tables = set()
    for ds in nds:
        twb_tables.update(_real_physical_tables(ds))
    tml_tables = {t.name for t in tables}
    stats['tables_in_twb'] = len(twb_tables)
    stats['tables_generated'] = len(tables)
    for mt in sorted(twb_tables - {t.lower() for t in tml_tables} - tml_tables):
        if not any(mt.lower() == t.lower() for t in tml_tables):
            issues.append(Issue('STRUCTURAL', 'WARNING',
                                f'Physical table "{mt}" in TWB has no .table.tml'))

    # custom-SQL relations vs sql_view TMLs
    twb_sql = sum(len(ds.get('custom_sql_sources', [])) for ds in nds)
    stats['custom_sql_in_twb'] = twb_sql
    stats['sql_views_generated'] = len(sql_views)
    if len(sql_views) < twb_sql:
        issues.append(Issue('STRUCTURAL', 'WARNING',
                            f'{twb_sql - len(sql_views)} custom-SQL relation(s) in TWB '
                            f'have no .sql_view.tml'))

    # joins
    twb_joins = sum(len(ds.get('joins', [])) for ds in nds)
    tml_joins = sum(len(m.joins) for m in models)
    stats['joins_in_twb'] = twb_joins
    stats['joins_in_tml'] = tml_joins
    if tml_joins < twb_joins:
        issues.append(Issue('STRUCTURAL', 'WARNING',
                            f'{twb_joins - tml_joins} join(s) in TWB not represented in TML'))

    # formulas — three-way split on the RAW formula. Query-time formulas
    # (WINDOW_/RUNNING_/RANK/TOTAL) are translatable but belong at the answer
    # level, so they are EXPECTED to be absent from the model and must not count
    # toward the silent-drop check.
    transl = untransl = query_time = 0
    for ds in nds:
        for cf in ds.get('calculated_fields', []):
            kind, _ = classify(cf.get('formula_raw', cf.get('formula', '')))
            if kind == 'untranslatable':
                untransl += 1
            elif kind == 'query_time':
                query_time += 1
            else:
                transl += 1
    tml_formulas = sum(len(m.formulas) for m in models)
    stats['total_calculated_fields_twb'] = transl + untransl + query_time
    stats['translatable_calculated_fields'] = transl
    stats['untranslatable_calculated_fields'] = untransl
    stats['query_time_calculated_fields'] = query_time
    stats['formulas_in_tml'] = tml_formulas
    if tml_formulas < transl:
        issues.append(Issue('STRUCTURAL', 'WARNING',
                            f'{transl - tml_formulas} translatable formula(s) not found in TML '
                            f'(possible silent drop)'))
    return stats, issues


def check_formula_equivalence(parsed, models, ds_map):
    issues: list[Issue] = []
    comparisons: list[dict] = []
    for ds in _non_param(parsed):
        cap = ds.get('caption', '')
        model = ds_map.get(cap)
        mf = {f.name.strip().lower(): f for f in model.formulas} if model else {}
        id2cap = {cf['internal_name']: cf['caption']
                  for cf in ds.get('calculated_fields', [])
                  if cf.get('internal_name') and cf.get('caption')}

        for cf in ds.get('calculated_fields', []):
            name = cf.get('caption', '')
            raw = cf.get('formula_raw', cf.get('formula', ''))
            kind, reason = classify(raw)
            if kind == 'untranslatable':
                comparisons.append({'datasource': cap, 'name': name, 'tableau': raw,
                                    'ts': None, 'status': 'SKIPPED (untranslatable)',
                                    'reason': reason, 'similarity': None})
                continue
            if kind == 'query_time':
                comparisons.append({'datasource': cap, 'name': name, 'tableau': raw,
                                    'ts': None, 'status': 'SKIPPED (query-time)',
                                    'reason': reason, 'similarity': None})
                continue
            if model is None:
                comparisons.append({'datasource': cap, 'name': name, 'tableau': raw,
                                    'ts': None, 'status': 'MISSING',
                                    'reason': f'No model TML for "{cap}"', 'similarity': 0.0})
                continue
            tf = mf.get(name.strip().lower())
            if tf is None:
                comparisons.append({'datasource': cap, 'name': name, 'tableau': raw,
                                    'ts': None, 'status': 'MISSING',
                                    'reason': f'Not found in model "{model.name}"', 'similarity': 0.0})
                issues.append(Issue('FORMULA', 'WARNING',
                                    f'Translatable formula "{name}" [{cap}] not found in '
                                    f'model "{model.name}" (silent drop)'))
                continue
            sim = formula_similarity(normalize_tableau_formula(raw, id2cap),
                                     normalize_ts_formula(tf.expr))
            if sim >= 0.85:
                status = 'MATCH'
            elif sim >= 0.5:
                status = 'PARTIAL'
                issues.append(Issue('FORMULA', 'WARNING',
                                    f'Formula "{name}" [{cap}] partial match ({sim:.0%}) — review'))
            else:
                status = 'LOW'
                issues.append(Issue('FORMULA', 'WARNING',
                                    f'Formula "{name}" [{cap}] low similarity ({sim:.0%}) — '
                                    f'likely mistranslated'))
            comparisons.append({'datasource': cap, 'name': name, 'tableau': raw,
                                'ts': tf.expr, 'status': status, 'reason': '', 'similarity': sim})
    return comparisons, issues


def _strip_sql_ops(expr: str) -> str:
    """Remove sql_*_op(...) calls (balanced parens) so banned-function
    checks don't false-positive on SQL inside pass-through templates."""
    result: list[str] = []
    i = 0
    while i < len(expr):
        m = re.search(r'\bsql_\w+_(?:op|aggregate_op)\s*\(', expr[i:], re.I)
        if not m:
            result.append(expr[i:])
            break
        result.append(expr[i:i + m.start()])
        depth = 1
        j = i + m.end()
        while j < len(expr) and depth > 0:
            if expr[j] == '(':
                depth += 1
            elif expr[j] == ')':
                depth -= 1
            j += 1
        i = j
    return ''.join(result)


def check_validity(models, tables, sql_views):
    issues: list[Issue] = []
    for tt in tables:
        if not tt.db:
            issues.append(Issue('VALIDITY', 'ERROR', f'Table "{tt.name}": missing "db"'))
        if not tt.schema:
            issues.append(Issue('VALIDITY', 'ERROR', f'Table "{tt.name}": missing "schema"'))
        for col in tt.columns:
            cn = col.get('name', '???')
            if 'db_column_name' not in col:
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Table "{tt.name}", column "{cn}": missing db_column_name'))
            dt = (col.get('db_column_properties', {}) or {}).get('data_type', '') or col.get('data_type', '')
            if dt == 'INT':
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Table "{tt.name}", column "{cn}": data_type "INT" must be "INT64"'))
            elif dt and dt not in VALID_TS_DATA_TYPES:
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Table "{tt.name}", column "{cn}": invalid data_type "{dt}"'))
    for sv in sql_views:
        if not sv.sql_query.strip():
            issues.append(Issue('VALIDITY', 'ERROR', f'SQL view "{sv.name}": empty sql_query'))
        if re.search(r'>>=|<<=|==', sv.sql_query):
            issues.append(Issue('VALIDITY', 'WARNING',
                                f'SQL view "{sv.name}": unescaped XML artifact (>>=/<<=/==) in SQL'))
    for m in models:
        seen: set[str] = set()
        for c in m.columns:
            cn = str(c.get('name', '')).lower()
            if cn in seen:
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Model "{m.name}": duplicate column "{cn}"'))
            seen.add(cn)
        for f in m.formulas:
            expr_no_passthrough = _strip_sql_ops(f.expr)
            for banned in BANNED_TS_FUNCTIONS:
                if re.search(rf'\b{re.escape(banned)}\s*\(', expr_no_passthrough, re.I):
                    issues.append(Issue('VALIDITY', 'ERROR',
                                        f'Model "{m.name}", formula "{f.name}": '
                                        f'unsupported function "{banned}()"'))
        for j in m.joins:
            if j['type'] and j['type'] not in VALID_JOIN_TYPES:
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Model "{m.name}": invalid join type "{j["type"]}"'))
            if j['cardinality'] and j['cardinality'] not in VALID_CARDINALITIES:
                issues.append(Issue('VALIDITY', 'ERROR',
                                    f'Model "{m.name}": invalid cardinality "{j["cardinality"]}"'))
    return issues


def check_limitation_coverage(parsed, tml_dir):
    issues: list[Issue] = []
    stats: dict = {}
    nds = _non_param(parsed)
    detected = []
    for ds in nds:
        for cf in ds.get('calculated_fields', []):
            un, reason = is_untranslatable(cf.get('formula_raw', cf.get('formula', '')))
            if un:
                detected.append({'datasource': ds.get('caption'), 'name': cf.get('caption'),
                                 'formula': cf.get('formula_raw', ''), 'reason': reason})
    stats['untranslatable_detected'] = len(detected)

    # Accept any of the conventional doc filenames.
    doc_text = ''
    for fn in ('MIGRATION_LIMITATIONS.md', 'MIGRATION_REPORT.md', 'MIGRATION_ACCURACY_REPORT.md'):
        p = os.path.join(tml_dir, fn)
        if os.path.exists(p):
            doc_text += '\n' + open(p).read().lower()
    documented = set()
    if doc_text:
        for item in detected:
            if (item['name'] or '').lower() in doc_text or item['formula'][:50].lower() in doc_text:
                documented.add(item['name'])
    else:
        issues.append(Issue('COVERAGE', 'WARNING',
                            'No migration limitations/report doc found in output directory'))
    stats['untranslatable_documented'] = len(documented)
    for item in detected:
        if item['name'] not in documented:
            issues.append(Issue('COVERAGE', 'ERROR',
                                f'Untranslatable formula "{item["name"]}" [{item["datasource"]}] '
                                f'not documented. Reason: {item["reason"]}'))
    return stats, detected, issues


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _bar(num, den):
    return f'{num}/{den}  ({num / den * 100:.0f}%)' if den else f'{num}/{den}  (N/A)'


def generate_report(twb_path, tml_dir, s_stats, s_iss, comps, f_iss,
                    v_iss, c_stats, c_iss, verbose=False):
    all_iss = s_iss + f_iss + v_iss + c_iss
    errors = [i for i in all_iss if i.severity == 'ERROR']
    warnings = [i for i in all_iss if i.severity == 'WARNING']
    L: list[str] = []
    w = L.append

    w(f'Migration Fidelity Report: {os.path.basename(twb_path)}')
    w('=' * 70)
    w('')
    w('1. STRUCTURAL COMPLETENESS')
    w('-' * 40)
    w(f'   Datasources → models:  {_bar(s_stats["models_generated"], s_stats["datasources_in_twb"])}')
    w(f'   Physical tables:       {_bar(s_stats["tables_generated"], s_stats["tables_in_twb"])}')
    w(f'   Custom SQL → sql_view: {_bar(s_stats["sql_views_generated"], s_stats["custom_sql_in_twb"])}')
    w(f'   Joins:                 {_bar(s_stats["joins_in_tml"], s_stats["joins_in_twb"])}')
    w(f'   Formulas (translatable): {_bar(s_stats["formulas_in_tml"], s_stats["translatable_calculated_fields"])}')
    w(f'   Skipped (untranslatable): {s_stats["untranslatable_calculated_fields"]}')
    w(f'   Skipped (query-time, answer-level): {s_stats.get("query_time_calculated_fields", 0)}')
    for i in s_iss:
        w(f'     [{i.severity}] {i.message}')
    w('')

    w('2. FORMULA EQUIVALENCE (token-level)')
    w('-' * 40)
    matched = [c for c in comps if c['status'] == 'MATCH']
    partial = [c for c in comps if c['status'] == 'PARTIAL']
    low = [c for c in comps if c['status'] == 'LOW']
    missing = [c for c in comps if c['status'] == 'MISSING']
    skipped_un = [c for c in comps if c['status'] == 'SKIPPED (untranslatable)']
    skipped_qt = [c for c in comps if c['status'] == 'SKIPPED (query-time)']
    tot = len(matched) + len(partial) + len(low)
    w(f'   High confidence (>=85%): {len(matched)}/{tot}')
    w(f'   Partial (50-84%):        {len(partial)}/{tot}')
    w(f'   Low (<50%):              {len(low)}/{tot}')
    w(f'   Missing from TML:        {len(missing)}')
    w(f'   Skipped (untranslatable):{len(skipped_un)}')
    w(f'   Skipped (query-time):    {len(skipped_qt)}')
    if partial or low or missing:
        w('')
        w('   Flagged:')
        for c in partial + low + missing:
            sim = f'{c["similarity"]:.0%}' if c['similarity'] is not None else 'N/A'
            w(f'     - "{c["name"]}" [{c["datasource"]}] {c["status"]} sim={sim}'
              + (f' — {c["reason"]}' if c.get('reason') else ''))
    w('')

    w('3. TML VALIDITY')
    w('-' * 40)
    v_err = [i for i in v_iss if i.severity == 'ERROR']
    v_warn = [i for i in v_iss if i.severity == 'WARNING']
    if not v_iss:
        w('   All checks PASSED')
    else:
        w(f'   Errors: {len(v_err)}   Warnings: {len(v_warn)}')
        for i in v_err:
            w(f'     [ERROR]   {i.message}')
        for i in v_warn:
            w(f'     [WARNING] {i.message}')
    w('')

    w('4. LIMITATION COVERAGE')
    w('-' * 40)
    w(f'   Untranslatable detected:   {c_stats.get("untranslatable_detected", 0)}')
    w(f'   Untranslatable documented: {c_stats.get("untranslatable_documented", 0)}')
    if c_iss:
        for i in c_iss:
            w(f'     [{i.severity}] {i.message}')
    else:
        w('   All untranslatable formulas documented.')
    w('')

    w('=' * 70)
    w('OVERALL')
    w('-' * 40)
    tr = s_stats['translatable_calculated_fields']
    fm = s_stats['formulas_in_tml']
    w(f'   Formula coverage:    {fm}/{tr} translatable ({fm / tr * 100:.0f}%)' if tr
      else '   Formula coverage:    N/A')
    w(f'   High-confidence:     {len(matched)}/{tot}')
    w(f'   TML validity:        {"PASS" if not v_err else "FAIL"}')
    w(f'   Limitation coverage: {"PASS" if all(i.severity != "ERROR" for i in c_iss) else "FAIL"}')
    w(f'   Total errors:        {len(errors)}')
    w(f'   Total warnings:      {len(warnings)}')
    w('')
    if errors:
        w('ACTION REQUIRED: fix the errors above before importing into ThoughtSpot.')
    elif warnings:
        w('Review warnings — importable, but some translations need manual verification.')
    else:
        w('Migration looks clean. Proceed with ThoughtSpot import.')

    if verbose:
        w('')
        w('DETAILED FORMULA COMPARISON')
        w('=' * 70)
        by_ds = defaultdict(list)
        for c in comps:
            by_ds[c['datasource']].append(c)
        for ds_name, cs in by_ds.items():
            w('')
            w(f'Datasource: {ds_name}')
            w('-' * 50)
            for c in cs:
                sim = f'{c["similarity"]:.0%}' if c['similarity'] is not None else 'N/A'
                w(f'  {c["name"]}  [{c["status"]} sim={sim}]')
                w(f'    Tableau: {c["tableau"][:140]}')
                if c['ts']:
                    w(f'    TS:      {c["ts"][:140]}')
                if c.get('reason'):
                    w(f'    Note:    {c["reason"]}')
    return '\n'.join(L), len(errors)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_verify(twb_path: str, tml_dir: str, verbose: bool = False) -> tuple[str, int]:
    """Run all four checks. Returns (report_text, error_count)."""
    # Import here to avoid a circular import at module load.
    from ts_cli.commands.tableau_parse import parse_twb

    parsed = parse_twb(twb_path)
    models, tables, sql_views, bad_yaml = load_tml_dir(tml_dir)
    ds_map = match_ds_to_model(parsed, models)

    s_stats, s_iss = check_structural(parsed, models, tables, sql_views, ds_map)
    comps, f_iss = check_formula_equivalence(parsed, models, ds_map)
    v_iss = bad_yaml + check_validity(models, tables, sql_views)
    c_stats, _detected, c_iss = check_limitation_coverage(parsed, tml_dir)

    return generate_report(twb_path, tml_dir, s_stats, s_iss, comps, f_iss,
                           v_iss, c_stats, c_iss, verbose=verbose)
