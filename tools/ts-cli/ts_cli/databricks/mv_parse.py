"""Databricks Metric View YAML -> structured dict (`ts databricks parse-mv`).

Pure functions: YAML text in, JSON-ready dict out. No I/O, no network calls —
trivially unit-testable. stdlib + PyYAML only (Genie-vendorable — see
package docstring).

Schema reference: agents/shared/schemas/databricks-metric-view.md.
Classification rules: agents/shared/mappings/ts-databricks/ts-from-databricks-rules.md.
"""
from __future__ import annotations

import re

import yaml

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_sql_comments(expr: str) -> str:
    """Strip -- line and /* */ block comments before classification.

    Naive w.r.t. comment markers inside string literals — acceptable per the
    rules file (classification only; the raw expr is preserved separately).
    """
    return _BLOCK_COMMENT_RE.sub(" ", _LINE_COMMENT_RE.sub("", expr)).strip()


def _split_fqn(s: str) -> list[str]:
    """Split a dotted identifier on '.', respecting backtick-quoted segments."""
    parts: list[str] = []
    buf: list[str] = []
    in_backtick = False
    for ch in s:
        if ch == "`":
            in_backtick = not in_backtick
        elif ch == "." and not in_backtick:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


_IDENT_SEGMENT_RE = re.compile(r"^[A-Za-z_][\w$]*$")


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
    low = stripped.lower()
    if low.startswith(("(select", "(with")) or low.startswith(("select ", "with ")):
        return {"kind": "sql_query", "raw": stripped,
                "parenthesized": stripped.startswith("(")}
    parts = _split_fqn(stripped)
    for part in parts:
        # A backtick-quoted segment (now unquoted by _split_fqn) may hold any
        # non-empty text; a bare segment must be a plain identifier.
        bare = part if "`" not in stripped else None
        if not part:
            return None
        if bare is not None and not _IDENT_SEGMENT_RE.match(part):
            return None
    return {"kind": "table_fqn", "raw": stripped,
            "parts": parts if len(parts) == 3 else None,
            "needs_live_check": True}


# ---------------------------------------------------------------------------
# Window spec (measures[].window) — all five range values live-verified
# 2026-07-08/09; see docs/audit/2026-07-08-dbx-window-claim-matrix.md and
# databricks-metric-view.md "Window with Offset".
# ---------------------------------------------------------------------------

_RANGE_FIXED = {"current", "cumulative", "all"}
_RANGE_RE = re.compile(
    r"^(trailing|leading)\s+(\d+)\s+([a-z]+)(?:\s+(inclusive|exclusive))?$")
_OFFSET_RE = re.compile(r"^(-\d+)\s+([a-z]+)$")
_WINDOW_KEYS = {"order", "range", "semiadditive", "offset"}
_SEMIADDITIVE_VALUES = {"last", "first"}


def parse_range(raw) -> dict | None:
    """Parse a window `range:` value into {type, n, unit, anchor}.

    Fixed types (current|cumulative|all) reject the inclusive/exclusive
    modifier; trailing/leading default to exclusive when it is omitted
    (live-verified C2, 2026-07-08).
    """
    s = str(raw).strip().lower()
    if s in _RANGE_FIXED:
        return {"type": s, "n": None, "unit": None, "anchor": None}
    m = _RANGE_RE.match(s)
    if not m:
        return None
    return {"type": m.group(1), "n": int(m.group(2)), "unit": m.group(3),
            "anchor": m.group(4) or "exclusive"}


def parse_offset(raw) -> dict | None:
    """Parse a window `offset:` value ('-N unit') into {n, unit}."""
    m = _OFFSET_RE.match(str(raw).strip().lower())
    if not m:
        return None
    return {"n": int(m.group(1)), "unit": m.group(2)}


def parse_window(window_val, measure_name: str) -> tuple[dict | None, list[str]]:
    """Parse a measure's `window:` block. Returns (window_dict, problems).

    On any problem returns (None, [messages]) — the caller records each
    message as an unsupported[] entry (fail loud, never a silent drop).
    density_check_required implements BL-098 item 1: trailing/leading frames
    are date-interval on Databricks but translate to row-positional
    moving_sum on ThoughtSpot — the numbers diverge on gapped data (E1).
    """
    problems: list[str] = []
    if (not isinstance(window_val, list) or len(window_val) != 1
            or not isinstance(window_val[0], dict)):
        return None, [f"measure '{measure_name}': window must be a "
                      f"single-entry list of mappings"]
    w = window_val[0]
    unknown = sorted(set(w) - _WINDOW_KEYS)
    if unknown:
        problems.append(f"measure '{measure_name}': unknown window key(s): "
                        f"{', '.join(unknown)}")
    order = w.get("order")
    if not order:
        problems.append(f"measure '{measure_name}': window missing required 'order'")
    raw_range = w.get("range")
    rng = parse_range(raw_range) if raw_range is not None else None
    if rng is None:
        problems.append(f"measure '{measure_name}': unrecognized window "
                        f"range: {raw_range!r}")
    semi = w.get("semiadditive")
    if semi not in _SEMIADDITIVE_VALUES:
        problems.append(f"measure '{measure_name}': window requires "
                        f"semiadditive last|first, got {semi!r}")
    raw_offset = w.get("offset")
    offset = None
    if raw_offset is not None:
        offset = parse_offset(raw_offset)
        if offset is None:
            problems.append(f"measure '{measure_name}': unrecognized window "
                            f"offset: {raw_offset!r}")
    if problems:
        return None, problems
    return {
        "order": order,
        "range": rng,
        "raw_range": str(raw_range).strip(),
        "semiadditive": semi,
        "offset": offset,
        "raw_offset": None if raw_offset is None else str(raw_offset).strip(),
        "density_check_required": rng["type"] in ("trailing", "leading"),
    }, []


# ---------------------------------------------------------------------------
# Expression classification — mirrors the decision trees in
# ts-from-databricks-rules.md (Dimension / Measure classification sections).
# Classification only; translation to TS formula text is PR 3's job.
# ---------------------------------------------------------------------------

_IDENT = r"(?:`[^`]+`|[A-Za-z_][\w$]*)"
_DOT_PATH = rf"{_IDENT}(?:\.{_IDENT})*"
_DIRECT_RE = re.compile(rf"^{_DOT_PATH}$")
_LOD_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*\((.*)\)\s+OVER\s*\(\s*PARTITION\s+BY\s+(.+)\)\s*$",
    re.IGNORECASE | re.DOTALL)
_OVER_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)
_SUBQUERY_RE = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_COUNT_STAR_RE = re.compile(r"^COUNT\s*\(\s*\*\s*\)$", re.IGNORECASE)
_FILTER_WHERE_RE = re.compile(r"\bFILTER\s*\(\s*WHERE\b", re.IGNORECASE)
_SIMPLE_AGG_RE = re.compile(
    rf"^([A-Za-z_]\w*)\s*\(\s*(DISTINCT\s+)?({_DOT_PATH})\s*\)$",
    re.IGNORECASE)
_MEASURE_REF_RE = re.compile(r"\bMEASURE\s*\(\s*(`[^`]+`|[A-Za-z_]\w*)\s*\)",
                             re.IGNORECASE)
_ANY_VALUE_RE = re.compile(r"\bANY_VALUE\s*\(\s*(`[^`]+`|[A-Za-z_]\w*)\s*\)",
                           re.IGNORECASE)
_WINDOW_EXTRAS_RE = re.compile(r"\b(ORDER\s+BY|ROWS|RANGE|GROUPS)\b", re.IGNORECASE)


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` at paren depth 0 (partition lists may contain calls)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def extract_cross_refs(expr: str) -> tuple[list[str], list[str]]:
    """Return (MEASURE() names, ANY_VALUE() names) in source order."""
    e = strip_sql_comments(expr)
    refs = [m.group(1).strip("`") for m in _MEASURE_REF_RE.finditer(e)]
    lod = [m.group(1).strip("`") for m in _ANY_VALUE_RE.finditer(e)]
    return refs, lod


def classify_dimension_expr(expr: str) -> dict:
    """Classify a dimension expr: direct | computed | lod_window | unsupported."""
    e = strip_sql_comments(expr)
    if _SUBQUERY_RE.search(e):
        return {"kind": "unsupported", "reason": "subquery in dimension expr"}
    m = _LOD_RE.match(e)
    if m:
        inner_expr = m.group(2).strip()
        partition_tail = m.group(3)
        # Reject shapes _LOD_RE over-matches: running/frame windows
        # (ORDER BY / ROWS / RANGE / GROUPS in the OVER clause), argless
        # ranking functions, and expressions spanning multiple windows.
        if (not inner_expr or _OVER_RE.search(inner_expr)
                or _WINDOW_EXTRAS_RE.search(partition_tail)):
            return {"kind": "unsupported",
                    "reason": "window function without the recognized "
                              "AGG(...) OVER (PARTITION BY ...) LOD shape"}
        return {"kind": "lod_window",
                "inner_agg": m.group(1).upper(),
                "inner_expr": inner_expr,
                "partition_by": _split_top_level(partition_tail)}
    if _OVER_RE.search(e):
        return {"kind": "unsupported",
                "reason": "window function without the recognized "
                          "AGG(...) OVER (PARTITION BY ...) LOD shape"}
    if _DIRECT_RE.match(e):
        return {"kind": "direct"}
    return {"kind": "computed"}


def classify_measure_expr(expr: str) -> dict:
    """Classify a measure expr per the rules-file decision tree.

    expr_kind: simple | count_distinct | count_star | conditional |
    complex_cross_measure | complex | unsupported. cross_refs/lod_refs are
    always recorded (PR 3's dependency DAG reads them on every kind).
    """
    e = strip_sql_comments(expr)
    refs, lod = extract_cross_refs(e)
    out = {"expr_kind": None, "agg_function": None, "physical_ref": None,
           "distinct": False, "cross_refs": refs, "lod_refs": lod}
    if _SUBQUERY_RE.search(e):
        out["expr_kind"] = "unsupported"
        out["reason"] = "subquery in measure expr"
        return out
    if _COUNT_STAR_RE.match(e):
        out["expr_kind"] = "count_star"
        return out
    if _FILTER_WHERE_RE.search(e):
        out["expr_kind"] = "conditional"
        return out
    if refs or lod:
        out["expr_kind"] = "complex_cross_measure"
        return out
    m = _SIMPLE_AGG_RE.match(e)
    if m:
        agg = m.group(1).upper()
        distinct = bool(m.group(2))
        col = m.group(3)
        if agg == "COUNT" and distinct:
            out["expr_kind"] = "count_distinct"
        else:
            out["expr_kind"] = "simple"
            out["agg_function"] = agg
            out["distinct"] = distinct
        out["physical_ref"] = col
        return out
    out["expr_kind"] = "complex"
    return out


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
    be a real expression (null/boolean values are problems, not literal
    "None"/"True" clauses).
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
    if on_val is None or isinstance(on_val, bool):
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
