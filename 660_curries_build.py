#!/usr/bin/env python3
"""660 Curries v2: SQLite-backed ingredient analytics with sub-recipe expansion.

What's new vs v1:
- All h3a and h3b recipes captured (~666 total, not 588).
- Each recipe's <a id="rec*"> anchor is preserved as external_id.
- Sub-recipes detected by scanning cross-references in ingredient lines.
- Sub-recipes are dual-indexed: as a row in `recipe` AND as a row in `ingredient`
  (so "how many recipes use Ginger Paste?" works as a normal ingredient query).
- Sub-recipe ingredient lists are expanded inline, scaled by amount/yield,
  with depth-first recursion and cycle detection (max depth 5).
- Ingredient quantities are converted to grams via a curated density table
  (~140 entries) instead of treating 1 cup as 240 g for everything.
- Per-piece weights for count units (1 garlic clove = 5g, 1 bay leaf = 0.1g, etc.).
- Semicolons and "or"-alternatives are stripped from ingredient names
  (fixes the 3 noisy entries from v1).
- Output: SQLite database (.db), JSON mirror, methodology + per-ingredient .md.
"""
import re, json, os, glob, html, statistics, math, sqlite3
from collections import Counter, defaultdict

XHTML = '/tmp/epub_extract/ops/xhtml'
OUT_DIR = '/home/kaustubh/Documents/GitHub/cookbook-database'
DB_PATH = f'{OUT_DIR}/660_curries.db'

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

# =================================================================
# Amount parsing
# =================================================================
UNICODE_FRACTIONS = {
    '¼':0.25,'½':0.5,'¾':0.75,'⅓':1/3,'⅔':2/3,
    '⅛':0.125,'⅜':0.375,'⅝':0.625,'⅞':0.875,
    '⅕':0.2,'⅖':0.4,'⅗':0.6,'⅘':0.8,
    '⅙':1/6,'⅚':5/6,
}
FRAC = '[¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚]'

def parse_amount(text):
    text = text.strip()
    m = re.match(rf'^\s*(\d+)?\s*({FRAC})', text)
    if m:
        total = float(m.group(1)) if m.group(1) else 0.0
        total += UNICODE_FRACTIONS[m.group(2)]
        return total, m.end()
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)', text)
    if m:
        return (float(m.group(1))+float(m.group(2)))/2, m.end()
    m = re.match(r'^\s*(\d+)\s*/\s*(\d+)', text)
    if m:
        return float(m.group(1))/float(m.group(2)), m.end()
    m = re.match(r'^\s*(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1)), m.end()
    return None, 0

# =================================================================
# Units
# =================================================================
ML_OF = {'teaspoon':5,'teaspoons':5,'tsp':5,'tsps':5,
         'tablespoon':15,'tablespoons':15,'tbsp':15,'tbsps':15,'tbs':15,
         'cup':240,'cups':240,
         'pint':473,'pints':473,'quart':946,'quarts':946,
         'fluid':30,  # "fluid ounce(s)"
         'fl':30}
G_OF = {'pound':454,'pounds':454,'lb':454,'lbs':454,
        'ounce':28,'ounces':28,'oz':28,
        'gram':1,'grams':1,'g':1,
        'kilogram':1000,'kilograms':1000,'kg':1000}
COUNT_UNITS = {'piece','pieces','clove','cloves','sprig','sprigs','leaf','leaves',
               'stalk','stalks','head','heads','bunch','bunches','can','cans',
               'package','packages','sheet','sheets','pinch','pinches','dash','dashes',
               'pod','pods','stick','sticks','strand','strands','small','medium','large',
               'whole'}

# Adjectives that precede a count unit ("4 medium-size cloves garlic" — skip
# "medium-size" so we see "cloves" as the unit).
SIZE_DESCRIPTORS = {'small','medium','large','tiny','huge','jumbo','baby',
                    'small-size','medium-size','large-size','medium-sized','small-sized','large-sized',
                    'extra-large','extra-small','golf-ball-sized'}

# =================================================================
# Density table — grams per cup (240 ml). Carefully curated for top
# ingredients; fall back to category default otherwise.
# Sources: USDA FoodData Central, King Arthur ingredient weight chart,
# standard culinary tables.
# =================================================================
DENSITY_G_PER_CUP = {
    # --- liquids (≈ water) ---
    'water':240,'milk':245,'buttermilk':240,'yogurt':245,'cream':238,
    'half-and-half':242,'coconut milk':226,'vegetable oil':218,
    'mustard oil':215,'coconut oil':218,'sesame oil':218,
    'vinegar':240,'cider vinegar':240,'malt vinegar':240,'rice vinegar':240,'feni':240,
    'soy sauce':255,'honey':340,'tamarind':260,'lime':244,'lemon':244,
    'rose water':240,'screw pine':240,'tea':240,
    'ghee':210,'butter':225,
    # --- whole spices (seeds, pods, sticks) ---
    'cumin seeds':95,'black cumin':100,'coriander seeds':90,'fennel seeds':95,
    'mustard seeds':140,'fenugreek seeds':150,'nigella seeds':115,
    "bishop's weed":95,'poppy seeds':145,'sesame seeds':144,
    'cloves':100,'cardamom, green':95,'cardamom, black':95,
    'cinnamon':100,'bay leaf':18,'star anise':80,
    # --- ground spices ---
    'turmeric':130,'ground cumin':100,'ground coriander':85,'cayenne':105,
    'red chile powder':115,'paprika':108,'black pepper':135,'ground black pepper':108,
    'nutmeg':110,'mace':70,'ground mace':70,'ground cinnamon':125,'ground cloves':107,
    'ground cardamom':100,'ground mustard':85,'ground fennel':95,'ground fenugreek':110,
    'ground ginger':95,
    'asafetida':150,'mango powder':115,'dried pomegranate seeds':110,
    'garam masala':95,'sambhar masala':95,'kokum':80,
    # --- salt / sugar / leavening ---
    'salt':292,'black salt':300,'sugar':200,'jaggery':210,'palm sugar':210,
    'baking powder':230,
    # --- flours / starches ---
    'all-purpose flour':125,'whole-wheat flour':120,'rice flour':125,
    'chickpea flour':92,'cornstarch':128,'cornmeal':156,'millet flour':110,
    'sorghum flour':130,'semolina':165,
    # --- rices & grains (dry) ---
    'basmati rice':190,'rice':195,'brown rice':190,'red rice':190,'cracked wheat':150,
    # --- legumes (dry) ---
    'chickpeas':200,'black chickpeas':205,'green chickpeas':165,
    'red kidney beans':190,'black-eyed peas':170,
    'mung beans, whole':205,'split mung beans, skinned':210,
    'urad dal, skinned split':208,'urad dal, whole':205,'chana dal':208,
    'masoor dal, split':195,'masoor, whole':195,
    'toovar dal':200,'toovar, whole':200,'moth beans':200,'horse gram':205,
    'yellow peas, whole':190,
    # --- nuts (whole, raw) ---
    'cashews':130,'almonds':143,'pistachios':125,'peanuts':145,
    'walnuts':100,'pine nuts':135,
    # --- coconut ---
    'coconut, fresh':80,'coconut, dried':93,'coconut, whole':80,
    # --- fresh herbs (chopped) ---
    'cilantro':16,'mint':10,'dill':9,'basil':24,'holy basil':22,
    'gongura':22,'curry leaves':14,'fenugreek leaves':28,'mustard greens':25,
    # --- aromatics (chopped) ---
    'onion':160,'shallot':160,'garlic':136,'ginger':96,
    'green chile':100,'dried red chile':35,'scallions':100,'lemongrass':70,
    # --- vegetables (chopped / general) ---
    'tomato':180,'potato':150,'sweet potato':133,'cauliflower':100,
    'cabbage':89,'spinach':30,'eggplant':82,'okra':100,'green peas':145,
    'green beans':110,'carrot':128,'bell pepper':149,'cucumber':119,
    'mushroom':70,'bitter melon':93,'bottle gourd':116,'ridge gourd':93,
    'ivy gourd':100,'taro root':132,'taro leaves':38,
    'pumpkin':116,'white pumpkin':100,'lotus root':95,'yams':136,
    'plantain':150,'radish':116,'turnip':130,'kohlrabi':135,'beets':136,
    'broccoli':91,'amaranth leaves':28,'drumstick':60,'corn':145,
    # --- fruits ---
    'apples':125,'banana':150,'cherries':155,'raisins':145,'dates':147,
    'apricots':155,'guava':165,'watermelon':152,'mango':165,
    'mango, unripe':165,'mango, ripe':165,'pineapple':165,'pomegranate seeds':174,
    # --- dairy products that aren't liquids ---
    'paneer':240,'whole-milk cheese':113,'khoya':260,
    # --- meats / seafood (raw, diced) ---
    'chicken':140,'lamb':140,'beef':150,'pork':150,'pork sausage':150,
    'veal':140,'turkey':140,'cornish game hen':140,'duck':150,
    'shrimp':145,'lobster':140,'crab':140,'scallops':140,'mussels':140,
    'salmon':140,'tuna':140,'tilapia':140,'catfish':140,'cod':140,
    'halibut':140,'mackerel':140,'red snapper':140,'carp':140,'sole':140,
    'fish':140,'eggs':243,'saffron':530,
}

# Per-piece weight for count units (grams)
PIECE_WEIGHT = {
    'garlic':5,                  # 1 clove
    'green chile':5,             # small chile
    'dried red chile':1,
    'cloves':0.07,
    'cardamom, green':0.3,
    'cardamom, black':0.7,
    'bay leaf':0.1,
    'curry leaves':0.05,
    'star anise':2.0,
    'cinnamon':2.5,              # 1 stick (~3 inch)
    'lime':50,
    'lemon':60,
    'eggs':50,                   # 1 large egg
    'onion':110,                 # 1 medium
    'shallot':30,                # 1 small pearl
    'tomato':123,                # 1 medium
    'potato':150,
    'paneer':240,                # ~1 package
    'banana':118,
    'plantain':180,
    'mango':200,'mango, unripe':200,'mango, ripe':200,
    'cucumber':300,
    'eggplant':82,
    'bell pepper':119,
    'cauliflower':600,
    'carrot':61,
    'chicken':1400,              # whole chicken
    'fish':500,                  # whole fish, small
    'papads':5,
    'lentil wafers':5,
    'lemongrass':17,             # 1 stalk
    'screw pine':5,              # 1 leaf
}

# Default fallback for an unknown ingredient × cup
DEFAULT_DENSITY_LIQUID = 240
DEFAULT_DENSITY_SOLID = 150

def grams_for(canonical, amount, unit_phrase, line_text):
    """Convert (amount, unit) → grams. Returns (grams, used_unit, normalized_bool, source)."""
    if amount is None:
        return None, unit_phrase, False, 'no_amount'
    u = (unit_phrase or '').lower().strip()
    u = re.sub(r'^of\s+', '', u)
    # mass units convert exactly
    for k, factor in sorted(G_OF.items(), key=lambda x:-len(x[0])):
        if u.startswith(k):
            return amount * factor, k, True, 'mass'
    # volume units use ingredient-specific density
    for k, ml_per in sorted(ML_OF.items(), key=lambda x:-len(x[0])):
        if u.startswith(k):
            density = DENSITY_G_PER_CUP.get(canonical)
            if density is None:
                # heuristic: anything ending in 'oil' or 'milk' or 'water' or 'juice' is liquid-ish
                liquidish = any(w in canonical for w in ('oil','milk','water','juice','vinegar','sauce','paste','cream','yogurt','syrup','stock','broth'))
                density = DEFAULT_DENSITY_LIQUID if liquidish else DEFAULT_DENSITY_SOLID
                src = 'volume_default'
            else:
                src = 'volume_known'
            # convert ml→g via density (which is g per 240ml cup)
            ml = amount * ml_per
            return ml * density / 240.0, k, True, src
    # count units
    if u in COUNT_UNITS or u == '':
        per = PIECE_WEIGHT.get(canonical)
        if per is not None:
            return amount * per, u or 'piece', True, 'piece_known'
        return None, u, False, 'count_unknown'
    return None, unit_phrase, False, 'unrecognized_unit'

# =================================================================
# Ingredient name cleanup + synonyms (carried over, lightly expanded)
# =================================================================
STOPWORDS = set('''a an the of and or to with for in on at by from as into
freshly finely thinly coarsely roughly lightly
chopped sliced diced minced grated crushed cracked halved quartered
peeled cored seeded stemmed trimmed pitted shredded julienned cubed
extra big tiny mini half halves quarters
hot warm cold room temperature
raw cooked toasted roasted boiled steamed fried
plus more about approximately roughly
preferably optional optionally divided
length-wise lengthwise crosswise crisscross
into pieces strips slices rounds wedges chunks
inch inches long thin thick wide cm centimeter centimeters
softened melted soft firm hard
free-range organic natural ripe unripe young old mature
your favorite store-bought home-made homemade
'''.split())
# NOTE: words intentionally NOT in STOPWORDS — they're descriptors that
# canonicalize handles via its leading-strip regex, AND removing them here
# preserves alias matches like "red lentils" → masoor dal:
#   - colors: red, green, yellow, black, white, brown, orange, purple, pink
#   - freshness: fresh, dry, dried, whole
#   - sizes: small, medium, large (these are also count units)
#   - preps: split (it's part of "split mung beans" etc.)

SYNONYMS = {
    'asafetida': ['hing','asafoetida'],
    'cumin seeds': ['cumin seed','cumin','jeera','zeera','safed zeera','whole cumin'],
    'ground cumin': ['cumin powder','powdered cumin','ground roasted cumin'],
    'black cumin': ['shahi zeera','shahi jeera','royal cumin','black cumin seeds'],
    'coriander seeds':['coriander seed','sabud dhania','whole coriander'],
    'ground coriander':['coriander powder','coriander, ground'],
    'cilantro':['fresh coriander','coriander leaves','taaza dhania','dhania','cilantro leaves','coriander leaf'],
    'turmeric':['ground turmeric','turmeric powder','haldi','manjal','ground tumeric','tumeric'],
    'cardamom, green':['green cardamom','cardamom pods','green cardamom pods','elaichi','cardamom seeds','cardamom seed','whole green cardamom','whole cardamom pods','cardamom','cardamom seeds from green or white pods','cardamom seeds from green pods'],
    'ground cardamom':['cardamom powder','ground green cardamom','ground cardamom seeds','powdered cardamom','cardamom seeds from green or white pods, ground','cardamom seeds, ground','cardamom seeds ground'],
    'cardamom, black':['black cardamom','black cardamom pods','badi elaichi','whole black cardamom','cardamom seeds from black pods','cardamom seeds from black pods, ground','cardamom from black pods'],
    'cinnamon':['cinnamon stick','cinnamon sticks','dalchini','cassia','whole cinnamon'],
    'ground cinnamon':['cinnamon powder','cinnamon, ground','powdered cinnamon','ground cassia'],
    'cloves':['clove','lavang','whole cloves'],
    'ground cloves':['cloves, ground','clove powder','ground clove','powdered cloves'],
    'bay leaf':['bay leaves','tez patta','indian bay leaf'],
    'mustard seeds':['mustard seed','black mustard seeds','brown mustard seeds','rai','mustard seeds, black','whole mustard seeds','whole mustard'],
    'ground mustard':['mustard powder','dry mustard','ground mustard seeds','dried mustard'],
    'fenugreek seeds':['fenugreek seed','methi seeds','methi','whole fenugreek','whole fenugreek seeds'],
    'ground fenugreek':['fenugreek powder','ground fenugreek seeds','ground methi','methi powder'],
    'fenugreek leaves':['fresh fenugreek','dried fenugreek','kasuri methi','dried fenugreek leaves','methi leaves','fenugreek'],
    'fennel seeds':['fennel seed','saunf','whole fennel seeds','whole fennel'],
    'ground fennel':['fennel powder','ground fennel seeds','powdered fennel'],
    'nigella seeds':['nigella','kalonji','nigella seed','onion seeds'],
    "bishop's weed":['ajwain','ajowan','carom seeds','ajwan','carom','bishop’s weed'],
    'black pepper':['black peppercorns','peppercorns','kali mirchi','whole black peppercorns','whole peppercorns','pepper'],
    'ground black pepper':['black pepper, ground','freshly ground black pepper','freshly ground pepper','pepper, ground','ground pepper','ground peppercorns'],
    'cayenne':['cayenne pepper','ground cayenne','cayenne (ground red pepper)'],
    'red chile powder':['ground red chile','red chili powder','kashmiri chile powder','ground deggi chiles','deggi mirch','deggi chile powder','ground kashmiri chiles'],
    'paprika':['sweet paprika','hungarian paprika'],
    'nutmeg':['ground nutmeg','grated nutmeg','jaiphal'],
    'mace':['jaipatri','blade mace','mace blades','blades of mace','whole mace'],
    'ground mace':['mace, ground','mace powder','powdered mace'],
    'saffron':['saffron threads','zaffran','kesar','zarda'],
    'poppy seeds':['poppy seed','khus-khus','khus khus','white poppy seeds'],
    'sesame seeds':['sesame seed','til','white sesame seeds'],
    'star anise':['star anise pods','badiyan'],
    'mango powder':['amchur','amchoor','dried mango powder'],
    'dried pomegranate seeds':['anardana','pomegranate seeds, dried'],
    'tamarind':['tamarind paste','tamarind pulp','tamarind concentrate','imli','tamarind extract'],
    'kokum':['kokum petals','dried kokum'],
    'kudampuli':['goraka','fish tamarind'],
    'curry leaves':['curry leaf','kadipatta','kari patta','fresh curry leaves'],
    'kaffir lime leaves':['kaffir lime leaf','makrut lime leaves'],
    'rose water':['rosewater','rose essence','gulab jal'],
    'screw pine':['kewra water','kewra','pandan'],
    'black salt':['kala namak'],
    'salt':['table salt','kosher salt','sea salt','iodized salt','coarse salt','coarse kosher or sea salt','coarse kosher salt','coarse sea salt'],
    'sugar':['granulated sugar','white sugar','chini'],
    'jaggery':['gur','palm jaggery'],
    'garlic':['garlic clove','garlic cloves','minced garlic','grated garlic','lasoon','lasson','crushed garlic'],
    'ginger':['fresh ginger','ginger root','ginger, fresh','adrak','grated ginger','minced ginger','gingerroot','fresh ginger root'],
    'ground ginger':['dried ginger','dry ginger','ginger powder','sonth','sunthi','dried ground ginger','powdered ginger'],
    'onion':['onions','red onion','yellow onion','sliced onion','chopped onion','pyaaz','kaanda','vengayam'],
    'shallot':['shallots','pearl onions','chinnay vengayam'],
    'scallions':['scallion','green onions','spring onion','spring onions'],
    'green chile':['green chiles','fresh green chile','green chilies','hara mirch','serrano chile','serrano','jalapeno','jalapeño','thai chile','thai chiles','thai bird chile'],
    'dried red chile':['dried red chiles','dried red chili','dried red chillies','red chile','red chiles','dried chiles','dried chile','lal mirch','byadagi','kashmiri chile','kashmiri chiles','dried red thai or cayenne chile','dried red thai or cayenne chiles','dried red thai chile','dried red thai chiles'],
    'mint':['fresh mint','mint leaves','pudhina','pudina','mint, fresh'],
    'dill':['fresh dill','dill leaves','suva','dill weed'],
    'basil':['basil leaves','fresh basil'],
    'holy basil':['tulsi'],
    'gongura':['gongura leaves','sorrel leaves'],
    'tomato':['tomatoes','plum tomato','plum tomatoes','roma tomato','roma tomatoes','tamatar','thakkali','crushed tomato','canned tomato','canned tomatoes','tomato puree'],
    'potato':['potatoes','aloo','batata','urulikazhangu','red potato','red potatoes','yukon gold','new potatoes','baby potatoes'],
    'sweet potato':['sweet potatoes','rataloo','yam'],
    'cauliflower':['cauliflower florets','phool gobhi','gobhi florets'],
    'cabbage':['green cabbage','shredded cabbage','bund gobhi','muttaikose'],
    'spinach':['fresh spinach','baby spinach','spinach leaves','palak','keerai'],
    'eggplant':['eggplants','baby eggplant','baingan','japanese eggplant','asian eggplant','aubergine'],
    'okra':['okra pods','bhindi','vendakkai',"lady's fingers"],
    'green peas':['frozen peas','fresh peas','mutter','matar','green peas, frozen','sweet peas','english peas','garden peas'],
    # NOTE: bare 'peas' is intentionally NOT an alias — it falsely matches
    # "pigeon peas", "yellow peas", "split peas" via tail matching.
    'green beans':['string beans','french beans','farasvi'],
    'carrot':['carrots','gajar'],
    'bell pepper':['bell peppers','red bell pepper','green bell pepper','yellow bell pepper','simla mirch','capsicum'],
    'cucumber':['cucumbers','kakadi'],
    'mushroom':['mushrooms','white mushrooms','button mushrooms','cremini','dhingri'],
    'bitter melon':['bitter gourd','karela'],
    'bottle gourd':['lauki','dudhi','opo squash','bottle gourd squash'],
    'ridge gourd':['luffa','toori','peerkangai','ridged luffa','luffa squash'],
    'ivy gourd':['tindora','tindori','kovakkai'],
    'taro root':['arbi','colocasia','taro'],
    'taro leaves':['patra','colocasia leaves','arbi leaves'],
    'pumpkin':['kaddu','red pumpkin'],
    'white pumpkin':['ash gourd','winter melon','wax gourd'],
    'lotus root':['kamal kakadi','nadru'],
    'yams':['suran','yam','jimikand'],
    'plantain':['raw plantain','green plantain','vazhaipazham'],
    'radish':['daikon','white radish','mooli','daikon radish'],
    'turnip':['turnips','shalgam'],
    'kohlrabi':['kohlrabi bulb'],
    'beets':['beet','beetroot','chukander'],
    'broccoli':['broccoli florets'],
    'amaranth leaves':['red amaranth','chinese spinach','red spinach','amaranth'],
    'drumstick':['drumsticks','moringa pods','sahjan'],
    'mustard greens':['sarson'],
    'corn':['fresh corn','corn kernels','makkai','sweet corn'],
    'lemongrass':['fresh lemongrass','lemongrass stalk'],
    'lime':['fresh lime','lime juice','limes','nimbu','key lime'],
    'lemon':['lemons','lemon juice','fresh lemon'],
    'mango, unripe':['unripe mango','green mango','raw mango','khatte aam','kacchi keri','mango (unripe)','green unripe papaya'],
    'mango, ripe':['ripe mango'],
    'mango':['mangoes'],
    'pineapple':['fresh pineapple','anaras','anasi'],
    'pomegranate seeds':['pomegranate arils','fresh pomegranate'],
    'apples':['apple','green apple'],
    'banana':['bananas','ripe banana'],
    'cherries':['fresh cherries','dried cherries'],
    'raisins':['golden raisins','kishmish','sultanas','raisin','dark raisins'],
    'dates':['date','medjool dates','pitted dates'],
    'apricots':['apricot','dried apricots','jardaloo'],
    'guava':['guavas'],
    'watermelon':['tarbooz'],
    'avocado':['hass avocado','hass avocados','avocados','firm hass avocado'],
    'arugula':['rocket'],
    'bamboo shoots':['bamboo shoot','canned bamboo shoots'],
    'bean sprouts':['mung bean sprouts','sprouted beans','store-bought bean sprouts'],
    'chives':['fresh chives'],
    'jackfruit':['raw jackfruit','canned raw jackfruit','green jackfruit','unripe jackfruit'],
    'flat beans':['flat green beans','italian flat beans'],
    'chickpeas':['garbanzo beans','kabuli chana','canned chickpeas','dried chickpeas','white chickpeas'],
    'black chickpeas':['kala chana','desi chana'],
    'green chickpeas':['hara chana'],
    'chickpea flour':['besan','gram flour','garbanzo flour'],
    'red kidney beans':['kidney beans','rajmah','rajma'],
    'black-eyed peas':['lobhia','black-eyed pea','chowli','cowpeas','red cowpeas','sabud chowli'],
    'mung beans, whole':['mung beans','whole mung','sabud moong','green gram','moong','whole green lentils','green lentils, whole'],
    'split mung beans, skinned':['moong dal','yellow split mung','skinned split mung','dhuli moong','skinned split green lentils','split green lentils','green lentils, split'],
    'urad dal, skinned split':['urad dal','split black gram','skinned split black lentils','dhuli urad','skinned split black lentils, picked over for stones','split black lentils'],
    'urad dal, whole':['whole urad','sabud urad','black gram, whole','whole black gram','whole black lentils'],
    'chana dal':['yellow split peas','split bengal gram','chana daal','split yellow peas','split yellow chickpeas','bengal gram, split','split bengal gram lentils'],
    'yellow peas, whole':['safed vatana','dried yellow peas','whole yellow peas'],
    'masoor dal, split':['red lentils','masoor dal','split red lentils','skinned masoor','skinned split brown lentils','split brown lentils','brown lentils, split','salmon-colored brown lentils'],
    'masoor, whole':['whole brown lentils','sabud masoor','brown lentils'],
    'toovar dal':['toor dal','arhar dal','pigeon peas, split','split pigeon peas','tuvar dal','yellow pigeon peas','split yellow pigeon peas','skinned split yellow pigeon peas','oily skinned split yellow pigeon peas','unoily skinned split yellow pigeon peas'],
    'toovar, whole':['whole pigeon peas','sabud toovar','sabud toor','whole yellow pigeon peas'],
    'moth beans':['matki','moth','dew gram'],
    'horse gram':['kulith','kollu'],
    'cashews':['cashew','cashew nuts','caju','raw cashews'],
    'almonds':['almond','blanched almonds','slivered almonds','almond, blanched'],
    'pistachios':['pistachio','shelled pistachios'],
    'peanuts':['peanut','sengdana','mungphalli','raw peanuts','roasted peanuts'],
    'walnuts':['walnut','walnut halves'],
    'pine nuts':['chilgozae','pinoli'],
    'coconut, fresh':['fresh coconut','grated coconut','grated fresh coconut','fresh grated coconut','shredded fresh coconut'],
    'coconut, dried':['dried coconut','dessicated coconut','desiccated coconut','copra','unsweetened shredded coconut','shredded coconut','shredded dried unsweetened coconut'],
    'coconut milk':['canned coconut milk','thick coconut milk','thin coconut milk','unsweetened coconut milk'],
    'coconut, whole':['coconut','nariyal','thenga'],
    'yogurt':['plain yogurt','greek yogurt','dahi','curd','whole-milk yogurt','natural yogurt'],
    'buttermilk':['cultured buttermilk','chaas','more'],
    'milk':['whole milk','full-fat milk','low-fat milk','2% milk'],
    'cream':['heavy cream','whipping cream','heavy whipping cream','double cream'],
    'half-and-half':['half and half'],
    'butter':['unsalted butter','salted butter','butter, unsalted'],
    'ghee':['clarified butter','ghee, melted'],
    'paneer':['indian cheese','fresh cheese','paneer cheese','homemade paneer'],
    'khoya':['mawa','milk solids'],
    'whole-milk cheese':['cheese'],
    'vegetable oil':['canola oil','sunflower oil','safflower oil','corn oil','neutral oil','oil','peanut oil','vegetable cooking oil','vegetable cooking spray','cooking spray'],
    'mustard oil':['kacchi ghani mustard oil'],
    'coconut oil':['virgin coconut oil'],
    'sesame oil':['gingelly oil','toasted sesame oil','til oil'],
    'basmati rice':['white basmati','aged basmati','basmati'],
    'rice':['long-grain rice','short-grain rice','white rice','plain rice'],
    'brown rice':['brown basmati'],
    'red rice':['rosematta rice','matta rice','kerala red rice'],
    'all-purpose flour':['plain flour','maida','flour','wheat flour'],
    'whole-wheat flour':['atta','chapati flour','whole-meal flour','wholemeal flour'],
    'rice flour':['ground rice'],
    'cornmeal':['polenta','makkai flour','corn flour'],
    'cornstarch':['cornflour','corn starch'],
    'millet flour':['bajra','bajra flour','pearl millet flour'],
    'sorghum flour':['jowar','jowar flour'],
    'semolina':['sooji','rava','farina','cream of wheat'],
    'papads':['papadum','papadams','papad','papadums','lentil wafers'],
    'chicken':['chicken thighs','chicken breast','chicken pieces','whole chicken','bone-in chicken','boneless chicken','skinless chicken','chicken, cut into','murghi'],
    'cornish game hen':['cornish hen','game hen','cornish hens'],
    'duck':['duck breast','duck legs'],
    'turkey':['ground turkey','turkey breast'],
    'lamb':['lamb shoulder','lamb leg','boneless lamb','bone-in lamb','lamb stew meat','ground lamb','lamb, cut into','gosht'],
    'beef':['beef chuck','ground beef','stew beef','beef stew meat','beef shoulder','beef sirloin','sirloin','flank steak','beef, cut into'],
    'pork':['pork shoulder','pork loin','pork tenderloin','pork butt','pork, cut into','pork stew meat'],
    'pork sausage':['italian sausage','sausage'],
    'eggs':['egg','hard-boiled eggs','large eggs','egg yolks','egg whites','egg yolk','egg white'],
    'shrimp':['prawns','shrimps','large shrimp','medium shrimp','peeled shrimp','jhinga','chingri'],
    'lobster':['lobster tail','lobster tails','lobster meat'],
    'crab':['crab meat','crab claws','kekada'],
    'scallops':['sea scallops','bay scallops'],
    'mussels':['fresh mussels','mussels in shell'],
    'salmon':['salmon fillet','salmon steaks'],
    'tuna':['tuna steak','fresh tuna'],
    'tilapia':['tilapia fillets'],
    'catfish':['catfish fillets'],
    'cod':['cod fillets'],
    'halibut':['halibut fillet','halibut steak'],
    'mackerel':['mackerel fillets','bangada'],
    'red snapper':['snapper','snapper fillets'],
    'carp':['carp steaks','rohu','ruhu'],
    'sole':['sole fillet','fillet of sole'],
    'fish':['fish fillets','firm white fish','any firm fish','meen','maach','mucchi','muchee'],
    'baking powder':['baking soda','sodium bicarbonate'],
    'water':['warm water','cold water','hot water','tap water','filtered water'],
    'vinegar':['white vinegar','distilled vinegar','sirka'],
    'cider vinegar':['apple cider vinegar'],
    'malt vinegar':['british malt vinegar'],
    'rice vinegar':['rice wine vinegar'],
    'feni':['feni vinegar','goan feni'],
    'soy sauce':['light soy sauce','dark soy sauce'],
    'honey':['raw honey','clover honey'],
    'tea':['black tea','tea leaves','tea bags','green tea'],
}
ALIAS_TO_CANON = {}
for canon, aliases in SYNONYMS.items():
    ALIAS_TO_CANON[canon] = canon
    for a in aliases:
        ALIAS_TO_CANON[a.lower()] = canon
CANONICAL_INGREDIENTS = set(SYNONYMS.keys())

# =================================================================
# Generic helpers
# =================================================================
def clean_text(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_ingredient_name(line_text):
    """Strip qty/unit/preps, return (amount, unit, name_core)."""
    name = line_text
    amount, idx = parse_amount(name)
    rest = name[idx:].strip() if amount is not None else name
    unit = ''
    # Skip leading size descriptors so the real count unit is reachable.
    while True:
        m = re.match(r'^([a-zA-Z\.\-]+)\b\s*', rest)
        if not m: break
        cand = m.group(1).lower().rstrip('.')
        if cand in SIZE_DESCRIPTORS:
            rest = rest[m.end():]
            continue
        break
    m = re.match(r'^([a-zA-Z\.\-]+)\b', rest)
    if m:
        cand = m.group(1).lower().rstrip('.')
        if cand in ML_OF or cand in G_OF or cand in COUNT_UNITS or cand in {'fluid','fl'}:
            unit = cand
            rest = rest[m.end():].strip()
            # absorb a second token like "ounces" after "fluid"
            m2 = re.match(r'^(ounces?|oz)\b', rest)
            if cand in {'fluid','fl'} and m2:
                rest = rest[m2.end():].strip()
    rest = re.sub(r'^(of\s+|to\s+)+', '', rest)
    # Strip leading meat/fish prep modifiers separated by commas
    # e.g. "boneless, skin-on wild salmon fillet" → "wild salmon fillet"
    rest = re.sub(r'^(?:(?:boneless|bone-in|skin-on|skin-removed|skinless|deboned)\s*,\s*)+', '', rest, flags=re.I)
    # Strip leading "wild" / "raw" descriptors (not unit, not in unit detector)
    rest = re.sub(r'^(?:wild|raw|live)\s+', '', rest, flags=re.I)
    rest_no_paren = re.sub(r'\([^)]*\)', '', rest).strip()
    # *** Fix #3: split on semicolons and on commas-with-preps.
    # DO NOT split on bare " or " — it drops the actual ingredient
    # (e.g. "coarse kosher or sea salt"). Substring fallback handles those.
    split_re = r'(?:;|,\s*(?:(?:finely|coarsely|roughly|thinly|lightly|freshly|partially|fully|very)\s+)?(?:chopped|sliced|diced|minced|grated|crushed|halved|quartered|peeled|cored|seeded|stemmed|trimmed|cubed|shredded|julienned|cut|broken|toasted|roasted|softened|melted|drained|rinsed|optional|divided|to taste|or more|or to taste|plus more|preferably|picked over|washed|soaked|skinned|deveined|deboned|boneless|skin-on|warmed|reconstituted|stems? removed|seeds? removed|tail-on|for [a-z\- ]+))'
    rest_clean = re.split(split_re, rest_no_paren, maxsplit=1)[0]
    # Trailing strip in three passes:
    # 1) Phrases preceded by whitespace
    rest_clean = re.sub(r'\s+(?:to taste|as needed|or to taste|optional|divided|for garnish|for serving|for tempering|for frying|for deep-frying|for pan-frying|for greasing|for dusting|for kneading|for brushing|for sprinkling|at room temperature|room temperature).*$', '', rest_clean, flags=re.I)
    # 2) Comma clauses ("oil, plus extra for brushing", "amaranth, well rinsed, tough stems")
    rest_clean = re.sub(r',\s*(?:plus (?:more|extra)|well rinsed|rinsed and drained|tough stems? discarded|tough ends? discarded|stem removed|stems? removed|seeds? removed|soaked\b|at room temperature|partially thawed|thawed).*$', '', rest_clean, flags=re.I)
    # 3) Trailing "for X" (no-comma form)
    rest_clean = re.sub(r'\s+for\s+(?:pan-frying|deep-frying|frying|tempering|garnish|garnishing|serving|brushing|kneading|dusting|sprinkling).*$', '', rest_clean, flags=re.I)
    tokens = rest_clean.split()
    while tokens and tokens[0].lower() in STOPWORDS:
        tokens.pop(0)
    name_core = ' '.join(tokens).strip(' ,.;:').lower()
    name_core = re.sub(r'\s+', ' ', name_core)
    return amount, unit, name_core

def canonicalize(name_core, subrecipe_titles):
    """Resolve to canonical ingredient name OR sub-recipe canonical name."""
    if not name_core:
        return None
    n = name_core.strip()
    # Try sub-recipe titles first (their canonical = title lowercased)
    if n in subrecipe_titles:
        return n
    if n in ALIAS_TO_CANON:
        return ALIAS_TO_CANON[n]
    # NOTE: 'ground' is intentionally NOT stripped here — it distinguishes
    # ground X from whole X for spices that exist in both forms.
    n2 = re.sub(r'^(red|green|yellow|black|white|brown|orange|small|medium|large|fresh|dried|whole|skinless|boneless)\s+', '', n)
    if n2 in ALIAS_TO_CANON: return ALIAS_TO_CANON[n2]
    parts = n.split()
    for k in (3, 2, 1):
        if len(parts) >= k:
            tail = ' '.join(parts[-k:])
            if tail in ALIAS_TO_CANON: return ALIAS_TO_CANON[tail]
            head = ' '.join(parts[:k])
            if head in subrecipe_titles: return head
    # Sort canonicals longest-first (and alphabetically for tiebreak — without
    # this, set hash ordering makes the result non-deterministic across runs).
    for canon in sorted(CANONICAL_INGREDIENTS, key=lambda c: (-len(c), c)):
        if canon in n:
            return canon
    return n  # fallback

# =================================================================
# Recipe parsing — pass 1: all h3a + h3b, plus rec anchors and cross-refs
# =================================================================
RECIPE_RE = re.compile(r'<h3\s+class="(h3a|h3b)"[^>]*>(.*?)</h3>(.*?)(?=<h3\s+class="(?:h3a|h3b)"|<h2|\Z)', re.DOTALL)
SUB_RE = re.compile(r'<h3\s+class="h3c"[^>]*>(.*?)</h3>', re.DOTALL)
REGION_RE = re.compile(r'<h3\s+class="h3d"[^>]*>(.*?)</h3>', re.DOTALL)
ETITLE_RE = re.compile(r'<h3\s+class="h3e"[^>]*>(.*?)</h3>', re.DOTALL)
SERVES_RE = re.compile(r'<span class="RY">\s*(?:SERVES|MAKES|YIELD[S]?)\s+([^<]+)</span>', re.I)
ITEM_RE = re.compile(r'<p\s+class="(item|itemb)"[^>]*>(.*?)</p>', re.DOTALL)
ANCHOR_IN_H3 = re.compile(r'<a\s+id="(rec\w+)"')
HREF_RE = re.compile(r'<a\s+href="([^"]+)#(rec\w+)"', re.I)

def parse_makes(text):
    """Parse '1½ cups' or 'about 1 cup' or 'a scant ½ cup' into (amount, unit)."""
    text = text.strip().lower()
    # Strip natural-language qualifiers the book uses
    text = re.sub(r'^(?:about|approximately|a scant|scant|almost|nearly|a generous|generous|a heaping|heaping|just under|just over)\s+', '', text)
    text = re.sub(r'^a\s+(?=[\d¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚])', '', text)  # bare "a" before a number
    a, idx = parse_amount(text)
    rest = text[idx:].strip()
    unit_match = re.match(r'^(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pints?|quarts?|ounces?|pounds?)\b', rest)
    unit = unit_match.group(1) if unit_match else ''
    return a, unit

def preprocess_html(html):
    """Normalize variant recipe-boundary markups into h3a/h3b form.

    Two patterns are missed by the bare h3a/h3b regex:

    1. <h3 class="h3d">[<a id="rec*"/>]STYLE</h3><h3 class="h3e|h3f">TITLE</h3>
       — h3d is the style label, h3e/h3f holds the real title, and the
       rec anchor (when present) belongs to this recipe. Used widely in
       chapter 2 for spice-blend variants and elsewhere for regional
       variants of fish/lentil/vegetable preparations.

    2. <h3 class="h3bno">TITLE</h3>
       — same as h3b but with suppressed top border, used for the first
       recipe of a new <h2> section ("Beef" → first beef recipe).

    Without this preprocessing, ~15 recipes go undetected and their
    ingredient lists are silently merged into the preceding h3a/h3b
    recipe, polluting its ingredients and breaking cross-references.
    """
    def promote(m):
        anchor_part = m.group(1) or ''
        style_text = m.group(2).strip()
        title = m.group(3).strip()
        return f'<h3 class="h3a">{anchor_part}{title}</h3>\n<h3 class="h3d">{style_text}</h3>'
    html = re.sub(
        r'<h3 class="h3d">((?:<a[^>]+/?>)*)([^<]*)</h3>\s*<h3 class="h3[ef]">([^<]+)</h3>',
        promote, html
    )
    html = html.replace('<h3 class="h3bno">', '<h3 class="h3b">')
    return html

def parse_all_recipes():
    recipes = []
    for path in sorted(glob.glob(f'{XHTML}/chapter*.html')):
        base = os.path.basename(path).replace('.html','')
        if base not in CHAPTER_CATEGORIES: continue
        cat, cat_label = CHAPTER_CATEGORIES[base]
        with open(path) as f:
            content = preprocess_html(f.read())
        # (content is the already-preprocessed HTML from above)
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
            # NOTE: h3e is intentionally NOT prepended — it often belongs to the
            # NEXT inline recipe inside the same body block (e.g. chapter2 packs
            # several variants under one h3a). Doing so produced bad titles like
            # "Madras Curry Powder — Whole Milk Solids" where the recipe is
            # actually just "Whole Milk Solids".
            region_text = clean_text(region.group(1)) if region else None
            serves_amount = None
            serves_unit = None
            serves_keyword = None
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
                # detect a cross-ref to a sub-recipe in this line
                ref_ids = []
                for href_m in HREF_RE.finditer(raw_item):
                    # only 'recipe' anchor type (skip box/Tips)
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

# =================================================================
# Build sub-recipe index
# =================================================================
def build_subrecipe_index(recipes):
    """A recipe is a sub-recipe if its rec_id is referenced from any ingredient line."""
    referenced = set()
    for r in recipes:
        for ing in r['ingredients_raw']:
            for rid in ing['ref_ids']:
                referenced.add(rid)
    # Index by rec_id
    by_rec_id = {r['rec_id']: r for r in recipes if r['rec_id']}
    # A recipe is a sub-recipe IFF its rec_id is referenced
    for r in recipes:
        r['is_subrecipe'] = (r['rec_id'] in referenced) if r['rec_id'] else False
    # Sub-recipe titles (lowercased) used during canonicalization
    sub_titles = {r['title'].lower(): r for r in recipes if r['is_subrecipe']}
    return by_rec_id, sub_titles, referenced

# =================================================================
# Final ingredient resolution pass (uses sub-recipe titles)
# =================================================================
def resolve_ingredients(recipes, by_rec_id, sub_titles):
    subrecipe_title_lookup = set(sub_titles.keys())
    for r in recipes:
        resolved = []
        for ing in r['ingredients_raw']:
            line = ing['line']
            ref_ids = ing['ref_ids']
            amount, unit, name_core = extract_ingredient_name(line)
            # If this line has a cross-ref, the canonical IS the sub-recipe title
            if ref_ids and ref_ids[0] in by_rec_id:
                sub = by_rec_id[ref_ids[0]]
                canon = sub['title'].lower()
                is_subref = True
                via_rec_id = ref_ids[0]
            else:
                canon = canonicalize(name_core, subrecipe_title_lookup)
                if canon is None:
                    continue
                # Detect if canonical maps to a sub-recipe by title
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

# =================================================================
# Expand sub-recipes recursively (depth-first with cycle detection)
# =================================================================
def cup_equivalent(amount, unit):
    """Express (amount,unit) in cups, for scaling sub-recipes."""
    if amount is None: return None
    u = (unit or '').lower()
    if u in ('cup','cups'): return amount
    if u in ('tablespoon','tablespoons','tbsp','tbsps','tbs'): return amount / 16
    if u in ('teaspoon','teaspoons','tsp','tsps'): return amount / 48
    if u in ('pint','pints'): return amount * 2
    if u in ('quart','quarts'): return amount * 4
    return None  # cannot scale non-volume amounts

def expand_subrecipes(recipes, by_rec_id, sub_titles, max_depth=5):
    """For every direct sub-recipe reference, expand its constituent ingredients
    (scaled by amount/yield) and append to the parent's ingredient list,
    tagged source='expanded'."""
    title_to_rec = sub_titles
    def expand(parent_id, ing, depth, visited):
        """Return list of expanded ingredient dicts for one sub-ref line."""
        if depth > max_depth: return []
        sub = None
        if ing.get('via_rec_id') and ing['via_rec_id'] in by_rec_id:
            sub = by_rec_id[ing['via_rec_id']]
        elif ing['canonical'] in title_to_rec:
            sub = title_to_rec[ing['canonical']]
        if sub is None: return []
        if sub['rec_id'] in visited: return []  # cycle
        # determine scale factor = parent amount / sub yield (both in cups)
        parent_cups = cup_equivalent(ing['amount'], ing['unit'])
        sub_yield_cups = cup_equivalent(sub.get('serves_amount'), sub.get('serves_unit'))
        scale = None
        if parent_cups and sub_yield_cups and sub_yield_cups > 0:
            scale = parent_cups / sub_yield_cups
        # If scale unknown, use 1.0 as best effort but flag it
        scale_known = scale is not None
        if scale is None:
            scale = 1.0
        out = []
        new_visited = visited | {sub['rec_id']}
        for sub_ing in sub.get('ingredients', []):
            scaled_amount = sub_ing['amount'] * scale if sub_ing['amount'] is not None else None
            grams = sub_ing['grams_est'] * scale if sub_ing['grams_est'] is not None else None
            new_ing = {
                'raw': f'[expanded from {sub["title"]}] {sub_ing["raw"]}',
                'amount': scaled_amount,
                'unit': sub_ing['unit'],
                'name_raw': sub_ing['name_raw'],
                'canonical': sub_ing['canonical'],
                'grams_est': grams,
                'normalized': sub_ing['normalized'],
                'gram_source': sub_ing['gram_source'],
                'is_subrecipe_ref': False,
                'via_rec_id': sub['rec_id'],
                'scale_known': scale_known,
                'scale_factor': scale,
                'expansion_depth': depth,
            }
            out.append(new_ing)
            # recurse if this sub-ingredient is itself a sub-recipe reference
            # (but NOT if it's a pantry staple — those are terminal)
            if sub_ing.get('is_subrecipe_ref') and sub_ing['canonical'] not in PANTRY_STAPLES:
                out.extend(expand(parent_id, sub_ing, depth+1, new_visited))
        return out
    for r in recipes:
        expanded = []
        for ing in r['ingredients']:
            if ing.get('is_subrecipe_ref') and ing['canonical'] not in PANTRY_STAPLES:
                expanded.extend(expand(r['rec_id'], ing, 1, set()))
        r['expanded_ingredients'] = expanded

# =================================================================
# SQLite population
# =================================================================
SCHEMA = '''
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS recipe_ingredient;
DROP TABLE IF EXISTS ingredient_role;
DROP TABLE IF EXISTS ingredient_alias;
DROP TABLE IF EXISTS ingredient;
DROP TABLE IF EXISTS recipe;

CREATE TABLE recipe (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  external_id     TEXT UNIQUE,
  title           TEXT NOT NULL,
  category        TEXT NOT NULL,
  category_label  TEXT NOT NULL,
  chapter_file    TEXT NOT NULL,
  region          TEXT,
  is_subrecipe    INTEGER NOT NULL DEFAULT 0,
  yield_amount    REAL,
  yield_unit      TEXT,
  yield_keyword   TEXT,    -- SERVES | MAKES | YIELDS | YIELD
  num_direct_ingredients INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_recipe_category ON recipe(category);
CREATE INDEX idx_recipe_external ON recipe(external_id);
CREATE INDEX idx_recipe_subrecipe ON recipe(is_subrecipe);

CREATE TABLE ingredient (
  canonical            TEXT PRIMARY KEY,
  is_subrecipe         INTEGER NOT NULL DEFAULT 0,
  is_pantry_staple     INTEGER NOT NULL DEFAULT 0,  -- sub-recipe but treated as terminal (ghee, paneer, etc.)
  subrecipe_recipe_id  INTEGER REFERENCES recipe(id),
  recipe_count_direct  INTEGER NOT NULL DEFAULT 0,
  recipe_count_expanded INTEGER NOT NULL DEFAULT 0,
  category_count       INTEGER NOT NULL DEFAULT 0,
  heat_sensitivity     REAL,
  versatility_score    REAL,
  density_g_per_cup    REAL,
  piece_weight_g       REAL
);

CREATE TABLE ingredient_alias (
  alias       TEXT PRIMARY KEY,
  canonical   TEXT NOT NULL REFERENCES ingredient(canonical)
);

CREATE TABLE ingredient_role (
  canonical   TEXT NOT NULL REFERENCES ingredient(canonical),
  role        TEXT NOT NULL,
  PRIMARY KEY (canonical, role)
);

CREATE TABLE recipe_ingredient (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  recipe_id       INTEGER NOT NULL REFERENCES recipe(id),
  canonical       TEXT NOT NULL REFERENCES ingredient(canonical),
  raw_line        TEXT NOT NULL,
  amount          REAL,
  unit            TEXT,
  grams_est       REAL,
  normalized      INTEGER NOT NULL DEFAULT 0,
  gram_source     TEXT,
  source          TEXT NOT NULL CHECK (source IN ('direct','expanded')),
  via_recipe_id   INTEGER REFERENCES recipe(id),
  scale_factor    REAL,
  scale_known     INTEGER,
  expansion_depth INTEGER
);
CREATE INDEX idx_ri_canon  ON recipe_ingredient(canonical);
CREATE INDEX idx_ri_recipe ON recipe_ingredient(recipe_id);
CREATE INDEX idx_ri_source ON recipe_ingredient(source);

CREATE VIEW v_ingredient_global_freq AS
SELECT canonical,
       SUM(CASE WHEN source='direct'   THEN 1 ELSE 0 END) AS n_direct,
       SUM(CASE WHEN source='expanded' THEN 1 ELSE 0 END) AS n_expanded,
       COUNT(DISTINCT recipe_id) AS n_recipes_any_source
FROM   recipe_ingredient
GROUP  BY canonical;

CREATE VIEW v_ingredient_category_usage AS
SELECT ri.canonical,
       r.category,
       ri.source,
       COUNT(DISTINCT ri.recipe_id) AS n_recipes,
       (SELECT COUNT(*) FROM recipe r2 WHERE r2.category = r.category) AS total_in_category
FROM   recipe_ingredient ri
JOIN   recipe r ON r.id = ri.recipe_id
GROUP  BY ri.canonical, r.category, ri.source;
'''

ROLE_PRIORS = {
    'tempering': {'cumin seeds','mustard seeds','fenugreek seeds','nigella seeds','fennel seeds',
                  'asafetida','curry leaves','dried red chile','bay leaf','cloves','cinnamon',
                  'cardamom, green','cardamom, black','star anise',"bishop's weed",
                  'black pepper','mace'},
    'base_aromatic': {'onion','shallot','garlic','ginger','green chile','tomato','scallions',
                      'ghee','vegetable oil','mustard oil','coconut oil','sesame oil','butter'},
    'ground_spice': {'turmeric','ground cumin','ground coriander','cayenne','red chile powder',
                     'paprika','ground black pepper','garam masala','mango powder','nutmeg',
                     'ground mace','ground cinnamon','ground cloves','ground cardamom',
                     'ground mustard','ground fennel','ground fenugreek','ground ginger',
                     'dried pomegranate seeds','black salt','salt','sugar'},
    'finishing': {'cilantro','mint','dill','basil','holy basil','lime','lemon','yogurt',
                  'cream','rose water','screw pine','saffron','black salt','ghee'},
}
ROLE_OF = defaultdict(list)
for role, items in ROLE_PRIORS.items():
    for it in items:
        ROLE_OF[it].append(role)

# Sub-recipes that are distinct culinary objects, not composed dishes to expand.
# When another recipe references one of these, treat it as a terminal ingredient
# (do not pull its constituent ingredients into the parent).
PANTRY_STAPLES = {
    'ghee',                    # clarified butter → distinct ingredient
    'whole-milk cheese',       # paneer
    'creamy homemade cheese',  # softer paneer variant
    'thick yogurt',            # drained yogurt; recipes asking for this mean the texture
}

HEAT_SENSITIVITY_PRIORS = {
    'cilantro':0.95,'mint':0.95,'dill':0.9,'basil':0.9,'holy basil':0.9,
    'curry leaves':0.4,'fenugreek leaves':0.6,'kaffir lime leaves':0.5,
    'lime':0.95,'lemon':0.95,'yogurt':0.8,'buttermilk':0.85,'cream':0.7,
    'rose water':1.0,'screw pine':1.0,'saffron':0.6,'garam masala':0.7,
    'mango powder':0.5,'black salt':0.5,
    'cumin seeds':0.1,'mustard seeds':0.1,'fenugreek seeds':0.1,'nigella seeds':0.1,
    'asafetida':0.15,'cloves':0.15,'cinnamon':0.15,'cardamom, green':0.2,
    'cardamom, black':0.2,'star anise':0.15,'bay leaf':0.2,
    'turmeric':0.25,'cayenne':0.3,'paprika':0.3,'ground coriander':0.3,'ground cumin':0.3,
    'onion':0.1,'garlic':0.1,'ginger':0.15,'tomato':0.2,'green chile':0.25,
    'salt':0.4,'sugar':0.5,'ghee':0.5,
}

def populate_db(recipes):
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    # Pass 1: insert recipes
    title_to_id = {}
    for r in recipes:
        cur.execute('''INSERT INTO recipe
                       (external_id,title,category,category_label,chapter_file,region,
                        is_subrecipe,yield_amount,yield_unit,yield_keyword,num_direct_ingredients)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (r['rec_id'], r['title'], r['category'], r['category_label'],
                     r['chapter_file'], r['region'], int(r['is_subrecipe']),
                     r['serves_amount'], r['serves_unit'], r['serves_keyword'],
                     len(r['ingredients'])))
        r['db_id'] = cur.lastrowid
        title_to_id[r['title'].lower()] = r['db_id']
    # Pass 2: collect canonical → first observed recipe id (if it's a sub-recipe)
    canon_to_subrecipe_db_id = {}
    for r in recipes:
        if r['is_subrecipe']:
            canon_to_subrecipe_db_id[r['title'].lower()] = r['db_id']
    # Pass 3: collect all canonicals across direct + expanded
    all_canons = set()
    for r in recipes:
        for ing in r['ingredients'] + r.get('expanded_ingredients', []):
            all_canons.add(ing['canonical'])
    for canon in all_canons:
        is_sub = canon in canon_to_subrecipe_db_id
        cur.execute('''INSERT INTO ingredient
                       (canonical,is_subrecipe,is_pantry_staple,subrecipe_recipe_id,
                        heat_sensitivity,density_g_per_cup,piece_weight_g)
                       VALUES (?,?,?,?,?,?,?)''',
                    (canon, int(is_sub), int(canon in PANTRY_STAPLES),
                     canon_to_subrecipe_db_id.get(canon),
                     HEAT_SENSITIVITY_PRIORS.get(canon),
                     DENSITY_G_PER_CUP.get(canon),
                     PIECE_WEIGHT.get(canon)))
    # Pass 4: aliases
    for alias, canon in ALIAS_TO_CANON.items():
        if canon in all_canons:
            try:
                cur.execute('INSERT INTO ingredient_alias (alias,canonical) VALUES (?,?)',
                            (alias, canon))
            except sqlite3.IntegrityError:
                pass
    # Pass 5: roles
    for canon in all_canons:
        for role in ROLE_OF.get(canon, []):
            cur.execute('INSERT INTO ingredient_role (canonical,role) VALUES (?,?)',
                        (canon, role))
    # Pass 6: recipe_ingredient rows (direct + expanded)
    def via_db_id(rec_id):
        if not rec_id: return None
        for r in recipes:
            if r['rec_id'] == rec_id: return r['db_id']
        return None
    for r in recipes:
        for ing in r['ingredients']:
            cur.execute('''INSERT INTO recipe_ingredient
                           (recipe_id,canonical,raw_line,amount,unit,grams_est,normalized,
                            gram_source,source,via_recipe_id,scale_factor,scale_known,expansion_depth)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (r['db_id'], ing['canonical'], ing['raw'], ing['amount'], ing['unit'],
                         ing['grams_est'], int(ing['normalized']), ing['gram_source'],
                         'direct',
                         via_db_id(ing.get('via_rec_id')),
                         None, None, None))
        for ing in r.get('expanded_ingredients', []):
            cur.execute('''INSERT INTO recipe_ingredient
                           (recipe_id,canonical,raw_line,amount,unit,grams_est,normalized,
                            gram_source,source,via_recipe_id,scale_factor,scale_known,expansion_depth)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (r['db_id'], ing['canonical'], ing['raw'], ing['amount'], ing['unit'],
                         ing['grams_est'], int(ing['normalized']), ing['gram_source'],
                         'expanded',
                         via_db_id(ing.get('via_rec_id')),
                         ing.get('scale_factor'),
                         int(bool(ing.get('scale_known'))),
                         ing.get('expansion_depth')))
    # Pass 7: backfill ingredient counts and versatility
    cur.execute('''UPDATE ingredient SET
                   recipe_count_direct = COALESCE((
                     SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredient
                     WHERE canonical = ingredient.canonical AND source='direct'), 0),
                   recipe_count_expanded = COALESCE((
                     SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredient
                     WHERE canonical = ingredient.canonical), 0),
                   category_count = COALESCE((
                     SELECT COUNT(DISTINCT r.category)
                     FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                     WHERE ri.canonical = ingredient.canonical), 0)''')
    # versatility = (categories_present / total_categories) * ln(1 + recipe_count_expanded)
    cur.execute('SELECT COUNT(DISTINCT category) FROM recipe')
    n_cats = cur.fetchone()[0]
    cur.execute('SELECT canonical, recipe_count_expanded, category_count FROM ingredient')
    rows = cur.fetchall()
    for canon, n_rec, n_cat in rows:
        vs = round((n_cat / n_cats) * math.log(1 + n_rec), 3) if n_rec else 0
        cur.execute('UPDATE ingredient SET versatility_score = ? WHERE canonical = ?', (vs, canon))
    con.commit()
    return con

# =================================================================
# Analytics export — JSON and human-readable .md
# =================================================================
def export_outputs(con, recipes):
    cur = con.cursor()
    # Total recipes (excluding spice_blend / sub-recipes from headline frequency stats)
    cur.execute('SELECT COUNT(*) FROM recipe')
    total_recipes_all = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM recipe WHERE is_subrecipe = 0')
    total_main_recipes = cur.fetchone()[0]
    cur.execute('SELECT category, COUNT(*) FROM recipe GROUP BY category')
    cats = dict(cur.fetchall())
    cur.execute('SELECT AVG(yield_amount) FROM recipe WHERE yield_keyword="SERVES"')
    avg_serves = cur.fetchone()[0]

    # Per-ingredient records
    cur.execute('''SELECT canonical, is_subrecipe, subrecipe_recipe_id, recipe_count_direct,
                          recipe_count_expanded, category_count, heat_sensitivity,
                          versatility_score, density_g_per_cup, piece_weight_g
                   FROM ingredient ORDER BY recipe_count_expanded DESC''')
    rows = cur.fetchall()
    ingredients_export = {}
    for (canon, is_sub, sub_rid, n_d, n_e, n_c, heat, vers, dens, pw) in rows:
        # Category breakdown
        cur.execute('''SELECT r.category, COUNT(DISTINCT ri.recipe_id) AS n,
                              (SELECT COUNT(*) FROM recipe r2 WHERE r2.category = r.category) AS tot
                       FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                       WHERE ri.canonical = ? AND ri.source = 'direct'
                       GROUP BY r.category''', (canon,))
        cat_direct = {c: {'n': n, 'total_in_cat': t} for c, n, t in cur.fetchall()}
        cur.execute('''SELECT r.category, COUNT(DISTINCT ri.recipe_id) AS n,
                              (SELECT COUNT(*) FROM recipe r2 WHERE r2.category = r.category) AS tot
                       FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                       WHERE ri.canonical = ?
                       GROUP BY r.category''', (canon,))
        cat_any = {c: {'n': n, 'total_in_cat': t} for c, n, t in cur.fetchall()}
        # Quantity stats (use grams_est across all sources)
        cur.execute('SELECT grams_est FROM recipe_ingredient WHERE canonical = ? AND grams_est IS NOT NULL', (canon,))
        qtys = [x[0] for x in cur.fetchall()]
        # Serves
        cur.execute('''SELECT r.yield_amount FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                       WHERE ri.canonical = ? AND r.yield_keyword = 'SERVES'
                       AND r.yield_amount IS NOT NULL''', (canon,))
        srvs = [x[0] for x in cur.fetchall()]
        # Co-occurrence (other ingredients in the same recipes)
        cur.execute('''SELECT ri2.canonical, COUNT(DISTINCT ri2.recipe_id)
                       FROM recipe_ingredient ri1
                       JOIN recipe_ingredient ri2
                            ON ri1.recipe_id = ri2.recipe_id AND ri1.canonical != ri2.canonical
                       WHERE ri1.canonical = ?
                       GROUP BY ri2.canonical
                       ORDER BY 2 DESC LIMIT 10''', (canon,))
        top_pairs = cur.fetchall()
        ingredients_export[canon] = {
            'canonical': canon,
            'is_subrecipe': bool(is_sub),
            'subrecipe_recipe_id': sub_rid,
            'recipe_count_direct': n_d,
            'recipe_count_expanded': n_e,
            'global_freq_direct_pct': round(100 * n_d / total_main_recipes, 2) if total_main_recipes else 0,
            'global_freq_expanded_pct': round(100 * n_e / total_main_recipes, 2) if total_main_recipes else 0,
            'category_count': n_c,
            'heat_sensitivity': heat,
            'versatility_score': vers,
            'density_g_per_cup': dens,
            'piece_weight_g': pw,
            'positional_roles': ROLE_OF.get(canon, ['unclassified']),
            'category_usage_direct': cat_direct,
            'category_usage_any_source': cat_any,
            'p_ingredient_given_category_direct': {c: round(v['n']/v['total_in_cat'], 4)
                                                    for c, v in cat_direct.items()},
            'p_category_given_ingredient_direct': {c: round(v['n']/n_d, 4)
                                                    for c, v in cat_direct.items()} if n_d else {},
            'quantity_g': {
                'n_with_qty': len(qtys),
                'mean': round(statistics.mean(qtys), 2) if qtys else None,
                'median': round(statistics.median(qtys), 2) if qtys else None,
                'min': round(min(qtys), 2) if qtys else None,
                'max': round(max(qtys), 2) if qtys else None,
                'total': round(sum(qtys), 2) if qtys else None,
            },
            'serves_when_present_mean': round(statistics.mean(srvs), 2) if srvs else None,
            'global_avg_serves': round(avg_serves, 2) if avg_serves else None,
            'top_co_occurring': [(c, n) for c, n in top_pairs],
        }

    # Derived: spice intensity per category
    SPICES = set(ROLE_PRIORS['tempering']) | set(ROLE_PRIORS['ground_spice'])
    cur.execute('''SELECT r.category, ri.recipe_id, COUNT(DISTINCT ri.canonical)
                   FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                   WHERE ri.canonical IN (%s)
                   GROUP BY r.category, ri.recipe_id''' % ','.join(['?']*len(SPICES)),
                tuple(SPICES))
    spice_per_cat = defaultdict(list)
    for cat, rid, n in cur.fetchall():
        spice_per_cat[cat].append(n)
    spice_intensity = {cat: {'mean_spices_per_recipe': round(statistics.mean(v),2),
                              'recipes_with_spices': len(v)}
                       for cat, v in spice_per_cat.items()}

    # Heat distribution
    CHILES = ('green chile','dried red chile','cayenne','red chile powder')
    cur.execute('SELECT id FROM recipe WHERE is_subrecipe = 0')
    main_recipe_ids = [x[0] for x in cur.fetchall()]
    heat_buckets = Counter()
    for rid in main_recipe_ids:
        cur.execute('''SELECT SUM(COALESCE(grams_est,0)) FROM recipe_ingredient
                       WHERE recipe_id = ? AND canonical IN (?,?,?,?)''',
                    (rid, *CHILES))
        total = cur.fetchone()[0] or 0
        if total == 0: heat_buckets['none'] += 1
        elif total < 1: heat_buckets['low'] += 1
        elif total < 5: heat_buckets['medium'] += 1
        else: heat_buckets['high'] += 1

    # Core set (excluding salt+oil)
    cur.execute('SELECT id FROM recipe WHERE is_subrecipe = 0')
    main_ids = set(x[0] for x in cur.fetchall())
    cur.execute('''SELECT recipe_id, canonical FROM recipe_ingredient
                   WHERE source IN ('direct','expanded')''')
    rid_to_canons = defaultdict(set)
    for rid, c in cur.fetchall():
        if rid in main_ids:
            rid_to_canons[rid].add(c)
    def greedy(skip=()):
        covered = set(); core = []
        target = int(0.8 * len(main_ids))
        while len(covered) < target:
            gains = Counter()
            for rid, canons in rid_to_canons.items():
                if rid in covered: continue
                for c in canons:
                    if c in skip: continue
                    gains[c] += 1
            if not gains: break
            best, g = gains.most_common(1)[0]
            core.append((best, g))
            for rid, canons in rid_to_canons.items():
                if best in canons: covered.add(rid)
        return core, len(covered)
    core_all, cov_all = greedy()
    core_ex, cov_ex = greedy(skip=('salt','vegetable oil'))

    derived = {
        'total_recipes_all': total_recipes_all,
        'total_main_recipes': total_main_recipes,
        'subrecipe_count': total_recipes_all - total_main_recipes,
        'categories': cats,
        'global_avg_serves': avg_serves,
        'spice_intensity_per_category': spice_intensity,
        'heat_level_distribution_grams': dict(heat_buckets),
        'core_set_80pct': {'size': len(core_all), 'recipes_covered': cov_all, 'items': core_all},
        'core_set_80pct_excl_salt_oil': {'size': len(core_ex), 'recipes_covered': cov_ex, 'items': core_ex},
    }

    # Recipes export
    recipes_export = []
    cur.execute('''SELECT id, external_id, title, category, region, is_subrecipe,
                          yield_keyword, yield_amount, yield_unit, num_direct_ingredients
                   FROM recipe ORDER BY id''')
    for row in cur.fetchall():
        rid = row[0]
        cur.execute('''SELECT canonical, raw_line, amount, unit, grams_est, source,
                              via_recipe_id, scale_factor
                       FROM recipe_ingredient WHERE recipe_id = ? ORDER BY id''', (rid,))
        ings = [{'canonical': c, 'raw': raw, 'amount': a, 'unit': u, 'grams_est': g,
                 'source': s, 'via_recipe_id': v, 'scale_factor': sf}
                for c, raw, a, u, g, s, v, sf in cur.fetchall()]
        recipes_export.append({
            'id': rid, 'external_id': row[1], 'title': row[2], 'category': row[3],
            'region': row[4], 'is_subrecipe': bool(row[5]),
            'yield_keyword': row[6], 'yield_amount': row[7], 'yield_unit': row[8],
            'num_direct_ingredients': row[9],
            'ingredients': ings,
        })

    # JSON
    dataset = {
        'meta': {
            'source': '660 Curries (epub)',
            'total_recipes': total_recipes_all,
            'main_recipes': total_main_recipes,
            'sub_recipes': total_recipes_all - total_main_recipes,
            'distinct_canonical_ingredients': len(ingredients_export),
            'normalization_notes': [
                'Quantities normalized to grams using a curated density table (140+ entries) by canonical ingredient.',
                'Count units (cloves, sprigs, leaves) converted via per-piece weights for common items; others left as NULL.',
                'Sub-recipes (chapter 2 spice blends + cross-referenced sauces) detected from <a href="#rec*"> markup.',
                'Sub-recipes are dual-indexed: queryable as ingredients AND as their own recipes.',
                'recipe_ingredient.source distinguishes "direct" (written in cookbook) from "expanded" (scaled in via sub-recipe).',
                'Sub-recipe expansion uses parent_amount / sub_recipe_yield (both in cups) as scale factor.',
                'Recursion limited to depth 5 with cycle detection.',
            ],
        },
        'derived': derived,
        'ingredients': ingredients_export,
        'recipes': recipes_export,
    }
    with open(f'{OUT_DIR}/660_curries_dataset.json', 'w') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=1)

    # Human-readable
    lines = [
        '# 660 Curries — Ingredient Analytics (v2)\n',
        f'Total recipes: **{total_recipes_all}** (of which **{total_recipes_all-total_main_recipes}** are sub-recipes used as ingredients elsewhere)',
        f'Main recipes for frequency stats: **{total_main_recipes}**',
        f'Distinct canonical ingredients: **{len(ingredients_export)}**',
        f'Global average servings per recipe: **{avg_serves:.2f}**' if avg_serves else '',
        '\nCategory totals:',
    ]
    for c, n in sorted(cats.items(), key=lambda x:-x[1]):
        lines.append(f'  - {c}: {n} recipes')
    lines.append('\n---\n## Ingredient Index (alphabetical)\n')
    for canon in sorted(ingredients_export.keys()):
        r = ingredients_export[canon]
        tag = ' *(sub-recipe)*' if r['is_subrecipe'] else ''
        lines.append(f'### {canon}{tag}')
        lines.append(f'- Frequency: **{r["recipe_count_direct"]}** direct / **{r["recipe_count_expanded"]}** including sub-recipe expansion '
                     f'({r["global_freq_direct_pct"]}% / {r["global_freq_expanded_pct"]}% of {total_main_recipes} main recipes)')
        lines.append(f'- Appears in {r["category_count"]} categories')
        if r['category_usage_direct']:
            lines.append('- Category usage (direct):')
            for c, v in sorted(r['category_usage_direct'].items(), key=lambda x:-x[1]['n']):
                p_ic = round(v['n']/v['total_in_cat'], 3)
                p_ci = round(v['n']/r['recipe_count_direct'], 3) if r['recipe_count_direct'] else 0
                lines.append(f'    - {c}: {v["n"]} / {v["total_in_cat"]}  (P(ingr|cat)={p_ic}, P(cat|ingr)={p_ci})')
        q = r['quantity_g']
        if q['n_with_qty']:
            lines.append(f'- Quantity (g): n={q["n_with_qty"]} mean={q["mean"]} median={q["median"]} range={q["min"]}–{q["max"]} total={q["total"]}')
        if r['density_g_per_cup'] is not None:
            lines.append(f'- Density used: {r["density_g_per_cup"]} g/cup')
        if r['piece_weight_g'] is not None:
            lines.append(f'- Per-piece weight: {r["piece_weight_g"]} g')
        if r['serves_when_present_mean']:
            lines.append(f'- Avg servings when present: {r["serves_when_present_mean"]} (global avg {r["global_avg_serves"]})')
        if r['top_co_occurring']:
            pairs = ', '.join(f'{n}× {x}' for x, n in r['top_co_occurring'])
            lines.append(f'- Top co-occurring: {pairs}')
        lines.append(f'- Versatility: {r["versatility_score"]}  |  Role(s): {", ".join(r["positional_roles"])}  |  Heat-sensitivity: {r["heat_sensitivity"]}')
        lines.append('')

    lines.append('\n---\n## Derived Analytics\n')
    lines.append('### Spice intensity per category')
    for cat, v in sorted(spice_intensity.items(), key=lambda x:-x[1]['mean_spices_per_recipe']):
        lines.append(f'- {cat}: mean {v["mean_spices_per_recipe"]} spices/recipe ({v["recipes_with_spices"]} recipes with ≥1 spice)')
    lines.append('\n### Heat level distribution (by total chile grams)')
    for k, n in derived['heat_level_distribution_grams'].items():
        lines.append(f'- {k}: {n} recipes')
    lines.append('\n### Core ingredient set (greedy, 80% coverage)')
    lines.append(f'Size: {derived["core_set_80pct"]["size"]} ingredients ({derived["core_set_80pct"]["recipes_covered"]} recipes covered)')
    for ing, gain in derived['core_set_80pct']['items']:
        lines.append(f'  - {ing} (+{gain})')
    lines.append('\n### Same, excluding salt + vegetable oil')
    lines.append(f'Size: {derived["core_set_80pct_excl_salt_oil"]["size"]} ingredients ({derived["core_set_80pct_excl_salt_oil"]["recipes_covered"]} recipes covered)')
    for ing, gain in derived['core_set_80pct_excl_salt_oil']['items']:
        lines.append(f'  - {ing} (+{gain})')

    with open(f'{OUT_DIR}/660_curries_ingredient_database.md', 'w') as f:
        f.write('\n'.join(lines))

# =================================================================
# Main
# =================================================================
def main():
    print('Parsing recipes…')
    recipes = parse_all_recipes()
    print(f'  raw recipes (h3a + h3b): {len(recipes)}')

    print('Building sub-recipe index…')
    by_rec_id, sub_titles, referenced = build_subrecipe_index(recipes)
    n_sub = sum(1 for r in recipes if r['is_subrecipe'])
    print(f'  sub-recipes identified: {n_sub}  (referenced rec ids: {len(referenced)})')

    print('Resolving ingredients (with sub-recipe awareness)…')
    resolve_ingredients(recipes, by_rec_id, sub_titles)
    n_lines = sum(len(r['ingredients']) for r in recipes)
    print(f'  direct ingredient lines: {n_lines}')

    print('Expanding sub-recipes…')
    expand_subrecipes(recipes, by_rec_id, sub_titles)
    n_exp = sum(len(r.get('expanded_ingredients',[])) for r in recipes)
    print(f'  expanded ingredient rows: {n_exp}')

    print('Populating SQLite…')
    con = populate_db(recipes)
    print(f'  DB written: {DB_PATH}')

    print('Exporting JSON + Markdown…')
    export_outputs(con, recipes)

    cur = con.cursor()
    print('\nTop 20 ingredients (by expanded recipe count):')
    cur.execute('''SELECT canonical, recipe_count_direct, recipe_count_expanded, is_subrecipe
                   FROM ingredient ORDER BY recipe_count_expanded DESC LIMIT 20''')
    for canon, d, e, is_sub in cur.fetchall():
        tag = ' [sub-recipe]' if is_sub else ''
        print(f'  {canon}: direct={d}, expanded={e}{tag}')

    print('\nTop sub-recipes (by direct reference count):')
    cur.execute('''SELECT canonical, recipe_count_direct FROM ingredient
                   WHERE is_subrecipe = 1 ORDER BY recipe_count_direct DESC LIMIT 15''')
    for canon, d in cur.fetchall():
        print(f'  {canon}: referenced in {d} recipes')

if __name__ == '__main__':
    main()
