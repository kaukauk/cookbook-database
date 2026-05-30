#!/usr/bin/env python3
"""Driver: drop-and-rebuild the multi-book SQLite DB, importing every book."""
import importlib, sys
from cookbook_common import init_db, finalize_counts, DB_PATH

BOOKS = [
    ('660_curries_build', 'main'),  # function `main(con)` in module
    ('dishoom_build',     'main'),
]

def main():
    con = init_db(DB_PATH)
    for mod_name, fn_name in BOOKS:
        mod = importlib.import_module(mod_name)
        getattr(mod, fn_name)(con)
    print('\nFinalizing aggregate counts…')
    finalize_counts(con)
    cur = con.cursor()
    cur.execute('SELECT slug, title, (SELECT COUNT(*) FROM recipe WHERE book_id=book.id) FROM book')
    print('\nBook summary:')
    for slug, title, n in cur.fetchall():
        print(f'  {slug}: {title}  →  {n} recipes')
    cur.execute('SELECT COUNT(*) FROM recipe'); n_r = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM ingredient'); n_i = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM recipe_ingredient'); n_ri = cur.fetchone()[0]
    print(f'\nTotal recipes: {n_r}')
    print(f'Distinct canonical ingredients: {n_i}')
    print(f'Recipe-ingredient rows: {n_ri}')
    print('\nTop 25 ingredients (by recipe_count_expanded):')
    cur.execute('''SELECT canonical, recipe_count_direct, recipe_count_expanded, book_count
                   FROM ingredient WHERE is_pantry_staple=0 AND is_subrecipe=0
                   ORDER BY recipe_count_expanded DESC LIMIT 25''')
    for c, d, e, b in cur.fetchall():
        print(f'  {c:35s}  direct={d:4d}  expanded={e:4d}  books={b}')
    print(f'\nDB: {DB_PATH}')

if __name__ == '__main__':
    sys.exit(main())
