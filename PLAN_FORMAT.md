# How a weekly plan is built

The rules for the weekly plan, collected in one place. `weeks/2026-10-19.md` is the
worked example. The file's end use is to be handed to another AI that loads it into Google Tasks.

## Weekly workflow

1. Propose the dishes, with starch and sides. Check `cooked_log.md` to avoid repeats.
2. User says what they like and asks for changes or substitutions.
3. Dishes confirmed: give the shopping list.
4. User says what they already have and any amendments.
5. Write the full day-by-day plan to a new file per week, `weeks/<shopping day>.md` (e.g.
   `weeks/2026-10-19.md`). Never overwrite an earlier week. Shopping day is the day before the first dish.

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

Within a day, tasks appear in the order they are done: usually make-ahead, prep, pre-side, pre-main,
starch, side, main.

| Type | What it is |
|---|---|
| `shopping` | The two shopping tables. On the day before the first dish. |
| `make-ahead main` / `make-ahead side` | **Keeps, and takes 30 minutes or more** (mostly waiting): dahi, paneer, thick yogurt, tomato paste, cashew cream, cooked legumes. Has a **Keeps** line so the user can move it to any earlier free day. |
| `main prep` / `side prep` | **Keeps, under 30 minutes**: a quick sub-recipe that could be done earlier (ginger paste, fried onion paste). Expected to be rare. |
| `pre-main` | **Doesn't keep, 30 minutes or more**: a wait that must happen just before that day's **main** can start. Thawing; making a marinade and letting the fish sit in it; soaking; a simmer of several hours. A dish can have **more than one**. |
| `pre-side` | The same thing for a **side**. A side is a standalone dish in its own right, so its ahead-of-time work is never folded into the pre-main. Title it `Pre-side — ...`. |
| `starch` | Always its own task and made from scratch, except frozen paratha. Rice is just the uncooked amount, in the rice cooker. |
| `side` | |
| `main` | |

- **Naming make-ahead and prep tasks.** Title and type say which dish it is for, by the first dish
  that uses it: `Make-ahead main — Paneer`, `Side prep — Ginger paste`. If it sits on a different day
  from that dish for timing reasons, prefix the dish's day: `Tues make-ahead side — Dahi`. Day words:
  Mon, Tues, Wed, Thurs, Fri, Sat, Sun. The Type field has no day.
- **Fetching from the room is never a task**: it is the dish's `Fetch from the room` line.
- A make-ahead or prep task is scheduled on the day of the **first** dish that uses it. Later dishes reuse the batch
  and say so under Reuses; no second task. Move it earlier only when it physically needs the lead
  time (dahi setting, soaking). Say what it is used in and how long it keeps.
- **Main and side are independent.** They are just two dishes made on the same day. A main task never
  refers to the side (no "serve with the raita", no side steps in its running order, no "reuses
  leftover side"), and a side never refers to the main. The starch may be mentioned in the main.
- Soaking every dal or legume gets its own task. It is a mandatory wait, so it is a pre-main (or
  pre-side), not a prep. When it sits on the day before, prefix the dish's day: `Thurs pre-main — Soak chickpeas`.
- **Classifying work done before a dish** (user, 19 Oct 2026). Two questions: does it keep (could it be
  done on any earlier day)? Does it take 30 minutes or more, mostly waiting?

  | | Keeps | Must be just before cooking |
  |---|---|---|
  | 30 min or more | make-ahead | pre-main / pre-side |
  | under 30 min | prep | in the dish itself |

  Making a marinade is part of the marinating pre-main. Anything doable while cooking (boiling eggs,
  toasting and grinding spices, roasting nuts, frying paneer, steaming a paste) is in the dish,
  ordered to overlap. Think like a chef cooking it.
- The goal for mains and sides: **no idle waiting**. A mandatory wait that can't be overlapped with
  other steps goes in a pre-main or pre-side; work that can be overlapped stays in the dish.
  Their mise en place refers to the result of any pre-task ("the marinated mackerel").

## Spice blends

- **No advance batches.** Make a blend only in the amount needed for this week: just the dish's amount
  if only one dish uses it, or enough for every dish this week that uses it. Never a jar to keep for
  later.
- A blend for one dish is made inside that dish as part of its mise en place: a spice cup with a
  `dry grind:` line (toasted first in the method if the recipe toasts it). It is not a prep task.
- A blend used by more than one dish this week is a prep task on the day of the first dish, sized
  for the week (make-ahead if it takes 30 minutes or more).
- Grinder choice: small amounts of dry spices go in the cast iron spice grinder. A large amount of dry
  spices, or anything oily, goes in the Sujata (dry grinding jar). With per-dish batches this should
  almost always be the cast iron grinder.

## Fields on a task

`### TASK: <Type> — <name>`, then a bullet list of the fields that apply, in this order:

- **Type**
- **Running order** — on a main or a side: the sequence of that dish's own tasks (its make-ahead and prep, its
  pre-main or pre-side, and for the main the starch). Never the other dish's.
- **Note** — if needed.
- **For / When** — pre-main and pre-side tasks.
- **Makes / Used in / Keeps / Why today** — make-ahead and prep tasks.
- **Reuses** — a batch made on an earlier task.
- **Time**
- **Fetch from the room**
- **Stove** — pans, pots and pressure cookers, saying when a lid is needed; then, after a semicolon,
  the oils or fats, named without an amount.
- **Cupboard equipment** — everything else fetched from the cupboard: utensils, hand blender, cast
  iron spice grinder, and the specific Sujata jar.
- **Appliances** — worktop appliances only: stand mixer, Sujata mixer grinder, rice cooker, smoothie
  blender, microwave.

Then, where they apply: `**Make-ahead (made above / earlier)**` or `**Prep (made above / earlier)**`, `**Mise en place**`, `**Method**`.
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

Every weekly plan carries `## Instructions for the AI adding this to Google Tasks` straight after
the overview table. Update the task count in it each week. It tells the AI to:

- Create exactly one task per `### TASK:` heading and nothing else; no merging, splitting or skipping.
  State the expected count.
- Fall back to all-day Calendar events if Google Tasks is unavailable, and say so.
- Set the due date from the `## ` day heading, with the year, no time of day, and not move tasks earlier.
- Title: the text after `### TASK: `, prefixed with its position in the day (`1/6 Make-ahead main — ...`).
- Notes: the whole task body, every field, copied exactly as plain text with its structure kept. No
  scaling, rounding, unit conversion, reordering or summarising.
- Shopping task: both tables in full; the Buy column is the amount to buy and already includes the buffer.
- Keep each Running order on its own task; never mix the main and the side.
- Finish by listing the tasks created, grouped by day, and flag anything ambiguous instead of guessing.
