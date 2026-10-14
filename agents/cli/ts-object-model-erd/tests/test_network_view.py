"""Network view behaviour, checked in a real (headless) browser."""
import os

import pytest

from . import browser

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
NET = "view=network"


def _fresh(name, out_dir):
    """Render an example with the CURRENT renderer. The committed model_erd.html
    embeds whichever renderer was current when it was regenerated, so probing it
    would test old code; test_examples.py separately keeps the committed copy fresh."""
    import build_erd
    ex = os.path.join(EXAMPLES, name)
    out = str(out_dir / (name + ".html"))
    build_erd.build([os.path.join(ex, "tml")], out, log=lambda *_: None,
                    ai_analysis_path=os.path.join(ex, "ai_analysis.json"))
    return out


@pytest.fixture(scope="session")
def FULFIL(tmp_path_factory):
    return _fresh("order-fulfilment", tmp_path_factory.mktemp("ex"))


@pytest.fixture(scope="session")
def SALES(tmp_path_factory):
    return _fresh("sales-inventory", tmp_path_factory.mktemp("ex"))


def test_cards_render_by_default(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      return {nodes: document.querySelectorAll('#nodes .node').length,
              titles: document.querySelectorAll('#nodes .nh, #nodes .node-block-title').length,
              dots: document.querySelectorAll('#nodes circle.dot').length};""", tmp_path)
    assert r == {"nodes": 29, "titles": 29, "dots": 0}


def test_probe_reports_js_errors(SALES, tmp_path):
    r = browser.probe(SALES, "throw new Error('boom');", tmp_path)
    assert "boom" in r["__error"]


def test_network_view_draws_one_dot_per_table(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      return {view: VIEW,
              dots: document.querySelectorAll('#nodes circle.dot').length,
              labels: [...document.querySelectorAll('#nodes .dot-label')].map(e=>e.textContent).sort(),
              cards: document.querySelectorAll('#nodes .nh').length,
              aliasFill: document.querySelector('#nodes .node circle.dot[data-kind="alias"]').getAttribute('fill')};""",
        tmp_path, hash=NET)
    assert r["view"] == "network"
    assert r["dots"] == 29 and r["cards"] == 0
    assert "SALES_REP" in r["labels"] and len(r["labels"]) == 29
    assert r["aliasFill"].upper() == "#7C3AED"


def test_hubs_are_bigger_than_leaves(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      const R=id=>dotR(tableById[id]);
      return {order:R('DM_ORDER'), leaf:R('DELIVERY_DRIVER')};""", tmp_path, hash=NET)
    assert r["order"] > r["leaf"] >= 7


def test_edges_end_on_dot_borders(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      const bad=[];
      edges.forEach(e=>{const G=edgeGeom(e,false);
        [[e.s,G.sp],[e.t,G.tp]].forEach(([n,p])=>{const c=center(n),d=Math.hypot(p.x-c.x,p.y-c.y);
          if(Math.abs(d-n.w/2)>0.5)bad.push([n.t.id,d,n.w/2]);});});
      return {bad, markers:[...document.querySelectorAll('#edges path.edge')].filter(p=>p.getAttribute('marker-end')!=='none').length,
              badges:document.querySelectorAll('#edges text').length};""", tmp_path, hash=NET)
    assert r["bad"] == []
    assert r["markers"] == 0 and r["badges"] == 0


def test_network_labels_do_not_overlap(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      const m=computeNetwork(),ids=Object.keys(m),hits=[];
      const box=id=>{const r=dotR(tableById[id]);return {x:m[id].x,y:m[id].y,w:2*r+6+labelW(tableById[id]),h:Math.max(2*r,16)};};
      for(let i=0;i<ids.length;i++)for(let k=i+1;k<ids.length;k++){const a=box(ids[i]),b=box(ids[k]);
        if(a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h)hits.push([ids[i],ids[k]]);}
      const lens=MODEL.joins.map(j=>{const a=m[j.from],b=m[j.to];return Math.hypot(a.x-b.x,a.y-b.y);}).sort((x,y)=>x-y);
      return {hits, median: lens[lens.length>>1]};""", tmp_path, hash=NET)
    assert r["hits"] == []
    assert 60 <= r["median"] <= 400


def test_network_layout_is_deterministic(FULFIL, tmp_path):
    runs = []
    for sub in ("a", "b"):  # separate Chrome profiles: two genuinely independent page loads
        d = tmp_path / sub
        d.mkdir()
        runs.append(browser.probe(FULFIL, "return computeNetwork();", d, hash=NET))
    assert "__error" not in runs[0]
    assert runs[0] == runs[1]


def test_zero_join_and_single_table_models(tmp_path):
    """Review Focus 2: no joins / one table must give finite positions and a valid fit."""
    import render
    for n_tables in (1, 4):
        tables = [{"id": "T%d" % i, "kind": "dim", "cols": [], "rls": [], "is_sql_view": False,
                   "sql_query": None, "alias_of": None, "in_rls_path": False} for i in range(n_tables)]
        bundle = {"models": [{"model": {"name": "Z%d" % n_tables, "guid": "", "description": ""},
                              "tables": tables, "joins": [], "formulas": {}, "findings": []}],
                  "index": [], "dropped": []}
        d = tmp_path / ("z%d" % n_tables); d.mkdir()
        page = d / "erd.html"; render.write_html(bundle, str(page))
        r = browser.probe(str(page), """
          return {dots: document.querySelectorAll('#nodes circle.dot').length,
                  finite: nodes.every(n=>isFinite(n.x)&&isFinite(n.y)), k: view.k};""", d, hash=NET)
        assert r["dots"] == n_tables and r["finite"] and r["k"] > 0


def test_toggle_disables_card_only_controls_and_round_trips(FULFIL, tmp_path):
    """Spec criteria 2 and 3: switching keeps each view's positions."""
    r = browser.probe(FULFIL, """
      const pos=()=>Object.fromEntries(nodes.map(n=>[n.t.id,[Math.round(n.x),Math.round(n.y)]]));
      const cards0=pos();
      document.querySelector('#view-seg [data-v="network"]').click();
      const dis={layout:[...document.querySelectorAll('#layout-seg button')].every(b=>b.disabled),
                 notation:[...document.querySelectorAll('#notation-seg button')].every(b=>b.disabled),
                 cols:document.getElementById('col-mode').disabled,
                 legend:!document.getElementById('net-legend').hidden};
      const n=nodes[0];n.x+=37;captureLayout();const net0=pos();
      document.querySelector('#view-seg [data-v="cards"]').click();
      const cards1=pos(),enabled=!document.getElementById('col-mode').disabled;
      document.querySelector('#view-seg [data-v="network"]').click();
      return {dis,enabled,cardsKept:JSON.stringify(cards0)===JSON.stringify(cards1),
              netKept:JSON.stringify(net0)===JSON.stringify(pos()),
              stored:localStorage.getItem('ts-erd-view')};""", tmp_path)
    assert all(r["dis"].values()), r["dis"]
    assert r["enabled"] and r["cardsKept"] and r["netKept"]
    assert r["stored"] == "network"


def test_stored_choice_beats_hash_and_hash_is_strict(FULFIL, tmp_path):
    """Review Focus 5: only an exact view=network hash, and only without a stored choice."""
    for h, expect in (("models/foo", "cards"), ("view=networkish", "cards"), ("x&view=network", "network")):
        d = tmp_path / h.replace("/", "_").replace("&", "_"); d.mkdir()
        assert browser.probe(FULFIL, "return VIEW;", d, hash=h) == expect, h
    d = tmp_path / "stored"; d.mkdir()
    r = browser.probe(FULFIL, """
      localStorage.setItem('ts-erd-view','cards');return initialView();""", d, hash="view=network")
    assert r == "cards"


def test_share_state_from_network_bakes_card_positions(FULFIL, tmp_path):
    """Review Focus 1: a file shared from network view must open with card positions."""
    r = browser.probe(FULFIL, """
      const cards=Object.fromEntries(nodes.map(n=>[n.t.id,{x:Math.round(n.x),y:Math.round(n.y)}]));
      setView('network');
      const baked=shareState().positions;
      return {same:JSON.stringify(baked)===JSON.stringify(cards), view:VIEW};""", tmp_path)
    assert r == {"same": True, "view": "network"}


def test_model_switch_in_network_view_relayouts(tmp_path):
    """Review Focus 3: a second model opens in network view with its own layout."""
    import render
    def model(name, ids):
        return {"model": {"name": name, "guid": name, "description": ""},
                "tables": [{"id": i, "kind": "dim", "cols": [], "rls": [], "is_sql_view": False,
                            "sql_query": None, "alias_of": None, "in_rls_path": False} for i in ids],
                "joins": [{"from": ids[0], "to": i, "name": ids[0] + i, "card": "MANY_TO_ONE",
                           "origin": "model", "type": "INNER", "on": ""} for i in ids[1:]],
                "formulas": {}, "findings": []}
    bundle = {"models": [model("A", ["A1", "A2", "A3"]), model("B", ["B1", "B2", "B3", "B4"])],
              "index": [], "dropped": []}
    page = tmp_path / "two.html"; render.write_html(bundle, str(page))
    r = browser.probe(str(page), """
      const sel=document.getElementById('model-switch');sel.value='1';sel.onchange();
      return {view:VIEW, dots:document.querySelectorAll('#nodes circle.dot').length,
              cached:Object.keys(layoutCache.network||{}).sort()};""", tmp_path, hash=NET)
    assert r == {"view": "network", "dots": 4, "cached": ["B1", "B2", "B3", "B4"]}


def test_labels_hide_when_zoomed_far_out(FULFIL, tmp_path):
    r = browser.probe(FULFIL, """
      view.k=0.2;applyView();const far=document.getElementById('viewport').classList.contains('net-far');
      view.k=1;applyView();const near=document.getElementById('viewport').classList.contains('net-far');
      return {far,near};""", tmp_path, hash=NET)
    assert r == {"far": True, "near": False}
