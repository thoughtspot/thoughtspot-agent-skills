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

from typing import Any, Dict, Iterable, List, Tuple

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
