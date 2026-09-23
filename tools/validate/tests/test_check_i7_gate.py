"""Unit tests for check_i7_gate — the I7 untranslatable-gate contract.

The validator's value is that it cannot pass a skill whose gate is *nearly* right.
Several of these are regression tests for ways the first cut of this validator was
shown to be foolable in adversarial review: a marker inside a fenced example, inside
an HTML comment, parked in the Changelog, or citing a sibling dialect's mapping.
"""
import check_i7_gate as g


MAPPING = "ts-snowflake/ts-snowflake-formula-translation.md"

GATE = f"""\
> **MANDATORY (I7) — before classifying any metric as untranslatable, open
> [`../../shared/mappings/{MAPPING}`](../../shared/mappings/{MAPPING})
> and check the reverse-translation tables. Do not decide from SQL syntax alone.**
> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).
"""

GOOD = f"## Step 9 — Classify formulas\n\n{GATE}\nSurface skipped entries.\n"


def make_repo(tmp_path, body, skill="ts-convert-from-snowflake-sv", runtime="cli",
              dialects=("ts-snowflake", "tableau")):
    """A minimal repo tree: one converter plus the shared mappings it resolves against."""
    d = tmp_path / "agents" / runtime / skill
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(body, encoding="utf-8")
    for dialect in dialects:
        m = tmp_path / "agents" / "shared" / "mappings" / dialect
        m.mkdir(parents=True, exist_ok=True)
        (m / f"{dialect}-formula-translation.md").write_text("x", encoding="utf-8")
    return p


# ── helpers ─────────────────────────────────────────────────────────────────

def test_dialect_of_strips_artifact_suffix():
    assert g.dialect_of("ts-convert-from-databricks-mv") == "databricks"
    assert g.dialect_of("ts-convert-to-snowflake-sv") == "snowflake"
    assert g.dialect_of("ts-convert-from-qlik") == "qlik"
    assert g.dialect_of("ts-object-model-erd") is None


def test_mapping_resolves_bare_and_ts_prefixed(tmp_path):
    make_repo(tmp_path, GOOD)
    assert g.mapping_for_dialect(tmp_path, "snowflake") == "ts-snowflake-formula-translation.md"
    assert g.mapping_for_dialect(tmp_path, "tableau") == "tableau-formula-translation.md"
    assert g.mapping_for_dialect(tmp_path, "nonesuch") is None


def test_strip_noncontent_blanks_fences_and_comments_keeping_line_count():
    src = "a\n```\nhidden\n```\nb\n<!--\nalso hidden\n-->\nc"
    out = g.strip_noncontent(src)
    assert len(out.splitlines()) == len(src.splitlines())
    assert "hidden" not in out and "also hidden" not in out
    assert out.splitlines()[0] == "a" and out.splitlines()[4] == "b"


def test_procedure_body_stops_at_changelog():
    assert "row" not in g.procedure_body("steps\n\n## Changelog\n\n| 1.0.0 | row |\n")


def test_blockquote_runs_groups_contiguous_lines():
    runs = g.blockquote_runs(["intro", "> a", "> b", "", "> c"])
    assert [s for s, _ in runs] == [2, 5]
    assert runs[0][1] == "> a\n> b"


# ── the contract ────────────────────────────────────────────────────────────

def test_complete_gate_passes(tmp_path):
    p = make_repo(tmp_path, GOOD)
    assert g.check_skill(p, tmp_path) == []


def test_missing_gate_fails(tmp_path):
    p = make_repo(tmp_path, GOOD.replace("**MANDATORY (I7) — before", "**Before"))
    assert "no `MANDATORY (I7)` gate" in g.check_skill(p, tmp_path)[0]


def test_gate_without_invariants_reference_fails(tmp_path):
    body = GOOD.replace("> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).\n", "")
    p = make_repo(tmp_path, body)
    assert "ts-model-conversion-invariants.md" in g.check_skill(p, tmp_path)[0]


def test_marker_and_citation_in_separate_blocks_fails(tmp_path):
    body = (
        "> **MANDATORY (I7) — do not decide from syntax alone.**\n\nLater:\n\n"
        "> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7) and\n"
        f"> ../../shared/mappings/{MAPPING}\n"
    )
    p = make_repo(tmp_path, body)
    assert "incomplete gate" in g.check_skill(p, tmp_path)[0]


def test_second_gate_can_satisfy(tmp_path):
    """from-tableau's real shape: an incomplete gate early, a complete one later."""
    body = "> **MANDATORY (I7) — partial, no refs**\n\n" + GOOD
    p = make_repo(tmp_path, body)
    assert g.check_skill(p, tmp_path) == []


# ── regressions: attacks that passed the first cut ──────────────────────────

def test_gate_inside_fenced_block_does_not_count(tmp_path):
    """A gate shown as a copy-paste EXAMPLE is not an instruction to the model."""
    p = make_repo(tmp_path, f"Authors should add:\n\n```markdown\n{GATE}```\n")
    assert "no `MANDATORY (I7)` gate" in g.check_skill(p, tmp_path)[0]


def test_gate_inside_html_comment_does_not_count(tmp_path):
    p = make_repo(tmp_path, f"<!--\n{GATE}-->\n")
    assert "no `MANDATORY (I7)` gate" in g.check_skill(p, tmp_path)[0]


def test_gate_only_in_changelog_does_not_count(tmp_path):
    p = make_repo(tmp_path, f"## Step 1\n\nDo things.\n\n## Changelog\n\n{GATE}")
    assert "no `MANDATORY (I7)` gate" in g.check_skill(p, tmp_path)[0]


def test_gate_citing_a_sibling_dialect_fails(tmp_path):
    """The dialect tie: a snowflake converter may not gate on tableau's mapping."""
    body = GOOD.replace(MAPPING, "tableau/tableau-formula-translation.md")
    p = make_repo(tmp_path, body)
    problems = g.check_skill(p, tmp_path)
    assert len(problems) == 1
    assert "does not cite ts-snowflake-formula-translation.md" in problems[0]
    assert "dialect is snowflake" in problems[0]


def test_changelog_citing_another_mapping_is_harmless(tmp_path):
    """A cross-referencing changelog row must not break an otherwise-good skill."""
    body = GOOD + "\n## Changelog\n\n| 1.0.1 | mirrors tableau/tableau-formula-translation.md |\n"
    p = make_repo(tmp_path, body)
    assert g.check_skill(p, tmp_path) == []


def test_unknown_dialect_reports_missing_mapping(tmp_path):
    p = make_repo(tmp_path, GOOD, skill="ts-convert-from-cognos")
    assert "no formula-translation mapping found for dialect 'cognos'" in g.check_skill(p, tmp_path)[0]


def test_empty_scope_is_a_failure(tmp_path, monkeypatch, capsys):
    """A discovered scope that comes back empty must never report success."""
    monkeypatch.setattr(sys_argv := __import__("sys"), "argv",
                        ["check_i7_gate.py", "--root", str(tmp_path)])
    assert g.main() == 1
    assert "empty result" in capsys.readouterr().out
