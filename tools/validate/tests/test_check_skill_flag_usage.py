"""Unit tests for check_skill_flag_usage — SKILL.md vs. real typer flag cross-check.

Uses a small synthetic flag_map (no ts_cli import needed) to test scan_text's pure
parsing logic in isolation, plus one integration test that imports the real ts_cli
command tree via build_flag_map to catch a genuinely wrong flag (the audit 11.1 shape:
`ts tml import --file` before --file existed).
"""
from pathlib import Path

import check_skill_flag_usage as fu

FLAG_MAP = {
    ("tml", "import"): {"--file", "--dir", "--policy", "--create-new", "--profile", "-p"},
    ("tml", "export"): {"--fqn", "--associated", "--profile", "-p"},
    ("metadata", "search"): {"--name", "--subtype", "--limit", "-n", "-s", "-l"},
}


def test_flags_unknown_flag_on_known_command():
    text = "```bash\nts tml import --bogus-flag model.tml\n```\n"
    hits = fu.scan_text(text, FLAG_MAP)
    assert hits == [(2, "tml", "import", "--bogus-flag")]


def test_does_not_flag_real_flags():
    text = "```bash\nts tml import --file model.tml --policy ALL_OR_NONE\n```\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_help_flag_always_valid():
    text = "```bash\nts tml export --help\n```\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_unknown_command_is_skipped_not_flagged():
    # "ts tml frobnicate" isn't a real command in FLAG_MAP — out of scope for this
    # validator (command-name typos are a different problem), so no finding at all,
    # even though --whatever isn't a real flag on anything.
    text = "```bash\nts tml frobnicate --whatever\n```\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_placeholder_values_are_not_mistaken_for_flags():
    text = "```bash\nts tml export {guid} --profile {name} --fqn\n```\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_prose_outside_fences_is_never_scanned():
    text = "Run `ts tml import --bogus-flag` to see the bug.\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_chained_segment_after_ampersand():
    text = "```bash\nts tml export {guid} --fqn && ts tml import --bogus-flag\n```\n"
    hits = fu.scan_text(text, FLAG_MAP)
    assert hits == [(2, "tml", "import", "--bogus-flag")]


def test_flags_on_non_ts_command_in_chain_are_ignored():
    # The --root flag belongs to a python3 script, not the preceding ts command —
    # must not be attributed to `ts metadata search`.
    text = "```bash\nts metadata search --name \"%x%\" && python3 script.py --root .\n```\n"
    assert fu.scan_text(text, FLAG_MAP) == []


def test_backslash_line_continuation_is_joined():
    text = (
        "```bash\n"
        "ts tml import \\\n"
        "  --bogus-flag model.tml\n"
        "```\n"
    )
    hits = fu.scan_text(text, FLAG_MAP)
    assert hits == [(2, "tml", "import", "--bogus-flag")]


def test_build_flag_map_finds_real_commands():
    root = Path(__file__).resolve().parents[3]
    flag_map = fu.build_flag_map(root)
    if flag_map is None:
        return  # typer/click not installed in this environment — soft-skip, like main()
    assert ("tml", "import") in flag_map
    assert "--file" in flag_map[("tml", "import")]
    assert "--profile" in flag_map[("tml", "import")]


def test_real_cli_rejects_the_audit_11_1_regression():
    # The historical bug: `ts tml import --file` before --file existed. Confirms the
    # validator would have caught it, using the REAL command tree.
    root = Path(__file__).resolve().parents[3]
    flag_map = fu.build_flag_map(root)
    if flag_map is None:
        return
    text = "```bash\nts tml import --made-up-flag model.tml\n```\n"
    hits = fu.scan_text(text, flag_map)
    assert hits == [(2, "tml", "import", "--made-up-flag")]
