#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""check_ossie_mapping_sync.py — our Ossie function mapping vs the shipped converter's.

Two hand-maintained accounts of one ruleset, in two repositories:

* `docs/ossie/ts-ossie-function-mapping.md` here — the internal review artifact,
  written before the converter existed and still cited by this repo's own work.
* `converters/thoughtspot/docs/expression-mapping.md` in apache/ossie — generated
  from `expressions/catalog.py`, the code that actually ships.

Nothing compared them. The converter was donated to the ASF, so the two can now
drift with no shared gate, and the same class of defect this repo already
records applies: BL-171 shipped six ThoughtSpot string functions that do not
exist because a translator and its mapping doc disagreed, and nothing read both.

**What is gated: a classification that disagrees.** Our doc calling a construct
`direct` where the shipped converter calls it `passthrough` or `unmappable`
means our doc tells a reader to write a native ThoughtSpot formula the converter
itself has established does not work. That is the dangerous direction and it is
deterministic, so it fails.

**What is reported only: a construct in one and not the other.** The two use
different spellings for the same thing — upstream writes the operators as `!=`
and `%`, this repo writes them as `a != b` and `a % b` — so a presence gap is
dominated by naming convention rather than drift. Normalising the names was
tried and made it WORSE: collapsing `COUNT(expr)`, `COUNT(*)` and
`COUNT(DISTINCT expr)` onto one key lost more resolution than it recovered
(98 exactly-matching constructs before, 96 after). Counting it as a defect
would produce about forty false positives, so it is printed as context and
nothing more.

**Never fails because apache/ossie is absent.** The upstream doc is in another
repository that most checkouts will not have. Without it this exits 0 and says
so, rather than turning "you have not cloned ossie" into a failed commit.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

#: This repo's account of the mapping.
OURS = "docs/ossie/ts-ossie-function-mapping.md"
#: The shipped converter's, relative to an apache/ossie checkout.
UPSTREAM = "converters/thoughtspot/docs/expression-mapping.md"
#: Where to look for that checkout when neither --ossie-root nor OSSIE_ROOT says.
CONVENTIONAL = ("../ossie", "../../ossie", "~/Dev/ts/ossie")

#: `| `SUM(expr)` | direct | ... |` — the construct name and its classification,
#: which both documents happen to put in the same two leading columns.
_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*(direct|passthrough|unmappable)\s*\|", re.MULTILINE
)


def classifications(path: Path) -> dict[str, str]:
    """`{construct: classification}` for every mapping row in `path`.

    First occurrence wins. Both documents repeat a handful of constructs in
    prose tables after the main one, and the main table comes first.
    """
    found: dict[str, str] = {}
    for name, classification in _ROW.findall(path.read_text(encoding="utf-8")):
        found.setdefault(name.strip(), classification)
    return found


def find_upstream(explicit: str | None) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("OSSIE_ROOT"):
        candidates.append(Path(os.environ["OSSIE_ROOT"]).expanduser())
    candidates.extend(Path(c).expanduser() for c in CONVENTIONAL)
    for root in candidates:
        doc = root / UPSTREAM
        if doc.is_file():
            return doc
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--ossie-root", help="An apache/ossie checkout (or set OSSIE_ROOT)")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 on a disagreeing classification (default: warn only)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ours_path = repo_root / OURS
    if not ours_path.is_file():
        print(f"  {OURS} not found; nothing to compare.")
        return 0

    upstream_path = find_upstream(args.ossie_root)
    if upstream_path is None:
        print("  apache/ossie checkout not found, so the shipped converter's mapping "
              "could not be read.\n"
              "  Pass --ossie-root <path> or set OSSIE_ROOT to compare. Skipping.")
        return 0

    ours = classifications(ours_path)
    upstream = classifications(upstream_path)
    shared = sorted(set(ours) & set(upstream))
    disagree = [(k, ours[k], upstream[k]) for k in shared if ours[k] != upstream[k]]

    if disagree:
        print(f"  Ossie mapping disagrees with the shipped converter on "
              f"{len(disagree)} construct(s):")
        for name, mine, theirs in disagree:
            print(f"    • `{name}`: {OURS} says {mine}, the converter says {theirs}")
        print(f"    The converter is what ships. Correct {OURS}, or open an issue "
              f"upstream if the converter is the one that is wrong.")
    else:
        print(f"  Ossie mapping agrees with the shipped converter on all "
              f"{len(shared)} construct(s) both describe.")

    only_ours, only_theirs = set(ours) - set(upstream), set(upstream) - set(ours)
    if only_ours or only_theirs:
        print(f"  ({len(only_ours)} construct(s) only here, {len(only_theirs)} only "
              f"upstream — largely different spellings of the same thing, not drift; "
              f"see this file's docstring.)")

    return 1 if (args.check and disagree) else 0


if __name__ == "__main__":
    sys.exit(main())
