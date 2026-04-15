# Worked Example — Snowflake Semantic View → ThoughtSpot Model

End-to-end conversion of `BIRD.SUPERHERO_SV.BIRD_SUPERHEROS_SV` to a ThoughtSpot
Model named `TEST_SV_BIRD Superhero`. Scenario B (inline joins) — the underlying
ThoughtSpot table objects have no pre-defined joins between them.

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
        ATTRIBUTE.ATTRIBUTE_NAME as attribute.ATTRIBUTE_NAME comment='the attribute that defines who they are',
        EYE_COLOUR.EYE_COLOUR as eye_colour.COLOUR comment='the color of the superhero''s eye',
        ...
        SUPERPOWER.POWER_NAME as superpower.POWER_NAME comment='the superpower name'
    )
    with extension (CA='...');
```

---

## Step 4: DDL Parse Results

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

**Fact tables:** `HERO_ATTRIBUTE` and `HERO_POWER` (never appear on TO side).
`SUPERHERO` also has outbound joins, making it an intermediate fact/bridge table.

---

## Step 6A: ThoughtSpot Table Objects Found + Column Names

```
ts metadata search --subtype ONE_TO_ONE_LOGICAL --all --profile champ-staging
```

**Important:** EYE_COLOUR, HAIR_COLOUR, and SKIN_COLOUR all resolve to the **same**
ThoughtSpot table object `colour` (same GUID). This is a dual-role table — include it
only once in model_tables.

| Semantic Alias | ThoughtSpot Name | ThoughtSpot GUID | Physical Column Names (from TML) |
|---|---|---|---|
| SUPERHERO | superhero | `18b70585-d020-4bc4-924e-977efcfbbcf7` | `id, name, full_name, height_cm, weight_kg, alignment_id, eye_colour_id, hair_colour_id, skin_colour_id, race_id, publisher_id, gender_id` |
| HERO_ATTRIBUTE | hero_attribute | `e8a38c54-8026-4942-a9f5-0816aa1ccb2f` | `hero_id, attribute_id, attribute_value` |
| HERO_POWER | hero_power | `f4b2e84a-1725-4b1d-b664-3486fc322eb5` | `hero_id, power_id` |
| ALIGNMENT | alignment | `766b058f-e3a3-4061-9288-0fb9b45a5aa7` | `id, alignment` |
| ATTRIBUTE | attribute | `41177cdc-60c7-4033-9182-badedfea93f0` | `id, attribute_name` |
| EYE_COLOUR / HAIR_COLOUR / SKIN_COLOUR | colour | `6905b1d7-2eb1-482f-a7f9-296aff8f08a4` | `id, colour` |
| GENDER | gender | `ef1360b0-c067-4328-977a-4ea28f766c75` | `id, gender` |
| PUBLISHER | publisher | `a8ed13f2-962b-44e6-8056-0345c702d9c3` | `id, publisher_name` |
| RACE | race | `2ad21b9a-2814-4013-ad7a-246ba39c8a83` | `id, race` |
| SUPERPOWER | superpower | `fcc132c8-8131-4f2a-9267-79fbd91c956d` | `id, power_name` |

**Column name mapping (semantic view alias → ThoughtSpot physical name):**

The semantic view uses the Snowflake view layer (`BIRD.SUPERHERO_SV.*`) which renames
columns from the physical tables. Examples:

| Semantic View Dimension | View Column | Physical Column (ThoughtSpot) | column_id |
|---|---|---|---|
| SUPERHERO.SUPERHERO_ID | SUPERHERO_ID (in SUPERHERO_SV view) | `id` (in physical superhero table) | `superhero::id` |
| SUPERHERO.SUPERHERO_NAME | SUPERHERO_NAME | `name` | `superhero::name` |
| SUPERHERO.SH_ALIGNMENT_ID | SH_ALIGNMENT_ID | `alignment_id` | `superhero::alignment_id` |
| HERO_ATTRIBUTE.HA_HERO_ID | HA_HERO_ID | `hero_id` | `hero_attribute::hero_id` |
| HERO_ATTRIBUTE.HA_ATTRIBUTE_ID | HA_ATTRIBUTE_ID | `attribute_id` | `hero_attribute::attribute_id` |
| EYE_COLOUR.EYE_COLOUR | EYE_COLOUR | `colour` | `colour::colour` |

---

## Step 7: Join Names (Scenario B — no pre-defined joins)

Exporting ThoughtSpot table TMLs confirms that none of the tables have pre-defined
`joins_with` entries. Use **inline joins** in the model TML instead of `referencing_join`.

---

## Output — ThoughtSpot Model TML (abbreviated)

```yaml
model:
  name: "TEST_SV_BIRD Superhero"
  model_tables:
  - id: hero_attribute
    name: hero_attribute
    fqn: "e8a38c54-8026-4942-a9f5-0816aa1ccb2f"
    joins:
    - name: ha_to_superhero
      with: superhero           # matches id of target entry
      on: "[hero_attribute::hero_id] = [superhero::id]"   # physical cols
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: ha_to_attribute
      with: attribute
      on: "[hero_attribute::attribute_id] = [attribute::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - id: hero_power
    name: hero_power
    fqn: "f4b2e84a-1725-4b1d-b664-3486fc322eb5"
    joins:
    - name: hp_to_superhero
      with: superhero
      on: "[hero_power::hero_id] = [superhero::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: hp_to_superpower
      with: superpower
      on: "[hero_power::power_id] = [superpower::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - id: superhero
    name: superhero
    fqn: "18b70585-d020-4bc4-924e-977efcfbbcf7"
    joins:
    - name: sh_to_alignment
      with: alignment
      on: "[superhero::alignment_id] = [alignment::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_colour
      with: colour
      on: "[superhero::eye_colour_id] = [colour::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_hair_colour
      with: colour
      on: "[superhero::hair_colour_id] = [colour::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_skin_colour
      with: colour
      on: "[superhero::skin_colour_id] = [colour::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_gender
      with: gender
      on: "[superhero::gender_id] = [gender::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_publisher
      with: publisher
      on: "[superhero::publisher_id] = [publisher::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - name: sh_to_race
      with: race
      on: "[superhero::race_id] = [race::id]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - id: alignment
    name: alignment
    fqn: "766b058f-e3a3-4061-9288-0fb9b45a5aa7"
  - id: attribute
    name: attribute
    fqn: "41177cdc-60c7-4033-9182-badedfea93f0"
  - id: colour               # ONE entry for EYE_COLOUR + HAIR_COLOUR + SKIN_COLOUR
    name: colour
    fqn: "6905b1d7-2eb1-482f-a7f9-296aff8f08a4"
  - id: gender
    name: gender
    fqn: "ef1360b0-c067-4328-977a-4ea28f766c75"
  - id: publisher
    name: publisher
    fqn: "a8ed13f2-962b-44e6-8056-0345c702d9c3"
  - id: race
    name: race
    fqn: "2ad21b9a-2814-4013-ad7a-246ba39c8a83"
  - id: superpower
    name: superpower
    fqn: "fcc132c8-8131-4f2a-9267-79fbd91c956d"
  columns:
  - name: "Superhero Name"
    column_id: superhero::name         # physical col 'name', not 'SUPERHERO_NAME'
    properties:
      column_type: ATTRIBUTE
  - name: "Full Name"
    column_id: superhero::full_name
    properties:
      column_type: ATTRIBUTE
  - name: "Height (cm)"
    column_id: superhero::height_cm
    properties:
      column_type: ATTRIBUTE
  - name: "Alignment"
    column_id: alignment::alignment
    properties:
      column_type: ATTRIBUTE
  - name: "Attribute Name"
    column_id: attribute::attribute_name
    properties:
      column_type: ATTRIBUTE
  - name: "Attribute Value"
    column_id: hero_attribute::attribute_value
    properties:
      column_type: ATTRIBUTE
  - name: "Eye Colour"
    column_id: colour::colour           # same physical col serves eye/hair/skin
    properties:
      column_type: ATTRIBUTE
  - name: "Gender"
    column_id: gender::gender
    properties:
      column_type: ATTRIBUTE
  - name: "Publisher"
    column_id: publisher::publisher_name
    properties:
      column_type: ATTRIBUTE
  - name: "Race"
    column_id: race::race
    properties:
      column_type: ATTRIBUTE
  - name: "Power Name"
    column_id: superpower::power_name
    properties:
      column_type: ATTRIBUTE
```

---

## Key patterns from this example

1. **Real DDL format:** Flat `dimensions` and `metrics` blocks at view level (not nested
   per-table). Relationships use `REL_NAME as FROM(COL) references TO(COL)` syntax.

2. **Inline joins (Scenario B):** Required when ThoughtSpot tables have no pre-defined
   `joins_with` entries. The `with` field is REQUIRED and must match the target table's `id`.

3. **`with` and `on` consistency:** `with: alignment` and `on: "[superhero::alignment_id] = [alignment::id]"`
   both use the `id` value (`alignment`). `id` values must be lowercase.

4. **Dual-role tables:** EYE_COLOUR, HAIR_COLOUR, SKIN_COLOUR all map to the same
   ThoughtSpot `colour` table. Only ONE entry in model_tables; THREE joins from superhero
   (each using a different FK column). Hair and skin colour columns are omitted — the
   `colour` table appears only once in the column list.

5. **Physical column names:** `SUPERHERO_ID` (view alias) → `id` (physical column).
   Always export the ThoughtSpot table TML and use those column names in `column_id`.

6. **`name` uniqueness:** Using `id: colour` for all three colour roles prevents the
   "Multiple tables have same alias" error that would occur with separate entries.

7. **No metrics in this model:** The superhero semantic view has no metrics block —
   all columns are dimensions (ATTRIBUTEs).
