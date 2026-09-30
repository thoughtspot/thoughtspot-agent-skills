# Taste rules: charts that do not look generated

Every attempt in the loop is critiqued against this list as well as against the intent. It is a
distillation for charts and dashboard tiles. It draws on the public "taste-skill" (Leonxlnx/taste-skill,
MIT), which targets landing pages and says itself that it is not for dashboards, and on the `dataviz`
palette validator. Take the principles, not the React and Tailwind machinery.

## Hard bans (a grep can find every one of these)

- **No emojis, no sparkle glyphs, no decorative symbols.** The skill already forces ASCII-only files, so
  a stray one fails `library-emit`. Use words, or a small inline SVG mark you drew for a reason.
- **No em-dashes** (use a comma, a colon or a full stop). No curly quotes.
- **No stock phrasing.** "Unlock", "Dive into", "Seamless", "Empower", "at a glance", "Explore your".
- **No fake precision.** A number is on screen because a row produced it. Projections are labelled as
  projections. Never invent a spec-sounding figure to decorate a card.
- **No gradients as decoration, no glow shadows, no glass.** A tooltip may carry one soft shadow.
- **No new hue.** See colour, below.

## Colour has one meaning

- Hues are **reserved** for the categorical dimension that earns them (on the Amuzing chart samples Liveboard, the five
  product families). Everything else is ink `#1E1E24` and slate greys (`AZ.T.slate`).
- A second categorical dimension (region) does not get hues. It gets position, labels or a slate ramp, so a
  colour never means two things on the same Liveboard.
- Sequential magnitude is **one hue, light to dark**. Diverging needs two hues and a neutral midpoint;
  when the palette is already spoken for, use sign and position (`+` and `-`, above and below a baseline).
- Up and down text may use `good` / `bad` **only with an explicit sign**. Status colour is never a series colour.
- **Validate any categorical palette** before building: `node <dataviz>/scripts/validate_palette.js "<hex,...>" --mode light`.
  Chroma floor, adjacent-pair colour-blind separation (target dE >= 8), normal-vision floor (>= 15). A
  WARN on contrast (amber on white) means direct labels are mandatory. The Amuzing family set
  (`#D1543A #2A6FD0 #0F9D8A #D99A00 #C2477A`) passes every gate in light mode.
- Lock the choice. Once an accent rule is set it applies to every tile, not just the first.

## Type, shape, space

- One family (Geist via the Google Fonts link, system fallback), a small fixed scale (11 / 12 / 13 / 14,
  hero 30 to 40), tabular numerals for anything numeric, tight tracking on hero numbers only.
- **One radius scale.** 6px on controls and tooltips; charts have no rounded-everything card soup.
- **Eyebrows are rationed.** A small label above a heading is allowed once per view, not above every block.
- **Cards only when elevation means something.** The Liveboard tile already is the card; do not draw another.
- Empty, loading and tiny-data states are designed: they name what is missing and what would fix it.

## Copy

- Specific and data-derived. "Jackets carry 37% of sales from 6% of units" beats "Explore your top categories".
- Titles name what is shown ("Monthly sales against last year"). The insight lives in the header line under
  it, computed from the rows.
- **Copy self-audit before emit:** re-read every visible string. Flag any that is grammatically off, has an
  unclear referent, reads like a forced metaphor, or sounds like a model trying to sound thoughtful. Replace
  it with a plain functional sentence. Boring and true beats cute.
- One register per tile.

## Interaction

- Every chart responds to the pointer: hover tooltip at minimum (`AZ.tip`), plus a click to isolate, a
  toggle, a sort or a scrub where the shape allows.
- Dim rather than remove when isolating (opacity about .25), so context survives.
- Hit targets larger than the mark. Visible keyboard focus on every control (`outline: 2px solid ink`).
- Motion is motivated: entrance once, transitions that show a change of state, nothing looping for decoration.
  Respect `prefers-reduced-motion`.

## The critique checklist (use it on every PNG)

1. Any label clipped, overlapping or under 11px?
2. Does each colour mean exactly one thing on this tile and on the Liveboard?
3. Is every number traceable to a row, and every projection labelled?
4. Any banned string, glyph or phrase?
5. Does the tooltip name the thing under the pointer with its value and its comparison?
6. Would the tile still read at half the width and with one region or one item type selected?
