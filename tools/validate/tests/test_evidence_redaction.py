"""Evidence and run records must not present a substituted name as what actually ran.

Live-verification transcripts, audit and review records, skill reference notes and specs
that record verification runs, and formula-fidelity run records are evidence. When a value
in them had to be removed (a profile, connection, cluster, Org, user or object name), it is
replaced by an explicit `<redacted-…>` marker — never by a plausible neutral name that a
reader would take for the real one. Ordinary docs may use neutral names.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVIDENCE_GLOBS = (
    "tools/formula-fidelity/runs/*.json",
    "docs/superpowers/verification/*.md",
    "docs/audit/*.md",
    "docs/reviews/*.md",
    "docs/superpowers/specs/*.md",            # specs carry GUID-bearing verification rows
    "agents/*/*/references/*.md",             # open-items and verified reference notes
)
# The neutral names used elsewhere in the repo for the removed values.
SUBSTITUTES = re.compile(
    r"\bdev-cluster\b|\bDBX_CONNECTION\b|\bTestOrg\b|Sample Model v3|\buser-[abc]\b"
    r"|\bdirect-query-cluster\b")

# The run records THIS change redacted, and the commit they are compared against. The
# check only applies while a record still carries a redaction marker: a legitimate later
# re-run rewrites the record, drops the marker, and is out of scope.
PRE_REDACTION_BASE = "1a1bee67aeb625582b4f220c845e6080038c222c"
REDACTED_RUN_RECORDS = (
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2.json",
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2-after-fixes.json",
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2-bl364-365.json",
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2-nonansi.json",
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2-nonansi-after-fixes.json",
    "tools/formula-fidelity/runs/2026-10-07-databricks-m2-nonansi-bl364-365.json",
    "tools/formula-fidelity/runs/2026-10-07-probe-quotes-grouping-1.json",
    "tools/formula-fidelity/runs/2026-10-07-probe-quotes-grouping-2.json",
    "tools/formula-fidelity/runs/2026-10-07-probe-quotes-grouping-3.json",
    "tools/formula-fidelity/runs/2026-10-07-probe-tableau-powerbi-forms.json",
)


def _evidence_files():
    for pattern in EVIDENCE_GLOBS:
        yield from sorted(REPO.glob(pattern))


def test_evidence_files_use_redaction_markers_not_substitute_names():
    offenders = [f"{p.relative_to(REPO)}:{n}"
                 for p in _evidence_files()
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if SUBSTITUTES.search(line)]
    assert offenders == [], offenders


def _at_base(rel: str):
    r = subprocess.run(["git", "show", f"{PRE_REDACTION_BASE}:{rel}"], cwd=REPO,
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def _without(d, keys):
    if isinstance(d, dict):
        return {k: _without(v, keys) for k, v in d.items() if k not in keys}
    if isinstance(d, list):
        return [_without(v, keys) for v in d]
    return d


def test_redaction_changed_nothing_but_the_redacted_fields():
    """Integrity of THIS change's redactions: a redacted run record differs from its
    pre-redaction version only in `connection` and `cases_file` — never in
    `cases_sha256`, results or counts."""
    compared = 0
    for rel in REDACTED_RUN_RECORDS:
        p = REPO / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if "<redacted-" not in text and "<outside repo>" not in text:
            continue                                   # re-run since: out of scope
        old = _at_base(rel)
        if old is None:
            continue                                   # shallow clone: base not available
        new = json.loads(p.read_text(encoding="utf-8"))
        keep = {"connection", "cases_file"}
        assert _without(new, keep) == _without(old, keep), rel
        compared += 1
    if compared == 0:
        pytest.skip("pre-redaction base not available")
