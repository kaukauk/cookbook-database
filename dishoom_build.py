#!/usr/bin/env python3
"""Dishoom (Shamil Thakrar et al.) parser.

Book-specific HTML structure:
  - Recipe titles: <p class="C646">…</p>  (main chapters)
                   <p class="C887"|"C887p">…<span class="C892">…</span></p>
                   (preparatory, breads, chutneys)
  - Anchors inside titles: <span id="id_NN"> or <span id="page_NNN"> — used by
    cross-references like href="23_Preparatory_recipes.xhtml#id_51"
  - Yield: first <p class="C654"><strong>SERVES X|MAKES X|YIELDS X</strong></p>
  - Ingredients: <p class="C659">…</p> and <p class="C674">…</p> (last in block)
  - Subsection headers: <p class="C654"><strong>FOR THE …|TO SERVE|TO ASSEMBLE|
                       STOVE METHOD|OVEN METHOD|VARIATIONS</strong></p>
    (same class as yield, distinguished by NOT starting with SERVES/MAKES/YIELDS)
  - Method steps: <p class="C693">…</p>  — marks end of ingredients
  - Cross-refs: <a href="FILE.xhtml#ANCHOR">text</a>
                target file 22 (Ingredients & cookery guidance) is NOT a recipe.

Recipe IDs are namespaced as f"{chapter_file}#{anchor}" because the book
re-uses page/id values across files.
"""
import re, os
from cookbook_common import (
    clean_text, clean_title, extract_ingredient_name, canonicalize,
    grams_for, expand_subrecipes,
)

XHTML = '/tmp/dishoom_epub/OEBPS/xhtml'

BOOK_META = {
    'slug':   'dishoom',
    'title':  'Dishoom: From Bombay with Love',
    'author': 'Shamil Thakrar, Kavi Thakrar, Naved Nasir',
    'source_path': '/home/kaustubh/Documents/books/cookbooks/India/Dishoom.epub',
    'notes':  'C646 (main) / C887 + C892 (preparatory) recipe titles; cross-file href anchors.',
}

CHAPTER_CATEGORIES = {
    '12_Breakfast':                              ('breakfast',   'Breakfast'),
    '13_Mid_morning_snacks':                     ('mid_morning', 'Mid-morning Snacks'),
    '14_Lunch':                                  ('lunch',       'Lunch'),
    '15_Afternoon_refreshments':                 ('afternoon',   'Afternoon Refreshments'),
    '16_Sunset_snacks':                          ('snacks',      'Sunset Snacks'),
    '17_First_dinner':                           ('dinner',      'First Dinner'),
    '18_Second_dinner':                          ('dinner',      'Second Dinner'),
    '19_Third_dinner':                           ('dinner',      'Third Dinner'),
    '20_Pudding':                                ('dessert',     'Pudding'),
    '21_Tipples':                                ('drink',       'Tipples'),
    '23_Preparatory_recipes':                    ('prep',        'Preparatory Recipes'),
    '24_Breads':                                 ('bread',       'Breads'),
    '25_Chutneys__pickles___dressings':          ('chutney',     'Chutneys, Pickles & Dressings'),
}

# Title paragraph: either C646 (main) or C887/C887p (prep/breads/chutneys)
TITLE_RE = re.compile(
    r'<p\s+class="(C646|C887|C887p)"[^>]*>(.*?)</p>(.*?)(?=<p\s+class="C(?:646|887p?)"|\Z)',
    re.DOTALL)
ANCHOR_IN_TITLE = re.compile(r'<span\s+id="(id_\d+|page_\d+)"')
# Yield: <p class="C654"><strong>SERVES 4</strong></p>
YIELD_RE = re.compile(
    r'<p\s+class="C654"[^>]*>\s*<strong>\s*(SERVES|MAKES|YIELDS?)\s+([^<]+?)\s*</strong>\s*</p>',
    re.I)
# Ingredient line: C659 or C674
INGRED_RE = re.compile(r'<p\s+class="(C659|C674)"[^>]*>(.*?)</p>', re.DOTALL)
# Method step: marks end of ingredient block
METHOD_RE = re.compile(r'<p\s+class="C693"[^>]*>')
HREF_RE = re.compile(r'<a\s+href="([^"]+\.xhtml)#([^"]+)"[^>]*>([^<]+)</a>', re.I)

NON_RECIPE_FILES = {'22_Ingredients___cookery_guidance', 'nav'}

# Heuristic: title text that's clearly NOT a recipe (the book sometimes uses
# C887 for chapter/section banners like "PREPARATORY RECIPES" itself).
NON_RECIPE_TITLES = {
    'preparatory recipes', 'breads', 'chutneys, pickles & dressings',
    'index', 'contents', 'gratitude',
    # Dishoom uses 'ON …' section banners with C646 styling — not recipes
    'on biryani', 'on grilling', 'on cocktail making',
}

# Cross-ref link texts that don't name an ingredient. Fall back to parsing the
# rest of the ingredient line when the link text is one of these.
UNINFORMATIVE_LINK_TEXTS = {
    'here', 'see here', 'this page', 'previous page', 'next page',
    'above', 'below', 'right', 'left', 'opposite',
    'the recipe', 'recipe', 'see recipe', 'see note', 'see notes',
    'see step 1', 'see step', 'see tip', 'as before', 'as above',
}

# Method-method subsection headers that some Preparatory recipes use to give
# alternate yields per method (e.g. STOVE METHOD MAKES 1 QUANTITY). We ignore
# these for yield extraction and only take the first SERVES/MAKES we see.

def parse_makes(text):
    """Parse '170g', '300ml', '1.5 LITRES', '4', 'ABOUT 8' → (amount, unit)."""
    t = text.strip().lower()
    t = re.sub(r'^(?:about|approximately|approx\.?|around)\s+', '', t)
    # number (with optional decimal/fraction)
    m = re.match(r'^(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)\s*([a-z]+)?', t)
    if not m:
        return None, ''
    num_str = m.group(1)
    if '–' in num_str or '-' in num_str:
        parts = re.split(r'[-–]', num_str)
        amt = (float(parts[0]) + float(parts[1])) / 2
    else:
        amt = float(num_str)
    unit = (m.group(2) or '').strip()
    # Normalize unit aliases
    if unit in ('litre','litres','liter','liters'):
        unit = 'l'
    return amt, unit

def extract_title(heading_html):
    """Clean recipe title from heading HTML. Returns title in normalized
    Title Case (since most headings are ALL CAPS in the source).

    Uses clean_title (not clean_text) because titles often have spans that
    split single words: '<span>O</span>N BIRYANI' must yield 'ON BIRYANI'
    not 'O N BIRYANI'."""
    t = clean_title(heading_html)
    # Collapse "MASALA" → "Masala". Many recipe names contain words that
    # should stay capitalized (Bombay, Dishoom) but for simplicity title-case
    # everything; cosmetic only — canonicalization is lower-cased.
    if t == t.upper() and len(t) > 2:
        t = t.title()
    # Fix common title-case glitches
    t = t.replace("'S", "'s").replace("'T", "'t")
    return t.strip()

def parse_all_recipes():
    """Pass 1: extract raw recipes from each chapter."""
    recipes = []
    for fname in sorted(os.listdir(XHTML)):
        base = fname.replace('.xhtml','')
        if base not in CHAPTER_CATEGORIES: continue
        cat, cat_label = CHAPTER_CATEGORIES[base]
        with open(f'{XHTML}/{fname}') as f:
            content = f.read()
        for m in TITLE_RE.finditer(content):
            heading_html = m.group(2)
            body = m.group(3)
            title = extract_title(heading_html)
            if not title or title.lower() in NON_RECIPE_TITLES:
                continue
            # All anchor IDs found in the title — used for cross-ref resolution
            anchor_ids = ANCHOR_IN_TITLE.findall(heading_html)
            # Primary external id: prefix with file so it's unique book-wide
            primary_anchor = anchor_ids[0] if anchor_ids else None
            rec_id = f'{base}#{primary_anchor}' if primary_anchor else None
            # Yield
            serves_amount = serves_unit = serves_keyword = None
            ym = YIELD_RE.search(body)
            if ym:
                serves_keyword = ym.group(1).upper().rstrip('S') + 'S' if not ym.group(1).upper().endswith('S') else ym.group(1).upper()
                # Normalize to SERVES / MAKES / YIELDS
                if serves_keyword.startswith('SERVE'): serves_keyword = 'SERVES'
                elif serves_keyword.startswith('MAKE'): serves_keyword = 'MAKES'
                else: serves_keyword = 'YIELDS'
                a, u = parse_makes(ym.group(2))
                serves_amount = a
                serves_unit = u
            # Ingredients: every C659/C674 in the body, BEFORE the first C693 (method).
            method_match = METHOD_RE.search(body)
            ingredient_zone = body[:method_match.start()] if method_match else body
            ingredients_raw = []
            for _, raw_item in INGRED_RE.findall(ingredient_zone):
                line = clean_text(raw_item)
                if not line: continue
                ref_pairs = []  # list of (target_file_base, anchor, link_text)
                for hm in HREF_RE.finditer(raw_item):
                    target_file = hm.group(1).replace('.xhtml','')
                    if target_file in NON_RECIPE_FILES: continue
                    ref_pairs.append((target_file, hm.group(2), hm.group(3).strip()))
                ingredients_raw.append({
                    'line': line,
                    'ref_pairs': ref_pairs,
                    'raw_html': raw_item,
                })
            recipes.append({
                'title': title,
                'category': cat,
                'category_label': cat_label,
                'chapter_file': base,
                'rec_id': rec_id,
                'all_anchor_ids': [f'{base}#{a}' for a in anchor_ids],
                'region': None,
                'serves_keyword': serves_keyword,
                'serves_amount': serves_amount,
                'serves_unit': serves_unit,
                'ingredients_raw': ingredients_raw,
            })
    return recipes

def build_subrecipe_index(recipes):
    """Build map: any anchor id → recipe. A recipe is a sub-recipe iff one of
    its anchors is referenced from another recipe's ingredient line."""
    by_anchor = {}
    for r in recipes:
        for aid in r['all_anchor_ids']:
            by_anchor[aid] = r
    referenced = set()  # of anchor ids (namespaced 'file#anchor')
    for r in recipes:
        for ing in r['ingredients_raw']:
            for tf, anch, _txt in ing['ref_pairs']:
                aid = f'{tf}#{anch}'
                if aid in by_anchor and by_anchor[aid] is not r:
                    referenced.add(aid)
    # mark sub-recipe flag
    for r in recipes:
        r['is_subrecipe'] = any(aid in referenced for aid in r['all_anchor_ids'])
    # title lookup for canonicalize: lowercase title → recipe
    sub_titles = {r['title'].lower(): r for r in recipes if r['is_subrecipe']}
    return by_anchor, sub_titles, referenced

def resolve_ingredients(recipes, by_anchor, sub_titles):
    subrecipe_title_lookup = set(sub_titles.keys())
    NON_INGREDIENT_PATTERNS = (
        'skewers', 'toothpicks', 'butcher twine', 'parchment paper',
        'aluminium foil', 'aluminum foil', 'cheesecloth', 'muslin',
        'banana leaves for wrapping',
    )
    for r in recipes:
        resolved = []
        for ing in r['ingredients_raw']:
            line = ing['line']
            line_lower = line.lower()
            if any(p in line_lower for p in NON_INGREDIENT_PATTERNS):
                continue
            amount, unit, name_core = extract_ingredient_name(line)
            via_rec_id = None
            is_subref = False
            # If line cross-references a recipe, use the LINK TEXT as the
            # canonical (more precise than the recipe title when one recipe
            # bundles multiple distinct sub-recipes, e.g. "Garlic & Ginger
            # Pastes" is referenced as "garlic paste" or "ginger paste").
            # Fall back to parsing the line if link text is uninformative
            # ("here", "see note", "above", etc).
            use_link = False
            if ing['ref_pairs']:
                tf, anch, link_text = ing['ref_pairs'][0]
                aid = f'{tf}#{anch}'
                lt = re.sub(r'\s+', ' ', link_text).strip().lower().rstrip('.,;:')
                if lt in UNINFORMATIVE_LINK_TEXTS or len(lt) < 3:
                    # uninformative — fall through to canonicalize(name_core)
                    pass
                else:
                    use_link = True
                    canon_lt = canonicalize(lt, subrecipe_title_lookup)
                    if aid in by_anchor:
                        sub = by_anchor[aid]
                        via_rec_id = sub.get('rec_id')
                        is_subref = True
                        canon = canon_lt if canon_lt and canon_lt != lt else lt
                        # If the sub-recipe is single-anchor and link text equals
                        # its title, prefer the title (more uniform).
                        if len(sub['all_anchor_ids']) == 1 and canon in (sub['title'].lower(), lt):
                            canon = sub['title'].lower()
                    else:
                        canon = canon_lt or lt
            if not use_link:
                canon = canonicalize(name_core, subrecipe_title_lookup)
                if canon is None:
                    continue
                if canon in subrecipe_title_lookup:
                    sub = sub_titles[canon]
                    via_rec_id = sub.get('rec_id')
                    is_subref = True
            grams, used_unit, normalized, src = grams_for(canon, amount, unit, line)
            resolved.append({
                'raw': line,
                'amount': amount,
                'unit': unit,
                'name_raw': name_core,
                'canonical': canon,
                'grams_est': grams,
                'normalized': normalized,
                'gram_source': src,
                'is_subrecipe_ref': is_subref,
                'via_rec_id': via_rec_id,
            })
        r['ingredients'] = resolved

def main(con):
    from cookbook_common import populate_book
    print('[dishoom] Parsing recipes…')
    recipes = parse_all_recipes()
    print(f'[dishoom]   raw recipes: {len(recipes)}')
    print('[dishoom] Building sub-recipe index…')
    by_anchor, sub_titles, referenced = build_subrecipe_index(recipes)
    n_sub = sum(1 for r in recipes if r['is_subrecipe'])
    print(f'[dishoom]   sub-recipes identified: {n_sub}')
    print('[dishoom] Resolving ingredients…')
    resolve_ingredients(recipes, by_anchor, sub_titles)
    n_lines = sum(len(r['ingredients']) for r in recipes)
    print(f'[dishoom]   direct ingredient lines: {n_lines}')
    print('[dishoom] Expanding sub-recipes…')
    # Need a by_rec_id map for expansion. Use primary rec_id.
    by_rec_id = {r['rec_id']: r for r in recipes if r.get('rec_id')}
    expand_subrecipes(recipes, by_rec_id, sub_titles)
    n_exp = sum(len(r.get('expanded_ingredients',[])) for r in recipes)
    print(f'[dishoom]   expanded ingredient rows: {n_exp}')
    print('[dishoom] Writing to DB…')
    populate_book(con, BOOK_META, recipes)
    print(f'[dishoom] Done: {len(recipes)} recipes inserted.')

if __name__ == '__main__':
    from cookbook_common import init_db, finalize_counts, DB_PATH
    con = init_db(DB_PATH)
    main(con)
    finalize_counts(con)
    print(f'DB: {DB_PATH}')
