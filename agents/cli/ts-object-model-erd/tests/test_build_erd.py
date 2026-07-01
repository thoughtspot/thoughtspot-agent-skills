import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import build_erd


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_build_from_fixture_dir(tmp_path):
    out = str(tmp_path / "erd.html")
    result = build_erd.build([FIXTURES], out, log=lambda *_: None)
    assert result == out
    html = open(out, encoding="utf-8").read()
    assert "Mini Sales" in html
    assert "MANY_TO_ONE" in html
