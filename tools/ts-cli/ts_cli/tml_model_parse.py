"""ThoughtSpot Model TML parsing — dialect-agnostic.

Pure functions: dicts in, structured data out. No I/O, no network, no
target-platform syntax (no Snowflake DDL, no dbt YAML/Jinja). Column-index
lookup, column_id resolution, dimension/metric/time_dimension classification,
join-graph walking, relationship naming, and metric dependency ordering are
identical work regardless of which platform's schema the Model TML is being
converted to — this module is the shared substrate for `sv_build_sv.py`
(→ Snowflake Semantic View) and `dbt_build_export.py` (→ dbt project files).

Split out under BL-100's "pure functions, no I/O" convention once a second
consumer (ts-convert-to-dbt) needed the identical parsing logic — see
agents/cli/ts-convert-to-dbt/references/open-items.md.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# to_snake — identifier conversion
# ---------------------------------------------------------------------------

def to_snake(name: str) -> str:
    """Convert a display name to a snake_case identifier."""
    s = re.sub(r"[^a-z0-9]", "_", name.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "field"
    if s[0].isdigit():
        s = "field_" + s
    return s[:255]


# ---------------------------------------------------------------------------
# Column resolution — column_id → physical column name
# ---------------------------------------------------------------------------

def build_column_index(table_tmls: dict[str, dict]) -> dict[str, dict]:
    """Build a lookup: (table_name, logical_name) → {db_column_name, data_type}.

    table_tmls: {table_name: parsed_table_tml_dict}
    """
    index: dict[tuple[str, str], dict] = {}
    for tname, tml in table_tmls.items():
        tbl = tml.get("table", {})
        for col in tbl.get("columns", []):
            logical = col.get("name", "")
            db_col = col.get("db_column_name", logical)
            dt = (col.get("db_column_properties") or {}).get("data_type", "")
            index[(tname, logical)] = {"db_column_name": db_col, "data_type": dt}
    return index


def resolve_column_id(
    column_id: str,
    model_table_map: dict[str, str],
    col_index: dict[tuple[str, str], dict],
    phys_by_node: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Resolve TABLE::COL → (logical_table_name, db_column_name, data_type).

    model_table_map: node key (alias-or-name) → logical table identifier.
    phys_by_node: node key → physical table name. The column index is keyed by the
    physical table name, so a role-play prefix (e.g. ON_BEHALF_ACCOUNT) must be
    translated to its physical table (ACCOUNT) before the lookup — otherwise the
    db_column_name/data_type fall back to the raw column and the role-play table's
    own dimensions collapse.
    """
    if "::" not in column_id:
        raise ValueError(f"column_id missing '::': {column_id}")
    table_part, col_part = column_id.split("::", 1)

    logical_table = model_table_map.get(table_part)
    if logical_table is None:
        raise ValueError(
            f"column_id references unknown table '{table_part}': {column_id}")

    phys = (phys_by_node or {}).get(table_part, table_part)
    entry = col_index.get((phys, col_part)) or col_index.get((table_part, col_part))
    if entry is None:
        return logical_table, col_part, ""
    return logical_table, entry["db_column_name"], entry.get("data_type", "")


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

_DATE_TYPES = frozenset({
    "DATE", "DATETIME", "DATE_TIME", "TIMESTAMP",
    "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ",
})
_DATE_SUFFIXES = (
    "_date", "_at", "_time", "_ts", "_datetime",
    "date", "time", "timestamp",
)


def _is_date_column(col_name: str, data_type: str) -> bool:
    dt = data_type.upper().strip()
    if dt in _DATE_TYPES:
        return True
    lower = col_name.lower()
    return any(lower.endswith(s) for s in _DATE_SUFFIXES)


def classify_column(
    col: dict,
    formulas_by_id: dict[str, dict],
    data_type: str = "",
) -> str:
    """Classify a model column as 'dimension', 'time_dimension', or 'metric'.

    Returns 'skip' for formula columns that should be omitted (untranslatable).
    """
    if col.get("formula_id"):
        fid = col["formula_id"]
        formula = formulas_by_id.get(fid)
        if formula is None:
            return "skip"
        props = col.get("properties") or {}
        ct = props.get("column_type", "ATTRIBUTE")
        if ct == "MEASURE":
            return "metric"
        return "dimension"

    props = col.get("properties") or {}
    ct = props.get("column_type", "ATTRIBUTE")
    if ct == "MEASURE":
        return "metric"

    col_name = col.get("name", "")
    if _is_date_column(col_name, data_type):
        return "time_dimension"
    return "dimension"


# ---------------------------------------------------------------------------
# Relationship parsing and naming
# ---------------------------------------------------------------------------

_JOIN_ON_RE = re.compile(
    r"\[([^\]:]+)::([^\]]+)\]\s*=\s*\[([^\]:]+)::([^\]]+)\]"
)


def parse_join_on(on_expr: str) -> list[tuple[str, str, str, str]]:
    """Parse a model join `on` expression into (left_table, left_col, right_table, right_col) tuples."""
    return _JOIN_ON_RE.findall(on_expr)


def build_relationship_name(
    left: str, right: str, left_col: str | None,
    used: set[str],
) -> str:
    """Generate a unique relationship name."""
    base = f"{left}_to_{right}"
    name = base
    if name in used:
        if left_col:
            name = f"{left}_{to_snake(left_col)}_to_{right}"
        if name in used:
            i = 2
            while f"{name}_{i}" in used:
                i += 1
            name = f"{name}_{i}"
    used.add(name)
    return name


# ---------------------------------------------------------------------------
# Metric ordering — topological sort by alias references
# ---------------------------------------------------------------------------

def order_metrics(metrics: list[dict]) -> list[dict]:
    """Sort metrics so base aggregates come before derived metrics that
    reference them by alias.

    Each metric dict has at minimum: {alias, expr, ...}.
    """
    by_alias = {m["alias"]: m for m in metrics}
    all_aliases = set(by_alias)

    deps: dict[str, set[str]] = {}
    for m in metrics:
        expr_lower = m.get("expr", "").lower()
        refs = set()
        for a in all_aliases:
            if a != m["alias"] and a.lower() in expr_lower:
                refs.add(a)
        deps[m["alias"]] = refs

    ordered: list[str] = []
    visited: set[str] = set()

    def visit(alias: str) -> None:
        if alias in visited:
            return
        visited.add(alias)
        for dep in deps.get(alias, ()):
            visit(dep)
        ordered.append(alias)

    for m in metrics:
        visit(m["alias"])

    return [by_alias[a] for a in ordered if a in by_alias]


# ---------------------------------------------------------------------------
# model_tables → table maps and join-graph walk
# ---------------------------------------------------------------------------

def model_table_identity(mt: dict) -> tuple[str, str]:
    """Return (node_key, physical_name) for a model_table entry.

    The node key is the identity that `column_id` prefixes and join `with:`/`on:`
    tokens reference — the **alias** for a role-playing instance of a reused
    physical table, otherwise the table's `id`/`name`. The physical name is the
    ThoughtSpot Table object (used for Table-TML/column-index lookups). For a
    role-play these differ (ON_BEHALF_ACCOUNT vs ACCOUNT); for a plain table
    they are the same."""
    node_key = mt.get("alias") or mt.get("id") or mt.get("name", "")
    physical = mt.get("name", node_key)
    return node_key, physical


def build_table_maps(
    model_tables: list[dict],
    table_tmls: dict[str, dict],
) -> tuple[dict[str, str], dict[str, str], list[str], dict[str, str]]:
    """Map model_table entries to logical table identifiers, FQNs, and physical names.

    Returns (mt_names, mt_fqns, mt_order, mt_phys). ``mt_names`` maps a node key
    (alias-or-name) to the logical table identifier — the alias for a role-play,
    so a reused physical table yields distinct logical tables. ``mt_phys`` maps
    the node key to the physical table name for column-index lookups. ``mt_fqns``
    joins the Table TML's db/schema/db_table fields (falling back to the physical
    name) — a fully dialect-agnostic dotted identifier, not Snowflake-specific.
    """
    mt_names: dict[str, str] = {}
    mt_fqns: dict[str, str] = {}
    mt_order: list[str] = []
    mt_phys: dict[str, str] = {}

    for mt in model_tables:
        node_key, physical = model_table_identity(mt)
        # Logical table = the node key (alias for a role-play, else the name).
        mt_names[node_key] = node_key
        mt_phys[node_key] = physical
        # Physical-name fallback so join `on:` clauses (which use physical names on
        # both sides) and un-aliased column_ids still resolve.
        mt_names.setdefault(physical, physical)
        mt_phys.setdefault(physical, physical)
        mt_order.append(node_key)

        ttml = table_tmls.get(physical, {})
        tbl = ttml.get("table", {})
        fqn_parts = []
        for k in ("db", "schema", "db_table"):
            v = tbl.get(k)
            if v:
                fqn_parts.append(v)
        mt_fqns[node_key] = ".".join(fqn_parts) if fqn_parts else physical

    return mt_names, mt_fqns, mt_order, mt_phys


def collect_join_data(
    model_tables: list[dict],
    mt_names: dict[str, str],
    col_index: dict[tuple[str, str], dict],
) -> tuple[list[dict], dict[str, list[str]]]:
    """Resolve joins from model_tables into join_data records and PK columns.

    Returns (join_data, mt_pks). Each join_data record: {name, ts_name,
    left_id, left_table, right_table, pairs, join_type, cardinality} — pairs are
    (left_table, left_physical_col, right_table, right_physical_col) tuples,
    resolved against the column index but with no target-platform SQL syntax.
    """
    join_data: list[dict] = []
    mt_pks: dict[str, list[str]] = {}
    used_rel_names: set[str] = set()

    for mt in model_tables:
        mt_id, _phys = model_table_identity(mt)
        for join in mt.get("joins", []):
            with_table = join.get("with", "")
            on_expr = join.get("on", "")
            pairs = parse_join_on(on_expr)

            resolved_pairs = []
            for lt, lc, rt, rc in pairs:
                lt_name = mt_names.get(lt, lt)
                rt_name = mt_names.get(rt, rt)
                lc_entry = col_index.get((lt_name, lc))
                rc_entry = col_index.get((rt_name, rc))
                lc_phys = lc_entry["db_column_name"] if lc_entry else lc
                rc_phys = rc_entry["db_column_name"] if rc_entry else rc
                resolved_pairs.append((lt, lc_phys, rt, rc_phys))

            left_col = resolved_pairs[0][1] if resolved_pairs else None
            left_lower = to_snake(mt_names.get(mt_id, mt_id))
            right_lower = to_snake(with_table)
            rel_name = build_relationship_name(
                left_lower, right_lower, left_col, used_rel_names)

            for _, _, _, right_col in resolved_pairs:
                mt_pks.setdefault(with_table, []).append(right_col)

            join_data.append({
                "name": rel_name,
                # The join's ORIGINAL ThoughtSpot name, kept beside the derived
                # one. `rel_name` is generated to be a safe, unique identifier
                # for target platforms with identifier rules (Snowflake SV);
                # dbt's ts_join_name has no such constraint and must round-trip
                # the user's own name, or every resync renames their joins.
                "ts_name": join.get("name") or "",
                "left_id": mt_id,
                "left_table": mt_names.get(mt_id, mt_id),
                "right_table": with_table,
                "pairs": resolved_pairs,
                "join_type": join.get("type", ""),
                "cardinality": join.get("cardinality", ""),
            })

    return join_data, mt_pks
