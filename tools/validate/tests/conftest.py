"""Put tools/validate on sys.path so tests can `import check_tml`, `import run_smoke_tests`,
etc. directly (mirrors the inline sys.path insert in test_check_tml.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
