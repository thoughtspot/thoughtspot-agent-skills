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
