# tools/ts-cli/tests/test_check_skill_cli_usage.py
"""Unit tests for tools/validate/check_skill_cli_usage.py's payload-assembly guard
(Task 10, Phase 4 — ts-convert-from-tableau SKILL.md Steps 6/7/11 rewire).

The validator lives outside the ts-cli package (tools/validate/), so it's loaded
via importlib rather than a normal import. Covers the PAYLOAD_ASSEMBLY_RE branch
added alongside FORMULA_ASSEMBLY_RE: a `json.dumps([open(f)...` heredoc must be
flagged, while a plain read-wrapper one-liner (the legitimate stdin-JSON pattern)
must not.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "cscu", Path(__file__).resolve().parents[3] / "tools/validate/check_skill_cli_usage.py")
cscu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cscu)


def test_flags_payload_assembly_heredoc(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("Build payload:\n\n```bash\npython3 - <<'PY'\n"
                 "import json, glob\nprint(json.dumps([open(x).read() for x in glob.glob('*.tml')]))\nPY\n```\n")
    assert cscu.scan_file(f)  # non-empty -> flagged


def test_read_wrapper_not_flagged(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text('```bash\npython3 -c "import json,pathlib; print(1)"\n```\n')
    assert cscu.scan_file(f) == []
