# Worked Example — Snowflake Semantic View → ThoughtSpot Model

End-to-end conversion of `BIRD.SUPERHERO_SV.BIRD_SUPERHEROS_SV` to a ThoughtSpot
Model named `TEST_SV_BIRD Superhero`.

The semantic view references Snowflake objects in the `BIRD.SUPERHERO_SV` schema —
in this case those objects are views, but a semantic view can equally reference
physical tables or a mix of both. ThoughtSpot Table objects for these views already
exist on the `se-thoughtspot` cluster (user answered **Y** at Step 3). The tables
have no pre-defined joins, so inline joins are used in the model TML.

---

## Input — Semantic View DDL (abbreviated)

```sql
create or replace semantic view BIRD_SUPERHEROS_SV
    tables (
        BIRD.SUPERHERO_SV.SUPERHERO primary key (SUPERHERO_ID),
        BIRD.SUPERHERO_SV.HERO_ATTRIBUTE,
        BIRD.SUPERHERO_SV.HERO_POWER,
        BIRD.SUPERHERO_SV.ALIGNMENT primary key (ALIGNMENT_ID),
        BIRD.SUPERHERO_SV.ATTRIBUTE primary key (ATTRIBUTE_ID),
        BIRD.SUPERHERO_SV.EYE_COLOUR primary key (EYE_COLOUR_PK_ID),
        BIRD.SUPERHERO_SV.HAIR_COLOUR primary key (HAIR_COLOUR_PK_ID),
        BIRD.SUPERHERO_SV.SKIN_COLOUR primary key (SKIN_COLOUR_PK_ID),
        BIRD.SUPERHERO_SV.GENDER primary key (GENDER_ID),
        BIRD.SUPERHERO_SV.PUBLISHER primary key (PUBLISHER_ID),
        BIRD.SUPERHERO_SV.RACE primary key (RACE_ID),
        BIRD.SUPERHERO_SV.SUPERPOWER primary key (SUPERPOWER_ID)
    )
    relationships (
        SUPERHERO_TO_ALIGNMENT as SUPERHERO(SH_ALIGNMENT_ID) references ALIGNMENT(ALIGNMENT_ID),
        SUPERHERO_TO_EYE_COLOUR as SUPERHERO(SH_EYE_COLOUR_ID) references EYE_COLOUR(EYE_COLOUR_PK_ID),
        SUPERHERO_TO_GENDER as SUPERHERO(SH_GENDER_ID) references GENDER(GENDER_ID),
        SUPERHERO_TO_HAIR_COLOUR as SUPERHERO(SH_HAIR_COLOUR_ID) references HAIR_COLOUR(HAIR_COLOUR_PK_ID),
        SUPERHERO_TO_PUBLISHER as SUPERHERO(SH_PUBLISHER_ID) references PUBLISHER(PUBLISHER_ID),
        SUPERHERO_TO_RACE as SUPERHERO(SH_RACE_ID) references RACE(RACE_ID),
        SUPERHERO_TO_SKIN_COLOUR as SUPERHERO(SH_SKIN_COLOUR_ID) references SKIN_COLOUR(SKIN_COLOUR_PK_ID),
        HERO_ATTRIBUTE_TO_ATTRIBUTE as HERO_ATTRIBUTE(HA_ATTRIBUTE_ID) references ATTRIBUTE(ATTRIBUTE_ID),
        HERO_ATTRIBUTE_TO_SUPERHERO as HERO_ATTRIBUTE(HA_HERO_ID) references SUPERHERO(SUPERHERO_ID),
        HERO_POWER_TO_SUPERHERO as HERO_POWER(HP_HERO_ID) references SUPERHERO(SUPERHERO_ID),
        HERO_POWER_TO_SUPERPOWER as HERO_POWER(HP_POWER_ID) references SUPERPOWER(SUPERPOWER_ID)
    )
    dimensions (
        SUPERHERO.SUPERHERO_ID as superhero.SUPERHERO_ID comment='the unique identifier of the superhero',
        SUPERHERO.SUPERHERO_NAME as superhero.SUPERHERO_NAME comment='the name of the superhero',
        SUPERHERO.FULL_NAME as superhero.FULL_NAME comment='the full name of the superhero',
        SUPERHERO.HEIGHT_CM as superhero.HEIGHT_CM comment='the height of the superhero in centimeters',
        SUPERHERO.WEIGHT_KG as superhero.WEIGHT_KG comment='the weight of the superhero in kilograms',
        ...
        ALIGNMENT.ALIGNMENT as alignment.ALIGNMENT comment='the alignment of the superhero (Good, Neutral, or Bad)',
        ATTRIBUTE.ATTRIBUTE_NAME as attribute.ATTRIBUTE_NAME comment='the attribute that defines who they are and what they are capable of',
        EYE_COLOUR.EYE_COLOUR as eye_colour.COLOUR comment='the color of the superhero''s eye',
        HAIR_COLOUR.HAIR_COLOUR as hair_colour.COLOUR comment='the color of the superhero''s hair',
        SKIN_COLOUR.SKIN_COLOUR as skin_colour.COLOUR comment='the color of the superhero''s skin',
        ...
        SUPERPOWER.POWER_NAME as superpower.POWER_NAME comment='the superpower name'
    )
    with extension (CA='...');
```

---

## DDL Parse Results

**Tables:**

| Semantic Alias | Fully-Qualified Reference | Primary Key | Is Join Target? |
|---|---|---|---|
| SUPERHERO | BIRD.SUPERHERO_SV.SUPERHERO | SUPERHERO_ID | YES (from HERO_ATTRIBUTE, HERO_POWER) |
| HERO_ATTRIBUTE | BIRD.SUPERHERO_SV.HERO_ATTRIBUTE | — | NO |
| HERO_POWER | BIRD.SUPERHERO_SV.HERO_POWER | — | NO |
| ALIGNMENT | BIRD.SUPERHERO_SV.ALIGNMENT | ALIGNMENT_ID | YES |
| ATTRIBUTE | BIRD.SUPERHERO_SV.ATTRIBUTE | ATTRIBUTE_ID | YES |
| EYE_COLOUR | BIRD.SUPERHERO_SV.EYE_COLOUR | EYE_COLOUR_PK_ID | YES |
| HAIR_COLOUR | BIRD.SUPERHERO_SV.HAIR_COLOUR | HAIR_COLOUR_PK_ID | YES |
| SKIN_COLOUR | BIRD.SUPERHERO_SV.SKIN_COLOUR | SKIN_COLOUR_PK_ID | YES |
| GENDER | BIRD.SUPERHERO_SV.GENDER | GENDER_ID | YES |
| PUBLISHER | BIRD.SUPERHERO_SV.PUBLISHER | PUBLISHER_ID | YES |
| RACE | BIRD.SUPERHERO_SV.RACE | RACE_ID | YES |
| SUPERPOWER | BIRD.SUPERHERO_SV.SUPERPOWER | SUPERPOWER_ID | YES |

**Fact tables:** `HERO_ATTRIBUTE` and `HERO_POWER` (never appear on the TO side of any relationship).
`SUPERHERO` is an intermediate table — it receives joins from the fact tables and sends joins to dimension tables.

---

## ThoughtSpot Table Objects Found

**CoCo:**
```sql
CALL SKILLS.PUBLIC.TS_SEARCH_MODELS('{profile_name}', 'SUPERHERO_SV', FALSE);
-- (repeat per table name as needed)
```

**Claude Code:**
```bash
ts metadata search --subtype ONE_TO_ONE_LOGICAL --name '%SUPERHERO_SV%' --profile se-thoughtspot
# (repeat per table name as needed)
```

The ThoughtSpot table objects point directly to the Snowflake objects in `BIRD.SUPERHERO_SV` —
the same objects the semantic view references. Column names in the ThoughtSpot TMLs therefore
match the column names those objects expose.

| Semantic Alias | ThoughtSpot Name | GUID | Columns (from TML) |
|---|---|---|---|
| SUPERHERO | SUPERHERO | `4c089346-7892-4cbb-925c-395f5c90302b` | SUPERHERO_ID, SUPERHERO_NAME, FULL_NAME, HEIGHT_CM, WEIGHT_KG, SH_GENDER_ID, SH_EYE_COLOUR_ID, SH_HAIR_COLOUR_ID, SH_SKIN_COLOUR_ID, SH_RACE_ID, SH_PUBLISHER_ID, SH_ALIGNMENT_ID |
| HERO_ATTRIBUTE | HERO_ATTRIBUTE | `0d52f26c-9bcf-4c1f-8461-b1b9c5174f8b` | HA_HERO_ID, HA_ATTRIBUTE_ID, ATTRIBUTE_VALUE |
| HERO_POWER | HERO_POWER | `aae49ef1-8b13-4891-b9fc-eeac65e0116a` | HP_HERO_ID, HP_POWER_ID |
| ALIGNMENT | ALIGNMENT | `e0115940-7faa-4821-a840-68f0e6bf1b87` | ALIGNMENT_ID, ALIGNMENT |
| ATTRIBUTE | ATTRIBUTE | `7d539ecb-0888-425d-b84c-f85d2acc6416` | ATTRIBUTE_ID, ATTRIBUTE_NAME |
| EYE_COLOUR | EYE_COLOUR | `e21ffc4d-51f7-4141-b05e-0e314722cc2a` | EYE_COLOUR_PK_ID, COLOUR |
| HAIR_COLOUR | HAIR_COLOUR | `02c48153-f640-4a81-bf55-11d58dfd2913` | HAIR_COLOUR_PK_ID, COLOUR |
| SKIN_COLOUR | SKIN_COLOUR | `1dc0334f-a5df-443a-8bef-dd81174b6c39` | SKIN_COLOUR_PK_ID, COLOUR |
| GENDER | GENDER | `bfd7596e-431f-4f6a-99f4-20cec611c16c` | GENDER_ID, GENDER |
| PUBLISHER | PUBLISHER | `1e7dec84-6e8c-413c-b284-e1c285bd72a3` | PUBLISHER_ID, PUBLISHER_NAME |
| RACE | RACE | `f2d74e25-e11c-44e6-bf0a-a7bfa39ccacd` | RACE_ID, RACE |
| SUPERPOWER | SUPERPOWER | `fbd2de8f-dc23-4aaa-a14b-08e54cf3ccfc` | SUPERPOWER_ID, POWER_NAME |

**Column name note:** Always use the column names from the ThoughtSpot Table TML as the
`column_id` value — not the left-hand side of the semantic view dimension. Some Snowflake
objects rename columns internally. For example, the semantic view accesses `EYE_COLOUR.EYE_COLOUR`
but the ThoughtSpot table exposes that column as `COLOUR` — so `column_id` is `eye_colour::COLOUR`.

---

## Join Names (no pre-defined joins — inline joins required)

Exporting ThoughtSpot table TMLs confirms that none of the tables have pre-defined
`joins_with` entries. Use **inline joins** in the model TML instead of `referencing_join`.

---

## Output — ThoughtSpot Model TML (abbreviated)

```yaml
model:
  name: "TEST_SV_BIRD Superhero"
  # guid: "{model_guid}"   # Omit on first import. Add on ALL subsequent reimports to
  #                        # update in-place — without it ThoughtSpot creates a new model.
  properties:
    is_bypass_rls: false
    join_progressive: true
  model_tables:
  - id: hero_attribute          # lowercase id — used in column_id and join on clauses
    name: HERO_ATTRIBUTE        # exact ThoughtSpot table object name
    fqn: "0d52f26c-9bcf-4c1f-8461-b1b9c5174f8b"
    joins:
    - name: ha_to_superhero
      with: superhero           # matches id of target entry
      on: "[hero_attribute::HA_HERO_ID] = [superhero::SUPERHERO_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: ha_to_attribute
      with: attribute
      on: "[hero_attribute::HA_ATTRIBUTE_ID] = [attribute::ATTRIBUTE_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
  - id: hero_power
    name: HERO_POWER
    fqn: "aae49ef1-8b13-4891-b9fc-eeac65e0116a"
    joins:
    - name: hp_to_superhero
      with: superhero
      on: "[hero_power::HP_HERO_ID] = [superhero::SUPERHERO_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: hp_to_superpower
      with: superpower
      on: "[hero_power::HP_POWER_ID] = [superpower::SUPERPOWER_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
  - id: superhero
    name: SUPERHERO
    fqn: "4c089346-7892-4cbb-925c-395f5c90302b"
    joins:
    - name: sh_to_alignment
      with: alignment
      on: "[superhero::SH_ALIGNMENT_ID] = [alignment::ALIGNMENT_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_eye_colour
      with: eye_colour
      on: "[superhero::SH_EYE_COLOUR_ID] = [eye_colour::EYE_COLOUR_PK_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_hair_colour
      with: hair_colour
      on: "[superhero::SH_HAIR_COLOUR_ID] = [hair_colour::HAIR_COLOUR_PK_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_skin_colour
      with: skin_colour
      on: "[superhero::SH_SKIN_COLOUR_ID] = [skin_colour::SKIN_COLOUR_PK_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_gender
      with: gender
      on: "[superhero::SH_GENDER_ID] = [gender::GENDER_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_publisher
      with: publisher
      on: "[superhero::SH_PUBLISHER_ID] = [publisher::PUBLISHER_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
    - name: sh_to_race
      with: race
      on: "[superhero::SH_RACE_ID] = [race::RACE_ID]"
      type: INNER
      cardinality: MANY_TO_ONE
  - id: alignment
    name: ALIGNMENT
    fqn: "e0115940-7faa-4821-a840-68f0e6bf1b87"
  - id: attribute
    name: ATTRIBUTE
    fqn: "7d539ecb-0888-425d-b84c-f85d2acc6416"
  - id: eye_colour
    name: EYE_COLOUR
    fqn: "e21ffc4d-51f7-4141-b05e-0e314722cc2a"
  - id: hair_colour
    name: HAIR_COLOUR
    fqn: "02c48153-f640-4a81-bf55-11d58dfd2913"
  - id: skin_colour
    name: SKIN_COLOUR
    fqn: "1dc0334f-a5df-443a-8bef-dd81174b6c39"
  - id: gender
    name: GENDER
    fqn: "bfd7596e-431f-4f6a-99f4-20cec611c16c"
  - id: publisher
    name: PUBLISHER
    fqn: "1e7dec84-6e8c-413c-b284-e1c285bd72a3"
  - id: race
    name: RACE
    fqn: "f2d74e25-e11c-44e6-bf0a-a7bfa39ccacd"
  - id: superpower
    name: SUPERPOWER
    fqn: "fbd2de8f-dc23-4aaa-a14b-08e54cf3ccfc"
  columns:
  - name: "the name of the superhero"          # from comment='...'
    column_id: superhero::SUPERHERO_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "the full name of the superhero"
    column_id: superhero::FULL_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "the height of the superhero in centimeters"
    column_id: superhero::HEIGHT_CM
    properties:
      column_type: ATTRIBUTE
  - name: "the weight of the superhero in kilograms"
    column_id: superhero::WEIGHT_KG
    properties:
      column_type: ATTRIBUTE
  - name: "the alignment of the superhero (Good, Neutral, or Bad)"
    column_id: alignment::ALIGNMENT
    properties:
      column_type: ATTRIBUTE
  - name: "the attribute that defines who they are and what they are capable of"
    column_id: attribute::ATTRIBUTE_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "the attribute value"
    column_id: hero_attribute::ATTRIBUTE_VALUE
    properties:
      column_type: ATTRIBUTE
  - name: "the color of the superhero's eye"
    column_id: eye_colour::COLOUR         # ThoughtSpot column name, not semantic view alias
    properties:
      column_type: ATTRIBUTE
  - name: "the color of the superhero's hair"
    column_id: hair_colour::COLOUR
    properties:
      column_type: ATTRIBUTE
  - name: "the color of the superhero's skin"
    column_id: skin_colour::COLOUR
    properties:
      column_type: ATTRIBUTE
  - name: "the gender of the superhero"
    column_id: gender::GENDER
    properties:
      column_type: ATTRIBUTE
  - name: "the name of the publisher"
    column_id: publisher::PUBLISHER_NAME
    properties:
      column_type: ATTRIBUTE
  - name: "the race of the superhero"
    column_id: race::RACE
    properties:
      column_type: ATTRIBUTE
  - name: "the superpower name"
    column_id: superpower::POWER_NAME
    properties:
      column_type: ATTRIBUTE
```

---

## Key patterns from this example

1. **Semantic view objects are the ThoughtSpot table targets.** The `tables` block lists the
   Snowflake objects (tables or views) the model should be built on. ThoughtSpot Table objects
   point directly to those same objects — not to underlying physical tables.

2. **Column names match directly.** Because the ThoughtSpot tables point to the same Snowflake
   objects as the semantic view, column names in `column_id` match what those objects expose.
   Always confirm by exporting Table TMLs — some objects rename columns internally
   (e.g., `EYE_COLOUR.EYE_COLOUR` in the semantic view → `COLOUR` in the ThoughtSpot TML).

3. **Inline joins.** Required when ThoughtSpot tables have no pre-defined `joins_with` entries.
   The `with` field is REQUIRED and must match the target table's `id` — or, if `id` is
   omitted, its `name`.

4. **`id` is optional.** When `id` is present it must equal `name` exactly (same case).
   When `id` is absent, ThoughtSpot uses `name` as the join reference target — `with` and
   `on` clauses then reference the `name` value directly. Omitting `id` is simpler and avoids
   case-mismatch errors.

5. **`with` and `on` consistency.** Both must reference the same identifier (either the `id`
   if present, or the `name` if `id` is omitted). In the superhero example, `id` is set to
   lowercase and both use it: `with: alignment` and `on: "[superhero::SH_ALIGNMENT_ID] = [alignment::ALIGNMENT_ID]"`.

6. **Display names from `comment=`.** The `comment='...'` value on each dimension becomes the
   ThoughtSpot column display name. Where no comment exists, title-case the DIM_NAME.

7. **No metrics in this model.** The superhero semantic view has no metrics block —
   all columns are dimensions (ATTRIBUTEs).

8. **Join type is INNER** for all dimension lookups.

---

## Creating tables from scratch (user answered N at Step 3)

When no ThoughtSpot Table objects exist for the semantic view's referenced objects,
create them before building the model:

1. **Ask the user for the connection** — get the connection GUID via the ThoughtSpot
   REST API (`POST /api/rest/2.0/connection/search` with `record_size: 500`)
2. **Introspect columns** from Snowflake `INFORMATION_SCHEMA.COLUMNS` for the schema
3. **Build table TMLs** for each object and import them in one batch
4. **Then build the model TML** referencing the newly created tables

Table TML format:
```yaml
table:
  name: TABLE_NAME
  db: DATABASE
  schema: SCHEMA
  db_table: TABLE_NAME
  connection:
    name: "{connection_name}"   # Exact ThoughtSpot connection name — case-sensitive
  columns:
  - name: COL_NAME
    db_column_name: COL_NAME    # Always include db_column_name — required on all instances
    properties:
      column_type: ATTRIBUTE
      db_column_properties:
        data_type: INT64        # or VARCHAR, DOUBLE, DATE, BOOL, DATE_TIME
```

**IMPORTANT:** Use `$$` dollar-quoting in SQL for TML strings. Do NOT use `\n`
escape sequences — they are passed literally and break YAML parsing.

---

## Formula columns — Dunder Mifflin Sales & Inventory example

The BIRD Superhero example above has no formula columns. This section documents the
patterns for semantic views that include computed metrics, window functions, and
semi-additive measures, using `DUNDERMIFFLIN.PUBLIC.DUNDER_MIFFLIN_SALES_INVENTORY`
as the source.

### Metric types requiring formulas

| Semantic view metric | SQL expression | Translation type |
|---|---|---|
| `EMPLOYEE` (dim) | `CONCAT(LAST_NAME, ', ', FIRST_NAME)` | ATTRIBUTE formula |
| `EMPLOYEES` | `COUNT(DM_ORDER_EMPLOYEE_ID)` — same col also ATTRIBUTE | COUNT formula (avoids duplicate `column_id`) |
| `CATEGORY_QUANTITY` | `SUM(qty) OVER (PARTITION BY category)` | `group_sum` window formula |
| `PRODUCT_TO_CATEGORY_CONTRIBUTION_RATIO` | `DIV0(qty, SUM(qty) OVER (PARTITION BY category))` | `safe_divide` + inline `group_sum` |
| `INVENTORY_BALANCE` | `SUM(col) NON ADDITIVE BY (date ASC NULLS LAST)` | `last_value` semi-additive formula |

### Rule 1 — Every formula needs a `columns[]` entry (ATTRIBUTE and MEASURE both)

```yaml
columns:
- name: "Employee"                        # ATTRIBUTE formula — no aggregation needed
  formula_id: formula_Employee
  properties:
    column_type: ATTRIBUTE
- name: "Category Quantity"               # MEASURE formula
  formula_id: formula_Category Quantity
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
formulas:
- id: formula_Employee
  name: "Employee"
  expr: "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"
  properties:
    column_type: ATTRIBUTE
- id: formula_Category Quantity
  name: "Category Quantity"
  expr: "group_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_CATEGORY::CATEGORY_NAME] )"
  properties:
    column_type: MEASURE
```

### Rule 2 — Duplicate `column_id`: use a formula for COUNT when the column is also an ATTRIBUTE

`DM_ORDER_EMPLOYEE_ID` appears as both an ATTRIBUTE dimension and the basis for the
`# Employees` COUNT metric. ThoughtSpot rejects duplicate `column_id` values even across
different `column_type` values. Solution: keep the ATTRIBUTE `column_id` entry and make
`# Employees` a formula:

```yaml
columns:
- name: "Dm Order Employee Id"
  column_id: DM_ORDER::DM_ORDER_EMPLOYEE_ID
  properties:
    column_type: ATTRIBUTE
    is_hidden: true
- name: "# Employees"
  formula_id: "formula_# Employees"
  properties:
    column_type: MEASURE
    aggregation: COUNT
    index_type: DONT_INDEX
formulas:
- id: "formula_# Employees"
  name: "# Employees"
  expr: "count ( [DM_ORDER::DM_ORDER_EMPLOYEE_ID] )"
  properties:
    column_type: MEASURE
```

### Rule 3 — Window function: `SUM(...) OVER (PARTITION BY dim)` → `group_sum`

Use the ThoughtSpot **column name** for the PARTITION BY dimension (e.g., `CATEGORY_NAME`),
not the semantic view alias (`product_category`):

```yaml
- id: formula_Category Quantity
  name: "Category Quantity"
  expr: "group_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_CATEGORY::CATEGORY_NAME] )"
  properties:
    column_type: MEASURE
```

### Rule 4 — Contribution ratio: inline the window function, do not reference another formula

```yaml
- id: formula_Product to Category Contribution Ratio
  name: "Product to Category Contribution Ratio"
  expr: "safe_divide ( [DM_ORDER_DETAIL::QUANTITY] , group_sum ( [DM_ORDER_DETAIL::QUANTITY] , [DM_CATEGORY::CATEGORY_NAME] ) )"
  properties:
    column_type: MEASURE
```

Do NOT attempt to reference `[Category Quantity]` inside this formula — ThoughtSpot does
not allow formula-referencing-formula. Inline the `group_sum(...)` directly.

### Rule 5 — `last_value` (NON ADDITIVE BY): block scalar required

`{ [col] }` in the formula contains `{` which YAML interprets as a flow mapping start.
Always use a `>-` block scalar for any formula `expr` containing curly braces:

```yaml
- id: formula_Inventory Balance
  name: "Inventory Balance"
  expr: >-
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE] } )
  properties:
    column_type: MEASURE
```

The `>-` (folded, strip) emits the value as a single line with no trailing newline —
correct for ThoughtSpot formula parsing.

### Rule 6 — `id` can be omitted; `name` becomes the join reference target

```yaml
model_tables:
- name: DM_ORDER_DETAIL          # no id field — name is the reference target
  fqn: "b1e360c4-d571-490f-bae2-e8dc7443c9fa"
  joins:
  - with: DM_ORDER               # matches name: DM_ORDER exactly (same case)
    'on': '[DM_ORDER_DETAIL::RRDER_ID] = [DM_ORDER::ORDER_ID]'
    type: INNER
    cardinality: MANY_TO_ONE
  - with: DM_PRODUCT
    'on': '[DM_ORDER_DETAIL::DM_ORDER_DETAIL_PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]'
    type: INNER
    cardinality: MANY_TO_ONE
- name: DM_ORDER
  fqn: "3a9faf5d-5bde-4299-81f6-0706eb6c1535"
  joins:
  - with: DM_CUSTOMER
    'on': '[DM_ORDER::DM_ORDER_CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]'
    type: INNER
    cardinality: MANY_TO_ONE
  - with: DM_DATE_DIM
    'on': '[DM_ORDER::ORDER_DATE] = [DM_DATE_DIM::DATE]'
    type: INNER
    cardinality: MANY_TO_ONE
  - with: DM_EMPLOYEE
    'on': '[DM_ORDER::DM_ORDER_EMPLOYEE_ID] = [DM_EMPLOYEE::EMPLOYEE_ID]'
    type: INNER
    cardinality: MANY_TO_ONE
- name: DM_CUSTOMER
  fqn: "32c062cb-e23a-4bd3-a02c-8b7c1048d57f"
- name: DM_DATE_DIM
  fqn: "a8b75478-4286-46d2-9f59-22f0a74c588b"
- name: DM_EMPLOYEE
  fqn: "09f37d71-1c8f-4650-8cd6-64c18bf3367b"
```
