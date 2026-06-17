"""Unit tests for check_mapping_currency — anchor parsing + staleness (git-free)."""
from datetime import date

import check_mapping_currency as mc


def _write(tmp_path, body, name="m.md"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_current_anchor_passes(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake — 2026-06 (Cortex GA) -->\n\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 17)) is None


def test_missing_anchor_warns(tmp_path):
    f = _write(tmp_path, "# Title\n\nsome rules\n")
    msg = mc.check_file(f, date(2026, 6, 17))
    assert msg and "no currency anchor" in msg


def test_stale_anchor_warns(tmp_path):
    f = _write(tmp_path, "<!-- currency: tableau — 2025-06 (old) -->\n# Title\n")
    msg = mc.check_file(f, date(2026, 6, 17))
    assert msg and "12 months old" in msg


def test_anchor_just_within_window_passes(tmp_path):
    # exactly STALE_MONTHS (6) old → not yet stale (> is the trigger)
    f = _write(tmp_path, "<!-- currency: databricks — 2025-12 (x) -->\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 1)) is None


def test_hyphen_dash_variant_accepted(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake - 2026-06 (hyphen) -->\n# Title\n")
    assert mc.check_file(f, date(2026, 6, 17)) is None


def test_malformed_date_warns(tmp_path):
    f = _write(tmp_path, "<!-- currency: snowflake — 2026-13 (bad month) -->\n# Title\n")
    # 2026-13 fails the \d{2} month? 13 matches \d{2}; date() raises → malformed branch
    msg = mc.check_file(f, date(2026, 6, 17))
    assert msg and "malformed" in msg


def test_anchor_below_head_window_is_missed(tmp_path):
    # Anchor past line 15 is not seen — enforces "near the top".
    body = "\n".join(["filler"] * 20) + "\n<!-- currency: tableau — 2026-06 (late) -->\n"
    f = _write(tmp_path, body)
    assert mc.check_file(f, date(2026, 6, 17)) is not None


def test_months_between():
    assert mc._months_between(date(2025, 12, 1), date(2026, 6, 1)) == 6
    assert mc._months_between(date(2026, 6, 1), date(2026, 6, 30)) == 0
