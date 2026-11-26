"""report_browser._dump_dom retries a Chrome start that crashed before loading the page,
and nothing else: a run that printed anything, or exited 0, is returned as it is."""
import report_browser


def _cmd(tmp_path, script):
    """A stand-in for Chrome: `script` runs under sh with $N = how many times it has run."""
    counter = tmp_path / "count"
    counter.write_text("0")
    body = f'N=$(( $(cat "{counter}") + 1 )); echo $N > "{counter}"; {script}'
    return ["sh", "-c", body], counter


def test_a_silent_crash_is_retried_once(tmp_path):
    cmd, counter = _cmd(tmp_path, 'if [ $N -eq 1 ]; then exit 134; fi; echo "<html>ok</html>"')
    run = report_browser._dump_dom(cmd, 10)
    assert run.returncode == 0 and "ok" in run.stdout
    assert counter.read_text().strip() == "2"


def test_a_second_silent_crash_is_returned_not_retried_again(tmp_path):
    cmd, counter = _cmd(tmp_path, "echo dyld >&2; exit 134")
    run = report_browser._dump_dom(cmd, 10)
    assert run.returncode == 134 and run.stdout == "" and "dyld" in run.stderr
    assert counter.read_text().strip() == "2"


def test_a_failure_that_printed_output_is_not_retried(tmp_path):
    # The page loaded: whatever it shows is the result, never a reason to run it again.
    cmd, counter = _cmd(tmp_path, 'echo "<html>partial</html>"; exit 1')
    run = report_browser._dump_dom(cmd, 10)
    assert run.returncode == 1 and "partial" in run.stdout
    assert counter.read_text().strip() == "1"


def test_a_clean_exit_with_no_output_is_not_retried(tmp_path):
    cmd, counter = _cmd(tmp_path, "true")
    run = report_browser._dump_dom(cmd, 10)
    assert run.returncode == 0 and run.stdout == ""
    assert counter.read_text().strip() == "1"
