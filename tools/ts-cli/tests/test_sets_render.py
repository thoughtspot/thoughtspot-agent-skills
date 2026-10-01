"""`ts_cli.sets.render` — review lists, Markdown and self-contained HTML."""
from ts_cli.sets.render import render_html, render_markdown, review_lists


def _grant(name, prov, ptype="USER", perm="READ_ONLY"):
    return {"principal_id": f"id-{name}", "principal_name": name, "principal_type": ptype,
            "permission": perm, "provenance": prov}


def _set(name="Basket", cls="REVIEW_DELETE", grants=None, guid="s1"):
    return {"guid": guid, "name": name, "class": cls, "reason": "r", "target": None,
            "cohort_type": "ADVANCED", "anchor_column": "col-guid-1", "author": "pin",
            "dependents": [], "liveboards": {},
            "grants": grants or [_grant("pin", "DIRECT", perm="MODIFY")]}


def _inv(set_name="Basket", grants=None, cls="REVIEW_DELETE", notes=(), top_notes=()):
    return {"schema": "ts-sets-inventory/1", "generated_at": "2026-10-01T00:00:00+00:00",
            "profile": "se", "scope": {}, "notes": list(top_notes),
            "summary": {"models": 1, "models_incomplete": 0, "sets": 1,
                        "by_class": {cls: 1}, "unexplained_grants": 0},
            "orgs": [{"org": "Primary", "notes": list(notes), "models": [
                {"guid": "m1", "name": "Dunder", "discovery": "COMPLETE", "set_count": 1,
                 "sets": [_set(set_name, cls, grants)]}]}]}


def test_review_list_never_contains_required():
    g = [_grant("u", "REQUIRED"), _grant("v", "UNEXPLAINED")]
    names = [x["principal_name"] for x in review_lists(_inv(grants=g))["grants"]]
    assert names == ["v"]


def test_review_list_excludes_unknown_and_markdown_counts_it():
    g = [_grant("u", "UNKNOWN"), _grant("w", "UNKNOWN"), _grant("v", "UNEXPLAINED"),
         _grant("x", "EXPLAINED"), _grant("y", "DIRECT")]
    inv = _inv(grants=g)
    assert [x["principal_name"] for x in review_lists(inv)["grants"]] == ["v"]
    md = render_markdown(inv)
    assert "Unknown grants (could not determine)" in md
    # the summary row carries the computed count (2) beside the unexplained count
    row = next(line for line in md.splitlines() if line.startswith("| 1 | 0 | 1 |"))
    assert row.rstrip().endswith("| 2 |")
    assert "Unknown grants (could not determine)" in render_html(inv)


def test_delete_list_only_review_delete():
    assert len(review_lists(_inv())["delete"]) == 1
    assert review_lists(_inv(cls="KEEP_SHARED"))["delete"] == []


def test_names_are_html_escaped():
    html = render_html(_inv(set_name="<script>x</script>"))
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_html_escapes_org_model_and_note_text():
    inv = _inv(notes=[{"kind": "dependents_failed", "object": "<b>o</b>", "detail": "<i>d</i>"}])
    inv["orgs"][0]["org"] = "<org>"
    inv["orgs"][0]["models"][0]["name"] = "<model>"
    html = render_html(inv)
    for raw in ("<org>", "<model>", "<b>o</b>", "<i>d</i>"):
        assert raw not in html


def test_html_is_self_contained():
    html = render_html(_inv())
    for ext in ("<script src", "<link", "http://", "https://", "@import"):
        assert ext not in html


def test_markdown_has_summary_and_notes():
    md = render_markdown(_inv(notes=[{"kind": "dependents_failed", "object": "Dunder / X",
                                      "detail": "d"}]))
    assert "REVIEW_DELETE" in md and "dependents_failed" in md and "Basket" in md


def test_top_level_notes_are_rendered_in_both_outputs():
    top = [{"kind": "org_skipped", "object": "Old Org (7)", "detail": "status 'INACTIVE'"}]
    inv = _inv(top_notes=top)
    for out in (render_markdown(inv), render_html(inv)):
        assert "org_skipped" in out and "Old Org (7)" in out


def test_anchor_column_labelled_as_column_id():
    inv = _inv()
    md, html = render_markdown(inv), render_html(inv)
    assert "Anchor (column id)" in md and "col-guid-1" in md
    assert "Anchor (column id)" in html and "col-guid-1" in html


def test_incomplete_model_says_unknown_not_zero():
    inv = _inv()
    inv["orgs"][0]["models"][0].update(discovery="INCOMPLETE", set_count=None, sets=[])
    for out in (render_markdown(inv), render_html(inv)):
        assert "INCOMPLETE" in out and "unknown" in out.lower()
        assert "Dunder — 0 Set" not in out


def test_document_order_is_preserved_not_resorted():
    inv = _inv()
    m = inv["orgs"][0]["models"][0]
    m["sets"] = [_set("Zeta", guid="z"), _set("Alpha", guid="a")]
    inv["orgs"].insert(0, {"org": "Zorg", "notes": [], "models": [
        {"guid": "m9", "name": "Zmodel", "discovery": "COMPLETE", "set_count": 0, "sets": []}]})
    for out in (render_markdown(inv), render_html(inv)):
        assert out.index("Zorg") < out.index("Primary")
        assert out.index("Zeta") < out.index("Alpha")
    assert [d["set"] for d in review_lists(inv)["delete"]] == ["Zeta", "Alpha"]


def test_liveboard_usage_shown_in_html_detail():
    inv = _inv()
    s = inv["orgs"][0]["models"][0]["sets"][0]
    s["dependents"] = [{"guid": "lb1", "name": "Sales LB", "type": "LIVEBOARD", "author_id": "a"}]
    s["liveboards"] = {"lb1": {"vizzes": [{"id": "v1", "title": "Top <baskets>"}], "filter": True}}
    html = render_html(inv)
    assert "Sales LB" in html and "Top &lt;baskets&gt;" in html and "Liveboard filter" in html
