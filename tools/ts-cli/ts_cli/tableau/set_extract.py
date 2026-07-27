"""Tableau Set detection + classification from TWB XML (BL-067 part 1, BL-131).

Split out of ``twb.py`` (module-per-concern, BL-069 pattern) purely to keep that
module's line count in budget — ``parse_twb`` still owns wiring ``sets[]`` into
its per-datasource output; this module owns the ``<group>``-scanning itself.

Classifies each real Set (a top-level ``<group>`` element — see
``_NON_SET_GROUPFILTER_FUNCTIONS`` for the two shapes that are NOT Sets) by the
exact shape documented in
``agents/cli/ts-convert-from-tableau/references/step-5-tml-generation.md``
"Tableau Sets -> ThoughtSpot column sets (Phase 2a/2b/2c)", and captures every
field that section's emission rules need. ``ts_cli.tableau.sets.build_cohort_tml``
(BL-067 part 2) turns one of ``extract_sets``'s dicts into a ``*.cohort.tml``.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

# Tableau's internal combined-field mechanism for multi-field dashboard
# Actions/Tooltips is ALSO written as a datasource-scoped <group> element
# (auto-named "Action (...)"/"Tooltip (...)"), but its <groupfilter> is a
# 'crossjoin' of several level-members children — a cross-product key for
# action-target matching, not a user-created Set. Excluding it is what keeps
# this an accurate Set count (live-reproduced: 469 of these vs. ~120 real
# Sets across the test corpus) — the "unrelated <group> usage" build-model
# must not count.
_NON_SET_GROUPFILTER_FUNCTIONS = {"crossjoin"}


def count_native_sets(root: ET.Element) -> int:
    """Count native Tableau Sets (BL-131) — real user-created ``<group>``
    elements under a datasource.

    Covers every Set flavor the skill's Phase-2a/2b/2c set->cohort step
    handles (static union/member/except, level-members, Top-N/Bottom-N
    ``function='end'``, condition-based ``function='filter'``), since
    ``build-model``'s automated GENERATE pass did not perform that
    conversion when this counter was first added — see SKILL.md Step 5b.

    Excludes two ``<group>`` shapes that are not Sets at all: Tableau's
    internal ``crossjoin`` combined-field mechanism (used for multi-field
    dashboard Actions/Tooltips — see ``_NON_SET_GROUPFILTER_FUNCTIONS``), and
    the Pivot-field construct (a ``<group>`` with plain ``<field>`` children,
    no ``<groupfilter>`` at all).
    """
    count = 0
    for g in root.findall(".//datasource//group"):
        gf = g.find("groupfilter")
        if gf is None:
            continue
        if gf.get("function") in _NON_SET_GROUPFILTER_FUNCTIONS:
            continue
        count += 1
    return count


_MEMBER_HTML_UNESCAPES = (
    ("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
)


def _decode_member(raw: str) -> str:
    """HTML-decode + strip Tableau's surrounding double-quotes from a member
    value. ``%null%`` is the documented NULL-member sentinel — returned as-is
    (it carries no quotes and is matched literally by the cohort emitter)."""
    if raw == "%null%":
        return raw
    val = raw
    for enc, dec in _MEMBER_HTML_UNESCAPES:
        val = val.replace(enc, dec)
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        val = val[1:-1]
    return val


def _internal_meta(ds: ET.Element) -> dict[str, dict[str, str]]:
    """[internal bracket-stripped column/calc name] -> {"caption", "datatype"}.

    The single lookup Set anchor/member resolution needs: covers both plain
    dimensions (``[Category]`` -> caption "Category") and calculated fields
    (``[Calculation_NNN]`` -> caption "01. Month") in one pass, since both are
    plain ``<column>`` elements carrying the same two attributes — mirrors the
    per-column caption fallback ``_extract_columns``/``_extract_calculated_fields``
    already use (``caption`` defaults to the bracket-stripped ``name``), plus the
    raw Tableau ``datatype`` (string/integer/real/boolean/date/datetime) the
    cohort emitter needs to pick STRING vs. DOUBLE vs. DATE_FILTER for a set's
    member conditions (step-5-tml-generation.md: "Match filter_value_type to the
    anchor's type").
    """
    out: dict[str, dict[str, str]] = {}
    for col in ds.findall("./column"):
        name = col.get("name", "").strip("[]")
        if name:
            out[name] = {
                "caption": col.get("caption", name),
                "datatype": col.get("datatype", "string"),
            }
    return out


def _iter_groupfilters(gf: ET.Element):
    """Yield ``gf`` itself, then every nested ``<groupfilter>`` descendant."""
    yield gf
    yield from gf.findall(".//groupfilter")


def _contains_function(gf: ET.Element, fn: str) -> bool:
    return any(g.get("function") == fn for g in _iter_groupfilters(gf))


def _collect_members(gf: Optional[ET.Element]) -> list[str]:
    """Recursively collect every ``function='member'`` leaf's ``member`` value
    (HTML-decoded, quote-stripped) under a groupfilter subtree."""
    if gf is None:
        return []
    return [
        _decode_member(g.get("member", ""))
        for g in _iter_groupfilters(gf)
        if g.get("function") == "member" and g.get("member") is not None
    ]


def _anchor_level(gf: ET.Element) -> Optional[str]:
    """The ``level='[Dim]'`` attribute from a groupfilter subtree — checked in
    document order (gf itself first), so it resolves correctly whether the
    anchor sits on the outer node (a static/except set) or nested a level or two
    down (Top-N's ``level-members`` child, condition's ``filter`` node)."""
    for g in _iter_groupfilters(gf):
        lvl = g.get("level")
        if lvl:
            return lvl.strip("[]")
    return None


def _is_pure_member_tree(gf: ET.Element) -> bool:
    """True when a groupfilter subtree is ONLY union/member/level-members nodes
    — a plain member list, with no end/except/intersect/filter anywhere inside."""
    return not any(
        g.get("function") in ("end", "except", "intersect", "filter")
        for g in _iter_groupfilters(gf)
    )


def _order_expr(gf: ET.Element) -> Optional[str]:
    for g in _iter_groupfilters(gf):
        if g.get("function") == "order":
            return g.get("expression")
    return None


def _find_function(gf: ET.Element, fn: str) -> Optional[ET.Element]:
    for g in _iter_groupfilters(gf):
        if g.get("function") == fn:
            return g
    return None


def _classify_except(gf: ET.Element) -> str:
    """"except" branch of ``_classify_groupfilter`` — split out to keep that
    function's cyclomatic complexity in budget."""
    children = gf.findall("./groupfilter")
    end_child = next((c for c in children if _contains_function(c, "end")), None)
    filter_child = next((c for c in children if _contains_function(c, "filter")), None)
    other = [c for c in children if c is not end_child and c is not filter_child]
    # "all except Top/Bottom-N" (Phase 2c, simple inverted-rank) is specifically
    # the WHOLE-DOMAIN case: the kept side is a bare level-members (no fixed
    # member list of its own). Anything else with a computed side (a specific
    # member list EXCEPT a Top-N/condition) is the general multi-formula
    # "mixed" composition instead (step-5-tml-generation.md "Computed set
    # operations — intersect/except of mixed types").
    whole_domain_kept = len(other) == 1 and other[0].get("function") == "level-members"
    if end_child is not None and whole_domain_kept:
        return "except_topn"
    if end_child is not None or filter_child is not None:
        return "mixed"
    return "except_members"


def _classify_intersect(gf: ET.Element) -> str:
    """"intersect" branch of ``_classify_groupfilter`` — split out for the same
    complexity-budget reason as ``_classify_except``."""
    children = gf.findall("./groupfilter")
    if children and all(_is_pure_member_tree(c) for c in children):
        return "intersect_members"
    return "mixed"


_GROUPFILTER_FUNCTION_TO_TYPE = {
    "union": "static", "member": "static", "level-members": "set_control",
    "end": "topn", "filter": "condition",
}


def _classify_groupfilter(gf: ET.Element) -> str:
    """Classify a top-level ``<group>``'s ``<groupfilter>`` tree into one of the
    documented Phase 2a/2b/2c set types (step-5-tml-generation.md "Tableau Sets ->
    ThoughtSpot column sets")."""
    fn = gf.get("function")
    if fn == "except":
        return _classify_except(gf)
    if fn == "intersect":
        return _classify_intersect(gf)
    return _GROUPFILTER_FUNCTION_TO_TYPE.get(fn, "unclassified")


_SIMPLE_AGG_RE = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*\[([^\]]+)\]\s*\)\s*$")


def _parse_order_expr(expr: Optional[str]) -> tuple[Optional[str], str, bool]:
    """``"SUM([Sales])"`` -> ``("Sales", "SUM", False)``.

    A derived/conditional ordering measure (null-padding, IF-exclusion — anything
    that isn't a bare ``AGG([col])``) falls back to the innermost bracketed column
    reference with a ``SUM`` aggregation and a ``dropped_nuance=True`` flag, per
    step-5-tml-generation.md: "use the plain underlying measure and flag the
    dropped nuance."
    """
    if not expr:
        return None, "SUM", False
    m = _SIMPLE_AGG_RE.match(expr)
    if m:
        return m.group(2), m.group(1).upper(), False
    cols = re.findall(r"\[([^\]]+)\]", expr)
    return (cols[-1] if cols else None), "SUM", True


def _topn_fields(end_node: ET.Element) -> dict:
    fields: dict[str, Any] = {"topn_direction": end_node.get("end", "top")}
    count = end_node.get("count", "")
    if count.startswith("[Parameters]"):
        fields["topn_count_param"] = count
    else:
        try:
            fields["topn_count_literal"] = int(count)
        except ValueError:
            fields["topn_count_literal"] = count
    fields["order_expr"] = _order_expr(end_node)
    return fields


def _side_spec(gf: ET.Element, meta: dict[str, dict[str, str]]) -> Optional[dict]:
    """Classify one side of an ``intersect``/``except`` as a leaf set-op operand —
    a member list, a Top-N, or a condition (the three "side type" rows in
    step-5-tml-generation.md's "Computed set operations" composition table).
    Returns ``None`` for a side that is itself a nested set-op (deeper than the
    one level the mixed-set builder supports) or an unrecognized shape — the
    caller flags that "Nested set operation" case rather than guessing.

    ``meta`` is accepted for signature symmetry with the other per-set
    resolvers (unused today — a side's own member/measure values are already
    fully resolved by ``_collect_members``/``_order_expr``, and it doesn't
    anchor on its own separate column)."""
    del meta  # not needed yet — see docstring
    fn = gf.get("function")
    if fn in ("union", "member") or (fn == "level-members" and _collect_members(gf)):
        return {"kind": "members", "members": _collect_members(gf)}
    if _contains_function(gf, "end"):
        end_node = _find_function(gf, "end")
        return _topn_fields(end_node) | {"kind": "topn"}
    if _contains_function(gf, "filter"):
        filter_node = _find_function(gf, "filter")
        return {"kind": "condition", "condition_expr": filter_node.get("expression")}
    return None


def _base_set_entry(g: ET.Element, set_type: str, gf: ET.Element, meta: dict) -> dict:
    """The fields every Set entry carries regardless of type: name/id/type,
    plus the resolved anchor (when one exists — a dynamic Set Control's
    ``level-members`` always has one; a few other shapes may not)."""
    entry: dict[str, Any] = {
        "name": g.get("caption", g.get("name", "").strip("[]")),
        "internal_name": g.get("name", ""),
        "set_type": set_type,
    }
    level_ref = _anchor_level(gf)
    if level_ref:
        entry["anchor_ref"] = level_ref
        entry["anchor_is_calc"] = level_ref.startswith("Calculation_")
        m = meta.get(level_ref, {})
        entry["anchor_name"] = m.get("caption", level_ref)
        entry["anchor_datatype"] = m.get("datatype", "string")
    return entry


def _populate_static(entry: dict, gf: ET.Element, meta: dict) -> None:
    del meta
    entry["members"] = _collect_members(gf)


def _populate_except_members(entry: dict, gf: ET.Element, meta: dict) -> None:
    del meta
    children = gf.findall("./groupfilter")
    excl = next((c for c in children if _contains_function(c, "member")), None)
    entry["members"] = _collect_members(excl)


def _populate_intersect_members(entry: dict, gf: ET.Element, meta: dict) -> None:
    del meta
    children = gf.findall("./groupfilter")
    side_sets = [set(_collect_members(c)) for c in children]
    entry["members"] = sorted(set.intersection(*side_sets)) if side_sets else []
    entry["side_member_counts"] = [len(s) for s in side_sets]


def _populate_topn(entry: dict, gf: ET.Element, meta: dict) -> None:
    del meta
    end_node = _find_function(gf, "end")
    if end_node is not None:
        entry.update(_topn_fields(end_node))


def _populate_condition(entry: dict, gf: ET.Element, meta: dict) -> None:
    del meta
    filter_node = _find_function(gf, "filter")
    entry["condition_expr"] = filter_node.get("expression") if filter_node is not None else None


def _populate_mixed(entry: dict, gf: ET.Element, meta: dict) -> None:
    children = gf.findall("./groupfilter")
    entry["mixed_op"] = gf.get("function")
    entry["sides"] = [_side_spec(c, meta) for c in children]


# set_type -> the populator that fills in its type-specific fields. set_control
# and unclassified need nothing beyond _base_set_entry's anchor resolution.
_SET_FIELD_POPULATORS = {
    "static": _populate_static,
    "except_members": _populate_except_members,
    "intersect_members": _populate_intersect_members,
    "topn": _populate_topn,
    "except_topn": _populate_topn,
    "condition": _populate_condition,
    "mixed": _populate_mixed,
}


def extract_sets(ds: ET.Element) -> list[dict]:
    """Extract native Tableau Sets (top-level ``<group>`` elements) from a
    datasource, classified per the Phase 2a/2b/2c rules in
    step-5-tml-generation.md "Tableau Sets -> ThoughtSpot column sets". Excludes
    the same non-Set ``<group>`` shapes as ``count_native_sets`` (crossjoin
    action/tooltip groups; Pivot-field groups with no ``<groupfilter>``).

    Returns one dict per real Set — fields populate per ``set_type``:
      - Always: ``name`` (caption), ``internal_name``, ``set_type``,
        ``anchor_ref``/``anchor_name``/``anchor_is_calc``/``anchor_datatype``
        (when an anchor is resolvable).
      - ``static``: ``members`` (raw list, may include the ``"%null%"`` sentinel).
      - ``except_members``: ``members`` (the EXCLUDED list).
      - ``intersect_members``: ``members`` (the pre-computed common members),
        ``side_member_counts`` (each side's raw count, for the audit/log line).
      - ``topn`` / ``except_topn``: ``topn_direction``, ``topn_count_literal`` XOR
        ``topn_count_param``, ``order_expr`` (raw ``AGG([col])`` text).
      - ``condition``: ``condition_expr``.
      - ``mixed``: ``mixed_op`` (``"intersect"``/``"except"``), ``sides`` (a
        2-element list of ``_side_spec`` dicts, or ``None`` entries when a side
        is itself a nested set-op the shallow decomposer can't unpack).
      - ``set_control``: no extra fields beyond the anchor — no fixed members.
    """
    meta = _internal_meta(ds)
    sets: list[dict] = []
    for g in ds.findall("./group"):
        gf = g.find("groupfilter")
        if gf is None or gf.get("function") in _NON_SET_GROUPFILTER_FUNCTIONS:
            continue

        set_type = _classify_groupfilter(gf)
        entry = _base_set_entry(g, set_type, gf, meta)
        populate = _SET_FIELD_POPULATORS.get(set_type)
        if populate is not None:
            populate(entry, gf, meta)
        sets.append(entry)
    return sets
