"""ts_cli.dependency — pure TML mutation + backup helpers behind `ts dependency`.

Public entry points re-exported here so callers can do
`from ts_cli.dependency import apply_remove, apply_repoint, backup_filename, ...`
without reaching into the `mutate`/`backup` submodules directly. See those modules'
docstrings for the full extraction rationale (BL-083 PR1, from
`agents/cli/ts-dependency-manager/SKILL.md` Step 7/9/11).
"""
from __future__ import annotations

from ts_cli.dependency.backup import (
    DELETE_ORDER,
    V2_TYPE_MAP,
    backup_filename,
    build_manifest,
    delete_sort_key,
    restore_policy_for,
    rollback_order,
    rollback_sort_key,
)
from ts_cli.dependency.mutate import (
    apply_remove,
    apply_repoint,
    convert_answer_to_table,
    remove_columns_from_answer,
    remove_columns_from_feedback,
    remove_columns_from_model_section,
    remove_columns_from_table_section,
    remove_columns_from_view,
    repoint_answer,
    repoint_model,
    repoint_view,
    sanitize_search_query,
)

__all__ = [
    # backup.py
    "DELETE_ORDER",
    "V2_TYPE_MAP",
    "backup_filename",
    "build_manifest",
    "delete_sort_key",
    "restore_policy_for",
    "rollback_order",
    "rollback_sort_key",
    # mutate.py
    "apply_remove",
    "apply_repoint",
    "convert_answer_to_table",
    "remove_columns_from_answer",
    "remove_columns_from_feedback",
    "remove_columns_from_model_section",
    "remove_columns_from_table_section",
    "remove_columns_from_view",
    "repoint_answer",
    "repoint_model",
    "repoint_view",
    "sanitize_search_query",
]
