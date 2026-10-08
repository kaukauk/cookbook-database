# dinner-plan

Cookbook database + meal planning. Moved here from `kaustubh-pc-arch:~/Documents/GitHub/cookbook-database`
on 6 Oct 2026; full git history came with it.

## What's here

| File | What it is |
|---|---|
| `cookbook.db` | SQLite, 809 recipes: 660 Curries (652 non-sub) + Dishoom. Ingredients only, **no methods**. |
| `kitchen_inventory.txt` | **Source of truth** for what's in the kitchen vs the room, substitutions, starch rules. |
| `jar_storage_system.txt` | The 63-jar storage system across 7 sizes, plus tubs/bags and workflow rules. |
| `makeable_recipes.txt` | Which recipes the jar system covers, by category. |
| `current-ingredients.txt` | Original pantry dump the whole thing was built from. |
| `shopping_list.txt` | Jar-system build-out shopping list (annotated: `/` done, `x` outstanding). |
| `cookbook_common.py`, `*_build.py` | The DB build pipeline. |
| `_analysis/makeable*.py` | Makeability scripts written 6 Oct: available-set model + blocker attribution. |
| `_claude-archive/` | Chat transcript and Claude memories from the move. |
| `THIS_WEEK.md` | Current meal plan. |
| `cooked_log.md` | Dishes already cooked, so weekly selection doesn't repeat them. |

## Gotchas

- **Sub-recipes are stored AS ingredients.** `ingredient.is_subrecipe=1` with `subrecipe_recipe_id`
  pointing at the component recipe. Spice blends, pastes and paneer are under *descriptive* canonical
  names, so `WHERE title LIKE '%garam masala%'` will wrongly tell you something is missing. Follow the links.
- **Methods are not in the DB.** They come from `660_Curries.epub`, still only on kaustubh-pc-arch at
  `~/Documents/books/cookbooks/India/`. Unzip and read `ops/xhtml/chapter*.html`.
- **Rice rule:** basmati or parboiled ponni only.
- **Always flag room-stored items** when giving a recipe — see `kitchen_inventory.txt`.

## Makeability as of 6 Oct 2026

- Kitchen jars only: **521 / 652** (80%)
- Including the 7 room-stored items: **572 / 652** (88%)
- Biggest single win left: move **rice flour** to the kitchen (19 recipes)

## Diet context for planning

Breakfast is fixed and large: ~1052 kcal, 39 g protein, 20 g fibre, zero vegetables
(90 g oats, 350 ml whole milk, 35 g peanut butter, 100 g yoghurt, 80 g banana, 100 g frozen berries,
20 g honey, 10 g chia) + multivitamin + vitamin D, with a protein scoop planned (~+25 g).
Target 2000-2500 kcal.

So dinner should carry: **vegetables and potassium** (the only real gap), and **oily fish once or
twice a week** for EPA/DHA, since chia only provides ALA. Dinner does **not** need to chase protein
or calories. Recommended breakfast trims: oats 90 -> 65 g, milk 350 -> 250 ml, drop the honey.
