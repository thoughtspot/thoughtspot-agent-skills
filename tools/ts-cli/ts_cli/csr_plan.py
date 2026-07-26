"""Pure planning logic behind `ts security column-rules` -- Column Security Rules.

No I/O, so every rule here is unit-testable without a live instance. The command
layer (`ts_cli/commands/security.py` and `security_planning.py`) is the thin wrapper,
mirroring how `share_plan.py` sits under `commands/share.py`.

CSR is the OTHER column-security mechanism. It is not column-level sharing, and the
two must not be modelled the same way:

- CSR declares only the RESTRICTED columns, naming the groups that may see each one.
  Column-level sharing (CLS) is the inverse: it enumerates every VISIBLE column per
  group. Three CSR rules on a 40-column table become roughly 40 x G grants under CLS.
- CSR is a separate axis from the share ACL. Turning it on does not change an object's
  grant list (verified live 2026-07-26).
- CSR on a PUBLISHED object is refused by this CLI by default -- but that is a
  conservative choice, not a platform restriction. Live-verified 2026-07-27: an
  owning-Org CSR update against a genuinely published table returned HTTP 204 and took
  effect. What is still unverified is whether a TENANT Org can see or use a rule set
  that way, so `build_csr_steps` blocks by default and `--allow-published` overrides it.

Endpoint shape confirmed against the canonical spec (`get-rest-api-reference`,
operations `fetchColumnSecurityRules` and `updateColumnSecurityRules`). Four things
matter and each has caught somebody already:

- `group_access` carries an `operation`: ADD, REMOVE or REPLACE. CSR is both
  incremental and declarative, so a caller has to choose which it means.
- `update` takes ONE table per call (`identifier` is a scalar), so its documented
  "all or none" rollback is per call, not per run.
- `column_security_rules` is a REQUIRED field. That is why `clear_csr: true` alone is
  rejected: it is schema validation, not a bug, so both are always emitted.
- Per-column `is_unsecured: true` exists, distinct from whole-table `clear_csr`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

OPERATIONS: Tuple[str, ...] = ("ADD", "REMOVE", "REPLACE")

# Mirrors the `ts alias` / `ts publish` / `ts share` convention: one manifest table,
# emitted by --init-table. The unit is (org, table, column, group).
#
# Only RESTRICTED columns appear -- that is CSR's declaration model, and the inverse
# of TS_SHARE_GRANTS. The two manifests are deliberately not interchangeable.
#
# group_name is NOT NULL with the empty string as its sentinel ("secured, no group can
# see it") rather than nullable, because a nullable column cannot sit in a primary key.
CSR_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS TS_COLUMN_SECURITY_RULES (\n"
    "    org_name     VARCHAR NOT NULL,\n"
    "    table_name   VARCHAR NOT NULL,\n"
    "    column_name  VARCHAR NOT NULL,\n"
    "    group_name   VARCHAR NOT NULL,   -- empty string = secured, no group can see it\n"
    "    updated_at   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),\n"
    "    PRIMARY KEY (org_name, table_name, column_name, group_name)\n"
    ");"
)

_RULE_KEYS = ("org_name", "table_name", "column_name", "group_name")


def _lower_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """Case-insensitive column access, so a CSV header and a Snowflake
    (upper-cased) column name parse identically."""
    return {str(k).strip().lower(): v for k, v in (row or {}).items()}


def _text(row: Dict[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _dedupe(values: Iterable[str]) -> List[str]:
    """Order-preserving dedupe, so a plan is stable but reads in the operator's order."""
    return list(dict.fromkeys(values))


def parse_rule_flags(rules: Iterable[str]) -> Dict[str, List[str]]:
    """Parse repeatable ``--rule "COL=G1,G2"`` flags into {column: [groups]}.

    An empty group list (``--rule "COST="``) is meaningful, not a mistake: it declares
    the column secured with no group able to see it. Without that form there would be
    no way to express it, because CSR has no separate "restricted" flag.

    Repeated flags naming the same column merge rather than overwrite, so
    ``--rule COST=A --rule COST=B`` is the same as ``--rule COST=A,B``.

    Pure -- no I/O.
    """
    parsed: Dict[str, List[str]] = {}
    for entry in rules or ():
        text = str(entry)
        if "=" not in text:
            raise ValueError(
                f"--rule '{text}' is malformed. Expected COL=GROUP[,GROUP...]; use "
                f"COL= (with nothing after the =) to secure a column for nobody.")
        column, _, groups = text.partition("=")
        column = column.strip()
        if not column:
            raise ValueError(f"--rule '{text}' has an empty column name before the '='.")
        names = [g.strip() for g in groups.split(",") if g.strip()]
        parsed[column] = _dedupe(parsed.get(column, []) + names)
    return parsed


def parse_rule_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Parse a TS_COLUMN_SECURITY_RULES manifest into normalised rows.

    Columns: ``org_name``, ``table_name``, ``column_name`` (all required) and
    ``group_name`` (required as a field; its empty string is the "secured, nobody"
    sentinel).

    Identifier casing is preserved throughout -- every field here is matched against a
    real name on the instance, so nothing is upper-cased the way an enum field would be.

    Fully blank rows are skipped so a trailing CSV newline is harmless. A partially
    filled row is an error: silently dropping a rule leaves a column unprotected with
    no trace of why.

    Pure -- no I/O.
    """
    parsed: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    for raw in rows or ():
        row = _lower_keys(raw)
        values = {key: _text(row, key) for key in _RULE_KEYS}
        if not any(values.values()):
            continue

        for field in ("org_name", "table_name", "column_name"):
            if not values[field]:
                raise ValueError(
                    f"Column security rule row is missing {field}: {raw!r}. CSR declares "
                    f"which columns are restricted, so a row needs all three of "
                    f"org_name, table_name and column_name.")

        key = (values["org_name"], values["table_name"],
               values["column_name"], values["group_name"])
        parsed[key] = dict(values)
    return list(parsed.values())


# ---------------------------------------------------------------------------
# Payload building -- one `security/column/rules/update` body
# ---------------------------------------------------------------------------

def build_update_payload(
    table_identifier: str,
    rules: Dict[str, List[str]],
    *,
    operation: str = "REPLACE",
    unsecure: Optional[Iterable[str]] = None,
    clear: bool = False,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/security/column/rules/update.

    ``column_security_rules`` is ALWAYS present, including when ``clear`` is set. The
    field is required by the request schema, which is why `clear_csr: true` on its own
    is rejected even though the prose implies the flag suffices. Emitting both is not
    belt-and-braces; it is the only accepted form.

    ``operation`` defaults to REPLACE so the call is idempotent: what the caller passes
    is what the column ends up with, and running it twice converges. ADD and REMOVE are
    reachable for the incremental cases.

    An empty group list for a column is preserved rather than dropped. Under REPLACE it
    declares the column secured with no group able to see it, which is a real state a
    manifest has to be able to express.

    One table per call: ``identifier`` is a scalar in the API, so the documented
    "all or none" rollback covers this body and nothing beyond it.

    Pure -- no I/O.
    """
    identifier = str(table_identifier or "").strip()
    if not identifier:
        raise ValueError("A table identifier (GUID or name) is required")

    if operation not in OPERATIONS:
        raise ValueError(
            f"operation '{operation}' is not valid. Expected one of: "
            f"{', '.join(OPERATIONS)}.")

    pruned = _dedupe(str(c).strip() for c in (unsecure or ()) if str(c).strip())

    if clear:
        if rules or pruned:
            raise ValueError(
                "clear cannot be combined with rules or unsecure: clear_csr already "
                "unsecures every column on the table, so pairing it with per-column "
                "instructions is ambiguous about what should survive.")
        return {"identifier": identifier, "clear_csr": True,
                "column_security_rules": []}

    if not rules and not pruned:
        raise ValueError(
            "nothing to do: pass at least one rule, one column to unsecure, or clear.")

    # Sorted so the same inputs always produce the same body, which is what makes a
    # --dry-run plan diffable between runs.
    entries: List[Dict[str, Any]] = [
        {"column_identifier": column,
         "is_unsecured": False,
         "group_access": [{"operation": operation,
                           "group_identifiers": _dedupe(rules[column] or [])}]}
        for column in sorted(rules)
    ]
    entries += [{"column_identifier": column, "is_unsecured": True}
                for column in sorted(pruned)]

    return {"identifier": identifier, "clear_csr": False,
            "column_security_rules": entries}


# ---------------------------------------------------------------------------
# Step assembly -- the `ts security column-rules apply` engine
# ---------------------------------------------------------------------------

def _table_index(tables: Optional[List[Dict[str, Any]]]) -> Dict[Tuple[str, str],
                                                                 Dict[str, Any]]:
    """{(org, table name): resolution entry} for the tables the command layer resolved."""
    return {(str(t.get("org_name") or ""), str(t.get("table_name") or "")): t
            for t in (tables or ())}


def build_csr_steps(
    rows: List[Dict[str, str]],
    tables: Optional[List[Dict[str, Any]]] = None,
    *,
    operation: str = "REPLACE",
    prune: bool = False,
) -> List[Dict[str, Any]]:
    """Turn manifest rows into one step per (org, table): one API call each.

    ``update`` takes a single table, so the batching question that `ts share` has does
    not arise here. What does arise is ordering: everything is sorted, so the same
    manifest always yields the same plan and a --dry-run diffs cleanly between runs.

    ``tables`` carries what only the command layer can know: the table's GUID, whether
    it is published, and which of its columns are secured today. It is optional so the
    pure function stays testable, and so `set` can build a step without a resolution
    pass.

    **Publication.** A step whose table is published is marked ``blocked`` rather than
    silently planned, and `apply` refuses blocked steps unless overridden. This is a
    conservative CLI default, not a platform restriction: live-verified 2026-07-27, an
    owning-Org CSR update against a genuinely published table returned HTTP 204 and took
    effect, the table staying published throughout. What is still unverified is whether
    a TENANT Org can see or use a rule set that way -- applying one could silently
    produce protection the tenant never receives, which is what the refusal guards
    against. `--allow-published` is the escape hatch. Failing at plan time is the house
    style, and it is also parent spec 5.1's CSR_BLOCKER at CLI level.

    A table entry may also carry ``publication_known: False``, meaning the command layer
    could not read publication state at all (a failed `metadata/search`). That blocks the
    step too, with its own reason: an unreadable gate must not degrade to an open one,
    and "not published" is a claim only a successful read can support. The key defaults
    to known when absent, so a caller with nothing to say about it is taken at its word.

    **Pruning.** With ``prune``, columns secured today but absent from the manifest are
    listed in ``unsecure``. Without it they are left alone. The asymmetry is deliberate:
    an incomplete manifest under prune-by-default would silently unsecure columns and
    expose data, whereas leaving stale protection in place is visible and recoverable.
    Only one of those two failure modes leaks.

    Pure -- no I/O.
    """
    if operation not in OPERATIONS:
        raise ValueError(
            f"operation '{operation}' is not valid. Expected one of: "
            f"{', '.join(OPERATIONS)}.")

    index = _table_index(tables)
    grouped: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    for row in rows or ():
        key = (row["org_name"], row["table_name"])
        rules = grouped.setdefault(key, {})
        groups = rules.setdefault(row["column_name"], [])
        # A blank group_name is the "secured, nobody" sentinel: it means the ABSENCE of
        # a group, so it must not travel as a literal "" identifier.
        if row["group_name"]:
            groups.append(row["group_name"])

    steps: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        org_name, table_name = key
        entry = index.get(key) or {}
        rules = {column: sorted(set(groups))
                 for column, groups in grouped[key].items()}

        secured_today = [str(c) for c in (entry.get("secured_columns") or [])]
        unsecure = (sorted(set(secured_today) - set(rules)) if prune else [])

        blocked = ""
        if entry.get("published"):
            blocked = (
                f"CSR_BLOCKED: '{table_name}' is published. The platform does accept "
                f"CSR from the owning Org (live-verified), but whether a tenant Org can "
                f"see or use it is unverified, so this is refused by default. Pass "
                f"--allow-published to override, or use column-level sharing "
                f"(`ts share`) instead.")
        elif not entry.get("publication_known", True):
            blocked = (
                f"CSR_BLOCKED: publication state could not be determined for "
                f"'{table_name}', so whether CSR can be defined on it is unknown. "
                f"Re-run once the read succeeds, or pass --allow-published to `apply` "
                f"to send it anyway.")

        steps.append({
            "org_name": org_name,
            "table_identifier": str(entry.get("table_guid") or table_name),
            "table_name": table_name,
            "operation": operation,
            "rules": rules,
            "unsecure": unsecure,
            "blocked": blocked,
        })
    return steps


# ---------------------------------------------------------------------------
# Read-back -- the `get` normaliser and the verification diff
# ---------------------------------------------------------------------------

def _str(value: Any) -> str:
    """Missing or null field to an empty string, without a branch at each call site."""
    return "" if value is None else str(value)


def _first(container: Dict[str, Any], *keys: str) -> Any:
    """The first present key. The API documents this response two ways.

    The prose example shows a ``data`` envelope with camelCase keys
    (``columnSecurityRules``, ``objId``, ``sourceTableDetails``); the response schema
    shows a bare array with snake_case (``column_security_rules``, ``obj_id``,
    ``source_table_details``). Which one a build returns is not knowable from the spec,
    so both are read.
    """
    for key in keys:
        if key in container:
            return container[key]
    return None


def normalise_fetch_response(data: Any) -> List[Dict[str, Any]]:
    """Flatten a `security/column/rules/fetch` response to one row per (table, column).

    Nested three levels deep is awkward to eyeball or diff; one flat row per secured
    column is what an operator reads and what a before/after comparison needs.

    ``group_names`` is sorted, so a diff reflects a real change of audience rather than
    the order the platform happened to list them in.

    Anything unexpected is skipped rather than raised on: a read-back must not fail
    louder than the write it is checking.
    """
    if isinstance(data, dict):
        entries = _first(data, "data", "tables") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    rows: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        table_guid = _str(_first(entry, "table_guid", "guid"))
        obj_id = _str(_first(entry, "obj_id", "objId"))
        rules = _first(entry, "column_security_rules", "columnSecurityRules") or []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            column = rule.get("column") or {}
            groups = rule.get("groups") or []
            source = _first(rule, "source_table_details", "sourceTableDetails") or {}
            rows.append({
                "table_guid": table_guid,
                "obj_id": obj_id,
                "column_id": _str(column.get("id")),
                "column_name": _str(column.get("name")),
                "group_names": sorted(_str(g.get("name")) for g in groups
                                      if isinstance(g, dict)),
                "source_table_name": _str(source.get("name")),
            })
    return rows


def diff_csr(before: List[Dict[str, Any]],
             after: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compare two `normalise_fetch_response` outputs, keyed on (table, column).

    This is what proves an apply landed and what returns a test cluster to baseline
    honestly. Reading a single state in isolation cannot do either.

    Pure -- no I/O.
    """
    def _key(row: Dict[str, Any]) -> Tuple[str, str]:
        return (_str(row.get("table_guid")), _str(row.get("column_name")))

    before_index = {_key(r): r for r in before or ()}
    after_index = {_key(r): r for r in after or ()}

    added = [after_index[k] for k in sorted(set(after_index) - set(before_index))]
    removed = [before_index[k] for k in sorted(set(before_index) - set(after_index))]
    changed = [
        {"table_guid": k[0], "column_name": k[1],
         "before_groups": before_index[k].get("group_names") or [],
         "after_groups": after_index[k].get("group_names") or []}
        for k in sorted(set(before_index) & set(after_index))
        if (before_index[k].get("group_names") or [])
        != (after_index[k].get("group_names") or [])
    ]
    return {"added": added, "removed": removed, "changed": changed}


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

# Code 10023 is OVERLOADED -- live-verified 2026-07-27 reading CSR from a target Org
# on `nebula-damian-alias`, a cluster where the feature is demonstrably ON (an
# owning-Org CSR update had just succeeded moments earlier):
#
#   HTTP 500 {"error":{"message":{"debug":{"code":10023, ...,
#             "debug":"[\"User does not have access to rea[d]...\"]"}}}}
#
# So 10023 means EITHER "the feature is feature-flagged off" (body text "Column
# Security rule feature is disabled") OR "the caller lacks access to read/modify CSR
# in this Org" -- a different failure entirely, and the one this fix exists for.
# Keying on the bare code, as this used to, announced the feature was off when the
# real problem was Org-scoped access -- the same defect class as the 14502 overload
# below. Disambiguation is now on the accompanying message text, never the code
# alone: the disabled-form text is required for the feature-flag reading, and the
# access-form text is required for the access reading. A bare 10023 with NEITHER
# text present is genuinely ambiguous and falls through to `None`, like anything else
# unrecognised, rather than guessing which of the two it is.
_FEATURE_DISABLED_RE = re.compile(
    r"Column Security rule feature is disabled", re.IGNORECASE)
_ACCESS_DENIED_RE = re.compile(r"does not have access", re.IGNORECASE)
_CODE_10023_RE = re.compile(r"\b10023\b")

# Code 14502 covers TWO genuinely different cases, live-verified 2026-07-27 to be
# distinct rather than the same failure with cosmetic wording:
#   - EMPTY name  -- "Referenced table with name  not found" (doubled space, an empty
#     name interpolated). The document really is missing its `table:` reference.
#   - NAMED but absent -- "Referenced table with name T2_PUBLISH not found." The
#     reference is fine; that table just does not exist in the Org being imported
#     into. This is the normal, expected outcome of importing a CSR document into an
#     Org that lacks the table, and it is how `table:` was confirmed to resolve
#     per-Org by name (design spec §8 Q5).
# Treating both as "the reference is missing" (the pre-fix behaviour) sends the
# operator to edit a document that is already correct. `_MISSING_TABLE_NAMED_RE`
# is what tells them apart: it only matches when a real, non-empty name sits between
# "with name" and "not found". A bare `14502` mention with no such phrase at all
# (e.g. a log line naming only the code) can't be told apart, so it falls back to the
# empty-reference wording -- the same call `explain_csr_error` always made before this
# distinction existed.
_MISSING_TABLE_RE = re.compile(r"\b14502\b|Referenced table with name\b",
                               re.IGNORECASE)
_MISSING_TABLE_NAMED_RE = re.compile(
    r"Referenced table with name\s+(\S[^\n]*?)\s+not found", re.IGNORECASE)

# Live-verified 2026-07-27: `is_unsecured: true` on a column with no rule today is a
# genuine HTTP 400, not a harmless no-op -- the platform's own wording is the useful
# part, so this is surfaced rather than paraphrased away. See `--prune`'s staleness
# note on `explain_csr_error` below.
_UNSECURE_NEVER_SECURED_RE = re.compile(
    r"is not secured,\s*cannot mark as unsecured", re.IGNORECASE)
_UNSECURE_COLUMN_NAME_RE = re.compile(r"Column '([^']+)' is not secured",
                                      re.IGNORECASE)

_RULES_REQUIRED_RE = re.compile(
    r"column_security_rules\D{0,40}(is )?required|required\D{0,40}column_security_rules",
    re.IGNORECASE)


def explain_csr_error(body_text: str,
                      status_code: Optional[int] = None) -> Optional[str]:
    """Translate a CSR failure into an actionable message.

    Returns None when nothing matches, so the caller surfaces the raw error rather than
    a confident paraphrase of a failure we do not recognise. Same contract as
    `explain_share_error`.

    Pure -- no I/O.
    """
    body = body_text or ""

    if _FEATURE_DISABLED_RE.search(body):
        return (
            "Column Security Rules are feature-flagged off on this cluster. The "
            "capability is Beta and needs 10.12.0.cl or later, plus the flag enabled "
            "by ThoughtSpot. This is not an access-control problem and no payload "
            "change will fix it: ask for the flag, then re-run.")

    if _CODE_10023_RE.search(body) and _ACCESS_DENIED_RE.search(body):
        return (
            "Code 10023, but this is an access failure, not the feature-flag case "
            "that shares its code -- the feature is not disabled. The caller lacks "
            "access to read or modify column security rules in the Org this call ran "
            "in. Groups and privileges are per-Org, so a token scoped to a tenant Org "
            "can lack what the Primary Org token has. Re-run with a profile or Org "
            "that holds the needed privilege.")

    if _MISSING_TABLE_RE.search(body):
        named = _MISSING_TABLE_NAMED_RE.search(body)
        table_name = named.group(1).strip() if named else ""
        if table_name:
            return (
                f"The column_security_rules document's `table:` reference is fine -- "
                f"'{table_name}' just does not exist in the Org being imported into. "
                f"CSR documents are portable only to Orgs that have a same-named "
                f"table. Editing this document will not help; import into an Org "
                f"where '{table_name}' exists, or create it there first.")
        return (
            "The column_security_rules document is missing its `table:` reference, so "
            "the platform resolved an empty table name (note the doubled space in its "
            "message). The reference is mandatory even when the document is imported "
            "alongside the table it belongs to.")

    if _UNSECURE_NEVER_SECURED_RE.search(body):
        name = _UNSECURE_COLUMN_NAME_RE.search(body)
        column = f" '{name.group(1)}'" if name else ""
        return (
            f"Column{column} is not secured, so it cannot be marked unsecured -- the "
            f"platform's own wording. The likely cause is a stale plan: `--prune` "
            f"computes `unsecure` from columns confirmed secured when `resolve` ran, "
            f"and one of them has since been unsecured by something else. Re-run "
            f"`resolve` to refresh the plan against current state, then re-apply.")

    if _RULES_REQUIRED_RE.search(body):
        return (
            "`column_security_rules` is a required field, so `clear_csr: true` must "
            "ship with `column_security_rules: []` beside it. The docs imply the flag "
            "alone suffices; the request schema disagrees.")

    if status_code == 403:
        return (
            "Forbidden, and not the CSR feature flag. Column security rules need "
            "ADMINISTRATION, or DATAMANAGEMENT with RBAC disabled, or "
            "CAN_MANAGE_WORKSHEET_VIEWS_TABLES with RBAC enabled.")

    return None


# ---------------------------------------------------------------------------
# The TML route -- CSR is a sibling document, exactly the column_alias pattern
# ---------------------------------------------------------------------------

CSR_TML_TYPE = "column_security_rules"


def csr_tml_filename(table_name: str) -> str:
    """The filename the platform itself uses for an exported CSR document."""
    return f"{table_name}_CSR.{CSR_TML_TYPE}.tml"


def build_csr_tml(table_name: str, rules: Dict[str, List[str]],
                  guid: Optional[str] = None) -> Dict[str, Any]:
    """Assemble a `column_security_rules` TML document.

    The ``table:`` reference is MANDATORY. Omitting it fails the import with code 14502
    and `Referenced table with name  not found`, the empty name interpolated into the
    message. It is required even when the document is imported alongside its table.

    ``guid`` is omitted unless supplied: at the document root it is what turns an import
    into an in-place update, so a first import must not carry one and an update must.

    Only restricted columns appear, each with the groups that may see it. This is the
    inverse of CLS, which enumerates every visible column per group.

    Pure -- no I/O.
    """
    name = str(table_name or "").strip()
    if not name:
        raise ValueError("A table name is required: the `table:` reference is mandatory "
                         "and an empty one fails the import with code 14502")

    document: Dict[str, Any] = {}
    if guid:
        document["guid"] = guid
    document[CSR_TML_TYPE] = {
        "table": {"name": name},
        "rules": [
            {"column_name": column,
             "accessible_groups": {"group_name": sorted(set(rules[column] or []))}}
            for column in sorted(rules)
        ],
    }
    return document


def _rules_from_tml(body: Dict[str, Any]) -> Dict[str, List[str]]:
    """{column: [groups]} from a parsed column_security_rules document body."""
    rules: Dict[str, List[str]] = {}
    for rule in (body.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        column = _str(rule.get("column_name"))
        if not column:
            continue
        groups = (rule.get("accessible_groups") or {}).get("group_name") or []
        rules[column] = [_str(g) for g in groups]
    return rules


def parse_csr_tml_export(edocs: Any) -> List[Dict[str, Any]]:
    """Pull the CSR documents out of a `metadata/tml/export` response.

    An export asked for with ``export_column_security_rules`` returns the table's own
    document alongside the CSR sibling, so the CSR one has to be picked out by
    ``info.type``.

    An empty result is a legitimate answer, not a failure: the export option is Beta,
    and a table with no secured columns has no CSR document to return.
    """
    import yaml

    parsed: List[Dict[str, Any]] = []
    for item in (edocs or ()):
        if not isinstance(item, dict):
            continue
        info = item.get("info") or {}
        if not isinstance(info, dict) or info.get("type") != CSR_TML_TYPE:
            continue
        text = item.get("edoc") or ""
        if not text:
            continue
        try:
            document = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        body = document.get(CSR_TML_TYPE) or {}
        if not isinstance(body, dict):
            continue
        parsed.append({
            "table_name": _str((body.get("table") or {}).get("name")),
            "rules": _rules_from_tml(body),
            "guid": _str(document.get("guid") or info.get("id")),
            "yaml": text,
        })
    return parsed
