# Formula fidelity test cases: research

Research from 2026-10-06 into where to get formula test cases that carry **expected
results**. Each case is a source formula, its input data, and the value the source
tool returns. The aim is to check that a translated ThoughtSpot formula returns the
same answer, not just that it imports.

| File | Contents |
|---|---|
| [recommendation.md](recommendation.md) | The 3–5 sources to start with, and the first milestones (M0, M1) |
| [sources.md](sources.md) | Catalogue of candidate sources, with licence verdicts, coverage and extraction notes |
| [oracles.md](oracles.md) | How to compute expected values ourselves (LibreOffice, the Python `formulas` library, warehouse SQL), with fidelity limits |
| [harness-design.md](harness-design.md) | End-to-end harness design: case format, load, oracle, translate, run in ThoughtSpot, compare, reverse direction |

**Licence verdicts are an engineering reading, not legal advice.** Get legal sign-off
before any third-party test data is copied into this repo. No third-party data is
committed here. Counts marked "measured" come from parsing downloaded copies, which
were not kept.
