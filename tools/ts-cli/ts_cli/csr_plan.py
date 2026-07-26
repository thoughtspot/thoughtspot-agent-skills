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
- CSR cannot be defined on PUBLISHED objects.

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
    return list(dict.fromkeys(v for v in values))


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

    **Publication.** CSR cannot be defined on a published object, so a step whose table
    is published is marked ``blocked`` rather than silently planned. `apply` refuses
    blocked steps unless overridden. Failing at plan time is the house style, and it is
    also parent spec 5.1's CSR_BLOCKER at CLI level.

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
                f"CSR_BLOCKED: '{table_name}' is published, and column security rules "
                f"cannot be defined on a published object. Use column-level sharing "
                f"(`ts share`) for published tables.")

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

_FEATURE_DISABLED_RE = re.compile(
    r"10023|Column Security rule feature is disabled", re.IGNORECASE)
_MISSING_TABLE_RE = re.compile(r"14502|Referenced table with name\s+not found",
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

    if _MISSING_TABLE_RE.search(body):
        return (
            "The column_security_rules document is missing its `table:` reference, so "
            "the platform resolved an empty table name (note the doubled space in its "
            "message). The reference is mandatory even when the document is imported "
            "alongside the table it belongs to.")

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
