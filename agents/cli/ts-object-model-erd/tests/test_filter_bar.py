"""The ERD's Show bar and Focus toggles, checked in a real (headless) browser.

The bar is one spec with the audit report's filter bar (ts_cli/audit/report/filter_bar.js):
"Show", an All chip, a toggle chip per table kind with its count, then the search box and
the shown count. Every chip starts on; switching one off HIDES the tables it covers and
their joins, and the diagram is laid out again; All switches every chip back on. RLS
subgraph and Noted only are Focus toggles beside it, which hide every table outside them.
"""
import pytest

from . import browser
from .test_network_view import _fresh

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")


@pytest.fixture(scope="session")
def FULFIL(tmp_path_factory):
    return _fresh("order-fulfilment", tmp_path_factory.mktemp("ex"))


_STATE = """
  function chips(){ return [...document.querySelectorAll('#filter-chips .fbar-chip')].map(b=>
    [b.dataset.f, b.getAttribute('aria-pressed'), b.querySelector('.fbar-count').textContent, b.disabled]); }
  function drawn(){ return [...document.querySelectorAll('#nodes .node:not(.gone)')].length; }
  function drawnEdges(){ return document.querySelectorAll('#edges .edge-g:not(.gone)').length; }
  function pos(){ const m={}; nodes.forEach(n=>m[n.t.id]=[Math.round(n.x),Math.round(n.y)]); return m; }
  function total(){ return document.querySelector('#filter-chips .fbar-total').textContent; }
  function click(f){ document.querySelector('#filter-chips .fbar-chip[data-f="'+f+'"]').click(); }
"""


def test_the_bar_has_the_shared_shape_with_counts(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      const bar=document.getElementById('filter-chips');
      const count=f=>MODEL.tables.filter(t=>f==='fact'?t.kind==='fact':f==='dim'?t.kind==='dim':
        f==='sql_view'?t.is_sql_view:f==='alias'?!!t.alias_of:!!(t.rls&&t.rls.length)).length;
      return {shape: [...bar.children].map(c=>c.className), label: bar.querySelector('.fbar-label').textContent,
              role: bar.getAttribute('role'), chips: chips(), total: total(),
              expected: ['fact','dim','sql_view','alias','rls'].map(count), tables: MODEL.tables.length,
              focus: [...document.querySelectorAll('.focus-btn')].map(b=>[b.id, b.getAttribute('aria-pressed')])};""",
        tmp_path)
    assert r["shape"] == (["fbar-label", "fbar-chip fbar-all"] + ["fbar-chip"] * 5
                          + ["fbar-search", "fbar-total"])
    assert r["label"] == "Show" and r["role"] == "group"
    assert [c[0] for c in r["chips"]] == ["all", "fact", "dim", "sql_view", "alias", "rls"]
    assert all(c[1] == "true" for c in r["chips"])
    assert [int(c[2]) for c in r["chips"]] == [r["tables"]] + r["expected"]
    assert [c[3] for c in r["chips"][1:]] == [n == 0 for n in r["expected"]]   # none covered: disabled
    assert r["total"] == "%d of %d tables shown" % (r["tables"], r["tables"])
    assert r["focus"] == [["focus-rls", "false"], ["focus-notes", "false"]]


def test_switching_chips_off_hides_tables_and_joins_and_lays_out_again(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      const before={drawn: drawn(), edges: drawnEdges(), pos: pos()};
      const aliases=MODEL.tables.filter(t=>t.alias_of).map(t=>t.id);
      click('alias');
      const noAlias={drawn: drawn(), edges: drawnEdges(), pos: pos(), total: total(), chips: chips(),
        keptJoins: MODEL.joins.filter(j=>!aliases.includes(j.from)&&!aliases.includes(j.to)).length,
        anyAlias: nodes.some(n=>n.t.alias_of)};
      click('dim');
      const two={drawn: drawn(), dims: nodes.some(n=>n.t.kind==='dim'), all: chips()[0][1]};
      click('all');
      return {before, aliases: aliases.length, noAlias, two, back: {drawn: drawn(), edges: drawnEdges(),
        pos: pos(), chips: chips(), total: total()}, tables: MODEL.tables.length};""", tmp_path)
    b, a = r["before"], r["noAlias"]
    assert b["drawn"] == r["tables"]
    assert a["drawn"] == r["tables"] - r["aliases"] and not a["anyAlias"]
    assert a["edges"] == a["keptJoins"] < b["edges"]
    # laid out again: the tables left do not all keep the places they had
    moved = [k for k in a["pos"] if a["pos"][k] != b["pos"][k]]
    assert moved
    assert a["total"] == "%d of %d tables shown" % (a["drawn"], r["tables"])
    assert [c[1] for c in a["chips"] if c[0] in ("all", "fact", "alias")] == ["false", "true", "false"]
    assert r["two"]["dims"] is False and r["two"]["all"] == "false"
    # All switches every chip back on, and the whole model takes its own layout back
    assert r["back"]["drawn"] == r["tables"] and r["back"]["edges"] == b["edges"]
    assert r["back"]["pos"] == b["pos"]
    assert all(c[1] == "true" for c in r["back"]["chips"])


def test_a_hidden_table_asked_for_shows_everything_again(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      const alias=MODEL.tables.find(t=>t.alias_of).id;
      click('alias');
      const hidden=!nodes.some(n=>n.t.id===alias);
      const f=document.getElementById('finder'); f.value=alias; f.dispatchEvent(new Event('change'));
      return {hidden, drawn: drawn(), tables: MODEL.tables.length, selected: selected&&selected.id===alias,
              alias: chips().find(c=>c[0]==='alias')[1]};""", tmp_path)
    assert r["hidden"] is True
    assert r["drawn"] == r["tables"] and r["selected"] is True and r["alias"] == "true"


def test_rls_subgraph_focus_hides_everything_outside_it(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      document.getElementById('focus-rls').click();
      const keep=MODEL.tables.filter(t=>(t.rls&&t.rls.length)||t.in_rls_path).map(t=>t.id).sort();
      const shown=nodes.map(n=>n.t.id).sort();
      const r={pressed: document.getElementById('focus-rls').getAttribute('aria-pressed'), shown, keep,
               drawn: drawn(), panel: document.querySelector('#inspector h2').textContent};
      document.getElementById('back').click();
      r.after=drawn(); r.tables=MODEL.tables.length;
      r.pressedAfter=document.getElementById('focus-rls').getAttribute('aria-pressed');
      return r;""", tmp_path)
    assert r["pressed"] == "true" and r["shown"] == r["keep"] and r["drawn"] == len(r["keep"])
    assert 0 < len(r["keep"]) < r["tables"]
    assert r["panel"] == "Secured subgraph"
    assert r["after"] == r["tables"] and r["pressedAfter"] == "false"


def test_noted_only_shows_noted_tables_and_both_ends_of_noted_joins(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      const t0=MODEL.tables[0].id, j=MODEL.joins.find(x=>x.from!==t0&&x.to!==t0);
      notes[t0]='a note'; notes[j.name]='a join note'; commitNotes();
      const btn=document.getElementById('focus-notes');
      const enabled=!btn.disabled; btn.click();
      return {enabled, shown: nodes.map(n=>n.t.id).sort(), want: [...new Set([t0, j.from, j.to])].sort(),
              pressed: btn.getAttribute('aria-pressed')};""", tmp_path)
    assert r["enabled"] is True and r["pressed"] == "true"
    assert r["shown"] == r["want"]


def test_a_drag_while_filtered_does_not_overwrite_the_saved_layout(FULFIL, tmp_path):
    r = browser.probe(FULFIL, _STATE + """
      click('alias');
      nodes[0].x+=50; captureLayout();
      return {saved: !!savedPos[layoutName], badge: document.getElementById('saved-badge').classList.contains('on')};""",
        tmp_path)
    assert r == {"saved": False, "badge": False}
