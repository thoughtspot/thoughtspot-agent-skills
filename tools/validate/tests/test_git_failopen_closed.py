"""A gate must not go green because git could not run (audit 4.1).

`_git` was written to fix two defects centrally — octal-escaped paths, and a
failing git invocation reading as "nothing to check". The BL-218 migration
closed the first everywhere and left the second live: ten validators still
called `subprocess.run(["git", ...])` directly and used `.stdout` without ever
checking `returncode`. Not a repo, `index.lock` contention, git absent from
PATH — each yields empty stdout, which every one of them interpreted as an empty
file list and reported PASS.

`check_repo_hygiene` was the sharpest case: its local helper was *named* `_git`,
shadowing the module, and passed `check=False` explicitly. That is how a local
copy survived a migration whose whole purpose was removing local copies.

The property pinned here is the one the rubric cares about: a git failure must
not produce exit 0.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from _git import GitEnumerationError, git_paths

#: (validator, extra args needed to make it touch git at all). Several only
#: enumerate under --staged/--base and legitimately pass without one.
VALIDATORS = [
    ("check_file_size", ["--staged"]),
    ("check_module_health", ["--staged"]),
    ("check_open_items", ["--base", "HEAD"]),
    ("check_repo_hygiene", []),
    ("check_patterns", ["--staged"]),
    ("check_skill_context_cost", ["--staged"]),
    ("check_skill_versions", ["--staged"]),
    ("check_yaml", ["--staged"]),
    ("check_slash_command_refs", []),
]


def test_git_paths_raises_outside_a_repo(tmp_path):
    with pytest.raises(GitEnumerationError):
        git_paths(["ls-files"], tmp_path)


@pytest.mark.parametrize("name,extra", VALIDATORS, ids=[v for v, _ in VALIDATORS])
def test_validator_does_not_pass_when_git_cannot_run(name, extra, tmp_path):
    """Point it at a directory that is not a git repo.

    Exit 0 here would mean the gate reported success on a tree it never read.
    A non-zero exit is the requirement; whether that is a clean FAIL line or a
    propagated GitEnumerationError differs per validator today — `check_secrets`
    is the model for the clean form.
    """
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / f"{name}.py"), "--root", str(tmp_path), *extra],
                       capture_output=True, text=True)
    # A DECLARED skip is a legitimate zero — it is the opposite of a silent
    # fail-open. `check_module_health` exits 0 with "SKIP … radon not installed"
    # before it ever reaches git, and the pytest matrix job does not install
    # radon while the `suite` job does. The rule is that a gate must not go
    # green SILENTLY because it could not run.
    if r.returncode == 0 and "SKIP" in r.stdout:
        return

    assert r.returncode != 0, (
        f"{name} reported success on a non-repo:\n{r.stdout[-400:]}")
    # A non-zero exit is necessary but not sufficient: any crash satisfies it.
    # This assertion caught three NameErrors that the returncode check alone
    # passed happily — the failure must be ABOUT git being unable to enumerate.
    blob = (r.stdout + r.stderr).lower()
    assert "gitenumerationerror" in blob or "git" in blob, (
        f"{name} failed, but not because git could not run:\n{r.stderr[-400:]}")
    for wrong in ("nameerror", "attributeerror", "importerror", "typeerror"):
        assert wrong not in blob, (
            f"{name} failed with a {wrong}, not a git enumeration failure:\n"
            f"{r.stderr[-500:]}")


def test_no_validator_still_reads_git_stdout_without_checking():
    """The migration's own rule: no new raw call site.

    Catches a reintroduced `subprocess.run(["git", ...])` whose returncode is
    never inspected — the exact shape this finding was about.
    """
    import re
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for f in sorted(root.glob("check_*.py")):
        s = f.read_text()
        for m in re.finditer(r"subprocess\.run\(\s*\[\s*[\"']git[\"']", s):
            seg = s[m.start():m.start() + 400]
            if "returncode" not in seg and "check=True" not in seg:
                offenders.append(f"{f.name}:{s[:m.start()].count(chr(10)) + 1}")
    assert offenders == [], (
        f"raw git calls that ignore returncode: {offenders}. Use _git.git_paths.")
