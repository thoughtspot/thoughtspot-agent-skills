"""The organic layout must not fling a node far from the rest of the graph.

Repulsion was repK/d^2 with no cap: two nodes that started close could throw one thousands
of pixels in a single step, and the springs and centring pull could not bring it back before
the layout cooled. The 28-table Order Fulfilment example opened with its PRODUCT -> CATEGORY
tail ~7,000 px out (farthest/median distance from the centroid 5.17). Both examples render
in headless Chrome; the bound is loose enough for any sane layout (every Model in a 52-graph
benchmark sat at or under 1.9 after the fix).
"""
import os
import statistics

import pytest

from . import browser

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples")
_POINTS = "return nodes.map(function(n){return [n.x,n.y];});"


@pytest.mark.parametrize("example", ["order-fulfilment", "sales-inventory"])
def test_no_node_is_flung_far_from_the_rest(example, tmp_path):
    pts = browser.probe(os.path.join(EXAMPLES, example, "model_erd.html"), _POINTS, tmp_path)
    cx = statistics.mean(p[0] for p in pts)
    cy = statistics.mean(p[1] for p in pts)
    d = sorted(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts)
    assert d[-1] / statistics.median(d) < 3, (example, round(d[-1] / statistics.median(d), 2))
