"""Screenshot every map of the explore page in headless Chrome, as a player first sees it: build the
site into a temporary folder, serve it, open explore/#look=<map> for each map, and save
<out>/<map>.png. For reviewing art and map changes; not a test.
    python3 tools/quest/tests/shoot_maps.py <out folder>"""
from __future__ import annotations

import functools
import http.server
import pathlib
import subprocess
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402
import smoke_explore as SX  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    out = pathlib.Path(argv[0]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    chrome = SX.find_chrome()
    if not chrome:
        print("no Chrome found; set QUEST_CHROME", file=sys.stderr)
        return 2
    pack = B.Pack(B.DEFAULT_PACK)
    with tempfile.TemporaryDirectory() as tmp:
        site = pathlib.Path(tmp) / "site"
        if B.main(["--out", str(site / pack.publish_path / "index.html")]) != 0:
            return 1

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for tmj in sorted((site / pack.publish_path / "explore" / "maps").glob("*.tmj")):
                url = f"http://127.0.0.1:{server.server_address[1]}/{pack.publish_path}/explore/#look={tmj.stem}"
                subprocess.run([chrome, "--headless=new", "--enable-unsafe-swiftshader", "--hide-scrollbars",
                                f"--user-data-dir={tmp}/profile-{tmj.stem}", "--virtual-time-budget=4000",
                                "--window-size=1040,620", f"--screenshot={out / (tmj.stem + '.png')}", url],
                               capture_output=True, timeout=120)
                print(out / f"{tmj.stem}.png")
        finally:
            server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
