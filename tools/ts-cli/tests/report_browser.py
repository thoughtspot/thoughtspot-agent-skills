"""Render an audit report HTML in headless Chrome and read back what it shows.

The same approach as agents/cli/ts-object-model-erd/tests/browser.py: the page is
loaded with `--dump-dom`. Two scripts are injected — an error trap at the very top of
<head> (before the report's own script runs, so a throw anywhere in it is recorded) and
a probe after load that writes the JS errors and the visible text of the rendered page
(scripts excluded, so the embedded JSON payload cannot satisfy a text check) into
<pre id="__probe">. Tests skip when no Chrome is installed (`CHROME is None`).
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
  p.textContent=JSON.stringify({errors:window.__errs,text:clone.textContent});
  document.body.appendChild(p);},50);});
</script>"""


def render(html_text: str, tmp_path, route: str = "") -> dict:
    """`{"errors": [...], "text": "..."}` for `html_text` opened at `#route`."""
    head, sep, rest = html_text.partition("<head>")
    assert sep, "no <head> in the report"
    body, sep2, tail = rest.rpartition("</body>")
    assert sep2, "no </body> in the report"
    page = tmp_path / "report_probe.html"
    page.write_text(head + sep + _TRAP + body + _PROBE + sep2 + tail, encoding="utf-8")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--user-data-dir={tmp_path / 'chrome-profile'}", "--window-size=1400,900",
           "--virtual-time-budget=5000", "--dump-dom",
           page.resolve().as_uri() + (f"#{route}" if route else "")]
    dom = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    assert m, f"the page produced no probe output; DOM head: {dom[:300]!r}"
    return json.loads(html.unescape(m.group(1)))
