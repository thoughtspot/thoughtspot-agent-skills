"""Registry-level guards over every ts-audit check — audit 6.1 / BL-297.

These do not prove a check can *fire* (that is each family's trip-test file).
They pin the two things that hold for all 51 regardless of what each one looks
for, and they are keyed on `ALL_CHECKS` itself, so a check added to a registry
is covered here from its first commit without editing a list.
"""
import pytest

from ts_cli.audit import (
    checks_ai, checks_data, checks_human, checks_perf, checks_security,
)
from ts_cli.audit.context import make_context

MODULES = (checks_ai, checks_data, checks_human, checks_perf, checks_security)

ALL = [(m.__name__.rsplit(".", 1)[-1], fn)
       for m in MODULES for fn in m.ALL_CHECKS]

IDS = [f"{mod}:{fn.__name__}" for mod, fn in ALL]


def _populated():
    """A context with every field non-empty, in realistic TML shapes.

    Not designed to trip anything in particular — designed to walk the loops.
    A check that raises on well-formed input is broken whatever it looks for.
    """
    tfqn = "t-1"
    table = {"guid": "tg-1", "table": {
        "name": "ORDERS",
        "columns": [
            {"name": "CUST_ID", "db_column_properties": {"data_type": "VARCHAR"}},
            {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
        ],
        "rls_rules": {"rules": [{"name": "r1", "expr": "[ORDERS::CUST_ID] = 'x'"}]},
    }}
    model = {"guid": "m-1", "model": {
        "name": "Sales",
        "description": "orders and returns",
        "columns": [
            {"name": "Cust Id", "column_id": "ORDERS::CUST_ID",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        ],
        "model_tables": [{"name": "ORDERS", "fqn": tfqn, "joins": [
            {"name": "j1", "on": "[ORDERS::CUST_ID] = [CUST::ID]"}]}],
        "model_instructions": {"data_model_instructions": "Use last 30 days"},
    }}
    return make_context(
        models=[model],
        tables={tfqn: table},
        dependents={"m-1": [{"id": "a-1", "type": "ANSWER", "name": "A"}]},
        metadata=[{"id": "m-1", "type": "LOGICAL_TABLE", "name": "Sales"}],
        ai_instructions={"m-1": {"nl_instructions_info": [
            {"instructions": ["Filter by region"], "scope": "GLOBAL"}]}},
        answers=[{"guid": "a-1", "answer": {"name": "A", "search_query": "[Amount]"}}],
        model_guids=["m-1"],
        warnings=[],
    )


@pytest.mark.parametrize("mod,fn", ALL, ids=IDS)
def test_check_survives_an_empty_context(mod, fn):
    """Every check must tolerate a context with nothing in it.

    `build_context` returns empty collections when an export fails or the user
    scopes the audit narrowly, so this is a real input, not a synthetic one.
    """
    assert isinstance(fn(make_context()), list)


@pytest.mark.parametrize("mod,fn", ALL, ids=IDS)
def test_check_survives_a_populated_context(mod, fn):
    """And must not raise on well-formed TML — whatever it does or does not find."""
    assert isinstance(fn(_populated()), list)


def test_every_check_id_is_unique():
    """Two checks sharing a `check_id` make a finding unattributable.

    The id is what the catalog, the report and a backlog citation all key on.
    """
    seen: dict[str, str] = {}
    dupes = []
    for mod, fn in ALL:
        cid = fn.__name__.replace("check_", "").upper()
        if cid in seen:
            dupes.append(f"{cid}: {seen[cid]} and {mod}.{fn.__name__}")
        seen[cid] = f"{mod}.{fn.__name__}"
    assert dupes == [], f"duplicate check ids: {dupes}"


#: Checks defined but deliberately NOT in ALL_CHECKS, with the reason.
#: Adding to this needs a catalog entry saying the check is deferred.
DEFERRED = {
    "check_h6": "H6 duplicate sets — deferred in check-catalog.md "
                "(requires deep set comparison); stub keeps the id allocated",
}


def test_every_defined_check_is_registered():
    """A check that exists but is in no ALL_CHECKS never runs, and says nothing.

    Found by counting: 51 functions are defined, 50 registered. The one gap is
    deliberate and now declared; any other is a check silently switched off.
    """
    import re
    from pathlib import Path as _P

    src = _P(__file__).resolve().parents[1] / "ts_cli" / "audit"
    unregistered = []
    for module in MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        registered = {fn.__name__ for fn in module.ALL_CHECKS}
        defined = set(re.findall(r"^def (check_[a-z0-9]+)\(",
                                 (src / f"{name}.py").read_text(), re.M))
        for missing in sorted(defined - registered):
            if missing not in DEFERRED:
                unregistered.append(f"{name}.{missing}")
    assert unregistered == [], (
        f"defined but never run: {unregistered}. Register them, delete them, or "
        f"add them to DEFERRED with a check-catalog entry saying why.")


def test_registries_are_not_empty():
    """A module whose ALL_CHECKS is empty contributes nothing and says nothing."""
    empty = [m.__name__ for m in MODULES if not m.ALL_CHECKS]
    assert empty == [], f"modules with an empty ALL_CHECKS: {empty}"


# ── BL-304: rules that used to exist twice now exist once ──────────────────

def test_shared_rules_are_imported_not_re_implemented():
    """The data/perf split was made by copying; six rules existed twice.

    A threshold tuned in one angle silently left the other on the old value, and
    `check_d2`/`check_p6` shipped the *same* two defects and had to be fixed twice
    (#528). This asserts the duplicates stay collapsed: each module must reach the
    shared rule rather than carry its own copy.
    """
    import re as _re
    from pathlib import Path as _P
    from ts_cli.audit import rules

    src = _P(__file__).resolve().parents[1] / "ts_cli" / "audit"
    offenders = []

    # The regexes were declared identically in two modules.
    for mod in ("checks_perf", "checks_security"):
        text = (src / f"{mod}.py").read_text()
        if _re.search(r"_FUNC_IN_EXPR\s*=\s*re\.compile", text):
            offenders.append(f"{mod}: re-declares _FUNC_IN_EXPR")
        if _re.search(r"_BRACKET_REF\s*=\s*re\.compile", text):
            offenders.append(f"{mod}: re-declares _BRACKET_REF")

    # The literal thresholds belong to `rules`, not to a check body.
    perf = (src / "checks_perf.py").read_text()
    if _re.search(r"len\(cols\)\s*>\s*75", perf):
        offenders.append("checks_perf: hardcodes the 75-column ceiling")
    if _re.search(r"measures\s*>\s*3", perf):
        offenders.append("checks_perf: re-implements fact detection")
    if _re.search(r"max_depth\s*>\s*[35]\b", perf):
        offenders.append("checks_perf: hardcodes the join-depth bands")

    data = (src / "checks_data.py").read_text()
    if _re.search(r"len\(mt\)\s*>\s*5\s+and\s+not", data):
        offenders.append("checks_data: re-implements the join_progressive predicate")

    assert offenders == [], (
        f"a rule has been copied back out of `rules.py`: {offenders}")


def test_both_angles_still_report_a_shared_rule():
    """Collapsing the code must not collapse the reporting.

    A wide un-progressive model is legitimately both a modelling and a
    performance finding; the angles are different lenses. Only the rule is shared.
    """
    from ts_cli.audit.checks_data import check_d4
    from ts_cli.audit.checks_perf import check_p4

    model = {"guid": "m-1", "model": {
        "name": "Wide",
        "model_tables": [{"name": f"T{i}"} for i in range(6)],
        "properties": {"join_progressive": False},
    }}
    ctx = make_context(models=[model])
    d4, p4 = check_d4(ctx), check_p4(ctx)
    assert len(d4) == 1 and d4[0].check_id == "D4"
    assert len(p4) == 1 and p4[0].check_id == "P4"
    assert d4[0].metric == p4[0].metric == 6
