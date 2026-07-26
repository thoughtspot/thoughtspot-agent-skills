"""Platform-neutral TML helpers — YAML serialization and import-response parsing.

Relocated from ts_cli/tableau/ (BL-063 PR 5): these were never Tableau-specific;
Databricks build-model and the dependency/tables commands use them too. Pure
functions, stdlib + PyYAML only — part of the Genie-vendorable closure.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


def dump_tml_yaml(data: dict) -> str:
    """Serialize a TML dict to YAML with proper quoting for formula expressions.

    Handles two problems that plain yaml.dump gets wrong for TML:
    1. Formula expressions contain : [] {} # which YAML misinterprets
    2. Long expressions get line-wrapped, producing invalid multi-line TML

    Values matching TML-sensitive patterns are double-quoted automatically.
    """
    import yaml

    class _QuotedStr(str):
        pass

    def _quoted_representer(dumper: yaml.Dumper, val: str) -> yaml.ScalarNode:
        return dumper.represent_scalar("tag:yaml.org,2002:str", val, style='"')

    _NEEDS_QUOTING = re.compile(r"[\[\]{}:#>|&*!%@`]|^\s|^'|^\"")

    def _quote_values(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {_quote_values(k): _quote_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_quote_values(v) for v in obj]
        if isinstance(obj, str) and _NEEDS_QUOTING.search(obj):
            return _QuotedStr(obj)
        return obj

    class _TmlDumper(yaml.Dumper):
        pass

    _TmlDumper.add_representer(_QuotedStr, _quoted_representer)

    quoted_data = _quote_values(data)
    return yaml.dump(
        quoted_data,
        Dumper=_TmlDumper,
        default_flow_style=False,
        allow_unicode=True,
        width=100000,
    )


def extract_imported_guid(import_result: list) -> str | None:
    """Pull the created/updated object GUID out of a tml import response.

    Two response shapes are both live on ThoughtSpot Cloud (verified BL-063 PR4,
    2026-07-10, se-thoughtspot): the historically-documented nested shape
    ``response.object[0].header.id_guid``, and a FLAT shape seen on `ts tml
    import` responses — ``response.header.id_guid`` (no ``object`` wrapper;
    ``header`` also carries ``name``/``metadata_type``; status lives at
    ``response.status.status_code``). Try nested first (preserves existing
    behavior for the Tableau MERGE flow), then fall back to flat. Returns None
    when neither shape yields a non-empty GUID, or the list is empty.
    """
    if not import_result:
        return None
    response = import_result[0].get("response", {})
    obj_list = response.get("object", [])
    if obj_list:
        guid = obj_list[0].get("header", {}).get("id_guid")
        if guid:
            return guid
    return response.get("header", {}).get("id_guid") or None


def tml_import_failures(import_result: Any) -> List[Dict[str, Any]]:
    """Per-item failures out of a `metadata/tml/import` response.

    `import` returns HTTP 200 even when every item failed: the per-item outcome lives
    at ``response.status.status_code`` -- ``"OK"`` on success, anything else a failure
    -- the same field `ts tml import`'s GUID-backfill loop already reads (see
    `commands/tml.py`). A caller that only checks the HTTP status code can print this
    body and exit 0 having imported nothing (live-observed on CSR import into an Org
    missing the referenced table, 2026-07-27).

    Status is read the same way regardless of which GUID shape `extract_imported_guid`
    had to fall back to (nested ``response.object[0].header`` vs flat
    ``response.header``): both put status at the sibling key ``response.status``, so
    this function does not need to branch on that shape at all.

    A missing ``status`` block (or a missing ``status_code`` within it) is NOT treated
    as a failure -- there is no positive evidence of one, and defaulting to "failed"
    would flag responses that never carried status information in the first place.
    Only an explicit, non-``"OK"`` ``status_code`` is reported.

    Tolerates a non-list, empty, or junk response by returning ``[]`` rather than
    raising: a read-back must not fail louder than the write it is checking.

    Each returned entry carries ``request_index`` (the item's own index if present,
    else its position), ``status_code``, ``error_code`` and ``error_message``.

    Pure -- no I/O.
    """
    failures: List[Dict[str, Any]] = []
    items = import_result if isinstance(import_result, list) else []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        response = item.get("response")
        if not isinstance(response, dict):
            continue
        status = response.get("status")
        if not isinstance(status, dict):
            continue
        status_code = status.get("status_code")
        if status_code is None or status_code == "OK":
            continue
        failures.append({
            "request_index": item.get("request_index", idx),
            "status_code": status_code,
            "error_code": status.get("error_code"),
            "error_message": status.get("error_message") or "",
        })
    return failures
