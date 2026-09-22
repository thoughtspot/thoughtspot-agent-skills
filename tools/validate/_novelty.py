"""Single source of truth for "is this value already taken on the base?".

Two validators independently grew the same rule within four days, and the second
copy shipped a bug the first had already fixed. This module exists so a third
copy is never written.

**The defect class.** A resource is allocated as "the next free value" from the
highest existing one — a ts-cli version, a `BL-NNN` id, a lint invariant `I<N>`,
a coverage-matrix row number. Two branches each take the same value, because each
sees only its own copy of the fencepost. Git then merges them **without a
conflict**: either both made the *identical* edit (the version case — same two
lines, same new value) or the two additions land in *different hunks* (the id
case — two entries, two index rows). And the validator passes, because the rule
it enforces is uniqueness or consistency **within one tree**, which a collision
preserves perfectly.

* **BL-274** (#518) — #511 and #512 both shipped ts-cli 0.139.0; then #484 and
  #516 both claimed 0.141.0.
* **BL-279** (#520) — #484 and #516 each defined a *different* item under BL-275.

**Three points, not two.** This is the part a second implementation gets wrong. A
value present on both the branch and the base is normally just something the
branch *inherited*; it is a collision only when the branch **introduced** it,
which absence at the merge base establishes. A two-point comparison flags every
inherited item — most of them — and gets switched off within a day. The converse
matters too: values the base gained that the branch has never seen are ordinary
drift, not a finding.

**Fail, never skip.** A gate that answers "no violations" when it could not read
its base is decorative. `resolve_base` raises rather than returning a sentinel, so
a caller cannot accidentally treat "could not run" as "clean". The repo's own rule
is that a gate must never go green because it could not run
(`.claude/rules/repo-audit.md`).

**Two inherited limits, true of every caller.** Two branches open at once still
both pass, because neither has collided yet — the second is caught when it
updates from `main`, which branch protection's `strict: true` requires before
merge, so that setting is load-bearing. And because reading the base needs git,
callers expose this as an opt-in `--base`: pre-commit and a `git archive` export
have no base ref, and get only the within-tree half of their rules.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class BaseUnavailable(RuntimeError):
    """The base revision could not be resolved or read. Distinct from "found nothing"."""


def _run(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def resolve_base(root: Path, base: str) -> str:
    """The commit sha `base` names. Raises BaseUnavailable if it does not resolve."""
    probe = _run(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], root)
    if probe.returncode != 0 or not probe.stdout.strip():
        raise BaseUnavailable(
            f"base revision {base!r} could not be resolved. This rule needs the "
            f"base ref (CI checks out with fetch-depth: 0). Omit --base for "
            f"pre-commit or a non-git export."
        )
    return probe.stdout.strip()


def merge_base_with_head(root: Path, base: str) -> str:
    """The merge base of `base` and HEAD. Raises BaseUnavailable if there is none."""
    result = _run(["merge-base", base, "HEAD"], root)
    if result.returncode != 0 or not result.stdout.strip():
        raise BaseUnavailable(f"no merge base between {base!r} and HEAD")
    return result.stdout.strip()


def read_at(root: Path, rev: str, rel: str) -> str:
    """File contents at a revision, or "" when the path does not exist there.

    A missing *path* is legitimate — optional files, and files that postdate part
    of history. A missing *revision* is not, and is the caller's job to reject via
    `resolve_base` before calling this.
    """
    result = _run(["show", f"{rev}:{rel}"], root)
    return result.stdout if result.returncode == 0 else ""


def novel_id_collisions(
    head_ids: set[str], merge_base_ids: set[str], base_ids: set[str]
) -> list[str]:
    """Ids this branch INTRODUCES that are already taken on the base, sorted.

    See the three-points note in the module docstring: subtracting the merge base
    first is what separates "the branch allocated this" from "the branch inherited
    this", and it is the whole rule.
    """
    return sorted((head_ids - merge_base_ids) & base_ids)
