# Open Items — ts-object-answer-promote

Unverified or partially verified API behaviors. Each item includes a status, test
procedure, and findings recorded against `champ-staging` (champagne-master-aws.thoughtspotstaging.cloud).

---

## Item 2 — Edit permissions in metadata search response

**Skill steps affected:** Step 6 (access check)

**Status:** PARTIALLY VERIFIED — tested against champ-staging

**Finding:** The `ts metadata search` response does not include an explicit permissions
field. `POST /api/rest/2.0/security/metadata/fetch` returned HTTP 500 on champ-staging.

**Current recommendation:** Proceed without pre-flight permission check. Rely on import
response for access errors. If `metadata_header.author` matches current user, skip warning.

**Still to test:**
- [ ] READ_ONLY shared Model import behaviour
- [ ] `security/metadata/fetch` on newer instance versions

---

## Item 3 — Bare display-name column references in Model formulas

**Skill steps affected:** Step 9 (column reference mapping)

**Status:** PARTIALLY VERIFIED — `TABLE::COLUMN_ID` translation confirmed working; bare names untested

**Finding:** Model formulas use `[TABLE::col]` format. Answer formulas use bare
`[display_name]`. Translating bare refs to `[TABLE::COLUMN_ID]` works (verified on
champ-staging).

**Still to test:**
- [ ] Whether bare display-name refs (untranslated) also work in Model formula import

---

## Item 4 — Answers embedded in Liveboards (not standalone objects)

**Skill steps affected:** Step 2 (Find the Answer)

**Status:** RESOLVED — deferred to BL-039 (out of current scope)

**Disposition:** The skill operates on **standalone saved Answers only**. Step 2 searches
`ts metadata search --type ANSWER`, which by design returns only independent Answer objects;
Liveboard-embedded Answers are not independent metadata objects and the skill never attempts
to promote from them. There is therefore no shipped path that could produce a wrong result
here. Resolving an embedded Answer out of a Liveboard TML and promoting from it is a future
enhancement tracked in **BL-039**, not a correctness gap in the current skill.

**Deferred questions (for BL-039):**
- Does Answer search return Liveboard-embedded Answers? (expected: no)
- Liveboard TML structure for embedded Answers
- Whether embedded Answer formulas reuse the same `formulas[]` / `expr` structure

---

## Item 5 — Sets (cohorts) in Answer TML — promotion path

**Skill steps affected:** Step 3, Step 4

**Status:** RESOLVED — structure VERIFIED; promotion deferred to BL-039 (out of current scope)

**Finding:** Sets appear as `cohorts[]` in Answer TML, not in `formulas[]`. Two types:
BIN_BASED (simple) and COLUMN_BASED (advanced/query). This structure is confirmed.

**Disposition:** The skill **promotes formulas and parameters only** — it detects sets and
explicitly tells the user they require separate promotion ("Sets require separate promotion
to standalone set objects. This skill handles formulas only"). Set promotion is not shipped
behaviour, so there is no shipped path to verify in the current skill. Building a standalone
set object from an answer-level cohort entry is a future enhancement tracked in **BL-039**.

**Deferred questions (for BL-039):**
- Build standalone cohort TML from an answer-level entry and import
- Verify a reusable set works as a column in new Answers on the same Model
