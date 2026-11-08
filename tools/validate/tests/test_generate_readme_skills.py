"""Tests for generate_readme_skills.py: README.md's skills tables are generated
from each SKILL.md's `metadata:` block, and `--check` fails, naming the file, on
drift and on each kind of invalid metadata.

Each test builds a small throwaway repo (two runtime dirs, a README with the
markers) rather than reading the real one, so a failure points at the generator,
not at whichever skill last changed. The marker names and anchors in `_README`
are literals on purpose: they are README.md's contract with the generator, and
renaming one should fail here, not pass silently.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import generate_readme_skills as g

# (runtime, skill, metadata block). Two Conversion converters on one platform and a
# non-converter cover the Conversion sort; Setup has two subcategories.
SKILLS = [
    ("cli", "ts-profile-thoughtspot",
     'metadata:\n  category: Setup\n  subcategory: Credentials\n  summary: "Add ThoughtSpot profiles"\n'),
    ("claude", "ts-profile-snowflake",
     'metadata:\n  category: Setup\n  subcategory: Credentials\n  summary: "Add Snowflake profiles"\n'),
    ("cli", "ts-load-source-data",
     'metadata:\n  category: Setup\n  subcategory: Data\n  summary: "Load CSV data"\n'),
    ("cli", "ts-convert-from-acme",
     'metadata:\n  category: Conversion\n  platform: Acme\n'
     '  coverage: "references/coverage-matrix.md"\n  summary: "Convert Acme into ThoughtSpot"\n'),
    ("cli", "ts-convert-to-acme",
     'metadata:\n  category: Conversion\n  platform: Acme\n'
     '  coverage: "references/coverage-matrix.md"\n  summary: "Convert ThoughtSpot into Acme"\n'),
    ("cli", "ts-link-semantic-layer",
     'metadata:\n  category: Conversion\n  platform: Any semantic layer\n  coverage: none\n'
     '  summary: "**Link, don\'t convert**"\n'),
    ("cli", "ts-object-model-coach",
     'metadata:\n  category: Semantic Authoring\n'
     '  summary: "Coach a Model; see the [guide](references/guide.md) or [docs](https://example.com/x)"\n'),
    ("cli", "ts-audit",
     'metadata:\n  category: "Platform & Governance"\n  summary: "Scan an environment"\n'),
    ("cli", "ts-object-model-agentql-query",
     'metadata:\n  category: Query\n  summary: "Query a Model"\n'),
    ("cli", "ts-recipe-formula-days-acme",
     'metadata:\n  category: Recipes\n  summary: "Business-day formula"\n'),
]

_README = """# Repo

## Skills

The catalog has <!-- BEGIN GENERATED: skills-total -->0 skills<!-- END GENERATED: skills-total -->. Prose.

<!-- BEGIN GENERATED: skills-overview -->
<!-- END GENERATED: skills-overview -->

<a id="setup"></a>
Hand-written Setup intro.

<!-- BEGIN GENERATED: skills-setup -->
<!-- END GENERATED: skills-setup -->

<a id="conversion"></a>
<!-- BEGIN GENERATED: skills-conversion -->
<!-- END GENERATED: skills-conversion -->

<a id="semantic-authoring"></a>
<!-- BEGIN GENERATED: skills-semantic-authoring -->
<!-- END GENERATED: skills-semantic-authoring -->

<a id="platform--governance"></a>
<!-- BEGIN GENERATED: skills-platform-governance -->
<!-- END GENERATED: skills-platform-governance -->

<a id="query"></a>
<!-- BEGIN GENERATED: skills-query -->
<!-- END GENERATED: skills-query -->

<a id="recipes"></a>
<!-- BEGIN GENERATED: skills-recipes -->
<!-- END GENERATED: skills-recipes -->

## Getting Started

Hand-written prose stays exactly as it is.
"""


def _write_skill(root: Path, runtime: str, name: str, meta: str) -> Path:
    d = root / "agents" / runtime / name
    (d / "references").mkdir(parents=True, exist_ok=True)
    (d / "references" / "coverage-matrix.md").write_text("# coverage\n", encoding="utf-8")
    path = d / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: Does a thing.\n{meta}---\n\n# {name}\n",
                    encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A git repo with every skill and the README staged: only tracked skills count."""
    for runtime, name, meta in SKILLS:
        _write_skill(tmp_path, runtime, name, meta)
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    return tmp_path


def _run(root: Path, *args: str) -> int:
    return g.main(["--root", str(root), *args])


def _set_meta(root: Path, name: str, meta: str, runtime: str = "cli") -> str:
    """Replace one skill's metadata block; return its repo-relative SKILL.md path."""
    _write_skill(root, runtime, name, meta)
    return f"agents/{runtime}/{name}/SKILL.md"


def _readme(root: Path) -> str:
    return (root / "README.md").read_text(encoding="utf-8")


# ── the happy path ─────────────────────────────────────────────────────────────


def test_regenerated_tree_passes_check(tree, capsys):
    assert _run(tree, "--check") == 1, "the unfilled skeleton must read as stale"
    assert _run(tree) == 0
    assert _run(tree, "--check") == 0
    assert "PASS" in capsys.readouterr().out
    text = _readme(tree)
    assert "Hand-written Setup intro." in text
    assert text.endswith("## Getting Started\n\nHand-written prose stays exactly as it is.\n")
    assert "The catalog has <!-- BEGIN GENERATED: skills-total -->10 skills across six categories" in text


def test_rendered_rows_counts_and_links(tree):
    assert _run(tree) == 0
    lines = _readme(tree).splitlines()
    assert "| [Setup](#setup) | Nothing else runs until credentials and data exist | 3 |" in lines
    assert "| [Platform & Governance](#platform--governance) | " \
           "Many audiences, one definition, without a copy per tenant | 1 |" in lines
    assert "|---|---|:-:|" in lines
    # The link path comes from the skill's real directory (agents/claude here).
    assert ("| [`ts-profile-snowflake`](agents/claude/ts-profile-snowflake/SKILL.md) "
            "| Add Snowflake profiles | Credentials |") in lines
    # Coverage: a path relative to the skill dir, or an em dash for none.
    assert ("| [`ts-convert-to-acme`](agents/cli/ts-convert-to-acme/SKILL.md) | Convert ThoughtSpot "
            "into Acme | Acme | [coverage](agents/cli/ts-convert-to-acme/references/coverage-matrix.md) |"
            ) in lines
    assert ("| [`ts-link-semantic-layer`](agents/cli/ts-link-semantic-layer/SKILL.md) "
            "| **Link, don't convert** | Any semantic layer | — |") in lines
    # A summary's relative link is rebased onto the repo root; a URL is not touched.
    assert ("| [`ts-object-model-coach`](agents/cli/ts-object-model-coach/SKILL.md) | Coach a Model; see the "
            "[guide](agents/cli/ts-object-model-coach/references/guide.md) or [docs](https://example.com/x) |"
            ) in lines
    assert "| Skill | What it builds |" in lines


def test_row_order_is_the_documented_sort(tree):
    assert _run(tree) == 0
    order = [ln.split("`")[1] for ln in _readme(tree).splitlines() if ln.startswith("| [`")]
    setup = order[:3]
    conversion = order[3:6]
    # Setup: subcategory, then name. Conversion: platform, to- before from-, non-converters last.
    assert setup == ["ts-profile-snowflake", "ts-profile-thoughtspot", "ts-load-source-data"]
    assert conversion == ["ts-convert-to-acme", "ts-convert-from-acme", "ts-link-semantic-layer"]


# ── failure modes ──────────────────────────────────────────────────────────────


def test_drift_fails_check_and_check_writes_nothing(tree, capsys):
    assert _run(tree) == 0
    _set_meta(tree, "ts-audit", 'metadata:\n  category: "Platform & Governance"\n  summary: "Changed"\n')
    before = _readme(tree)
    capsys.readouterr()
    assert _run(tree, "--check") == 1
    out = capsys.readouterr().out
    assert "FAIL  README.md: the skills tables are stale" in out
    assert "+| [`ts-audit`](agents/cli/ts-audit/SKILL.md) | Changed |" in out
    assert _readme(tree) == before


def test_hand_edit_inside_a_generated_block_is_drift(tree):
    assert _run(tree) == 0
    readme = tree / "README.md"
    readme.write_text(_readme(tree).replace("| Query a Model |", "| Query a Model, edited |"),
                      encoding="utf-8")
    assert _run(tree, "--check") == 1


def test_unknown_category_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-audit", 'metadata:\n  category: Misc\n  summary: "Scan"\n')
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: metadata.category 'Misc' is not one of:" in capsys.readouterr().out
    before = _readme(tree)
    assert _run(tree) == 1, "generation must refuse too, not write a README without the skill"
    assert _readme(tree) == before


def test_missing_category_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-audit", 'metadata:\n  summary: "Scan"\n')
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: metadata.category is missing" in capsys.readouterr().out


def test_no_metadata_block_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-audit", "")
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: frontmatter has no `metadata:` mapping" in capsys.readouterr().out


def test_missing_summary_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-object-model-agentql-query", "metadata:\n  category: Query\n")
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: metadata.summary is missing" in capsys.readouterr().out


def test_conversion_row_missing_platform_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-convert-from-acme",
                    'metadata:\n  category: Conversion\n  coverage: none\n  summary: "Convert"\n')
    assert _run(tree, "--check") == 1
    assert (f"FAIL  {rel}: metadata.platform is missing (required for category Conversion)"
            in capsys.readouterr().out)


def test_setup_row_missing_subcategory_fails(tree, capsys):
    rel = _set_meta(tree, "ts-load-source-data", 'metadata:\n  category: Setup\n  summary: "Load"\n')
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: metadata.subcategory is missing" in capsys.readouterr().out


def test_coverage_path_that_does_not_exist_fails(tree, capsys):
    rel = _set_meta(tree, "ts-convert-to-acme",
                    'metadata:\n  category: Conversion\n  platform: Acme\n'
                    '  coverage: "references/nope.md"\n  summary: "Convert"\n')
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: metadata.coverage 'references/nope.md' is not a file" in capsys.readouterr().out


@pytest.mark.parametrize("summary, message", [
    ('"Search | set | remove"', "metadata.summary contains '|'"),
    ('"Line one\\nline two"', "metadata.summary contains a line break"),
    ("|\n    Line one\n    line two", "metadata.summary contains a line break"),
], ids=["pipe", "escaped-newline", "literal-block"])
def test_pipe_or_newline_in_summary_is_refused(tree, capsys, summary, message):
    rel = _set_meta(tree, "ts-object-model-agentql-query",
                    f"metadata:\n  category: Query\n  summary: {summary}\n")
    before = _readme(tree)
    assert _run(tree) == 1
    assert f"FAIL  {rel}: {message}" in capsys.readouterr().out
    assert _readme(tree) == before


def test_invalid_frontmatter_yaml_fails_naming_the_file(tree, capsys):
    rel = _set_meta(tree, "ts-audit", "metadata:\n  category: [unclosed\n")
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: frontmatter is not valid YAML" in capsys.readouterr().out


def test_missing_marker_fails_naming_readme(tree, capsys):
    readme = tree / "README.md"
    readme.write_text(_readme(tree).replace("<!-- END GENERATED: skills-query -->\n", ""),
                      encoding="utf-8")
    assert _run(tree, "--check") == 1
    assert "FAIL  README.md: the GENERATED block 'skills-query' must appear exactly once" \
           in capsys.readouterr().out


def test_missing_anchor_fails_naming_readme(tree, capsys):
    readme = tree / "README.md"
    readme.write_text(_readme(tree).replace('<a id="recipes"></a>\n', ""), encoding="utf-8")
    assert _run(tree, "--check") == 1
    assert 'FAIL  README.md: no <a id="recipes"></a> anchor' in capsys.readouterr().out


# ── tracked skills only ────────────────────────────────────────────────────────


def test_untracked_skill_is_skipped_and_the_same_skill_tracked_fails(tree, capsys):
    """A gitignored wip skill sits on disk in the main checkout by design; it must not
    fail the gate. The moment it is tracked, its missing metadata must."""
    assert _run(tree) == 0
    rel = _set_meta(tree, "ts-object-wip-thing", "")
    assert _run(tree, "--check") == 0, "an untracked skill dir with no metadata must not fail"
    assert "ts-object-wip-thing" not in _readme(tree)
    _git(tree, "add", rel)
    capsys.readouterr()
    assert _run(tree, "--check") == 1
    assert f"FAIL  {rel}: frontmatter has no `metadata:` mapping" in capsys.readouterr().out


def test_not_a_git_repo_fails_rather_than_finding_no_skills(tmp_path, capsys):
    for runtime, name, meta in SKILLS:
        _write_skill(tmp_path, runtime, name, meta)
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    assert _run(tmp_path, "--check") == 1
    assert "FAIL  cannot list tracked SKILL.md files" in capsys.readouterr().out
