"""Unit tests for check_customer_references.py — links into a tenant's internal systems.

Every FIRING fixture below is assembled with ``_j()`` from pieces that split the host,
so this file never holds a contiguous tenant link (or personal path / address). Otherwise
the gate's own CI ``--all`` run would flag its tests — and exempting the test file instead
would be a hole a real leak could hide in. Fake tenants only (``acme-corp``).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import check_customer_references as ccr

VALIDATE = Path(__file__).resolve().parents[1]
DOC_ID = "1AbCdEfGh2IjKlMnOp3QrStUvWx4YzAbCdEf"


def _j(*parts: str) -> str:
    return "".join(parts)


def _hits(text: str, rel_path: str = "", level: str = "FAIL") -> list:
    return [h for h in ccr.scan_text(text, rel_path) if h.level == level]


def _rules(text: str, rel_path: str = "") -> list[str]:
    return [h.rule for h in _hits(text, rel_path)]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    """A maintainer's real denylist must never leak into the suite or its output."""
    monkeypatch.delenv(ccr.DENYLIST_ENV, raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))


# ── each pattern fires ───────────────────────────────────────────────────────

FIRING = [
    ("sharepoint/onedrive", _j("https://acme-corp-my.", "sharepoint.com/personal/jane_doe_acme-corp_com/Documents/model.xlsx")),
    ("sharepoint/onedrive", _j("https://acme-corp.", "sharepoint.com/sites/Finance/Shared%20Documents/q3.xlsx")),
    ("sharepoint/onedrive", _j("https://acme-corp.", "sharepoint.com/:x:/r/teams/BI/abc")),
    ("sharepoint/onedrive", _j("https://acme-corp.", "sharepoint.us/sites/Gov")),
    ("sharepoint/onedrive", _j("https://acme-corp.", "sharepoint.cn/sites/Cn")),
    ("teams", _j("https://teams.", "microsoft.com/l/message/19:abc@thread.skype/123")),
    ("onedrive-consumer", _j("https://1drv", ".ms/x/s!AbCdEf123")),
    ("onedrive-consumer", _j("https://onedrive", ".live.com/edit.aspx?resid=ABC123")),
    ("atlassian", _j("https://acme-corp.", "atlassian.net/browse/DATA-1234")),
    ("atlassian", _j("https://acme-corp.", "atlassian.net/wiki/spaces/BI/pages/123")),
    ("atlassian", _j("https://thoughtspot.", "atlassian.net/wiki/spaces/ENG/pages/1")),
    ("atlassian", _j("https://thoughtspot.", "atlassian.net/jira/software/projects/X")),
    ("slack", _j("https://acme-corp.", "slack.com/archives/C01ABCDEF/p1700000000000000")),
    ("slack", _j("https://app.", "slack.com/client/T01ABC/C01DEF")),
    ("slack", _j("https://acme-corp.", "slack.com/files/U01/F01/report.csv")),
    ("slack", _j("https://acme-corp.", "slack.com/team/U01ABC")),
    ("slack", _j("https://hooks.", "slack.com/services/T0/B0/x")),
    ("google-doc", _j("https://docs.", f"google.com/document/d/{DOC_ID}/edit")),
    ("google-doc", _j("https://docs.", f"google.com/spreadsheets/d/{DOC_ID}/edit#gid=0")),
    ("google-doc", _j("https://docs.", f"google.com/presentation/u/0/d/{DOC_ID}")),
    ("google-doc", _j("https://docs.", f"google.com/forms/d/e/{DOC_ID}/viewform")),
    ("google-doc", _j("https://docs.", "google.com/a/acme-corp.com/document/d/x")),
    ("google-drive", _j("https://drive.", f"google.com/file/d/{DOC_ID}/view")),
    ("google-drive", _j("https://drive.", f"google.com/drive/folders/{DOC_ID}")),
    ("google-drive", _j("https://drive.", f"google.com/open?id={DOC_ID}")),
    ("google-drive", _j("https://drive.", f"google.com/uc?export=download&id={DOC_ID}")),
    ("google-forms", _j("https://forms", ".gle/AbCdEf12345")),
    ("snowflake", _j("https://acme-corp.", "snowflakecomputing.com")),
    ("snowflake", _j("https://ab12345.us-east-1.", "snowflakecomputing.com")),
    ("snowflake", _j("https://app.", "snowflake.com/acme-corp/prod-account/#/data")),
    ("databricks", _j("https://acme-corp-prod.", "cloud.databricks.com/?o=1")),
    ("databricks", _j("https://dbc-1a2b3c4d-9f8e.", "cloud.databricks.com")),
    ("databricks", _j("https://adb-8890275531604417.7.", "azuredatabricks.net")),
    ("qlik", _j("https://acme-corp.eu.", "qlikcloud.com/sense/app/1")),
    ("looker", _j("https://acme-corp.", "looker.com/dashboards/1")),
    ("looker", _j("https://acme-corp.cloud.", "looker.com/explore/x")),
    ("salesforce", _j("https://acme-corp.", "my.salesforce.com/001")),
    ("salesforce", _j("https://acme-corp.", "lightning.force.com/lightning/r/Account")),
    ("thoughtspot-cluster", _j("https://acme-corp.", "thoughtspot.cloud/#/pinboard/abc")),
    ("thoughtspot-cluster", _j("base_url: acme-corp-prod.", "thoughtspot.cloud")),
    ("thoughtspot-cluster", _j("https://acme-corp.", "thoughtspotstaging.cloud")),
    ("thoughtspot-cluster", _j("https://acme-corp.", "thoughtspot.com/")),
]


@pytest.mark.parametrize("rule,text", FIRING)
def test_pattern_fires(rule, text):
    assert _rules(text) == [rule]


def test_case_insensitive():
    assert _rules(_j("HTTPS://ACME-CORP.", "ATLASSIAN.NET/browse/X-1")) == ["atlassian"]


def test_personal_onedrive_in_js_comment_fires():
    # The real-world shape: a OneDrive path left in a comment in example code.
    js = _j(
        "const data = load();  // source: https://acme-corp-my.",
        "sharepoint.com/personal/jane_doe_acme-corp_com/Documents/Example/data.xlsx\n",
    )
    hits = _hits(js)
    assert [(h.line, h.rule) for h in hits] == [(1, "sharepoint/onedrive")]


def test_my_prefixed_real_tenant_still_fires():
    assert _rules(_j("https://myacme-corp.", "thoughtspot.cloud")) == ["thoughtspot-cluster"]


def test_hit_reports_line_number():
    text = "line one\nline two\n" + _j("see https://acme-corp.", "atlassian.net/browse/A-1\n")
    assert [h.line for h in _hits(text)] == [3]


# ── finding 2: markup and encoding cannot smuggle a host past the placeholder test ──

@pytest.mark.parametrize("text", [
    _j("**acme-corp.", "thoughtspot.cloud**"),
    _j("*acme-corp.", "atlassian.net*"),
    _j("[acme-corp.", "thoughtspot.cloud]"),
    _j("<td>acme-corp.", "thoughtspot.cloud</td>"),
    _j("[acme-corp.", "atlassian.net](https://example.com)"),
    _j("`acme-corp.", "thoughtspot.cloud`"),
])
def test_markup_around_a_real_host_still_fires(text):
    assert len(_rules(text)) == 1


@pytest.mark.parametrize("text", [
    _j("https://acme-{env}.", "thoughtspot.cloud"),        # a template token inside a real label
    _j("https://{env}.acme-corp.", "thoughtspot.cloud"),   # a template label beside a real one
    _j("https://a.acme-corp.", "atlassian.net/browse/X-1"),
    _j("https://*.acme-corp.", "thoughtspot.cloud"),
])
def test_template_only_exempts_a_whole_label(text):
    assert len(_rules(text)) == 1


def test_safelinks_percent_encoded_onedrive_fires():
    line = _j("https://eur01.safelinks.protection.outlook.com/?url=https%3A%2F%2Facme-corp-my.",
              "sharepoint.com%2Fpersonal%2Fjane_doe%2FDocuments&data=05")
    assert _rules(line) == ["sharepoint/onedrive"]


def test_google_redirect_percent_encoded_doc_fires():
    line = _j("https://www.google.com/url?q=https%3A%2F%2Fdocs.", f"google.com%2Fdocument%2Fd%2F{DOC_ID}%2Fedit")
    assert _rules(line) == ["google-doc"]


def test_double_percent_encoded_fires():
    line = _j("?u=https%253A%252F%252Facme-corp.", "atlassian.net%252Fwiki%252Fx")
    assert _rules(line) == ["atlassian"]


def test_html_entity_encoded_fires():
    assert _rules(_j("acme-corp&#46;", "atlassian&#46;net/browse/X-1")) == ["atlassian"]


# ── item 1: matching is linear — no catastrophic backtracking ────────────────

ADVERSARIAL = {
    # the round-2 reproductions: 60s+ at 50K before the fix
    "star": "a*", "bracket": "[a]", "percent": "%a%", "brace": "{a}", "angle": "<a>", "dots": "a.",
    # round 3: a host FOLLOWED BY A PATH, for every rule family (the path capture used to run
    # to the end of the line: 106s at 1M for `x.slack.com/`)
    "sharepoint": _j("x.sharepoint", ".com/"), "atlassian": _j("x.atlassian", ".net/"),
    "slack": _j("x.slack", ".com/"), "snowflake": _j("x.snowflakecomputing", ".com/"),
    "databricks": _j("x.cloud.databricks", ".com/"), "box-host": _j("x.app.box", ".com/"),
    "qlik": _j("x.qlikcloud", ".com/"), "looker": _j("x.looker", ".com/"),
    "salesforce": _j("x.my.salesforce", ".com/"), "thoughtspot": _j("x.thoughtspot", ".cloud/"),
    "slack-firing": _j("acme-corp.slack", ".com/a"), "ts-firing": _j("acme-corp.thoughtspot", ".cloud/a"),
    "onedrive": _j("1drv", ".ms/"), "teams": _j("teams.microsoft", ".com/l/"),
    "gdoc": _j("docs.google", ".com/document/d/"), "gdomain": _j("docs.google", ".com/a/"),
    "drive": _j("drive.google", ".com/uc?a&"), "forms": _j("forms", ".gle/a"),
    "sf-app": _j("app.snowflake", ".com/a"), "tableau": _j("#/si", "te/a"),
    "powerbi": _j("app.powerbi", ".com/groups/a"), "box-share": _j("app.box", ".com/s/a"),
    "dropbox": _j("dropbox", ".com/s/a"), "zoom": _j("zoom", ".us/j/"), "gong": _j("app.gong", ".io/call"),
    "email": "a.b@c.", "home": _j("/Use", "rs/a"),
    # round 4: long-tenant shapes found by the final review (up to 0.49s locally at 1M)
    "long-region-tenant": "us-east-1." * 25 + _j("x.snowflakecomputing", ".com "),
    "long-markup-tenant": "x" + "*" * 255 + _j("y.sharepoint", ".com "),
    "many-dot-labels": "a." * 128 + _j("slack", ".com/"),
}

# Linearity is asserted as a GROWTH RATIO, not a wall-clock budget: CI runners are several
# times slower than a laptop, and a fixed 1s budget failed there on correct code. Linear
# code scales x4 from 250K to 1M; the quadratic code this guards against scaled x16.
_RATIO_LIMIT = 8.0
_CEILING_1M = 10.0        # seconds; still far below the ~100s of the quadratic version
_NOISE_FLOOR = 0.05       # a 1M scan this fast cannot be quadratic; ratios of tiny times are noise


def _scan_seconds(seed: str, size: int) -> float:
    import time
    line = "thoughtspot slack sharepoint google " + seed * (size // len(seed))
    start = time.perf_counter()
    ccr.scan_text(line, "x.md")
    return time.perf_counter() - start


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_adversarial_line_scans_in_linear_time(name):
    seed = ADVERSARIAL[name]
    small = big = float("inf")
    for _ in range(3):                    # best of up to 3, retried only while it looks bad
        small = min(small, _scan_seconds(seed, 250_000))
        big = min(big, _scan_seconds(seed, 1_000_000))
        assert big < _CEILING_1M, f"{name}: {big:.2f}s at 1M"
        if big < _NOISE_FLOOR or big / small < _RATIO_LIMIT:
            return
    pytest.fail(f"{name}: 1M/250K = {big / small:.1f} (> {_RATIO_LIMIT}) — not linear")


# ── allowlisted hosts and placeholders do not fire ───────────────────────────

@pytest.mark.parametrize("host", sorted(ccr.ALLOWED_HOSTS))
def test_allowlisted_host_is_clean(host):
    assert _rules(f"https://{host}/some/path") == []


def test_thoughtspot_jira_allowed_only_for_tickets_and_bare_host():
    assert _rules("https://thoughtspot.atlassian.net/browse/SCAL-326935") == []
    assert _rules("[SCAL-1](https://thoughtspot.atlassian.net/browse/SCAL-1)") == []
    assert _rules("cloudId `thoughtspot.atlassian.net`") == []


@pytest.mark.parametrize("text", [
    "https://{instance}.thoughtspot.cloud",
    "https://{your-instance}.thoughtspot.cloud",
    "https://<your-cluster>.thoughtspot.cloud",
    "https://[tenant].thoughtspot.cloud",
    "https://%TENANT%.thoughtspot.cloud",
    "https://${TS_HOST}.thoughtspot.cloud",
    "https://*.thoughtspot.cloud",
    "https://your-instance.thoughtspot.cloud",
    "https://example.thoughtspot.cloud",
    "https://se.example.thoughtspot.cloud",
    "https://example-tenant.thoughtspot.cloud",
    "https://mycompany.thoughtspot.cloud",
    "https://myorg-staging.thoughtspot.cloud",
    "https://myco.thoughtspot.cloud",
    "https://my.thoughtspot.cloud",
    "https://yourorg.thoughtspot.cloud",
    "https://company.thoughtspot.cloud",
    "https://test.thoughtspot.cloud",
    "https://demo.thoughtspot.cloud",
    "https://a.thoughtspot.cloud",
    "https://your-domain.atlassian.net/browse/PROJ-1",
    "https://{tenant}-my.sharepoint.com/personal/{user}/Documents",
    "https://<tenant>.sharepoint.com/sites/<site>",
    "https://<workspace>.slack.com/archives/<channel>",
    "https://acme-corp.slack.com",                      # bare workspace root
    "https://docs.google.com/document/d/YOUR_DOC_ID/edit",
    "https://drive.google.com/file/d/<file-id>/view",
    "https://docs.google.com/document/d/{doc_id}/edit",
    # Placeholder forms the repo already uses (grepped 2026-10-08):
    "https://dbc-abc123.cloud.databricks.com",
    "https://dbc-def456.cloud.databricks.com",
    "https://dbc-xxxxx.cloud.databricks.com",
    "https://dbx.cloud.databricks.com",
    "https://your-workspace.cloud.databricks.com",
    "https://adb-1234567890.1.azuredatabricks.net",
    "https://acme.us.qlikcloud.com",
    "https://acme.qlikcloud.com",
    "<account-identifier>.snowflakecomputing.com",
    "https://app.snowflake.com/<org>/<account>/",
])
def test_placeholder_is_clean(text):
    assert _rules(text) == []


@pytest.mark.parametrize("text", [
    # A real workspace id is random and can contain a filler pattern by chance; its exact
    # shape must still fire (the repo's own test-workspace host was this shape).
    _j("https://dbc-abc12345-9f8e.", "cloud.databricks.com"),
    _j("https://dbc-12345678-9f8e.", "cloud.databricks.com/?o=7"),
    _j("https://adb-1234567890123457.3.", "azuredatabricks.net"),
])
def test_real_databricks_id_shapes_fire_even_with_filler(text):
    assert _rules(text) == ["databricks"]


@pytest.mark.parametrize("text", [
    "https://your-workspace.cloud.databricks.com",     # databricks.yml / docs placeholder
    "/sql/1.0/warehouses/{warehouse_id}",
])
def test_databricks_placeholders_now_in_the_tree_are_clean(text):
    assert ccr.scan_text(text) == []


# ── item 6: more tenant systems ──────────────────────────────────────────────

@pytest.mark.parametrize("rule,text", [
    ("tableau-site", _j("https://10ay.online.tableau.com/#/site/", "acme-corp/workbooks")),
    ("tableau-site", _j("https://tableau.acme-corp.com/#/site/", "Finance/views/x")),
    ("databricks", _j("https://acme-corp.", "gcp.databricks.com/?o=1")),
    ("databricks", _j("https://acme-corp.", "cloud.databricks.us")),
    ("power-bi", _j("https://app.powerbi.com/groups/", "4f1e2d3c-aaaa-bbbb-cccc-0123456789ab/reports/x")),
    ("power-bi", _j("https://app.powerbi.com/groups/", "me/reports/x")),
    ("box", _j("https://acme-corp.app.", "box.com/folder/1")),
    ("box", _j("https://app.box.com/s/", "abc9xyz")),
    ("dropbox", _j("https://www.dropbox.com/s/", "a1b2c3/report.xlsx")),
    ("dropbox", _j("https://www.dropbox.com/scl/", "fi/a1b2/report.xlsx")),
    ("zoom", _j("https://us02web.zoom", ".us/j/81234567890")),
    ("zoom", _j("https://acme-corp.zoom", ".us/rec/share/abc")),
    ("gong", _j("https://app.gong", ".io/call?id=123")),
])
def test_new_coverage_fires(rule, text):
    assert _rules(text) == [rule]


# ── item 7: vendor placeholders and public hosts stay quiet; tightened words fire ──

@pytest.mark.parametrize("text", [
    "ORGNAME-ACCOUNTNAME.snowflakecomputing.com",
    "https://xy12345.us-east-1.snowflakecomputing.com",
    "myorg-myaccount.snowflakecomputing.com",
    "YOUR_ACCOUNT.snowflakecomputing.com",
    "https://your_org.thoughtspot.cloud",
    "https://$TS_HOST.thoughtspot.cloud/",
    "https://dbc-a1b2c3d4-e5f6.cloud.databricks.com",      # Databricks docs' example
    "https://adb-1234567890123456.7.azuredatabricks.net",  # Microsoft docs' example
    "https://developers.looker.com/api",
    "https://try-everywhere.thoughtspot.cloud",
    "https://training.thoughtspot.com/courses",
    "https://prod-apsoutheast-a.online.tableau.com",       # a shared Tableau Cloud pod
    "https://online.tableau.com/#/site/<site-name>/views",
    "https://online.tableau.com/#/site/{site}",
    "https://app.powerbi.com/groups/{workspace-id}/reports",
    "https://www.dropbox.com/s/<id>/file",
])
def test_vendor_placeholders_and_public_hosts_are_clean(text):
    assert _rules(text) == []


@pytest.mark.parametrize("text", [
    _j("https://yourcause.", "thoughtspot.cloud"),
    _j("https://examplebank.", "atlassian.net/browse/X-1"),
    _j("https://foxxxy.", "slack.com/archives/C1"),
    _j("https://acme-xxxcorp.", "thoughtspot.cloud"),
    _j("https://mytheresa.", "thoughtspot.cloud"),
])
def test_placeholder_words_match_whole_parts_only(text):
    assert len(_rules(text)) == 1


# ── round 3: every part must be a placeholder; GCP workspace ids ─────────────

@pytest.mark.parametrize("label", [
    "ORGNAME-ACMEPROD", "myorg-acmeprod", "acmecorp-myaccount", "contoso-example",
    "contoso_xy12345", "your_acme", "orgname-contoso", "x-corp", "contoso-123456", "your-contoso",
])
def test_one_placeholder_part_does_not_exempt_a_real_label(label):
    assert _rules(_j(f"https://{label}.", "snowflakecomputing.com")) == ["snowflake"]


@pytest.mark.parametrize("label", [
    "ORGNAME-ACCOUNTNAME", "myorg-myaccount", "xy12345", "your-workspace", "{x}", "<x>",
])
def test_all_placeholder_parts_stay_clean(label):
    assert _rules(f"https://{label}.snowflakecomputing.com") == []


@pytest.mark.parametrize("label", [
    "your-snowflake-account", "your-ts-instance", "your-thoughtspot-instance", "your-env",
    "your-subdomain", "your-qlik-tenant", "your-looker-instance", "example-snowflake-account",
    "example-customer", "example-corp",
])
def test_documentation_labels_with_vendor_and_generic_words_stay_quiet(label):
    """Round 4: generic and vendor words are WEAK tokens — quiet next to a strong part."""
    assert _rules(f"https://{label}.snowflakecomputing.com") == []
    assert _rules(f"https://{label}.thoughtspot.cloud") == []


def test_weak_tokens_alone_never_exempt():
    """`x` and `corp` are both weak: with no strong part, `x-corp` names a tenant."""
    assert _rules(_j("https://x-corp.", "snowflakecomputing.com")) == ["snowflake"]
    assert _rules(_j("https://acme-corp.", "thoughtspot.cloud")) == ["thoughtspot-cluster"]
    assert _rules(_j("https://snowflake-customer.", "atlassian.net/wiki/x")) == ["atlassian"]


@pytest.mark.parametrize("text", [
    _j("https://1234567890123456.7.", "gcp.databricks.com"),
    _j("https://8812734650912345.3.", "gcp.databricks.com/?o=1"),
])
def test_gcp_numeric_workspace_id_fires(text):
    assert _rules(text) == ["databricks"]


def test_email_address_is_not_a_cluster():
    assert _rules("contact support@thoughtspot.com for access") == []


# ── grandfathered entries: scoped, hashed, and never stale ───────────────────

def test_grandfathered_entries_are_live():
    """Each (path, ident_hash) must still match something in that file, or it is stale."""
    repo = VALIDATE.parents[1]
    for path, digest in ccr.GRANDFATHERED:
        text = (repo / path).read_text(encoding="utf-8")
        raw = [h.ident for h in ccr.scan_text(text, path, grandfathered=set())]
        assert digest in {ccr.ident_hash(i) for i in raw}, f"stale GRANDFATHERED entry: {path}"


def test_grandfathered_id_is_scoped_to_its_file(monkeypatch):
    path = "docs/notes.md"
    monkeypatch.setattr(ccr, "GRANDFATHERED", {(path, ccr.ident_hash(DOC_ID))})
    line = _j("https://docs.", f"google.com/document/d/{DOC_ID}/edit")
    assert _rules(line, path) == []
    assert _rules(line, "agents/cli/other.md") == ["google-doc"]


def test_validator_source_holds_no_exempted_identifier():
    """Exemptions are hashes: the validator must never republish what it exempts."""
    src = (VALIDATE / "check_customer_references.py").read_text()
    assert ccr.scan_text(src, "tools/validate/check_customer_references.py", grandfathered=set()) == []


# ── binary / UTF-16 ──────────────────────────────────────────────────────────

def test_binary_file_with_nul_byte_is_skipped(tmp_path):
    f = tmp_path / "blob.dat"
    f.write_bytes(b"\x00\x01\x02\x03\xff" + _j("https://acme-corp.", "atlassian.net/browse/X-1").encode())
    assert ccr.scan_file(f, tmp_path) == []


def test_binary_suffix_is_skipped(tmp_path):
    f = tmp_path / "workbook.xlsx"
    f.write_bytes(_j("https://acme-corp.", "atlassian.net/browse/X-1").encode())
    assert ccr.scan_file(f, tmp_path) == []


def test_utf16_with_bom_is_scanned(tmp_path):
    f = tmp_path / "export.csv"
    f.write_bytes(_j("link,https://acme-corp.", "atlassian.net/browse/X-1\n").encode("utf-16"))
    assert [h.rule for h in ccr.scan_file(f, tmp_path)] == ["atlassian"]


@pytest.mark.parametrize("enc", ["utf-16-le", "utf-16-be"])
def test_utf16_without_bom_is_scanned(tmp_path, enc):
    f = tmp_path / "export.txt"
    f.write_bytes(_j("see https://acme-corp.", "atlassian.net/browse/X-1\n").encode(enc))
    assert [h.rule for h in ccr.scan_file(f, tmp_path)] == ["atlassian"]


def test_same_content_as_text_file_fires(tmp_path):
    f = tmp_path / "notes.md"
    f.write_bytes(_j("https://acme-corp.", "atlassian.net/browse/X-1").encode())
    assert [h.rule for h in ccr.scan_file(f, tmp_path)] == ["atlassian"]


# ── finding 7: personal details WARN, never FAIL ─────────────────────────────

@pytest.mark.parametrize("text", [
    _j("/Users/", "jsmithx/Dev/repo"),
    _j("/home/", "jsmithx/work"),
    _j("/private/tmp/claude-501/-Users-", "jsmithx-Dev-repo/abc/scratchpad"),
    _j("owner: jane.smithx", "@acme-corp.com"),
])
def test_personal_detail_warns(text):
    assert _rules(text) == []
    assert len(_hits(text, level="WARN")) == 1


@pytest.mark.parametrize("text", [
    "/Users/username/.ssh", "/home/runner/work/x", "~/Dev/repo", "/home/<user>/x",
    "noreply@anthropic.com", "support@thoughtspot.com", "guest1@thoughtspot.com",
    "user@example.com", "jane.doe@example.com", "first.last@company.com",
])
def test_non_personal_detail_is_quiet(text):
    assert ccr.scan_text(text) == []


# ── the gate's exit code and modes ───────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q", "-b", "main"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_customer_references.py"), "--root", str(root), *extra],
        capture_output=True, text=True,
    )


LINK = _j("// https://acme-corp-my.", "sharepoint.com/personal/jane_doe/Documents/a.xlsx\n")


def test_gate_fails_on_staged_hit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "example.js").write_text(LINK)
    _git(["add", "-A"], tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "example.js:1" in result.stdout


def test_staged_link_removed_on_disk_still_blocks(tmp_path):
    """Finding 3: the INDEX is committed, not the working tree."""
    _init_repo(tmp_path)
    f = tmp_path / "example.js"
    f.write_text(LINK)
    _git(["add", "-A"], tmp_path)
    f.write_text("// clean now\n")                      # NOT re-staged
    assert _run(tmp_path).returncode == 1


def test_staged_then_deleted_on_disk_blocks(tmp_path):
    _init_repo(tmp_path)
    f = tmp_path / "example.js"
    f.write_text(LINK)
    _git(["add", "-A"], tmp_path)
    f.unlink()
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout


def test_git_mv_with_appended_link_blocks(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "old.md").write_text("".join(f"line {i} of a long enough file\n" for i in range(40)))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "base"], tmp_path)
    _git(["mv", "old.md", "new.md"], tmp_path)
    with (tmp_path / "new.md").open("a") as fh:
        fh.write(LINK)
    _git(["add", "new.md"], tmp_path)
    status = _git(["diff", "--cached", "--name-status"], tmp_path).stdout
    assert status.startswith("R"), status                # really a rename, not A+D
    result = _run(tmp_path)
    assert result.returncode == 1 and "new.md:41" in result.stdout


def test_type_change_symlink_to_file_blocks(tmp_path):
    """Item 3: a symlink replaced by a regular file is a TYPE change (T), not M."""
    _init_repo(tmp_path)
    (tmp_path / "target.md").write_text("target\n")
    (tmp_path / "notes.md").symlink_to("target.md")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "base"], tmp_path)
    (tmp_path / "notes.md").unlink()
    (tmp_path / "notes.md").write_text(LINK)
    _git(["add", "notes.md"], tmp_path)
    status = _git(["diff", "--cached", "--name-status"], tmp_path).stdout
    assert status.startswith("T"), status
    result = _run(tmp_path)
    assert result.returncode == 1 and "notes.md:1" in result.stdout


def test_gate_fails_on_tracked_hit_in_all_mode(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text(_j("https://acme-corp.", "thoughtspot.cloud\n"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    assert _run(tmp_path).returncode == 0          # nothing staged
    result = _run(tmp_path, "--all")
    assert result.returncode == 1
    assert "docs/notes.md:1" in result.stdout


def test_all_mode_scans_tracked_symlink_text(tmp_path):
    """Round 3 item 9: a tracked symlink is a blob holding its target text. A dangling one
    used to be dropped from --all (its target does not exist), so it was never scanned."""
    _init_repo(tmp_path)
    (tmp_path / "link.md").symlink_to(_j("../acme-corp.", "atlassian.net/wiki/x"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "--no-verify", "-m", "link"], tmp_path)
    result = _run(tmp_path, "--all")
    assert result.returncode == 1, result.stdout
    assert "link.md:1: [atlassian]" in result.stdout


def test_gate_passes_on_clean_tree(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("See https://docs.thoughtspot.com and https://{instance}.thoughtspot.cloud\n")
    _git(["add", "-A"], tmp_path)
    result = _run(tmp_path, "--all")
    assert result.returncode == 0, result.stdout


def test_warnings_never_fail_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _init_repo(tmp_path)
    (tmp_path / "notes.md").write_text(_j("path: /Users/", "jsmithx/Dev\n"))
    _git(["add", "-A"], tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "WARN" in result.stdout and "::warning" in result.stdout


def test_gate_fails_closed_outside_a_repo(tmp_path):
    result = _run(tmp_path, "--all")
    assert result.returncode == 1
    assert "could not read" in result.stdout


def _range_repo(root: Path) -> None:
    _init_repo(root)
    (root / "a.md").write_text(_j("old https://acme-corp.", "thoughtspot.cloud\n"))
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base"], root)
    _git(["checkout", "-q", "-b", "pr"], root)


def test_range_flags_added_lines_with_commit_and_line(tmp_path):
    _range_repo(tmp_path)
    (tmp_path / "b.md").write_text("one\n" + _j("https://acme-corp.", "atlassian.net/wiki/x\n"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "add b"], tmp_path)
    (tmp_path / "b.md").write_text("one\n")                          # removed again later
    _git(["commit", "-q", "-am", "clean b"], tmp_path)
    result = _run(tmp_path, "--range", "main..pr")
    assert result.returncode == 1                    # history still carries it
    assert "b.md:2: [atlassian]" in result.stdout
    assert "a.md" not in result.stdout               # base-branch content is out of range


def test_range_flags_commit_messages(tmp_path):
    _range_repo(tmp_path)
    (tmp_path / "c.md").write_text("clean\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", _j("fix per https://acme-corp.", "slack.com/archives/C1/p1")], tmp_path)
    result = _run(tmp_path, "--range", "main..pr")
    assert result.returncode == 1 and "message:1: [slack]" in result.stdout


def test_range_scans_content_lines_that_start_with_plus_plus(tmp_path):
    """Item 4: an added line whose content is `++ …` shows as `+++ …` in the diff;
    it is content, not a file header."""
    _range_repo(tmp_path)
    (tmp_path / "d.md").write_text("intro\n" + _j("++ https://acme-corp.", "atlassian.net/wiki/x\n"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "add d"], tmp_path)
    result = _run(tmp_path, "--range", "main..pr")
    assert result.returncode == 1 and "d.md:2: [atlassian]" in result.stdout


def test_message_file_mode(tmp_path):
    """What the commit-msg hook runs. EVERY line is scanned (a `#` line is part of an `-m`
    message); only the reference diff below the scissors line is not."""
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("subject\n\n" + _j("see https://acme-corp.", "atlassian.net/wiki/x\n")
                   + "# Please enter the commit message\n")
    result = _run(tmp_path, "--message-file", str(msg))
    assert result.returncode == 1 and "commit message:3: [atlassian]" in result.stdout

    msg.write_text(_j("#591 see https://acme-corp.", "atlassian.net/wiki/x\n"))
    assert _run(tmp_path, "--message-file", str(msg)).returncode == 1

    scissors = " ------------------------ >8 ------------------------\n"
    verbose_diff = "diff --git a/n.md b/n.md\n" + _j("-removed https://acme-corp.", "atlassian.net/wiki/y\n")
    # A real `-v` session (scissors, then git's diff) with the default comment char.
    msg.write_text("clean subject\n#" + scissors + verbose_diff)
    assert _run(tmp_path, "--message-file", str(msg)).returncode == 0

    # `;` is honoured only when core.commentChar says so.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    msg.write_text("clean subject\n;" + scissors + verbose_diff)
    assert _run(repo, "--message-file", str(msg)).returncode == 1
    _git(["config", "core.commentChar", ";"], repo)
    assert _run(repo, "--message-file", str(msg)).returncode == 0
    _git(["config", "core.commentChar", "auto"], repo)
    assert _run(repo, "--message-file", str(msg)).returncode == 0


def test_forged_scissors_line_does_not_hide_a_link(tmp_path):
    """Round 4 item 3: `git commit -m s -m "; ---- >8 ----" -m "<link>"` used to end the scan
    at the forged scissors line. A scissors line counts only with git's comment char AND a
    following `diff --git` line (what a `-v` session writes)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    msg = tmp_path / "COMMIT_EDITMSG"
    for char in ("#", ";"):
        msg.write_text("s\n\n" + char + " ------------------------ >8 ------------------------\n\n"
                       + _j("https://acme-corp.", "atlassian.net/wiki/x\n"))
        result = _run(repo, "--message-file", str(msg))
        assert result.returncode == 1 and "[atlassian]" in result.stdout, char
    _git(["config", "core.commentChar", ";"], repo)
    assert _run(repo, "--message-file", str(msg)).returncode == 1        # still no diff below


def test_range_grandfathering_needs_the_full_sha(tmp_path, monkeypatch):
    """Item 8: a 7-character prefix must NOT exempt a commit (prefixes can collide)."""
    _range_repo(tmp_path)
    (tmp_path / "e.md").write_text(_j("https://acme-corp.", "atlassian.net/wiki/x\n"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "add e"], tmp_path)
    sha = _git(["rev-parse", "HEAD"], tmp_path).stdout.strip()
    digest = ccr.ident_hash(_j("acme-corp.", "atlassian.net"))
    monkeypatch.setattr(ccr, "RANGE_GRANDFATHERED", {(sha[:7], digest)})
    assert ccr.scan_range(tmp_path, "main..pr") != []
    monkeypatch.setattr(ccr, "RANGE_GRANDFATHERED", {(sha, digest)})
    assert ccr.scan_range(tmp_path, "main..pr") == []


def test_range_survives_a_nul_byte_in_a_later_commit(tmp_path):
    """Round-3 item 1 (the reviewer's repro): a text file with a NUL after 8000 bytes used
    to shift the NUL-framed `git log -p` parse so every older commit went unscanned."""
    _range_repo(tmp_path)
    (tmp_path / "a1.md").write_text("one\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", _j("A: see https://acme-corp.", "slack.com/archives/C1/p1")], tmp_path)
    (tmp_path / "b.md").write_text(_j("https://acme-corp.", "atlassian.net/wiki/x\n"))
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "B adds"], tmp_path)
    (tmp_path / "b.md").write_text("gone\n")
    _git(["commit", "-q", "-am", "B removes"], tmp_path)
    (tmp_path / "c.txt").write_bytes(b"x" * 9000 + b"\0\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "C"], tmp_path)
    result = _run(tmp_path, "--range", "main..pr")
    assert result.returncode == 1, result.stdout
    assert "message:1: [slack]" in result.stdout
    assert "b.md:1: [atlassian]" in result.stdout


def test_range_fails_closed_on_unparseable_commit_list(tmp_path, monkeypatch):
    _range_repo(tmp_path)
    monkeypatch.setattr(ccr, "git_bytes", lambda args, root: b"not-a-sha\n")
    with pytest.raises(ccr.GitEnumerationError):
        ccr.scan_range(tmp_path, "main..pr")


def test_range_ignores_removed_lines(tmp_path):
    _range_repo(tmp_path)
    (tmp_path / "a.md").write_text("old placeholder\n")
    _git(["commit", "-q", "-am", "remove link"], tmp_path)
    assert _run(tmp_path, "--range", "main..pr").returncode == 0


def test_range_pr_commits_are_clean():
    """This branch's own history passes, given its scoped RANGE_GRANDFATHERED entries."""
    repo = VALIDATE.parents[1]
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=repo,
                          capture_output=True, text=True)
    if base.returncode != 0:
        pytest.skip("no origin/main to compare against")
    assert ccr.scan_range(repo, f"{base.stdout.strip()}..HEAD") == [] or all(
        h.level == "WARN" for _, h in ccr.scan_range(repo, f"{base.stdout.strip()}..HEAD"))


# ── finding 6: opt-in private customer-name denylist ─────────────────────────
# Fake names only.

FAKE_NAMES = "\ufeff# private list\n\nAcme Corp\nFakeco Industries\nQwk\nzz\n"


def _deny(text: str = FAKE_NAMES):
    return ccr.compile_denylist(text.lstrip("\ufeff").splitlines())


def test_denylist_ignores_comments_blanks_and_short_entries():
    dl = _deny()
    assert [n for _, n in dl.substrings] == [3, 4] and [n for _, n in dl.words] == [5]


@pytest.mark.parametrize("text", [
    "Built for ACME   corp last year.", "table ACME_CORP_SALES", "AcmeCorp dashboard",
    "acmecorp", "Acme-Corp", "acme.corp",
])
def test_denylist_normalised_forms_all_match(text):
    hits = _deny().hits(1, text)
    assert [h.match for h in hits] == ["<denylist entry #3>"]   # entry number, never the name


def test_short_entry_matches_only_as_a_whole_word():
    dl = _deny()
    assert [h.match for h in dl.hits(1, "the Qwk team")] == ["<denylist entry #5>"]
    assert dl.hits(1, "Qwkly and xqwk") == []


def test_no_denylist_file_is_a_silent_skip(capsys):
    assert ccr.load_denylist() is None
    assert capsys.readouterr().out == ""


def test_denylist_file_with_utf8_bom_loads(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_bytes("Acme Corp\n".encode("utf-8-sig"))
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(deny))
    dl = ccr.load_denylist()
    assert dl is not None and dl.hits(1, "acme corp") != []


def test_default_path_under_home_is_used():
    cfg = Path(os.environ["HOME"]) / ".config" / "thoughtspot-agent-skills"
    cfg.mkdir(parents=True)
    (cfg / "customer-denylist.txt").write_text(FAKE_NAMES)
    assert ccr.load_denylist() is not None


def test_gate_fails_on_denylisted_name_without_printing_it(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text(FAKE_NAMES, encoding="utf-8")
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(deny))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "notes.md").write_text("Ran the probe for FakecoIndustries.\n")
    _git(["add", "-A"], repo)
    result = _run(repo)
    assert result.returncode == 1
    assert "notes.md:1: [customer-name] <denylist entry #4>" in result.stdout
    assert "fakeco" not in result.stdout.lower()


def test_denylisted_path_is_redacted_in_output(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text(FAKE_NAMES, encoding="utf-8")
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(deny))
    repo = tmp_path / "repo"
    (repo / "examples" / "fakeco_industries").mkdir(parents=True)
    _init_repo(repo)
    (repo / "examples" / "fakeco_industries" / "notes.md").write_text(
        _j("https://acme-corp.", "atlassian.net/wiki/x\n"))
    _git(["add", "-A"], repo)
    result = _run(repo)
    assert result.returncode == 1
    assert "<path redacted: denylist entry #4>" in result.stdout
    assert "fakeco" not in result.stdout.lower()


GLOBEX_LINES = (
    # a host hit whose own text carries the name
    _j("ref https://globex-industrial.", "atlassian.net/wiki/spaces/X\n")
    # WARN lines carrying the name
    + _j("owner globex.industrial", "@acme-corp.com\n")
    + _j("path /Users/", "globexindustrial/Dev/x\n")
    + "plain mention of GLOBEX_INDUSTRIAL\n"
)


def _globex_repo(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text("Globex Industrial\n", encoding="utf-8")
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(deny))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")         # WARN annotations printed too
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "base.md").write_text("base\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "base"], repo)
    _git(["checkout", "-q", "-b", "pr"], repo)
    (repo / "notes.md").write_text(GLOBEX_LINES)
    _git(["add", "-A"], repo)
    return repo


def _assert_redacted(result):
    out = result.stdout.lower()
    assert result.returncode == 1, result.stdout
    assert "<denylist entry #1>" in out
    assert "globex" not in out, result.stdout
    assert "warn" in out                                   # the WARN lines were printed, redacted


def test_name_redacted_in_staged_output(tmp_path, monkeypatch):
    repo = _globex_repo(tmp_path, monkeypatch)
    _assert_redacted(_run(repo))


def test_name_redacted_in_all_output(tmp_path, monkeypatch):
    repo = _globex_repo(tmp_path, monkeypatch)
    _git(["commit", "-q", "-m", "notes"], repo)
    _assert_redacted(_run(repo, "--all"))


def test_name_redacted_in_range_output_and_commit_message(tmp_path, monkeypatch):
    repo = _globex_repo(tmp_path, monkeypatch)
    _git(["commit", "-q", "-m", _j("notes for Globex Industrial, see https://acme-corp.", "slack.com/archives/C1")], repo)
    result = _run(repo, "--range", "main..pr")
    _assert_redacted(result)
    assert "message:1" in result.stdout


def test_repeated_name_in_a_long_url_path_is_never_cut_before_redaction(tmp_path, monkeypatch):
    """Round 3 item 8: a hit's text used to be cut to 200 characters when it was CREATED,
    before redaction — so a name straddling the cut survived as a fragment."""
    seg = "globexindustrial/"
    prefix = _j("https://acme-corp.", "atlassian.net/wiki/")
    host_start = len("https://")
    pad = "p" * ((200 - (len(prefix) - host_start) - 10) % len(seg))   # old cut lands 10 chars in
    line = prefix + pad + "/" + seg * 12 + "\n"
    deny = tmp_path / "deny.txt"
    deny.write_text("Globex Industrial\n", encoding="utf-8")
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(deny))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "notes.md").write_text(line)
    _git(["add", "-A"], repo)
    result = _run(repo)
    assert result.returncode == 1
    assert "globex" not in result.stdout.lower(), result.stdout
    # The invariant itself: a hit's stored text is never pre-cut, so redacting it leaves no
    # fragment of the name (the old code cut it to 200 chars, mid-name, before redaction).
    dl = ccr.load_denylist()
    for hit in ccr.scan_text(line, "notes.md"):
        assert "globex" not in dl.redact(hit.match).lower(), hit.match[-30:]


def test_redact_before_truncation():
    dl = _deny("Globex Industrial\n")
    hit = ccr.Hit(1, "atlassian", "x" * 95 + "globexindustrial" + "y" * 20, "advice")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ccr._emit("f.md:1", hit, dl)
    assert "globex" not in buf.getvalue().lower()


def test_gate_with_missing_explicit_denylist_notes_and_passes(tmp_path, monkeypatch):
    monkeypatch.setenv(ccr.DENYLIST_ENV, str(tmp_path / "missing.txt"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "README.md").write_text("hello\n")
    _git(["add", "-A"], repo)
    result = _run(repo)
    assert result.returncode == 0
    assert "NOTE" in result.stdout
