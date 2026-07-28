"""Per-wave alias assembly for an Org migration -- spec step 7 (pure functions, no I/O).

**Why a wave and not a tenant.** Per-Org aliases live on the *Primary* Org's Model and there
is no delta update until 26.10, so every append re-imports the WHOLE document. Done per
tenant, tenant *k* pays the cost of all *k* before it -- O(N^2) across a fleet -- and past
5 MB each import goes async at 10-15 minutes. So one merge per wave, serialised: two
concurrent full-document writes clobber each other.

**What makes this the one catastrophic step.** The import REPLACES the document. If the
export that fed the merge came back partial, every already-cut-over tenant it omitted loses
its aliases, and those users see `STRING_1` where they saw `Region`. Nothing surfaces it:
each entry in the document is individually valid, the import returns `OK`, and the export
afterwards looks correct. `missing_org_coverage` is what turns "confirm the export was
complete" from an instruction a human is asked to follow by eye into an assertion.

The transform and the overlap rule live in `ts_cli/alias.py` and are reused, not restated.
What is migration-specific is only this: which aliases a migrated tenant needs (the inverse
of the rename the migration just applied), and which Orgs must already be present.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set

from ts_cli.alias import WILDCARD_GROUP, find_scope_overlaps, flatten_columns
from ts_cli.migrate.schema import SET_BLOCKER, ColumnMappingRow

DEFAULT_LOCALE = "en-US"


def translations_from_mapping(rows: Sequence[ColumnMappingRow], org_name: str,
                             locale: str = DEFAULT_LOCALE) -> List[dict]:
    """Alias translations that give a migrated Org its own column names back.

    The alias is the **inverse of the rename**. `apply` rewrote the tenant's content from
    `Segment` to `STRING_1` so it binds to the published Model; this makes `Segment` what
    that Org's users SEE. So `column` is the published name and `alias` is the tenant's.

    Deriving these from the approved `column-mapping.csv` rather than having an operator
    retype them matters: the mapping is the artefact a human already reviewed, and a typo
    here is invisible -- a misspelled `column` silently aliases nothing, and the tenant sees
    the physical name with no error.

    Scope is always `TS_WILDCARD_ALL`. A tenant migration wants every user in the Org to see
    the tenant's names, that IS Org-wide scope, and mixing in a group scope for the same
    column would make both resolve to the base name.

    Skipped rows, and why each is right rather than merely convenient:

    - **Names that already agree.** No alias is needed, and the document is size-bound
      (5 MB async, 25 MB hard), so an entry that changes nothing is not free.
    - **No `published_column`.** An unmapped gap has no target to alias; `apply` refuses
      these, so reaching here means the mapping was edited afterwards.
    - **`SET_BLOCKER`.** The Model cannot be published at all, so there is nothing to alias
      onto.
    """
    out: List[dict] = []
    seen: Set[str] = set()
    for row in rows or ():
        published = (row.published_column or "").strip()
        tenant = (row.tenant_column or "").strip()
        if not published or not tenant or published == tenant:
            continue
        if row.status == SET_BLOCKER:
            continue
        if published in seen:
            continue
        seen.add(published)
        # A provenance description, matching the convention already on the cluster. This
        # document is the one a human may have to audit or rebuild by hand after a partial
        # export, and "why is ORG1 in here" is the question they will be asking.
        out.append({"column": published, "locale": locale, "org": org_name,
                    "group": WILDCARD_GROUP, "alias": tenant,
                    "description": f"{org_name} tenant alias"})
    return out


def orgs_present(columns: Sequence[dict]) -> Set[str]:
    """Org names carrying at least one alias entry in this document."""
    return {org for (_col, _loc, org, _grp) in flatten_columns(list(columns or []))}


def missing_org_coverage(existing_columns: Sequence[dict],
                         expected_orgs: Iterable[str]) -> List[str]:
    """Orgs that must already hold aliases on this Model but are ABSENT from the export.

    **The check that stops the catastrophic case.** A partial export merges into a document
    that then replaces what is on the Model, silently stripping every Org it missed.

    Org coverage rather than a count: a count is satisfiable by the wrong Orgs. Ten aliases
    for one tenant pass a "ten or more" assertion while nine tenants are being wiped. Naming
    the Orgs also makes the refusal actionable -- "ORG3 is missing" says what to go and look
    at, where "expected 40, got 31" does not.
    """
    present = orgs_present(existing_columns)
    return [f"{org}: already cut over, but the alias export returned NO entries for it. "
            f"Merging would drop that Org's aliases on import and its users would see the "
            f"base column names. Re-export before retrying"
            for org in sorted({o for o in expected_orgs if o} - present)]


def _shrink_problem(existing_columns: Sequence[dict],
                    merged_columns: Sequence[dict]) -> List[str]:
    """Refuse a merge that came out SMALLER than what it merged into.

    A merge is additive, so this is unreachable today. It is asserted anyway because the
    consequence is silent alias loss across the whole fleet, and the cost of being wrong
    about "unreachable" is paid by every already-migrated tenant at once.
    """
    before, after = len(flatten_columns(list(existing_columns or []))), \
        len(flatten_columns(list(merged_columns or [])))
    if after >= before:
        return []
    return [f"the merged document has FEWER alias entries than the Model already carries "
            f"({after} < {before}). A merge cannot shrink, so something dropped entries; "
            f"importing would apply that loss"]


def wave_problems(existing_columns: Sequence[dict], merged_columns: Sequence[dict],
                  expected_orgs: Optional[Iterable[str]] = None) -> List[str]:
    """Every reason this wave must not be imported. Empty list means go.

    Returns ALL problems rather than the first: an alias document is assembled once per
    wave, and finding the second fault only after re-running the first fix wastes a
    serialised window that the whole wave is queued behind.
    """
    problems = missing_org_coverage(existing_columns, expected_orgs or ())
    problems += _shrink_problem(existing_columns, merged_columns)
    problems += find_scope_overlaps(merged_columns)
    seen: Set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]
