# Vendored JavaScript for the audit report's formula graph

Third-party code, embedded as it is in an audit report that has formula chains to draw
(`report.py`, `graph_script`, which puts each LICENSE file's text in a comment ahead of the code). Nothing here is edited by hand. `MANIFEST` pins each
file's SHA-256; `check_file_size.py` skips a file here only while its hash matches, and
`tests/test_audit_formula_graph.py` fails if a file and the manifest disagree. The directory
is in CODEOWNERS, so a re-pin requests the owner's review (binding only where branch
protection requires code-owner review); the mechanical guard is the hash test.

| File | Package and version | Source | Licence |
|---|---|---|---|
| `cytoscape.min.js` | cytoscape 3.30.2 | `https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js` | MIT, `LICENSE-cytoscape` |
| `dagre.min.js` | @dagrejs/dagre 1.1.4 | `https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js` | MIT, `LICENSE-dagre` |
| `cytoscape-dagre.js` | cytoscape-dagre 2.5.0 | `https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js` | MIT, `LICENSE-cytoscape-dagre` |

They load in this order, one script (`report.GRAPH_VENDOR`): `dagre.min.js` (sets the
`dagre` global), `cytoscape.min.js`, then `cytoscape-dagre.js`, which registers the dagre
layout with Cytoscape. `dagre.min.js` bundles `@dagrejs/graphlib` 2.2.4, whose BSD-3-Clause notice stays inside
the bundle. `@dagrejs/dagre` is the maintained fork of `dagre`; it does not bundle lodash, so it is
96 KB against `dagre` 0.8.5's 284 KB.

`MANIFEST`'s hashes are of the files as served at the URLs above on 2026-11-18: a reviewer of a
re-pin can download the named version and compare its SHA-256 without trusting the committer.
`.gitattributes` keeps these files byte-exact (no line-ending conversion).

To update one: download the new version from the same source, replace the file, update
its line in `MANIFEST` (`shasum -a 256 <file>`) and this table, and check the licence.
