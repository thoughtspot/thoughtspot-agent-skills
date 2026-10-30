"""Unit tests for `ts dependency cascade-preview` / `cascade-delete` and the pure logic in
`ts_cli.dependency.cascade`. No live connection: the client is a fake.

Response shapes follow what a test cluster returned on 2026-10-30: `dependents` entries
carry `authorName: null` (the author is only in the `csv` field), and a preview of an
object that is already deleted still answers `{"dependents": {"<guid>": []}}` — so
outcomes come from existence checks (v2 `metadata/search`), modelled by `FakeClient.present`.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from ts_cli.cli import app
from ts_cli.dependency import cascade as c
from ts_cli.report.resolver import SourceUnresolvedError
from ts_cli.report.schema import SourceDescriptor

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)

SRC = "7c9d6e4d-cee4-4d03-a062-62e26804ac02"      # a Table
COL = "43ff35d7-bf89-4f18-b1d3-a56f38f470b8"      # a column of OWNER
OWNER = "95158c5f-7805-48f0-8802-c727d1785a04"    # the column's Table
M1 = "8777533f-dca2-49d3-986a-9d7daf902cdf"
M2 = "db767288-f968-47ae-aa45-1228e0309e26"
LB = "601be8e5-140e-477c-8812-843795306438"
NEW = "11111111-2222-3333-4444-555555555555"
CSV_HEAD = ("sourceColumnGUID,sourceColumnName,dependentGUID,dependentName,dependentType,"
            "dependentSubType,childGUID,childName,childType,author,lastModified,views,orgName")
BASE = "https://cluster.example"
OLD = 1_000          # `modified` of an object untouched since long before the backup


def _dep(guid, name, typ="LOGICAL_TABLE", sub="WORKSHEET"):
    return {"id": guid, "name": name, "type": typ, "subType": sub, "authorName": None}


def _csv(source, deps, authors=None):
    authors = authors or {}
    rows = [f"{source},{source},{d['id']},{d['name']},{d['type']},{d['subType'] or ''},,,,"
            f"{authors.get(d['id'], 'tsadmin')},2025-01-01 00:00:00,0,Primary" for d in deps]
    return "\n".join([CSV_HEAD] + rows) + "\n"


def _preview(source=SRC, deps=None, authors=None, extra_keys=None, csv_only=()):
    deps = [_dep(M1, "Model A"), _dep(M2, "Model B")] if deps is None else deps
    return {"dependents": {source: deps, **(extra_keys or {})},
            "csv": _csv(source, list(deps) + list(csv_only), authors)}


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

class TestPureLogic:
    def test_is_admin(self):
        assert c.is_admin({"privileges": ["AUTHORING", "ADMINISTRATION"]})
        assert not c.is_admin({"privileges": ["AUTHORING", "DATAMANAGEMENT"]})
        assert not c.is_admin({})

    def test_form_preview_and_apply(self):
        assert c.cascade_form("LOGICAL_TABLE", SRC, apply=False) == {
            "type": "LOGICAL_TABLE", "id": json.dumps([SRC]),
            "operation_type": "DELETE_OBJECT_CASCADE", "apply_changes": "false"}
        assert c.cascade_form("LOGICAL_COLUMN", COL, apply=True)["apply_changes"] == "true"
        with pytest.raises(c.CascadeError):
            c.cascade_form("PINBOARD", SRC, apply=False)

    @pytest.mark.parametrize("typ,sub,want", [
        ("PINBOARD_ANSWER_BOOK", None, "LIVEBOARD"), ("QUESTION_ANSWER_BOOK", None, "ANSWER"),
        ("LOGICAL_TABLE", "WORKSHEET", "MODEL"), ("LOGICAL_TABLE", "SQL_VIEW", "SQL_VIEW"),
        ("LOGICAL_TABLE", "AGGR_WORKSHEET", "VIEW"), ("LOGICAL_TABLE", "ONE_TO_ONE_LOGICAL", "TABLE"),
        ("PINBOARD_ANSWER_BOOK", "", "LIVEBOARD")])
    def test_backup_type(self, typ, sub, want):
        assert c.backup_type(typ, sub) == want

    @pytest.mark.parametrize("typ,sub", [("LOGICAL_TABLE", "USER_DEFINED"),
                                         ("LOGICAL_TABLE", None), ("COHORT", None)])
    def test_unknown_type_is_refused_not_guessed(self, typ, sub):
        with pytest.raises(c.CascadeError, match="Unsupported"):
            c.backup_type(typ, sub)

    def test_parse_preview_dedupes_and_reads_author_and_org_from_csv(self):
        resp = _preview(deps=[_dep(M1, "Model A"), _dep(M1, "Model A"),
                              _dep(LB, "LB", "PINBOARD_ANSWER_BOOK", None)],
                        authors={M1: "alice", LB: "bob"})
        out = c.parse_preview(resp, SRC)
        assert [o["guid"] for o in out["objects"]] == [M1, LB]
        assert [o["author"] for o in out["objects"]] == ["alice", "bob"]
        assert [o["type"] for o in out["objects"]] == ["MODEL", "LIVEBOARD"]
        assert {o["org"] for o in out["objects"]} == {"Primary"}

    def test_scope_includes_other_keys_and_csv_only_rows(self):
        # The review's blocker: an object named only under another key, or only in the
        # CSV, must still be in scope — `dependents[<guid>]` is not proven complete.
        resp = _preview(deps=[_dep(M1, "Model A")],
                        extra_keys={M1: [_dep(NEW, "Deep Answer", "QUESTION_ANSWER_BOOK", None)]},
                        csv_only=[_dep(LB, "CSV-only LB", "PINBOARD_ANSWER_BOOK", None)])
        assert {o["guid"] for o in c.parse_preview(resp, SRC)["objects"]} == {M1, NEW, LB}

    def test_parse_preview_empty_and_self(self):
        assert c.parse_preview(_preview(deps=[]), SRC)["objects"] == []
        assert c.parse_preview(_preview(deps=[_dep(SRC, "self")]), SRC)["objects"] == []

    @pytest.mark.parametrize("resp", [
        {}, {"dependents": {}}, {"dependents": {M1: []}}, [], None, "<html>",
        {"dependents": None}, {"dependents": {SRC: "x"}}, {"dependents": {SRC: ["x"]}},
        {"dependents": {SRC: []}, "csv": 7}])
    def test_unreadable_responses_are_refused(self, resp):
        with pytest.raises(c.CascadeError):
            c.mentioned(resp, SRC)

    def test_summarize_counts_other_and_unknown_owners(self):
        objs = [{"type": "MODEL", "author": "tsadmin"}, {"type": "MODEL", "author": "alice"},
                {"type": "ANSWER", "author": None}]
        assert c.summarize(objs, "tsadmin") == {
            "counts": {"MODEL": 2, "ANSWER": 1}, "total": 3, "owned_by_others": 1,
            "author_unknown": 1}

    def test_deleted_set_table_includes_source_column_does_not(self):
        assert c.deleted_set([{"guid": M1}], SRC, "LOGICAL_TABLE") == {M1, SRC}
        assert c.deleted_set([{"guid": M1}], COL, "LOGICAL_COLUMN") == {M1}

    @pytest.mark.parametrize("plan,msg", [
        ({"guid": SRC, "type": "LOGICAL_TABLE", "backup_dir": "/b"}, "confirm"),
        ({"guid": SRC, "type": "LOGICAL_TABLE", "backup_dir": "/b", "confirm": "delete"}, "confirm"),
        ({"guid": [SRC, M1], "type": "LOGICAL_TABLE", "backup_dir": "/b", "confirm": "DELETE"}, "ONE"),
        ({"guid": "Quarterly Revenue Model For Region", "type": "LOGICAL_TABLE",
          "backup_dir": "/b", "confirm": "DELETE"}, "ONE"),
        ({"guid": SRC, "type": "PINBOARD", "backup_dir": "/b", "confirm": "DELETE"}, "type"),
        ({"guid": SRC, "type": "LOGICAL_TABLE", "confirm": "DELETE"}, "backup_dir"),
        ([], "object")])
    def test_check_plan_refusals(self, plan, msg):
        with pytest.raises(c.CascadeError, match=msg):
            c.check_plan(plan)

    def test_backup_problems(self):
        good = {"source_object": {"guid": SRC},
                "objects": [{"guid": SRC, "intent": "DELETE", "backup_file": "a"}]}
        assert c.backup_problems(good, SRC, "LOGICAL_TABLE", SRC, {"a": True}) == []
        assert c.backup_problems(good, SRC, "LOGICAL_TABLE", SRC, {"a": False})
        assert c.backup_problems(good, SRC, "LOGICAL_TABLE", M1, {"a": True})
        col = {"source_object": {"guid": OWNER},
               "objects": [{"guid": M1, "intent": "DELETE", "backup_file": "a"}]}
        assert any("FIX_SOURCE" in p for p in
                   c.backup_problems(col, COL, "LOGICAL_COLUMN", OWNER, {"a": True}))

    def test_recheck(self):
        manifest = {"objects": [{"guid": M1, "intent": "DELETE"}, {"guid": OWNER, "intent": "FIX_SOURCE"}]}
        assert c.recheck({M1}, manifest)["match"]
        assert c.recheck({M1, M2}, manifest)["not_backed_up"] == [M2]
        assert c.recheck(set(), manifest)["no_longer_listed"] == [M1]

    def test_stale(self):
        assert c.stale({M1: 5, M2: 20, LB: None}, 10) == sorted([M2, LB])

    def test_classify_gone(self):
        assert c.classify_gone({M1, M2}, {M1, M2}) == "APPLIED"
        assert c.classify_gone({M1, M2}, set()) == "NOT_APPLIED"
        assert c.classify_gone({M1, M2}, {M1}) == "PARTIAL"


# ---------------------------------------------------------------------------
# Command shell — fake client
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status: int, body: Any):
        self.status_code, self._body = status, body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class FakeClient:
    """`auth/session/user` answers `user`. Every cascade call pops `script`; a script entry
    that is an Exception class is raised (the client refusing to retry an ambiguous
    failure). `metadata/search` answers from `present` (GUID → modified), which becomes
    `after_apply` once the delete is sent; `search_fails_after_apply` makes it raise."""

    def __init__(self, user: dict, script: List[Any], present: Optional[Dict[str, int]] = None,
                 after_apply: Optional[Dict[str, int]] = None, base_url: str = BASE,
                 search_fails_after_apply: bool = False):
        self.user, self.script, self.base_url = user, list(script), base_url
        self.present = dict(present if present is not None else {})
        self.after_apply, self.search_fails = after_apply, search_fails_after_apply
        self.cascade_calls: List[dict] = []

    def get(self, path, **_):
        assert path == "/api/rest/2.0/auth/session/user"
        return _Resp(200, self.user)

    def post(self, path, json=None, **_):
        assert path == "/api/rest/2.0/metadata/search"
        if self.applies and self.search_fails:
            raise SystemExit(1)
        return _Resp(200, [{"metadata_id": m["identifier"],
                            "metadata_header": {"modified": self.present[m["identifier"]]}}
                           for m in json["metadata"] if m["identifier"] in self.present])

    def request(self, method, path, **kw):
        assert (method, path) == ("POST", c.CASCADE_PATH)
        self.cascade_calls.append(kw)
        if kw["data"]["apply_changes"] == "true" and self.after_apply is not None:
            self.present = dict(self.after_apply)
        nxt = self.script.pop(0)
        if isinstance(nxt, type) and issubclass(nxt, BaseException):
            raise nxt(1)
        return nxt

    @property
    def applies(self):
        return [k for k in self.cascade_calls if k["data"]["apply_changes"] == "true"]


ADMIN = {"name": "tsadmin", "privileges": ["ADMINISTRATION", "AUTHORING"]}
GUEST = {"name": "guest", "privileges": ["AUTHORING", "DATAMANAGEMENT"]}

# What `resolve_source` answers for each reference: (guid, type, subtype, owner GUID).
KNOWN = {SRC: (SRC, "LOGICAL_TABLE", "ONE_TO_ONE_LOGICAL", None),
         "PRODUCT": (SRC, "LOGICAL_TABLE", "ONE_TO_ONE_LOGICAL", None),
         COL: (COL, "LOGICAL_COLUMN", None, OWNER),
         OWNER: (OWNER, "LOGICAL_TABLE", "ONE_TO_ONE_LOGICAL", None)}


def _resolve(ref, _client):
    if ref not in KNOWN:
        raise SourceUnresolvedError(ref)
    guid, typ, sub, owner = KNOWN[ref]
    parent = {"guid": owner, "name": "SUPPLIER", "subtype": "ONE_TO_ONE_LOGICAL"} if owner else None
    return SourceDescriptor(input=ref, guid=guid, type=typ, name="x", subtype=sub, parent=parent)


def _columns(_client, table_guid):
    return [{"header": {"id": COL, "name": "Supplier Name"}}] if table_guid == OWNER else []


def _run(args, fake, stdin=None):
    with patch("ts_cli.commands.dependency_cascade.ThoughtSpotClient", return_value=fake), \
         patch("ts_cli.commands.dependency_cascade.resolve_profile", return_value="p"), \
         patch("ts_cli.commands.dependency_cascade.resolve_source", side_effect=_resolve), \
         patch("ts_cli.commands.dependency_cascade._fetch_table_columns", side_effect=_columns):
        return runner.invoke(app, ["dependency"] + args, input=stdin)


def _out(result):
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


def _backup(tmp_path, source=SRC, deletes=(M1, M2, SRC), base_url=BASE, fix_source=True,
            missing_file=None):
    objs = [{"guid": g, "intent": "DELETE"} for g in deletes]
    if source != SRC and fix_source:
        objs.append({"guid": source, "intent": "FIX_SOURCE"})
    for o in objs:
        path = tmp_path / f"{o['guid']}.json"
        if o["guid"] != missing_file:
            path.write_text(json.dumps({"tml": {}}))
        o["backup_file"] = str(path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"base_url": base_url, "source_object": {"guid": source},
                                    "objects": objs}))
    os.utime(manifest, (100, 100))           # backup taken at t=100 s
    return str(tmp_path)


def _plan(backup_dir, guid=SRC, typ="LOGICAL_TABLE", **extra):
    return json.dumps({"guid": guid, "type": typ, "backup_dir": backup_dir,
                       "confirm": "DELETE", **extra})


ALL = {SRC: OLD, M1: OLD, M2: OLD}


class TestPreviewCommand:
    def test_admin_preview(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview(authors={M2: "alice"}))])
        r = _run(["cascade-preview", SRC], fake)
        assert r.exit_code == 0, _out(r)
        out = json.loads(r.stdout)
        assert out["status"] == "PREVIEW" and out["total"] == 2 and out["owned_by_others"] == 1
        assert out["source_deleted"] is True and out["source"]["guid"] == SRC
        assert out["backup_source"] == {"guid": SRC, "name": "x", "type": "TABLE"}
        assert fake.applies == [] and fake.cascade_calls[0]["data"]["apply_changes"] == "false"

    def test_preview_by_name(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())])
        r = _run(["cascade-preview", "PRODUCT"], fake)
        assert json.loads(r.stdout)["source"]["guid"] == SRC

    def test_column_by_name_resolves_its_guid_and_owner(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview(source=COL, deps=[_dep(M1, "A")]))])
        r = _run(["cascade-preview", OWNER, "--column", "Supplier Name"], fake)
        out = json.loads(r.stdout)
        assert out["source"] == {"guid": COL, "type": "LOGICAL_COLUMN"}
        assert out["source_deleted"] is False
        assert out["backup_source"] == {"guid": OWNER, "name": "x", "type": "TABLE"}
        assert fake.cascade_calls[0]["data"]["type"] == "LOGICAL_COLUMN"

    def test_unknown_column_name_sends_nothing(self):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-preview", OWNER, "--column", "Nope"], fake)
        assert r.exit_code == 1 and fake.cascade_calls == []

    def test_column_guid_names_the_owning_table_as_backup_source(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview(source=COL, deps=[_dep(M1, "A")]))])
        r = _run(["cascade-preview", COL, "--type", "LOGICAL_COLUMN"], fake)
        assert json.loads(r.stdout)["backup_source"]["guid"] == OWNER

    def test_type_mismatch_is_refused_before_any_cascade_call(self):
        # live 2026-10-30: the server previews a Table GUID sent as LOGICAL_COLUMN
        fake = FakeClient(ADMIN, [_Resp(200, _preview())])
        r = _run(["cascade-preview", SRC, "--type", "LOGICAL_COLUMN"], fake)
        assert r.exit_code == 1 and "is a LOGICAL_TABLE" in _out(r)
        assert fake.cascade_calls == []

    def test_non_admin_is_refused_before_any_cascade_call(self):
        fake = FakeClient(GUEST, [])
        r = _run(["cascade-preview", SRC], fake)
        assert r.exit_code == 1 and "administrators" in _out(r)
        assert fake.cascade_calls == []

    def test_business_rule_refusal_is_shown_verbatim(self):
        body = {"error_code": "METADATA_ERROR", "message": "Failed to process metadata",
                "details": "Error Message: Deleting columns linked to filters is not allowed"}
        fake = FakeClient(ADMIN, [_Resp(400, body)])
        r = _run(["cascade-preview", COL, "--type", "LOGICAL_COLUMN"], fake)
        assert r.exit_code == 1
        assert json.loads(r.stdout)["status"] == "REFUSED" and "linked to filters" in r.stdout

    def test_bad_type(self):
        assert _run(["cascade-preview", SRC, "--type", "PINBOARD"], FakeClient(ADMIN, [])).exit_code == 1


class TestDeleteCommand:
    def test_happy_path_sends_delete_once_and_confirms_everything_gone(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, _preview())],
                          present=ALL, after_apply={})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert r.exit_code == 0, _out(r)
        out = json.loads(r.stdout)
        assert out["status"] == "APPLIED" and out["still_present"] == []
        assert out["deleted"] == sorted([SRC, M1, M2]) and out["deleted_without_backup"] == []
        assert len(fake.applies) == 1
        assert fake.applies[0]["idempotent"] is False and fake.applies[0]["timeout"] == 600
        assert fake.cascade_calls[0]["data"]["apply_changes"] == "false"
        assert "--profile p" in out["rollback"]

    @pytest.mark.parametrize("bad", [
        {"confirm": "yes"}, {"guid": [SRC]}, {"type": "PINBOARD"}, {"backup_dir": ""}])
    def test_bad_plan_sends_nothing(self, tmp_path, bad):
        fake = FakeClient(ADMIN, [])
        plan = {**json.loads(_plan(_backup(tmp_path))), **bad}
        r = _run(["cascade-delete"], fake, json.dumps(plan))
        assert r.exit_code == 1 and fake.cascade_calls == []

    def test_missing_manifest_sends_nothing(self, tmp_path):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-delete"], fake, _plan(str(tmp_path / "nope")))
        assert r.exit_code == 1 and "manifest" in _out(r) and fake.cascade_calls == []

    def test_backup_from_another_cluster_sends_nothing(self, tmp_path):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, base_url="https://other")))
        assert r.exit_code == 1 and fake.cascade_calls == []

    def test_non_admin_sends_nothing(self, tmp_path):
        fake = FakeClient(GUEST, [])
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert r.exit_code == 1 and fake.cascade_calls == []

    @pytest.mark.parametrize("kwargs,plan_kw", [
        ({"source": M1, "deletes": (M2,)}, {"guid": COL, "typ": "LOGICAL_COLUMN"}),   # wrong owner
        ({"source": M1}, {}),                                                         # table: not itself
        ({"source": OWNER, "deletes": (M1,), "fix_source": False},
         {"guid": COL, "typ": "LOGICAL_COLUMN"}),                                      # no owner entry
        ({"missing_file": M1}, {}),                                                   # a file is gone
    ])
    def test_bad_backup_sends_nothing(self, tmp_path, kwargs, plan_kw):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, **kwargs), **plan_kw))
        assert r.exit_code == 1 and json.loads(r.stdout)["status"] == "BAD_BACKUP"
        assert fake.cascade_calls == []

    def test_guid_of_the_wrong_type_sends_nothing(self, tmp_path):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path), typ="LOGICAL_COLUMN"))
        assert r.exit_code == 1 and "is a LOGICAL_TABLE" in _out(r) and fake.cascade_calls == []

    def test_unknown_guid_sends_nothing(self, tmp_path):
        fake = FakeClient(ADMIN, [])
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, source=NEW), guid=NEW))
        assert r.exit_code == 1 and fake.cascade_calls == []

    @pytest.mark.parametrize("grown", [
        _preview(deps=[_dep(M1, "A"), _dep(M2, "B"), _dep(NEW, "New", "QUESTION_ANSWER_BOOK", None)]),
        _preview(extra_keys={M1: [_dep(NEW, "Deep", "QUESTION_ANSWER_BOOK", None)]}),
        _preview(csv_only=[_dep(NEW, "CSV only", "QUESTION_ANSWER_BOOK", None)])])
    def test_object_not_in_the_backup_blocks_the_delete(self, tmp_path, grown):
        fake = FakeClient(ADMIN, [_Resp(200, grown)], present=ALL)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "RECHECK_MISMATCH"
        assert out["not_backed_up"] == [NEW] and fake.applies == []

    def test_shrunk_scope_blocks_the_delete(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview(deps=[_dep(M1, "A")]))], present=ALL)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert json.loads(r.stdout)["no_longer_listed"] == [M2] and fake.applies == []

    def test_object_changed_after_backup_blocks_the_delete(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], present={**ALL, M2: 200_000})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "STALE_BACKUP"
        assert out["changed_since_backup"] == [M2] and fake.applies == []

    def test_refusal_on_apply_reports_nothing_deleted(self, tmp_path):
        body = {"error_code": "METADATA_ERROR", "details": "Deleting columns linked to filters is not allowed"}
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(400, body)], present=ALL)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert r.exit_code == 1 and json.loads(r.stdout)["status"] == "REFUSED"
        assert len(fake.applies) == 1

    def test_500_with_everything_present_is_not_applied(self, tmp_path):
        # live 2026-10-30: a cascade including a Liveboard failed this way; nothing deleted
        body = {"code": 14009, "debug": "FAILED_TO_COMMIT ... Restrict delete failed for edge=2"}
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(500, body)],
                          present=ALL, after_apply=ALL)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "NOT_APPLIED"
        assert "Restrict delete failed" in out["server_response"] and len(fake.applies) == 1

    def test_timeout_with_nothing_gone_yet_is_unknown_not_not_applied(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), SystemExit], present=ALL, after_apply=ALL)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "UNKNOWN" and "NOT run the delete again" in out["note"]
        assert len(fake.applies) == 1

    def test_timeout_but_everything_gone_is_applied_yet_not_exit_0(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), SystemExit], present=ALL, after_apply={})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert json.loads(r.stdout)["status"] == "APPLIED" and r.exit_code == 1

    def test_200_but_something_still_present_is_partial(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, _preview())],
                          present=ALL, after_apply={M2: OLD})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "PARTIAL" and out["still_present"] == [M2]

    @pytest.mark.parametrize("body", ["<html>ok</html>", {"dependents": {SRC: ["x"]}}, []])
    def test_unreadable_200_response_never_exits_0(self, tmp_path, body):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, body)],
                          present=ALL, after_apply={})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["response_readable"] is False

    def test_deleted_without_backup_fails_loudly(self, tmp_path):
        # the server's answer names an object outside the backup (here under another key)
        applied = _preview(extra_keys={M1: [_dep(NEW, "Deep", "QUESTION_ANSWER_BOOK", None)]})
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, applied)],
                          present=ALL, after_apply={})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["deleted_without_backup"] == [NEW]

    def test_existence_check_failure_after_delete_still_prints_status(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, _preview())],
                          present=ALL, search_fails_after_apply=True)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "UNKNOWN" and len(fake.applies) == 1

    def test_column_delete_happy_path(self, tmp_path):
        prev = _preview(source=COL, deps=[_dep(M1, "A")])
        fake = FakeClient(ADMIN, [_Resp(200, prev), _Resp(200, prev)],
                          present={COL: OLD, M1: OLD, OWNER: OLD}, after_apply={OWNER: OLD})
        r = _run(["cascade-delete"], fake,
                 _plan(_backup(tmp_path, source=OWNER, deletes=(M1,)), guid=COL, typ="LOGICAL_COLUMN"))
        assert r.exit_code == 0, _out(r)
        out = json.loads(r.stdout)
        assert out["deleted"] == sorted([COL, M1]) and out["status"] == "APPLIED"
