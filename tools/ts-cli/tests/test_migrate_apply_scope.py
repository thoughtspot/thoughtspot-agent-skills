"""Scope correctness of `ts migrate apply` (audit 2026-07-29 findings 17.2/17.3/17.4).

Three bugs with the same shape -- an operation scoped wider than the thing being
migrated -- and the same failure mode: imports cleanly, renders wrong (or, for 17.4,
passes a security gate that should refuse).
"""
import json
from unittest.mock import MagicMock, patch

from ts_cli.cli import app
from ts_cli.migrate.apply_plan import (
    SEGMENT_PHYSICAL, SEGMENT_SHARED, SEGMENT_UNKNOWN, bound_variable_names,
    segmentation_for_target,
)
from ts_cli.migrate.mapping import write_mapping
from ts_cli.migrate.rewrite import repoint_source, rewrite_content
from ts_cli.migrate.schema import ColumnMappingRow, MATCHED, ModelComparison

from runners import runner  # shared, stream-separated (BL-139)


# ---------------------------------------------------------------------------
# 17.3 -- repoint_source must not rebind the OTHER sources of a mixed dependent
# ---------------------------------------------------------------------------

MIXED_DOC = {
    "guid": "lb-1",
    "liveboard": {"name": "Board", "tables": [
        {"fqn": "src-1", "name": "Sales", "id": "Sales"},
        {"fqn": "other-9", "name": "Inventory", "id": "Inventory"},
    ]},
}


def test_only_the_migrating_models_entry_is_repointed():
    """A Liveboard reading the migrating Model AND an unrelated one is charged as
    content (classify takes the worst kind). Rebinding the unrelated entry too imports
    cleanly and renders wrong -- the unrelated visualizations silently read the
    published master."""
    out = repoint_source(MIXED_DOC, "tgt-1", "Sales", source_guid="src-1")
    entries = {e["name"]: e for e in out["liveboard"]["tables"]}
    assert entries["Sales"]["fqn"] == "tgt-1"
    assert entries["Inventory"]["fqn"] == "other-9"      # untouched


def test_a_name_only_entry_matching_the_model_name_is_repointed():
    """Resolution falls back to the name when there is no fqn, so a name-only entry
    for the migrating Model must be rebound -- and one for another source must not."""
    doc = {"answer": {"tables": [{"name": "Sales", "id": "Sales"},
                                 {"name": "Inventory", "id": "Inventory"}]}}
    out = repoint_source(doc, "tgt-1", "Sales", source_guid="src-1")
    entries = {e.get("id", e["name"]): e for e in out["answer"]["tables"]}
    assert entries["Sales"] == {"fqn": "tgt-1", "name": "Sales", "id": "Sales"}
    assert "fqn" not in entries["Inventory"]


def test_without_a_source_guid_the_legacy_rebind_all_survives():
    out = repoint_source(MIXED_DOC, "tgt-1", "Sales")
    assert all(e["fqn"] == "tgt-1" for e in out["liveboard"]["tables"])


def test_rewrite_content_threads_the_scope_through():
    out = rewrite_content(MIXED_DOC, {}, "tgt-1", "Sales", source_guid="src-1")
    entries = {e["id"]: e for e in out["liveboard"]["tables"]}
    assert entries["Sales"]["fqn"] == "tgt-1"
    assert entries["Inventory"]["fqn"] == "other-9"


# ---------------------------------------------------------------------------
# 17.4 -- the tenant-isolation gate must judge THIS target's variables only
# ---------------------------------------------------------------------------

def _table_doc(**fields):
    return {"table": {"name": "FACT", "rls_rules": {"rules": []}, **fields}}


def _var(name, vtype="TABLE_MAPPING", values=("db1", "db2")):
    return {"name": name, "variable_type": vtype,
            "values": [{"value": v} for v in values]}


def test_bound_variable_names_reads_whole_value_tokens_only():
    docs = [_table_doc(db="${env_db}", schema="STATIC", db_table="pre_${x}_post")]
    assert bound_variable_names(docs) == {"env_db"}     # partial token is static text


def test_an_unrelated_programmes_variable_cannot_vouch_for_this_target():
    """The false pass: static (unparameterized) tables + SOMEONE ELSE's per-Org
    variable. The unscoped read concluded SEGMENT_PHYSICAL and skipped the no-RLS
    refusal exactly where every tenant reads the same rows."""
    docs = [_table_doc(db="PROD_DB")]                   # no tokens: truly shared
    unrelated = [_var("other_programme_db")]            # 2 distinct per-Org values
    assert segmentation_for_target(docs, unrelated, "ORG_B") == SEGMENT_SHARED


def test_a_bound_variable_with_per_org_values_still_reads_physical():
    docs = [_table_doc(db="${env_db}")]
    assert segmentation_for_target(docs, [_var("env_db")], "ORG_B") == SEGMENT_PHYSICAL


def test_a_bound_variable_that_cannot_be_read_stays_unknown():
    """Bound but unreadable is not 'safe' -- an unreadable check is not a passed one."""
    docs = [_table_doc(db="${env_db}")]
    assert segmentation_for_target(docs, [_var("someone_else")], "ORG_B") == SEGMENT_UNKNOWN


def test_no_table_docs_at_all_stays_unknown():
    assert segmentation_for_target([], [_var("env_db")], "ORG_B") == SEGMENT_UNKNOWN


# ---------------------------------------------------------------------------
# 17.2 -- a multi-Model mapping is refused, not silently bound to targets[0]
# ---------------------------------------------------------------------------

@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_apply_refuses_a_multi_model_mapping(mock_cls, _rp, tmp_path):
    """`audit --all-models` writes one CSV across every Model by design; `apply` plans
    against targets[0], so Model B's content would land on Model A's master."""
    write_mapping(tmp_path / "column-mapping.csv", [
        ModelComparison(model_name="Sales", source_model_guid="g1",
                        target_model_guid="g2",
                        rows=[ColumnMappingRow("Sales", "Amount", "T::A",
                                               "Amount", MATCHED)]),
        ModelComparison(model_name="Inventory", source_model_guid="g3",
                        target_model_guid="g4",
                        rows=[ColumnMappingRow("Inventory", "Qty", "T::Q",
                                               "Qty", MATCHED)]),
    ])
    result = runner.invoke(app, ["migrate", "apply", "-d", str(tmp_path),
                                 "--source-profile", "src",
                                 "--target-profile", "tgt", "--dry-run"])
    assert result.exit_code == 1
    assert "one `apply` per Model" in result.stderr
