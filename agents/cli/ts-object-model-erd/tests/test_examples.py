"""The committed example ERDs must match what the current renderer produces.

Each rendered `model_erd.html` inlines renderer.js/css, so any renderer change
leaves the examples showing an old viewer. This re-renders every example and
fails on drift, naming the command that refreshes it.
"""
import os

import pytest

import build_erd
import parser as erd_parser

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
NAMES = sorted(d for d in os.listdir(EXAMPLES)
               if os.path.isdir(os.path.join(EXAMPLES, d, "tml")))


def _render(name, out):
    ex = os.path.join(EXAMPLES, name)
    ai = os.path.join(ex, "ai_analysis.json")
    build_erd.build([os.path.join(ex, "tml")], out, log=lambda *_: None,
                    ai_analysis_path=ai if os.path.exists(ai) else None)


def test_examples_discovered():
    assert {"sales-inventory", "order-fulfilment"} <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_committed_example_is_current(name, tmp_path):
    out = str(tmp_path / "model_erd.html")
    _render(name, out)
    committed = os.path.join(EXAMPLES, name, "model_erd.html")
    with open(out, encoding="utf-8") as a, open(committed, encoding="utf-8") as b:
        fresh, stored = a.read(), b.read()
    assert fresh == stored, (
        "examples/%s/model_erd.html is stale. Regenerate from the skill dir with:\n"
        "  python3 build_erd.py examples/%s/tml --ai-analysis "
        "examples/%s/ai_analysis.json --out examples/%s/model_erd.html"
        % (name, name, name, name))


def test_order_fulfilment_exercises_aliases_and_rls():
    """The alias example exists to show role-playing dimensions — keep it honest."""
    models, tables = build_erd._discover([os.path.join(EXAMPLES, "order-fulfilment", "tml")])
    by_name = {t["table"]["name"]: t for t in tables}
    parsed = erd_parser.parse_model(models[0], by_name)
    aliases = [t for t in parsed["tables"] if t["alias_of"]]
    assert len(aliases) >= 15
    assert {t["alias_of"] for t in aliases} >= {"DM_EMPLOYEE", "DM_DATE_DIM",
                                                 "DM_CUSTOMER", "DM_BRANCH"}
    assert [t["id"] for t in parsed["tables"] if t["rls"]]
    assert all(j["card"] != "UNKNOWN" for j in parsed["joins"])
