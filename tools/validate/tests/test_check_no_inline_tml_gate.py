"""Unit tests for check_no_inline_tml_gate — the GATE_RE fingerprint."""
import check_no_inline_tml_gate as g


def test_flags_grep_aggregation_command():
    assert g.GATE_RE.search("grep -nE '^\\s*aggregation:\\s*COUNT_DISTINCT' <file>")
    assert g.GATE_RE.search("    grep -nE '^\\s*aggregation:' <file>  # I2")


def test_does_not_flag_prose_mentions():
    # The I5 bullet legitimately mentions the key in prose — must not match.
    assert not g.GATE_RE.search("- **I5** — no physical-column `aggregation: COUNT_DISTINCT`; use a formula.")
    assert not g.GATE_RE.search("no `aggregation:` inside any `formulas[]` entry")


def test_does_not_flag_ts_tml_lint():
    assert not g.GATE_RE.search("python3 -c \"...\" | ts tml lint")


def test_scan_file_finds_gate(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("intro\n```bash\ngrep -nE '^\\s*aggregation:\\s*COUNT_DISTINCT' x\n```\n")
    hits = g.scan_file(f)
    assert len(hits) == 1 and hits[0][0] == 3


def test_scan_file_clean(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("Use `ts tml lint` to gate the import.\n- **I5** — no `aggregation: COUNT_DISTINCT`\n")
    assert g.scan_file(f) == []
