"""Pre-import TML linter — the model invariants that `--policy VALIDATE_ONLY` does NOT catch.

ThoughtSpot accepts TML that violates these and then behaves wrong (silently drops a
formula, flips a measure to an attribute, breaks a join at query time). Catching them
locally — before import — is the only way to fail loud. Rules mirror invariants I1/I2/I4/I5
in `agents/shared/schemas/ts-model-conversion-invariants.md`.

Pure functions over a parsed TML dict so they are trivially unit-testable.
"""
from __future__ import annotations

from typing import Any


def lint_tml(data: dict) -> list[str]:
    """Return a list of invariant-violation strings for one parsed TML doc. Empty = clean.

    Auto-detects table vs model TML by the top-level key. Only the model invariants
    (I1/I2/I4/I5) plus the guid-placement rule are checked here — these are the ones the
    server's VALIDATE_ONLY policy does not surface.
    """
    if not isinstance(data, dict):
        return ["Top-level TML value must be a mapping"]

    findings: list[str] = []

    # guid must sit at the document root, never nested inside table:/model:.
    for key in ("table", "model"):
        inner = data.get(key)
        if isinstance(inner, dict) and "guid" in inner:
            findings.append(
                f"guid is nested inside '{key}:' — it must be a top-level key "
                f"(sibling of '{key}:'), or omitted on first import."
            )

    model = data.get("model")
    if not isinstance(model, dict):
        return findings  # not a model TML — nothing more to check here

    formulas = model.get("formulas") or []
    columns = model.get("columns") or []
    model_tables = model.get("model_tables") or []

    # I1 — every formulas[] id has a paired columns[] entry (formula_id == id).
    paired = {c.get("formula_id") for c in columns if isinstance(c, dict)}
    for f in formulas:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if fid and fid not in paired:
            findings.append(
                f"I1: formula '{fid}' has no paired columns[] entry "
                f"(formula_id: {fid}) — it will be silently dropped on import."
            )

    # I2 — no aggregation: inside a formulas[] entry (only columns[] may carry it).
    for f in formulas:
        if isinstance(f, dict) and isinstance(f.get("properties"), dict) and "aggregation" in f["properties"]:
            findings.append(
                f"I2: formula '{f.get('id', '?')}' has an aggregation: under formulas[] — "
                f"raises 'FORMULA is not a valid aggregation type'. Move it to the columns[] entry."
            )

    # I4 — model_tables[].id (when present) must equal name exactly (case included).
    for t in model_tables:
        if isinstance(t, dict) and "id" in t and t.get("id") != t.get("name"):
            findings.append(
                f"I4: model_tables id '{t.get('id')}' != name '{t.get('name')}' — "
                f"joins silently fail at query time ('{t.get('name')} does not exist in schema')."
            )

    # I5 — a physical-column columns[] entry must not use aggregation: COUNT_DISTINCT
    # (it silently flips column_type MEASURE → ATTRIBUTE; use a `unique count(...)` formula).
    for c in columns:
        if not isinstance(c, dict) or "formula_id" in c:
            continue  # formula columns are exempt; this targets physical columns
        props = c.get("properties") or {}
        if isinstance(props, dict) and props.get("aggregation") == "COUNT_DISTINCT":
            findings.append(
                f"I5: column '{c.get('name', '?')}' uses aggregation: COUNT_DISTINCT — "
                f"this flips MEASURE → ATTRIBUTE silently. Use a `unique count(...)` formula instead."
            )

    return findings
