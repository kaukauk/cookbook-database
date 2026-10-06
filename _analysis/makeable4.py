import sqlite3
con=sqlite3.connect("cookbook.db"); c=con.cursor()

# ingredients NOT owned at all (specialty / never bought), per jar system + user statements
SPECIALTY = {
 # exotic spices / souring agents not in the 63-jar system
 'teflam seeds','pathar ke phool or black stone flower','paan ki jad or betal flower root',
 'charoli seeds','kudampuli','gongura','holy basil','kaffir lime leaves','lemongrass',
 'anise seeds','caraway seeds','chinese five-spice powder','citric acid','dried rose petals',
 'gulkand','mamra','pav bhaji masala','chana masala',
 # grains/flours not in system
 'millet flour','pearl barley','oats','cornmeal','couscous','matzo meal','spaghetti',
 'whole-wheat ribbons','white falooda noodles','chickpea-flour noodles',
 # legumes not in system (marked x / not held)
 'horse gram','moth beans','flat beans','green chickpeas','black chickpeas',
 'yellow peas, whole','mixed sprouted grains','partially sprouted beans and/or peas',
 # bottled / liquids not held
 'rose water','screw pine',
 # alcohol & bar items
 'absinthe','aperol','gin','rum','vodka','whisky','tequila','champagne','prosecco',
 'ancho reyes liqueur','ceylon arrack','kamm & sons','mozart dry chocolate spirit',
 'punch à la ford','bitters','medium-dry cider','simple syrup','soda water','agave syrup',
 # prepared / western / commercial
 'bhel mix','bombay mix','sev','papdi','scant tbsp hp sauce','tin heinz baked beans',
 'worcestershire sauce','tabasco sauce','mayonnaise',
 'dried or fresh cheese-filled tortellini','fresh or dried fettuccini-type egg noodles',
 'puff pastry','packet frozen spring roll wrappers','bag frozen patra rounds',
 'bag frozen surti undhiyu mix','round poori shells','meringue nests',
 'ready-made sponge or madeira cake','processed cheese slices','cream cheese','cheddar',
 'bread buns','parathas','cocoa powder',
 'dark chocolate','condensed milk','evaporated milk','vanilla','coffee','tea',
 'gooseberry jam','apple juice, from concentrate','lychee juice','bloody mary mix',
 'chai syrup','rose syrup','dried cranberries','sunflower seeds',
 # meats not bought
 'bacon','veal','turkey','duck','cornish game hen','pork sausage','chicken livers',
}
# user explicitly does NOT have these
MISSING = {'walnuts','dates','apricots','wheat berries','sabudana'}
# stored in the room, not the kitchen
ROOM = {'chickpea flour','rice flour','whole-wheat flour','urad dal, whole',
        'masoor dal, split','masoor, whole','black-eyed peas','mung beans, whole'}

rows=c.execute("select canonical,is_subrecipe,subrecipe_recipe_id from ingredient").fetchall()
SUB={r[0]:r[2] for r in rows if r[1]==1 and r[2]}
direct={}
for rid,canon in c.execute("select recipe_id,canonical from recipe_ingredient where source='direct'"):
    direct.setdefault(rid,set()).add(canon)

def makeable(rid,unavail,seen=None,memo=None):
    memo=memo if memo is not None else {}
    if rid in memo: return memo[rid]
    seen = seen or set()
    if rid in seen: return True
    memo[rid]=True
    for canon in direct.get(rid,()):
        if canon in SUB:
            if not makeable(SUB[canon],unavail,seen|{rid},memo):
                memo[rid]=False; return False
        elif canon in unavail:
            memo[rid]=False; return False
    return memo[rid]

recs=c.execute("select id,title,category_label from recipe where book_id=1 and is_subrecipe=0").fetchall()
for label,unavail in [("A: kitchen + room (full system)",SPECIALTY|MISSING),
                      ("B: kitchen jars only",SPECIALTY|MISSING|ROOM)]:
    memo={}
    ok=[r for r in recs if makeable(r[0],unavail,None,memo)]
    print(f"{label}: {len(ok)} / {len(recs)}  ({100*len(ok)/len(recs):.1f}%)")
    from collections import Counter
    cnt=Counter(r[2] for r in ok); tot=Counter(r[2] for r in recs)
    for k in sorted(tot): print(f"   {k:<40} {cnt[k]:>3}/{tot[k]}")
    globals()['set_'+label[0]]=set(r[0] for r in ok)

lost=set_A-set_B
print("\nrecipes lost by keeping those 8 items in the room:",len(lost))
from collections import Counter
blame=Counter()
for rid in lost:
    for canon in direct.get(rid,()):
        if canon in ROOM: blame[canon]+=1
for k,v in blame.most_common(): print(f"   {k:<24} {v}")


from collections import Counter
print("\n=== top blockers, kitchen-only ===")
memo={}; un=SPECIALTY|MISSING|ROOM
blocked=[r for r in recs if not makeable(r[0],un,None,memo)]
b=Counter()
def why(rid,seen=None):
    seen=seen or set()
    if rid in seen: return
    for canon in direct.get(rid,()):
        if canon in SUB: why(SUB[canon],seen|{rid})
        elif canon in un: b[canon]+=1
for r in blocked: why(r[0])
for k,v in b.most_common(12): print(f"   {k:<24} {v}")
print("\n=== cost of the 8 room items, kitchen-only ===")
b2=Counter()
memoA={}; unA=SPECIALTY|MISSING
lost=[r for r in recs if makeable(r[0],unA,None,memoA) and not makeable(r[0],un,None,memo)]
for r in lost:
    un2=ROOM
    def why2(rid,seen=None):
        seen=seen or set()
        if rid in seen: return
        for canon in direct.get(rid,()):
            if canon in SUB: why2(SUB[canon],seen|{rid})
            elif canon in un2: b2[canon]+=1
    why2(r[0])
for k,v in b2.most_common(): print(f"   {k:<24} {v}")
