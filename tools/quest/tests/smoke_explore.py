"""Smoke-play the explore page in a real headless Chrome: build the site into a temporary folder,
serve it, open explore/#smoke=<realm> and read the page's log. The run must show the realm locked
for a fresh player (when the pack's unlock rule asks it), load its map, talk to every step's object
in order with each gate drawn and solid exactly until its own steps are done (and pushed against
as soon as it can be reached), the decree of a realm of halls shown, kept by Esc and shown again, and
the realm saved as finished.

pytest runs it wherever Chrome is installed (GitHub's ubuntu-latest has it; CI fails without it).
Playwright may take it over later (design §5).
    python3 tools/quest/tests/smoke_explore.py [realm id ...]   (default: every explorable realm)
Chrome is found at $QUEST_CHROME, or the usual install paths. Exits non-zero on any failure."""
from __future__ import annotations

import functools
import html
import http.server
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build as B  # noqa: E402

CHROMES = [os.environ.get("QUEST_CHROME", ""), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           shutil.which("google-chrome") or "", shutil.which("google-chrome-stable") or "", shutil.which("chromium") or ""]


def find_chrome() -> str | None:
    return next((c for c in CHROMES if c and pathlib.Path(c).exists()), None)


def run(realm: str, site: pathlib.Path, port: int, chrome: str, profile: pathlib.Path) -> list[str]:
    url = f"http://127.0.0.1:{port}/{B.Pack(B.DEFAULT_PACK).publish_path}/explore/#smoke={realm}"
    # CI's Ubuntu runners don't allow Chrome's sandbox (user namespaces); the page is our own local build.
    ci = ["--no-sandbox"] if os.environ.get("GITHUB_ACTIONS") == "true" else []
    out = subprocess.run([chrome, "--headless=new", "--enable-unsafe-swiftshader", *ci, f"--user-data-dir={profile}",
                          "--virtual-time-budget=60000", "--dump-dom", url], capture_output=True, text=True, timeout=180)
    m = re.search(r'<pre[^>]*id="log"[^>]*>(.*?)</pre>', out.stdout, re.S)
    return html.unescape(m.group(1)).splitlines() if m else [f"ERROR no log in the page ({out.stderr[-300:]!r})"]


def check(realm: str, log: list[str], data: dict) -> list[str]:
    problems = [line for line in log if line.startswith(("ERROR", "NOGL"))]
    r = next(x for x in data["realms"] if x["id"] == realm)
    if f"MAP {realm}" not in log:
        problems.append(f"the {realm} map never loaded")
    if data["realms"][0]["id"] != realm and data["pack"]["unlock"] == "first_realm_first" and f"LOCKED {realm}" not in log:
        problems.append(f"{realm} was not locked for a fresh player")
    smoke = next((line for line in log if line.startswith(f"SMOKE {realm} ")), None)
    if not smoke:
        return problems + [f"no SMOKE line for {realm}"]
    steps, saved = smoke[len(f"SMOKE {realm} "):].split(" | ")
    want = [f"hall:{h['id']}" for h in r["halls"]] + [f"{e['id']}:{x}" for e in r["encounters"]
                                                       for x in ("merchant", "guide", "compiler", "foe", "reward")]
    got = [re.sub(r"\[gates:[01x]*\]$", "", s) for s in steps.split()]
    if got != want:
        problems.append(f"steps {got} != {want}")
    # Each gate is shut exactly while a step it requires is still ahead (the page logs them in map order).
    tmj = json.loads((B.PACKS / data["pack"]["id"] / "maps" / f"{realm}.tmj").read_text(encoding="utf-8"))
    needs = [str(next((p["value"] for p in o.get("properties", []) if p["name"] == "requires"), "")).split(",")
             for layer in tmj["layers"] if layer["type"] == "objectgroup" for o in layer["objects"] if o["type"] == "gate"]
    for i, s in enumerate(steps.split()):
        m = re.search(r"\[gates:([01x]*)\]$", s)
        seen = m.group(1) if m else ""
        if len(seen) != len(needs):
            problems.append(f"at {want[i] if i < len(want) else s} the page logged {len(seen)} gates, the map has {len(needs)}")
            continue
        for g, req in enumerate(needs):
            shut = any(n.strip() in want[i:] for n in req)
            if seen[g] == "x":
                problems.append(f"at {want[i] if i < len(want) else s} gate {g + 1} is drawn but not solid, or solid but not drawn")
            elif (seen[g] == "1") != shut:
                problems.append(f"at {want[i] if i < len(want) else s} gate {g + 1} is {'shut' if seen[g] == '1' else 'open'}")
    if r["halls"] and f"DECREE {realm}" not in log:
        problems.append(f"the decree of {realm} wasn't shown, kept by Esc and shown again")
    if not (json.loads(saved) or {}).get("done"):
        problems.append(f"{realm} was not saved as finished")
    if f"EXIT {realm}" not in log:
        problems.append(f"the exit of {realm} didn't take the player back to the overworld")
    return problems


def main(argv: list[str]) -> int:
    chrome = find_chrome()
    if not chrome:
        print("no Chrome found; set QUEST_CHROME", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pack = B.Pack(B.DEFAULT_PACK)
        if B.main(["--out", str(tmp / "site" / pack.publish_path / "index.html")]) != 0:
            return 1
        data = json.loads((tmp / "site" / pack.publish_path / "quest.json").read_text(encoding="utf-8"))
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        handler = functools.partial(Quiet, directory=str(tmp / "site"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        failed = 0
        try:
            for realm in argv or data["pack"]["explore_realms"]:
                log = run(realm, tmp / "site", server.server_address[1], chrome, tmp / f"profile-{realm}")
                problems = check(realm, log, data)
                print(f"{realm}: {'OK' if not problems else 'FAIL'}  " + " / ".join(log))
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)
                failed += bool(problems)
        finally:
            server.shutdown()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
