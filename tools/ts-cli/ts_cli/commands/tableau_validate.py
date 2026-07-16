"""ts tableau validate — deterministic TML validation harness (T5).

Local proofread (invariant lint) + remote VALIDATE_ONLY import + per-object
error classification (fixable / LOCKED / warning) + attempt tracking +
persistent lock registry with cascade detection.

No data is persisted to the cluster — VALIDATE_ONLY is a dry-run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


# ── Attempt tracking ────────────────────────────────────────────────────────

_STATE_FILE = "_validate_state.json"
_LOCK_REGISTRY_FILE = "_lock_registry.json"
_LIMITATIONS_FILE = "MIGRATION_LIMITATIONS.md"
HARD_CAP = 10
SOFT_CAP = 10


def _load_state(output_dir: str) -> dict:
    path = Path(output_dir) / _STATE_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"attempt": 0, "history": []}


def _save_state(output_dir: str, state: dict) -> None:
    path = Path(output_dir) / _STATE_FILE
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Lock registry ──────────────────────────────────────────────────────────

def _load_lock_registry(output_dir: str) -> dict:
    """Load the persistent lock registry.

    Shape: {"locked_objects": {"sv_orders.sql_view.tml": {
        "object_name": "...", "locked_at_attempt": 3,
        "error_code": 14537, "error_message": "...", "reason": "..."
    }}}
    """
    path = Path(output_dir) / _LOCK_REGISTRY_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"locked_objects": {}}


def _save_lock_registry(output_dir: str, registry: dict) -> None:
    path = Path(output_dir) / _LOCK_REGISTRY_FILE
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_dependency_map(directory: str) -> dict[str, list[str]]:
    """Map each model file -> list of table/sql_view names it depends on."""
    output_path = Path(directory)
    deps: dict[str, list[str]] = {}
    for model_file in sorted(output_path.glob("*.model.tml")):
        try:
            tml = yaml.safe_load(model_file.read_text(encoding="utf-8"))
            if not isinstance(tml, dict) or "model" not in tml:
                continue
            table_names = [
                mt["name"] for mt in (tml["model"].get("model_tables") or [])
                if isinstance(mt, dict) and mt.get("name")
            ]
            deps[model_file.name] = table_names
        except Exception:
            continue
    return deps


def _write_limitations(output_dir: str, registry: dict) -> None:
    """Auto-generate MIGRATION_LIMITATIONS.md from the lock registry."""
    locked = registry.get("locked_objects", {})
    if not locked:
        return

    lines = [
        "# Migration Limitations",
        "",
        "Objects below failed validation with errors that cannot be resolved by",
        "editing TML. They are documented here and excluded from the fix loop.",
        "",
        "| File | Object | Error Code | Reason | Detail |",
        "|---|---|---|---|---|",
    ]
    for filename, entry in sorted(locked.items()):
        obj_name = entry.get("object_name", "—")
        code = entry.get("error_code") or "—"
        reason = entry.get("reason", "—")
        msg = (entry.get("error_message") or "")[:120].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {filename} | {obj_name} | {code} | {reason} | {msg} |")

    path = Path(output_dir) / _LIMITATIONS_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Error classification ────────────────────────────────────────────────────

# Error codes / message patterns that are LOCKED — never attempt to fix.
# These come from the Migrator's known-unfixable list + the design doc.
LOCKED_CODES = {14540, 14516}

# 14537 sub-classification: "invalid identifier" means a wrong column name in
# the SQL query, which is fixable. All other 14537s (permissions, missing
# schema, network) are locked.
_14537_FIXABLE_PATTERNS = [
    re.compile(r"invalid identifier", re.IGNORECASE),
]

LOCKED_PATTERNS = [
    re.compile(r"QUALIFY\b", re.IGNORECASE),
    re.compile(r"LOOKUP\s*\(", re.IGNORECASE),
    re.compile(r"INDEX\s*\(", re.IGNORECASE),
    re.compile(r"\bSIZE\s*\(", re.IGNORECASE),
    re.compile(r"PREVIOUS_VALUE\s*\(", re.IGNORECASE),
]

WARNING_PATTERNS = [
    re.compile(r"Table with id null not found.*Matching with db/schema/dbTable", re.IGNORECASE),
    re.compile(r"id null not found", re.IGNORECASE),
]


def classify_error(error_code: int | None, error_message: str) -> str:
    """Classify a validation error as 'fixable', 'locked', or 'warning'.

    Returns one of: 'fixable', 'locked', 'warning'.
    """
    if error_code == 14537:
        for pat in _14537_FIXABLE_PATTERNS:
            if pat.search(error_message):
                return "fixable"
        return "locked"

    if error_code and error_code in LOCKED_CODES:
        return "locked"

    for pat in WARNING_PATTERNS:
        if pat.search(error_message):
            return "warning"

    for pat in LOCKED_PATTERNS:
        if pat.search(error_message):
            return "locked"

    return "fixable"


# ── Local proofread (invariant lint) ─────────────────────────────────────────

_PROOFREAD_CHECKS = [
    {
        "id": "full_outer",
        "pattern": re.compile(r'"FULL_OUTER"|FULL_OUTER', re.IGNORECASE),
        "message": "FULL_OUTER is invalid — use OUTER",
        "applies_to": {"table", "model", "sql_view"},
    },
    {
        "id": "int_not_int64",
        "pattern": re.compile(r"data_type:\s*INT\b(?!64)"),
        "message": "data_type INT is invalid — use INT64",
        "applies_to": {"table"},
    },
    {
        "id": "case_when_in_formula",
        "pattern": re.compile(r"\bCASE\s+WHEN\b", re.IGNORECASE),
        "message": "CASE WHEN in formula — must be translated to if/then/else",
        "applies_to": {"model"},
    },
    {
        "id": "fqn_in_model_tables",
        "pattern": re.compile(r"fqn:"),
        "message": "fqn: key found — model_tables must not contain fqn",
        "applies_to": {"model"},
    },
    {
        "id": "window_in_model_formula",
        "pattern": re.compile(r"\b(?:cumulative_|moving_)\w+\s*\(", re.IGNORECASE),
        "message": "cumulative_/moving_ function in model formula — these are query-time only",
        "applies_to": {"model"},
    },
    {
        "id": "missing_db_column_properties",
        "pattern": None,
        "message": "Column missing db_column_properties",
        "applies_to": {"table"},
        "custom_check": "_check_db_column_properties",
    },
]


def _detect_tml_type(filepath: Path) -> str:
    name = filepath.name.lower()
    if name.endswith(".model.tml"):
        return "model"
    elif name.endswith(".table.tml"):
        return "table"
    elif name.endswith(".sql_view.tml"):
        return "sql_view"
    return "unknown"


def _check_db_column_properties(filepath: Path, content: str) -> list[dict]:
    """Check that every table column has db_column_properties."""
    errors = []
    try:
        tml = yaml.safe_load(content)
        if not isinstance(tml, dict) or "table" not in tml:
            return errors
        for col in tml["table"].get("columns") or []:
            if not isinstance(col, dict):
                continue
            if "db_column_properties" not in col:
                errors.append({
                    "file": filepath.name,
                    "check_id": "missing_db_column_properties",
                    "message": f"Column '{col.get('name', '?')}' missing db_column_properties",
                    "classification": "fixable",
                })
    except Exception:
        pass
    return errors


def run_proofread(directory: str) -> list[dict]:
    """Run local invariant checks on all TML files. No API calls.

    Returns a list of error dicts:
    [{"file": "...", "check_id": "...", "message": "...", "classification": "fixable"|"locked"|"warning"}]
    """
    output_path = Path(directory)
    errors: list[dict] = []

    for tml_file in sorted(output_path.glob("*.tml")):
        tml_type = _detect_tml_type(tml_file)
        content = tml_file.read_text(encoding="utf-8")

        for check in _PROOFREAD_CHECKS:
            if tml_type not in check["applies_to"]:
                continue

            if check.get("custom_check"):
                if check["custom_check"] == "_check_db_column_properties":
                    errors.extend(_check_db_column_properties(tml_file, content))
                continue

            if check["pattern"] and check["pattern"].search(content):
                errors.append({
                    "file": tml_file.name,
                    "check_id": check["id"],
                    "message": check["message"],
                    "classification": "fixable",
                })

    return errors


# ── Parse API validation response ────────────────────────────────────────────

def parse_validation_response(api_response: list | dict) -> list[dict]:
    """Extract per-object status from the tml/import VALIDATE_ONLY response.

    Returns a list of error dicts with classification:
    [{"index": 0, "status": "ERROR", "error_code": 14537,
      "message": "...", "classification": "fixable"|"locked"|"warning"}]
    """
    items = api_response if isinstance(api_response, list) else [api_response]
    errors: list[dict] = []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        response_block = item.get("response", {})
        status = response_block.get("status", {})
        status_code = status.get("status_code", "")

        if status_code == "OK":
            continue

        error_messages = status.get("error_message", "")
        if isinstance(error_messages, list):
            error_messages = "; ".join(str(m) for m in error_messages)
        elif not isinstance(error_messages, str):
            error_messages = str(error_messages)

        error_code = None
        code_match = re.search(r'\b(\d{4,5})\b', error_messages)
        if code_match:
            error_code = int(code_match.group(1))

        # Also check for error_code in the status block itself
        if not error_code:
            raw_code = status.get("error_code")
            if raw_code and str(raw_code).isdigit():
                error_code = int(raw_code)

        classification = classify_error(error_code, error_messages)

        # Try to identify which file this applies to
        obj_info = response_block.get("object", [])
        obj_name = ""
        if isinstance(obj_info, list) and obj_info:
            header = obj_info[0].get("header", {})
            obj_name = header.get("name", "")

        errors.append({
            "index": item.get("request_index", i),
            "object_name": obj_name,
            "status": status_code,
            "error_code": error_code,
            "message": error_messages,
            "classification": classification,
        })

    return errors


# ── Build TML payload ────────────────────────────────────────────────────────

def build_payload(directory: str) -> list[str]:
    """Build the ordered TML string array: tables → sql_views → models."""
    output_path = Path(directory)
    files = (
        sorted(output_path.glob("*.table.tml"))
        + sorted(output_path.glob("*.sql_view.tml"))
        + sorted(output_path.glob("*.model.tml"))
    )
    return [f.read_text(encoding="utf-8") for f in files]


def build_file_index(directory: str) -> list[str]:
    """Return the ordered file names matching build_payload order."""
    output_path = Path(directory)
    files = (
        sorted(output_path.glob("*.table.tml"))
        + sorted(output_path.glob("*.sql_view.tml"))
        + sorted(output_path.glob("*.model.tml"))
    )
    return [f.name for f in files]


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_validate(directory: str, api_response: list | dict | None = None) -> dict:
    """Run the full validation pipeline.

    Phase 1: Local proofread (always runs).
    Phase 2: Parse API response (if provided — caller handles the API call).
    Phase 3: Lock registry + cascade detection.

    Locked error details are suppressed from the output — Claude only sees
    fixable errors.  Locked errors are auto-documented in
    MIGRATION_LIMITATIONS.md and tracked in _lock_registry.json.

    Returns:
    {
        "status": "VALID" | "INVALID" | "PROOFREAD_FAIL",
        "attempt": int,
        "exhausted": bool,
        "fixable": [...],
        "locked_summary": {"count": N, "files": [...],
                           "documented_in": "MIGRATION_LIMITATIONS.md"},
        "warnings": [...],
        "files": ["file1.table.tml", ...]
    }
    """
    state = _load_state(directory)
    state["attempt"] += 1
    attempt = state["attempt"]
    exhausted = attempt >= HARD_CAP

    # Phase 1: local proofread
    proofread_errors = run_proofread(directory)
    fixable_proofread = [e for e in proofread_errors if e["classification"] == "fixable"]

    if fixable_proofread and api_response is None:
        _save_state(directory, state)
        return {
            "status": "PROOFREAD_FAIL",
            "attempt": attempt,
            "exhausted": exhausted,
            "fixable": fixable_proofread,
            "locked_summary": {"count": 0, "files": [], "documented_in": _LIMITATIONS_FILE},
            "warnings": [],
            "files": build_file_index(directory),
        }

    # Phase 2: parse API response
    api_errors: list[dict] = []
    if api_response is not None:
        file_index = build_file_index(directory)
        api_errors = parse_validation_response(api_response)
        for err in api_errors:
            idx = err.get("index", 0)
            if idx < len(file_index):
                err["file"] = file_index[idx]

    all_errors = proofread_errors + api_errors

    # Phase 3: lock registry + cascade detection
    registry = _load_lock_registry(directory)
    dep_map = _build_dependency_map(directory)

    # Build set of TML object names from locked files
    locked_names: set[str] = set()
    output_path = Path(directory)
    for locked_file in registry.get("locked_objects", {}):
        fpath = output_path / locked_file
        if fpath.exists():
            try:
                locked_tml = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                if isinstance(locked_tml, dict):
                    for key in ("sql_view", "table"):
                        if key in locked_tml and isinstance(locked_tml[key], dict):
                            name = locked_tml[key].get("name", "")
                            if name:
                                locked_names.add(name)
            except Exception:
                pass

    for err in all_errors:
        filename = err.get("file", "")

        # Already in the lock registry from a previous attempt? Force locked.
        if filename in registry.get("locked_objects", {}):
            err["classification"] = "locked"
            continue

        # Cascade: model depends on a locked sql_view
        if err["classification"] == "fixable" and filename.endswith(".model.tml"):
            model_deps = dep_map.get(filename, [])
            if any(d in locked_names for d in model_deps):
                err["classification"] = "locked"

    fixable = [e for e in all_errors if e.get("classification") == "fixable"]
    locked = [e for e in all_errors if e.get("classification") == "locked"]
    warnings = [e for e in all_errors if e.get("classification") == "warning"]

    # Register newly locked objects
    for err in locked:
        filename = err.get("file", "")
        if filename and filename not in registry["locked_objects"]:
            registry["locked_objects"][filename] = {
                "object_name": err.get("object_name", ""),
                "locked_at_attempt": attempt,
                "error_code": err.get("error_code"),
                "error_message": (err.get("message") or "")[:200],
                "reason": (
                    "sql_execution" if err.get("error_code") == 14537
                    else "cascade" if err.get("file", "").endswith(".model.tml")
                    else "pattern_match"
                ),
            }
            if err.get("object_name"):
                locked_names.add(err["object_name"])

    _save_lock_registry(directory, registry)
    _write_limitations(directory, registry)

    if not fixable and not locked:
        status = "VALID"
    else:
        status = "INVALID"

    state["history"].append({
        "attempt": attempt,
        "fixable_count": len(fixable),
        "locked_count": len(locked),
        "warning_count": len(warnings),
    })
    _save_state(directory, state)

    locked_files = sorted({e.get("file", "") for e in locked if e.get("file")})

    return {
        "status": status,
        "attempt": attempt,
        "exhausted": exhausted,
        "fixable": fixable,
        "locked_summary": {
            "count": len(locked),
            "files": locked_files,
            "documented_in": _LIMITATIONS_FILE,
        },
        "warnings": warnings,
        "files": build_file_index(directory),
    }


def reset_attempts(directory: str) -> None:
    """Reset the attempt counter and lock registry (for a fresh validation run)."""
    for fname in (_STATE_FILE, _LOCK_REGISTRY_FILE, _LIMITATIONS_FILE):
        path = Path(directory) / fname
        if path.exists():
            path.unlink()