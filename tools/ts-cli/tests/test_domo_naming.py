"""The naming authority, and the join-key heuristic.

`_looks_like_key` had NO test at all despite a round-3 claim that "20 cases pinned,
both classes" — the pinning happened in a session and was never committed, which is the
`grep`-able version of the record running ahead of the change. It is pinned here.

The `Index` tests assert the properties four review rounds of one bug class established:
one flat namespace covering tables, columns, formulas AND the generated `formula_*` id
space; NFC-normalised comparison; dataset-scoped resolution; stable ordering; and a
transportable index so the two CLI stages cannot independently re-derive it.
"""
from __future__ import annotations

import json
import unicodedata

import pytest

from ts_cli.domo.build_model import (
    _NOT_KEYS,
    _looks_like_key,
    _pick_join_key,
    build_model_artifacts,
)
from ts_cli.domo.ir import BeastMode, Dataset, DomoApp, DomoColumn
from ts_cli.domo.naming import (
    FORMULA_ID_PREFIX,
    build_index,
    bundle_digest,
    index_from_dict,
    index_to_dict,
    ordered_datasets,
)


def _app(datasets, beast_modes=()):
    app = DomoApp(app_name="T", source="-", extraction_mode="offline")
    app.datasets = list(datasets)
    app.beast_modes = list(beast_modes)
    return app


def _ds(did, name, cols, rows=100):
    return Dataset(id=did, name=name, rows=rows,
                   columns=[DomoColumn(c, t) for c, t in cols])


class TestLooksLikeKey:
    """Both failure directions, because fixing one previously broke the other."""

    @pytest.mark.parametrize("name", [
        # separated
        "Customer ID", "Order Id", "order_guid", "sku_code", "OrderKey", "row urn",
        # camelCase
        "customerId", "userIds", "dataSourceId", "orderKey",
        # glued — the class a token-only test missed
        "orderid", "custid", "CUSTOMERID", "SSID", "productcode",
    ])
    def test_is_a_key(self, name):
        assert _looks_like_key(name) is True

    @pytest.mark.parametrize("name", [
        # English words ending in an id-like substring — the class a suffix-only test
        # matched, which silently changed which column two tables joined on
        "Paid", "Void", "Valid", "Invalid", "Rapid", "Overpaid", "Candid", "Unpaid",
        # ordinary measures / dimensions
        "Region", "Amount", "Revenue", "Quantity", "Status", "Date", "Name",
    ])
    def test_is_not_a_key(self, name):
        assert _looks_like_key(name) is False

    def test_denylist_entries_are_all_actually_rejected(self):
        """A `_NOT_KEYS` entry that still matches is a silent false positive."""
        leaking = [w for w in _NOT_KEYS if _looks_like_key(w)]
        assert not leaking, f"_NOT_KEYS entries still matching: {leaking}"

    @pytest.mark.parametrize("name", ["Churn", "Return", "Turn", "Saturn", "Nocturne"])
    def test_urn_token_does_not_leak_into_english_words(self, name):
        """`urn` is a key token, but these merely end in it."""
        assert _looks_like_key(name) is False

    def test_plural_and_singular_agree(self):
        for stem in ("bid", "kid", "lid", "grid"):
            assert _looks_like_key(stem) == _looks_like_key(stem + "s"), stem


class TestPickJoinKey:
    def test_prefers_the_id_like_column(self):
        key, note = _pick_join_key({"Region", "Order ID", "Date"})
        assert key == "Order ID"
        assert "not used" in note

    def test_reports_rather_than_joining_on_incidental_columns(self):
        key, note = _pick_join_key({"Region", "Date"})
        assert key is None
        assert "incidental" in note

    def test_does_not_pick_a_measure_over_a_glued_id(self):
        key, _ = _pick_join_key({"Amount", "orderid"})
        assert key == "orderid"


class TestNamespaceIsFlatAndComplete:
    def test_formula_id_prefix_is_reserved_against_columns(self):
        """A column named `formula_Net` would alias the id of a Beast Mode `Net`."""
        app = _app([_ds("d", "S", [("formula_Net", "DOUBLE"), ("Qty", "DOUBLE")])],
                   [BeastMode(id=1, name="Net", formula="SUM(`Qty`)",
                              data_source_id="d", status="VALID")])
        index = build_index(app)
        column = index.display("d", "formula_Net")
        formula = index.formula("d", "Net")
        assert column != f"{FORMULA_ID_PREFIX}{formula}"
        assert not column.startswith(FORMULA_ID_PREFIX), (
            "a column must never carry the generated-id prefix")

    def test_table_namespace_is_shared_with_columns(self):
        """`taken` used to be dead after the table loop, so these coexisted."""
        app = _app([_ds("d", "Revenue", [("Revenue", "DOUBLE")])])
        index = build_index(app)
        assert index.table("d") != index.display("d", "Revenue")

    def test_nfc_and_nfd_columns_do_not_both_ship(self):
        composed = unicodedata.normalize("NFC", "Café")
        decomposed = unicodedata.normalize("NFD", "Café")
        assert composed != decomposed
        app = _app([_ds("d", "S", [(composed, "VARCHAR"), (decomposed, "VARCHAR")])])
        index = build_index(app)
        names = list(index.columns_by_dataset["d"].values())
        assert len(set(names)) == len(names)
        assert names[0] != names[1]

    def test_duplicate_raw_column_on_one_dataset_is_reported(self):
        app = _app([_ds("d", "S", [("Amount", "DOUBLE"), ("Amount", "DOUBLE")])])
        index = build_index(app)
        assert any("duplicate raw column" in (r.get("reason") or "")
                   for r in index.renames)

    def test_filenames_cannot_collide(self):
        """`Sales-Data` and `Sales Data` both slug to `Sales_Data`."""
        app = _app([_ds("a", "Sales-Data", [("x", "DOUBLE")]),
                    _ds("b", "Sales Data", [("y", "DOUBLE")])])
        index = build_index(app)
        assert index.table_file("a") != index.table_file("b")

    def test_same_dataset_column_and_formula_clash_is_recorded(self):
        app = _app([_ds("d", "S", [("Revenue", "DOUBLE")])],
                   [BeastMode(id=1, name="Revenue", formula="SUM(`Revenue`) * 2",
                              data_source_id="d", status="VALID")])
        index = build_index(app)
        assert index.display("d", "Revenue") == "Revenue"
        assert index.formula("d", "Revenue") != "Revenue"
        assert any("Revenue" in r["from"] for r in index.formula_renames)

    def test_cross_dataset_bare_name_is_not_guessed_when_ambiguous(self):
        app = _app([_ds("a", "A", [("v", "DOUBLE")]), _ds("b", "B", [("v", "DOUBLE")])],
                   [BeastMode(id=1, name="Target", formula="SUM(`v`)",
                              data_source_id="a", status="VALID"),
                    BeastMode(id=2, name="Target", formula="SUM(`v`)",
                              data_source_id="b", status="VALID")])
        index = build_index(app)
        # 'Target' now names two different formulas, so a bare ref from a third
        # context must not bind to either.
        assert index.resolve("zzz", "Target") is None


class TestDeterminism:
    def test_dataset_order_is_not_discovery_order(self):
        """Discovery order is a filename glob; ordering must come from the data."""
        a = _ds("zzz", "Alpha", [("x", "DOUBLE")])
        b = _ds("aaa", "Zulu", [("y", "DOUBLE")])
        assert [d.id for d in ordered_datasets(_app([a, b]))] == ["aaa", "zzz"]
        assert [d.id for d in ordered_datasets(_app([b, a]))] == ["aaa", "zzz"]

    def test_index_is_identical_regardless_of_input_order(self):
        cols = [("Order ID", "VARCHAR"), ("Revenue", "DOUBLE")]
        a, b = _ds("d1", "Orders", cols), _ds("d2", "Refunds", cols)
        one = index_to_dict(build_index(_app([a, b])))
        two = index_to_dict(build_index(_app([b, a])))
        assert one == two

    def test_digest_changes_when_the_bundle_changes(self):
        base = _app([_ds("d", "S", [("A", "DOUBLE")])])
        more = _app([_ds("d", "S", [("A", "DOUBLE"), ("B", "DOUBLE")])])
        assert bundle_digest(base) != bundle_digest(more)

    def test_index_round_trips_through_json(self):
        app = _app([_ds("d", "S", [("A", "DOUBLE")])],
                   [BeastMode(id=1, name="M", formula="SUM(`A`)",
                              data_source_id="d", status="VALID")])
        original = build_index(app)
        restored = index_from_dict(json.loads(json.dumps(index_to_dict(original))))
        assert restored.table("d") == original.table("d")
        assert restored.display("d", "A") == original.display("d", "A")
        assert restored.formula("d", "M") == original.formula("d", "M")
        assert restored.bundle_digest == original.bundle_digest
        assert restored.derived is False, "a loaded index must not claim to be derived"


class TestDuplicateDatasetNames:
    def test_no_self_join_and_no_orphan_table(self):
        """Join maps used to key on the RAW name, giving `[S::k] = [S::k]`."""
        app = _app([_ds("d1", "Sales", [("k", "VARCHAR")], rows=9000),
                    _ds("d2", "Sales", [("k", "VARCHAR")], rows=100)])
        arts = build_model_artifacts(app, connection_name="C", db="D", schema="S",
                                     model_name="M")
        for j in arts["mapping"]["joins"]:
            assert j["left"] != j["right"], f"self-join emitted: {j}"
        assert len(arts["tables"]) == 2, "one .table.tml overwrote the other"
        model = arts["model"]["tml"]["model"]
        names = [t["name"] for t in model["model_tables"]]
        assert len(names) == len(set(names)), f"duplicate model_tables: {names}"
