"""Naming and classification for Snowflake Semantic View constructs.

Split out of ``sv_translate`` when that module crossed the 1000-line gate —
module-per-concern, the repo's documented answer (BL-069 pattern). Everything
here answers "what is this construct called, and what kind of thing is it?",
which is upstream of every expression the translator builds and is re-exported
from ``sv_translate`` so callers and tests import unchanged.
"""
from __future__ import annotations

import re

def build_node_id_map(parsed: dict) -> dict[str, str]:
    """Map each SV table alias -> its ThoughtSpot model node id (role-play aware).

    A physical table referenced by more than one SV table is *reused* — a
    role-playing pattern (e.g. one ``USER`` table played as ``CASE_OWNER``,
    ``INCIDENT_OWNER`` and ``INCIDENT_RESOLVED_BY``). Each reused instance whose
    alias differs from the physical name becomes its own node, identified by the
    alias, so column references and joins stay unambiguous. A single-use table
    (or the one instance whose alias equals the physical name) uses the physical
    table name as its node id — no alias needed.

    Returns ``{sv_alias: node_id}``. Keyed by the alias exactly as parsed."""
    tables = parsed.get("tables", [])
    phys_count: dict[str, int] = {}
    for t in tables:
        phys_count[t["name"]] = phys_count.get(t["name"], 0) + 1
    node_of: dict[str, str] = {}
    for t in tables:
        alias, phys = t["alias"], t["name"]
        reused = phys_count[phys] > 1
        node_of[alias] = alias if (reused and alias != phys) else phys
    return node_of


def display_title(entry: dict, *, promote_synonym: bool = False) -> str:
    """The ThoughtSpot display name for an SV construct — title-cased declared
    name, or the first synonym when ``promote_synonym`` is set.

    ``promote_synonym`` defaults to **False**. On a Semantic View this
    converter did not author, ``with synonyms=(...)`` means *alternate NL
    names* — promoting the first one over the declared name destroys the
    logical identifier (BL-179: 29 of 36 named constructs renamed on the
    TPC-DS fixture; `PHYSICAL_QUANTITY` became `units`). Provenance is not
    knowable from the DDL, so the safe reading is the default and the
    round-trip case opts in.

    Promotion is not needed to round-trip a display name either: `build-sv`
    derives the construct name as ``to_snake(display_name)``, so title-casing
    it back recovers the name. Opt in only when the display name does not
    survive that transform (`"YTD Sales"` -> `ytd_sales` -> `"Ytd Sales"`).

    THE one naming path. ``sv_build_model`` mints every formula id as
    ``formula_<display_title>`` and re-exports this function rather than
    restating the rule, because two independent naming paths are exactly what
    BL-178 defect 2 was: the resolver emitted ``[formula_<sql_token>]`` while the
    builder declared ``id: formula_<display title>``, so every metric-on-fact
    reference dangled. Anything that needs to *predict* a minted id must call
    this."""
    synonyms = entry.get("synonyms") or []
    if promote_synonym and synonyms:
        return synonyms[0]
    return entry["name"].replace("_", " ").title()


def construct_formula_id(
    construct: dict, *, promote_synonym: bool = False,
) -> str:
    """The `formulas[].id` build-model will mint for a parsed SV construct.

    ``construct`` is a parse-sv dimension/fact/metric dict (declared name in
    ``source_column``); the translated entry that reaches build-model carries the
    same name under ``name``."""
    return "formula_" + display_title(
        {"name": construct["source_column"],
         "synonyms": construct.get("synonyms")},
        promote_synonym=promote_synonym)


_NON_NUMERIC_HEAD_RE = re.compile(
    r"^\s*(?:"
    r"concat|to_char|to_varchar|to_date|to_time|to_timestamp[a-z_]*|"
    r"substr|substring|left|right|lpad|rpad|upper|lower|trim|ltrim|rtrim|"
    r"replace|split[a-z_]*|date_trunc|dateadd|datediff|last_day|next_day|"
    r"current_date|current_timestamp|startswith|endswith|contains|like|"
    r"iff|decode|to_boolean"
    r")\s*\(",
    re.IGNORECASE)

_COMPARISON_RE = re.compile(r"(?<![<>!])(?:[<>]=?|=|!=|<>)(?!=)")


def fact_column_type(fact: dict) -> str:
    """MEASURE or ATTRIBUTE for one parsed SV fact (BL-181).

    A Semantic View's ``facts()`` block *is* the signal: it declares row-level
    numeric values, while ``dimensions()`` declares categorical ones. Snowflake
    draws that line by which block a construct sits in — so a fact defaults to
    MEASURE, and previously every fact was hardcoded ATTRIBUTE, which declared
    quantities, prices and profit to be categorical.

    ATTRIBUTE is returned only when the declared expression is *evidently*
    non-numeric: it is headed by a string/date/boolean-producing function, or it
    is a bare comparison. A `CASE` is left as MEASURE only when it has no
    string literal in it.

    This deliberately does NOT try to infer intent from column names. A source
    that declares an employee number in ``facts()`` gets a summable measure,
    because that is what the source declared; `build-model` reports the split so
    the skill's review step can catch a mis-declared one.
    """
    expr = (fact.get("expr") or "").strip()
    if not expr:
        return "MEASURE"          # passthrough of a physical numeric column
    if _NON_NUMERIC_HEAD_RE.match(expr):
        return "ATTRIBUTE"
    if expr.upper().startswith("CASE") and "'" in expr:
        return "ATTRIBUTE"        # CASE returning string labels
    if "||" in expr:
        return "ATTRIBUTE"        # string concatenation
    if _COMPARISON_RE.search(expr) and not expr.upper().startswith("CASE"):
        return "ATTRIBUTE"        # a predicate, not a quantity
    return "MEASURE"
