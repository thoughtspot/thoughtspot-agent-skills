"""ERD data generation for the audit report.

The ERD bundle format (`parse_model`) is defined ONCE in the shared ERD library
(`agents/shared/erd/parser.py`) — the single source of truth consumed by both the
`ts-object-model-erd` skill and this audit embed. This module only *adapts* the
`AuditContext` into that shared parser and layers on audit-specific enrichment
(`ai_analysis`, `ai_instructions`); it does not redefine how a Model is parsed.

`parse_model` is re-exported here so existing callers/tests can keep importing it
from `ts_cli.audit.erd`, but there is exactly one implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

# The shared ERD library lives at <repo>/agents/shared/erd. ts-cli runs editable
# from within the repo (pip install -e tools/ts-cli), so this resolves in dev/CI.
# If it is ever installed outside the repo, the ERD embed degrades gracefully
# (parse_model is None → build_erd_for_audit returns []), mirroring how
# report.py._read_erd_assets() handles a missing shared renderer.
_ERD_DIR = Path(__file__).resolve().parents[4] / "agents" / "shared" / "erd"


def _load_shared_parse_model():
    try:
        spec = importlib.util.spec_from_file_location(
            "_erd_parser", str(_ERD_DIR / "parser.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.parse_model
    except Exception:
        return None


parse_model = _load_shared_parse_model()


def build_erd_for_audit(ctx: Any) -> list:
    """Generate ERD data for all models in the audit context.

    Adapts each model in the AuditContext into the shared parser's input shape,
    then enriches the result with audit-derived AI instructions. Returns a list
    of parsed ERD model dicts, one per ctx.models entry (empty if the shared ERD
    library is unavailable).
    """
    if parse_model is None:
        return []
    results = []
    for model_tml in ctx.models:
        needed: dict = {}
        for mt in (model_tml.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            name = mt.get("name", "")
            t = ctx.tables.get(fqn)
            if not t:
                for k, v in ctx.tables.items():
                    tbl_name = v.get("table", {}).get("name") or v.get("sql_view", {}).get("name")
                    if tbl_name == name or k.endswith("." + name):
                        t = v
                        break
            if t:
                needed[name] = t
        erd = parse_model(model_tml, needed)
        guid = erd["model"]["guid"]
        ai_data = ctx.ai_instructions.get(guid, {})
        instructions = []
        for info in (ai_data.get("nl_instructions_info") or []):
            instructions.extend(info.get("instructions") or [])
        if instructions:
            erd["model"]["ai_instructions"] = instructions
        results.append(erd)
    return results
