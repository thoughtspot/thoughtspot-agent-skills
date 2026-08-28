"""The binding invariant: every emitted reference resolves to the RIGHT column.

The PR #440 re-review named this as the property that matters, and the one the
earlier fixtures could not express:

    every `[Column]` in an emitted formula or `answer_column` resolves to a column
    the model actually exposes, **on the right table**

Two bugs lived in that gap, both producing a clean import with wrong numbers rather
than a failure: a Beast Mode on the second dataset read the first dataset's column of
the same name, and an Answer on the second dataset grouped by the first dataset's
column. Asserting "the rename happened" did not catch either — only asserting that the
references still resolve does.

These are property checks over the whole bundle, not example assertions, so a new
fixture or a new rename rule is covered automatically.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ts_cli.domo.answers import build_liveboard_artifacts
from ts_cli.domo.build_model import build_model_artifacts
from ts_cli.domo.ir import (
    BeastMode,
    Card,
    CardQuery,
    Dataset,
    DomoApp,
    DomoColumn,
    Page,
    QueryColumn,
)
from ts_cli.domo.naming import build_column_index
from ts_cli.domo.parsing import parse_app

BUNDLES = [
    str(Path(__file__).parent / "fixtures" / "domo"),
    str(Path(__file__).parent / "fixtures" / "domo_edge"),
]

_REF = re.compile(r"\[([^\[\]]+)\]")


def _model_columns(model_tml: dict) -> set[str]:
    return {c["name"] for c in model_tml["model"]["columns"]}


def _column_to_table(model_tml: dict) -> dict[str, str]:
    """Display name -> the table it is exposed from.

    `build_model_tml` encodes the source table in `column_id` as `Table::Column`;
    there is no separate `table` key on the emitted entry.
    """
    out: dict[str, str] = {}
    for c in model_tml["model"]["columns"]:
        if c.get("formula_id"):
            continue
        cid = c.get("column_id") or ""
        out[c["name"]] = cid.split("::", 1)[0] if "::" in cid else c.get("table", "")
    return out


def _refs(expr: str) -> list[str]:
    """EVERY reference in an expression, formula refs included.

    Formula-to-formula refs used to be filtered out here. That exemption is why a
    formula on dataset B binding to dataset A's same-named sibling formula was
    invisible to this suite by construction — the exact bug this file exists to catch.
    A `[formula_X]` ref is returned with the prefix stripped so it resolves against
    the formula name set.

    Commented-out (`/* TODO review: … */`) formulas are inert and deliberately hold
    the untranslated original, so those are exempt.
    """
    if expr.strip().startswith("/*"):
        return []
    return [r[len("formula_"):] if r.startswith("formula_") else r
            for r in _REF.findall(expr)]


@pytest.mark.parametrize("bundle", BUNDLES, ids=["domo", "domo_edge"])
class TestEveryReferenceResolves:
    def test_formula_refs_resolve_to_something_the_model_exposes(self, bundle):
        app = parse_app(bundle)
        model = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                      model_name="M")["model"]["tml"]
        exposed = _model_columns(model) | {f["name"] for f in model["model"]["formulas"]}
        dangling = [(f["id"], r) for f in model["model"]["formulas"]
                    for r in _refs(f["expr"]) if r not in exposed]
        assert not dangling, f"refs the Model does not expose: {dangling}"

    def test_no_formula_references_itself(self, bundle):
        """A self-reference imports and computes nothing meaningful."""
        app = parse_app(bundle)
        model = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                      model_name="M")["model"]["tml"]
        loops = [f["name"] for f in model["model"]["formulas"]
                 if f["name"] in _refs(f["expr"])]
        assert not loops, f"self-referential formulas: {loops}"

    def test_formula_refs_resolve_to_the_owning_dataset(self, bundle):
        """The actual bug: `sum([Revenue])` on dataset B binding to A's Revenue."""
        app = parse_app(bundle)
        index = build_column_index(app)
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        col_table = _column_to_table(arts["model"]["tml"])
        # The owning dataset comes from the mapping, not from the name: once two
        # datasets share a Beast Mode name the name alone cannot identify the owner,
        # which is precisely the case the bug lived in.
        by_name = {f["name"]: f for f in arts["mapping"]["beast_modes"]}

        wrong = []
        for f in arts["model"]["tml"]["model"]["formulas"]:
            entry = by_name.get(f["name"])
            owner = (entry or {}).get("dataset")
            if not owner:
                continue
            formula_owner = {r["name"]: r["dataset"]
                             for r in arts["mapping"]["beast_modes"]}
            for ref in _refs(f["expr"]):
                table = col_table.get(ref)
                if table and table != owner:
                    wrong.append((f["id"], ref, "->", table, "expected", owner))
                # A sibling-formula ref must also belong to the owning dataset.
                if ref in formula_owner and formula_owner[ref] not in (None, "", owner):
                    wrong.append((f["id"], "formula", ref, "->",
                                  formula_owner[ref], "expected", owner))
        assert not wrong, f"formula bound to the wrong table: {wrong}"

    def test_answer_columns_resolve_to_the_cards_dataset(self, bundle):
        app = parse_app(bundle)
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        col_table = _column_to_table(arts["model"]["tml"])
        exposed = _model_columns(arts["model"]["tml"])
        formula_names = {f["name"] for f in arts["mapping"]["beast_modes"]}
        formula_owner = {f["name"]: f["dataset"] for f in arts["mapping"]["beast_modes"]}
        ds_by_id = {d.id: d.name for d in app.datasets}

        lb = build_liveboard_artifacts(app, model_name="M")
        card_by_urn = {c.urn: c for c in app.cards}
        problems = []
        for viz in lb["liveboard"]["tml"]["liveboard"]["visualizations"]:
            ans = viz["answer"]
            card = next((c for c in card_by_urn.values() if c.title == ans["name"]), None)
            owner = ds_by_id.get(card.data_set_id) if card else None
            for col in ans["answer_columns"]:
                name = col["name"]
                if name not in exposed and name not in formula_names:
                    problems.append(("unexposed", ans["name"], name))
                    continue
                if name in formula_names:
                    # A formula is legitimate here, but it must be one the card's own
                    # dataset owns — this used to be skipped outright.
                    if owner and formula_owner.get(name) not in (None, owner):
                        problems.append(("formula from another dataset", ans["name"],
                                         name, formula_owner.get(name), owner))
                    continue
                table = col_table.get(name)
                if owner and table and table != owner:
                    problems.append(("wrong table", ans["name"], name, table, owner))
        assert not problems, f"answer columns misbound: {problems}"

    def test_search_query_refs_match_answer_columns(self, bundle):
        app = parse_app(bundle)
        lb = build_liveboard_artifacts(app, model_name="M")
        for viz in lb["liveboard"]["tml"]["liveboard"]["visualizations"]:
            ans = viz["answer"]
            declared = {c["name"] for c in ans["answer_columns"]}
            for ref in _REF.findall(ans["search_query"]):
                assert ref in declared, (
                    f"{ans['name']}: search_query references [{ref}] which is not an "
                    f"answer_column ({sorted(declared)})")

    def test_no_backticks_survive_into_tml(self, bundle):
        """A raw Domo backtick in a formula body makes the whole model unimportable."""
        app = parse_app(bundle)
        model = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                      model_name="M")["model"]["tml"]
        live = [f["id"] for f in model["model"]["formulas"]
                if "`" in f["expr"] and not f["expr"].strip().startswith("/*")]
        assert not live, f"backticks in a live formula: {live}"


class TestBindingUnderRenames:
    """A hand-built worst case: same column names on both datasets, cards on each."""

    def _app(self) -> DomoApp:
        app = DomoApp(app_name="Both", source="-", extraction_mode="offline")
        cols = [("Order ID", "STRING"), ("Region", "STRING"), ("Revenue", "DOUBLE")]
        app.datasets = [
            Dataset(id="d1", name="Orders", rows=90000,
                    columns=[DomoColumn(n, t) for n, t in cols]),
            Dataset(id="d2", name="Refunds", rows=900,
                    columns=[DomoColumn(n, t) for n, t in cols]),
        ]
        app.beast_modes = [
            BeastMode(id=1, name="Total", formula="SUM(`Revenue`)", data_source_id="d1"),
            BeastMode(id=2, name="Total", formula="SUM(`Revenue`)", data_source_id="d2"),
        ]
        app.cards = [
            Card(urn="c1", title="By Region (Orders)", chart_type="bar", data_set_id="d1",
                 query=CardQuery(group_by=["Region"],
                                 columns=[QueryColumn(column="Region"),
                                          QueryColumn(column="Revenue", aggregation="SUM")])),
            Card(urn="c2", title="By Region (Refunds)", chart_type="bar", data_set_id="d2",
                 query=CardQuery(group_by=["Region"],
                                 columns=[QueryColumn(column="Region"),
                                          QueryColumn(column="Revenue", aggregation="SUM")])),
        ]
        app.pages = [Page(id="p", name="P", card_ids=["c1", "c2"])]
        return app

    def test_two_formulas_two_tables_two_bindings(self):
        app = self._app()
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        exprs = {f["id"]: f["expr"] for f in arts["model"]["tml"]["model"]["formulas"]}
        assert exprs["formula_Total"] == "sum([Revenue])"
        assert exprs["formula_Total (Refunds)"] == "sum([Revenue (Refunds)])", (
            "the Refunds formula must read Refunds' Revenue, not Orders'")

    def test_each_card_binds_to_its_own_dataset(self):
        app = self._app()
        lb = build_liveboard_artifacts(app, model_name="M")
        got = {v["answer"]["name"]: [c["name"] for c in v["answer"]["answer_columns"]]
               for v in lb["liveboard"]["tml"]["liveboard"]["visualizations"]}
        assert got["By Region (Orders)"] == ["Region", "Revenue"]
        assert got["By Region (Refunds)"] == ["Region (Refunds)", "Revenue (Refunds)"]

    def test_unbindable_reference_is_flagged_not_shipped(self):
        app = self._app()
        app.beast_modes.append(
            BeastMode(id=3, name="Bogus", formula="SUM(`Nope`)", data_source_id="d1"))
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        row = [f for f in arts["mapping"]["beast_modes"] if f["name"] == "Bogus"][0]
        assert row["status"] == "NEEDS REVIEW"
        assert "does not expose" in row["note"]


class TestOneSourceOfTruth:
    """The naming rule must be computed in exactly one place.

    Findings 1/2 in the PR #440 re-review were caused by two stages deriving the same
    rule independently and drifting. These pin the collapse so it cannot silently
    come back.
    """

    @pytest.mark.parametrize("bundle", BUNDLES, ids=["domo", "domo_edge"])
    def test_every_translated_formula_has_an_indexed_name(self, bundle):
        from ts_cli.domo.naming import build_column_index, deduped_beast_modes

        app = parse_app(bundle)
        index = build_column_index(app)
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        emitted = {f["name"] for f in arts["model"]["tml"]["model"]["formulas"]}
        # The index and the translation loop must agree on the exact name set.
        assert emitted == index.formula_names

    @pytest.mark.parametrize("bundle", BUNDLES, ids=["domo", "domo_edge"])
    def test_dedupe_is_shared_not_reimplemented(self, bundle):
        from ts_cli.domo.naming import deduped_beast_modes

        app = parse_app(bundle)
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        assert len(arts["mapping"]["beast_modes"]) == len(deduped_beast_modes(app))

    def test_index_formula_names_are_unique(self):
        """A duplicate name means a duplicate formula id, hence a dangling reference."""
        from ts_cli.domo.naming import build_column_index

        app = DomoApp(app_name="D", source="-", extraction_mode="offline")
        app.datasets = [Dataset(id=f"d{i}", name=f"T{i}", rows=10,
                                columns=[DomoColumn("v", "DOUBLE")]) for i in range(3)]
        app.beast_modes = [BeastMode(id=i, name="Same", formula="SUM(`v`)",
                                     data_source_id=f"d{i}") for i in range(3)]
        index = build_column_index(app)
        names = [index.formula(f"d{i}", "Same") for i in range(3)]
        assert len(set(names)) == 3, f"formula names collided: {names}"

