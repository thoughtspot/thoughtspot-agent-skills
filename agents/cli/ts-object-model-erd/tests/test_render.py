import os
import re
import sys

HERE = os.path.dirname(__file__)
SKILL_DIR = os.path.dirname(HERE)
SHARED = os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "shared", "erd")
for p in (SKILL_DIR, SHARED):
    if p not in sys.path:
        sys.path.insert(0, p)

import render  # noqa: E402


def _bundle():
    return {"models": [{"model": {"name": "Alpha", "guid": "a", "description": ""},
                        "tables": [], "joins": [], "formulas": {}, "findings": []}],
            "index": [{"name": "Alpha", "guid": "a", "tables": 0, "joins": 0,
                       "findings": 0, "rls": 0}],
            "dropped": []}


def test_render_is_self_contained():
    html = render.render_html(_bundle())
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', html)
    assert "@import" not in html
    assert "cdn" not in html.lower()


def test_render_embeds_model_json():
    html = render.render_html(_bundle())
    assert "__ERD_DATA__" in html
    assert '"name": "Alpha"' in html or '"name":"Alpha"' in html


def test_write_html_creates_file(tmp_path):
    out = str(tmp_path / "erd.html")
    render.write_html(_bundle(), out)
    assert os.path.exists(out)
    assert "<svg" in open(out, encoding="utf-8").read()
