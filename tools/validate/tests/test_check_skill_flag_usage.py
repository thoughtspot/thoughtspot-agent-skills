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


# ── Positional-argument cross-check (BL-545) ────────────────────────────────────
# `ts tml lint out/*.tml` and `ts tml import out/*.table.tml …` shipped in two
# converter skills although neither command declares a positional argument, so both
# exited 2 ("Got unexpected extra argument(s)") and neither converter had a lint gate.
# The flag check could not see it: the bug was in the tokens that are NOT flags.

CMD_MAP = {
    ("tml", "lint"): fu.CommandSpec(
        flags=frozenset({"--file", "--dir", "--pattern", "--order"}),
        value_opts=frozenset({"--file", "--dir", "--pattern", "--order"}),
        max_positional=0),
    ("tml", "import"): fu.CommandSpec(
        flags=frozenset({"--file", "--dir", "--pattern", "--order", "--policy",
                         "--profile", "-p", "--create-new", "--no-create-new"}),
        value_opts=frozenset({"--file", "--dir", "--pattern", "--order", "--policy",
                              "--profile", "-p"}),
        max_positional=0),
    ("tml", "export"): fu.CommandSpec(
        flags=frozenset({"--fqn", "--profile", "-p"}),
        value_opts=frozenset({"--profile", "-p"}),
        max_positional=None),          # variadic GUIDS
    ("tml", "verify-render"): fu.CommandSpec(
        flags=frozenset({"--profile", "-p"}),
        value_opts=frozenset({"--profile", "-p"}),
        max_positional=1),
}


def _pos(text):
    return fu.scan_positionals(text, CMD_MAP)


def test_positional_old_powerbi_lint_form_fails():
    hits = _pos("```bash\nts tml lint out/*.tml\n```\n")
    assert hits == [(2, "tml", "lint", ["out/*.tml"], 0)]


def test_positional_old_powerbi_import_form_fails():
    text = ("```bash\n"
            "ts tml import out/*.table.tml out/*.model.tml --profile <name> "
            "--policy VALIDATE_ONLY\n```\n")
    assert _pos(text) == [(2, "tml", "import", ["out/*.table.tml", "out/*.model.tml"], 0)]


def test_positional_fixed_forms_pass():
    text = ("```bash\n"
            "ts tml lint --dir out/ --pattern '*.tml'\n"
            "ts tml import --dir out/ --pattern '*.table.tml' --pattern '*.model.tml' "
            "--order tableau --profile <name> --policy VALIDATE_ONLY\n"
            "ts tml import --file out/table.<T>.tml --file out/model.<M>.tml --profile <name>\n"
            "ts tml lint --dir=out/ --pattern=\"*.liveboard.tml\"\n"
            "```\n")
    assert _pos(text) == []


def test_positional_legitimate_positional_commands_pass():
    text = ("```bash\n"
            "ts tml export {guid} --profile {name} --fqn\n"
            "ts tml export <guid-1> <guid-2> <guid-3> --fqn\n"
            "ts tml verify-render <liveboard-guid> --profile <name>   # REQUIRED gate\n"
            "```\n")
    assert _pos(text) == []


def test_positional_too_many_for_a_single_argument_fails():
    text = "```bash\nts tml verify-render <guid-a> <guid-b>\n```\n"
    assert _pos(text) == [(2, "tml", "verify-render", ["<guid-a>", "<guid-b>"], 1)]


def test_positional_option_values_are_not_counted():
    # A value-taking option consumes the next token, even when the value is
    # quoted with spaces or written inside an optional [...] group.
    text = ("```bash\n"
            "ts tml import --profile \"My Staging\" [--policy ALL_OR_NONE] --create-new "
            "--dir out/\n```\n")
    assert _pos(text) == []


def test_positional_choice_braces_are_not_arguments():
    # `{--a|--b}` is split at the `|` by the chain splitter, leaving `{--a` behind;
    # it is the flag, not a positional. Seen in from-snowflake-sv / from-databricks-mv.
    spec = fu.CommandSpec(flags=frozenset({"--on", "--no-on", "--profile"}),
                          value_opts=frozenset({"--profile"}), max_positional=0)
    text = "```bash\nts x build {--on|--no-on} --profile {profile}\n```\n"
    assert fu.scan_positionals(text, {("x", "build"): spec}) == []


def test_positional_comments_redirections_and_ellipses_are_not_arguments():
    text = ("```bash\n"
            "ts tml lint --dir out/   # pre-import: flags any blank chart tile\n"
            "ts tml lint --dir out/ > lint.json 2>&1\n"
            "ts tml import --dir out/ --order tableau …\n"
            "ts tml import --dir out/ ...\n"
            "```\n")
    assert _pos(text) == []


def test_positional_unknown_flag_stops_the_walk():
    # The flag check reports --bogus; its arity is unknown, so the positional walk
    # must not guess whether `x` was its value.
    assert _pos("```bash\nts tml lint --bogus x\n```\n") == []


def test_positional_unparseable_segment_is_skipped():
    for seg in ("ts tml lint \"unbalanced", "ts tml lint $(ls out/*.tml)",
                "ts tml lint `ls out`"):
        assert _pos(f"```bash\n{seg}\n```\n") == [], seg


def test_positional_prose_and_unknown_commands_are_ignored():
    text = ("Run `ts tml lint out/*.tml` in prose.\n"
            "```bash\nts tml frobnicate a b c\n```\n")
    assert _pos(text) == []


def test_positional_end_of_options_marker():
    assert _pos("```bash\nts tml lint -- --dir\n```\n") == [(2, "tml", "lint", ["--dir"], 0)]


def test_real_cli_positional_check_bl_545():
    # Against the REAL command tree: the two forms BL-545 found fail, the fixed forms
    # and a genuinely positional command pass.
    root = Path(__file__).resolve().parents[3]
    cmd_map = fu.build_command_map(root)
    if cmd_map is None:
        return  # typer not installed in this environment — soft-skip, like main()
    bad = ("```bash\n"
           "ts tml lint out/*.tml\n"
           "ts tml import out/*.table.tml out/*.model.tml --profile <name> --policy VALIDATE_ONLY\n"
           "```\n")
    assert [(h[1], h[2], h[3]) for h in fu.scan_positionals(bad, cmd_map)] == [
        ("tml", "lint", ["out/*.tml"]),
        ("tml", "import", ["out/*.table.tml", "out/*.model.tml"]),
    ]
    good = ("```bash\n"
            "ts tml lint --dir out/ --pattern '*.tml'\n"
            "ts tml import --dir out/ --pattern '*.table.tml' --pattern '*.model.tml' "
            "--order tableau --profile <name> --policy VALIDATE_ONLY\n"
            "ts tml export {guid} --profile {name} --fqn --associated\n"
            "ts tml verify-render <liveboard-guid> --profile <name>\n"
            "ts qlik build-model <app.qvf> --connection \"<TS connection>\" --db <DB> "
            "--schema <SCHEMA> --output out/ [--mode offline]\n"
            "```\n")
    assert fu.scan_positionals(good, cmd_map) == []
