"""Render an audit report HTML in headless Chrome and read back what it shows.

The same approach as agents/cli/ts-object-model-erd/tests/browser.py: the page is
loaded with `--dump-dom`. Two scripts are injected — an error trap at the very top of
<head> (before the report's own script runs, so a throw anywhere in it is recorded) and
a probe after load that writes the JS errors and the visible text of the rendered page
(scripts excluded, so the embedded JSON payload cannot satisfy a text check) into
<pre id="__probe">. Tests skip when no Chrome is installed (`CHROME is None`).
`visible` is the shown view's innerText, which leaves out what CSS hides, and `extra`
is whatever an `actions` script stored in `window.__extra`.
"""
import html
import json
import os
import re
import shutil
import subprocess

_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME = (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
          or shutil.which("chromium") or (_MAC if os.path.exists(_MAC) else None))

_TRAP = ('<script>window.__errs=[];window.addEventListener("error",function(e){'
         'window.__errs.push(String(e.message||e));});</script>')
_PROBE = """<script>
window.addEventListener("load",function(){setTimeout(function(){
  var clone=document.body.cloneNode(true);
  Array.prototype.slice.call(clone.querySelectorAll("script,#__probe")).forEach(
    function(n){n.parentNode.removeChild(n);});
  var p=document.createElement("pre");p.id="__probe";
  var view=document.querySelector(".view.active");
  p.textContent=JSON.stringify({errors:window.__errs,text:clone.textContent,
    active:view?view.id:null,active_text:view?view.textContent:"",
    visible:view?view.innerText:"",extra:window.__extra===undefined?null:window.__extra});
  document.body.appendChild(p);},__SETTLE__);});
</script>"""


#: How many times a launch is tried when it dies on the macOS code-sign-clone race.
CLONE_RACE_ATTEMPTS = 3


def is_clone_race(run: subprocess.CompletedProcess) -> bool:
    """True when Chrome died before rendering because macOS ran it from a temporary
    "code-sign clone" of the app bundle that lacked its framework (BL-653). With an
    everyday Chrome open, each headless launch runs from such a clone, which Chrome
    creates and is meant to remove (stale ones pile up); now and then a launch lands in one being removed and dyld
    aborts it. Only that exact signature counts: a launch killed by a signal, with no
    output, whose stderr names a missing library under `code_sign_clone`."""
    err = run.stderr or ""
    return (run.returncode < 0 and not run.stdout
            and "Library not loaded" in err and "code_sign_clone" in err)


def run_chrome(cmd, timeout: int = 120,
               attempts: int = CLONE_RACE_ATTEMPTS) -> subprocess.CompletedProcess:
    """Run headless Chrome, retrying only a launch lost to the code-sign-clone race; any
    other result, a crash included, is returned at once. A hang is never retried (that
    would hide a genuine one): it raises with Chrome's stderr tail, which TimeoutExpired
    alone does not show. The one copy of this rule: the ERD and quest test helpers load
    this file by path rather than keep their own."""
    for attempt in range(1, attempts + 1):
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) \
                else (exc.stderr or "")
            raise RuntimeError(f"headless Chrome hung past {timeout} s (not retried); "
                               f"stderr tail: {err[-600:]!r}") from exc
        run.attempts = attempt
        if not is_clone_race(run):
            return run
    return run


_run_chrome = run_chrome  # the name the tests and callers used first


def render(html_text: str, tmp_path, route: str = "", actions: str = "",
           size: str = "1400,900", settle_ms: int = 50) -> dict:
    """`{"errors": [...], "text": "...", "active": <id of the shown view>, "active_text":
    "...", "visible": "...", "extra": ...}` for `html_text` opened at `#route`. `actions`,
    a script body, runs on load before the probe reads the page (a click, say). `size`
    is the window, "width,height". `settle_ms` is how long after load the probe reads the
    page: raise it when `actions` finish on a timer. Animation frames stop firing soon after
    load under `--virtual-time-budget`, so an animation cannot be waited on here."""
    head, sep, rest = html_text.partition("<head>")
    assert sep, "no <head> in the report"
    body, sep2, tail = rest.rpartition("</body>")
    assert sep2, "no </body> in the report"
    page = tmp_path / "report_probe.html"
    act = (f'<script>window.addEventListener("load",function(){{{actions}}});</script>'
           if actions else "")
    probe = _PROBE.replace("__SETTLE__", str(int(settle_ms)))
    page.write_text(head + sep + _TRAP + body + act + probe + sep2 + tail, encoding="utf-8")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--user-data-dir={tmp_path / 'chrome-profile'}", f"--window-size={size}",
           "--virtual-time-budget=5000", "--dump-dom",
           page.resolve().as_uri() + (f"#{route}" if route else "")]
    run = run_chrome(cmd)
    dom = run.stdout
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    assert m, (f"the page produced no probe output; Chrome exit {run.returncode} after "
               f"{run.attempts} launch(es); "
               f"DOM head: {dom[:300]!r}; stderr tail: {run.stderr[-600:]!r}")
    return json.loads(html.unescape(m.group(1)))
