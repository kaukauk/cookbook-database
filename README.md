# cookbook-database

A SQLite database of recipes and ingredients built from two Indian cookbooks (*660 Curries* and *Dishoom*), plus scripts that use it to plan weekly dinners around what's in my pantry.

The build pipeline parses each cookbook's EPUB, extracts every recipe's ingredient lines, normalises quantities to grams, maps hundreds of ingredient spellings onto canonical names, and links sub-recipes (spice blends, pastes, sauces) so a recipe's full ingredient list can be expanded recursively.

## What it does

- **EPUB parsing:** finds recipe boundaries, titles, yields and ingredient lines from the books' XHTML markup, keyed by each recipe's anchor ID.
- **Ingredient parsing:** splits each line into amount, unit and ingredient name. It handles unicode and ASCII fractions, mixed numbers and ranges, and strips prep words ("finely chopped", "to taste").
- **Canonicalisation:** a curated synonym table (~210 canonical ingredients, ~750 aliases) with fallback matching on descriptors, n-grams and substrings.
- **Gram estimates:** volume and count units are converted to grams using a density table and per-piece weights.
- **Sub-recipe expansion:** when a recipe calls for another recipe (e.g. a garam masala blend), that recipe's ingredients are scaled and expanded in, with cycle detection and a depth limit.
- **Analysis:** `_analysis/makeable*.py` works out which recipes can be cooked with the current pantry and which missing ingredients block the most recipes.

The database has 809 recipes. It stores ingredient lines only, not cooking methods.

## Schema

| Table | Contents |
|---|---|
| `book` | Source cookbooks |
| `recipe` | Title, category, region, yield, and whether it's a sub-recipe |
| `ingredient` | Canonical ingredients, with pantry-staple and sub-recipe flags and usage counts |
| `ingredient_alias` | Alias → canonical name mappings |
| `recipe_ingredient` | Parsed lines: raw text, amount, unit, gram estimate, and whether the row is direct or expanded from a sub-recipe |

There are also views for ingredient frequency, overall and per book or category.

## Running it

Requires Python 3 (standard library only). The source EPUBs aren't included, so set `DB_PATH` in `cookbook_common.py` and `source_path` in each `*_build.py` to your own paths, then:

```
python build_all.py
```

This drops and rebuilds `cookbook.db` and prints a summary of books, recipe counts and the most common ingredients.

## Other files

- `660_curries_methodology.md`: detailed notes on the parsing and canonicalisation approach
- `weeks/`, `PLAN_FORMAT.md`, `cooked_log.md`, `kitchen_inventory.txt`: my weekly meal plans and the pantry data they're built from
