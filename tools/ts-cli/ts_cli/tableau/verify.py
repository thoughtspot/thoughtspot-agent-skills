"""Source↔output verification gate for the Tableau converter.

Diffs the *parsed* Tableau workbook (``ts tableau parse`` output) against the
*generated* ThoughtSpot Model TML to catch two failure classes coverage-from-
the-TWB-alone cannot see:

  - **Silent drops** — a physical table, join, or translatable formula that
    existed in the workbook but never made it into the generated TML.
  - **Mistranslations** — a formula that WAS emitted, but whose ThoughtSpot
    expression barely resembles its Tableau source (a candidate for manual
    review, not necessarily wrong, but worth a human's eyes).

Harvested from a parallel Tableau converter's ``tableau_verify.py`` (PR #252,
closed) and reimplemented here against OUR data shapes and OUR modules — not
a wholesale port. In particular:

  - Formula-tier classification is delegated entirely to
    :mod:`ts_cli.tableau.classify` (``classify_formulas``), so this module
    NEVER re-implements the translatable/untranslatable verdict. A formula
    tiered into ``classify.UNTRANSLATABLE_TIERS`` (untranslatable, geospatial,
    circular, orphan, parameter_query, row_offset_ambiguous,
    window_ambiguous) is *expected* to be absent from ``model.formulas`` and
    is never counted as a drop.

    Note: unlike the reference implementation, our ``classify.py`` has no
    separate "query-time" tier. Its ``TRANSLATABLE_TIERS`` includes the tiers
    matching Tableau's RANK/TOTAL functions (``pass_through``) — our
    translator emits real ThoughtSpot ``rank``/``group_aggregate`` formulas
    for these into ``model.formulas`` (ThoughtSpot's formula language
    supports them as genuine stored Model formulas, unlike Tableau's
    answer/table-calc-only equivalents).

    WINDOW_* (moving) and the row-offset family (LOOKUP/INDEX/FIRST/LAST)
    were formerly mistiered as translatable too, but ``translate_formulas()``
    never actually converted them — they passed straight through as raw
    Tableau syntax and hard-failed ThoughtSpot import (error 14516, "Search
    did not find '<FUNC> ( ... )'"). Fixed: these now reject at translate
    time (``validate.py``) and tier ``window_ambiguous``/
    ``row_offset_ambiguous`` — both are genuinely translatable in the
    abstract (``moving_*``/``first_value``/``last_value`` exist), but need a
    sort/partition attribute from the worksheet's "Compute Using" addressing
    that this pipeline has no wiring to resolve automatically; see
    tableau-formula-translation.md. ``SIZE()`` is the one row-offset function
    with a context-free translation and is tiered ``row_offset_native``
    (genuinely translated, not omitted).

    RUNNING_* (cumulative) has the identical latent defect — classified
    "cumulative" (translatable) but not actually converted by
    ``translate_formulas()`` today — tracked separately, out of scope here.

  - TML validity is delegated entirely to :mod:`ts_cli.tml_lint`
    (``lint_tml`` for the I1/I2/I4/I5/I8 invariants). This module never
    re-implements TML invariant logic.

    Model↔table-TML dangling-reference checking is provided separately by
    ``ts tml lint --dir`` (``lint_cross_references``) and is intentionally
    out of scope here.

Pure functions only — no I/O, no network, no ThoughtSpot/Tableau connection.
Backs ``ts tableau verify``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.tableau.classify import (
    TRANSLATABLE_TIERS,
    UNTRANSLATABLE_TIERS,
    classify_formulas,
)
from ts_cli.tml_lint import lint_tml

# ---------------------------------------------------------------------------
# Finding / severity helpers
# ---------------------------------------------------------------------------


def _finding(severity: str, message: str) -> dict:
    return {"severity": severity, "message": message}


def _severity(findings: list[dict]) -> str:
    """Highest severity present, else 'OK'."""
    sevs = {f.get("severity") for f in findings}
    if "ERROR" in sevs:
        return "ERROR"
    if "WARNING" in sevs:
        return "WARNING"
    return "OK"


# ---------------------------------------------------------------------------
# Datasource selection — `ts tableau verify` checks ONE model at a time
# (mirroring the one-model-per-datasource migration flow), so a `parsed`
# input carrying multiple datasources must be narrowed to the one this
# model_tml corresponds to.
# ---------------------------------------------------------------------------


def _normalize_ds_name(s: str) -> str:
    return re.sub(r"[\s/\\._-]+", " ", s or "").strip().lower()


def _flatten_datasource(parsed: dict, model_name: str) -> dict:
    """A `parsed` dict with no `datasources[]` — a flattened single-datasource
    shape (top-level `tables`/`columns`/`joins`/`calculated_fields`, or the
    `formulas` alias for `calculated_fields`)."""
    return {
        "name": parsed.get("name", model_name),
        "tables": parsed.get("tables", []),
        "sql_views": parsed.get("sql_views", []),
        "columns": parsed.get("columns", []),
        "joins": parsed.get("joins", []),
        "calculated_fields": parsed.get("calculated_fields", parsed.get("formulas", [])),
        "orphan_calcs": parsed.get("orphan_calcs", []),
        "calc_map": parsed.get("calc_map", {}),
    }


def _pick_datasource(parsed: dict, model_name: str) -> dict:
    """Select the one datasource-shaped dict this model_tml should be checked
    against. Full `ts tableau parse` output has `datasources: [...]`; with a
    single entry it's unambiguous, with several the best name match to
    `model_name` wins, falling back to the first (that fallback is a
    deliberate best-effort choice, not a silent failure — the caller's report
    always names the datasource actually used, in `summary.datasource`)."""
    if "datasources" not in parsed:
        return _flatten_datasource(parsed, model_name)

    datasources = parsed.get("datasources") or []
    if not datasources:
        return _flatten_datasource({}, model_name)
    if len(datasources) == 1:
        return datasources[0]

    target = _normalize_ds_name(model_name)
    for ds in datasources:
        if _normalize_ds_name(ds.get("name", "")) == target:
            return ds
    return datasources[0]


# ---------------------------------------------------------------------------
# Formula normalization + LCS similarity
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""\[[^\]]+\] | '(?:[^'\\]|\\.)*' | "(?:[^"\\]|\\.)*" | \d+\.?\d* |
        [a-zA-Z_]\w* | [<>=!]+ | [(),+\-*/] | \S""",
    re.VERBOSE,
)

# Tableau function keywords whose ThoughtSpot rendering differs in spelling
# (mirrors ts_cli/tableau/functions.py's _build_function_map — kept in sync
# manually since that map renders full call templates, not bare tokens).
# Value is the token(s) the ThoughtSpot side actually emits; empty = dropped.
_RENAME_TOKENS: dict[str, list[str]] = {
    "countd": ["unique", "count"],
    "avg": ["average"],
    "zn": ["ifnull"],
    "len": ["strlen"],
    "ceiling": ["ceil"],
    "str": ["to_string"],
    "float": ["to_double"],
    "find": ["strpos"],
    "log": ["log10"],
    "power": ["pow"],
    "end": [],
    "elseif": ["else", "if"],
}

# Deliberately NOT mapped: DATEDIFF/DATEADD/DATETRUNC/DATEPART/DATENAME. Their
# ThoughtSpot function name depends on a runtime unit argument (e.g.
# DATEDIFF('day', ...) -> diff_days(...), DATEDIFF('month', ...) ->
# diff_months(...)), so no static token map can resolve it. Formulas using
# these score lower here and surface for manual review — the correct
# fallback for a heuristic, not a bug.


def _norm_bracket_ref(inner: str, id2cap: Optional[dict]) -> str:
    if id2cap and inner in id2cap:
        return f"[formula::{id2cap[inner].strip().lower()}]"
    if inner.lower().startswith("formula_"):
        return f"[formula::{inner[8:].strip().lower()}]"
    if "::" in inner:
        return f"[{inner.split('::', 1)[1].strip().lower()}]"
    return f"[{inner.strip().lower()}]"


def _norm_literal(inner: str) -> str:
    if re.fullmatch(r"-?\d+", inner):
        return inner
    try:
        return str(float(inner))
    except ValueError:
        return inner.lower()


def normalize_expr(expr: str, id2cap: Optional[dict] = None) -> list[str]:
    """Token-normalize a formula expression (raw Tableau OR translated TML)
    for similarity comparison.

    Strips ``//`` comments, lower-cases identifiers, collapses bracket
    references to their bare column/formula name (dropping table qualifiers
    and the ``formula_`` cross-reference prefix so both sides read the same
    way), and renames the handful of Tableau function keywords whose
    ThoughtSpot spelling differs (``_RENAME_TOKENS``). ``id2cap`` (Tableau
    side only — pass the datasource's ``calc_map``) resolves an internal
    ``[Calculation_NNN]`` cross-reference to its caption before bracket-
    normalizing it, so it lines up with the TML's ``[formula_<Caption>]``.
    """
    expr = re.sub(r"//[^\n]*", "", expr or "")
    out: list[str] = []
    for tok in _TOKEN_RE.findall(expr):
        if tok.startswith("[") and tok.endswith("]"):
            out.append(_norm_bracket_ref(tok[1:-1], id2cap))
        elif tok[:1] in "'\"":
            out.append(_norm_literal(tok[1:-1]))
        else:
            low = tok.lower()
            out.extend(_RENAME_TOKENS.get(low, [low]))
    return out


def _similarity(a: list[str], b: list[str]) -> float:
    """LCS-based token similarity in [0, 1] (Dice coefficient over the LCS
    length: ``2 * lcs / (len(a) + len(b))``). Falls back to a Jaccard set
    ratio above ~400 tokens a side, where the O(mn) DP table would be costly
    and by that size token-set overlap is a fine proxy."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    m, n = len(a), len(b)
    if m > 400 or n > 400:
        sa, sb = set(a), set(b)
        return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        ai = a[i - 1]
        row, prev_row = dp[i], dp[i - 1]
        for j in range(1, n + 1):
            row[j] = prev_row[j - 1] + 1 if ai == b[j - 1] else max(prev_row[j], row[j - 1])
    return (2.0 * dp[m][n]) / (m + n)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _formula_name(cf: dict) -> str:
    return cf.get("caption") or cf.get("name", "")


def _table_check(ds: dict, model_tables: list[dict]) -> tuple[list[dict], dict]:
    """Physical tables and custom-SQL relations, both represented in
    `model_tables[]` (a SQL View becomes its own model_tables entry — see
    model_builder.py's `_sql_view_model_tables` — so both classes are checked
    against the same name set)."""
    twb_tables = {t.get("name", "") for t in ds.get("tables", []) if t.get("name")}
    twb_sql_views = {v.get("name", "") for v in ds.get("sql_views", []) if v.get("name")}
    model_table_names = {t.get("name", "") for t in model_tables if isinstance(t, dict)}
    stats = {
        "tables_in_parse": len(twb_tables),
        "sql_views_in_parse": len(twb_sql_views),
        "tables_in_model": len(model_table_names),
    }

    findings: list[dict] = []
    missing_tables = sorted(twb_tables - model_table_names)
    if missing_tables:
        findings.append(_finding(
            "ERROR", f"Physical table(s) dropped from the model: {', '.join(missing_tables)}"))
    missing_sql_views = sorted(twb_sql_views - model_table_names)
    if missing_sql_views:
        findings.append(_finding(
            "ERROR",
            f"Custom-SQL relation(s) dropped from the model: {', '.join(missing_sql_views)}"))
    return findings, stats


def _join_check(ds: dict, model_tables: list[dict]) -> tuple[list[dict], dict]:
    twb_joins = len(ds.get("joins", []))
    model_joins = sum(len(t.get("joins") or []) for t in model_tables if isinstance(t, dict))
    stats = {"joins_in_parse": twb_joins, "joins_in_model": model_joins}

    findings: list[dict] = []
    if model_joins < twb_joins:
        findings.append(_finding(
            "WARNING",
            f"{twb_joins - model_joins} join(s) in the parsed workbook not represented "
            f"in model_tables"))
    return findings, stats


def _formula_drop_check(model: dict, tiers: dict[str, str]) -> tuple[list[dict], dict, list[str]]:
    """Every TRANSLATABLE-tiered formula (per classify.py) must have a
    matching model.formulas[] entry; an UNTRANSLATABLE-tiered one is expected
    to be absent and is never checked here."""
    translatable = sorted(n for n, t in tiers.items() if t in TRANSLATABLE_TIERS)
    untranslatable_count = sum(1 for t in tiers.values() if t in UNTRANSLATABLE_TIERS)
    model_formula_names = {
        f.get("name", "").strip().lower() for f in model.get("formulas", []) or []
        if isinstance(f, dict)
    }
    stats = {
        "translatable_formulas": len(translatable),
        "untranslatable_formulas": untranslatable_count,
        "formulas_in_model": len(model_formula_names),
    }

    missing_formulas = [n for n in translatable if n.strip().lower() not in model_formula_names]
    findings: list[dict] = []
    if missing_formulas:
        findings.append(_finding(
            "ERROR",
            f"{len(missing_formulas)} translatable formula(s) missing from model.formulas "
            f"(possible silent drop): {', '.join(missing_formulas)}"))
    return findings, stats, missing_formulas


def check_structural(ds: dict, model: dict, tiers: dict[str, str]) -> dict:
    """Datasources→model, physical tables/custom-SQL→model_tables, join
    counts, and translatable-formula drop detection. Each sub-area is its own
    helper (`_table_check`/`_join_check`/`_formula_drop_check`) purely to keep
    this function's own complexity low — the checks themselves are independent."""
    model_tables = model.get("model_tables", []) or []
    table_findings, table_stats = _table_check(ds, model_tables)
    join_findings, join_stats = _join_check(ds, model_tables)
    formula_findings, formula_stats, missing_formulas = _formula_drop_check(model, tiers)

    return {
        "stats": {**table_stats, **join_stats, **formula_stats},
        "findings": table_findings + join_findings + formula_findings,
        "missing_formulas": missing_formulas,
    }


def check_formula_equivalence(ds: dict, model: dict, tiers: dict[str, str]) -> dict:
    """Per-translatable-formula token-level similarity between the raw
    Tableau expression and its TML translation. Untranslatable formulas are
    recorded as SKIPPED, never compared or flagged."""
    findings: list[dict] = []
    comparisons: list[dict] = []
    calc_map = ds.get("calc_map", {})
    model_formulas = {
        f.get("name", "").strip().lower(): f for f in model.get("formulas", []) or []
        if isinstance(f, dict)
    }

    for cf in ds.get("calculated_fields", []):
        name = _formula_name(cf)
        tier = tiers.get(name, "untranslatable")
        if tier in UNTRANSLATABLE_TIERS:
            comparisons.append({"name": name, "status": "SKIPPED (untranslatable)",
                                "similarity": None})
            continue

        tf = model_formulas.get(name.strip().lower())
        if tf is None:
            # Already surfaced (with the full missing-name list) as a
            # structural ERROR — record it here for the formula-level report
            # without double-counting the error.
            comparisons.append({"name": name, "status": "MISSING", "similarity": 0.0})
            continue

        sim = _similarity(
            normalize_expr(cf.get("formula", ""), id2cap=calc_map),
            normalize_expr(tf.get("expr", "")),
        )
        if sim >= 0.85:
            status = "MATCH"
        elif sim >= 0.5:
            status = "PARTIAL"
            findings.append(_finding(
                "WARNING", f'Formula "{name}" partial match ({sim:.0%}) with its '
                f'Tableau source — review the translation'))
        else:
            status = "LOW"
            findings.append(_finding(
                "WARNING", f'Formula "{name}" low similarity ({sim:.0%}) with its '
                f'Tableau source — likely mistranslated'))
        comparisons.append({"name": name, "status": status, "similarity": sim})

    return {"comparisons": comparisons, "findings": findings}


def check_validity(model_tml: dict) -> list[dict]:
    """Reuses tml_lint.py entirely — no invariant logic lives here."""
    return [_finding("ERROR", msg) for msg in lint_tml(model_tml)]


def check_limitation_coverage(tiers: dict[str, str]) -> dict:
    """Advisory in our flow: `ts tableau verify` has no `--limitations`/report-
    list input today (the migration report is generated later, by the skill,
    not by this pure module), so this check can only report HOW MANY
    untranslatable formulas were detected — it cannot confirm each was
    documented anywhere. Always WARN, never ERROR, until a limitations-list
    input exists."""
    untranslatable_names = sorted(n for n, t in tiers.items() if t in UNTRANSLATABLE_TIERS)
    stats = {"untranslatable_detected": len(untranslatable_names),
             "untranslatable_names": untranslatable_names}
    findings = []
    if untranslatable_names:
        findings.append(_finding(
            "WARNING",
            f"{len(untranslatable_names)} untranslatable formula(s) detected (advisory only "
            f"— no limitations/report list was supplied to confirm each was documented)."))
    return {"stats": stats, "findings": findings}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def verify_conversion(parsed: dict, model_tml: dict) -> dict:
    """Diff a parsed Tableau workbook against the generated Model TML.

    ``parsed`` is a ``ts tableau parse`` output (``{"datasources": [...]}``)
    or a flattened single-datasource shape (top-level ``tables``/``columns``/
    ``joins``/``calculated_fields`` — or ``formulas`` as an alias for
    ``calculated_fields``). ``model_tml`` is the generated Model TML dict
    (``{"model": {...}}`` or already-flattened).

    Model↔table-TML dangling-reference checking is provided separately by
    ``ts tml lint --dir`` (``lint_cross_references``) and is intentionally
    out of scope here.

    Returns ``{"ok": bool, "checks": [...], "summary": {...}}`` — ``ok`` is
    False iff any check carries an ERROR-severity finding.
    """
    model = (model_tml.get("model", model_tml) or {}) if isinstance(model_tml, dict) else {}
    ds = _pick_datasource(parsed or {}, model.get("name", ""))

    classified = classify_formulas(
        ds.get("calculated_fields", []), orphan_calcs=set(ds.get("orphan_calcs", [])))
    tiers = {c["name"]: c["tier"] for c in classified["formulas"]}

    structural = check_structural(ds, model, tiers)
    formula_eq = check_formula_equivalence(ds, model, tiers)
    validity_findings = check_validity(model_tml)
    limitation = check_limitation_coverage(tiers)

    checks = [
        {"name": "structural", "severity": _severity(structural["findings"]),
         "findings": structural["findings"], "stats": structural["stats"]},
        {"name": "formula_equivalence", "severity": _severity(formula_eq["findings"]),
         "findings": formula_eq["findings"], "comparisons": formula_eq["comparisons"]},
        {"name": "validity", "severity": _severity(validity_findings),
         "findings": validity_findings},
        {"name": "limitation_coverage", "severity": _severity(limitation["findings"]),
         "findings": limitation["findings"], "stats": limitation["stats"]},
    ]

    all_findings = [f for c in checks for f in c["findings"]]
    n_errors = sum(1 for f in all_findings if f["severity"] == "ERROR")
    n_warnings = sum(1 for f in all_findings if f["severity"] == "WARNING")
    summary = {
        "datasource": ds.get("name", ""),
        "model": model.get("name", ""),
        "errors": n_errors,
        "warnings": n_warnings,
        **structural["stats"],
    }
    return {"ok": n_errors == 0, "checks": checks, "summary": summary}
