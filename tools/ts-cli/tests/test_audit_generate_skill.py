"""The ts-audit skill's catalog-derived sections are generated, so they cannot drift.

`SKILL.md` restated the categories, the profile bars and which rules each catalog file
holds — by hand, so every rule change had to remember to edit it. Those sections are now
named GENERATED blocks rendered from the catalog (`ts_cli.audit.generate_skill`), and
`generate --check` fails when one is stale, exactly as for check-catalog.md.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ts_cli.audit import generate
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.generate_skill import (
    SKILL_BLOCKS, id_ranges, render_named_blocks, skill_blocks,
)

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def blocks():
    return skill_blocks(load_catalog())


def test_id_ranges_compress_runs_and_keep_order():
    assert id_ranges(["A1", "A2", "A3"]) == "A1–A3"
    assert id_ranges(["H1", "H2", "H3", "H4", "H5", "H7", "H8"]) == "H1–H5, H7–H8"
    assert id_ranges(["P11", "P9", "P13", "P14"]) == "P9, P11, P13–P14"
    assert id_ranges(["S5"]) == "S5"
    assert id_ranges([]) == "—"


def test_every_block_is_rendered(blocks):
    assert set(blocks) == set(SKILL_BLOCKS)


def test_category_blocks_come_from_categories_yaml(blocks):
    cat = load_catalog()
    for c in cat.categories.values():
        assert f"| **{c.id}** | {c.label} |" in blocks["categories-table"]
        assert c.label in blocks["angles-overview"] and c.label in blocks["angles-select"]
    assert "X  All angles (A, D, H, P, S)" in blocks["angles-select"]


def test_rules_files_table_lists_active_and_retired_ids(blocks):
    table = blocks["rules-files"]
    assert "| `rules/human.yaml` | H — Human Readiness |" in table
    assert "H6 retired" in table
    assert "S11" in table


def test_profile_block_names_each_profile_and_what_differs(blocks):
    text = blocks["profiles"]
    assert "Spotter-ready" in text and "General" in text and "(default)" in text
    # every rule whose grading differs by profile is listed, with both gradings
    cat = load_catalog()
    for rule in cat.rules.values():
        if rule.status == "active" and rule.profiles:
            assert rule.title in text, rule.id


def test_render_named_blocks_replaces_only_the_marked_text():
    doc = ("before\n<!-- BEGIN GENERATED: x -->\nold\n<!-- END GENERATED: x -->\nafter\n")
    assert render_named_blocks(doc, {"x": "new"}) == (
        "before\n<!-- BEGIN GENERATED: x -->\nnew\n<!-- END GENERATED: x -->\nafter\n")


def test_render_named_blocks_fails_on_a_missing_marker():
    with pytest.raises(ValueError, match="x"):
        render_named_blocks("no markers here\n", {"x": "new"})


def test_shipped_docs_are_current():
    assert generate.check(REPO) == []


def test_check_reports_a_stale_skill(tmp_path):
    for rel in (generate.DOC_REL, generate.SKILL_REL):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / generate.CATALOG_REL, tmp_path / generate.CATALOG_REL)
    assert generate.check(tmp_path) == []
    skill = tmp_path / generate.SKILL_REL
    skill.write_text(skill.read_text().replace("| **A** | AI Readiness |", "| **A** | AI |"))
    problems = generate.check(tmp_path)
    assert len(problems) == 1 and "SKILL.md is stale" in problems[0]
