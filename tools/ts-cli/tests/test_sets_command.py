"""`ts sets inventory` — scope resolution, dry-run, selector errors, Org listing."""
import json
from unittest.mock import MagicMock, patch

from ts_cli.cli import app
from ts_cli.commands import sets as sets_cmd

from runners import runner  # shared, stream-separated (BL-139)

MODELS = [{"guid": "g1", "name": "Dunder Mifflin"}, {"guid": "g2", "name": "Retail"}]


def _fake_inventory(c, label, models, export_dir=None):
    return {"org": label, "notes": [], "models": [
        {"guid": m["guid"], "name": m["name"], "discovery": "COMPLETE", "set_count": 0,
         "sets": []} for m in models]}


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory)
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_inventory_contains_scopes_and_emits_schema(_c, _m, _inv, _rp):
    r = runner.invoke(app, ["sets", "inventory", "--model-contains", "dunder", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["schema"] == "ts-sets-inventory/1"
    assert [m["name"] for m in out["orgs"][0]["models"]] == ["Dunder Mifflin"]
    assert out["summary"]["models"] == 1


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_dry_run_scans_nothing(_c, _m):
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--dry-run", "--profile", "p"])
    assert r.exit_code == 0 and not inv.called
    assert json.loads(r.stdout)["orgs"][0]["models"] == [{"guid": "g2", "name": "Retail"}]


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_unmatched_selector_errors_before_scanning(_c, _m):
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Nope", "--profile", "p"])
    assert r.exit_code == 1 and "Nope" in r.stderr and not inv.called


def test_requires_a_scope():
    r = runner.invoke(app, ["sets", "inventory", "--profile", "p"])
    assert r.exit_code == 1 and "scope" in r.stderr.lower()


# --- R11: selectors -----------------------------------------------------------------

@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_whitespace_contains_selector_errors_before_scanning(client, _m):
    """`--model-contains " "` would otherwise match every Model with a space in its name."""
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model-contains", "  ", "--profile", "p"])
    assert r.exit_code == 1 and "empty" in r.stderr.lower()
    assert not inv.called and not client.called


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_empty_model_selector_errors_before_scanning(client, _m):
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "", "--profile", "p"])
    assert r.exit_code == 1 and "empty" in r.stderr.lower()
    assert not inv.called and not client.called


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_selectors_are_stripped(_c, _m):
    r = runner.invoke(app, ["sets", "inventory", "--model", "  Retail ", "--dry-run", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["orgs"][0]["models"] == [{"guid": "g2", "name": "Retail"}]


@patch("ts_cli.commands.sets._models_in", return_value=MODELS + [dict(MODELS[1])])
@patch("ts_cli.commands.sets._client", return_value=object())
def test_duplicate_models_are_deduplicated_by_guid(_c, _m):
    r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--dry-run", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["orgs"][0]["models"] == [{"guid": "g2", "name": "Retail"}]


# --- Org listing (amendment 3) ------------------------------------------------------

def test_all_org_ids_pages_and_keeps_active_only():
    client = MagicMock()
    client.post.return_value.json.return_value = [
        {"orgId": 0, "orgName": "Primary", "status": "ACTIVE"},
        {"orgId": 7, "orgName": "Old", "status": "INACTIVE"}]
    with patch("ts_cli.client.ThoughtSpotClient", return_value=client), \
         patch("ts_cli.commands.sets.resolve_profile", return_value="p"):
        ids, notes = sets_cmd._all_org_ids("p")
    assert ids == ["0"]
    assert [(n["kind"], n["object"]) for n in notes] == [("org_skipped", "Old (7)")]
    assert notes[0]["reason"] == "inactive"
    body = client.post.call_args.kwargs["json"]
    assert client.post.call_args.args[0] == "/api/rest/2.0/orgs/search"
    assert body["record_offset"] == 0 and body["record_size"] > 0


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory)
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
@patch("ts_cli.commands.sets._all_org_ids", return_value=(["0", "3"], []))
def test_all_orgs_scans_each_org(_ids, client, _m, _inv, _rp):
    r = runner.invoke(app, ["sets", "inventory", "--all-orgs", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert [o["org"] for o in json.loads(r.stdout)["orgs"]] == ["0", "3"]
    assert [c.args[1] for c in client.call_args_list] == ["0", "3"]


def test_org_rows_missing_status_or_id_are_skipped_with_notes():
    client = MagicMock()
    client.post.return_value.json.return_value = [
        {"orgId": 0, "orgName": "Primary", "status": "ACTIVE"},
        {"orgId": 4, "orgName": "NoStatus"},
        {"orgName": "NoId", "status": "ACTIVE"}]
    with patch("ts_cli.client.ThoughtSpotClient", return_value=client), \
         patch("ts_cli.commands.sets.resolve_profile", return_value="p"):
        ids, notes = sets_cmd._all_org_ids("p")
    assert ids == ["0"]
    assert [n["object"] for n in notes] == ["NoStatus (4)", "NoId (None)"]
    assert [n["reason"] for n in notes] == ["malformed", "malformed"]


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory)
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_skipped_orgs_appear_in_output_notes(_c, _m, _inv, _rp):
    skipped = [{"kind": "org_skipped", "object": "Old (7)", "detail": "status 'INACTIVE'"}]
    with patch("ts_cli.commands.sets._all_org_ids", return_value=(["0"], skipped)):
        r = runner.invoke(app, ["sets", "inventory", "--all-orgs", "--profile", "p"])
        d = runner.invoke(app, ["sets", "inventory", "--all-orgs", "--dry-run", "--profile", "p"])
    assert r.exit_code == 0 and d.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["notes"] == skipped
    assert json.loads(d.stdout)["notes"] == skipped


def test_report_refuses_dry_run(tmp_path):
    p = tmp_path / "i.json"
    p.write_text(json.dumps({"schema": "ts-sets-inventory/1", "dry_run": True}))
    r = runner.invoke(app, ["sets", "report", str(p), "-o", str(tmp_path / "out")])
    assert r.exit_code == 1
    assert not (tmp_path / "out").exists()


def test_report_refuses_wrong_schema(tmp_path):
    p = tmp_path / "i.json"
    p.write_text(json.dumps({"schema": "something-else/1"}))
    r = runner.invoke(app, ["sets", "report", str(p), "-o", str(tmp_path)])
    assert r.exit_code == 1


def test_report_writes_html_and_markdown(tmp_path):
    inv = {"schema": "ts-sets-inventory/1", "generated_at": "t", "profile": "se",
           "scope": {}, "notes": [], "orgs": [{"org": "Primary", "notes": [], "models": []}],
           "summary": {"models": 0, "models_incomplete": 0, "sets": 0, "by_class": {},
                       "unexplained_grants": 0}}
    p = tmp_path / "i.json"
    p.write_text(json.dumps(inv))
    r = runner.invoke(app, ["sets", "report", str(p), "-o", str(tmp_path / "out")])
    assert r.exit_code == 0, r.stderr
    out = json.loads(r.stdout)
    assert (tmp_path / "out" / "report.html").read_text().startswith("<!doctype html>")
    assert "Reusable Set inventory" in (tmp_path / "out" / "report.md").read_text()
    assert out["html"].endswith("report.html")


import pytest  # noqa: E402


@pytest.mark.parametrize("doc", [
    {"schema": "ts-sets-inventory/1", "orgs": []},
    {"schema": "ts-sets-inventory/1", "summary": {}},
    {"schema": "ts-sets-inventory/1", "summary": {}, "orgs": {"not": "a list"}},
    {"schema": "ts-sets-inventory/1", "summary": [], "orgs": []},
], ids=["no_summary", "no_orgs", "orgs_not_list", "summary_not_dict"])
def test_report_refuses_malformed_document(tmp_path, doc):
    p = tmp_path / "i.json"
    p.write_text(json.dumps(doc))
    r = runner.invoke(app, ["sets", "report", str(p), "-o", str(tmp_path / "out")])
    assert r.exit_code == 1
    assert "Traceback" not in r.stderr
    assert not (tmp_path / "out").exists()


class _BaseClient:
    base_url = "https://se.example.thoughtspot.cloud"


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory)
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=_BaseClient())
def test_inventory_records_base_url_for_report_links(_c, _m, _inv, _rp):
    r = runner.invoke(app, ["sets", "inventory", "--model-contains", "dunder", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["base_url"] == "https://se.example.thoughtspot.cloud"


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory)
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_inventory_without_a_base_url_omits_it(_c, _m, _inv, _rp):
    r = runner.invoke(app, ["sets", "inventory", "--model-contains", "dunder", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["base_url"] is None


# --- --export-tml ---------------------------------------------------------------------

@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_export_tml_passes_dir_to_each_org(_c, _m, _rp, tmp_path):
    with patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory) as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--export-tml",
                                str(tmp_path / "tml"), "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert inv.call_args.kwargs["export_dir"] == tmp_path / "tml"
    out = json.loads(r.stdout)
    assert out["scope"]["export_tml"] == str(tmp_path / "tml")
    assert out["summary"]["tml_exported"] == 0   # present even with no Sets


@patch("ts_cli.commands.sets.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_no_export_tml_means_no_export(_c, _m, _rp):
    with patch("ts_cli.commands.sets.inventory_org", side_effect=_fake_inventory) as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--profile", "p"])
    assert r.exit_code == 0, r.stderr
    assert inv.call_args.kwargs["export_dir"] is None
    assert "tml_exported" not in json.loads(r.stdout)["summary"]


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_dry_run_exports_nothing(_c, _m, tmp_path):
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--dry-run",
                                "--export-tml", str(tmp_path / "tml"), "--profile", "p"])
    assert r.exit_code == 0 and not inv.called
    assert not (tmp_path / "tml").exists() and "no Set TML exported" in r.stderr


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_export_tml_refuses_a_file(_c, _m, tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    for extra in ([], ["--dry-run"]):
        with patch("ts_cli.commands.sets.inventory_org") as inv:
            r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--export-tml",
                                    str(f), "--profile", "p"] + extra)
        assert r.exit_code == 1 and "not a directory" in r.stderr and not inv.called


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_export_tml_refuses_a_non_empty_dir(_c, _m, tmp_path):
    (tmp_path / "old.cohort.tml").write_text("x")
    with patch("ts_cli.commands.sets.inventory_org") as inv:
        r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--export-tml",
                                str(tmp_path), "--profile", "p"])
    assert r.exit_code == 1 and "not empty" in r.stderr and not inv.called


@patch("ts_cli.commands.sets._models_in", return_value=MODELS)
@patch("ts_cli.commands.sets._client", return_value=object())
def test_export_tml_refuses_an_unwritable_parent(_c, _m, tmp_path):
    """Caught before the scan, not after every write fails (pr-reviewer re-review)."""
    import os
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):   # running as root: the check cannot be exercised
            return
        for extra in ([], ["--dry-run"]):
            with patch("ts_cli.commands.sets.inventory_org") as inv:
                r = runner.invoke(app, ["sets", "inventory", "--model", "Retail", "--export-tml",
                                        str(locked / "new" / "tml"), "--profile", "p"] + extra)
            assert r.exit_code == 1 and "cannot be written" in r.stderr and not inv.called
            assert not (locked / "new").exists()
    finally:
        locked.chmod(0o700)
