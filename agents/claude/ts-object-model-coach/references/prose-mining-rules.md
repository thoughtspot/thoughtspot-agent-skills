# Prose Mining Rules — `ts-coach-model`

How to extract business phrases and question seeds from analyst-written prose on the
Model and its dependent objects. Used in [SKILL.md Step 3c](../SKILL.md). The output
feeds candidate generation in Step 6 (synonyms, AI Context, Reference Question
paraphrases) and the critique in Step 4 (gaps in existing assets).

The premise: tokenised `search_query` strings tell you HOW analysts query, but prose
fields (titles, descriptions) tell you what BUSINESS LANGUAGE they use. Both signals
matter; they fill different gaps.

---

## Sources to mine, ranked by signal quality

| Source | Why it matters | Typical signal density |
|---|---|---|
| **Liveboard tile names** (`liveboard.visualizations[].answer.name`) | Analysts label tiles in user-facing language — what they want users to SEE the question called | Very high |
| **Liveboard descriptions** (`liveboard.description`) | Author-written summary of the dashboard's analytical purpose | High |
| **Liveboard tile descriptions** (`liveboard.visualizations[].description`) | Per-viz business commentary | High |
| **Liveboard name** (`liveboard.name`) | Concise business framing of the dashboard | High |
| **Answer descriptions** (`answer.description`) | Author-written explanation of the question | High when populated |
| **Answer dynamic_name / dynamic_description** | ThoughtSpot-AI-generated labels, often surprisingly good | Medium |
| **Answer names** (`answer.name`) | Often the canonical short form of the question | Medium |
| **Model description** (`model.description`) | Whole-Model business overview — broad, sets the domain vocabulary | Medium-high |
| **Column descriptions** (`columns[].description`) | Per-column author notes | High when populated |
| **Existing column ai_context** | Already curated business meaning | Authoritative — don't duplicate, refine |
| **Table descriptions** (`table.description` on physical tables) | Schema-level analyst commentary | Sporadic — high quality where present |

Skip sources that are debug-style ("Bin not sorting correctly", "Pass Through Functions
- Moving Windows") — flag by regex and exclude.

---

## Phrase extraction

For each prose source, run lightweight NLP — no external models required:

### 1. Sentence + clause splitting

Split on `.`, `!`, `?`, and conjunctions (`and`, `but`, `which`). Trim and lowercase.

### 2. Noun phrase extraction

Use a regex-based shallow parser — sufficient for English business prose:

```python
import re

# Adjective(s) + Noun(s), stop at verb / preposition / punctuation
NP = re.compile(
    r"\b(?:(?:[a-z]+(?:_| ))?(?:[a-z]+))\b(?:(?:[a-z]+(?:_| ))?(?:[a-z]+))*",
    re.IGNORECASE,
)
# Stopwords to filter from inside multi-word NPs
STOP = {"the","a","an","of","by","to","in","on","at","for","with","is","are","be","and","or"}
```

Or use `nltk.pos_tag` if available. The output is a list of candidate phrases per source.

### 3. Filter by length and content

Keep phrases with:
- 1 ≤ word count ≤ 5 (longer phrases rarely match column names)
- ≥ 1 non-stopword
- No digits-only tokens
- No ThoughtSpot-internal keywords (`liveboard`, `worksheet`, `answer`, `viz`)

### 4. Match phrases to columns

For each phrase, score its match against each Model column display name:

```python
def stem(s):
    return re.sub(r"\W+", "", s.lower()).rstrip("s")  # crude lemmatisation

def overlap(phrase, col_name):
    p_tokens = {stem(t) for t in phrase.split() if t.lower() not in STOP}
    c_tokens = {stem(t) for t in col_name.split() if t.lower() not in STOP}
    if not p_tokens or not c_tokens:
        return 0.0
    return len(p_tokens & c_tokens) / len(p_tokens | c_tokens)   # Jaccard
```

Match thresholds:

| Score | Treatment |
|---|---|
| ≥ 0.8 | Exact / near-exact (e.g. "inventory balance" ↔ `Inventory Balance`) — drop, phrase is just the column name |
| 0.5 – 0.79 | Strong synonym candidate (e.g. "inventory levels" ↔ `Inventory Balance`) — keep for synonym proposal |
| 0.25 – 0.49 | Weak / ambiguous — flag for user review only, don't auto-propose |
| < 0.25 | No relationship to that column |

A phrase that scores 0.5 against multiple columns goes to the highest-scoring column;
ties → pick the column with fewer existing synonyms.

### 5. Question-seed extraction

Distinct from the phrase loop: scan full sentences for question-shaped patterns —
prose that reads like a query rather than a label:

```python
QUESTION_SHAPES = [
    re.compile(r"\bgrowth (in|of) (\w+)", re.I),                  # → YoY pattern seed
    re.compile(r"\b(top|bottom) (\d+) (\w+)", re.I),              # → top-N seed
    re.compile(r"\b(\w+) (over time|by month|by quarter|trend)", re.I),  # → time-series seed
    re.compile(r"\bcompare (\w+) (to|vs|versus) (\w+)", re.I),    # → comparison seed
    re.compile(r"\b(\w+) (per|each) (\w+)", re.I),                # → ratio seed
    re.compile(r"\bshare of (\w+)", re.I),                        # → share-of-total seed
]
```

For each match, emit a question seed: `{pattern: "yoy", phrase: "growth in sales amounts",
source: "model.description"}`. These feed Step 6.3 (Reference Questions) as paraphrase
variants of the canonical question.

---

## Output format

Save to `{run_dir}/mined_prose_extract.json`:

```json
{
  "synonym_candidates_per_column": {
    "Inventory Balance": [
      {"phrase": "inventory levels", "score": 0.67, "sources": ["model.description"]},
      {"phrase": "stock", "score": 0.50, "sources": ["liveboard.tile.name#42"]}
    ],
    "Amount": [
      {"phrase": "sales amounts", "score": 0.50, "sources": ["model.description"]},
      {"phrase": "sales", "score": 0.50, "sources": ["model.description","answer.name#Total Amount by Order Id"]}
    ]
  },
  "question_seeds": [
    {"pattern": "yoy",        "phrase": "growth in sales amounts",        "source": "model.description"},
    {"pattern": "top_n",      "phrase": "top 10 customers by revenue",     "source": "answer.name#Total Amount by Order Id"},
    {"pattern": "share",      "phrase": "share of total inventory balance","source": "answer.name#Balances with of and percentage of"}
  ],
  "ai_context_evidence_per_column": {
    "Inventory Balance": ["tracks inventory levels", "current quantity at end of period"],
    "Amount": ["sales transactions", "transaction value", "growth in sales amounts"]
  }
}
```

---

## Worked example — Dunder Mifflin Sales & Inventory

Given the Model description:

> *"The Dunder Mifflin Sales & Inventory worksheet provides a comprehensive overview of
> sales transactions, including details about the products sold, the quantities
> involved, and the prices at which they were sold. It also includes information about
> the customers, such as their names, codes, and geographical details, as well as the
> employees who handled each transaction. Additionally, the worksheet tracks inventory
> levels and includes metrics to analyze the growth in sales amounts."*

Extracted phrases and column matches:

| Phrase | Best column | Score | → Synonym proposal? |
|---|---|---|---|
| "sales transactions" | `Amount` (via stem `sale`) | 0.33 | Weak — flag for review |
| "products sold" | `Product Name` | 0.33 | Weak |
| "quantities" | `Quantity` | 1.00 | Skip — same as column |
| "prices" | `Unit Price` | 0.50 | ✅ propose `synonyms: ['price']` |
| "customers" | `Customer Name` | 0.50 | ✅ propose |
| "geographical details" | `Customer State` (via stem `geog`/`state`) | 0.0 | No match — but seeds AI Context evidence |
| "employees" | `Employee` | 1.0 | Skip — same |
| **"inventory levels"** | `Inventory Balance` | 0.67 | ✅ **propose `synonyms: ['inventory levels','stock','levels']`** |
| **"growth in sales amounts"** | `Amount` | 0.50 | ✅ propose synonym `'sales'` + emit YoY question seed |

Question seeds emitted: `yoy(growth_in_sales_amounts)`. This becomes a +5-bonus
candidate in Step 6.3 with the variant phrasing *"growth in sales amounts"* added
to the canonical *"Amount YoY growth by ___"*.

AI Context evidence aggregated:
- `Inventory Balance`: ["tracks inventory levels"]
- `Amount`: ["sales transactions", "growth in sales amounts"]
- `Customer State`: ["geographical details", "customers' codes and geographical details"]

In Step 6.1 these become 2-3 sentence ai_context drafts (see
[ai-asset-review-rules.md](ai-asset-review-rules.md) for the template).

---

## Edge cases and gotchas

**Empty descriptions.** Common on demo Models — degrade gracefully. The skill should
still produce useful output from `search_query` patterns + schema alone, but reduce
the volume target (Snowflake's "10–20" assumes some prose evidence).

**AI-generated descriptions** (e.g. starts with `(AI generated)` suffix). Treat as
medium-quality input. Don't lean on them as sole evidence — confirm with mined
search_query overlap before proposing a synonym.

**Multi-language descriptions.** This skill is English-only in v1. If the description
is non-English, log it and skip prose mining for that source.

**Acronyms vs full forms.** "rev" / "revenue" are common pairs but don't share stems.
Add a small known-acronyms table per domain if needed; default to keeping them as
separate synonym candidates and letting the user reject duplicates.

**Sets and bin labels.** Phrases like `"Amount set"` or `"Top 10 Products"` are
ThoughtSpot Set names, not business phrases. Filter them by checking against
`answer.cohorts[].name` for each mined Answer.

**Dynamic descriptions vs static.** `dynamic_description` is regenerated by ThoughtSpot
periodically; don't treat it as authoritative. Use as supplemental signal only.

---

## Validation

Before passing extracts to Step 6:
1. No phrase appears as a synonym candidate for >1 column (resolve ties by score)
2. No proposed synonym is identical to its column's display name (case-insensitive)
3. No question seed references a column not in the Model
4. Total proposed synonyms per column ≤ 8 (avoid synonym sprawl)
