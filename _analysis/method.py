#!/usr/bin/env python3
"""Print a recipe's ingredients + method text, by recipe id or title substring.

    ./method.py 344
    ./method.py "Tamilian Okra"

Methods are not in cookbook.db; they are pulled out of the epub in source-books/.
"""
import sqlite3, sys, re, html, zipfile, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB   = os.path.join(ROOT, "cookbook.db")
EPUB = {1: os.path.join(ROOT, "source-books", "660_Curries.epub"),
        2: os.path.join(ROOT, "source-books", "Dishoom.epub")}

def find(arg):
    con = sqlite3.connect(DB)
    if arg.isdigit():
        row = con.execute("select id,book_id,title,chapter_file,yield_amount,yield_unit,yield_keyword"
                          " from recipe where id=?", (int(arg),)).fetchone()
        if not row: sys.exit(f"no recipe with id {arg}")
        return con, row
    rows = con.execute("select id,book_id,title,chapter_file,yield_amount,yield_unit,yield_keyword"
                       " from recipe where title like ? order by id", (f"%{arg}%",)).fetchall()
    if not rows: sys.exit(f"no recipe matching {arg!r}")
    if len(rows) > 1:
        print("several matches:", file=sys.stderr)
        for r in rows: print(f"  {r[0]}  {r[2]}", file=sys.stderr)
        sys.exit(1)
    return con, rows[0]

def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    con, (rid, book, title, chap, ya, yu, yk) = find(sys.argv[1])
    print(f"#{rid}  {title}   [{yk or ''} {ya or '?'} {yu or ''}]".rstrip())
    print()
    for (line,) in con.execute("select raw_line from recipe_ingredient"
                               " where recipe_id=? and source='direct'", (rid,)):
        print("  -", line)
    print()
    subs = con.execute("select i.canonical, i.subrecipe_recipe_id, r.title"
                       " from recipe_ingredient ri join ingredient i on i.canonical=ri.canonical"
                       " left join recipe r on r.id=i.subrecipe_recipe_id"
                       " where ri.recipe_id=? and ri.source='direct' and i.is_subrecipe=1", (rid,)).fetchall()
    if subs:
        print("sub-recipes:")
        for canon, sid, stitle in subs:
            print(f"  {canon} -> #{sid} {stitle}")
        print()

    path = EPUB.get(book)
    if not path or not os.path.exists(path):
        sys.exit(f"(method text needs {path})")
    want = re.sub(r'\s+', ' ', re.sub(r'\s+(WITH|IN|AND|OVER|TOPPED|LAYERED|STUFFED|SIMMERED|POACHED|BATHED|FLAVORED|PICKLED|WRAPPED)\b.*', '', title)).strip()
    tail = title[len(want):].strip()
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if chap in n and n.endswith(('.html', '.xhtml'))] \
                or [n for n in z.namelist() if n.endswith(('.html', '.xhtml'))]
        for n in names:
            s = z.read(n).decode('utf-8', 'replace')
            for m in re.finditer(re.escape(tail or want), s):
                seg = re.sub(r'<[^>]+>', '\n', s[max(0, m.start() - 400):m.start() + 4000])
                seg = re.sub(r'\n\s*\n+', '\n', html.unescape(seg))
                if re.search(r'\n1\.\n', seg) and re.search(r'SERVES|MAKES', seg):
                    print(seg.strip())
                    return
    print("(could not locate the method text; grep the epub by hand)")

main()
