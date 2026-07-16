"""ts tableau generate-tml — batch TML generation from parsed workbook (T3).

Reads parsed.json (from T1) and translated.json (from T2), generates all
Table, SQL View, and Model TMLs deterministically.  No LLM reasoning — the
generation is mechanical mapping from parsed data to YAML via TML schema rules.

Pure functions only — no network, no live ThoughtSpot connection.
"""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import yaml

from ts_cli.commands.tableau_postprocess import _to_upper_snake

# ---------------------------------------------------------------------------
# YAML: dump OrderedDict as plain mapping (no Python tags)
# ---------------------------------------------------------------------------

yaml.add_representer(
    OrderedDict,
    lambda dumper, data: dumper.represent_mapping(
        'tag:yaml.org,2002:map', data.items()),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    'string': 'VARCHAR',
    'integer': 'INT64',
    'real': 'DOUBLE',
    'date': 'DATE',
    'datetime': 'DATE_TIME',
    'boolean': 'BOOL',
    'float': 'DOUBLE',
}

_JOIN_TYPE_MAP = {
    'inner': 'INNER',
    'left': 'LEFT_OUTER',
    'right': 'RIGHT_OUTER',
    'full': 'OUTER',
}


def _ts_data_type(local_type: str) -> str:
    return _TYPE_MAP.get((local_type or '').lower(), 'VARCHAR')


def _is_measure(col: dict) -> bool:
    if col.get('role') == 'dimension':
        return False
    agg = col.get('aggregation', '')
    lt = (col.get('local_type', '') or '').lower()
    return agg in ('Sum', 'Avg') and lt in ('integer', 'real', 'float', 'double')


def _sanitize_formula_id(name: str) -> str:
    fid = re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_')
    if not fid or fid[0].isdigit():
        fid = 'f_' + fid
    return fid


def _load_table_map(path: str) -> dict:
    """Parse a table mapping file (Step 2.5 format).

    Each line: SOURCE : TARGET  or  SOURCE - TARGET
    Both sides are reduced to their last dot-segment (the table name) —
    ThoughtSpot column refs use ``[TableName::Column]``, not the full
    ``DB.SCHEMA.TABLE`` path.
    Returns {source_last_segment_upper: target_last_segment}.
    """
    mapping = {}
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            for sep in (':', '-'):
                if sep in line:
                    parts = line.split(sep, 1)
                    if len(parts) == 2:
                        src = parts[0].strip().split('.')[-1].strip()
                        tgt = parts[1].strip().split('.')[-1].strip()
                        if src and tgt:
                            mapping[src.upper()] = tgt
                    break
    return mapping


def _load_full_table_map(path: str) -> list[tuple[str, str]]:
    """Parse table mapping file preserving full qualified names for SQL rewriting.

    Returns ``[(full_source, full_target)]`` — used by ``_remap_sql_query``
    to rewrite table references inside SQL view queries.
    """
    pairs: list[tuple[str, str]] = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            for sep in (':', '-'):
                if sep in line:
                    parts = line.split(sep, 1)
                    if len(parts) == 2:
                        src = parts[0].strip()
                        tgt = parts[1].strip()
                        if src and tgt:
                            pairs.append((src, tgt))
                    break
    return pairs


_SQL_IDENT_RE = r'(?:"[^"]*"|\w+)'


def _remap_sql_query(
    sql: str,
    sql_table_map: list[tuple[str, str]],
) -> tuple[str, list[dict]]:
    """Rewrite table references in SQL and strip Tableau parameter refs.

    ``sql_table_map`` is ``[(full_source, full_target)]`` from the mapping
    file.  Matching is case-insensitive and handles both quoted and unquoted
    SQL identifiers.  A 2-part source (``SCHEMA.TABLE``) also matches a
    3-part reference (``DB.SCHEMA.TABLE``) — the optional leading qualifier
    is consumed so it doesn't dangle after replacement.

    Tableau parameter references ``<[Parameters].[Name]>`` are replaced
    with ``NULL`` — ThoughtSpot SQL views cannot be parameterised; the
    corresponding model parameters handle filtering at query time.
    """
    warnings: list[dict] = []

    sorted_map = sorted(sql_table_map, key=lambda p: len(p[0]), reverse=True)
    for src, tgt in sorted_map:
        src_parts = src.split('.')
        seg_pats = [rf'(?:"{re.escape(p)}"|{re.escape(p)})'
                    for p in src_parts]
        core = r'\s*\.\s*'.join(seg_pats)
        if len(src_parts) == 1:
            prefix = rf'(?:{_SQL_IDENT_RE}\s*\.\s*{_SQL_IDENT_RE}\s*\.\s*)?'
        elif len(src_parts) == 2:
            prefix = rf'(?:{_SQL_IDENT_RE}\s*\.\s*)?'
        else:
            prefix = ''
        new_sql, n = re.subn(prefix + core, tgt, sql, flags=re.IGNORECASE)
        if n:
            warnings.append({
                'type': 'table_remapped_in_sql',
                'source': src, 'target': tgt, 'count': n})
            sql = new_sql

    params = set(re.findall(r'<\[Parameters\]\.\[([^\]]+)\]>', sql))
    if params:
        sql = re.sub(r'<\[Parameters\]\.\[[^\]]+\]>', 'NULL', sql)
        for p in sorted(params):
            warnings.append({
                'type': 'param_removed_from_sql', 'parameter': p})

    return sql, warnings


def _norm_table_name(name: str) -> str:
    """Strip brackets and extract the last segment of a qualified name."""
    return name.strip('[]').split('].[')[-1].split('.')[-1]


_DISAMBIG_RE = re.compile(r'^(.*\S) \(([^()]+)\)$')


def _split_disambig(name: str) -> tuple[str, str]:
    """Split Tableau's collision-disambiguation suffix off a field name.

    When two sources share a column name, Tableau stores one of them as
    ``NAME (Source)`` — e.g. ``BRAND_NAME (TAB_POPULAR_CATEGORIES)``.
    Returns (base_name, source_hint); hint is '' when there is no suffix.
    """
    m = _DISAMBIG_RE.match(name or '')
    if m:
        return m.group(1), m.group(2)
    return name or '', ''


def _norm_key(name: str) -> str:
    """Normalize a table reference for cross-format matching.

    Collapses the differences between TWB relation names and generated
    TML object names ('Custom SQL Query1' vs 'Custom_SQL_Query1').
    """
    return _to_upper_snake(_norm_table_name(name or ''))


# ---------------------------------------------------------------------------
# Table TML builder
# ---------------------------------------------------------------------------

def _build_table_tml(
    table_name: str,
    columns: list[dict],
    connection: str,
    db: str,
    schema: str,
) -> OrderedDict:
    cols = []
    seen: set[str] = set()
    for c in columns:
        name = c.get('name', '')
        if not name or name in seen:
            continue
        seen.add(name)
        col = OrderedDict()
        col['name'] = name
        # Physical identifier must not carry Tableau's " (Source)" suffix
        col['db_column_name'] = _split_disambig(name)[0]
        col['properties'] = OrderedDict()
        col['properties']['column_type'] = 'MEASURE' if _is_measure(c) else 'ATTRIBUTE'
        col['properties']['index_type'] = 'DONT_INDEX'
        if _is_measure(c):
            agg = c.get('aggregation', 'SUM')
            col['properties']['aggregation'] = agg.upper()
        col['db_column_properties'] = OrderedDict()
        col['db_column_properties']['data_type'] = _ts_data_type(c.get('local_type', 'string'))
        cols.append(col)

    tml = OrderedDict()
    tml['table'] = OrderedDict()
    tml['table']['name'] = table_name
    tml['table']['db'] = db
    tml['table']['schema'] = schema
    tml['table']['db_table'] = table_name
    tml['table']['connection'] = OrderedDict([('name', connection)])
    tml['table']['columns'] = cols
    return tml


# ---------------------------------------------------------------------------
# SQL View TML builder
# ---------------------------------------------------------------------------

def _build_sql_view_tml(
    name: str,
    sql_query: str,
    columns: list[dict],
    connection: str,
) -> OrderedDict:
    view_cols = []
    seen: set[str] = set()
    for c in columns:
        col_name = c.get('name', '')
        if not col_name or col_name in seen:
            continue
        seen.add(col_name)
        vc = OrderedDict()
        vc['name'] = col_name
        # Must match the SQL's actual output column — never Tableau's
        # " (Source)" disambiguation label
        vc['sql_output_column'] = _split_disambig(col_name)[0]
        vc['data_type'] = _ts_data_type(c.get('local_type', 'string'))
        vc['properties'] = OrderedDict()
        vc['properties']['column_type'] = 'MEASURE' if _is_measure(c) else 'ATTRIBUTE'
        view_cols.append(vc)

    tml = OrderedDict()
    tml['sql_view'] = OrderedDict()
    tml['sql_view']['name'] = name
    tml['sql_view']['connection'] = OrderedDict([('name', connection)])
    tml['sql_view']['sql_query'] = sql_query
    tml['sql_view']['sql_view_columns'] = view_cols
    return tml


# ---------------------------------------------------------------------------
# Model TML builder
# ---------------------------------------------------------------------------

def _param_ts_type(datatype: str) -> str:
    return {
        'string': 'CHAR', 'integer': 'INT64', 'real': 'DOUBLE',
        'float': 'DOUBLE', 'date': 'DATE', 'boolean': 'BOOL',
    }.get((datatype or '').lower(), 'CHAR')


def _build_parameter(p: dict) -> OrderedDict:
    param = OrderedDict()
    param['name'] = p.get('caption', p.get('internal_name', ''))
    param['default_value'] = str(p.get('current_value', ''))
    param['data_type'] = _param_ts_type(p.get('datatype', 'string'))
    allowed = p.get('allowed_values', [])
    if allowed:
        vals = []
        for v in allowed:
            if isinstance(v, dict):
                vals.append(str(v.get('value', v)))
            else:
                vals.append(str(v))
        if vals:
            param['allowed_values'] = vals
    return param


def _find_param_refs(text: str, all_params: list[dict]) -> set[str]:
    refs: set[str] = set()
    for p in all_params:
        cap = p.get('caption', '')
        iname = p.get('internal_name', '')
        if cap and f'[{cap}]' in text:
            refs.add(cap)
        if iname and f'[{iname}]' in text:
            refs.add(cap or iname)
    for m in re.finditer(r'\[Parameters\]\.\[([^\]]+)\]', text):
        iname = m.group(1)
        for p in all_params:
            if p.get('internal_name') == iname or p.get('caption') == iname:
                refs.add(p.get('caption', iname))
    return refs


def _has_aggregate(expr: str) -> bool:
    return bool(re.search(
        r'\b(sum|average|unique\s+count|count|min|max|stddev|group_aggregate|cumulative_|moving_)\s*\(',
        expr, re.IGNORECASE))


def _invalid_decision_refs(expr: str, ds: dict, captions: list[str],
                           all_params: list[dict]) -> list[str]:
    """Return bracketed refs in a decision expr that match nothing in the model.

    Valid refs: physical column names, formula captions, sanitized formula
    ids (``formula_<id>``), and parameter captions. Table-qualified refs
    (``T::C``) are checked on the column part only.
    """
    known: set[str] = set()
    for c in ds.get('physical_columns', []):
        if c.get('name'):
            known.add(c['name'])
    for cap in captions:
        known.add(cap)
        known.add(f'formula_{_sanitize_formula_id(cap)}')
        known.add(f'formula_{cap}')
    for p in all_params or []:
        cap = p.get('caption') or p.get('internal_name')
        if cap:
            known.add(cap)

    bad = []
    for ref in re.findall(r'\[([^\]]+)\]', expr or ''):
        name = ref.split('::', 1)[1] if '::' in ref else ref
        if name not in known:
            bad.append(ref)
    return bad


def _humanize_shelf(shelf: str, formula_column_map: dict) -> str:
    """Render a TWB shelf expression readably for the decisions file.

    ``[federated.x].[usr:Calculation_137:qk:3]`` → ``usr(Date Axis)``;
    ``[federated.x].[none:PLATFORM:nk]`` → ``PLATFORM``.
    """
    def _one(m):
        agg, field = m.group(1), m.group(2)
        field = formula_column_map.get(field, field)
        return field if agg == 'none' else f'{agg}({field})'
    out = re.sub(r'\[([^:\[\]]+):([^:\[\]]+):[^\]]*\]', _one, shelf or '')
    return re.sub(r'\[[^\]]*\]\.', '', out).strip()


def _decision_context_for(cf: dict, formula_lookup: dict, calc_fields: list,
                          formula_column_map: dict, worksheets: list) -> dict:
    """Build the extra decision context for one unresolved formula:
    referenced sibling formulas' exprs, and the worksheets that use it."""
    raw = cf.get('formula_raw') or cf.get('formula') or ''
    caption_by_internal = {c.get('internal_name'): c.get('caption')
                          for c in calc_fields}
    referenced: dict = {}
    for ref in re.findall(r'\[([^\]]+)\]', raw):
        cap = formula_column_map.get(ref) or caption_by_internal.get(ref) \
            or (ref if any(c.get('caption') == ref for c in calc_fields) else None)
        if not cap or cap == cf.get('caption'):
            continue
        entries = formula_lookup.get(cap, [])
        if entries:
            referenced[cap] = entries[0].get('translated') or entries[0].get('original', '')

    internal = cf.get('internal_name', '')
    used_in = []
    for ws in worksheets or []:
        if internal and internal in ws.get('fields', []):
            used_in.append({
                'sheet': ws.get('name', ''),
                'rows': _humanize_shelf(ws.get('rows', ''), formula_column_map),
                'cols': _humanize_shelf(ws.get('cols', ''), formula_column_map),
            })
        if len(used_in) >= 3:
            break

    out: dict = {}
    if referenced:
        out['referenced_formulas'] = referenced
    if used_in:
        out['used_in_sheets'] = used_in
    return out


def _load_decisions(path: str) -> dict[str, dict]:
    """Load decisions.json → {caption: decision}. Format:
    {"decisions": [{"caption": ..., "action": "use_expr"|"skip",
                    "expr": ..., "column_type": ..., "aggregation": ...,
                    "reason": ..., "model": ...(optional, informational)}]}
    """
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    out: dict[str, dict] = {}
    for d in data.get('decisions', []):
        cap = d.get('caption', '')
        if cap:
            out[cap] = d
    return out


def _convert_on_clause(on_clause, left_table, right_table, resolve, display_col):
    """Rewrite a Tableau join on-clause into TML ``[Table::Column]`` refs.

    Handles the two forms the parser emits:
      classic:      ``[TableA].[col_a] = [TableB].[col_b]``
      object-graph: ``[col_a] = [col_b (Other Source)]`` — an unhinted ref
        belongs to the join side the hinted ref doesn't name.
    Unrecognized shapes are returned unchanged (validate will flag them).
    """
    qualified = re.findall(r'\[([^\]]+)\]\.\[([^\]]+)\]', on_clause)
    if len(qualified) == 2:
        defaults = [left_table, right_table]
        sides = []
        for i, (tref, cref) in enumerate(qualified):
            tbl = resolve(tref) or defaults[i]
            base = _split_disambig(cref)[0]
            sides.append(f'[{tbl}::{display_col(tbl, base)}]')
        return f'{sides[0]} = {sides[1]}'

    bare = re.findall(r'\[([^\]]+)\]', on_clause)
    if len(bare) == 2:
        (b0, h0), (b1, h1) = _split_disambig(bare[0]), _split_disambig(bare[1])
        t0 = resolve(h0) if h0 else None
        t1 = resolve(h1) if h1 else None
        if t0 is None and t1 is None:
            t0, t1 = left_table, right_table
        elif t0 is None:
            t0 = left_table if t1 == right_table else right_table
        elif t1 is None:
            t1 = right_table if t0 == left_table else left_table
        return (f'[{t0}::{display_col(t0, b0)}] = '
                f'[{t1}::{display_col(t1, b1)}]')

    return on_clause


def _build_model_tml(
    model_name: str,
    table_names: list[str],
    ds: dict,
    formula_lookup: dict[str, list[dict]],
    all_params: list[dict],
    joins: list[dict] | None = None,
    rename_map: dict[str, str] | None = None,
    table_columns: dict[str, list[dict]] | None = None,
    decisions: dict[str, dict] | None = None,
) -> tuple[OrderedDict, list[str], dict]:
    """Build a model TML.

    ``decisions`` maps formula caption → an LLM decision record
    ({action: use_expr|skip, expr, column_type, aggregation, reason}) from a
    ``decisions.json`` produced in Step 5.1. Decisions go through the same
    schema path as deterministic formulas; exprs with unknown refs are
    rejected into warnings rather than written.

    Returns (tml, omitted_formula_names, warnings) where warnings carries
    'dropped_joins', 'unassigned_columns', 'skipped_by_decision', and
    'invalid_decisions' — surfaced in the summary so failures are loud
    instead of silently guessed.
    """
    rename_map = rename_map or {}
    table_columns = table_columns or {}
    warnings: dict = {'dropped_joins': [], 'unassigned_columns': [],
                      'skipped_by_decision': [], 'invalid_decisions': []}

    def _resolve(name: str) -> Optional[str]:
        """Map a TWB-side table reference to a generated table name."""
        if not name:
            return None
        hit = rename_map.get(_norm_key(name))
        if hit:
            return hit
        for tname in table_names:
            if _norm_key(tname) == _norm_key(name):
                return tname
        return None

    def _display_col(table: str, base: str) -> str:
        """Generated display name for a base column name in a table."""
        for c in table_columns.get(table, []):
            if _split_disambig(c.get('name', ''))[0] == base:
                return c.get('name', base)
        return base

    # model_tables
    model_tables = []
    for tname in table_names:
        mt = OrderedDict()
        mt['name'] = tname
        model_tables.append(mt)

    # Inject joins — model_tables[].joins[] on the source (left) entry,
    # with/on/type/cardinality per the model TML schema
    mt_by_name = {mt['name']: mt for mt in model_tables}
    for j in (joins or []):
        lt = _resolve(j.get('left_table', ''))
        rt = _resolve(j.get('right_table', ''))
        on_clause = j.get('on_clause', '')
        jtype = _JOIN_TYPE_MAP.get(
            (j.get('join_type', 'left') or 'left').lower(), 'LEFT_OUTER')
        if not lt or not rt or lt == rt or not on_clause:
            warnings['dropped_joins'].append({
                'left_table': j.get('left_table', ''),
                'right_table': j.get('right_table', ''),
                'reason': ('missing on clause' if not on_clause
                           else 'unresolved table reference'),
            })
            continue
        on_str = _convert_on_clause(on_clause, lt, rt, _resolve, _display_col)
        mt_by_name[lt].setdefault('joins', []).append(OrderedDict([
            ('with', rt),
            ('on', on_str),
            ('type', jtype),
            ('cardinality', 'MANY_TO_ONE'),
        ]))

    # Formulas + formula columns
    formulas_list = []
    formula_columns = []
    omitted = []

    calc_fields = ds.get('calculated_fields', [])
    all_captions = [cf.get('caption', '') for cf in calc_fields if cf.get('caption')]

    def _sanitize_formula_refs(expr: str) -> str:
        """Align formula-to-formula refs with the sanitized formula ids.

        T2 emits refs as ``[formula_<caption>]`` (spaces preserved) while the
        generated ``id:`` is ``formula_<sanitized>`` — rewrite refs to match
        the id exactly, per the documented convention in tableau-tml-rules.md.
        """
        for c in all_captions:
            expr = expr.replace(
                f'[formula_{c}]', f'[formula_{_sanitize_formula_id(c)}]')
        return expr

    for cf in sorted(calc_fields, key=lambda c: c.get('level', 0)):
        cap = cf.get('caption', '')
        if not cap:
            continue

        decision = (decisions or {}).get(cap)
        if decision and decision.get('action') == 'skip':
            warnings['skipped_by_decision'].append({
                'caption': cap, 'reason': decision.get('reason', '')})
            continue

        expr = None
        if decision and decision.get('action') in ('use_expr', 'add', 'replace'):
            expr = decision.get('expr', '')
            bad_refs = _invalid_decision_refs(expr, ds, all_captions, all_params)
            if bad_refs:
                warnings['invalid_decisions'].append({
                    'caption': cap, 'unknown_refs': bad_refs})
                expr = None  # fall through to default handling

        entries = formula_lookup.get(cap, [])
        entry = entries[0] if entries else {}
        if expr is None:
            if not entries:
                omitted.append(cap)
                continue
            tier = entry.get('tier', 'translatable')
            if tier == 'untranslatable':
                omitted.append(cap)
                continue
            expr = entry.get('translated', '')
            if not expr:
                omitted.append(cap)
                continue

        expr = _sanitize_formula_refs(expr)
        # A decision may rename the formula (Tableau auto-captions ad-hoc
        # calcs with the raw formula text — unusable as a display name)
        display_name = (decision or {}).get('name') or cap
        fid = f'formula_{_sanitize_formula_id(display_name)}'

        formulas_list.append(OrderedDict([
            ('id', fid),
            ('name', display_name),
            ('expr', expr),
        ]))

        fc = OrderedDict()
        fc['name'] = display_name
        fc['formula_id'] = fid
        fc['properties'] = OrderedDict()
        if decision and decision.get('column_type'):
            is_meas = decision['column_type'] == 'MEASURE'
        else:
            is_meas = _has_aggregate(expr) or cf.get('role') == 'measure'
        fc['properties']['column_type'] = 'MEASURE' if is_meas else 'ATTRIBUTE'
        if is_meas:
            fc['properties']['aggregation'] = (decision or {}).get('aggregation', 'SUM')
        formula_columns.append(fc)

    # Physical columns
    phys_columns = []
    phys_cols_data = ds.get('physical_columns', [])
    seen_cols: set[str] = set()
    for c in phys_cols_data:
        cname = c.get('name', '')
        if not cname or cname in seen_cols:
            continue
        parent = c.get('parent_table', '')
        matched_table = _resolve(parent)
        if not matched_table:
            # Tableau's " (Source)" collision suffix names the column's
            # actual source — use it as a secondary assignment signal
            hint = _split_disambig(cname)[1]
            if hint:
                matched_table = _resolve(hint)
        if not matched_table:
            if len(table_names) == 1:
                matched_table = table_names[0]
            else:
                warnings['unassigned_columns'].append(
                    {'column': cname, 'parent_table': parent})
                continue
        seen_cols.add(cname)

        pc = OrderedDict()
        pc['name'] = cname
        pc['column_id'] = f'{matched_table}::{cname}'
        pc['properties'] = OrderedDict()
        pc['properties']['column_type'] = 'MEASURE' if _is_measure(c) else 'ATTRIBUTE'
        phys_columns.append(pc)

    # Parameters referenced by formulas actually included in this model
    param_refs: set[str] = set()
    for f in formulas_list:
        param_refs |= _find_param_refs(f.get('expr', ''), all_params)

    params_for_model = []
    if param_refs:
        for p in all_params:
            if p.get('caption', '') in param_refs:
                params_for_model.append(_build_parameter(p))

    # Assemble
    tml = OrderedDict()
    tml['model'] = OrderedDict()
    tml['model']['name'] = model_name
    tml['model']['model_tables'] = model_tables

    columns_all = phys_columns + formula_columns
    if columns_all:
        tml['model']['columns'] = columns_all
    if formulas_list:
        tml['model']['formulas'] = formulas_list
    if params_for_model:
        tml['model']['parameters'] = params_for_model

    return tml, omitted, warnings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _build_connection_table_index(
    connection_tables: list[str],
) -> dict[str, str]:
    """Build {UPPER_SNAKE_normalized: original_name} from connection table names.

    Used for fuzzy-matching Tableau source tables against the connection
    hierarchy when no explicit table mapping is provided.
    """
    index: dict[str, str] = {}
    for name in connection_tables:
        key = _to_upper_snake(name)
        if key not in index:
            index[key] = name
    return index


def run_generate(
    parsed: dict,
    translated: dict,
    connection: str,
    database: str,
    schema: str,
    table_map: dict[str, str] | None,
    out_dir: str,
    decisions: dict[str, dict] | None = None,
    sql_table_map: list[tuple[str, str]] | None = None,
    connection_tables: list[str] | None = None,
) -> dict:
    """Generate all Table, SQL View, and Model TMLs.

    ``decisions`` (from ``--decisions decisions.json``) resolves formulas the
    translator could not — see ``_load_decisions`` for the format. When any
    unresolved formulas remain, a ``decisions-needed.json`` questions file is
    written next to the TMLs for the LLM to answer in one pass.

    ``sql_table_map`` (from ``_load_full_table_map``) carries the full
    qualified source→target pairs used to rewrite table references inside
    SQL view queries and to strip Tableau parameter references.

    ``connection_tables`` (from ``--connection-tables``) is an optional list
    of table names available in the ThoughtSpot connection hierarchy.  When
    no explicit ``table_map`` entry matches a Tableau source table, the name
    is normalized to UPPER_SNAKE_CASE and matched against this list.

    Returns a summary dict with generated files and counts.
    """
    os.makedirs(out_dir, exist_ok=True)
    table_map = table_map or {}
    conn_index = _build_connection_table_index(connection_tables) if connection_tables else {}

    # Build formula lookup from translated.json
    formula_lookup: dict[str, list[dict]] = {}
    for item in translated.get('formulas', []):
        cap = item.get('caption', '')
        if cap:
            formula_lookup.setdefault(cap, []).append(item)

    # Extract parameters
    all_params: list[dict] = []
    for ds in parsed.get('datasources', []):
        if ds.get('is_parameters'):
            all_params = ds.get('parameters', [])
            break

    datasources = [ds for ds in parsed.get('datasources', [])
                   if not ds.get('is_parameters')]

    summary: dict = {
        'tables': [],
        'sql_views': [],
        'models': [],
        'omitted_formulas': [],
        'dropped_joins': [],
        'unassigned_columns': [],
        'skipped_by_decision': [],
        'invalid_decisions': [],
        'sql_remaps': [],
        'connection_matched': [],
    }
    decisions_needed: list[dict] = []
    decisions_context: dict[str, dict] = {}

    for ds in datasources:
        ds_caption = ds.get('caption', ds.get('name', 'Unknown'))
        ds_tables = ds.get('tables', [])
        phys_cols = ds.get('physical_columns', [])

        # TWB-side table reference → generated TML object name. Every
        # rename made in Phases 1-2 is recorded here so Phase 3 (joins,
        # column_id assignment) resolves names instead of re-matching
        # raw strings.
        rename_map: dict[str, str] = {}
        # Generated table name → the column records assigned to it
        table_columns: dict[str, list[dict]] = {}

        # ── Phase 1: Table TMLs ──────────────────────────────────────
        generated_table_names: list[str] = []
        for tbl in ds_tables:
            if tbl.get('sql_query'):
                continue  # handled in Phase 2

            phys_table = tbl.get('physical_table', '')
            if not phys_table or phys_table.startswith('[Extract]') or phys_table == '[sqlproxy]':
                continue

            raw_name = _norm_table_name(phys_table)
            target_name = table_map.get(raw_name.upper())
            if target_name is None and conn_index:
                norm = _to_upper_snake(raw_name)
                target_name = conn_index.get(norm)
                if target_name:
                    summary['connection_matched'].append(
                        {'source': raw_name, 'matched': target_name})
            if target_name is None:
                target_name = raw_name
            rename_map[_norm_key(raw_name)] = target_name
            rel_name = tbl.get('relation_name', '')
            if rel_name:
                rename_map[_norm_key(rel_name)] = target_name

            # Collect columns for this table
            cols = [c for c in phys_cols
                    if _norm_key(c.get('parent_table', '')) == _norm_key(raw_name)]
            if not cols and len(ds_tables) == 1:
                cols = phys_cols  # single-table datasource fallback

            table_columns[target_name] = cols
            tml = _build_table_tml(target_name, cols, connection, database, schema)
            fname = f'{target_name}.table.tml'
            fpath = os.path.join(out_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as fh:
                yaml.dump(dict(tml), fh, default_flow_style=False,
                          sort_keys=False, allow_unicode=True, width=9999)
            ncols = len(tml['table']['columns'])
            summary['tables'].append({'name': target_name, 'columns': ncols, 'file': fname})
            generated_table_names.append(target_name)

        # ── Phase 2: SQL View TMLs ───────────────────────────────────
        for tbl in ds_tables:
            sql_query = tbl.get('sql_query')
            if not sql_query:
                continue

            rel_name = tbl.get('relation_name', 'Custom_SQL_Query')
            view_name = re.sub(r'[^a-zA-Z0-9_]', '_', rel_name).strip('_')
            if not view_name:
                view_name = 'Custom_SQL_Query'
            # Disambiguate generic "Custom_SQL_Query" using datasource caption
            if view_name == 'Custom_SQL_Query' and ds_caption:
                prefix = re.sub(r'[^a-zA-Z0-9_]', '_', ds_caption).strip('_')
                prefix = re.sub(r'_+', '_', prefix)
                if prefix:
                    view_name = f'{prefix}_Custom_SQL'

            rename_map[_norm_key(rel_name)] = view_name

            raw_name = _norm_table_name(rel_name)
            cols = [c for c in phys_cols
                    if _norm_key(c.get('parent_table', '')) == _norm_key(raw_name)]
            if not cols:
                for src in ds.get('custom_sql_sources', []):
                    src_name = src.get('name', '')
                    if src_name:
                        cols = [c for c in phys_cols
                                if c.get('parent_table', '') == src_name]
                        if cols:
                            rename_map[_norm_key(src_name)] = view_name
                            break

            if sql_table_map is not None:
                sql_query, sql_warnings = _remap_sql_query(sql_query, sql_table_map)
                for w in sql_warnings:
                    w['sql_view'] = view_name
                summary['sql_remaps'].extend(sql_warnings)

            table_columns[view_name] = cols
            tml = _build_sql_view_tml(view_name, sql_query, cols, connection)
            fname = f'{view_name}.sql_view.tml'
            fpath = os.path.join(out_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as fh:
                yaml.dump(dict(tml), fh, default_flow_style=False,
                          sort_keys=False, allow_unicode=True, width=9999)
            ncols = len(tml['sql_view']['sql_view_columns'])
            summary['sql_views'].append({'name': view_name, 'columns': ncols, 'file': fname})
            generated_table_names.append(view_name)

        # ── Phase 3: Model TML ───────────────────────────────────────
        if not generated_table_names:
            continue

        model_name = re.sub(r'[^a-zA-Z0-9_ ]', '', ds_caption).strip()
        model_name = re.sub(r' +', ' ', model_name)
        if not model_name:
            model_name = 'Model'

        model_tml, omitted, warnings = _build_model_tml(
            model_name=model_name,
            table_names=generated_table_names,
            ds=ds,
            formula_lookup=formula_lookup,
            all_params=all_params,
            joins=ds.get('joins'),
            rename_map=rename_map,
            table_columns=table_columns,
            decisions=decisions,
        )

        fname = f'{model_name.replace(" ", "_")}.model.tml'
        fpath = os.path.join(out_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as fh:
            yaml.dump(dict(model_tml), fh, default_flow_style=False,
                      sort_keys=False, allow_unicode=True, width=9999)

        nformulas = len(model_tml.get('model', {}).get('formulas', []))
        ncols = len(model_tml.get('model', {}).get('columns', []))
        summary['models'].append({
            'name': model_name,
            'formulas': nformulas,
            'columns': ncols,
            'file': fname,
        })
        if omitted:
            summary['omitted_formulas'].extend(
                [{'model': model_name, 'formula': f} for f in omitted])
        summary['dropped_joins'].extend(
            [{'model': model_name, **dj} for dj in warnings['dropped_joins']])
        summary['unassigned_columns'].extend(
            [{'model': model_name, **uc} for uc in warnings['unassigned_columns']])
        summary['skipped_by_decision'].extend(
            [{'model': model_name, **sd} for sd in warnings['skipped_by_decision']])
        summary['invalid_decisions'].extend(
            [{'model': model_name, **iv} for iv in warnings['invalid_decisions']])

        # Collect unresolved formulas for the decisions-needed questions file
        model_entry_added = False
        for cf in ds.get('calculated_fields', []):
            cap = cf.get('caption', '')
            if not cap or (decisions and cap in decisions):
                continue
            f_entries = formula_lookup.get(cap, [])
            f_entry = f_entries[0] if f_entries else {}
            if f_entry.get('deterministic'):
                continue
            needed_entry = {
                'model': model_name,
                'caption': cap,
                'tier': f_entry.get('tier', 'missing'),
                'reason': f_entry.get('reason', ''),
                'original': f_entry.get('original') or cf.get('formula_raw', ''),
                'auto_expr': f_entry.get('translated') or None,
                'status': 'omitted' if cap in (omitted or []) else 'included_auto',
            }
            needed_entry.update(_decision_context_for(
                cf, formula_lookup, ds.get('calculated_fields', []),
                parsed.get('formula_column_map', {}),
                parsed.get('worksheets', [])))
            decisions_needed.append(needed_entry)
            model_entry_added = True
        if model_entry_added:
            m = model_tml.get('model', {})
            decisions_context[model_name] = {
                'columns': [c.get('name') for c in m.get('columns', []) if c.get('name')],
                'parameters': [p.get('name') for p in m.get('parameters', []) if p.get('name')],
            }

    if decisions_needed:
        needed_path = os.path.join(out_dir, 'decisions-needed.json')
        with open(needed_path, 'w', encoding='utf-8') as fh:
            json.dump({
                'instructions': (
                    'For each formula, answer with a decision: '
                    '{"caption", "action": "use_expr"|"skip", "expr", '
                    '"column_type", "aggregation", "reason"}. '
                    '"included_auto" entries already carry auto_expr in the TML — '
                    'decide only if the auto translation is wrong. '
                    'Write decisions.json and re-run generate-tml --decisions.'),
                'formulas': decisions_needed,
                'context': decisions_context,
            }, fh, indent=2)
        summary['decisions_needed'] = {
            'count': len(decisions_needed), 'file': 'decisions-needed.json'}

    return summary
