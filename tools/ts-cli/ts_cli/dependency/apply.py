"""ts_cli.dependency.apply — pure decision logic behind `ts dependency apply-change`.

BL-083 PR2. This is the deterministic half of the destructive orchestrator that
`agents/cli/ts-dependency-manager/SKILL.md` Step 9 previously re-derived from inline
pseudocode on every run: drift detection (`check_drift` ~910), the target obj_id
derivation (~991), the import/verify outcome matrix (`import_and_verify` ~1259), the
post-import verification body checks (`verify_change_applied` ~1161), the 9c fix
ordering (Step 9 overview ~887), the 9d set-delete consumer guard (~1908), and the
REMOVE_CHART-vs-REMOVE_COLUMN chart-axis-role classification the SKILL's Step 4/6
made by hand (`ts metadata report` does not emit it — see the module note below).

PURE functions only — no network, no filesystem, no `ThoughtSpotClient` import. The
I/O shell that wires these into REST calls (export/get/delete/import) lives in
`ts_cli.commands.dependency` (`apply_change_cmd`). This mirrors the split already
used by `mutate.py`/`backup.py` (pure) vs `commands/dependency.py` (I/O), and by
`snowflake_ops.py`/`spotql_ops.py` elsewhere in the CLI.

Chart-role classification scope (BL-083 PR2 decision, 2026-07-08): the role functions
here (`chart_role_for_answer`, `classify_liveboard_viz_roles`) are self-contained in
this module and consumed by `apply-change` to auto-derive per-viz decisions (the
always-safe default is CONVERT_TO_TABLE; the caller's plan may override per viz).
Surfacing these roles in the `ts metadata report` output so Step 6 can present them
interactively is deferred to a follow-up (open-items.md #22) — `build_report` does not
wire per-dependent chart classification at all today, so that is a larger change than
this destructive orchestrator needs.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ts_cli.dependency.backup import DELETE_ORDER, V2_TYPE_MAP, delete_sort_key

__all__ = [
    "derive_target_obj_id",
    "is_drift",
    "import_outcome",
    "is_success_outcome",
    "verify_remove_applied",
    "verify_repoint_applied",
    "FIX_ORDER",
    "fix_sort_key",
    "sort_fixes",
    "set_delete_decision",
    "chart_role_for_answer",
    "classify_liveboard_viz_roles",
    "v2_type_for",
    # re-exported from backup.py for a single import surface in the command shell
    "DELETE_ORDER",
    "V2_TYPE_MAP",
    "delete_sort_key",
]


# ---------------------------------------------------------------------------
# obj_id derivation (SKILL.md Step 9 ~991)
# ---------------------------------------------------------------------------

def derive_target_obj_id(target_name: str, target_guid: str) -> str:
    """Derive the target obj_id for a REPOINT: `{target_name}-{first 8 of guid}`.

    Matches SKILL.md's `f"{target_name}-{target_guid[:8]}"`. A guid shorter than 8
    chars is used whole (Python slicing tolerates it).
    """
    return f"{target_name}-{target_guid[:8]}"


# ---------------------------------------------------------------------------
# Drift detection (SKILL.md check_drift ~910)
# ---------------------------------------------------------------------------

def is_drift(snapshot: Optional[int], current: Optional[int]) -> bool:
    """Return True if an object drifted since it was scanned in Step 4.

    `snapshot` is `modified_at_scan[guid]`; `current` is the just-re-queried
    `metadata_header.modified`. A falsy snapshot (0/None) means there is nothing to
    compare against — return False (permissive) exactly as SKILL.md's check_drift
    does; a source-not-found case surfaces naturally later in the flow. When both are
    present, drift is a plain inequality.

    Note: this is the PURE comparison only. The I/O shell separately treats a failed
    re-query (network error / deleted object) as drift=True (fail safe) before
    reaching this function.
    """
    if not snapshot:
        return False
    return snapshot != current


# ---------------------------------------------------------------------------
# Import/verify outcome matrix (SKILL.md import_and_verify ~1259)
# ---------------------------------------------------------------------------

def import_outcome(api_ok: bool, verified: bool) -> str:
    """Map (import-API status, post-import verification) to a single outcome.

    The matrix (SKILL.md ~1170) — the ERROR+verified cell is the load-bearing one:
    open-item #15 documents TS returning status_code ERROR while actually applying
    the change, so trusting the API status alone would abort a run that in fact
    succeeded.

      OK    + verified   -> SUCCESS
      ERROR + verified   -> SUCCESS_WITH_WARNING   (TS lied; change applied)
      OK    + not verified -> FAIL_SILENT          (silent rejection — rare)
      ERROR + not verified -> FAIL_VERIFIED        (genuine rejection)
    """
    if api_ok and verified:
        return "SUCCESS"
    if (not api_ok) and verified:
        return "SUCCESS_WITH_WARNING"
    if api_ok and (not verified):
        return "FAIL_SILENT"
    return "FAIL_VERIFIED"


def is_success_outcome(outcome: str) -> bool:
    """True for the two outcomes that mean the change is live (SUCCESS,
    SUCCESS_WITH_WARNING). Used to gate 'proceed to dependents' after the source
    import and to compute the failed-consumer set for the 9d set guard.
    """
    return outcome in ("SUCCESS", "SUCCESS_WITH_WARNING")


# ---------------------------------------------------------------------------
# Post-import verification — pure body checks (SKILL.md verify_change_applied ~1161)
# ---------------------------------------------------------------------------

def verify_remove_applied(body_str: str, cols_to_remove: Iterable[str]) -> Tuple[bool, str]:
    """Confirm none of `cols_to_remove` still appear in a re-exported TML body.

    `body_str` is `json.dumps(exported_tml)` (the caller does the network re-export
    and serialization). Checks the three reference forms SKILL.md checks: the quoted
    display name (`"col"`), the bracketed search-token form (`[col]`), and the
    table-qualified form (`::col`). Returns `(verified, detail)`.
    """
    cols = list(cols_to_remove)
    leftover = [
        c for c in cols
        if (f'"{c}"' in body_str) or (f"[{c}]" in body_str) or (f"::{c}" in body_str)
    ]
    if leftover:
        return False, f"REMOVE not applied — still references: {leftover}"
    return True, f"REMOVE verified — none of {cols} appear in TML"


def verify_repoint_applied(
    body_str: str,
    target_guid: Optional[str],
    target_obj_id: Optional[str],
    column_gap: Iterable[str],
) -> Tuple[bool, str]:
    """Confirm a REPOINT landed: the target (by guid or obj_id) is referenced in the
    re-exported TML body and no `column_gap` column remains.

    Matches SKILL.md's REPOINT verification branch (~1213): the target is 'found' if
    either `target_guid` or `target_obj_id` appears in the body; gap columns are
    checked via the `[col]`/`::col` forms. Returns `(verified, detail)`.
    """
    target_found = False
    if target_guid and target_guid in body_str:
        target_found = True
    if target_obj_id and target_obj_id in body_str:
        target_found = True
    if not target_found and (target_guid or target_obj_id):
        ref = target_obj_id or (target_guid[:8] if target_guid else "?")
        return False, f"REPOINT not applied — target {ref} not in TML"

    gap = list(column_gap)
    if gap:
        still_present = [c for c in gap if (f"[{c}]" in body_str) or (f"::{c}" in body_str)]
        if still_present:
            return False, f"REPOINT partial — gap columns still present: {still_present}"
    return True, "REPOINT verified — target referenced; gap columns absent"


# ---------------------------------------------------------------------------
# 9c fix ordering (SKILL.md Step 9 overview ~887-890)
# ---------------------------------------------------------------------------

# Terminal (leaf) dependents first so a Model's own dependent Views/Answers/Sets
# reflect the fix before the Model itself is rewritten; the source is handled
# separately in 9b (not part of this ordering). Feedback shares its Model's guid and
# is applied just before dependent Models.
FIX_ORDER: Dict[str, int] = {
    "ANSWER": 0,
    "LIVEBOARD": 0,
    "SET": 1,
    "COHORT": 1,
    "VIEW": 2,
    "FEEDBACK": 3,
    "MODEL": 4,
    "WORKSHEET": 4,
}


def fix_sort_key(dep: Dict[str, Any]) -> int:
    """Sort key for the 9c fix loop — `dep["type"]` (case-insensitive) looked up in
    `FIX_ORDER`; unknown types sort last (9)."""
    return FIX_ORDER.get(str(dep.get("type", "")).upper(), 9)


def sort_fixes(deps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `deps` in 9c processing order (stable within a type). Does not mutate."""
    return sorted(deps, key=fix_sort_key)


# ---------------------------------------------------------------------------
# 9d set-delete consumer guard (SKILL.md Step 9d ~1908, Fix #2 2026-04-26)
# ---------------------------------------------------------------------------

def set_delete_decision(
    set_entry: Dict[str, Any],
    failed_fix_guids: Iterable[str],
) -> Tuple[bool, str]:
    """Decide whether a reusable Set may be deleted in 9d.

    A Set is deleted only if EVERY consumer fix in 9c succeeded. If any consumer's
    fix failed, deleting the Set would leave that consumer pointing at a missing Set
    GUID (silent breakage) — skip and let the user investigate. Returns
    `(should_delete, skip_reason)`; `skip_reason` is empty when `should_delete` is
    True.
    """
    consumer_guids = set(set_entry.get("in_use_by", []) or [])
    failed = consumer_guids & set(failed_fix_guids)
    if failed:
        reason = (
            f"skipped — {len(failed)} consumer fix(es) failed in 9c; deleting the Set "
            f"would dangle those consumers. Failed consumer GUIDs: {sorted(failed)}"
        )
        return False, reason
    return True, ""


# ---------------------------------------------------------------------------
# Chart-axis-role classification (BL-083 PR2) — REMOVE_CHART vs REMOVE_COLUMN
# ---------------------------------------------------------------------------

def chart_role_for_answer(answer_dict: Dict[str, Any], cols_to_remove: Iterable[str]) -> str:
    """Classify how removing `cols_to_remove` affects a single Answer body.

    Returns:
      - ``"REMOVE_CHART"`` when the answer is displayed as a chart AND a removed
        column sits on an x or y axis. Stripping an x/y column from an active chart
        leaves an invalid visualization that TS rejects (error 14544), so the viz
        must either be converted to a table or removed — a decision the caller makes.
      - ``"REMOVE_COLUMN"`` otherwise (table-mode answer, chart with the column only
        on a color/size/shape binding, or the column not used on any axis) — the
        column can be stripped in place with no visualization decision needed.

    Only x/y axes trigger REMOVE_CHART; color/size/shape bindings are strippable and
    are handled by `mutate.remove_columns_from_answer`. A table-mode answer never
    triggers REMOVE_CHART even if a stale `axis_configs` entry names the column,
    because an inactive chart config does not cause an import rejection.
    """
    cols = set(cols_to_remove)
    display_mode = answer_dict.get("display_mode")
    if display_mode == "TABLE_MODE":
        return "REMOVE_COLUMN"
    chart = answer_dict.get("chart", {})
    for axis in chart.get("axis_configs", []):
        for key in ("x", "y"):
            vals = axis.get(key)
            if isinstance(vals, list) and any(c in vals for c in cols):
                return "REMOVE_CHART"
    return "REMOVE_COLUMN"


def classify_liveboard_viz_roles(
    liveboard_dict: Dict[str, Any],
    cols_to_remove: Iterable[str],
    *,
    source_guid: Optional[str] = None,
) -> Dict[str, str]:
    """Classify each Liveboard visualization that references the source.

    Returns `{viz_id: "REMOVE_CHART" | "REMOVE_COLUMN"}` for every visualization
    whose embedded answer references `source_guid` (or every visualization when
    `source_guid` is None). Vizzes not touching the source are omitted. The role is
    computed by `chart_role_for_answer` on each viz's `answer` body. Callers use the
    REMOVE_CHART entries to know which vizzes need a per-viz CONVERT_TO_TABLE-vs-REMOVE
    decision; REMOVE_COLUMN vizzes are stripped in place with no decision.
    """
    cols = list(cols_to_remove)
    roles: Dict[str, str] = {}
    for viz in liveboard_dict.get("visualizations", []):
        answer = viz.get("answer", {})
        tables = answer.get("tables", [])
        targets_source = source_guid is None or any(t.get("fqn") == source_guid for t in tables)
        if not targets_source:
            continue
        roles[viz.get("id", "")] = chart_role_for_answer(answer, cols)
    return roles


# ---------------------------------------------------------------------------
# v2 delete type mapping (reuses backup.V2_TYPE_MAP; SKILL.md v2_type_for ~936)
# ---------------------------------------------------------------------------

def v2_type_for(skill_type: str) -> str:
    """Map a skill type label to the v2 metadata `type` used by delete/get calls.

    Thin wrapper over `backup.V2_TYPE_MAP` with the same default (LOGICAL_TABLE) as
    SKILL.md's `v2_type_for`, so the command shell has a single import surface.
    """
    return V2_TYPE_MAP.get(str(skill_type).upper(), "LOGICAL_TABLE")
