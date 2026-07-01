import os
import sys

import pytest

HERE = os.path.dirname(__file__)
SKILL_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")

if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)


@pytest.fixture
def fixtures_dir():
    return FIXTURES
