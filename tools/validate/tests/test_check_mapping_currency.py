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


# ---------------------------------------------------------------------------
# Upstream drift — the half that age alone cannot see.
# ---------------------------------------------------------------------------

class TestUpstreamDrift:
    """An anchor citing `<repo> @ <sha>` records a commit nothing used to check.

    `docs/ossie/*` sat anchored at `apache/ossie @ b5da5d6` while upstream ran 55
    commits ahead -- 14 of them touching `core-spec/`, including the one-document
    format change (#383) and the OSSIE_SQL_2026 registration (#439) -- and the
    anchor read `2026-08`, so the six-month age test stayed silent and would have
    until February.
    """

    def test_the_upstream_ref_is_parsed_from_an_anchor(self):
        anchor = "<!-- currency: ossie — 2026-08 (apache/ossie @ b5da5d6; core-spec unchanged) -->"
        m = mc.UPSTREAM_REF_RE.search(anchor)
        assert m is not None
        assert m.group("repo") == "apache/ossie"
        assert m.group("sha") == "b5da5d6"

    def test_an_anchor_with_no_upstream_ref_is_ignored(self):
        # Most anchors cite a product, not a commit; they stay age-only.
        assert mc.UPSTREAM_REF_RE.search(
            "<!-- currency: snowflake — 2026-06 (Cortex Analyst GA) -->"
        ) is None

    def test_drift_is_not_checked_unless_asked(self, tmp_path, monkeypatch):
        # Pre-commit must stay offline. If this regresses, every commit made
        # without network starts failing.
        called = []
        monkeypatch.setattr(mc, "upstream_drift", lambda *a, **k: called.append(a) or (99, 99))
        f = tmp_path / "m.md"
        f.write_text(
            "<!-- currency: ossie — %s (apache/ossie @ deadbee) -->\n# x\n"
            % date.today().strftime("%Y-%m"),
            encoding="utf-8",
        )
        assert mc.check_file(f, date.today()) is None
        assert called == [], "upstream was contacted without --check-upstream"

    def test_drift_on_a_watched_path_nudges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mc, "upstream_drift", lambda *a, **k: (55, 14))
        f = tmp_path / "m.md"
        f.write_text(
            "<!-- currency: ossie — %s (apache/ossie @ b5da5d6) -->\n# x\n"
            % date.today().strftime("%Y-%m"),
            encoding="utf-8",
        )
        result = mc.check_file(f, date.today(), check_upstream=True)
        assert result is not None
        kind, message = result
        assert kind == "drifted"
        assert "14" in message and "55" in message

    def test_drift_that_misses_every_watched_path_is_silent(self, tmp_path, monkeypatch):
        # 55 commits of converter work do not make a spec anchor stale. Counting
        # raw commits would cry wolf on every upstream merge.
        monkeypatch.setattr(mc, "upstream_drift", lambda *a, **k: (55, 0))
        f = tmp_path / "m.md"
        f.write_text(
            "<!-- currency: ossie — %s (apache/ossie @ b5da5d6) -->\n# x\n"
            % date.today().strftime("%Y-%m"),
            encoding="utf-8",
        )
        assert mc.check_file(f, date.today(), check_upstream=True) is None

    def test_an_unreachable_upstream_says_so_rather_than_passing(self, tmp_path, monkeypatch):
        # Offline must not read as "no drift" -- that is the failure this whole
        # change exists to correct, and it would be ironic to reintroduce it here.
        monkeypatch.setattr(mc, "upstream_drift", lambda *a, **k: None)
        f = tmp_path / "m.md"
        f.write_text(
            "<!-- currency: ossie — %s (apache/ossie @ b5da5d6) -->\n# x\n"
            % date.today().strftime("%Y-%m"),
            encoding="utf-8",
        )
        result = mc.check_file(f, date.today(), check_upstream=True)
        assert result is not None and result[0] == "unknown"

    def test_neither_drifted_nor_unknown_blocks_a_commit(self):
        # Only presence failures block. External state cannot gate a PR.
        assert "drifted" not in mc.BLOCKING_KINDS
        assert "unknown" not in mc.BLOCKING_KINDS
