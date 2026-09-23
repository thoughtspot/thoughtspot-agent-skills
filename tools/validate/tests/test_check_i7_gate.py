"""Unit tests for check_i7_gate — the I7 untranslatable-gate contract.

The validator's value is that it cannot pass a skill whose gate is *nearly* right:
a marker with no reference, a reference in a different part of the file, or a gate
citing some other dialect's mapping. These tests pin each of those.
"""
import check_i7_gate as g


GOOD_GATE = """\
## Step 9 — Classify formulas

> **MANDATORY (I7) — before classifying any metric as untranslatable, open
> [`../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`](../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
> and check the reverse-translation tables. Do not decide from SQL syntax alone.**
> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).

Surface skipped entries to the user.
"""


def write(tmp_path, text, name="SKILL.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── blockquote_runs ─────────────────────────────────────────────────────────

def test_blockquote_runs_groups_contiguous_lines():
    lines = ["intro", "> a", "> b", "", "> c", "tail"]
    runs = g.blockquote_runs(lines)
    assert [start for start, _ in runs] == [2, 5]
    assert runs[0][1] == "> a\n> b"


def test_blockquote_runs_handles_trailing_quote():
    runs = g.blockquote_runs(["x", "> last"])
    assert len(runs) == 1 and runs[0][0] == 2


def test_blockquote_runs_none():
    assert g.blockquote_runs(["plain", "text"]) == []


# ── cited_mapping ───────────────────────────────────────────────────────────

def test_cited_mapping_single():
    text = "see ../../shared/mappings/tableau/tableau-formula-translation.md twice, " \
           "../../shared/mappings/tableau/tableau-formula-translation.md"
    assert g.cited_mapping(text) == "tableau-formula-translation.md"


def test_cited_mapping_ambiguous_returns_none():
    text = ("../../shared/mappings/tableau/tableau-formula-translation.md and "
            "../../shared/mappings/qlik/qlik-thoughtspot-formula-translation.md")
    assert g.cited_mapping(text) is None


def test_cited_mapping_absent_returns_none():
    assert g.cited_mapping("no mapping here") is None


# ── check_skill ─────────────────────────────────────────────────────────────

def test_complete_gate_passes(tmp_path):
    p = write(tmp_path, GOOD_GATE)
    assert g.check_skill(p, tmp_path) == []


def test_missing_gate_fails(tmp_path):
    body = GOOD_GATE.replace("**MANDATORY (I7) — before", "**Before")
    p = write(tmp_path, body)
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    assert "no `MANDATORY (I7)` gate" in problems[0]


def test_gate_without_invariants_reference_fails(tmp_path):
    body = GOOD_GATE.replace(
        "> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).\n", ""
    )
    p = write(tmp_path, body)
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    assert "ts-model-conversion-invariants.md" in problems[0]


def test_marker_and_citation_in_separate_blocks_fails(tmp_path):
    """The whole point: a marker here and a reference there is not a gate."""
    body = (
        "> **MANDATORY (I7) — do not decide from syntax alone.**\n"
        "\n"
        "Later, unrelated:\n"
        "\n"
        "> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7) and\n"
        "> ../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md\n"
    )
    p = write(tmp_path, body)
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    assert "incomplete gate" in problems[0]


def test_gate_citing_wrong_dialect_fails(tmp_path):
    """A gate pointing at a sibling's mapping must not satisfy this skill."""
    body = GOOD_GATE.replace(
        "ts-snowflake/ts-snowflake-formula-translation.md",
        "tableau/tableau-formula-translation.md",
        1,
    )
    p = write(tmp_path, body)
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    # The skill now cites two different mappings, so it is ambiguous, not gated.
    assert "formula-translation" in problems[0]


def test_second_gate_can_satisfy(tmp_path):
    """from-tableau's real shape: an incomplete gate early, a complete one later."""
    body = (
        "> **MANDATORY (I7) — before classifying, open\n"
        "> [`../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`]"
        "(../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)**\n"
        "\n" + GOOD_GATE
    )
    p = write(tmp_path, body)
    assert g.check_skill(p, tmp_path) == []


def test_no_mapping_cited_fails_with_count(tmp_path):
    p = write(tmp_path, "> **MANDATORY (I7)** but nothing to check.\n")
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    assert "cites none" in problems[0]
