"""Databricks Metric View YAML -> structured dict (`ts databricks parse-mv`).

Pure functions: YAML text in, JSON-ready dict out. No I/O, no network calls —
trivially unit-testable. stdlib + PyYAML only (Genie-vendorable — see
package docstring).

This module owns source classification, the joins walk, and the top-level
assembly; expression classification lives in mv_expr.py and window-spec
parsing in mv_window.py (both re-exported here, so this module remains the
package's single public import surface).

Schema reference: agents/shared/schemas/databricks-metric-view.md.
Classification rules: agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md.
"""
from __future__ import annotations

import re

import yaml

from ts_cli.databricks.mv_expr import (  # noqa: F401 — re-exported API
    classify_dimension_expr,
    classify_measure_expr,
    extract_cross_refs,
    split_dot_path,
    strip_sql_comments,
)
from ts_cli.databricks.mv_window import (  # noqa: F401 — re-exported API
    parse_offset,
    parse_range,
    parse_window,
)

_IDENT_SEGMENT_RE = re.compile(r"^[A-Za-z_][\w$]*$")
_SQL_SOURCE_RE = re.compile(r"^\(?\s*(select|with)\b", re.IGNORECASE)


def classify_source(raw: str) -> dict | None:
    """Classify a `source:` value into one of the documented source forms.

    Returns {"kind": "sql_query", ...} or {"kind": "table_fqn", ...}, or None
    when the value matches neither (caller records an unsupported[] entry).
    An FQN cannot be distinguished from an MV-on-MV source offline, so every
    table_fqn carries needs_live_check: True — the SKILL step runs the live
    information_schema.tables check and fails loud on METRIC_VIEW.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    if _SQL_SOURCE_RE.match(stripped):
        return {"kind": "sql_query", "raw": stripped,
                "parenthesized": stripped.startswith("(")}
    parts = split_dot_path(stripped)
    # Re-walk the raw text so each segment keeps its own quoted/bare flag
    # (split_dot_path strips the backticks).
    quoted_flags = _segment_quoted_flags(stripped)
    for part, quoted in zip(parts, quoted_flags):
        if not part:
            return None
        if not quoted and not _IDENT_SEGMENT_RE.match(part):
            return None
    return {"kind": "table_fqn", "raw": stripped,
            "parts": parts if len(parts) == 3 else None,
            "needs_live_check": True}


def _segment_quoted_flags(s: str) -> list[bool]:
    """Per dot-segment of s: True when the segment is backtick-quoted."""
    flags: list[bool] = []
    quoted = False
    in_backtick = False
    for ch in s:
        if ch == "`":
            in_backtick = not in_backtick
            quoted = True
        elif ch == "." and not in_backtick:
            flags.append(quoted)
            quoted = False
    flags.append(quoted)
    return flags


# ---------------------------------------------------------------------------
# Joins — nested hierarchy walk (SKILL.md Step 5's walk_joins, codified).
# on/using XOR, cardinality: > rely: > many_to_one default, per
# databricks-metric-view.md "Join Structure".
# ---------------------------------------------------------------------------

_CARDINALITY_VALUES = {"many_to_one", "one_to_many"}


def _join_cardinality(j: dict, alias: str) -> tuple[str, str] | str:
    """Resolve (cardinality, source) for a join, or an error message string."""
    card = j.get("cardinality")
    rely = j.get("rely")
    if card is not None:
        if card not in _CARDINALITY_VALUES:
            return (f"join '{alias}': unknown cardinality value {card!r} "
                    f"(expected many_to_one|one_to_many)")
        return card, "cardinality"
    if rely is not None:
        if not (isinstance(rely, dict) and rely.get("at_most_one_match") is True):
            return (f"join '{alias}': unrecognized rely block {rely!r} "
                    f"(only {{at_most_one_match: true}} is documented)")
        return "many_to_one", "rely"
    return "many_to_one", "default"


def _join_on_using(j: dict, alias: str, parent_alias: str):
    """Resolve (on, using) for a join, or an error message string.

    YAML 1.1 resolves an unquoted `on:` key to boolean True — accept both
    `"on"` and `True` as the key. `using:` must be a list (a null/scalar
    value is a problem, not a crash or per-character garbage); `on:` must
    be a non-empty SQL boolean-expression string (null, bool, numeric, or
    blank/whitespace-only values are problems, not literal "None"/"True"
    clauses or a silently accepted empty on-clause).
    """
    has_on = "on" in j or True in j
    has_using = "using" in j
    if has_on == has_using:
        return f"join '{alias}': exactly one of 'on' or 'using' is required"
    if has_using:
        if not isinstance(j["using"], list):
            return (f"join '{alias}': 'using' must be a list of column names, "
                    f"got {j['using']!r}")
        using = [str(c) for c in j["using"]]
        on = " AND ".join(f"{parent_alias}.{c} = {alias}.{c}" for c in using)
        return on, using
    on_val = j.get("on", j.get(True))
    if not isinstance(on_val, str) or not on_val.strip():
        return (f"join '{alias}': 'on' must be a SQL boolean expression, "
                f"got {on_val!r}")
    return str(on_val), None


def parse_joins(join_list, parent_alias: str = "source",
                unsupported: list | None = None) -> list[dict]:
    """Walk the nested joins: hierarchy into the contract's join tree.

    Problems append {"kind": "join", "name", "detail"} entries to
    `unsupported` and drop that node (and its subtree) from the output —
    the non-empty unsupported[] list makes the command exit non-zero, so
    nothing is silently lost.
    """
    if unsupported is None:
        unsupported = []
    out: list[dict] = []
    for j in join_list or []:
        if not isinstance(j, dict) or not j.get("name"):
            unsupported.append({"kind": "join", "name": None,
                                "detail": f"join entry missing 'name': {j!r}"})
            continue
        alias = str(j["name"])
        src = classify_source(str(j.get("source", "")))
        if src is None:
            unsupported.append({"kind": "join", "name": alias,
                                "detail": f"join '{alias}': unrecognized "
                                          f"source {j.get('source')!r}"})
            continue
        resolved_on = _join_on_using(j, alias, parent_alias)
        if isinstance(resolved_on, str):
            unsupported.append({"kind": "join", "name": alias,
                                "detail": resolved_on})
            continue
        on, using = resolved_on
        resolved = _join_cardinality(j, alias)
        if isinstance(resolved, str):
            unsupported.append({"kind": "join", "name": alias, "detail": resolved})
            continue
        cardinality, card_source = resolved
        out.append({
            "alias": alias,
            "source": src,
            "on": on,
            "using": using,
            "parent": parent_alias,
            "cardinality": cardinality,
            "cardinality_source": card_source,
            "joins": parse_joins(j.get("joins"), alias, unsupported),
        })
    return out


# ---------------------------------------------------------------------------
# Top-level assembly — `ts databricks parse-mv`'s single entry point.
# ---------------------------------------------------------------------------

_KNOWN_TOP_KEYS = {"version", "comment", "source", "joins", "filter",
                   "fields", "dimensions", "measures", "materialization"}
_KNOWN_VERSIONS = {"0.1", "1.1"}

_DENSITY_WARNING = (
    "measure '{name}': range '{raw_range}' is a date-interval frame on "
    "Databricks but translates to row-positional moving_sum on ThoughtSpot — "
    "numbers match only if order column '{order}' is dense at the {unit} "
    "grain (one row per {unit}, no gaps). Verify density before trusting the "
    "translation (BL-098; docs/audit/2026-07-09-dbx-semantic-claim-matrix.md E1)."
)


def _unsupported_entry(kind: str, name, detail: str) -> dict:
    return {"kind": kind, "name": name, "detail": detail}


def _bad_synonyms(entry: dict, kind: str, name, unsupported: list) -> bool:
    """True (and records an unsupported entry) when synonyms is a non-list."""
    syn = entry.get("synonyms")
    if syn is None or isinstance(syn, list):
        return False
    unsupported.append(_unsupported_entry(
        kind, str(name), f"{kind} '{name}': synonyms must be a list, got {syn!r}"))
    return True


def _parse_dimension(d: dict, unsupported: list) -> dict | None:
    name, expr = d.get("name"), d.get("expr")
    if not name or expr is None:
        unsupported.append(_unsupported_entry(
            "dimension", name, f"dimension entry requires name and expr: {d!r}"))
        return None
    if _bad_synonyms(d, "dimension", name, unsupported):
        return None
    expr = str(expr)
    cls = classify_dimension_expr(expr)
    if cls["kind"] == "unsupported":
        unsupported.append(_unsupported_entry(
            "dimension", str(name), f"dimension '{name}': {cls['reason']}"))
        return None
    return {"name": str(name), "expr": expr, "kind": cls["kind"],
            "display_name": d.get("display_name"),
            "comment": d.get("comment"),
            "synonyms": list(d.get("synonyms") or []),
            "inner_agg": cls.get("inner_agg"),
            "inner_expr": cls.get("inner_expr"),
            "partition_by": cls.get("partition_by", [])}


def _parse_measure(m: dict, unsupported: list, warnings: list) -> dict | None:
    name, expr = m.get("name"), m.get("expr")
    if not name or expr is None:
        unsupported.append(_unsupported_entry(
            "measure", name, f"measure entry requires name and expr: {m!r}"))
        return None
    if _bad_synonyms(m, "measure", name, unsupported):
        return None
    expr = str(expr)
    cls = classify_measure_expr(expr)
    if cls["expr_kind"] == "unsupported":
        unsupported.append(_unsupported_entry(
            "measure", str(name), f"measure '{name}': {cls['reason']}"))
        return None
    window = None
    if m.get("window") is not None:
        window, problems = parse_window(m["window"], str(name))
        if problems:
            unsupported.extend(
                _unsupported_entry("measure", str(name), p) for p in problems)
            return None
        if window["density_check_required"]:
            warnings.append(_DENSITY_WARNING.format(
                name=name, raw_range=window["raw_range"],
                order=window["order"], unit=window["range"]["unit"]))
    return {"name": str(name), "expr": expr,
            "kind": "windowed" if window else cls["expr_kind"],
            "expr_kind": cls["expr_kind"],
            "agg_function": cls["agg_function"],
            "physical_ref": cls["physical_ref"],
            "distinct": cls["distinct"],
            "cross_refs": cls["cross_refs"],
            "lod_refs": cls["lod_refs"],
            "display_name": m.get("display_name"),
            "comment": m.get("comment"),
            "synonyms": list(m.get("synonyms") or []),
            "format": m.get("format"),
            "window": window}


def _check_unknown_top_keys(doc: dict, unsupported: list) -> None:
    for key in doc:
        if key not in _KNOWN_TOP_KEYS:
            unsupported.append(_unsupported_entry("unknown_key", None, str(key)))


def _resolve_source(doc: dict, unsupported: list) -> dict | None:
    src_raw = doc.get("source")
    if src_raw is None:
        unsupported.append(_unsupported_entry(
            "missing_source", None, "required top-level 'source' is missing"))
        return None
    src = classify_source(str(src_raw))
    if src is None:
        unsupported.append(_unsupported_entry(
            "unrecognized_source", None, str(src_raw)))
        return None
    return src


def _resolve_dimensions(doc: dict, unsupported: list) -> list[dict]:
    if "fields" in doc and "dimensions" in doc:
        unsupported.append(_unsupported_entry(
            "ambiguous_dimensions", None,
            "both 'fields:' and 'dimensions:' present — undocumented "
            "combination, refusing to guess precedence"))
        return []
    dims_raw = doc.get("fields", doc.get("dimensions")) or []
    if not isinstance(dims_raw, list):
        unsupported.append(_unsupported_entry(
            "dimensions", None,
            f"dimensions/fields must be a list, got {type(dims_raw).__name__}"))
        dims_raw = []
    dims: list[dict] = []
    for d in dims_raw:
        entry = _parse_dimension(d if isinstance(d, dict) else {}, unsupported)
        if entry:
            dims.append(entry)
    return dims


def _resolve_measures(doc: dict, unsupported: list, warnings: list) -> list[dict]:
    measures_raw = doc.get("measures") or []
    if not isinstance(measures_raw, list):
        unsupported.append(_unsupported_entry(
            "measures", None,
            f"measures must be a list, got {type(measures_raw).__name__}"))
        measures_raw = []
    measures: list[dict] = []
    for m in measures_raw:
        entry = _parse_measure(m if isinstance(m, dict) else {},
                               unsupported, warnings)
        if entry:
            measures.append(entry)
    return measures


def _resolve_materialization(doc: dict, unsupported: list):
    mat = doc.get("materialization")
    if mat is not None and not isinstance(mat, dict):
        unsupported.append(_unsupported_entry(
            "materialization", None,
            f"materialization must be a mapping, got {type(mat).__name__}"))
        return None
    return mat  # verbatim pass-through (no TS analog)


def parse_metric_view(yaml_text: str) -> dict:
    """Parse Metric View YAML (v0.1 or v1.1) into the parse-mv JSON contract.

    Never raises on bad input — every failure becomes an unsupported[] entry
    (the command exits non-zero when unsupported[] is non-empty). Both
    versions normalize into one shape; there is no downstream version
    branching.
    """
    unsupported: list[dict] = []
    warnings: list[str] = []
    result = {"version": None, "comment": None, "source": None, "joins": [],
              "dimensions": [], "measures": [], "filter": None,
              "materialization": None, "warnings": warnings,
              "unsupported": unsupported}
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        unsupported.append(_unsupported_entry("yaml_error", None, str(exc)))
        return result
    if not isinstance(doc, dict):
        unsupported.append(_unsupported_entry(
            "yaml_error", None, "top level is not a YAML mapping"))
        return result

    version = str(doc.get("version", "1.1"))  # GA default; YAML floats -> str
    if version not in _KNOWN_VERSIONS:
        unsupported.append(_unsupported_entry("unknown_version", None, version))
        return result
    result["version"] = version

    _check_unknown_top_keys(doc, unsupported)
    result["source"] = _resolve_source(doc, unsupported)
    joins_val = doc.get("joins")
    if joins_val is not None and not isinstance(joins_val, list):
        unsupported.append(_unsupported_entry(
            "joins", None,
            f"joins must be a list, got {type(joins_val).__name__}"))
        joins_val = None
    result["joins"] = parse_joins(joins_val, "source", unsupported)
    result["dimensions"] = _resolve_dimensions(doc, unsupported)
    result["measures"] = _resolve_measures(doc, unsupported, warnings)

    if not result["dimensions"] and not result["measures"]:
        warnings.append("Metric View declares no dimensions and no measures")

    flt = doc.get("filter")
    result["filter"] = str(flt).strip() if flt is not None else None
    result["comment"] = doc.get("comment")
    result["materialization"] = _resolve_materialization(doc, unsupported)
    return result
