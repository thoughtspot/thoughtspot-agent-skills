"""Unit tests for check_mapping_currency — anchor parsing + staleness (git-free).

check_file returns (kind, msg) | None, kind ∈ {"missing","malformed","stale"}.
Presence failures (missing/malformed) are BLOCKING; staleness is a soft nudge.
"""
from datetime import date

import check_mapping_currency as mc


def _write(tmp_path, body, name="m.md"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_current_anchor_passes(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake — 2026-06 (Cortex GA) -->\n\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 17)) is None


def test_missing_anchor_is_blocking(tmp_path):
    f = _write(tmp_path, "# Title\n\nsome rules\n")
    res = mc.check_file(f, date(2026, 6, 17))
    assert res and res[0] == "missing" and "no currency anchor" in res[1]
    assert res[0] in mc.BLOCKING_KINDS


def test_stale_anchor_is_soft_nudge(tmp_path):
    f = _write(tmp_path, "<!-- currency: tableau — 2025-06 (old) -->\n# Title\n")
    res = mc.check_file(f, date(2026, 6, 17))
    assert res and res[0] == "stale" and "12 months old" in res[1]
    assert res[0] not in mc.BLOCKING_KINDS  # staleness never blocks


def test_anchor_just_within_window_passes(tmp_path):
    f = _write(tmp_path, "<!-- currency: databricks — 2025-12 (x) -->\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 1)) is None


def test_hyphen_dash_variant_accepted(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake - 2026-06 (hyphen) -->\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 17)) is None


def test_malformed_date_is_blocking(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake — 2026-13 (bad month) -->\n# Title\n")
    res = mc.check_file(f, date(2026, 6, 17))
    assert res and res[0] == "malformed" and res[0] in mc.BLOCKING_KINDS


def test_anchor_below_head_window_is_missed(tmp_path):
    body = "\n".join(["filler"] * 20) + "\n<!-- currency: tableau — 2026-06 (late) -->\n"
    f = _write(tmp_path, body)
    res = mc.check_file(f, date(2026, 6, 17))
    assert res and res[0] == "missing"


def test_anchored_dirs_cover_schemas(tmp_path):
    assert mc._is_anchored_path("agents/shared/schemas/snowflake-schema.md")
    assert mc._is_anchored_path("agents/shared/mappings/tableau/x.md")
    assert not mc._is_anchored_path("agents/cli/foo/SKILL.md")
    assert not mc._is_anchored_path("agents/shared/schemas/notes.txt")


def test_months_between():
    assert mc._months_between(date(2025, 12, 1), date(2026, 6, 1)) == 6
    assert mc._months_between(date(2026, 6, 1), date(2026, 6, 30)) == 0
