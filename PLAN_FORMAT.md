# How THIS_WEEK.md is built

The rules for the weekly plan, collected in one place. `THIS_WEEK.md` for 7-10 Oct 2026 is the
worked example. The file's end use is to be handed to another AI that loads it into Google Tasks.

## Weekly workflow

1. Propose the dishes, with starch and sides. Check `cooked_log.md` to avoid repeats.
2. User says what they like and asks for changes or substitutions.
3. Dishes confirmed: give the shopping list.
4. User says what they already have and any amendments.
5. Write the full day-by-day plan to `THIS_WEEK.md`. Shopping day is the day before the first dish.

## Quantities

- Baseline is 2 portions. Every amount inside a task is the exact cooking amount.
- The shopping list's Buy column is cook amount +25%, rounded up. The buffer never goes in the pot.
- Ingredients are counted once. Use the book's own ingredient lines for a dish (`source='direct'` in
  `cookbook.db`), not the expanded sub-recipe rows. A prep task owns its ingredients.

## Shopping list

- Two tables: **Buy**, and **Already have — check before leaving**.
- The check table covers only fresh items, freezer, tins and room-stored items. Ask each week what
  fresh items are on hand.
- Never listed, assumed full until the user says otherwise: everything in the jar system, oils, rice
  (basmati, parboiled ponni), atta, plain wheat flour, dried chickpeas.
- Never bought, made at home instead (list the raw input and schedule the prep): dahi, paneer, cashew
  cream (the standing substitute for double cream), tomato paste. Fresh curry leaves: dried only.
- Flag anything that has to be fetched from the room (see `kitchen_inventory.txt`).

## File layout

1. Title with the date range and "2 portions", the spoilage-order reasoning, and the overview table.
2. `## Instructions for the AI adding this to Google Tasks` (see below).
3. `## How to read this file`.
4. One `## <Day> <date>` section per day, starting with the shopping day, containing only
   `### TASK:` blocks. Nothing else sits under a day heading.

No "already cooked" list in this file; that lives in `cooked_log.md`.

## Task types and order

Within a day, tasks appear in the order they are done: usually main/side prep, pre-side, pre-main, starch, side,
main.

| Type | What it is |
|---|---|
| `shopping` | The two shopping tables. On the day before the first dish. |
| `main prep` / `side prep` | A sub-recipe the book assumes you have (pastes, blends, dahi, paneer, cashew cream, cooked or soaked legumes). Full ingredients and method, from the book, the web or own knowledge. |
| `pre-main` | Work that must happen ahead of that day's **main** but only makes sense shortly before cooking: thawing, rubbing or marinating with a rest, washing and drying, roasting something that has to cool, fetching from the room. |
| `pre-side` | The same thing for a **side**. A side is a standalone dish in its own right, so its ahead-of-time work is never folded into the pre-main. Title it `Pre-side — ...`. |
| `starch` | Always its own task and made from scratch, except frozen paratha. Rice is just the uncooked amount, in the rice cooker. |
| `side` | |
| `main` | |

- **Naming prep tasks.** Title and type say which dish the prep is for: `Main prep — <name>` or
  `Side prep — <name>`, by the first dish that uses it. If it has to sit on a different day from that
  dish for timing reasons (setting, soaking), prefix the dish's day: `Wed side prep — Dahi`,
  `Thurs main prep — Soak chickpeas`. Day words: Mon, Tues, Wed, Thurs, Fri, Sat, Sun. The Type field
  stays `main prep` or `side prep` without the day.
- A prep task is scheduled on the day of the **first** dish that uses it. Later dishes reuse the batch
  and say so under Reuses; no second task. Move it earlier only when it physically needs the lead
  time (dahi setting, soaking). Say what it is used in and how long it keeps.
- **Main and side are independent.** They are just two dishes made on the same day. A main task never
  refers to the side (no "serve with the raita", no side steps in its running order, no "reuses
  leftover side"), and a side never refers to the main. The starch may be mentioned in the main.
- Soaking gets its own prep task for every dal or legume.
- **Prep vs pre-main / pre-side.** Prep is a sub-recipe that keeps, so it can be made a day or more ahead.
  Pre-main and pre-side work is time- or space-sensitive: looking at it, you would not want to do it the day before or
  that morning. It is a common-sense call; use judgement.
- The goal for mains and sides: **nothing that slows the cooking down or makes the user wait.** No
  ahead-of-time work, no resting, cooling, thawing or soaking inside them. If a step forces a wait,
  move it to that dish's pre-main or pre-side. Their mise en place refers to the result ("the rubbed salmon").

## Fields on a task

`### TASK: <Type> — <name>`, then a bullet list of the fields that apply, in this order:

- **Type**
- **Running order** — on a main or a side: the sequence of that dish's own tasks (its prep, its
  pre-main or pre-side, and for the main the starch). Never the other dish's.
- **Note** — if needed.
- **For / When** — pre-main and pre-side tasks.
- **Makes / Used in / Why today** — prep tasks.
- **Reuses** — a batch made on an earlier task.
- **Time**
- **Fetch from the room**
- **Stove** — pans, pots and pressure cookers, saying when a lid is needed; then, after a semicolon,
  the oils or fats, named without an amount.
- **Cupboard equipment** — everything else fetched from the cupboard: utensils, hand blender, cast
  iron spice grinder, and the specific Sujata jar.
- **Appliances** — worktop appliances only: stand mixer, Sujata mixer grinder, rice cooker, smoothie
  blender, microwave.

Then, where they apply: `**Prep recipes (made above / earlier)**`, `**Mise en place**`, `**Method**`.
Use only equipment listed in `kitchen_inventory.txt`.

## Mise en place

- It replaces the ingredient list. One line per container, with prep state and exact amount.
- Whatever enters the pan at the same moment shares a container.
- Container words: `Bowl`, `Small bowl`, `Spice cup`, `Cup` (plus `Plate`, or a named vessel such as
  `Sujata chutney jar`, unnumbered). Never "pinch bowl".
- Numbered per type, each starting at 1: `Bowl 1`, `Bowl 2`, `Small bowl 1`, `Cup 1`, `Spice cup 1`.
- Order: largest amounts first; containers of spices and other jar-system items together at the end.
- Water is pre-measured in its own cup whenever the recipe adds it, including for deglazing or
  rinsing a jar.
- Oils are not in the mise en place. They are on the Stove line.
- Whole spices are ground fresh. In a container that needs it, the first sub-line is
  `- dry grind: <whole spices>` alone on its line, followed by `- then add: <everything else>`.
  Powders and whole items that go in at the same time share the cup.
- Always write `dry grind` (cast iron spice grinder, strictly dry) or `wet grind` / `blend` (Sujata or
  hand blender). Never a bare "grind".
- Nuts go in the Sujata when there is more than a little. Sujata jars, smallest to largest: chutney
  jar, dry grinding jar, wet grinding jar.

## Method

- Numbered steps. Refer to ingredients by name ("add the mustard seeds"), never by container number.
- Do not repeat amounts from the mise en place. The exception is oil: give its amount in the step.
- Name the actual pan from the Stove line.

## The prompt section for the other AI

Every `THIS_WEEK.md` carries `## Instructions for the AI adding this to Google Tasks` straight after
the overview table. Update the task count in it each week. It tells the AI to:

- Create exactly one task per `### TASK:` heading and nothing else; no merging, splitting or skipping.
  State the expected count.
- Fall back to all-day Calendar events if Google Tasks is unavailable, and say so.
- Set the due date from the `## ` day heading, with the year, no time of day, and not move tasks earlier.
- Title: the text after `### TASK: `, prefixed with its position in the day (`1/6 Main prep — ...`).
- Notes: the whole task body, every field, copied exactly as plain text with its structure kept. No
  scaling, rounding, unit conversion, reordering or summarising.
- Shopping task: both tables in full; the Buy column is the amount to buy and already includes the buffer.
- Keep each Running order on its own task; never mix the main and the side.
- Finish by listing the tasks created, grouped by day, and flag anything ambiguous instead of guessing.
