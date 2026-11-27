"""The headless-Chrome helper retries only a launch lost to the macOS code-sign-clone race
(BL-653): killed by a signal, no output, and dyld naming a missing library under
`code_sign_clone`. Anything else, a crash included, is returned at once."""
import subprocess

import report_browser as rb

_RACE = ("dyld[1]: Library not loaded: @executable_path/../Frameworks/Google Chrome "
         "Framework.framework/Versions/1/Google Chrome Framework\n  Referenced from: "
         "/private/var/folders/x/X/com.google.Chrome.code_sign_clone/code_sign_clone.ab/"
         "Google Chrome.app.bundle/Contents/MacOS/Google Chrome\n")


def _done(rc=0, out="", err=""):
    return subprocess.CompletedProcess(["chrome"], rc, out, err)


def _fake(monkeypatch, results):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return results[min(len(calls), len(results)) - 1]
    monkeypatch.setattr(rb.subprocess, "run", run)
    return calls


def test_the_race_signature():
    assert rb.is_clone_race(_done(-6, "", _RACE))


def test_other_failures_are_not_the_race():
    assert not rb.is_clone_race(_done(-6, "", "Segmentation fault"))          # other crash
    assert not rb.is_clone_race(_done(1, "", _RACE))                         # not a signal
    assert not rb.is_clone_race(_done(-6, "<html></html>", _RACE))           # it rendered
    assert not rb.is_clone_race(_done(-6, "", "Library not loaded: libfoo"))  # no clone


def test_a_race_is_retried_until_a_launch_succeeds(monkeypatch):
    calls = _fake(monkeypatch, [_done(-6, "", _RACE), _done(0, "<html>ok</html>")])
    assert rb._run_chrome(["chrome"]).stdout == "<html>ok</html>"
    assert len(calls) == 2


def test_the_retries_stop_at_the_limit(monkeypatch):
    calls = _fake(monkeypatch, [_done(-6, "", _RACE)])
    run = rb._run_chrome(["chrome"])
    assert rb.is_clone_race(run)
    assert len(calls) == rb.CLONE_RACE_ATTEMPTS


def test_any_other_crash_is_not_retried(monkeypatch):
    calls = _fake(monkeypatch, [_done(-11, "", "Segmentation fault")])
    assert rb._run_chrome(["chrome"]).returncode == -11
    assert len(calls) == 1


def test_a_clone_path_without_a_missing_library_is_not_the_race():
    assert not rb.is_clone_race(_done(-6, "", "…/code_sign_clone/… Segmentation fault"))


_PAGE = "<html><head></head><body><p>x</p></body></html>"
_PROBE_DOM = '<html><body><pre id="__probe">{&quot;errors&quot;: []}</pre></body></html>'


def test_render_recovers_from_a_race(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, [_done(-6, "", _RACE), _done(0, _PROBE_DOM)])
    assert rb.render(_PAGE, tmp_path) == {"errors": []}
    assert len(calls) == 2


def test_render_names_the_race_when_every_launch_hits_it(monkeypatch, tmp_path):
    _fake(monkeypatch, [_done(-6, "", _RACE)])
    try:
        rb.render(_PAGE, tmp_path)
    except AssertionError as exc:
        msg = str(exc)
    else:
        raise AssertionError("render passed with no probe output")
    assert "exit -6" in msg and f"after {rb.CLONE_RACE_ATTEMPTS} launch" in msg
    assert "code_sign_clone" in msg


def test_a_hang_is_not_retried_and_shows_stderr(monkeypatch):
    calls = []

    def hang(cmd, **kw):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"], stderr=b"dyld: something stuck")
    monkeypatch.setattr(rb.subprocess, "run", hang)
    try:
        rb.run_chrome(["chrome"], timeout=2)
    except RuntimeError as exc:
        assert "hung past 2 s" in str(exc) and "something stuck" in str(exc)
    else:
        raise AssertionError("a hang returned")
    assert len(calls) == 1
