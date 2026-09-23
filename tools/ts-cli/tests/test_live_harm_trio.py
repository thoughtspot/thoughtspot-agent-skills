"""Three audit findings that degrade while they wait (13.6a, 13.1, 4.2).

13.6a — `CREATE OR REPLACE SEMANTIC VIEW` without `COPY GRANTS` silently drops
every privilege granted on the view. The skill advertises "updating an existing
Snowflake SV from a changed model" as a first-class flow, which is exactly the
case where grants exist to lose. Verified against the Snowflake reference:
`COPY GRANTS` is the last clause of the statement, and "copies any privileges
granted on the existing semantic view to the new semantic view".

This was logged as 13.8 in `docs/audit/2026-07-11-full.md` and reappeared as
13.6a in 2026-09-22 — it has survived two sweeps.

4.2 — `source ~/.zshenv && ts tml import …` run through `bash -c`. `source` on a
missing file is a hard failure, so TML import breaks on any machine without
`~/.zshenv`: Windows, most Linux, any bash-default shell.
"""
import subprocess
from pathlib import Path

from ts_cli.sv_build_sv import _assemble_ddl


def _ddl(**over):
    args = dict(sv_name="DB.SCH.SV", tables_clause=["orders AS DB.SCH.ORDERS"],
                rel_clause=[], dim_entries=[], metric_entries=[],
                comment_text="c", ca_json="{}")
    args.update(over)
    return _assemble_ddl(**args)


# ── 13.6a — grants must survive a re-run ───────────────────────────────────

def test_ddl_copies_grants():
    """Without this, re-running the converter revokes every grant on the view."""
    assert "COPY GRANTS" in _ddl()


def test_copy_grants_is_the_final_clause():
    """Snowflake puts it last, after comment/extension — verified at the source."""
    ddl = _ddl().rstrip().rstrip(";").rstrip()
    assert ddl.endswith("COPY GRANTS"), ddl[-120:]


def test_ddl_still_ends_with_a_statement_terminator():
    assert _ddl().rstrip().endswith(";")


def test_copy_grants_appears_once():
    assert _ddl().count("COPY GRANTS") == 1


# ── 4.2 — importing must not depend on ~/.zshenv existing ──────────────────

def test_import_command_does_not_source_zshenv():
    """`source` on a missing file is fatal under bash -c, so this broke import
    on every machine without ~/.zshenv.

    Inspects CODE lines only — the comment recording why says the string too.
    """
    src = Path(__file__).resolve().parents[1] / "ts_cli" / "io_helpers.py"
    code = [ln for ln in src.read_text().splitlines()
            if not ln.lstrip().startswith("#")]
    offenders = [ln.strip() for ln in code if "source ~/.zshenv" in ln]
    assert offenders == [], offenders


def test_sourcing_a_missing_file_really_is_fatal():
    """The premise, demonstrated rather than asserted."""
    r = subprocess.run(["bash", "-c", "source /nonexistent/zshenv && echo reached"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "reached" not in r.stdout
