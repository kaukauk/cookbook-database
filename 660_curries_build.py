#!/usr/bin/env python3
"""660 Curries parser. Calls into cookbook_common for canonicalization,
density tables, sub-recipe expansion, and DB writes.

Book-specific:
  - EPUB chapter map
  - HTML class names (h3a/h3b/h3bno/h3d+h3e/h3f, RY, item/itemb)
  - rec_* anchor format for cross-references
"""
import re, os, glob
from cookbook_common import (
    clean_text, extract_ingredient_name, canonicalize,
    grams_for, expand_subrecipes,
    SYNONYMS, ALIAS_TO_CANON, CANONICAL_INGREDIENTS,
    parse_amount, FRAC,
)

XHTML = '/tmp/epub_extract/ops/xhtml'

BOOK_META = {
    'slug':   '660_curries',
    'title':  '660 Curries',
    'author': 'Raghavan Iyer',
    'source_path': '/home/kaustubh/Documents/books/cookbooks/India/660_Curries.epub',
    'notes':  'h3a/h3b recipe boundaries with rec_* anchors; chapter2 is sub-recipe spice-blend chapter.',
}

CHAPTER_CATEGORIES = {
    'chapter2':  ('spice_blend',  'Spice Blends and Pastes'),
    'chapter3':  ('appetizer',    'Appetizer Curries'),
    'chapter3a': ('appetizer',    'Appetizer Curries'),
    'chapter4':  ('poultry',      'Poultry, Game & Egg Curries'),
    'chapter5':  ('meat',         'Beef, Lamb & Pork Curries'),
    'chapter6':  ('seafood',      'Fish & Seafood Curries'),
    'chapter7':  ('paneer',       'Paneer Curries'),
    'chapter8':  ('legume',       'Legume Curries'),
    'chapter8a': ('legume',       'Legume Curries'),
    'chapter8b': ('legume',       'Legume Curries'),
    'chapter9':  ('vegetable',    'Vegetable Curries'),
    'chapter9a': ('vegetable',    'Vegetable Curries'),
    'chapter9b': ('vegetable',    'Vegetable Curries'),
    'chapter10': ('contemporary', 'Contemporary Curries'),
    'chapter11': ('biryani',      'Biryani Curries'),
    'chapter12': ('cohort',       'Curry Cohorts (rice/bread/sides)'),
}

RECIPE_RE = re.compile(r'<h3\s+class="(h3a|h3b)"[^>]*>(.*?)</h3>(.*?)(?=<h3\s+class="(?:h3a|h3b)"|<h2|\Z)', re.DOTALL)
SUB_RE = re.compile(r'<h3\s+class="h3c"[^>]*>(.*?)</h3>', re.DOTALL)
REGION_RE = re.compile(r'<h3\s+class="h3d"[^>]*>(.*?)</h3>', re.DOTALL)
SERVES_RE = re.compile(r'<span class="RY">\s*(?:SERVES|MAKES|YIELD[S]?)\s+([^<]+)</span>', re.I)
ITEM_RE = re.compile(r'<p\s+class="(item|itemb)"[^>]*>(.*?)</p>', re.DOTALL)
ANCHOR_IN_H3 = re.compile(r'<a\s+id="(rec\w+)"')
HREF_RE = re.compile(r'<a\s+href="([^"]+)#(rec\w+)"', re.I)

def parse_makes(text):
    text = text.strip().lower()
    text = re.sub(r'^(?:about|approximately|a scant|scant|almost|nearly|a generous|generous|a heaping|heaping|just under|just over)\s+', '', text)
    text = re.sub(r'^a\s+(?=[\d¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚])', '', text)
    a, idx = parse_amount(text)
    rest = text[idx:].strip()
    unit_match = re.match(r'^(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pints?|quarts?|ounces?|pounds?)\b', rest)
    unit = unit_match.group(1) if unit_match else ''
    return a, unit

def preprocess_html(html_text):
    """Normalize h3d+h3e/h3f → h3a, and h3bno → h3b."""
    def promote(m):
        anchor_part = m.group(1) or ''
        style_text = m.group(2).strip()
        title = m.group(3).strip()
        return f'<h3 class="h3a">{anchor_part}{title}</h3>\n<h3 class="h3d">{style_text}</h3>'
    html_text = re.sub(
        r'<h3 class="h3d">((?:<a[^>]+/?>)*)([^<]*)</h3>\s*<h3 class="h3[ef]">([^<]+)</h3>',
        promote, html_text
    )
    html_text = html_text.replace('<h3 class="h3bno">', '<h3 class="h3b">')
    return html_text

def parse_all_recipes():
    recipes = []
    for path in sorted(glob.glob(f'{XHTML}/chapter*.html')):
        base = os.path.basename(path).replace('.html','')
        if base not in CHAPTER_CATEGORIES: continue
        cat, cat_label = CHAPTER_CATEGORIES[base]
        with open(path) as f:
            content = preprocess_html(f.read())
        for m in RECIPE_RE.finditer(content):
            heading_html = m.group(2)
            body = m.group(3)
            title = clean_text(heading_html)
            anchor_m = ANCHOR_IN_H3.search(heading_html)
            rec_id = anchor_m.group(1) if anchor_m else None
            sub = SUB_RE.search(body)
            region = REGION_RE.search(body)
            full_title = title
            if sub: full_title += ' ' + clean_text(sub.group(1))
            region_text = clean_text(region.group(1)) if region else None
            serves_amount = serves_unit = serves_keyword = None
            sm = SERVES_RE.search(body)
            if sm:
                kw_match = re.search(r'(SERVES|MAKES|YIELD[S]?)', sm.group(0), re.I)
                serves_keyword = kw_match.group(1).upper() if kw_match else 'SERVES'
                a, u = parse_makes(sm.group(1))
                serves_amount = a
                serves_unit = u
            items = ITEM_RE.findall(body)
            ingredients_raw = []
            for _, raw_item in items:
                line = clean_text(raw_item)
                if not line: continue
                ref_ids = []
                for href_m in HREF_RE.finditer(raw_item):
                    anchor_text = re.search(r'<span class="link">([^<]+)</span>', raw_item)
                    if anchor_text and anchor_text.group(1).lower() == 'recipe':
                        ref_ids.append(href_m.group(2))
                ingredients_raw.append({'line': line, 'ref_ids': ref_ids, 'raw_html': raw_item})
            recipes.append({
                'title': full_title,
                'category': cat,
                'category_label': cat_label,
                'chapter_file': base,
                'rec_id': rec_id,
                'region': region_text,
                'serves_keyword': serves_keyword,
                'serves_amount': serves_amount,
                'serves_unit': serves_unit,
                'ingredients_raw': ingredients_raw,
            })
    return recipes

def build_subrecipe_index(recipes):
    referenced = set()
    for r in recipes:
        for ing in r['ingredients_raw']:
            for rid in ing['ref_ids']:
                referenced.add(rid)
    by_rec_id = {r['rec_id']: r for r in recipes if r['rec_id']}
    for r in recipes:
        r['is_subrecipe'] = (r['rec_id'] in referenced) if r['rec_id'] else False
    sub_titles = {r['title'].lower(): r for r in recipes if r['is_subrecipe']}
    return by_rec_id, sub_titles, referenced

def resolve_ingredients(recipes, by_rec_id, sub_titles):
    subrecipe_title_lookup = set(sub_titles.keys())
    NON_INGREDIENT_PATTERNS = (
        'skewers', 'toothpick', 'bamboo skewers', 'metal skewers',
        'butcher twine', 'parchment paper', 'aluminum foil',
        'cheesecloth', 'banana leaves for wrapping',
    )
    for r in recipes:
        resolved = []
        for ing in r['ingredients_raw']:
            line = ing['line']
            ref_ids = ing['ref_ids']
            line_lower = line.lower()
            if any(p in line_lower for p in NON_INGREDIENT_PATTERNS):
                continue
            amount, unit, name_core = extract_ingredient_name(line)
            if ref_ids and ref_ids[0] in by_rec_id:
                sub = by_rec_id[ref_ids[0]]
                canon = sub['title'].lower()
                is_subref = True
                via_rec_id = ref_ids[0]
            else:
                canon = canonicalize(name_core, subrecipe_title_lookup)
                if canon is None:
                    continue
                is_subref = canon in subrecipe_title_lookup
                via_rec_id = sub_titles[canon]['rec_id'] if is_subref else None
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
    """Parse + populate. Pass an open multi-book DB connection."""
    from cookbook_common import populate_book
    print('[660] Parsing recipes…')
    recipes = parse_all_recipes()
    print(f'[660]   raw recipes (h3a + h3b): {len(recipes)}')
    print('[660] Building sub-recipe index…')
    by_rec_id, sub_titles, referenced = build_subrecipe_index(recipes)
    n_sub = sum(1 for r in recipes if r['is_subrecipe'])
    print(f'[660]   sub-recipes identified: {n_sub}')
    print('[660] Resolving ingredients…')
    resolve_ingredients(recipes, by_rec_id, sub_titles)
    print('[660] Expanding sub-recipes…')
    expand_subrecipes(recipes, by_rec_id, sub_titles)
    n_exp = sum(len(r.get('expanded_ingredients',[])) for r in recipes)
    print(f'[660]   expanded ingredient rows: {n_exp}')
    print('[660] Writing to DB…')
    populate_book(con, BOOK_META, recipes)
    print(f'[660] Done: {len(recipes)} recipes inserted.')

if __name__ == '__main__':
    from cookbook_common import init_db, finalize_counts, DB_PATH
    con = init_db(DB_PATH)
    main(con)
    finalize_counts(con)
    print(f'DB: {DB_PATH}')
