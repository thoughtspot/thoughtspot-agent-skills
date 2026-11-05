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

    def test_stale_compares_server_times_per_object(self):
        manifest = {"objects": [{"guid": M1, "modified": 5}, {"guid": M2, "modified": 5},
                                {"guid": LB, "modified": None}, {"guid": NEW}]}
        # M1 unchanged; M2 edited since; LB and NEW have no recorded time (an older
        # backup) and count as stale; OWNER is not in the backup at all.
        assert c.stale({M1: 5, M2: 6, LB: 5, NEW: 5, OWNER: 9}, manifest) == sorted([M2, LB, NEW])
        assert c.stale({}, manifest) == []          # absent objects are invisible()'s concern

    def test_invisible(self):
        assert c.invisible({M1: "LOGICAL_TABLE", M2: "ANSWER"}, {M1: 1}) == [M2]

    @pytest.mark.parametrize("status,body,want", [
        (None, None, False), (200, {}, False), (408, "", False), (502, "<html>", False),
        (524, "<html>", False), (500, "<html>proxy</html>", False), (503, {"x": 1}, False),
        (400, {"error_code": "METADATA_ERROR"}, True), (403, "", True), (404, "", True),
        (500, {"error": {"message": {"debug": {"code": 14009, "incident_id_guid": "i-1"}}}}, True),
        (500, {"message": "upstream connect error"}, False)])
    def test_definite_failure(self, status, body, want):
        assert c.definite_failure(status, body) is want

    @pytest.mark.parametrize("status,body,want", [
        (200, [{"edoc": json.dumps({"nls_feedback": {"feedback": [{"id": "1"}, {"id": "2"}]}})}], 2),
        (400, {"debug": "No accessible metadata objects found for the provided input."}, 0),
        (400, {"debug": "Specified identifier doesn't exist"}, None),
        (200, [{"edoc": "not json"}], None), (200, [], None), (500, "", None)])
    def test_feedback_count(self, status, body, want):
        assert c.feedback_count(status, body) == want

    def test_owners_in_scope(self):
        objs = [{"guid": M1, "type": "MODEL"}, {"guid": LB, "type": "LIVEBOARD"},
                {"guid": M2, "type": "VIEW"}]
        assert c.owners_in_scope(objs, SRC, "LOGICAL_TABLE") == {M1, M2, SRC}
        assert c.owners_in_scope(objs, COL, "LOGICAL_COLUMN") == {M1, M2}

    def test_attached_blockers(self):
        sets = {"sets": {M1: [{"guid": NEW, "name": "Top customers"}], M2: []},
                "incomplete": [SRC]}
        headers = {M1: {"orgIds": [0], "ownerOrgId": 0}, M2: {"orgIds": [0, 7], "ownerOrgId": 0}}
        out = c.attached_blockers({M1, M2, SRC}, sets, {M1: 0, M2: 3, SRC: None}, headers)
        kinds = {(b["owner"], b["kind"]) for b in out}
        assert kinds == {(M1, "SET"), (M2, "FEEDBACK"), (M2, "PUBLISHED"), (SRC, "SETS_UNCHECKED"),
                         (SRC, "FEEDBACK_UNCHECKED"), (SRC, "PUBLISHED_UNCHECKED")}
        assert [b["org_ids"] for b in out if b["kind"] == "PUBLISHED"] == [[7]]
        assert c.attached_blockers({M1}, {"sets": {M1: []}}, {M1: 0}, {M1: {}}) == []

    def test_feedback_count_reads_a_yaml_edoc(self):
        edoc = "nls_feedback:\n  feedback:\n  - id: '1'\n"
        assert c.feedback_count(200, [{"edoc": edoc}]) == 1

    @pytest.mark.parametrize("resp", [
        {"dependents": {SRC: [{"name": "no id"}]}, "csv": ""},
        {"dependents": {SRC: []}, "csv": CSV_HEAD + "\n" + SRC + ",x,,Lost Answer,QUESTION_ANSWER_BOOK,,,,,a,b,0,Primary\n"}])
    def test_entries_without_a_guid_are_refused_not_dropped(self, resp):
        with pytest.raises(c.CascadeError, match="refusing"):
            c.mentioned(resp, SRC)

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
    """`auth/session/user` answers `user`. A cascade call on a source (`ROOTS`) pops
    `script`; a script entry that is an Exception class is raised (the client refusing to
    retry an ambiguous failure). A preview of anything else — the extra previews that
    widen the scope — answers `sub[guid]`, or no dependents. `metadata/search` answers
    from `present` (GUID → modified), which becomes `after_apply` once the delete is sent;
    `search_fails_after_apply` makes it raise. The cohort listing answers `sets[guid]`
    (a list of rows, or an Exception class to raise); the FEEDBACK export answers
    `feedback[guid]` entries, none by default. With `present` left out, every searched
    object exists (the preview-only default); `published[guid]` adds Org ids."""

    ROOTS = (SRC, COL, OWNER)

    def __init__(self, user: dict, script: List[Any], present: Optional[Dict[str, int]] = None,
                 after_apply: Optional[Dict[str, int]] = None, base_url: str = BASE,
                 search_fails_after_apply: bool = False, sub: Optional[Dict[str, Any]] = None,
                 sets: Optional[Dict[str, Any]] = None, feedback: Optional[Dict[str, int]] = None,
                 org: str = "", published: Optional[Dict[str, List[int]]] = None):
        self.user, self.script, self.base_url, self.org = user, list(script), base_url, org
        self.present = None if present is None else dict(present)
        self.published = published or {}
        self.after_apply, self.search_fails = after_apply, search_fails_after_apply
        self.sub, self.sets, self.feedback = sub or {}, sets or {}, feedback or {}
        self.cascade_calls: List[dict] = []

    def get(self, path, **_):
        if path.startswith("/callosum/v1/metadata/detail/"):
            rows = self.sets.get(path.rsplit("/", 1)[1], [])
            if isinstance(rows, type) and issubclass(rows, BaseException):
                raise rows(1)
            return _Resp(200, rows)
        assert path == "/api/rest/2.0/auth/session/user"
        return _Resp(200, self.user)

    def _feedback_export(self, guid):
        n = self.feedback.get(guid, 0)
        if not n:
            return _Resp(400, {"debug": "No accessible metadata objects found for the provided input."})
        fb = {"nls_feedback": {"feedback": [{"id": str(i)} for i in range(n)]}}
        return _Resp(200, [{"edoc": json.dumps(fb)}])

    def post(self, path, json=None, **_):
        assert path == "/api/rest/2.0/metadata/search"
        if self.applies and self.search_fails:
            raise SystemExit(1)
        assert json.get("include_hidden_objects") and json.get("include_incomplete_objects")
        present = (self.present if self.present is not None
                   else {m["identifier"]: OLD for m in json["metadata"]})
        return _Resp(200, [{"metadata_id": g, "metadata_header": {
                               "modified": present[g], "ownerOrgId": 0,
                               "orgIds": [0] + self.published.get(g, [])}}
                           for g in (m["identifier"] for m in json["metadata"]) if g in present])

    def request(self, method, path, **kw):
        if path == "/api/rest/2.0/metadata/tml/export":
            return self._feedback_export(kw["json"]["metadata"][0]["identifier"])
        assert (method, path) == ("POST", c.CASCADE_PATH)
        guid = json.loads(kw["data"]["id"])[0]
        if kw["data"]["apply_changes"] == "false" and guid not in self.ROOTS:
            answer = self.sub.get(guid, {"dependents": {guid: []}, "csv": CSV_HEAD + "\n"})
            return answer if isinstance(answer, _Resp) else _Resp(200, answer)
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
            missing_file=None, org=""):
    objs = [{"guid": g, "intent": "DELETE", "modified": OLD} for g in deletes]
    if source != SRC and fix_source:
        objs.append({"guid": source, "intent": "FIX_SOURCE", "modified": OLD})
    for o in objs:
        path = tmp_path / f"{o['guid']}.json"
        if o["guid"] != missing_file:
            path.write_text(json.dumps({"tml": {}}))
        o["backup_file"] = str(path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"base_url": base_url, "org": org,
                                    "source_object": {"guid": source}, "objects": objs}))
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
        assert fake.applies[0]["idempotent"] is False and fake.applies[0]["timeout"] == 900
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
        body = {"error": {"message": {"debug": {"code": 14009, "incident_id_guid": "i-1", "debug": "FAILED_TO_COMMIT ... Restrict delete failed for edge=2"}}}}
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


# ---------------------------------------------------------------------------
# PR #692 review: Sets and feedback, scope union, timeouts, visibility, outcomes
# ---------------------------------------------------------------------------

def _set_row(guid, name):
    return {"header": {"id": guid, "name": name}, "cohortConfig": {"cohort_type": "SIMPLE"}}


SET1 = "22222222-3333-4444-5555-666666666666"


class TestReviewFixes:
    def test_preview_is_never_retried_and_waits_long(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())])
        _run(["cascade-preview", SRC], fake)
        assert fake.cascade_calls[0]["idempotent"] is False
        assert fake.cascade_calls[0]["timeout"] == 900

    def test_a_models_set_blocks_the_preview(self):
        # live 2026-11-02: the preview of a Model never names its Sets, yet the delete
        # removes them
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], sets={M1: [_set_row(SET1, "Top")]})
        r = _run(["cascade-preview", SRC], fake)
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "BLOCKED"
        assert out["attached"] == [{"owner": M1, "kind": "SET", "guid": SET1, "name": "Top",
                                    "owner_name": "Model A"}]

    def test_a_models_feedback_blocks_the_preview(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], feedback={M1: 2})
        out = json.loads(_run(["cascade-preview", SRC], fake).stdout)
        assert out["status"] == "BLOCKED"
        assert [(b["owner"], b["kind"], b["count"]) for b in out["attached"]] == [(M1, "FEEDBACK", 2)]

    def test_a_failed_set_listing_blocks_rather_than_reads_as_none(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], sets={M2: RuntimeError})
        out = json.loads(_run(["cascade-preview", SRC], fake).stdout)
        assert out["status"] == "BLOCKED" and out["attached"][0]["kind"] == "SETS_UNCHECKED"

    def test_a_column_delete_does_not_check_the_owner_it_keeps(self):
        prev = _preview(source=COL, deps=[_dep(M1, "A")])
        fake = FakeClient(ADMIN, [_Resp(200, prev)], feedback={OWNER: 4})
        r = _run(["cascade-preview", OWNER, "--column", "Supplier Name"], fake)
        assert r.exit_code == 0 and json.loads(r.stdout)["attached"] == []

    def test_sets_block_the_delete_before_anything_is_sent(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], present=ALL,
                          sets={SRC: [_set_row(SET1, "Top")]})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path)))
        assert r.exit_code == 1 and json.loads(r.stdout)["status"] == "BLOCKED"
        assert fake.applies == []

    def test_scope_includes_what_a_listed_models_own_preview_names(self):
        sub = {M1: _preview(source=M1, deps=[_dep(NEW, "Deep Answer", "QUESTION_ANSWER_BOOK", None)])}
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], sub=sub)
        out = json.loads(_run(["cascade-preview", SRC], fake).stdout)
        assert {o["guid"] for o in out["objects"]} == {M1, M2, NEW} and out["total"] == 3

    def test_a_wider_scope_than_the_backup_blocks_the_delete(self, tmp_path):
        sub = {M2: _preview(source=M2, deps=[_dep(NEW, "Deep", "QUESTION_ANSWER_BOOK", None)])}
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], present=ALL, sub=sub)
        out = json.loads(_run(["cascade-delete"], fake, _plan(_backup(tmp_path))).stdout)
        assert out["status"] == "RECHECK_MISMATCH" and out["not_backed_up"] == [NEW]
        assert fake.applies == []

    def test_an_object_the_existence_check_cannot_see_blocks_the_delete(self, tmp_path):
        prev = _preview(deps=[_dep(M1, "A"), _dep(LB, "LB", "PINBOARD_ANSWER_BOOK", None)])
        fake = FakeClient(ADMIN, [_Resp(200, prev)], present={SRC: OLD, M1: OLD})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, deletes=(M1, LB, SRC))))
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == "NOT_VISIBLE" and out["not_visible"] == [LB]
        assert fake.applies == []

    def test_a_backup_without_recorded_times_is_stale(self, tmp_path):
        bd = _backup(tmp_path)
        m = json.loads((tmp_path / "manifest.json").read_text())
        for o in m["objects"]:
            o.pop("modified")
        (tmp_path / "manifest.json").write_text(json.dumps(m))
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], present=ALL)
        out = json.loads(_run(["cascade-delete"], fake, _plan(bd)).stdout)
        assert out["status"] == "STALE_BACKUP" and fake.applies == []

    @pytest.mark.parametrize("manifest_kw,client_kw", [
        ({"org": "7"}, {}), ({}, {"org": "7"}), ({"base_url": ""}, {})])
    def test_another_org_or_an_unrecorded_cluster_sends_nothing(self, tmp_path, manifest_kw, client_kw):
        fake = FakeClient(ADMIN, [], **client_kw)
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, **manifest_kw)))
        assert r.exit_code == 1 and fake.cascade_calls == []

    def test_a_trailing_slash_is_the_same_cluster(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, _preview())],
                          present=ALL, after_apply={})
        r = _run(["cascade-delete"], fake, _plan(_backup(tmp_path, base_url=BASE.upper() + "/")))
        assert r.exit_code == 0, _out(r)

    @pytest.mark.parametrize("resp", [_Resp(502, "<html>Bad gateway</html>"), _Resp(408, ""),
                                      _Resp(524, "<html>timeout</html>"),
                                      _Resp(500, "<html>proxy error</html>")])
    def test_a_gateway_answer_with_nothing_gone_yet_is_unknown(self, tmp_path, resp):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), resp], present=ALL, after_apply=ALL)
        out = json.loads(_run(["cascade-delete"], fake, _plan(_backup(tmp_path))).stdout)
        assert out["status"] == "UNKNOWN" and "NOT run the delete again" in out["note"]

    def test_a_200_with_nothing_gone_is_unknown_not_not_applied(self, tmp_path):
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(200, _preview())],
                          present=ALL, after_apply=ALL)
        out = json.loads(_run(["cascade-delete"], fake, _plan(_backup(tmp_path))).stdout)
        assert out["status"] == "UNKNOWN"

    def test_endpoint_switched_off_says_so(self):
        body = {"error": {"code": "API_NOT_ALLOWED",
                          "message": "Requested API is not enabled. Reach out to SRE to enable this API"}}
        fake = FakeClient(ADMIN, [_Resp(404, body)])
        r = _run(["cascade-preview", SRC], fake)
        assert r.exit_code == 1 and json.loads(r.stdout)["status"] == "NOT_AVAILABLE"


class TestSecondReviewFixes:
    """The independent review of the PR #692 fixes."""

    def test_an_object_published_into_other_orgs_blocks(self):
        # the Set listing sees only the caller's Org: another Org's Sets would go unlisted
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], published={M2: [7]})
        out = json.loads(_run(["cascade-preview", SRC], fake).stdout)
        assert out["status"] == "BLOCKED"
        assert [(b["owner"], b["kind"], b["org_ids"]) for b in out["attached"]] == [(M2, "PUBLISHED", [7])]

    def test_a_refusal_after_the_delete_is_sent_is_checked_against_existence(self, tmp_path):
        body = {"error_code": "METADATA_ERROR", "details": "Deleting columns linked to filters is not allowed"}
        fake = FakeClient(ADMIN, [_Resp(200, _preview()), _Resp(400, body)], present=ALL, after_apply={})
        out = json.loads(_run(["cascade-delete"], fake, _plan(_backup(tmp_path))).stdout)
        assert out["status"] == "APPLIED" and out["deleted"] == sorted([SRC, M1, M2])

    @pytest.mark.parametrize("answer,status", [
        (_Resp(400, {"error_code": "METADATA_ERROR", "details": "linked to filters"}), "REFUSED"),
        (_Resp(500, {"error": {"message": {"debug": {"code": 14009, "incident_id_guid": "i"}}}}),
         "PREVIEW_FAILED")])
    def test_a_widening_preview_failure_names_the_object(self, answer, status):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())], sub={M1: answer})
        r = _run(["cascade-preview", SRC], fake)
        out = json.loads(r.stdout)
        assert r.exit_code == 1 and out["status"] == status
        assert out["while_previewing"] == {"guid": M1, "name": "Model A", "type": "MODEL"}


# The FEEDBACK export's answers on a staging cluster (PR #692 review, 2026-11-03).
_E14531 = {"error": {"message": {"debug": {"code": 14531, "incident_id_guid": "i",
           "debug": "Cannot manage feedbacks for object that is not Spotter-enabled"}}}}
_E13006 = {"error": {"message": {"debug": {"code": 13006, "incident_id_guid": "i",
           "debug": "Object of type SQL_VIEW cannot have associated NLS feedback"}}}}
_E10002 = {"error": {"message": {"debug": {"code": 10002, "incident_id_guid": "i",
           "debug": "No accessible metadata objects found for the provided input."}}}}


class TestFeedbackOnlyOnModels:
    """Damian's 2026-11-03 blocker: the feedback lookup answered Tables, Views and SQL
    Views with an error, so every delete reaching one was BLOCKED."""

    @pytest.mark.parametrize("status,body,want", [
        (400, _E10002, 0),                    # Model with no feedback
        (500, _E14531, 0),                    # Table / View: not Spotter-enabled
        (500, _E13006, 0),                    # SQL View
        (500, {"error": {"message": {"debug": {"code": 99999}}}}, None),   # anything else
        (500, "<html>proxy</html>", None)])
    def test_each_answer_shape(self, status, body, want):
        assert c.feedback_count(status, body) == want

    def test_a_tables_and_views_feedback_is_not_looked_up(self):
        # SRC is a Table; M1, M2 are a View and a SQL View here. Only Models are asked.
        prev = _preview(deps=[_dep(M1, "V", "LOGICAL_TABLE", "AGGR_WORKSHEET"),
                              _dep(M2, "SV", "LOGICAL_TABLE", "SQL_VIEW")])
        fake = FakeClient(ADMIN, [_Resp(200, prev)], feedback={SRC: 3, M1: 3, M2: 3})
        exported = []
        real = fake._feedback_export
        fake._feedback_export = lambda g: exported.append(g) or real(g)
        r = _run(["cascade-preview", SRC], fake)
        assert r.exit_code == 0, _out(r)
        assert json.loads(r.stdout)["status"] == "PREVIEW" and exported == []

    def test_a_model_whose_lookup_fails_still_blocks(self):
        fake = FakeClient(ADMIN, [_Resp(200, _preview())])
        fake._feedback_export = lambda g: _Resp(500, "<html>proxy</html>")
        out = json.loads(_run(["cascade-preview", SRC], fake).stdout)
        assert out["status"] == "BLOCKED"
        assert {(b["owner"], b["kind"]) for b in out["attached"]} == {
            (M1, "FEEDBACK_UNCHECKED"), (M2, "FEEDBACK_UNCHECKED")}

    def test_a_model_source_is_looked_up(self, tmp_path):
        KNOWN["MODEL_SRC"] = (SRC, "LOGICAL_TABLE", "WORKSHEET", None)
        try:
            fake = FakeClient(ADMIN, [_Resp(200, _preview(deps=[]))], feedback={SRC: 1})
            out = json.loads(_run(["cascade-preview", "MODEL_SRC"], fake).stdout)
        finally:
            del KNOWN["MODEL_SRC"]
        assert [(b["owner"], b["kind"]) for b in out["attached"]] == [(SRC, "FEEDBACK")]
