"""Network view behaviour, checked in a real (headless) browser."""
import os

import pytest

from . import browser

pytestmark = pytest.mark.skipif(browser.CHROME is None, reason="Google Chrome not installed")

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
FULFIL = os.path.join(EXAMPLES, "order-fulfilment", "model_erd.html")
SALES = os.path.join(EXAMPLES, "sales-inventory", "model_erd.html")


def test_cards_render_by_default(tmp_path):
    r = browser.probe(FULFIL, """
      return {nodes: document.querySelectorAll('#nodes .node').length,
              titles: document.querySelectorAll('#nodes .nh, #nodes .node-block-title').length,
              dots: document.querySelectorAll('#nodes circle.dot').length};""", tmp_path)
    assert r == {"nodes": 29, "titles": 29, "dots": 0}


def test_probe_reports_js_errors(tmp_path):
    r = browser.probe(SALES, "throw new Error('boom');", tmp_path)
    assert "boom" in r["__error"]
