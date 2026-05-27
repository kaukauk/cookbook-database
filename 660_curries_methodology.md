# 660 Curries — Ingredient Analytics: Methodology (v2)

## 1. Source & extraction

- Source: `660_Curries.epub`, unpacked to OPF/XHTML.
- 16 chapter files parsed. Every recipe is delimited by `<h3 class="h3a">` or `<h3 class="h3b">` (v1 missed all h3a recipes — fixed in v2, gaining 78 recipes).
- Each recipe is keyed by its `<a id="rec*"/>` anchor as `external_id`. These anchors are how the EPUB resolves cross-references; preserving them is what makes sub-recipe expansion possible.
- Sub-heading classes capture additional title parts: `h3c` (subtitle), `h3d` (regional style), `h3e` (secondary title).
- Yield/servings come from `<span class="RY">SERVES N</span>` (also `MAKES`, `YIELDS`).
- Ingredient lines are `<p class="item">…</p>` and `<p class="itemb">…</p>`.

**Recipe count:** 666 recipes total. After classifying which ones are sub-recipes (referenced from another recipe's ingredient list), we have ~630 main recipes and ~36 sub-recipes (mostly Chapter 2 spice blends and pastes, plus a few cross-referenced sauces).

## 2. Ingredient line parsing

Each `<p class="item">` line is split into `(amount, unit, name_core)`:

- **Amount** supports integers, decimals, unicode fractions (¼ ½ ¾ etc.), mixed forms (`2 ½` or `2½`), ASCII fractions (`1/2`), and ranges (`2 to 3` → midpoint).
- **Unit** matches against mass (g, oz, lb, kg), volume (tsp, tbsp, cup, fl oz, pint, quart), and count units (clove, sprig, leaf, pinch, can, package, etc.).
- **Name** has trailing prep words stripped (chopped, sliced, minced, peeled, picked over, soaked, stems removed, etc.) and trailing modifiers stripped (to taste, for garnish, for frying, divided). Parentheticals are removed. Semicolons split on alternatives.

## 3. Canonicalization

Curated synonym table: ~210 canonical heads, ~750 alias forms. Resolution order:
1. Sub-recipe titles (lowercased) — if the line is a cross-reference to another recipe in this book.
2. Exact alias match.
3. Strip a leading descriptor (red/green/dried/whole/...) and retry.
4. Trailing n-grams (last 3, 2, 1 words).
5. Substring match against any canonical (longest-first, so "dried red chile" wins over "red chile").
6. Fallback: raw lowercase name.

## 4. Quantity → grams normalization (v2: real density table)

v1 used 1 cup = 240 g for everything. v2 uses a curated **density table** (g per 240 ml cup) of ~140 entries:

- Powders ~95–145 g/cup (turmeric 130, cumin 95, ground coriander 85, chickpea flour 92).
- Whole seeds 90–150 g/cup (mustard 140, cumin 95, fenugreek 150, sesame 144).
- Flours 92–165 g/cup (chickpea flour 92, AP flour 125, semolina 165).
- Sugars/salts 200–300 g/cup (salt 292, sugar 200, jaggery 210).
- Rices/lentils dry ~190–210 g/cup.
- Liquids 218–245 g/cup (oil 218, water/milk 240/245, coconut milk 226, honey 340).
- Fresh herbs (chopped) 9–28 g/cup (cilantro 16, mint 10, basil 24).
- Chopped vegetables 30–180 g/cup.

For **count units** (cloves, leaves, pods, sprigs, "1 small onion"), a per-piece weight table is used: garlic clove 5 g, cardamom pod 0.3 g, bay leaf 0.1 g, curry leaf 0.05 g, dried red chile 1 g, medium onion 110 g, medium tomato 123 g, large egg 50 g, etc.

If neither density nor piece weight is known, `grams_est` is left `NULL` but the ingredient still counts toward frequency / co-occurrence / role metrics.

## 5. Sub-recipe detection and expansion

**The model:**
- A sub-recipe is any recipe whose `<a id="rec*"/>` is referenced from another recipe's ingredient line via `<a href="chapter*.html#rec*">`. The `<span class="link">recipe</span>` anchor text is required (skipping `box`, `Tips`, etc.).
- Sub-recipes are stored in BOTH tables:
  - `recipe` row with `is_subrecipe = 1` and their own ingredient list.
  - `ingredient` row with `is_subrecipe = 1` and `subrecipe_recipe_id` linking back. This makes them queryable as ingredients ("how many recipes use Ghee?" works just like "how many use turmeric?").

**Pantry staples** (ghee, whole-milk cheese / paneer, creamy homemade cheese, thick yogurt) are sub-recipes in the book but are **NOT expanded** — they're distinct culinary objects, not composed dishes. Marked via `ingredient.is_pantry_staple = 1`. They still appear as first-class queryable ingredients ("how many recipes use ghee?" works), but a recipe calling for "1 tbsp Ghee" does not get butter added to its expanded ingredient list, because in the kitchen ghee is its own ingredient. The recursive expansion also skips pantry staples — so if a spice blend uses ghee, the parent recipe gets the spice blend's other constituents expanded in, but ghee remains terminal.

**Expansion algorithm** (depth-first with cycle detection, max depth 5):
1. For each `recipe_ingredient` line that is a sub-recipe reference with amount `A` and unit (cups/tbsp/tsp/pint/quart):
2. Look up the sub-recipe's yield from its `<span class="RY">MAKES N cups</span>`.
3. Convert both amounts to cups and compute `scale = A_cups / yield_cups`.
4. For each ingredient in the sub-recipe, emit a new `recipe_ingredient` row in the parent with `source = 'expanded'`, multiplied by `scale`.
5. If a sub-ingredient is itself a sub-recipe reference, recurse.

**The `source` column distinguishes:**
- `direct` — written in the cookbook on that recipe's ingredient list.
- `expanded` — pipeline-added by scaling a sub-recipe's contents into the parent.

This gives you two views of every aggregate:
- **As-written** (direct only): how the cook reads the recipe.
- **Fully expanded** (direct + expanded): every constituent ingredient that ends up in the dish.

Example from the database: `cumin seeds` appears in **278 recipes directly**, but in **401 recipes after expansion** — the extra 123 come from spice blends and pastes that themselves contain cumin.

Trade-off: butter shows up in only 10 recipes directly but 186 after expansion, because the Ghee sub-recipe (referenced by 171 recipes) lists butter as its ingredient. Semantically ghee IS butter, so this is borderline double-counting — the source field lets queries decide.

## 6. Storage: SQLite

Primary store is `660_curries.db`. JSON (`660_curries_dataset.json`) is a read-only export from the DB.

**Schema (5 tables, 2 views):**

| table | purpose |
|---|---|
| `recipe` | One row per recipe (main + sub). `external_id` is the `rec*` anchor; `is_subrecipe` flag; yield_amount + yield_unit |
| `ingredient` | One row per canonical. `is_subrecipe` + `subrecipe_recipe_id` link sub-recipes back to their recipe row. Stores heat_sensitivity, density, piece weight, versatility |
| `ingredient_alias` | Every known alias → canonical |
| `ingredient_role` | Role priors (tempering / base_aromatic / ground_spice / finishing) |
| `recipe_ingredient` | Every appearance: direct or expanded. Has `via_recipe_id` and `scale_factor` for traceability |
| `v_ingredient_global_freq` (view) | Direct vs expanded counts |
| `v_ingredient_category_usage` (view) | Category × source breakdown |

## 7. Metrics computed (per ingredient)

1. **Global frequency** — direct and expanded variants.
2. **Category usage** — `count / total_in_category` per category, per source.
3. **Quantity stats** — n, mean, median, min, max, total grams (across all sources).
4. **Serving-weighted usage** — mean `serves` of recipes containing this ingredient vs global average.
5. **Conditional probabilities** — `P(ingredient | category)` and `P(category | ingredient)`.
6. **Co-occurrence** — top 10 most-frequently paired ingredients.
7. **Positional role** — heuristic identity-based classification (tempering / base_aromatic / ground_spice / finishing / unclassified). **Still a curated prior, not measured from instruction text** — upgrading this requires parsing the method paragraphs.
8. **Heat sensitivity** — heuristic prior (0 = robust, 1 = fragile).
9. **Versatility score** — `(categories_seen / total_categories) × ln(1 + recipe_count_expanded)`.

## 8. Derived analytics

- **Spice intensity per category** — mean number of distinct spice-set ingredients per recipe.
- **Heat level distribution** — total chile mass per recipe, bucketed (`none / low <1g / medium <5g / high ≥5g`). The thresholds are tighter than v1 because density-aware grams are now realistic.
- **Core ingredient set** — greedy set cover for ≥80% of main recipes. Two flavors (with and without salt+oil).
- **Regional clustering** — NOT computed. `region` field is captured; clustering is a downstream exercise.

## 9. Output files

| File | Purpose |
|---|---|
| `660_curries.db` | **Authoritative store.** SQLite, queryable from anything |
| `660_curries_dataset.json` | Read-only mirror of the DB for tools that prefer JSON |
| `660_curries_schema.sql` | The schema as a standalone DDL |
| `660_curries_ingredient_database.md` | Human-readable per-ingredient report |
| `660_curries_methodology.md` | This document |
| `660_curries_ingredients.txt`, `_by_type.txt` | Original flat lists (pre-pipeline) |

## 10. Headline numbers (v2)

- **666 recipes** parsed (vs 588 in v1 — h3a class was missed).
- **~36 sub-recipes** (Chapter 2 spice blends + cross-referenced sauces). Most-referenced: Ghee (171), Garlic Paste (79), Ginger Paste (67).
- **~310 distinct canonical ingredients**.
- **~7,500 direct ingredient rows + ~2,150 expanded rows** = ~9,650 `recipe_ingredient` records.
- Top 10 by expanded frequency: salt (619), cayenne (554), vegetable oil (482), cilantro (407), cumin seeds (401), turmeric (374), onion (292), coriander seeds (263), mustard seeds (259), ginger (256).
- Average servings: ~5.7.
- 80% greedy cover (excl. salt+oil): just `cayenne + cilantro + turmeric`.

## 11. Known limitations

- **Positional role and heat sensitivity are priors.** Not measured from instruction text. Would need NLP pass on method paragraphs.
- **Density table is comprehensive but not exhaustive.** ~140 entries cover all top ingredients; uncommon ones fall back to a 150 g/cup default for solids, 240 g/cup for liquids.
- **Sub-recipe expansion is unit-aware but limited to volume.** Lines like "1 tablespoon Ghee" expand cleanly; "1 pinch of Garam Masala" does not (no scale ratio available), so it's treated as scale=1.0 and flagged via `scale_known=0`.
- **Recursive expansion has max depth 5** — generous in practice (typical depth is 1, occasionally 2).
- ~~Ghee-as-butter double counting~~ — fixed by the `is_pantry_staple` flag (ghee no longer leaks into butter counts).
- **A handful of unusual phrasings** still survive as their own canonical (e.g. "cowpeas or whole green lentils, partially sprouted, or store-bought bean sprouts"). Each appears in 1 recipe, doesn't distort aggregates.
- **Regional clustering** still not computed.
