"""ts metadata parameterize / unparameterize — bind template variables to object fields.

Attaches to the SAME `app` Typer group defined in `ts_cli/commands/metadata.py`
rather than registering its own, so the subcommands appear under `ts metadata`.
`cli.py` imports this module to run the `@app.command` registration (same pattern
as `dependency_apply.py` attaching to `dependency.app`).

Split out of metadata.py to keep that module under the file-size gate.

Endpoint shapes verified live on 2026-07-25 (see
docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md §2.5):

- POST /api/rest/2.0/metadata/parameterize-fields  (batch field_names[])
- POST /api/rest/2.0/metadata/unparameterize       (single field_name + restore value)

The singular POST /api/rest/2.0/metadata/parameterize is deprecated and unused here.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.metadata import app, _profile_option

# The only Logical Table attributes that can carry a variable.
TABLE_FIELDS = ("databaseName", "schemaName", "tableName")

# field_type is fully determined by metadata_type, so callers never supply it.
# Getting it wrong is the code-10002 error class
# ("Parameterization of given Object cannot be done with Variable of type: ..."),
# which this mapping makes unreachable.
_FIELD_TYPE_BY_METADATA_TYPE = {
    "LOGICAL_TABLE": "ATTRIBUTE",
    "CONNECTION": "CONNECTION_PROPERTY",
    "CONNECTION_CONFIG": "CONNECTION_PROPERTY",
}


def _field_type_for(metadata_type: str) -> str:
    try:
        return _FIELD_TYPE_BY_METADATA_TYPE[metadata_type]
    except KeyError:
        raise ValueError(
            f"Unknown metadata type '{metadata_type}'. Expected one of: "
            f"{', '.join(_FIELD_TYPE_BY_METADATA_TYPE)}"
        ) from None


def _validate_field_names(metadata_type: str, field_names: List[str]) -> None:
    if not field_names:
        raise ValueError("Specify at least one field to parameterize")
    if metadata_type != "LOGICAL_TABLE":
        # Connection property names are warehouse-specific and open-ended
        # (accountName, warehouse, role, vendor extras), so they pass through.
        return
    unknown = [f for f in field_names if f not in TABLE_FIELDS]
    if unknown:
        raise ValueError(
            f"Not a parameterizable Logical Table field: {', '.join(unknown)}. "
            f"Expected one of: {', '.join(TABLE_FIELDS)}"
        )


def build_parameterize_payload(
    metadata_type: str, identifier: str, field_names: List[str], variable: str,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/metadata/parameterize-fields.

    Pure — no I/O — so it is unit-testable without a live instance.
    """
    field_type = _field_type_for(metadata_type)
    _validate_field_names(metadata_type, field_names)
    return {
        "metadata_type": metadata_type,
        "metadata_identifier": identifier,
        "field_type": field_type,
        "field_names": list(field_names),
        "variable_identifier": variable,
    }


def build_unparameterize_payload(
    metadata_type: str, identifier: str, field_name: str, value: str,
) -> Dict[str, Any]:
    """Build the request body for POST /api/rest/2.0/metadata/unparameterize.

    ``value`` is mandatory: the endpoint replaces the variable with a static
    value rather than simply clearing it, so there is no "just remove the
    variable" call. Callers must have recorded the original.
    """
    field_type = _field_type_for(metadata_type)
    if not value:
        raise ValueError(
            "A restore value is required — unparameterize replaces the variable with a "
            "static value rather than clearing the field"
        )
    return {
        "metadata_type": metadata_type,
        "metadata_identifier": identifier,
        "field_type": field_type,
        "field_name": field_name,
        "value": value,
    }


def shared_token_warning(field_names: List[str], variable: str) -> Optional[str]:
    """Warn when one variable is being bound to several fields at once.

    Verified live: ``field_names[]`` is a batch convenience that writes the SAME
    ``${variable}`` token into every field listed. Binding one variable to both
    databaseName and schemaName therefore makes them resolve to one identical
    value, which is almost never intended — the usual model is one variable per
    distinct value. Legitimate when the values genuinely are identical, so this
    warns rather than blocks.

    Returns the warning text, or None when there is nothing to flag.
    """
    if len(field_names) < 2:
        return None
    return (
        f"Warning: binding '{variable}' to {len(field_names)} fields "
        f"({', '.join(field_names)}) writes the same value into all of them. "
        f"Use one variable per distinct value unless they really are identical."
    )


@app.command("parameterize")
def parameterize(
    identifier: str = typer.Argument(..., help="GUID or name of the object to parameterize"),
    variable: str = typer.Option(..., "--variable", "-v", help="Variable name or ID to bind"),
    field: List[str] = typer.Option(..., "--field", "-f",
                                    help="Field to parameterize (repeatable). For a Logical Table: "
                                         f"{' | '.join(TABLE_FIELDS)}. For a Connection: the property name."),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE | CONNECTION | CONNECTION_CONFIG"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Bind a template variable to one or more fields of an object.

    Replaces the field's static value with a `${variable}` token. The variable's
    per-org values then resolve at runtime. `field_type` is derived from --type,
    so a type mismatch is impossible.

    Create the variable first with `ts variables create`, and give it a value in
    every target org with `ts variables set` — publishing fails closed otherwise.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \b
      ts metadata parameterize 4be2cc25-... --variable apj_schema --field schemaName
      ts metadata parameterize T1_PUBLISH --variable apj_db --field databaseName
      ts metadata parameterize APJ --type CONNECTION --variable acct_var --field accountName
    """
    payload = build_parameterize_payload(type, identifier, list(field), variable)
    warning = shared_token_warning(list(field), variable)
    if warning:
        print(warning, file=sys.stderr)
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post("/api/rest/2.0/metadata/parameterize-fields", json=payload)


@app.command("unparameterize")
def unparameterize(
    identifier: str = typer.Argument(..., help="GUID or name of the object"),
    field: str = typer.Option(..., "--field", "-f", help="Single field to restore"),
    value: str = typer.Option(..., "--value",
                              help="Static value to write back in place of the variable. "
                                   "Required — the field cannot simply be cleared."),
    type: str = typer.Option("LOGICAL_TABLE", "--type", "-t",
                             help="Object type: LOGICAL_TABLE | CONNECTION | CONNECTION_CONFIG"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Remove a variable from a field, restoring a static value.

    One field per call (unlike `parameterize`, which is batched). The endpoint
    substitutes --value for the variable, so the caller must know the value to
    restore; `ts publish build` records the originals for exactly this reason.

    Output: empty on success (HTTP 204). Raises on error.

    Examples:

    \b
      ts metadata unparameterize 4be2cc25-... --field schemaName --value ALIAS_TESTS
      ts metadata unparameterize APJ --type CONNECTION --field accountName --value xy12345
    """
    payload = build_unparameterize_payload(type, identifier, field, value)
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post("/api/rest/2.0/metadata/unparameterize", json=payload)
