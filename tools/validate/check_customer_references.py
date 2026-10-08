#!/usr/bin/env python3
"""
check_customer_references.py — fail on links into a customer's (or any tenant's) internal systems.

This repo is public. A link into a tenant's own systems — a Jira ticket, a personal
OneDrive path, a Slack thread, a Google Doc, a warehouse account, a ThoughtSpot cluster —
names the customer, often names an employee, and points at material that was never meant
to leave that tenant. Nothing caught one when a PR added an example file carrying a
customer's internal links, so this gate exists to catch the next.

What it FAILS on (case-insensitive, in any text file anywhere in the tree):

  - Microsoft 365: any `<tenant>.sharepoint.{com,us,cn}` host (covers personal OneDrive,
    `<tenant>-my.sharepoint.com`, and every site path), consumer OneDrive share links
    (the `1drv` short-link domain and the `onedrive.live` site), and Teams deep links.
  - Atlassian: any `<tenant>.atlassian.net` host. ThoughtSpot's own tenant is allowed
    ONLY as a bare host or a `/browse/<KEY>-<n>` ticket link; its wiki and every other
    path still fail.
  - Slack: any path under `<workspace>.slack.com/` (archives, files, team, client,
    webhooks...), except the bare workspace root and the public hosts allowlisted below.
  - Google Workspace: Docs/Sheets/Slides/Forms documents, domain-scoped `/a/<domain>/`
    links, Drive files/folders/`open?id=`/`uc?id=`, and Forms short links.
  - Warehouse / BI tenants: Snowflake accounts (`<acct>.snowflakecomputing.com`, and the
    org/account path on the `app` web host), Databricks workspaces (AWS, Azure, GCP and
    GovCloud hosts), Tableau Cloud/Server site URLs (`#/site/<name>`), Power BI workspace
    links, Qlik Cloud, Looker, and Salesforce orgs.
  - File sharing and meetings: Box enterprise hosts and shared links, Dropbox shared links,
    Zoom meeting/recording links, Gong call recordings.
  - ThoughtSpot clusters: any `<name>.thoughtspot.cloud` (and the staging/dev `.cloud`
    domains, `.thoughtspot.com`, `.thoughtspot.app`) not in ALLOWED_HOSTS.
  - Opt-in: names on a private customer denylist (see "Private name list" below).

Every line is HTML-entity- and percent-decoded (up to two rounds) before matching, so a
link wrapped by a safe-links or redirect service (`?url=https%3A%2F%2F...`) still fails.

What it WARNS on (printed, never fails; a CI annotation under GitHub Actions):

  - home-directory paths that name a user (`/Users/<name>/`, `/home/<name>/`, and the
    dash-encoded form scratch directories use);
  - personal-looking email addresses (`first.last@company`). Role addresses such as
    `noreply@` or `support@` are not personal and are not reported.

What it does NOT flag:

  - Placeholders. A host is documentation when every label left of the service domain
    is either a placeholder or a neutral label (a region/environment word or a number),
    and at least one is a placeholder. A placeholder label is a WHOLE template token
    (`{x}`, `${x}`, `$X`, `<x>`, `[x]`, `%x%`, `*`), a single character, a placeholder word
    (`acme`, `test`, `my`/`myorg`/`your-…`, ...), or contains a placeholder word or filler
    as a WHOLE hyphen/underscore part (`example-tenant`, `ORGNAME-ACCOUNTNAME`,
    `dbc-xxxxx`). Never a prefix or substring: `examplebank` and `yourcause` fail. Markup around a host is never part of a label, so
    a real host wrapped in `**bold**`, `[brackets]` or a `<td>` cell still fails.
  - Hosts on ALLOWED_HOSTS / ALLOWED_ATLASSIAN_TENANTS, and (path, identifier) pairs on
    GRANDFATHERED. Every entry carries a one-line justification; adding one is a reviewed
    change to this file (CODEOWNERS), never an inline marker in the flagged file.
  - Binary files (known binary suffixes, or NUL bytes that are not UTF-16 text).

Modes:

  --root .                staged files — the STAGED CONTENT (index), including renames;
                          what the pre-commit hook runs
  --root . --all          every tracked file on disk (CI)
  --root . --range A..B   every commit in A..B: added lines and the commit message (CI, PRs).
                          Needs no secrets, so it also runs on fork PRs.
  --message-file PATH     one commit message; what the commit-msg hook runs

Private name list (opt-in). The patterns above recognise LINKS; they cannot tell that a
bare word is a customer's name. A maintainer can supply names that live OUTSIDE this repo:

  - path: $TS_CUSTOMER_DENYLIST, else ~/.config/thoughtspot-agent-skills/customer-denylist.txt
  - format: one name per line, UTF-8 (a BOM is fine); blank lines and `#` comments ignored
  - matching: both sides are normalised (lowercase, non-alphanumerics removed), so
    "Acme Corp" also matches `ACME_CORP`, `AcmeCorp` and `acmecorp`. Names that normalise
    to 5+ characters match as substrings; shorter ones (3-4) only as whole words; shorter
    still are ignored. File CONTENTS, PATHS and commit messages are all checked.
  - no file → skipped silently. An explicitly set $TS_CUSTOMER_DENYLIST that names a missing
    file prints a one-line note (a likely misconfiguration), but does not fail.
  - a hit prints the denylist ENTRY NUMBER, never the name, and a path that contains a
    name is printed as `<path redacted: denylist entry #N>`: CI logs on a public repo are
    public.

To use it in CI, store the list as a repository secret and write it to a file in a step
before the validators run, e.g.
    printf '%s\\n' "$CUSTOMER_DENYLIST" > "$RUNNER_TEMP/denylist.txt"
    echo "TS_CUSTOMER_DENYLIST=$RUNNER_TEMP/denylist.txt" >> "$GITHUB_ENV"
with `env: CUSTOMER_DENYLIST: ${{ secrets.CUSTOMER_DENYLIST }}`. Secrets are not exposed
to workflows triggered from forks, so on a fork PR the name check is skipped.
validate.yml deliberately does not reference the secret until one exists.

Why a separate validator rather than a rule in check_secrets.py: check_secrets looks for
*credentials* and exempts lines by value-shape heuristics tuned for secrets. A tenant link
is not a credential, needs host-level allowlists rather than value placeholders, and its
fix is different (replace with a placeholder, not rotate a key).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import unquote

from _git import (GitEnumerationError, git_bytes, git_config_get, staged_blob,
                  staged_relpaths, tracked_relpaths)


# ---------------------------------------------------------------------------
# Allowlists — every entry needs a one-line justification.
# ---------------------------------------------------------------------------

ALLOWED_ATLASSIAN_TENANTS = {
    # ThoughtSpot's own Jira — SCAL product-bug tickets cited by the AgentQL skill.
    # Scoped: only the bare host and /browse/<KEY>-<n> ticket links are allowed.
    "thoughtspot",
}

ALLOWED_HOSTS = {
    # Public ThoughtSpot web properties.
    "docs.thoughtspot.com",            # public product documentation
    "developers.thoughtspot.com",      # public developer documentation (not cited today; public)
    "community.thoughtspot.com",       # public community knowledge base
    "www.thoughtspot.com",             # public marketing site (not cited today; public)
    "spottercode.thoughtspot.app",     # public SpotterCode MCP endpoint wired in .mcp.json
    # Internal ThoughtSpot clusters are deliberately NOT listed: name them in prose
    # ("the SE demo cluster") or by profile, never by hostname, in a public repo.
    "try-everywhere.thoughtspot.cloud",  # public ThoughtSpot free-trial cluster
    "training.thoughtspot.com",        # public ThoughtSpot training site
    # Public vendor hosts that share a tenant-shaped domain.
    "accounts.cloud.databricks.com",   # Databricks account console login, same for every customer
    "accounts.gcp.databricks.com",     # the same console on GCP
    "accounts.cloud.databricks.us",    # the same console on GovCloud
    "api.slack.com",                   # Slack's public API documentation
    "docs.looker.com",                 # Looker's public documentation
    "developers.looker.com",           # Looker's public developer documentation
    # Vendor-DOCUMENTED example ids, exactly as the vendor's docs print them. Any other id
    # of the same shape still fails (_REAL_ID_SHAPES).
    "dbc-a1b2c3d4-e5f6.cloud.databricks.com",       # Databricks docs' example workspace
    "adb-1234567890123456.7.azuredatabricks.net",   # Microsoft docs' example workspace
}

# Exact (path, identifier) pairs that predate this gate and await an OWNER DECISION.
# The identifier is stored as `ident_hash()` — a truncated sha256 of the matched host
# (lowercase) or Google document id — so this file never republishes what it exempts.
# Scoped to one file AND one identifier: a NEW occurrence anywhere else still fails. A
# stale entry (identifier no longer in that file) fails the test suite.
# Empty: the last entries (the repo's own Databricks test-workspace host) were replaced
# with placeholders in the tree, with the owner's approval. The real host is kept in a
# local stash for deploys; `_REAL_ID_SHAPES` makes sure it fails if it comes back.
GRANDFATHERED: set[tuple[str, str]] = set()

# --range only: (FULL commit sha, ident_hash) pairs for history that is already public
# and cannot change without rewriting a pushed branch. Empty: the branch that introduced
# this gate was squashed, so its interim history never reaches main. Keep the mechanism for
# the day a pushed commit cannot be rewritten.
RANGE_GRANDFATHERED: set[tuple[str, str]] = set()


def ident_hash(ident: str) -> str:
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:16]



# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------

# A WHOLE label that is template syntax. Nothing may surround the token: markup such as
# `**`, `<td>` or `[` next to a real host must never turn it into a "template".
_TOKEN = (r"(?:\$\{[^{}\s/.]+\}|\{[^{}\s/.]+\}|<[^<>\s/.]+>|\[[^\[\]\s/.]+\]|%[^%\s/.]+%|\*"
          r"|\$[A-Za-z_][A-Za-z0-9_]*)")
_TOKEN_RE = re.compile(rf"^{_TOKEN}$")


def _is_token_label(label: str) -> bool:
    """A whole template token, optionally with OneDrive's `-my` suffix (`{tenant}-my`)."""
    if label.lower().endswith("-my"):
        label = label[: -len("-my")]
    return bool(_TOKEN_RE.match(label))

# Words that mark a WHOLE label as documentation.
WHOLE_LABEL_WORDS = {
    "test", "demo", "sample", "placeholder", "instance", "cluster", "tenant",
    "host", "hostname", "company", "org", "workspace", "domain", "new",
    "acme",        # the classic fictitious company (`acme-corp` is NOT this word, and fires)
    "dbx",         # generic Databricks abbreviation used in test fixtures
    "username", "user", "account", "orgname", "accountname",
}

# Tokens a hyphen/underscore label may be BUILT FROM and still be documentation. Every part
# must be a STRONG or WEAK token (or neutral), and at least one part must be STRONG:
#   STRONG — unmistakably a placeholder: `your`, `example`, the enumerated `my…`/`your…`
#            forms, documented filler (`xy12345`, `abc123`, `xx…`).
#   WEAK   — generic or vendor words that are only documentation NEXT TO a strong part:
#            `your-snowflake-account`, `example-corp` are quiet, but `x-corp`, `acme-corp`
#            (no strong part) and `contoso-example`, `your-contoso` (a real part) still fail.
# Never a prefix or substring: `examplebank`, `yourcause` fail.
STRONG_PART_TOKENS = {
    "example", "examples", "placeholder", "your", "my", "orgname", "accountname",
    "xy12345",                       # Snowflake's documented account locator
    "abc123", "def456", "123456", "1234567890",
}
WEAK_PART_TOKENS = {
    "sample", "test", "demo", "new", "account", "identifier", "locator", "region", "name", "id",
    "org", "company", "corp", "customer", "workspace", "instance", "cluster", "tenant", "host",
    "hostname", "domain", "subdomain", "site", "team", "server", "user", "username", "env",
    "snowflake", "ts", "thoughtspot", "qlik", "looker", "tableau", "databricks", "salesforce",
    "slack", "atlassian", "jira", "sharepoint", "box", "dbc", "adb", "x",
}
_FILLER_PART_RE = re.compile(r"^x{2,}$", re.IGNORECASE)         # xx, xxxxx (a lone `x` is weak)

# `my`/`your` forms are ENUMERATED (as a whole label, or as a part), so a real tenant
# like `mytheresa` or `yourcause` still fires.
_MY_YOUR_RE = re.compile(
    r"^(?:my|your)(?:[-_]?(?:co|company|org|instance|cluster|tenant|host|domain|site|team"
    r"|workspace|server|account))?(?:[-_](?:staging|dev|test|prod))?$",
    re.IGNORECASE,
)

# Labels that carry no tenant identity on their own: regions, clouds, environments, short
# numbers. A LONG number is not neutral: it is a generated id (_REAL_ID_SHAPES).
_NEUTRAL_LABELS = {
    "us", "eu", "ap", "uk", "au", "ca", "jp", "sg", "in", "de", "fr", "ch", "br",
    "east", "west", "north", "south", "central", "aws", "gcp", "azure", "cloud",
    "prod", "dev", "staging", "stage", "qa", "uat", "sandbox", "se", "privatelink",
}
_REGION_RE = re.compile(r"^[a-z]{2,}(?:-[a-z]+)+-\d+$", re.IGNORECASE)   # us-east-1


# Generated tenant ids — a Databricks AWS workspace (`dbc-<8 hex>-<4 hex>`), Azure workspace
# (`adb-<15-16 digits>`) or GCP workspace (an all-numeric id, `<16 digits>.<n>.gcp…`). Random
# ids can contain a filler pattern by chance; a label of a real id's shape is never a
# placeholder, and a tenant containing one is never a placeholder either.
_REAL_ID_SHAPES = re.compile(r"^(?:dbc-[0-9a-f]{8}-[0-9a-f]{4}|adb-\d{15,16}|\d{10,})$", re.IGNORECASE)


def _is_strong_part(part: str) -> bool:
    return part in STRONG_PART_TOKENS or bool(_FILLER_PART_RE.match(part) or _MY_YOUR_RE.match(part))


def _is_placeholder_part(part: str) -> bool:
    return _is_strong_part(part) or part in WEAK_PART_TOKENS


def is_placeholder_label(label: str) -> bool:
    """True if ONE label (no dots) is documentation rather than a tenant name."""
    if _REAL_ID_SHAPES.match(label):
        return False
    if _is_token_label(label):
        return True
    if label.lower().endswith("-my"):             # OneDrive personal host: `<tenant>-my`
        label = label[: -len("-my")]
    if any(ch in "{}<>[]$*%" for ch in label):    # markup glued to a real label
        return False
    low = label.lower()
    if len(low) <= 1 or low in WHOLE_LABEL_WORDS or _MY_YOUR_RE.match(low):
        return True
    parts = [p for p in re.split(r"[-_]", low) if p]
    if not all(_is_placeholder_part(p) or _is_neutral_label(p) for p in parts):
        return False
    return any(_is_strong_part(p) for p in parts)


def _is_neutral_label(label: str) -> bool:
    low = label.lower()
    return ((low.isdigit() and len(low) <= 3) or low in _NEUTRAL_LABELS
            or bool(_REGION_RE.match(low)))


def is_placeholder_tenant(tenant: str) -> bool:
    """True if the variable part of a host is documentation, not a real tenant.

    Every label must be a placeholder or neutral, and at least one a placeholder:
    `se.example` and `acme.us` are placeholders; `{env}.acme-corp` and `a.acme-corp`
    still name `acme-corp`, so they are not. A label shaped like a generated workspace id
    makes the whole tenant real (`1234567890123456.7` is not saved by its `7`).
    """
    labels = tenant.split(".")
    if any(_REAL_ID_SHAPES.match(l) for l in labels):
        return False
    if not all(is_placeholder_label(l) or _is_neutral_label(l) for l in labels):
        return False
    return any(is_placeholder_label(l) for l in labels)


# A Google document id is a long mixed-case base64url string. A placeholder id is
# words in one case joined by `_`/`-` (`YOUR_DOC_ID`, `document-id-here`).
_PLACEHOLDER_ID_RE = re.compile(r"^(?:[A-Z]+|[a-z]+)(?:[_-](?:[A-Z]+|[a-z]+))*$")


def is_placeholder_id(doc_id: str) -> bool:
    return bool(_PLACEHOLDER_ID_RE.match(doc_id))


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
#
# LINEAR TIME BY CONSTRUCTION. An earlier version matched hosts with one regex,
# `(char | template-token)+` preceded by a look-behind, which backtracks quadratically
# on input such as `a*a*a*…` (60s+ on a 50K-character line). Every regex below is now
# anchored on a LITERAL (a service domain, or a fixed URL prefix) followed only by plain
# character classes. A host's tenant part is then collected by a bounded backward walk
# over host characters, and classified in Python.

# Characters a host's tenant part may contain, template syntax included, so that
# `{your-instance}` is collected whole and `**acme-corp` is collected WITH its markup
# (which `is_placeholder_label` then refuses to treat as a template).
_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                        "_-.{}<>[]$%*")
_MAX_TENANT = 260          # longer than any DNS name; bounds the backward walk
_SEG = r"[^/\s#?&\"'`)\]<>|]{1,200}"    # one URL path segment (bounded)
_GOOGLE_ID = r"(?P<id>[A-Za-z0-9_-]{10,200})"
# BOUNDED: an unbounded path capture ran from every host match to the end of the line
# (quadratic: 106s on a 1M-character line of `x.slack.com/`).
_PATH_RE = re.compile(r"/[^\s)\]>\"'`|]{0,300}")


_LEAD_MARKUP = re.compile(r"^(?:<[^<>]{0,40}>|[*\[{(<$%])+")
_TRAIL_MARKUP = re.compile(r"(?:[*\]})>%])+$")


def _tenant_before(line: str, dot: int) -> str:
    """The tenant part ending just before ``line[dot]`` (the dot before the domain).

    Each label is either kept whole (a complete template token such as `{instance}`) or
    has surrounding markup stripped — `**acme-corp`, `[acme-corp`, `<td>acme-corp` all
    become `acme-corp` — so markup can neither hide a real host nor break the allowlist
    match for a public one written as a markdown link.
    """
    j, stop = dot, max(0, dot - _MAX_TENANT)
    while j > stop and line[j - 1] in _HOST_CHARS:
        j -= 1
    labels = []
    for label in line[j:dot].split("."):
        if not _is_token_label(label):
            label = _TRAIL_MARKUP.sub("", _LEAD_MARKUP.sub("", label))
        if label:
            labels.append(label)
    return ".".join(labels)


@dataclass(frozen=True)
class HostRule:
    """`<tenant>.<domain>`: the domain regex starts at the dot before the domain."""
    name: str
    domain: re.Pattern
    advice: str
    # Optional check on the text right after the domain (e.g. Slack needs a path).
    after: Optional[re.Pattern] = None


@dataclass(frozen=True)
class Rule:
    """A literal-anchored pattern; ``exempt`` gets the match."""
    name: str
    regex: re.Pattern
    exempt: Optional[Callable[[re.Match], bool]]
    advice: str


_TICKET_PATH = re.compile(r"^/browse/[A-Z][A-Z0-9_]*-\d+(?:[?#].*)?$")


def _host_exempt(rule: HostRule, tenant: str, host: str, path: str) -> bool:
    if host in ALLOWED_HOSTS or is_placeholder_tenant(tenant):
        return True
    if rule.name == "atlassian" and tenant.lower() in ALLOWED_ATLASSIAN_TENANTS:
        return path in ("", "/") or bool(_TICKET_PATH.match(path))
    return False


def _google_exempt(m: re.Match) -> bool:
    return is_placeholder_id(m.group("id"))


def _segment_exempt(m: re.Match) -> bool:
    return is_placeholder_tenant(m.group("tenant"))


_REPLACE = "Replace it with a placeholder such as `<tenant>`."
_REMOVE = "Remove it."


def _host_rule(name: str, domain_re: str, advice: str, after: Optional[str] = None) -> HostRule:
    return HostRule(name, re.compile(rf"\.(?P<domain>{domain_re})\b", re.IGNORECASE), advice,
                    re.compile(after) if after else None)


HOST_RULES: tuple[HostRule, ...] = (
    _host_rule("sharepoint/onedrive", r"sharepoint\.(?:com|us|cn)",
               f"A SharePoint / personal OneDrive link into a tenant. {_REPLACE}"),
    _host_rule("atlassian", r"atlassian\.net",
               f"A Jira/Confluence link outside the allowed tenant tickets. {_REPLACE}"),
    _host_rule("slack", r"slack\.com", f"A link into a Slack workspace. {_REMOVE}",
               after=r"/[^\s)\]>\"'`|]"),
    _host_rule("snowflake", r"snowflakecomputing\.com", f"A Snowflake account host. {_REPLACE}"),
    _host_rule("databricks",
               r"cloud\.databricks\.com|gcp\.databricks\.com|cloud\.databricks\.us|azuredatabricks\.net",
               f"A Databricks workspace host. {_REPLACE}"),
    _host_rule("box", r"app\.box\.com", f"A Box enterprise host. {_REPLACE}"),
    _host_rule("qlik", r"qlikcloud\.com", f"A Qlik Cloud tenant host. {_REPLACE}"),
    _host_rule("looker", r"looker\.com", f"A Looker instance host. {_REPLACE}"),
    _host_rule("salesforce", r"my\.salesforce\.com|lightning\.force\.com",
               f"A Salesforce org host. {_REPLACE}"),
    _host_rule("thoughtspot-cluster",
               r"thoughtspot(?:staging|dev)?\.cloud|thoughtspot\.com|thoughtspot\.app",
               f"A ThoughtSpot host not on ALLOWED_HOSTS — likely a customer cluster. {_REPLACE}"),
)

RULES: tuple[Rule, ...] = (
    Rule("onedrive-consumer", re.compile(r"(?:\b1drv\.ms/|\bonedrive\.live\.com\b)", re.IGNORECASE),
         None, f"A OneDrive share link. {_REMOVE}"),
    Rule("teams", re.compile(r"\bteams\.microsoft\.com/l/", re.IGNORECASE),
         None, f"A Microsoft Teams deep link into a tenant. {_REMOVE}"),
    Rule("google-doc",
         re.compile(rf"\bdocs\.google\.com/(?:document|spreadsheets|presentation|forms|file)"
                    rf"/(?:u/\d+/)?d/(?:e/)?{_GOOGLE_ID}", re.IGNORECASE),
         _google_exempt, f"A Google Docs/Sheets/Slides/Forms link. {_REMOVE}"),
    Rule("google-doc",
         re.compile(rf"\bdocs\.google\.com/a/(?P<tenant>{_SEG})/", re.IGNORECASE),
         _segment_exempt, f"A Google Workspace link scoped to a customer's domain. {_REMOVE}"),
    Rule("google-drive",
         re.compile(rf"\bdrive\.google\.com/(?:file/(?:u/\d+/)?d/|drive/(?:u/\d+/)?folders/"
                    rf"|open\?id=|uc\?(?:[^\s&]{{0,200}}&){{0,20}}?id=){_GOOGLE_ID}", re.IGNORECASE),
         _google_exempt, f"A Google Drive link. {_REMOVE}"),
    Rule("google-forms", re.compile(r"\bforms\.gle/[A-Za-z0-9_-]{1,100}", re.IGNORECASE),
         None, f"A Google Forms short link. {_REMOVE}"),
    Rule("snowflake",
         re.compile(rf"\bapp\.snowflake\.com/(?P<tenant>{_SEG})/", re.IGNORECASE),
         _segment_exempt, f"A Snowflake web-UI link naming an org/account. {_REPLACE}"),
    Rule("tableau-site",
         re.compile(rf"#/site/(?P<tenant>{_SEG})", re.IGNORECASE),
         _segment_exempt, f"A Tableau Cloud/Server site URL. {_REPLACE}"),
    Rule("power-bi",
         re.compile(rf"\bapp\.powerbi\.com/groups/(?P<tenant>{_SEG})", re.IGNORECASE),
         _segment_exempt, f"A Power BI workspace link. {_REMOVE}"),
    Rule("box", re.compile(r"\bapp\.box\.com/s/[A-Za-z0-9]", re.IGNORECASE),
         None, f"A Box shared link. {_REMOVE}"),
    Rule("dropbox", re.compile(r"\bdropbox\.com/(?:s|scl)/[A-Za-z0-9]", re.IGNORECASE),
         None, f"A Dropbox shared link. {_REMOVE}"),
    Rule("zoom", re.compile(r"\bzoom\.us/(?:j|rec)/", re.IGNORECASE),
         None, f"A Zoom meeting or recording link. {_REMOVE}"),
    Rule("gong", re.compile(r"\bapp\.gong\.io/call", re.IGNORECASE),
         None, f"A Gong call recording link. {_REMOVE}"),
)

# Cheap pre-filter: a line that contains none of these cannot match any rule.
_TRIGGERS = ("sharepoint", "1drv", "onedrive", "teams.microsoft", "atlassian", "slack",
             "google", "forms.gle", "snowflake", "databricks", "qlikcloud", "looker",
             "salesforce", "force.com", "thoughtspot", "#/site/", "powerbi", "box.com",
             "dropbox", "zoom.us", "gong.io")


# ---------------------------------------------------------------------------
# Personal details — WARN only
# ---------------------------------------------------------------------------

_HOME_RE = re.compile(r"(?:/(?:Users|home)/|[-/](?:Users|home)-)(?P<name>[A-Za-z0-9._]{1,64})[/-]")
_HOME_PLACEHOLDERS = {"username", "user", "you", "me", "runner", "ubuntu", "name", "example",
                      "shared", "guest", "admin", "root", "your", "someone", "jdoe"}
# One character class per side, anchored by `@`, so matching stays linear; the TLD shape
# is checked in Python.
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])(?P<local>[A-Za-z0-9._%+-]{1,64})@(?P<domain>[A-Za-z0-9.-]{1,253})")
_TLD_RE = re.compile(r"\.[A-Za-z]{2,}$")
# `first.last` / `first_last` — the shape of a personal corporate address. Role and
# synthetic addresses (`noreply`, `support`, `guest1`) do not have it.
_PERSONAL_LOCAL_RE = re.compile(r"^[A-Za-z]{2,}[._][A-Za-z]{2,}$")
_SAFE_EMAIL_DOMAINS = re.compile(r"(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost)$",
                                 re.IGNORECASE)
_SAFE_LOCALS = {"jane.doe", "john.doe", "first.last", "firstname.lastname", "example.user"}


def _personal_hits(line_num: int, line: str) -> list["Hit"]:
    hits = []
    for m in _HOME_RE.finditer(line):
        name = m.group("name")
        if name.lower() not in _HOME_PLACEHOLDERS and not is_placeholder_label(name):
            hits.append(Hit(line_num, "personal-path", m.group(0),
                            "A home directory that names a user. Use `~/` or a placeholder.",
                            level="WARN"))
    if "@" in line:
        for m in _EMAIL_RE.finditer(line):
            local, domain = m.group("local"), m.group("domain").rstrip(".")
            if not _TLD_RE.search(domain):
                continue
            if (_PERSONAL_LOCAL_RE.match(local) and local.lower() not in _SAFE_LOCALS
                    and not _SAFE_EMAIL_DOMAINS.search(domain)):
                hits.append(Hit(line_num, "personal-email", m.group(0),
                                "A personal email address. Use `user@example.com`.", level="WARN"))
    return hits


# ---------------------------------------------------------------------------
# Hits and scanning
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Hit:
    line: int
    rule: str
    match: str
    advice: str
    level: str = "FAIL"
    ident: str = ""          # host or document id, for GRANDFATHERED lookups


def decode_line(line: str) -> str:
    """HTML-entity- and percent-decode, up to two rounds (safe-links / redirect wrappers)."""
    if "%" not in line and "&" not in line:
        return line
    cur = line
    for _ in range(2):
        nxt = unquote(html.unescape(cur))
        if nxt == cur:
            break
        cur = nxt
    return cur


def _rule_hits(line_num: int, line: str) -> list[Hit]:
    low = line.lower()
    if not any(t in low for t in _TRIGGERS):
        return []
    hits = []
    for rule in HOST_RULES:
        for m in rule.domain.finditer(line):
            if rule.after is not None and not rule.after.match(line, m.end()):
                continue
            tenant = _tenant_before(line, m.start())
            if not tenant:
                continue
            host = f"{tenant}.{m.group('domain')}".lower()
            pm = _PATH_RE.match(line, m.end())
            path = pm.group(0) if pm else ""
            if _host_exempt(rule, tenant, host, path):
                continue
            hits.append(Hit(line_num, rule.name, f"{tenant}.{m.group('domain')}{path}",
                            rule.advice, ident=host))
    for rule in RULES:
        for m in rule.regex.finditer(line):
            if rule.exempt is not None and rule.exempt(m):
                continue
            ident = m.groupdict().get("id") or m.group(0).lower()
            hits.append(Hit(line_num, rule.name, m.group(0), rule.advice, ident=ident))
    return hits


def scan_text(text: str, rel_path: str = "", denylist: Optional["Denylist"] = None,
              grandfathered: Optional[set] = None) -> list[Hit]:
    """Every non-exempt finding in ``text`` (FAIL and WARN levels)."""
    grand = GRANDFATHERED if grandfathered is None else grandfathered
    hits: list[Hit] = []
    for line_num, raw in enumerate(text.splitlines(), 1):
        line = decode_line(raw)
        for h in _rule_hits(line_num, line):
            if (rel_path, ident_hash(h.ident)) not in grand:
                hits.append(h)
        hits.extend(_personal_hits(line_num, line))
        if denylist is not None:
            hits.extend(denylist.hits(line_num, line))
    return hits


# ---------------------------------------------------------------------------
# Opt-in private customer-name denylist (see the module docstring)
# ---------------------------------------------------------------------------

DENYLIST_ENV = "TS_CUSTOMER_DENYLIST"
DEFAULT_DENYLIST = "~/.config/thoughtspot-agent-skills/customer-denylist.txt"
_MIN_WORD_LEN = 3          # shorter normalised names are ignored (they would match everywhere)
_MIN_SUBSTRING_LEN = 5     # shorter ones match only as whole words, never as substrings
_DENY_ADVICE = ("A name on the private customer denylist. Replace it with a synthetic "
                "name (`acme-corp`); see .claude/rules/security.md.")


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.lower())


@dataclass
class Denylist:
    substrings: list[tuple[str, int]] = field(default_factory=list)       # (normalised, entry #)
    words: list[tuple[re.Pattern, int]] = field(default_factory=list)
    # Every entry, longest first, as a pattern over ORIGINAL text, for redacting output.
    redactors: list[tuple[re.Pattern, int]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.substrings) + len(self.words)

    def entries_in(self, text: str) -> list[int]:
        """Entry numbers of every listed name found in ``text``."""
        found = []
        if self.substrings:
            normed = _norm(text)
            found += [n for s, n in self.substrings if s in normed]
        found += [n for rx, n in self.words if rx.search(text)]
        return sorted(set(found))

    def redact(self, text: str) -> str:
        """Replace every listed name in ``text`` with `<denylist entry #N>`."""
        for rx, n in self.redactors:
            text = rx.sub(f"<denylist entry #{n}>", text)
        return text

    def hits(self, line_num: int, line: str) -> list[Hit]:
        # Never echo the matched text: the name is the secret, and CI logs are public.
        return [Hit(line_num, "customer-name", f"<denylist entry #{n}>", _DENY_ADVICE)
                for n in self.entries_in(line)]


def compile_denylist(lines: Iterable[str]) -> Optional[Denylist]:
    dl = Denylist()
    seen: set[str] = set()
    for n, raw in enumerate(lines, 1):
        name = raw.strip()
        if not name or name.startswith("#"):
            continue
        key = _norm(name)
        if len(key) < _MIN_WORD_LEN or key in seen:
            continue
        seen.add(key)
        if len(key) >= _MIN_SUBSTRING_LEN:
            dl.substrings.append((key, n))
            # The normalised key with optional separators between its characters: matches
            # `Acme Corp`, `ACME_CORP`, `acme-corp`, `AcmeCorp` in the original text.
            # Literal/class alternation only, so it cannot backtrack.
            rx = re.compile(r"[^A-Za-z0-9]*".join(map(re.escape, key)), re.IGNORECASE)
        else:
            parts = re.findall(r"[A-Za-z0-9]+", name)
            rx = re.compile(r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]*".join(map(re.escape, parts))
                            + r"(?![A-Za-z0-9])", re.IGNORECASE)
            dl.words.append((rx, n))
        dl.redactors.append((rx, n))
    dl.redactors.sort(key=lambda r: len(r[0].pattern), reverse=True)
    return dl if len(dl) else None


def denylist_path() -> Path:
    return Path(os.environ.get(DENYLIST_ENV) or DEFAULT_DENYLIST).expanduser()


def load_denylist() -> Optional[Denylist]:
    """The configured denylist, or None when no file is configured (a silent skip)."""
    path = denylist_path()
    if not path.is_file():
        if os.environ.get(DENYLIST_ENV):
            print(f"NOTE  ${DENYLIST_ENV} is set but names no readable file; name check skipped.")
        return None
    return compile_denylist(path.read_text(encoding="utf-8-sig", errors="replace").splitlines())


# ---------------------------------------------------------------------------
# Decoding file content
# ---------------------------------------------------------------------------

_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z",
    ".twbx", ".tdsx", ".hyper", ".qvf", ".pbix", ".xlsx", ".xls", ".docx", ".pptx",
    ".pyc", ".pyo", ".so", ".dylib", ".whl", ".woff", ".woff2", ".ttf", ".otf",
}
_SNIFF_BYTES = 8192


def _utf16_without_bom(head: bytes) -> Optional[str]:
    """'utf-16-le' / 'utf-16-be' if the NUL pattern is UTF-16 text, else None."""
    sample = head[: _SNIFF_BYTES - (_SNIFF_BYTES % 2)]
    if len(sample) < 4:
        return None
    even, odd = sample[0::2], sample[1::2]
    if odd.count(0) >= 0.9 * len(odd) and even.count(0) <= 0.1 * len(even):
        return "utf-16-le"
    if even.count(0) >= 0.9 * len(even) and odd.count(0) <= 0.1 * len(odd):
        return "utf-16-be"
    return None


def decode_text(path_name: str, data: bytes) -> Optional[str]:
    """The file as text, or None if it is binary. UTF-16 (with or without BOM) is text."""
    if Path(path_name).suffix.lower() in _BINARY_SUFFIXES:
        return None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    head = data[:_SNIFF_BYTES]
    if b"\0" in head:
        enc = _utf16_without_bom(head)
        return data.decode(enc, errors="replace") if enc else None
    return data.decode("utf-8-sig", errors="replace")


def is_binary(path: Path, head: bytes) -> bool:
    return decode_text(path.name, head) is None


def scan_bytes(rel: str, data: bytes, denylist: Optional[Denylist] = None) -> list[Hit]:
    # A denylisted name in the PATH (examples/<customer>/...) counts, binary or not.
    hits = denylist.hits(0, rel) if denylist is not None else []
    text = decode_text(rel, data)
    if text is None:
        return hits
    return hits + scan_text(text, rel, denylist)


def scan_file(path: Path, repo_root: Path, denylist: Optional[Denylist] = None) -> list[Hit]:
    """Scan one working-tree file. A SYMLINK is scanned as its link text — what git stores
    as its blob — never followed: its target may be outside the repo, missing (a dangling
    link is still committed), or a directory."""
    try:
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", errors="replace")
        else:
            data = path.read_bytes()
    except OSError:
        data = b""
    return scan_bytes(path.relative_to(repo_root).as_posix(), data, denylist)


# ---------------------------------------------------------------------------
# --range: added lines and commit messages of every commit in a range
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _range_commits(repo_root: Path, rev_range: str) -> list[tuple[str, bool]]:
    """(sha, is_merge) for every commit in ``rev_range``, oldest first.

    One `rev-list --parents` line per commit: plain text, no NUL framing to be shifted by
    file content. Anything that is not a 40-hex sha fails CLOSED — an unparseable list
    must never read as "nothing to scan".
    """
    raw = git_bytes(["rev-list", "--reverse", "--parents", rev_range], repo_root)
    commits = []
    for line in raw.decode("ascii", errors="replace").splitlines():
        fields = line.split()
        if not fields or not all(_SHA_RE.match(f) for f in fields):
            raise GitEnumerationError(f"unexpected rev-list output for {rev_range}: {line[:80]!r}")
        commits.append((fields[0], len(fields) > 2))
    return commits


def _diff_hits(diff: str, short: str, denylist: Optional["Denylist"],
               keep: Callable[["Hit", str], bool]) -> list[tuple[str, "Hit"]]:
    """Findings in the ADDED lines of one commit's patch."""
    out: list[tuple[str, Hit]] = []
    # File headers (`---`/`+++`) are only recognised between a `diff --git` line and the
    # first hunk. Inside a hunk, `+++ x` is an ADDED line whose content is `++ x`.
    path, shown, new_line, in_header = "", "", 0, False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            path, shown, in_header = "", "", True
            continue
        m = _HUNK_RE.match(line)
        if m:
            new_line, in_header = int(m.group(1)), False
            continue
        if in_header:
            if line.startswith("+++ "):
                path = line[6:] if line.startswith("+++ b/") else ""
                shown = _display_path(path, denylist)
                if path and denylist is not None:
                    out += [(f"commit {short} {shown}", h) for h in denylist.hits(0, path)]
            continue
        if line.startswith("+"):
            for h in scan_text(line[1:], path, denylist, grandfathered=set()):
                if keep(h, path):
                    out.append((f"commit {short} {shown}:{new_line}", h))
            new_line += 1
        elif line.startswith(" "):
            new_line += 1
    return out


def scan_range(repo_root: Path, rev_range: str, denylist: Optional[Denylist] = None
               ) -> list[tuple[str, Hit]]:
    """(location, hit) for every finding in the range's added lines and commit messages.

    Each commit is read on its own (message, then patch), so no content — a NUL byte in a
    text file, say — can shift the parse and silently drop older commits. A merge commit's
    message is scanned; its diff is not (see BL-387).
    """
    out: list[tuple[str, Hit]] = []
    for sha, is_merge in _range_commits(repo_root, rev_range):
        short = sha[:7]

        def keep(h: Hit, path: str = "", sha: str = sha) -> bool:
            digest = ident_hash(h.ident)
            if h.level == "FAIL" and (any(sha == c and digest == d
                                          for c, d in RANGE_GRANDFATHERED)
                                      or (path, digest) in GRANDFATHERED):
                return False
            return True

        message = git_bytes(["log", "-1", "--format=%B", sha], repo_root).decode("utf-8", "replace")
        for h in scan_text(message, "", denylist, grandfathered=set()):
            if keep(h):
                out.append((f"commit {short} message:{h.line}", h))
        if is_merge:
            continue
        diff = git_bytes(["show", "--format=", "-p", "--no-color", "--no-ext-diff", sha],
                         repo_root).decode("utf-8", "replace")
        out += _diff_hits(diff, short, denylist, keep)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# The `git commit -v` scissors line: `<comment char> ------------------------ >8 ---…`.
_SCISSORS_RE = re.compile(r"^(?P<c>\S{1,8}) -{24} >8 -{24}\s*$")


def commit_message_text(raw: str, comment_char: Optional[str] = None) -> str:
    """The text to scan for a commit message: EVERY line, `#` lines included, up to a REAL
    `git commit -v` scissors line.

    `#` lines are not dropped: with `git commit -m` they are part of the recorded message
    (`#591 see …`), and the hook cannot tell an editor message from an `-m` one. A link in
    a git-generated comment is then flagged too, which costs the author an edit, not a
    leak.

    A scissors line only ends the message when git itself wrote it, otherwise
    `-m s -m "<scissors>" -m "<link>"` would hide the link. So it must use the comment
    character git would use (``comment_char``: `core.commentChar`, default `#`; for
    `auto`, any single character), and a `diff --git` line must follow it, which is what
    git appends below the scissors in a `-v` session.
    """
    lines = raw.splitlines()
    last_diff = max((i for i, l in enumerate(lines) if l.startswith("diff --git ")), default=-1)
    char = comment_char or "#"
    for i in range(last_diff):                       # empty when there is no diff below
        m = _SCISSORS_RE.match(lines[i])
        if not m:
            continue
        c = m.group("c")
        if (char == "auto" and len(c) == 1) or c == char:
            return "\n".join(lines[:i])
    return "\n".join(lines)


def _display_path(rel: str, denylist: Optional[Denylist]) -> str:
    if denylist is not None:
        entries = denylist.entries_in(rel)
        if entries:
            return f"<path redacted: denylist entry #{entries[0]}>"
    return rel


def _emit(location: str, hit: Hit, denylist: Optional[Denylist] = None) -> None:
    """Print one finding. EVERY printed field passes through the denylist redactor first
    (before truncation, so a name cannot survive half-cut): a host, a home path, an email
    or a commit message can contain a listed name just as a file can."""
    red = denylist.redact if denylist is not None else (lambda s: s)
    location, shown, advice = red(location), red(hit.match), red(hit.advice)
    if len(shown) > 100:
        shown = shown[:97] + "..."
    print(f"{hit.level:<5} {location}: [{hit.rule}] {shown}")
    print(f"      {advice}")
    if hit.level == "WARN" and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=Personal detail ({hit.rule})::{location} — {advice}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fail on links into a tenant's internal systems.")
    parser.add_argument("--root", default=".", help="Repo root (default: current dir)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true",
                      help="Scan all tracked files on disk (default: the staged content)")
    mode.add_argument("--range", metavar="A..B",
                      help="Scan the added lines and commit messages of every commit in A..B")
    mode.add_argument("--message-file", metavar="PATH",
                      help="Scan a commit message file (the commit-msg hook)")
    args = parser.parse_args(argv)
    repo_root = Path(args.root).resolve()
    denylist = load_denylist()

    findings: list[tuple[str, Hit]] = []
    try:
        if args.message_file:
            text = commit_message_text(
                Path(args.message_file).read_text(encoding="utf-8", errors="replace"),
                git_config_get("core.commentChar", repo_root))
            findings = [(f"commit message:{h.line}", h)
                        for h in scan_text(text, "", denylist, grandfathered=set())]
            scanned = "the commit message"
        elif args.range:
            findings = scan_range(repo_root, args.range, denylist)
            scanned = f"commits in {args.range}"
        elif args.all:
            # tracked_relpaths, not tracked_files: the latter drops paths whose target does
            # not exist, which silently skipped every dangling tracked symlink.
            files = [repo_root / r for r in tracked_relpaths(repo_root)
                     if (repo_root / r).is_symlink() or (repo_root / r).is_file()]
            for path in files:
                rel = path.relative_to(repo_root).as_posix()
                shown = _display_path(rel, denylist)
                findings += [(f"{shown}:{h.line}" if h.line else shown, h)
                             for h in scan_file(path, repo_root, denylist)]
            scanned = f"{len(files)} tracked file(s)"
        else:
            # The INDEX is what gets committed — read staged blobs, not the working tree.
            rels = staged_relpaths(repo_root)
            for rel in rels:
                shown = _display_path(rel, denylist)
                findings += [(f"{shown}:{h.line}" if h.line else shown, h)
                             for h in scan_bytes(rel, staged_blob(repo_root, rel), denylist)]
            scanned = f"{len(rels)} staged file(s)"
    except GitEnumerationError as exc:
        # A git failure must fail the gate, never read as "nothing to scan" (see _git).
        detail = denylist.redact(str(exc)) if denylist is not None else exc
        print(f"FAIL  could not read what to scan: {detail}")
        print("      Refusing to report PASS on an unscanned tree.")
        return 1

    fails = [f for f in findings if f[1].level == "FAIL"]
    for location, hit in fails + [f for f in findings if f[1].level == "WARN"]:
        _emit(location, hit, denylist)

    if fails:
        print()
        print(f"{len(fails)} customer reference(s) found. This repo is PUBLIC.")
        print("If a host is genuinely public or ThoughtSpot-owned, add it to the allowlist in")
        print("tools/validate/check_customer_references.py with a one-line justification.")
        return 1

    warns = len(findings) - len(fails)
    names = f", {len(denylist)} denylisted name(s)" if denylist else ""
    note = f" ({warns} personal-detail warning(s) above)" if warns else ""
    print(f"No customer references{names} in {scanned}{note}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
