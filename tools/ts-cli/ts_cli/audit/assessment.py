"""Assessment profiles — the bar an audit is measured against, in one table.

ts-audit asks the user to choose *Spotter-ready* or *General* (SKILL Step 2b). Until BL-399
the choice was stored and never read: every check ran one fixed set of thresholds, so a
Spotter-ready audit passed descriptions at 80% against a promised 95%. The pass marks
below are the skill's own promise ("descriptions >= 95%, synonyms >= 80%, AI context
required" vs ">= 50%, >= 25%, recommended"); the one rule added to fill the gap is that a
coverage check is HIGH below HALF its pass mark and MEDIUM between that and the pass mark.

`check-catalog.md` describes these rows; change them here, not in the check functions.
"""
from __future__ import annotations

DEFAULT = "general"

ASSESSMENTS = {
    "spotter": {
        "label": "Spotter-ready",
        # coverage checks: pass mark (%), and the severity when below it
        "coverage": {"A1": (95, "graded"), "A2": (80, "graded"), "A6": (80, "graded")},
        # presence checks: severity when absent
        "presence": {"A3": "HIGH", "A4": "HIGH"},
    },
    "general": {
        "label": "General",
        # AI context is "recommended", not required: a gap is advisory (LOW) at any depth
        "coverage": {"A1": (50, "graded"), "A2": (25, "graded"), "A6": (80, "LOW")},
        "presence": {"A3": "MEDIUM", "A4": "MEDIUM"},
    },
}


def normalise(name) -> str:
    """'spotter' / 'Spotter-ready' / 'general' / None -> a key of ASSESSMENTS."""
    key = str(name or DEFAULT).strip().lower()
    key = {"spotter-ready": "spotter", "spotter_ready": "spotter"}.get(key, key)
    if key not in ASSESSMENTS:
        raise ValueError(f"unknown assessment '{name}': use spotter or general")
    return key


def label(name) -> str:
    return ASSESSMENTS[normalise(name)]["label"]


def pass_mark(name, check_id: str) -> float:
    return ASSESSMENTS[normalise(name)]["coverage"][check_id][0]


def coverage_severity(name, check_id: str, pct: float):
    """None when `pct` meets the pass mark; else the finding's severity."""
    mark, mode = ASSESSMENTS[normalise(name)]["coverage"][check_id]
    if pct >= mark:
        return None
    if mode == "graded":
        return "HIGH" if pct < mark / 2 else "MEDIUM"
    return mode


def presence_severity(name, check_id: str) -> str:
    return ASSESSMENTS[normalise(name)]["presence"][check_id]


def threshold(name, check_id: str) -> dict:
    """The Finding.threshold payload. `green` is the pass mark and `yellow` where HIGH
    starts — the keys the report's coverage bar already reads (`f.th.green`, which used to
    fall back to a hard-coded 80)."""
    mark, mode = ASSESSMENTS[normalise(name)]["coverage"][check_id]
    out = {"green": mark, "assessment": label(name)}
    if mode == "graded":
        out["yellow"] = mark / 2
    return out
