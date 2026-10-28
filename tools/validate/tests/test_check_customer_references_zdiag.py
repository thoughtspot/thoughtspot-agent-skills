"""TEMPORARY diagnostic (draft PR, never merged): timings for the flaky zoom linearity case."""
import gc, sys, time
import pytest
import check_customer_references as ccr

def _t(seed, n, gc_off):
    line = "thoughtspot slack sharepoint google " + seed * (n // len(seed))
    out = []
    for _ in range(3):
        if gc_off: gc.disable()
        s = time.perf_counter(); hits = ccr.scan_text(line, "x.md"); d = time.perf_counter() - s
        gc.enable(); out.append(d)
    return min(out), max(out), len(hits)

def test_zoom_timing_report():
    rows = [f"py={sys.version.split()[0]} tracked={len(gc.get_objects()):,} thresholds={gc.get_threshold()}"]
    for name, seed in (("zoom", "zoom" + ".us/j/"), ("dropbox", "dropbox" + ".com/s/a"), ("star", "a*")):
        for gc_off in (False, True):
            r = {n: _t(seed, n, gc_off) for n in (250_000, 1_000_000, 2_000_000)}
            rows.append(f"{name:8s} gc_off={gc_off!s:5s} " + " ".join(
                f"{n//1000}K=min{a:.3f}/max{b:.3f}s hits={h}" for n, (a, b, h) in r.items())
                + f" ratio1M={r[1_000_000][0]/r[250_000][0]:.1f} ratio2M/1M={r[2_000_000][0]/r[1_000_000][0]:.1f}")
    pytest.fail("ZDIAG\n" + "\n".join(rows))
