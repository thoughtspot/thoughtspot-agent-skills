import os
import sys

import pytest

HERE = os.path.dirname(__file__)
SKILL_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")

# ERD generation lives in the shared library (agents/shared/erd) — the single
# source of truth consumed by both this skill and the ts-audit ERD embed.
SHARED_ERD = os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "shared", "erd")

for _p in (SHARED_ERD, SKILL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def fixtures_dir():
    return FIXTURES
