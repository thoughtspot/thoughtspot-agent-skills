"""Share HTML round trips, checked in a real (headless) browser.

A shared file is the original page plus `window.ERD_INITIAL_STATE`. The tests build
the recipient's page the same way: take a fresh render and inject the state the
sender's shareState() produced.
"""
import json
import re

import pytest

from . import browser
from .test_network_view import _fresh

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")


@pytest.fixture(scope="module")
def FULFIL(tmp_path_factory):
    return _fresh("order-fulfilment", tmp_path_factory.mktemp("ex"))


def _with_state(html_path, state, out):
    """The recipient's page: the same file with a baked ERD_INITIAL_STATE."""
    src = open(html_path, encoding="utf-8").read()
    m = re.search(r'<script id="erd-data">.*?</script>', src, re.S)
    assert m, "no erd-data script"
    baked = "<script>window.ERD_INITIAL_STATE = %s;</script>" % json.dumps(state)
    out.write_text(src[:m.end()] + baked + src[m.end():], encoding="utf-8")
    return str(out)


def _two_models(tmp_path, name="two.html"):
    """Two models over the SAME table ids, so a leak between them is visible."""
    import render
    ids = ["X1", "X2", "X3", "X4"]
    def model(name):
        return {"model": {"name": name, "guid": name, "description": ""},
                "tables": [{"id": i, "kind": "dim", "cols": [], "rls": [], "is_sql_view": False,
                            "sql_query": None, "alias_of": None, "in_rls_path": False} for i in ids],
                "joins": [{"from": "X1", "to": i, "name": "X1" + i, "card": "MANY_TO_ONE",
                           "origin": "model", "type": "INNER", "on": ""} for i in ids[1:]],
                "formulas": {}, "findings": []}
    page = tmp_path / name
    render.write_html({"models": [model("A"), model("B")], "index": [], "dropped": []}, str(page))
    return str(page)


_POS = "Object.fromEntries(nodes.map(n=>[n.t.id,{x:Math.round(n.x),y:Math.round(n.y)}]))"


def test_share_from_layered_opens_layered(FULFIL, tmp_path):
    """A file shared from Layered → opens in Layered → with the sender's positions,
    and does not plant layered positions in the recipient's Organic layout."""
    (tmp_path / "s").mkdir()
    state = browser.probe(FULFIL, "setLayout('lr');nodes[0].x+=40;captureLayout();return shareState();",
                          tmp_path / "s")
    assert state["layout"] == "lr"
    (tmp_path / "r").mkdir()
    page = _with_state(FULFIL, state, tmp_path / "r" / "shared.html")
    r = browser.probe(page, """
      return {layoutName, on:[...document.querySelectorAll('#layout-seg button.on')].map(b=>b.dataset.l),
              pos:%s, organic:savedPos.organic||null};""" % _POS, tmp_path / "r")
    assert r["layoutName"] == "lr" and r["on"] == ["lr"]
    assert r["pos"] == state["positions"]
    assert r["organic"] is None


def test_shared_state_belongs_to_its_model(tmp_path):
    """In a multi-model file the baked positions and notes are the shared model's:
    the file opens on that model, and the other model gets neither."""
    two = _two_models(tmp_path)
    (tmp_path / "s").mkdir()
    state = browser.probe(two, """
      const sel=document.getElementById('model-switch');sel.value='1';sel.onchange();
      nodes[0].x+=55;captureLayout();notes['X2']='B only';
      return shareState();""", tmp_path / "s")
    assert state["model"] == "B"
    (tmp_path / "r").mkdir()
    page = _with_state(two, state, tmp_path / "r" / "shared.html")
    r = browser.probe(page, """
      const opened={model:MODEL.model.name, sel:document.getElementById('model-switch').value,
                    pos:%s, note:notes['X2']||null};
      const sel=document.getElementById('model-switch');sel.value='0';sel.onchange();
      return {opened, other:{model:MODEL.model.name, organic:savedPos.organic||null, notes:Object.keys(notes)}};""" % _POS,
        tmp_path / "r")
    assert r["opened"] == {"model": "B", "sel": "1", "pos": state["positions"], "note": "B only"}
    assert r["other"] == {"model": "A", "organic": None, "notes": []}


def test_legacy_shared_state_applies_to_the_first_model_only(tmp_path):
    """A file shared before the state carried a model name still opens with its positions,
    on the model it opens on, and does not leak them into the others."""
    two = _two_models(tmp_path)
    (tmp_path / "s").mkdir()
    pos = browser.probe(two, "nodes[1].x+=70;return %s;" % _POS, tmp_path / "s")
    (tmp_path / "r").mkdir()
    page = _with_state(two, {"positions": pos, "notes": {"X3": "old"}}, tmp_path / "r" / "legacy.html")
    r = browser.probe(page, """
      const first={pos:%s, note:notes['X3']||null};
      const sel=document.getElementById('model-switch');sel.value='1';sel.onchange();
      return {first, other:{organic:savedPos.organic||null, notes:Object.keys(notes)}};""" % _POS, tmp_path / "r")
    assert r["first"] == {"pos": pos, "note": "old"}
    assert r["other"] == {"organic": None, "notes": []}


def test_model_switch_applies_the_current_layout(tmp_path):
    """Switching models while in Layered → lays the new model out Layered →, so the
    highlight, saved-position drags and orthogonal routing all match what is drawn."""
    two = _two_models(tmp_path)
    r = browser.probe(two, """
      setLayout('lr');
      const sel=document.getElementById('model-switch');sel.value='1';sel.onchange();
      const want=getLayout('lr');
      return {layoutName, model:MODEL.model.name,
              placed:nodes.every(n=>n.x===want[n.t.id].x&&n.y===want[n.t.id].y),
              on:[...document.querySelectorAll('#layout-seg button.on')].map(b=>b.dataset.l)};""", tmp_path)
    assert r == {"layoutName": "lr", "model": "B", "placed": True, "on": ["lr"]}
