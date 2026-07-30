# Backlog (fixture)

Trimmed specimen of the naive "accept both" resolution of PR #356's conflict in
docs/backlog.md. Two `## BL-171` sections. Also preserves the stale `**Target:**`
line that git auto-merged onto the emitters item — Rule 1 does NOT catch that half;
it is here so the fixture records the real shape.

---

## BL-170 -- Live-verify four internal ground-truth conflicts `Tier 2`

**Status:** RESOLVED 2026-07-29.

**Outcome:** four conflicts settled, two follow-on entries filed (BL-171, BL-172).

---

## BL-171 -- Five ts-cli emitters still emit the six non-existent string functions `Tier 1`

**Status:** OPEN.

Five converter emitters still translate a source function to a bare name the
ThoughtSpot formula parser rejects.

**Target:** next live-instance pass on se-thoughtspot; bundle with any converter formula
work that touches these functions.

---

## BL-171 — Bound `ts tml verify-render` per-tile probing on large liveboards `Tier 3`

Raised reviewing #356. On a board with 20+ tiles the per-tile re-probe is sequential
and unbounded.

**Target:** next converter-formula pass. Tier 1 because it produces failed imports today on
five of the six conversion paths.

---

## BL-172 -- `check_formula_catalog.py` silently skips most data rows `Tier 1`

**Status:** OPEN.

**Target:** next validator pass; before BL-171's validator extension.
