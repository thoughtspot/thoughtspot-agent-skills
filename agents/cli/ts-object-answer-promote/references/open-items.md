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

**Status:** UNTESTED

**Why it matters:** `ts metadata search --type ANSWER` returns only standalone saved
Answers. Liveboard-embedded Answers are not independent metadata objects.

**What to record:**
- [ ] Does Answer search return Liveboard-embedded Answers?
- [ ] What is the Liveboard TML structure for embedded Answers?
- [ ] Do embedded Answer formulas use the same `formulas[]` / `expr` structure?

---

## Item 5 — Sets (cohorts) in Answer TML — promotion path

**Skill steps affected:** Step 3, Step 4

**Status:** VERIFIED (structure) / UNTESTED (promotion path)

**Finding:** Sets appear as `cohorts[]` in Answer TML, not in `formulas[]`. Two types:
BIN_BASED (simple) and COLUMN_BASED (advanced/query).

**Still to test:**
- [ ] Build standalone cohort TML from answer-level entry and import
- [ ] Verify reusable set works as a column in new Answers on the same Model
