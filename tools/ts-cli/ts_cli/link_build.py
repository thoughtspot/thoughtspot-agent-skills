"""Pure builders for `ts link build` — register a semantic-layer object as a ThoughtSpot
Table plus a thin, formula-free Model.

Unlike the `ts-convert-from-*` pipelines, nothing is translated: the platform behind the
connection (Snowflake Semantic View, Databricks Metric View, Honeydew, Cube, Kyvos, …)
owns the metric logic and generates the SQL. ThoughtSpot only needs the column list,
each column's role (attribute vs measure), its aggregation, and the metadata that makes
it searchable (descriptions, synonyms, ai_context, Spotter instructions).

There are deliberately no per-platform adapters. The input is one normalized spec the
skill assembles from whatever the platform exposes; the only platform-shaped choice is
the aggregation mode:

- ``aggregate`` — every measure gets ``aggregation: AGGREGATE`` (Snowflake SV and
  Databricks MV: ThoughtSpot wraps the column in the platform's own measure function).
- ``standard`` — every measure gets its logical aggregation (``SUM``, ``COUNT_DISTINCT``,
  …), taken from the column's ``aggregation`` field or inferred from its ``expr``
  (Honeydew-style platforms that expect a standard aggregate over the metric).

Everything here is pure (no I/O) so it is unit-tested without a live cluster.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

AGGREGATION_MODES = ("aggregate", "standard")

# ThoughtSpot data_type values accepted verbatim in a spec.
_TS_TYPES = {"VARCHAR", "INT64", "INT32", "DOUBLE", "FLOAT", "BOOL", "DATE", "DATE_TIME", "TIME"}
_NUMERIC_TS_TYPES = {"INT64", "INT32", "DOUBLE", "FLOAT"}

# Warehouse type (lower-case base name) → ThoughtSpot data_type. Covers the type names
# the supported platforms report; decimal/number are resolved by scale below.
_WAREHOUSE_TYPE_MAP = {
    "string": "VARCHAR", "varchar": "VARCHAR", "char": "VARCHAR", "text": "VARCHAR",
    "character varying": "VARCHAR", "nvarchar": "VARCHAR",
    "bigint": "INT64", "int": "INT64", "integer": "INT64", "smallint": "INT64",
    "tinyint": "INT64", "byteint": "INT64", "long": "INT64",
    "double": "DOUBLE", "float": "DOUBLE", "float4": "DOUBLE", "float8": "DOUBLE",
    "real": "DOUBLE", "double precision": "DOUBLE",
    "boolean": "BOOL", "bool": "BOOL",
    "date": "DATE",
    "timestamp": "DATE_TIME", "timestamp_ntz": "DATE_TIME", "timestamp_ltz": "DATE_TIME",
    "timestamp_tz": "DATE_TIME", "datetime": "DATE_TIME",
    "time": "TIME",
}

# SQL / ThoughtSpot spellings of an aggregation → ThoughtSpot `aggregation` value.
_AGG_ALIASES = {
    "SUM": "SUM",
    "COUNT": "COUNT",
    "COUNT_DISTINCT": "COUNT_DISTINCT", "COUNT DISTINCT": "COUNT_DISTINCT",
    "UNIQUE COUNT": "COUNT_DISTINCT", "UNIQUE_COUNT": "COUNT_DISTINCT",
    "DISTINCT_COUNT": "COUNT_DISTINCT", "COUNTD": "COUNT_DISTINCT",
    "AVG": "AVERAGE", "AVERAGE": "AVERAGE", "MEAN": "AVERAGE",
    "MIN": "MIN", "MAX": "MAX",
    "STDDEV": "STD_DEVIATION", "STDDEV_SAMP": "STD_DEVIATION", "STDDEV_POP": "STD_DEVIATION",
    "STD_DEVIATION": "STD_DEVIATION",
    "VARIANCE": "VARIANCE", "VAR_SAMP": "VARIANCE", "VAR_POP": "VARIANCE",
    "AGGREGATE": "AGGREGATE",
}

_ACRONYMS = {"id": "ID", "gbp": "GBP", "usd": "USD", "eur": "EUR", "kpi": "KPI",
             "pct": "%", "py": "PY", "yoy": "YoY", "ytd": "YTD", "mtd": "MTD"}

_FILTER_HEAD_RE = re.compile(r"^FILTER\s*\(\s*WHERE\b", re.IGNORECASE)
_OUTER_AGG_RE = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*(DISTINCT\b)?", re.IGNORECASE)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def _close_index(text: str, open_idx: int) -> Optional[int]:
    """Index of the paren closing the one at ``open_idx``; None if unbalanced."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _is_filter_tail(rest: str) -> bool:
    """True when ``rest`` is exactly one ``FILTER (WHERE …)`` clause and nothing after it."""
    if not _FILTER_HEAD_RE.match(rest):
        return False
    close = _close_index(rest, rest.index("("))
    return close is not None and not rest[close + 1:].strip()


class LinkSpecError(ValueError):
    """The spec cannot produce valid TML; the message says which columns and why."""


def map_data_type(raw: str) -> Optional[str]:
    """Map a warehouse (or ThoughtSpot) type name to a ThoughtSpot `data_type`.

    ``decimal(p, s)`` / ``number(p, s)`` / ``numeric(p, s)`` become DOUBLE when the scale
    is above 0 and INT64 otherwise (no scale → INT64, the platforms' default of 0). Returns None for unknown or
    unsupported types (arrays, structs, variant, binary, …).
    """
    if not raw:
        return None
    text = str(raw).strip()
    if text.upper() in _TS_TYPES:
        return text.upper()
    base = text.lower().split("<")[0]
    m = re.match(r"^\s*(decimal|number|numeric)\s*(?:\(\s*\d+\s*(?:,\s*(\d+)\s*)?\))?\s*$", base)
    if m:
        # No scale means scale 0 on every supported platform (Snowflake NUMBER = (38,0),
        # Spark DECIMAL = (10,0)) — same rule as sv_introspect.map_snowflake_type.
        return "DOUBLE" if m.group(2) and int(m.group(2)) > 0 else "INT64"
    base = base.split("(")[0].strip()
    return _WAREHOUSE_TYPE_MAP.get(base)


def infer_aggregation(expr: Optional[str]) -> Optional[str]:
    """Infer a ThoughtSpot aggregation from a measure expression's OUTERMOST function.

    ``SUM(x)`` → SUM, ``COUNT(DISTINCT x)`` → COUNT_DISTINCT, ``AVG(x)`` → AVERAGE.
    Returns None when the outer call does not span the whole expression
    (``SUM(a) / SUM(b)``) or is not an aggregate — there is no single honest answer then,
    and guessing SUM would re-aggregate a ratio.
    """
    if not expr or not isinstance(expr, str):
        return None
    # Blank out quoted literals so a ')' inside one cannot unbalance the paren walk.
    text = _STRING_LITERAL_RE.sub("''", expr.strip())
    m = _OUTER_AGG_RE.match(text)
    if not m:
        return None
    open_idx = text.index("(")
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                rest = text[i + 1:].strip()
                # `SUM(x) FILTER (WHERE …)` is still a SUM; anything else after the outer
                # call (`/ SUM(b)`, `* 100`, `OVER (…)`) makes it a compound expression.
                if rest and not _is_filter_tail(rest):
                    return None
                break
    else:
        return None
    fn = m.group(1).upper()
    if m.group(2):
        # COUNT(DISTINCT x) is COUNT_DISTINCT; SUM/AVG(DISTINCT x) has no ThoughtSpot
        # column aggregation, so refuse rather than emit a plain SUM/AVERAGE.
        return "COUNT_DISTINCT" if fn == "COUNT" else None
    agg = _AGG_ALIASES.get(fn)
    return agg if agg != "AGGREGATE" else None


def normalize_aggregation(value: Optional[str]) -> Optional[str]:
    """Normalize a spec's explicit ``aggregation`` value; None if unrecognised."""
    if not value:
        return None
    return _AGG_ALIASES.get(re.sub(r"\s+", " ", str(value).strip().upper()))


def humanize(name: str) -> str:
    """``dm_order.employee_count`` → ``Employee Count``; ``revenue_gbp`` → ``Revenue GBP``."""
    leaf = name.split(".")[-1]
    words = [w for w in re.split(r"[_\s]+", leaf) if w]
    return " ".join(_ACRONYMS.get(w.lower(), w[:1].upper() + w[1:]) for w in words) or name


def _display_names(columns: List[dict], naming: str) -> Dict[str, str]:
    """Unique (case-insensitive) Model display name per source column name.

    An explicit ``display_name`` always wins: those are reserved first, and two explicit
    names that clash raise LinkSpecError. Every other column gets its humanized name
    (or its source name with ``naming="raw"``); on a clash it falls back to humanizing
    the full dotted name, then the source name, then a numeric suffix — so the result
    is always unique, since duplicate Model column names fail import.
    """
    out: Dict[str, str] = {}
    taken: set = set()
    for c in columns:
        dn = c.get("display_name")
        if dn:
            if dn.lower() in taken:
                raise LinkSpecError(f"display_name {dn!r} is used by more than one column")
            out[c["name"]] = dn
            taken.add(dn.lower())
    for c in columns:
        n = c["name"]
        if n in out:
            continue
        if naming == "raw":
            candidates = [n]
        else:
            candidates = [humanize(n), " ".join(humanize(p) for p in n.split(".")), n]
        choice = next((v for v in candidates if v.lower() not in taken), None)
        if choice is None:
            i = 2
            while f"{candidates[0]} {i}".lower() in taken:
                i += 1
            choice = f"{candidates[0]} {i}"
        out[n] = choice
        taken.add(choice.lower())
    return out


def _instructions_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


_SKIP_REASON = ("non-numeric measure: ThoughtSpot coerces it to ATTRIBUTE, "
                "which queries the platform measure unwrapped and fails")


class _Resolved:
    """One spec column after type/role/aggregation resolution."""
    __slots__ = ("col", "name", "data_type", "is_measure", "aggregation")

    def __init__(self, col: dict, data_type: str, is_measure: bool, aggregation: Optional[str]):
        self.col, self.name, self.data_type = col, col["name"], data_type
        self.is_measure, self.aggregation = is_measure, aggregation


_TEXT_FIELDS = ("description", "ai_context", "display_name", "expr", "aggregation", "data_type", "kind")


def _check_text_fields(spec: dict, columns: List[dict]) -> None:
    """Type-check the free-text fields so a malformed spec fails cleanly, not in a traceback."""
    bad: List[str] = []
    for key in ("description",):
        if spec.get(key) is not None and not isinstance(spec[key], str):
            bad.append(f"spec.{key} must be a string")
    ins = spec.get("instructions")
    if ins is not None and not isinstance(ins, (str, list)):
        bad.append("spec.instructions must be a string or a list of strings")
    for c in columns:
        for key in _TEXT_FIELDS:
            if c.get(key) is not None and not isinstance(c[key], str):
                bad.append(f"{c['name']}.{key} must be a string")
        syn = c.get("synonyms")
        if syn is not None and not isinstance(syn, (str, list)):
            bad.append(f"{c['name']}.synonyms must be a list of strings")
    if bad:
        raise LinkSpecError("spec has wrongly-typed fields:\n  " + "\n  ".join(bad))


def _synonyms(value: Any) -> List[str]:
    """A list of non-blank, stripped synonyms. A bare string is one synonym, not its
    characters; None and blank entries are dropped."""
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or []) if v is not None and str(v).strip()]


def _validate_options(aggregation_mode: str, naming: str, default_aggregation: Optional[str]) -> Optional[str]:
    """Check the build options; returns the normalized default aggregation (standard mode only)."""
    if aggregation_mode not in AGGREGATION_MODES:
        raise LinkSpecError(f"aggregation mode must be one of {AGGREGATION_MODES}, got {aggregation_mode!r}")
    if naming not in ("humanize", "raw"):
        raise LinkSpecError(f"naming must be 'humanize' or 'raw', got {naming!r}")
    if not default_aggregation or aggregation_mode != "standard":
        return None
    fallback = normalize_aggregation(default_aggregation)
    if not fallback:
        raise LinkSpecError(f"unrecognised default aggregation {default_aggregation!r}")
    return fallback


def _validate_columns(columns: Any) -> None:
    if not isinstance(columns, list) or not columns:
        raise LinkSpecError("spec 'columns' must be a non-empty list")
    if not all(isinstance(c, dict) for c in columns):
        raise LinkSpecError("every entry in 'columns' must be an object")
    names = [c.get("name") for c in columns]
    if not all(isinstance(n, str) and n for n in names):
        raise LinkSpecError("every column needs a non-empty string 'name'")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise LinkSpecError(f"duplicate column name(s): {', '.join(dupes)}")


def _validate_spec(spec: Any, aggregation_mode: str, naming: str,
                   default_aggregation: Optional[str]) -> Optional[str]:
    """Structural checks; returns the normalized default aggregation (or None)."""
    fallback = _validate_options(aggregation_mode, naming, default_aggregation)
    if not isinstance(spec, dict):
        raise LinkSpecError("spec must be a JSON object")
    missing = [k for k in ("connection", "db", "schema", "db_table") if not spec.get(k)]
    if missing:
        raise LinkSpecError(f"spec is missing required field(s): {', '.join(missing)}")
    _validate_columns(spec.get("columns"))
    _check_text_fields(spec, spec["columns"])
    return fallback


def _standard_aggregation(col: dict, fallback: Optional[str]) -> Tuple[Optional[str], str]:
    """(aggregation, source) for a measure in standard mode; aggregation None = error,
    with source holding the message."""
    explicit = col.get("aggregation")
    if explicit:
        agg = normalize_aggregation(explicit)
        return (agg, "explicit") if agg else (None, f"unrecognised aggregation {explicit!r}")
    agg = infer_aggregation(col.get("expr"))
    if agg:
        return agg, "inferred"
    if fallback:
        return fallback, "default"
    return None, ("no aggregation — give 'aggregation', an 'expr' with an outer aggregate, "
                  "or pass a default aggregation")


def _resolve_columns(columns: List[dict], aggregation_mode: str, fallback: Optional[str]):
    """Resolve every column; returns (kept, skipped, agg_source) or raises with ALL errors."""
    errors: List[str] = []
    skipped: List[dict] = []
    kept: List[_Resolved] = []
    warnings: List[str] = []
    agg_source: Dict[str, int] = {}
    for c in columns:
        n = c["name"]
        dt = map_data_type(c.get("data_type", ""))
        kind = str(c.get("kind", "")).lower()
        if dt is None:
            errors.append(f"{n}: unsupported or missing data_type {c.get('data_type')!r}")
            continue
        if kind not in ("measure", "attribute", "dimension"):
            errors.append(f"{n}: kind must be 'measure', 'attribute' or 'dimension', got {c.get('kind')!r}")
            continue
        if kind != "measure":
            kept.append(_Resolved(c, dt, False, None))
            continue
        if dt not in _NUMERIC_TS_TYPES:
            skipped.append({"name": n, "data_type": dt, "reason": _SKIP_REASON})
            continue
        if aggregation_mode == "aggregate":
            agg, source = "AGGREGATE", "aggregate"
        else:
            agg, source = _standard_aggregation(c, fallback)
            if agg is None:
                errors.append(f"{n}: {source}")
                continue
        agg_source[source] = agg_source.get(source, 0) + 1
        kept.append(_Resolved(c, dt, True, agg))
        if agg == "COUNT_DISTINCT":
            warnings.append(f"{n}: COUNT_DISTINCT on a physical column is documented to be coerced "
                            f"to ATTRIBUTE on import (open item #4) — check 'coerced' after import")
    if errors:
        raise LinkSpecError("spec cannot be built:\n  " + "\n  ".join(errors))
    if not kept:
        raise LinkSpecError("no columns left to register after skipping non-numeric measures")
    return kept, skipped, agg_source, warnings


def _column_entries(r: _Resolved, table_name: str, display_name: str) -> Tuple[dict, dict]:
    """(table column, model column) TML entries for one resolved column."""
    props: Dict[str, Any] = {"column_type": "MEASURE" if r.is_measure else "ATTRIBUTE"}
    if r.aggregation:
        props["aggregation"] = r.aggregation
    if r.is_measure or r.data_type in ("DATE", "DATE_TIME", "TIME"):
        props["index_type"] = "DONT_INDEX"
    desc = (r.col.get("description") or "").strip()

    tc: Dict[str, Any] = {"name": r.name, "db_column_name": r.name}
    mc: Dict[str, Any] = {"name": display_name, "column_id": f"{table_name}::{r.name}"}
    if desc:
        tc["description"] = desc
        mc["description"] = desc
    tc["properties"] = dict(props)
    tc["db_column_properties"] = {"data_type": r.data_type}

    mprops = dict(props)
    synonyms = _synonyms(r.col.get("synonyms"))
    if synonyms:
        mprops["synonyms"] = synonyms
        mprops["synonym_type"] = "USER_DEFINED"
    ai_context = (r.col.get("ai_context") or "").strip()
    if ai_context:
        mprops["ai_context"] = ai_context
    mc["properties"] = mprops
    return tc, mc


def _with_description(head: Dict[str, Any], description: str, rest: Dict[str, Any]) -> Dict[str, Any]:
    """``head`` + optional ``description`` + ``rest``, preserving TML key order."""
    doc = dict(head)
    if description:
        doc["description"] = description
    doc.update(rest)
    return doc


def _report(tbl_name: str, model_name: str, aggregation_mode: str, kept: List[_Resolved],
            model_cols: List[dict], agg_source: Dict[str, int], skipped: List[dict],
            instructions: Any) -> dict:
    measures = sum(1 for r in kept if r.is_measure)
    return {
        "table_name": tbl_name,
        "model_name": model_name,
        "aggregation_mode": aggregation_mode,
        "columns": len(kept),
        "attributes": len(kept) - measures,
        "measures": measures,
        "aggregation_source": agg_source,
        "with_synonyms": sum(1 for m in model_cols if "synonyms" in m["properties"]),
        "with_ai_context": sum(1 for m in model_cols if "ai_context" in m["properties"]),
        "with_description": sum(1 for m in model_cols if "description" in m),
        "skipped": skipped,
        "instructions": _instructions_list(instructions),
    }


def build_link_tml(
    spec: dict,
    *,
    aggregation_mode: str,
    model_name: str,
    table_name: Optional[str] = None,
    naming: str = "humanize",
    default_aggregation: Optional[str] = None,
    spotter_enabled: bool = True,
) -> Tuple[dict, dict, dict]:
    """Build (table_doc, model_doc, report) from a link spec.

    Spec shape::

        {
          "connection": "TS-DBX", "db": "catalog", "schema": "schema",
          "db_table": "semantic_object_name",
          "description": "object-level description",          # optional
          "instructions": "Spotter guidance" | ["…", "…"],    # optional → API, not TML
          "columns": [
            {"name": "revenue", "data_type": "decimal(28,2)", "kind": "measure",
             "description": "…", "synonyms": ["sales"], "ai_context": "…",
             "display_name": "Revenue", "aggregation": "sum", "expr": "SUM(amount)"},
            …
          ]
        }

    Non-numeric measures are SKIPPED (ThoughtSpot rejects a non-numeric MEASURE and
    coerces it to ATTRIBUTE, which queries the platform's measure unwrapped and fails —
    live-verified on a Databricks Metric View, 2026-09-28) and listed in the report.
    The model's ``model_tables`` entry has no ``fqn``; the caller adds it after the
    Table import returns a GUID.

    Raises LinkSpecError for a spec that cannot produce valid TML.
    """
    fallback = _validate_spec(spec, aggregation_mode, naming, default_aggregation)
    kept, skipped, agg_source, warnings = _resolve_columns(spec["columns"], aggregation_mode, fallback)

    tbl_name = table_name or spec["db_table"]
    display = _display_names([r.col for r in kept], naming)
    entries = [_column_entries(r, tbl_name, display[r.name]) for r in kept]
    table_cols = [tc for tc, _ in entries]
    model_cols = [mc for _, mc in entries]

    object_desc = (spec.get("description") or "").strip()
    table = _with_description({"name": tbl_name}, object_desc, {
        "db": spec["db"], "schema": spec["schema"], "db_table": spec["db_table"],
        "connection": {"name": spec["connection"]}, "columns": table_cols})
    model = _with_description({"name": model_name}, object_desc, {
        "model_tables": [{"name": tbl_name}],
        "columns": model_cols,
        "properties": {"is_bypass_rls": False, "join_progressive": True,
                       "spotter_config": {"is_spotter_enabled": spotter_enabled}}})

    report = _report(tbl_name, model_name, aggregation_mode, kept, model_cols,
                     agg_source, skipped, spec.get("instructions"))
    report["warnings"] = warnings
    return {"table": table}, {"model": model}, report


def diff_column_roles(expected_model: dict, exported_model: dict) -> List[dict]:
    """Columns whose column_type or aggregation ThoughtSpot changed on import.

    ThoughtSpot coerces some combinations silently (a non-numeric MEASURE becomes an
    ATTRIBUTE; COUNT_DISTINCT on a physical column is documented to do the same), and
    the import still reports OK — so the only reliable check is to re-export and compare.
    Matches by ``column_id``. Pure.
    """
    def _index(doc: dict) -> Dict[str, dict]:
        m = doc.get("model", doc)
        return {c.get("column_id"): c.get("properties", {}) for c in m.get("columns", [])
                if c.get("column_id")}

    want, got = _index(expected_model), _index(exported_model)
    out: List[dict] = []
    for cid, wp in want.items():
        gp = got.get(cid)
        if gp is None:
            out.append({"column_id": cid, "issue": "missing after import"})
            continue
        for key in ("column_type", "aggregation"):
            want_v, got_v = wp.get(key), gp.get(key)
            if key == "aggregation" and wp.get("column_type") == "MEASURE":
                # SUM is ThoughtSpot's default and an export may omit it.
                want_v, got_v = want_v or "SUM", got_v or "SUM"
            if want_v != got_v:
                out.append({"column_id": cid, "field": key,
                            "expected": wp.get(key), "actual": gp.get(key)})
    return out
