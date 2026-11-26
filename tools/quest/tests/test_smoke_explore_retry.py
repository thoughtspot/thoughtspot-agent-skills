"""smoke_explore._dump_dom retries a Chrome start that crashed before loading the page, and
nothing else: a run that printed anything, or exited 0, is returned as it is."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import smoke_explore as SX  # noqa: E402


def _cmd(tmp_path, script):
    """A stand-in for Chrome: `script` runs under sh with $N = how many times it has run."""
    counter = tmp_path / "count"
    counter.write_text("0")
    body = f'N=$(( $(cat "{counter}") + 1 )); echo $N > "{counter}"; {script}'
    return ["sh", "-c", body], counter


def test_a_silent_crash_is_retried_once(tmp_path):
    cmd, counter = _cmd(tmp_path, 'if [ $N -eq 1 ]; then exit 134; fi; echo "<html>ok</html>"')
    out = SX._dump_dom(cmd, 10)
    assert out.returncode == 0 and "ok" in out.stdout
    assert counter.read_text().strip() == "2"


def test_a_second_silent_crash_is_returned_not_retried_again(tmp_path):
    cmd, counter = _cmd(tmp_path, "echo dyld >&2; exit 134")
    out = SX._dump_dom(cmd, 10)
    assert out.returncode == 134 and out.stdout == "" and "dyld" in out.stderr
    assert counter.read_text().strip() == "2"


def test_a_failure_that_printed_output_is_not_retried(tmp_path):
    # The page loaded: whatever it shows is the result, never a reason to run it again.
    cmd, counter = _cmd(tmp_path, 'echo "<html>partial</html>"; exit 1')
    out = SX._dump_dom(cmd, 10)
    assert out.returncode == 1 and "partial" in out.stdout
    assert counter.read_text().strip() == "1"


def test_a_clean_exit_with_no_output_is_not_retried(tmp_path):
    cmd, counter = _cmd(tmp_path, "true")
    out = SX._dump_dom(cmd, 10)
    assert out.returncode == 0 and out.stdout == ""
    assert counter.read_text().strip() == "1"
