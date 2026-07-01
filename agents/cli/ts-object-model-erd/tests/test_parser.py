import os

import parser

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_load_tml_returns_dict():
    data = parser.load_tml(os.path.join(FIXTURES, "mini.model.tml"))
    assert data["model"]["name"] == "Mini Sales"
    assert data["guid"] == "model-guid-001"
