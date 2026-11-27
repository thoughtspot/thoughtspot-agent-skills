"""Run a JS probe inside a rendered ERD in headless Chrome and return its result.

The probe is appended as a classic <script> after the renderer, so it shares the
renderer's global lexical scope (`nodes`, `MODEL`, `VIEW`, ...). It runs after
load, serialises its return value into <pre id="__probe">, and Chrome's
--dump-dom hands the DOM back. A fresh --user-data-dir per call means empty
localStorage, so every probe starts from a first-visit state.
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

_WRAP = """<script>
window.addEventListener("load",function(){setTimeout(function(){
  var out;try{out=(function(){%s})();}catch(e){out={"__error":String(e&&e.stack||e)};}
  var p=document.createElement("pre");p.id="__probe";p.textContent=JSON.stringify(out);
  document.body.appendChild(p);},50);});
</script>"""


def _shared():
    """The audit tests' Chrome launcher, loaded by path: one copy of the macOS
    code-sign-clone retry (BL-653) for every headless-Chrome test helper."""
    import importlib.util
    import pathlib
    path = (pathlib.Path(__file__).resolve().parents[4]
            / "tools" / "ts-cli" / "tests" / "report_browser.py")
    spec = importlib.util.spec_from_file_location("_report_browser_shared", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def probe(html_path, js_body, tmp_path, hash=""):
    src = open(html_path, encoding="utf-8").read()
    head, sep, tail = src.rpartition("</body>")
    assert sep, "no </body> in %s" % html_path
    page = tmp_path / "probe.html"
    page.write_text(head + (_WRAP % js_body) + sep + tail, encoding="utf-8")
    profile = tmp_path / "chrome-profile"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--user-data-dir=%s" % profile, "--window-size=1400,900",
           "--virtual-time-budget=5000", "--dump-dom",
           page.resolve().as_uri() + (("#" + hash) if hash else "")]
    run = _shared().run_chrome(cmd, timeout=90)
    dom = run.stdout
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    assert m, "probe produced no output; Chrome exit %s after %s launch(es); DOM head: %r; " \
              "stderr tail: %r" % (run.returncode, run.attempts, dom[:500], run.stderr[-600:])
    return json.loads(html.unescape(m.group(1)))
