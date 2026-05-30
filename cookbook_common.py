#!/usr/bin/env python3
"""Shared canonicalization, density tables, parsers, and SQLite schema.

Each cookbook has its own build script (Dishoom and 660 Curries parse very
different EPUB structures), but they all share:
  - the canonical-ingredient synonym dictionary
  - density (g/cup) + per-piece weights for amount-to-grams conversion
  - the amount/unit parser and the ingredient-name extractor
  - the SQLite schema (with a `book` table so recipes from different books
    coexist while ingredients/aliases stay global)
  - populate_book() and init_db() helpers

Build scripts call:
    con = init_db(DB_PATH)                 # drop-and-recreate; do this once per build_all run
    populate_book(con, book_meta, recipes) # called once per book
"""
import re, html, math, os, sqlite3, statistics, json
from collections import Counter, defaultdict

DB_PATH = '/home/kaustubh/Documents/GitHub/cookbook-database/cookbook.db'

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
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', text)
    if m:
        return (float(m.group(1))+float(m.group(2)))/2, m.end()
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
         'ml':1,'millilitre':1,'millilitres':1,'milliliter':1,'milliliters':1,
         'cl':10,'centilitre':10,'centilitres':10,
         'l':1000,'litre':1000,'litres':1000,'liter':1000,'liters':1000,
         'pint':473,'pints':473,'quart':946,'quarts':946,
         'fluid':30, 'fl':30}
G_OF = {'pound':454,'pounds':454,'lb':454,'lbs':454,
        'ounce':28,'ounces':28,'oz':28,
        'gram':1,'grams':1,'g':1,
        'kilogram':1000,'kilograms':1000,'kg':1000}
COUNT_UNITS = {'piece','pieces','clove','cloves','sprig','sprigs','leaf','leaves',
               'stalk','stalks','head','heads','bunch','bunches','can','cans',
               'package','packages','sheet','sheets','pinch','pinches','dash','dashes',
               'pod','pods','stick','sticks','strand','strands','small','medium','large',
               'whole','handful','knob','knobs','bulb','bulbs','quantity','quantities',
               'slice','slices','rasher','rashers'}
               # NOTE: 'egg'/'eggs' deliberately excluded — "2 egg whites" must
               # parse with name_core = "egg whites" so the aliasing → eggs works.
SIZE_DESCRIPTORS = {'small','medium','large','tiny','huge','jumbo','baby',
                    'small-size','medium-size','large-size','medium-sized','small-sized','large-sized',
                    'extra-large','extra-small','golf-ball-sized'}

# =================================================================
# Density table — grams per cup (240 ml).
# =================================================================
DENSITY_G_PER_CUP = {
    'water':240,'milk':245,'buttermilk':240,'yogurt':245,'cream':238,
    'half-and-half':242,'coconut milk':226,'vegetable oil':218,
    'mustard oil':215,'coconut oil':218,'sesame oil':218,'olive oil':218,
    'vinegar':240,'cider vinegar':240,'malt vinegar':240,'rice vinegar':240,'feni':240,
    'soy sauce':255,'honey':340,'tamarind':260,'lime':244,'lemon':244,
    'rose water':240,'screw pine':240,'tea':240,'coffee':240,'orange juice':248,
    'ghee':210,'butter':225,'condensed milk':306,'evaporated milk':252,
    'double cream':238,'single cream':238,'whipping cream':238,'sour cream':240,
    'cumin seeds':95,'black cumin':100,'coriander seeds':90,'fennel seeds':95,
    'mustard seeds':140,'fenugreek seeds':150,'nigella seeds':115,
    "bishop's weed":95,'poppy seeds':145,'sesame seeds':144,
    'cloves':100,'cardamom, green':95,'cardamom, black':95,
    'cinnamon':100,'bay leaf':18,'star anise':80,
    'turmeric':130,'ground cumin':100,'ground coriander':85,'cayenne':105,
    'red chile powder':115,'paprika':108,'black pepper':135,'ground black pepper':108,
    'nutmeg':110,'mace':70,'ground mace':70,'ground cinnamon':125,'ground cloves':107,
    'ground cardamom':100,'ground mustard':85,'ground fennel':95,'ground fenugreek':110,
    'ground ginger':95,
    'asafetida':150,'mango powder':115,'dried pomegranate seeds':110,
    'garam masala':95,'sambhar masala':95,'kokum':80,'chaat masala':100,
    'salt':292,'black salt':300,'sugar':200,'jaggery':210,'palm sugar':210,
    'brown sugar':213,'icing sugar':125,'caster sugar':200,
    'baking powder':230,'baking soda':230,'yeast':5,
    'all-purpose flour':125,'whole-wheat flour':120,'rice flour':125,
    'chickpea flour':92,'cornstarch':128,'cornmeal':156,'millet flour':110,
    'sorghum flour':130,'semolina':165,'bread flour':125,
    'basmati rice':190,'rice':195,'brown rice':190,'red rice':190,'cracked wheat':150,
    'couscous':173,'quinoa':170,'oats':81,
    'chickpeas':200,'black chickpeas':205,'green chickpeas':165,
    'red kidney beans':190,'black-eyed peas':170,
    'mung beans, whole':205,'split mung beans, skinned':210,
    'urad dal, skinned split':208,'urad dal, whole':205,'chana dal':208,
    'masoor dal, split':195,'masoor, whole':195,
    'toovar dal':200,'toovar, whole':200,'moth beans':200,'horse gram':205,
    'yellow peas, whole':190,
    'cashews':130,'almonds':143,'pistachios':125,'peanuts':145,
    'walnuts':100,'pine nuts':135,'pecans':100,'hazelnuts':135,
    'coconut, fresh':80,'coconut, dried':93,'coconut, whole':80,'coconut cream':238,
    'cilantro':16,'mint':10,'dill':9,'basil':24,'holy basil':22,
    'gongura':22,'curry leaves':14,'fenugreek leaves':28,'mustard greens':25,
    'parsley':16,'chives':4,
    'onion':160,'shallot':160,'garlic':136,'ginger':96,
    'green chile':100,'dried red chile':35,'scallions':100,'lemongrass':70,
    'garlic paste':240,'ginger paste':240,'garlic-ginger paste':240,
    'onion-tomato masala':240,'makhani sauce':240,
    'tomato':180,'potato':150,'sweet potato':133,'cauliflower':100,
    'cabbage':89,'spinach':30,'eggplant':82,'okra':100,'green peas':145,
    'green beans':110,'carrot':128,'bell pepper':149,'cucumber':119,
    'mushroom':70,'bitter melon':93,'bottle gourd':116,'ridge gourd':93,
    'ivy gourd':100,'taro root':132,'taro leaves':38,
    'pumpkin':116,'white pumpkin':100,'lotus root':95,'yams':136,
    'plantain':150,'radish':116,'turnip':130,'kohlrabi':135,'beets':136,
    'broccoli':91,'amaranth leaves':28,'drumstick':60,'corn':145,
    'celery':100,'fennel bulb':87,'asparagus':134,'leek':89,
    'apples':125,'banana':150,'cherries':155,'raisins':145,'dates':147,
    'apricots':155,'guava':165,'watermelon':152,'mango':165,
    'mango, unripe':165,'mango, ripe':165,'pineapple':165,'pomegranate seeds':174,
    'strawberries':152,'blueberries':148,'orange':180,
    'paneer':240,'whole-milk cheese':113,'khoya':260,'cream cheese':232,
    'cheddar':113,'mozzarella':113,'feta':150,'ricotta':246,
    'chicken':140,'lamb':140,'beef':150,'pork':150,'pork sausage':150,
    'veal':140,'turkey':140,'cornish game hen':140,'duck':150,'bacon':140,
    'shrimp':145,'lobster':140,'crab':140,'scallops':140,'mussels':140,
    'salmon':140,'tuna':140,'tilapia':140,'catfish':140,'cod':140,
    'halibut':140,'mackerel':140,'red snapper':140,'carp':140,'sole':140,
    'fish':140,'eggs':243,'saffron':530,
    'gin':240,'vodka':240,'rum':240,'whisky':240,'whiskey':240,
    'wine':240,'beer':240,'champagne':240,'vermouth':240,'bitters':240,
    'simple syrup':320,'maple syrup':322,'agave syrup':332,
    'tonic water':240,'soda water':240,'ginger ale':240,
}

PIECE_WEIGHT = {
    'garlic':5,
    'green chile':5,
    'dried red chile':1,
    'cloves':0.07,
    'cardamom, green':0.3,
    'cardamom, black':0.7,
    'bay leaf':0.1,
    'curry leaves':0.05,
    'star anise':2.0,
    'cinnamon':2.5,
    'lime':50,
    'lemon':60,
    'eggs':50,
    'onion':110,
    'shallot':30,
    'tomato':123,
    'potato':150,
    'paneer':240,
    'banana':118,
    'plantain':180,
    'mango':200,'mango, unripe':200,'mango, ripe':200,
    'cucumber':300,
    'eggplant':82,
    'bell pepper':119,
    'cauliflower':600,
    'carrot':61,
    'chicken':1400,
    'fish':500,
    'papads':5,
    'lentil wafers':5,
    'lemongrass':17,
    'screw pine':5,
    'scallions':15,
    'orange':131,
    'apples':182,
}

DEFAULT_DENSITY_LIQUID = 240
DEFAULT_DENSITY_SOLID = 150

def grams_for(canonical, amount, unit_phrase, line_text):
    if amount is None:
        return None, unit_phrase, False, 'no_amount'
    u = (unit_phrase or '').lower().strip()
    u = re.sub(r'^of\s+', '', u)
    for k, factor in sorted(G_OF.items(), key=lambda x:-len(x[0])):
        if u.startswith(k):
            return amount * factor, k, True, 'mass'
    for k, ml_per in sorted(ML_OF.items(), key=lambda x:-len(x[0])):
        if u.startswith(k):
            density = DENSITY_G_PER_CUP.get(canonical)
            if density is None:
                liquidish = any(w in canonical for w in
                                ('oil','milk','water','juice','vinegar','sauce','paste','cream','yogurt','syrup','stock','broth','drizzle'))
                density = DEFAULT_DENSITY_LIQUID if liquidish else DEFAULT_DENSITY_SOLID
                src = 'volume_default'
            else:
                src = 'volume_known'
            ml = amount * ml_per
            return ml * density / 240.0, k, True, src
    if u in COUNT_UNITS or u == '':
        per = PIECE_WEIGHT.get(canonical)
        if per is not None:
            return amount * per, u or 'piece', True, 'piece_known'
        return None, u, False, 'count_unknown'
    return None, unit_phrase, False, 'unrecognized_unit'

# =================================================================
# Canonicalization
# =================================================================
STOPWORDS = set('''a an the of and or to with for in on at by from as into
freshly finely thinly coarsely roughly lightly very
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
good-quality quality flaky fine coarse
'''.split())

SYNONYMS = {
    'asafetida': ['hing','asafoetida'],
    'cumin seeds': ['cumin seed','cumin','jeera','zeera','safed zeera','whole cumin'],
    'ground cumin': ['cumin powder','powdered cumin','ground roasted cumin','roasted ground cumin','roasted cumin powder'],
    'black cumin': ['shahi zeera','shahi jeera','royal cumin','black cumin seeds'],
    'coriander seeds':['coriander seed','sabud dhania','whole coriander'],
    'ground coriander':['coriander powder','coriander, ground','roasted ground coriander'],
    'cilantro':['fresh coriander','coriander leaves','taaza dhania','dhania','cilantro leaves','coriander leaf','coriander','coriander stalks','coriander stems','coriander sprigs','coriander leaves and stems','coriander stalks and leaves','coriander leaves, picked'],
    'turmeric':['ground turmeric','turmeric powder','haldi','manjal','ground tumeric','tumeric'],
    'cardamom, green':['green cardamom','cardamom pods','green cardamom pods','elaichi','cardamom seeds','cardamom seed','whole green cardamom','whole cardamom pods','cardamom','cardamom seeds from green or white pods','cardamom seeds from green pods'],
    'ground cardamom':['cardamom powder','ground green cardamom','ground cardamom seeds','powdered cardamom','cardamom seeds from green or white pods, ground','cardamom seeds, ground','cardamom seeds ground'],
    'cardamom, black':['black cardamom','black cardamom pods','black cardamom pod','badi elaichi','whole black cardamom','cardamom seeds from black pods','cardamom seeds from black pods, ground','cardamom from black pods','seeds from black cardamom pods','seeds from black cardamom pods, ground','seeds from 2 black cardamom pods','seeds from 2 black cardamom pods, ground'],
    'cinnamon':['cinnamon stick','cinnamon sticks','dalchini','cassia','whole cinnamon','cassia bark'],
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
    "bishop's weed":['ajwain','ajowan','carom seeds','ajwan','carom','bishop’s weed','ajwain seeds',"bishop's weed or dried thyme"],
    'black pepper':['black peppercorns','peppercorns','kali mirchi','whole black peppercorns','whole peppercorns','pepper'],
    'ground black pepper':['black pepper, ground','freshly ground black pepper','freshly ground pepper','pepper, ground','ground pepper','ground peppercorns','freshly cracked black pepper'],
    'cayenne':['cayenne pepper','ground cayenne','cayenne (ground red pepper)'],
    'red chile powder':['ground red chile','red chili powder','kashmiri chile powder','ground deggi chiles','deggi mirch','deggi chile powder','ground kashmiri chiles','kashmiri chilli powder','kashmiri red chilli powder','degi mirch','red chilli powder','chilli powder'],
    'paprika':['sweet paprika','hungarian paprika','smoked paprika'],
    'nutmeg':['ground nutmeg','grated nutmeg','jaiphal'],
    'mace':['jaipatri','blade mace','mace blades','blades of mace','whole mace'],
    'ground mace':['mace, ground','mace powder','powdered mace'],
    'saffron':['saffron threads','zaffran','kesar','zarda','saffron strands'],
    'poppy seeds':['poppy seed','khus-khus','khus khus','white poppy seeds'],
    'sesame seeds':['sesame seed','til','white sesame seeds','toasted sesame seeds'],
    'star anise':['star anise pods','badiyan'],
    'mango powder':['amchur','amchoor','dried mango powder'],
    'dried pomegranate seeds':['anardana','pomegranate seeds, dried'],
    'tamarind':['tamarind paste','tamarind pulp','tamarind concentrate','imli','tamarind extract','tamarind water','tamarind juice'],
    'kokum':['kokum petals','dried kokum'],
    'kudampuli':['goraka','fish tamarind'],
    'curry leaves':['curry leaf','kadipatta','kari patta','fresh curry leaves'],
    'kaffir lime leaves':['kaffir lime leaf','makrut lime leaves'],
    'rose water':['rosewater','rose essence','gulab jal'],
    'dried rose petals':['rose petals','crumbled rose petals','dried rose petals, crumbled'],
    'rose syrup':['rose cordial'],
    'screw pine':['kewra water','kewra','pandan'],
    'black salt':['kala namak'],
    'salt':['table salt','kosher salt','sea salt','iodized salt','coarse salt','coarse kosher or sea salt','coarse kosher salt','coarse sea salt','fine sea salt','flaky sea salt','sea salt flakes','maldon salt'],
    'sugar':['granulated sugar','white sugar','chini','caster sugar','golden caster sugar','demerara sugar','soft brown sugar'],
    'jaggery':['gur','palm jaggery','jaggery powder','grated jaggery'],
    'garlic':['garlic clove','garlic cloves','minced garlic','grated garlic','lasoon','lasson','crushed garlic','garlic bulb','garlic bulbs','garlic head','garlic heads'],
    'ginger':['fresh ginger','ginger root','ginger, fresh','adrak','grated ginger','minced ginger','gingerroot','fresh ginger root','fresh root ginger','root ginger'],
    'ground ginger':['dried ginger','dry ginger','ginger powder','sonth','sunthi','dried ground ginger','powdered ginger'],
    'onion':['onions','red onion','yellow onion','sliced onion','chopped onion','pyaaz','kaanda','vengayam','brown onion','white onion','spanish onion'],
    'shallot':['shallots','pearl onions','chinnay vengayam','banana shallots'],
    'scallions':['scallion','green onions','spring onion','spring onions'],
    'green chile':['green chiles','fresh green chile','green chilies','hara mirch','serrano chile','serrano','jalapeno','jalapeño','thai chile','thai chiles','thai bird chile','green chilli','green chillies','bird chillies','birdseye chillies','finger chillies','red chilli','fresh red chilli','fresh red chillies','red chillies','green chillies, deseeded'],
    'dried red chile':['dried red chiles','dried red chili','dried red chillies','red chile','red chiles','dried chiles','dried chile','lal mirch','byadagi','kashmiri chile','kashmiri chiles','dried red thai or cayenne chile','dried red thai or cayenne chiles','dried red thai chile','dried red thai chiles','whole dried red chillies','kashmiri dried red chillies','dried chilli flakes','dried red chilli flakes','red chilli flakes','chilli flakes','crushed red chillies','crushed red chilli','dried guajillo chiles','dried red kashmiri or guajillo chiles','guajillo chiles'],
    'mint':['fresh mint','mint leaves','pudhina','pudina','mint, fresh','mint sprigs'],
    'dill':['fresh dill','dill leaves','suva','dill weed'],
    'basil':['basil leaves','fresh basil'],
    'holy basil':['tulsi'],
    'gongura':['gongura leaves','sorrel leaves'],
    'tomato':['tomatoes','plum tomato','plum tomatoes','roma tomato','roma tomatoes','tamatar','thakkali','crushed tomato','canned tomato','canned tomatoes','tomato puree','vine tomatoes','vine-ripened tomatoes','cherry tomatoes','tinned tomatoes','tinned plum tomatoes','chopped tomatoes'],
    'tomato paste':['tomato purée','tomato pulp'],
    'tomato ketchup':['ketchup'],
    'potato':['potatoes','aloo','batata','urulikazhangu','red potato','red potatoes','yukon gold','new potatoes','baby potatoes','maris piper','desiree','king edward','floury potatoes','waxy potatoes'],
    'sweet potato':['sweet potatoes','rataloo','yam'],
    'cauliflower':['cauliflower florets','phool gobhi','gobhi florets'],
    'cabbage':['green cabbage','shredded cabbage','bund gobhi','muttaikose','white cabbage','red cabbage'],
    'spinach':['fresh spinach','baby spinach','spinach leaves','palak','keerai'],
    'eggplant':['eggplants','baby eggplant','baingan','japanese eggplant','asian eggplant','aubergine','aubergines','baby aubergine'],
    'okra':['okra pods','bhindi','vendakkai',"lady's fingers","ladies fingers"],
    'green peas':['frozen peas','fresh peas','mutter','matar','green peas, frozen','sweet peas','english peas','garden peas','petits pois'],
    'green beans':['string beans','french beans','farasvi','fine beans','runner beans'],
    'carrot':['carrots','gajar'],
    'bell pepper':['bell peppers','red bell pepper','green bell pepper','yellow bell pepper','simla mirch','capsicum','red pepper','green pepper','yellow pepper','red peppers','green peppers'],
    'cucumber':['cucumbers','kakadi'],
    'mushroom':['mushrooms','white mushrooms','button mushrooms','cremini','dhingri','chestnut mushrooms','portobello mushrooms','field mushrooms'],
    'bitter melon':['bitter gourd','karela'],
    'bottle gourd':['lauki','dudhi','opo squash','bottle gourd squash'],
    'ridge gourd':['luffa','toori','peerkangai','ridged luffa','luffa squash','ridged luffa squash'],
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
    'broccoli':['broccoli florets','tenderstem broccoli'],
    'amaranth leaves':['red amaranth','chinese spinach','red spinach','amaranth'],
    'drumstick':['drumsticks','moringa pods','sahjan'],
    'mustard greens':['sarson'],
    'corn':['fresh corn','corn kernels','makkai','sweet corn','sweetcorn'],
    'celery':['celery stalks','celery sticks','celery ribs'],
    'fennel bulb':['fennel'],
    'asparagus':['asparagus spears'],
    'leek':['leeks'],
    'lemongrass':['fresh lemongrass','lemongrass stalk'],
    'lime':['fresh lime','lime juice','limes','nimbu','key lime','juice of a lime','juice of 1 lime'],
    'lemon':['lemons','lemon juice','fresh lemon','juice of a lemon','juice of 1 lemon'],
    'mango, unripe':['unripe mango','green mango','raw mango','khatte aam','kacchi keri','mango (unripe)','green unripe papaya'],
    'mango, ripe':['ripe mango','alphonso mango','alphonso mangoes'],
    'mango':['mangoes'],
    'pineapple':['fresh pineapple','anaras','anasi'],
    'pomegranate seeds':['pomegranate arils','fresh pomegranate','seeds from 1 small to medium-size ripe pomegranate','seeds from 1 pomegranate','fresh pomegranate seeds','pomegranate seeds separated from the flesh','fresh pomegranate, seeds separated from the flesh'],
    'sabudana':['tapioca pearls','sago','sago pearls','uncooked medium-size white tapioca pearls','white tapioca pearls'],
    'raspberries':['raspberry','fresh raspberries','raspberry purée','raspberry puree','frozen raspberries','berries','mixed berries','dried fruit berries'],
    'kale':['kale leaves','curly kale','cavolo nero'],
    'cocoa powder':['cocoa','unsweetened cocoa powder','dusting of cocoa powder'],
    'vanilla':['vanilla extract','pure vanilla extract','vanilla essence','vanilla bean','vanilla pod','vanilla seeds','vanilla pod or 2 tsp vanilla extract','vanilla pod or 3 tsp vanilla extract'],
    'veal':['boneless veal','veal shoulder'],
    'mangetout':['snow peas','sugar snap peas'],
    'pomfret':['pomfrets','silver pomfret','frozen whole pomfrets','pomfret fillets'],
    'beef tenderloin':['filets mignons','filet mignon','beef fillet','tenderloin'],
    'parsnip':['parsnips'],
    'absinthe':[],
    'aperol':['aperol apéritif'],
    'tequila':['centenario or other good-quality reposado tequila','reposado tequila','blanco tequila'],
    'prosecco':['cl bottle prosecco, well chilled','75cl bottle prosecco','sparkling prosecco'],
    'orange':['oranges','blood orange','orange juice'],
    'apples':['apple','green apple','bramley apple','granny smith'],
    'banana':['bananas','ripe banana'],
    'cherries':['fresh cherries','dried cherries'],
    'raisins':['golden raisins','kishmish','sultanas','raisin','dark raisins','currants'],
    'dates':['date','medjool dates','pitted dates','medjool date'],
    'apricots':['apricot','dried apricots','jardaloo'],
    'guava':['guavas'],
    'watermelon':['tarbooz'],
    'strawberries':['strawberry','fresh strawberries'],
    'blueberries':['blueberry'],
    'avocado':['hass avocado','hass avocados','avocados','firm hass avocado','ripe avocado'],
    'arugula':['rocket','rocket leaves'],
    'bamboo shoots':['bamboo shoot','canned bamboo shoots'],
    'bean sprouts':['mung bean sprouts','sprouted beans','store-bought bean sprouts'],
    'chives':['fresh chives'],
    'parsley':['fresh parsley','flat-leaf parsley','italian parsley','curly parsley'],
    'jackfruit':['raw jackfruit','canned raw jackfruit','green jackfruit','unripe jackfruit'],
    'flat beans':['flat green beans','italian flat beans'],
    'yard-long beans':['yard long beans','cut-up yard-long beans','long beans','chinese long beans'],
    'puff pastry':['frozen puff pastry','frozen puff pastry, completely thawed','puff pastry sheets','puff pastry, thawed'],
    'wheat berries':['kanak','kanak or wheat berries','whole wheat berries','wheat'],
    'bread buns':['white bread','white hamburger-style buns','white finger-sandwich-style buns','finger sandwich-style buns','white finger-sandwich-style buns, about 3 inches in diameter','white, finger sandwich-style buns','hamburger buns','dinner rolls','bread rolls','paav','pav buns','pao','pav','brioche buns','white bloomer','sourdough','bloomer','soft white roll','soft white rolls','sourdough bread','thick slice of white bloomer or sourdough','slice of white bloomer','slice of sourdough','white bloomer or sourdough','thick slices of white bloomer, sourdough or brioche','white bloomer, sourdough or brioche','slices of bloomer','brioche loaf','brioche'],
    'chickpeas':['garbanzo beans','kabuli chana','canned chickpeas','dried chickpeas','white chickpeas','tinned chickpeas'],
    'black chickpeas':['kala chana','desi chana'],
    'green chickpeas':['hara chana'],
    'chickpea flour':['besan','gram flour','garbanzo flour'],
    'red kidney beans':['kidney beans','rajmah','rajma'],
    'black-eyed peas':['lobhia','black-eyed pea','chowli','cowpeas','red cowpeas','sabud chowli','black eye beans','black-eye beans'],
    'mung beans, whole':['mung beans','whole mung','sabud moong','green gram','moong','whole green lentils','green lentils, whole'],
    'split mung beans, skinned':['moong dal','yellow split mung','skinned split mung','dhuli moong','skinned split green lentils','split green lentils','green lentils, split','yellow moong dal'],
    'urad dal, skinned split':['urad dal','split black gram','skinned split black lentils','dhuli urad','skinned split black lentils, picked over for stones','split black lentils','white urad dal','split urad daal','urad daal','split urad dal','urad daal split'],
    'urad dal, whole':['whole urad','sabud urad','black gram, whole','whole black gram','whole black lentils','black urad dal','whole black urad','whole urad daal','whole black urad daal'],
    'chana dal':['yellow split peas','split bengal gram','chana daal','split yellow peas','split yellow chickpeas','bengal gram, split','split bengal gram lentils'],
    'yellow peas, whole':['safed vatana','dried yellow peas','whole yellow peas'],
    'masoor dal, split':['red lentils','masoor dal','split red lentils','skinned masoor','skinned split brown lentils','split brown lentils','brown lentils, split','salmon-colored brown lentils'],
    'masoor, whole':['whole brown lentils','sabud masoor','brown lentils'],
    'toovar dal':['toor dal','arhar dal','pigeon peas, split','split pigeon peas','tuvar dal','yellow pigeon peas','split yellow pigeon peas','skinned split yellow pigeon peas','oily skinned split yellow pigeon peas','unoily skinned split yellow pigeon peas','toovar lentils','oily or unoily skinned split yellow'],
    'toovar, whole':['whole pigeon peas','sabud toovar','sabud toor','whole yellow pigeon peas'],
    'moth beans':['matki','moth','dew gram'],
    'horse gram':['kulith','kollu'],
    'cashews':['cashew','cashew nuts','caju','raw cashews','ground cashew nuts','cashew nuts, ground','cashews, ground','ground cashews'],
    'almonds':['almond','blanched almonds','slivered almonds','almond, blanched','ground almonds','almonds, ground','flaked almonds'],
    'pistachios':['pistachio','shelled pistachios','shelled pistachio nuts','shelled pistachio','pistachio nuts','unsalted pistachios','pistachio kernels'],
    'peanuts':['peanut','sengdana','mungphalli','raw peanuts','roasted peanuts','salted peanuts'],
    'walnuts':['walnut','walnut halves'],
    'pine nuts':['chilgozae','pinoli'],
    'pecans':['pecan'],
    'hazelnuts':['hazelnut','blanched hazelnuts'],
    'coconut, fresh':['fresh coconut','grated coconut','grated fresh coconut','fresh grated coconut','shredded fresh coconut'],
    'coconut, dried':['dried coconut','dessicated coconut','desiccated coconut','copra','unsweetened shredded coconut','shredded coconut','shredded dried unsweetened coconut','fine desiccated coconut','dried coconut flakes','coconut flakes'],
    'coconut milk':['canned coconut milk','thick coconut milk','thin coconut milk','unsweetened coconut milk','tinned coconut milk','full-fat coconut milk'],
    'coconut, whole':['coconut','nariyal','thenga'],
    'coconut cream':['thick coconut cream'],
    'yogurt':['plain yogurt','greek yogurt','dahi','curd','whole-milk yogurt','natural yogurt','yoghurt','plain yoghurt','greek yoghurt','natural yoghurt','full-fat yoghurt','full-fat yogurt','greek-style yoghurt'],
    'buttermilk':['cultured buttermilk','chaas','more'],
    'milk':['whole milk','full-fat milk','low-fat milk','2% milk','semi-skimmed milk','skimmed milk'],
    'cream':['heavy cream','whipping cream','heavy whipping cream','double cream','single cream','pouring cream'],
    'half-and-half':['half and half'],
    'butter':['unsalted butter','salted butter','butter, unsalted','softened butter'],
    'ghee':['clarified butter','ghee, melted'],
    'paneer':['indian cheese','fresh cheese','paneer cheese','homemade paneer'],
    'khoya':['mawa','milk solids'],
    'whole-milk cheese':['cheese'],
    'cream cheese':['mascarpone'],
    'cheddar':['cheddar cheese','mature cheddar','strong cheddar'],
    'mozzarella':['mozzarella cheese','fresh mozzarella'],
    'feta':['feta cheese'],
    'ricotta':['ricotta cheese'],
    'condensed milk':['sweetened condensed milk'],
    'evaporated milk':['carnation milk'],
    'vegetable oil':['canola oil','sunflower oil','safflower oil','corn oil','neutral oil','oil','peanut oil','vegetable cooking oil','vegetable cooking spray','cooking spray','groundnut oil','rapeseed oil','flavourless oil','tasteless oil'],
    'mustard oil':['kacchi ghani mustard oil'],
    'coconut oil':['virgin coconut oil','extra-virgin coconut oil'],
    'sesame oil':['gingelly oil','toasted sesame oil','til oil'],
    'olive oil':['extra-virgin olive oil','extra virgin olive oil','light olive oil'],
    'basmati rice':['white basmati','aged basmati','basmati','basmati rice (uncooked)','cooked basmati rice'],
    'rice':['long-grain rice','short-grain rice','white rice','plain rice'],
    'brown rice':['brown basmati'],
    'red rice':['rosematta rice','matta rice','kerala red rice'],
    'all-purpose flour':['plain flour','maida','flour','wheat flour','strong white flour','plain white flour'],
    'whole-wheat flour':['atta','chapati flour','whole-meal flour','wholemeal flour','wholewheat flour','wholewheat chapati flour'],
    'rice flour':['ground rice'],
    'cornmeal':['polenta','makkai flour','corn flour'],
    'cornstarch':['cornflour','corn starch'],
    'millet flour':['bajra','bajra flour','pearl millet flour'],
    'sorghum flour':['jowar','jowar flour'],
    'semolina':['sooji','rava','farina','cream of wheat','fine semolina'],
    'couscous':['pearl couscous'],
    'oats':['rolled oats','porridge oats','jumbo oats'],
    'papads':['papadum','papadams','papad','papadums','lentil wafers','uncooked lentil wafers','uncooked lentil wafers, at least 6 inches in diameter','plain lentil wafers'],
    'chicken':['chicken thighs','chicken breast','chicken pieces','whole chicken','bone-in chicken','boneless chicken','skinless chicken','chicken, cut into','murghi','chicken legs','chicken wings','chicken drumsticks','boneless chicken thighs','chicken fillet','chicken fillets'],
    'chicken livers':['chicken liver'],
    'cornish game hen':['cornish hen','game hen','cornish hens'],
    'duck':['duck breast','duck legs'],
    'turkey':['ground turkey','turkey breast'],
    'lamb':['lamb shoulder','lamb leg','boneless lamb','bone-in lamb','lamb stew meat','ground lamb','lamb, cut into','gosht','lamb mince','minced lamb','diced lamb','leg of lamb','lamb chops','lamb shanks','lamb rump','lamb neck'],
    'beef':['beef chuck','ground beef','stew beef','beef stew meat','beef shoulder','beef sirloin','sirloin','flank steak','beef, cut into','minced beef','beef mince','diced beef'],
    'pork':['pork shoulder','pork loin','pork tenderloin','pork butt','pork, cut into','pork stew meat','pork belly','pork ribs','minced pork','diced pork'],
    'pork sausage':['italian sausage','sausage','sausages'],
    'bacon':['streaky bacon','smoked bacon','back bacon','pancetta'],
    'eggs':['egg','hard-boiled eggs','large eggs','egg yolks','egg whites','egg yolk','egg white','medium eggs','free-range eggs','organic eggs','medium free-range eggs','large free-range eggs'],
    'shrimp':['prawns','shrimps','large shrimp','medium shrimp','peeled shrimp','jhinga','chingri','king prawns','tiger prawns','raw prawns'],
    'lobster':['lobster tail','lobster tails','lobster meat'],
    'crab':['crab meat','crab claws','kekada'],
    'scallops':['sea scallops','bay scallops'],
    'mussels':['fresh mussels','mussels in shell'],
    'salmon':['salmon fillet','salmon steaks','salmon fillets'],
    'tuna':['tuna steak','fresh tuna'],
    'tilapia':['tilapia fillets'],
    'catfish':['catfish fillets'],
    'cod':['cod fillets','cod fillet'],
    'halibut':['halibut fillet','halibut steak'],
    'mackerel':['mackerel fillets','bangada'],
    'red snapper':['snapper','snapper fillets'],
    'carp':['carp steaks','rohu','ruhu'],
    'sole':['sole fillet','fillet of sole'],
    'fish':['fish fillets','firm white fish','any firm fish','meen','maach','mucchi','muchee','white fish'],
    'baking powder':['sodium bicarbonate'],
    'baking soda':['bicarbonate of soda','bicarb','sodium bicarbonate'],
    'yeast':['active dry yeast','instant yeast','fast-action yeast','dried yeast','fresh yeast'],
    'water':['warm water','cold water','hot water','tap water','filtered water','boiling water','iced water','ice-cold water','still water','ice cubes','ice','lots of ice cubes','ice cube'],
    'vinegar':['white vinegar','distilled vinegar','sirka','white wine vinegar'],
    'cider vinegar':['apple cider vinegar'],
    'malt vinegar':['british malt vinegar'],
    'rice vinegar':['rice wine vinegar'],
    'feni':['feni vinegar','goan feni'],
    'soy sauce':['light soy sauce','dark soy sauce'],
    'worcestershire sauce':['worcester sauce'],
    'honey':['raw honey','clover honey','runny honey'],
    'tea':['black tea','tea leaves','tea bags','green tea','assam tea','darjeeling tea','english breakfast tea'],
    'coffee':['instant coffee','ground coffee','espresso'],
    'simple syrup':['sugar syrup'],
    'maple syrup':['pure maple syrup'],
    'gin':['london dry gin'],
    'vodka':['plain vodka'],
    'rum':['white rum','dark rum','spiced rum'],
    'whisky':['whiskey','scotch','bourbon'],
    'wine':['red wine','white wine','dry white wine','dry red wine'],
    'beer':['lager','ale','indian pale ale'],
    'champagne':['prosecco','sparkling wine','cava'],
    'vermouth':['dry vermouth','sweet vermouth'],
    'bitters':['angostura bitters'],
    'tonic water':['indian tonic water'],
    'soda water':['club soda','sparkling water'],
    'ginger ale':['ginger beer'],
    'chaat masala':['chaat masala powder'],
    'garam masala':['garam masala powder'],
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

def clean_title(s):
    """Like clean_text but strips tags WITHOUT inserting whitespace, so
    constructs like '<span>O</span>N BIRYANI' yield 'ON BIRYANI' not 'O N BIRYANI'.
    Use this for recipe titles where spans split single words."""
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_ingredient_name(line_text):
    """Strip qty/unit/preps, return (amount, unit, name_core)."""
    name = line_text
    # Normalize curly quotes/apostrophes to straight so aliases match
    # (e.g. "bishop's weed" alias vs "bishop’s weed" in the source).
    name = name.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    # Strip leading "A pinch of", "A few", "A handful of" patterns
    name = re.sub(r'^a\s+(pinch|few|handful|small handful|large handful|generous pinch|tiny pinch|good pinch|knob|generous knob|drizzle|splash|dash|squeeze|sprinkle|spoonful|good\s+\S+)\s+of\s+', '', name, flags=re.I)
    name = re.sub(r'^a\s+(pinch|few|handful|knob|drizzle|splash|dash|squeeze|sprinkle|spoonful)\s+', '', name, flags=re.I)
    # Strip leading "1 recipe X" or "1 quantity X" pattern (660-style sub-recipe ref)
    name = re.sub(r'^(\d+(?:\.\d+)?)\s+(?:recipe|quantity)\s+', r'\1 ', name, flags=re.I)
    # Strip leading "about/approximately/roughly" qualifiers before an amount
    name = re.sub(r'^(about|approximately|approx\.?|roughly|around|nearly|almost)\s+(?=\d|[¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚])', '', name, flags=re.I)
    # Strip leading approximations like "scant", "generous" before a number or unit
    name = re.sub(r'^(scant|generous|heaped|heaping|good|big)\s+(?=\d|[¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚]|tsp|tbsp|tablespoon|teaspoon|cup|pinch|handful)', '', name, flags=re.I)
    name = re.sub(r'^(tin|packet|jar|bottle|can)\s+(?:of\s+)?', '', name, flags=re.I)
    amount, idx = parse_amount(name)
    rest = name[idx:].strip() if amount is not None else name
    unit = ''
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
            m2 = re.match(r'^(ounces?|oz)\b', rest)
            if cand in {'fluid','fl'} and m2:
                rest = rest[m2.end():].strip()
    rest = re.sub(r'^(of\s+|to\s+)+', '', rest)
    rest = re.sub(r'^(?:(?:boneless|bone-in|skin-on|skin-removed|skinless|deboned)\s*,\s*)+', '', rest, flags=re.I)
    rest = re.sub(r'^(?:wild|raw|live)\s+', '', rest, flags=re.I)
    rest_no_paren = re.sub(r'\([^)]*\)', '', rest).strip()
    rest_no_paren = re.sub(r'\s+([,;.])', r'\1', rest_no_paren)
    rest_no_paren = re.sub(r'\s{2,}', ' ', rest_no_paren)
    # Allow up to 2 adverbs before a prep verb ("very finely chopped", "roughly torn", "plus an extra X")
    split_re = r'(?:;|,\s*(?:(?:finely|coarsely|roughly|thinly|lightly|freshly|partially|fully|very)\s+){0,2}(?:chopped|sliced|diced|minced|grated|crushed|halved|quartered|peeled|cored|seeded|deseeded|stemmed|trimmed|cubed|shredded|julienned|cut|broken|torn|beaten|whisked|whipped|toasted|roasted|softened|melted|drained|rinsed|smashed|bruised|crumbled|squeezed|squashed|optional|divided|to taste|to finish|to garnish|to serve|to top|or more|or to taste|plus (?:more|extra|an extra|a little|a few)|preferably|picked over|picked|washed|soaked|skinned|deveined|deboned|boneless|skin-on|warmed|reconstituted|stems? removed|seeds? removed|stalks? removed|ends trimmed|see (?:note|notes|tip|step|recipe|above|below)|tail-on|made (?:from|of|with)|ground to a paste|at least|about|each|approximately|approx\.?|page\b|recipe\b|for [a-z\- ]+))'
    rest_clean = re.split(split_re, rest_no_paren, maxsplit=1)[0]
    rest_clean = re.sub(r'\s+(?:to taste|as needed|or to taste|optional|divided|for garnish|for serving|for tempering|for frying|for deep-frying|for pan-frying|for greasing|for dusting|for kneading|for brushing|for sprinkling|for grilling|for spreading|at room temperature|room temperature).*$', '', rest_clean, flags=re.I)
    rest_clean = re.sub(r',\s*(?:plus (?:more|extra|an extra|a few)|well rinsed|rinsed and drained|tough stems? discarded|tough ends? discarded|stem removed|stems? removed|seeds? removed|stalks? removed|ends trimmed|soaked\b|at room temperature|partially thawed|thawed|see (?:note|notes|tip|step|recipe|above|below)\b|to (?:finish|garnish|serve|top)|ground to a paste).*$', '', rest_clean, flags=re.I)
    rest_clean = re.sub(r'\s+for\s+(?:pan-frying|deep-frying|frying|tempering|garnish|garnishing|serving|brushing|kneading|dusting|sprinkling|grilling|spreading).*$', '', rest_clean, flags=re.I)
    tokens = rest_clean.split()
    while tokens and tokens[0].lower() in STOPWORDS:
        tokens.pop(0)
    name_core = ' '.join(tokens).strip(' ,.;:').lower()
    name_core = re.sub(r'\s+', ' ', name_core)
    return amount, unit, name_core

def canonicalize(name_core, subrecipe_titles):
    if not name_core:
        return None
    n = name_core.strip()
    if n in subrecipe_titles:
        return n
    if n in ALIAS_TO_CANON:
        return ALIAS_TO_CANON[n]
    n2 = re.sub(r'^(red|green|yellow|black|white|brown|orange|small|medium|large|fresh|dried|whole|skinless|boneless)\s+', '', n)
    if n2 in ALIAS_TO_CANON: return ALIAS_TO_CANON[n2]
    parts = n.split()
    for k in (3, 2, 1):
        if len(parts) >= k:
            tail = ' '.join(parts[-k:])
            if tail in ALIAS_TO_CANON: return ALIAS_TO_CANON[tail]
            head = ' '.join(parts[:k])
            if head in subrecipe_titles: return head
    for canon in sorted(CANONICAL_INGREDIENTS, key=lambda c: (-len(c), c)):
        if canon in n:
            return canon
    return n

def cup_equivalent(amount, unit):
    """Express (amount,unit) in cups for sub-recipe scaling."""
    if amount is None: return None
    u = (unit or '').lower()
    if u in ('cup','cups'): return amount
    if u in ('tablespoon','tablespoons','tbsp','tbsps','tbs'): return amount / 16
    if u in ('teaspoon','teaspoons','tsp','tsps'): return amount / 48
    if u in ('pint','pints'): return amount * 2
    if u in ('quart','quarts'): return amount * 4
    if u in ('ml','millilitre','millilitres','milliliter','milliliters'): return amount / 240
    if u in ('l','litre','litres','liter','liters'): return amount * 1000 / 240
    if u in ('g','gram','grams'): return amount / 240   # rough; assumes ~1g/ml
    if u in ('kg','kilogram','kilograms'): return amount * 1000 / 240
    return None

# =================================================================
# Roles, pantry staples, heat sensitivity priors
# =================================================================
ROLE_PRIORS = {
    'tempering': {'cumin seeds','mustard seeds','fenugreek seeds','nigella seeds','fennel seeds',
                  'asafetida','curry leaves','dried red chile','bay leaf','cloves','cinnamon',
                  'cardamom, green','cardamom, black','star anise',"bishop's weed",
                  'black pepper','mace'},
    'base_aromatic': {'onion','shallot','garlic','ginger','green chile','tomato','scallions',
                      'ghee','vegetable oil','mustard oil','coconut oil','sesame oil','butter','olive oil',
                      'garlic paste','ginger paste','garlic-ginger paste','onion-tomato masala'},
    'ground_spice': {'turmeric','ground cumin','ground coriander','cayenne','red chile powder',
                     'paprika','ground black pepper','garam masala','mango powder','nutmeg',
                     'ground mace','ground cinnamon','ground cloves','ground cardamom',
                     'ground mustard','ground fennel','ground fenugreek','ground ginger',
                     'dried pomegranate seeds','black salt','salt','sugar','chaat masala'},
    'finishing': {'cilantro','mint','dill','basil','holy basil','lime','lemon','yogurt',
                  'cream','rose water','screw pine','saffron','black salt','ghee'},
}
ROLE_OF = defaultdict(list)
for role, items in ROLE_PRIORS.items():
    for it in items:
        ROLE_OF[it].append(role)

PANTRY_STAPLES = {
    'ghee', 'whole-milk cheese', 'creamy homemade cheese', 'thick yogurt',
    'paneer', 'butter',
}

HEAT_SENSITIVITY_PRIORS = {
    'cilantro':0.95,'mint':0.95,'dill':0.9,'basil':0.9,'holy basil':0.9,
    'curry leaves':0.4,'fenugreek leaves':0.6,'kaffir lime leaves':0.5,
    'lime':0.95,'lemon':0.95,'yogurt':0.8,'buttermilk':0.85,'cream':0.7,
    'rose water':1.0,'screw pine':1.0,'saffron':0.6,'garam masala':0.7,
    'mango powder':0.5,'black salt':0.5,'chaat masala':0.7,
    'cumin seeds':0.1,'mustard seeds':0.1,'fenugreek seeds':0.1,'nigella seeds':0.1,
    'asafetida':0.15,'cloves':0.15,'cinnamon':0.15,'cardamom, green':0.2,
    'cardamom, black':0.2,'star anise':0.15,'bay leaf':0.2,
    'turmeric':0.25,'cayenne':0.3,'paprika':0.3,'ground coriander':0.3,'ground cumin':0.3,
    'onion':0.1,'garlic':0.1,'ginger':0.15,'tomato':0.2,'green chile':0.25,
    'salt':0.4,'sugar':0.5,'ghee':0.5,
}

# =================================================================
# SQLite schema (multi-book)
# =================================================================
SCHEMA = '''
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS recipe_ingredient;
DROP TABLE IF EXISTS ingredient_role;
DROP TABLE IF EXISTS ingredient_alias;
DROP TABLE IF EXISTS ingredient;
DROP TABLE IF EXISTS recipe;
DROP TABLE IF EXISTS book;
DROP VIEW IF EXISTS v_ingredient_global_freq;
DROP VIEW IF EXISTS v_ingredient_category_usage;
DROP VIEW IF EXISTS v_ingredient_book_freq;

CREATE TABLE book (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  slug        TEXT UNIQUE NOT NULL,
  title       TEXT NOT NULL,
  author      TEXT,
  source_path TEXT,
  notes       TEXT
);

CREATE TABLE recipe (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id         INTEGER NOT NULL REFERENCES book(id),
  external_id     TEXT,
  title           TEXT NOT NULL,
  category        TEXT NOT NULL,
  category_label  TEXT NOT NULL,
  chapter_file    TEXT NOT NULL,
  region          TEXT,
  is_subrecipe    INTEGER NOT NULL DEFAULT 0,
  yield_amount    REAL,
  yield_unit      TEXT,
  yield_keyword   TEXT,
  num_direct_ingredients INTEGER NOT NULL DEFAULT 0,
  UNIQUE (book_id, external_id)
);
CREATE INDEX idx_recipe_category ON recipe(category);
CREATE INDEX idx_recipe_book ON recipe(book_id);
CREATE INDEX idx_recipe_subrecipe ON recipe(is_subrecipe);

CREATE TABLE ingredient (
  canonical            TEXT PRIMARY KEY,
  is_subrecipe         INTEGER NOT NULL DEFAULT 0,
  is_pantry_staple     INTEGER NOT NULL DEFAULT 0,
  subrecipe_recipe_id  INTEGER REFERENCES recipe(id),
  recipe_count_direct  INTEGER NOT NULL DEFAULT 0,
  recipe_count_expanded INTEGER NOT NULL DEFAULT 0,
  category_count       INTEGER NOT NULL DEFAULT 0,
  book_count           INTEGER NOT NULL DEFAULT 0,
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
SELECT ri.canonical, r.category, ri.source,
       COUNT(DISTINCT ri.recipe_id) AS n_recipes,
       (SELECT COUNT(*) FROM recipe r2 WHERE r2.category = r.category) AS total_in_category
FROM   recipe_ingredient ri
JOIN   recipe r ON r.id = ri.recipe_id
GROUP  BY ri.canonical, r.category, ri.source;

CREATE VIEW v_ingredient_book_freq AS
SELECT ri.canonical, b.slug AS book_slug, b.title AS book_title,
       COUNT(DISTINCT ri.recipe_id) AS n_recipes
FROM   recipe_ingredient ri
JOIN   recipe r ON r.id = ri.recipe_id
JOIN   book   b ON b.id = r.book_id
GROUP  BY ri.canonical, b.id;
'''

def init_db(path=DB_PATH):
    """Drop and recreate the DB; return the open connection."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    return con

def populate_book(con, book_meta, recipes):
    """Insert one book and all its recipes/ingredients/expansions.

    book_meta: dict with keys slug, title, author (optional), source_path, notes (optional)
    recipes:   list of recipe dicts produced by the book-specific parser.
               Each must have:
                 title, category, category_label, chapter_file,
                 region (or None), rec_id (or None — local-to-book external id),
                 serves_amount, serves_unit, serves_keyword,
                 is_subrecipe (bool),
                 ingredients   (list of resolved-ingredient dicts: canonical, raw,
                                amount, unit, grams_est, normalized, gram_source,
                                is_subrecipe_ref, via_rec_id)
                 expanded_ingredients (same shape, plus scale_known/scale_factor/expansion_depth)
    """
    cur = con.cursor()
    cur.execute('INSERT INTO book (slug,title,author,source_path,notes) VALUES (?,?,?,?,?)',
                (book_meta['slug'], book_meta['title'],
                 book_meta.get('author'), book_meta.get('source_path'),
                 book_meta.get('notes')))
    book_id = cur.lastrowid

    # Pass 1: insert recipes
    rec_id_to_db = {}
    for r in recipes:
        cur.execute('''INSERT INTO recipe
                       (book_id,external_id,title,category,category_label,chapter_file,region,
                        is_subrecipe,yield_amount,yield_unit,yield_keyword,num_direct_ingredients)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (book_id, r.get('rec_id'), r['title'], r['category'], r['category_label'],
                     r['chapter_file'], r.get('region'), int(r['is_subrecipe']),
                     r.get('serves_amount'), r.get('serves_unit'), r.get('serves_keyword'),
                     len(r.get('ingredients', []))))
        r['db_id'] = cur.lastrowid
        if r.get('rec_id'):
            rec_id_to_db[r['rec_id']] = r['db_id']

    # Pass 2: ensure ingredient rows exist for every canonical we use
    canon_to_subrecipe_db_id = {}
    for r in recipes:
        if r['is_subrecipe']:
            canon_to_subrecipe_db_id[r['title'].lower()] = r['db_id']
    # Also: any canonical referenced via a cross-ref (via_rec_id) is a
    # sub-recipe by that name, even if the name differs from the source
    # recipe's title (e.g. Dishoom's "garlic paste" → "Garlic & Ginger Pastes" recipe).
    for r in recipes:
        for ing in r.get('ingredients', []):
            if ing.get('is_subrecipe_ref') and ing.get('via_rec_id'):
                target_db_id = rec_id_to_db.get(ing['via_rec_id'])
                if target_db_id and ing['canonical'] not in canon_to_subrecipe_db_id:
                    canon_to_subrecipe_db_id[ing['canonical']] = target_db_id
    all_canons_in_book = set()
    for r in recipes:
        for ing in r.get('ingredients', []) + r.get('expanded_ingredients', []):
            all_canons_in_book.add(ing['canonical'])
    for canon in all_canons_in_book:
        is_sub = canon in canon_to_subrecipe_db_id
        cur.execute('''INSERT OR IGNORE INTO ingredient
                       (canonical,is_subrecipe,is_pantry_staple,subrecipe_recipe_id,
                        heat_sensitivity,density_g_per_cup,piece_weight_g)
                       VALUES (?,?,?,?,?,?,?)''',
                    (canon, int(is_sub), int(canon in PANTRY_STAPLES),
                     canon_to_subrecipe_db_id.get(canon),
                     HEAT_SENSITIVITY_PRIORS.get(canon),
                     DENSITY_G_PER_CUP.get(canon),
                     PIECE_WEIGHT.get(canon)))
        # If a later book contributes a sub-recipe for an existing canonical, update.
        if is_sub:
            cur.execute('''UPDATE ingredient SET is_subrecipe=1,
                                                 subrecipe_recipe_id=COALESCE(subrecipe_recipe_id,?)
                           WHERE canonical=?''',
                        (canon_to_subrecipe_db_id[canon], canon))

    # Pass 3: aliases — insert any we don't yet have
    for alias, canon in ALIAS_TO_CANON.items():
        if canon in all_canons_in_book:
            cur.execute('INSERT OR IGNORE INTO ingredient_alias (alias,canonical) VALUES (?,?)',
                        (alias, canon))

    # Pass 4: roles
    for canon in all_canons_in_book:
        for role in ROLE_OF.get(canon, []):
            cur.execute('INSERT OR IGNORE INTO ingredient_role (canonical,role) VALUES (?,?)',
                        (canon, role))

    # Pass 5: recipe_ingredient rows
    def via_db_id(rec_id):
        return rec_id_to_db.get(rec_id)
    for r in recipes:
        for ing in r.get('ingredients', []):
            cur.execute('''INSERT INTO recipe_ingredient
                           (recipe_id,canonical,raw_line,amount,unit,grams_est,normalized,
                            gram_source,source,via_recipe_id,scale_factor,scale_known,expansion_depth)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (r['db_id'], ing['canonical'], ing['raw'], ing.get('amount'), ing.get('unit'),
                         ing.get('grams_est'), int(ing.get('normalized', False)), ing.get('gram_source'),
                         'direct',
                         via_db_id(ing.get('via_rec_id')),
                         None, None, None))
        for ing in r.get('expanded_ingredients', []):
            cur.execute('''INSERT INTO recipe_ingredient
                           (recipe_id,canonical,raw_line,amount,unit,grams_est,normalized,
                            gram_source,source,via_recipe_id,scale_factor,scale_known,expansion_depth)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (r['db_id'], ing['canonical'], ing['raw'], ing.get('amount'), ing.get('unit'),
                         ing.get('grams_est'), int(ing.get('normalized', False)), ing.get('gram_source'),
                         'expanded',
                         via_db_id(ing.get('via_rec_id')),
                         ing.get('scale_factor'),
                         int(bool(ing.get('scale_known'))),
                         ing.get('expansion_depth')))
    con.commit()
    return book_id

def finalize_counts(con):
    """Run after all books are populated: backfill aggregate counts on ingredient."""
    cur = con.cursor()
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
                     WHERE ri.canonical = ingredient.canonical), 0),
                   book_count = COALESCE((
                     SELECT COUNT(DISTINCT r.book_id)
                     FROM recipe_ingredient ri JOIN recipe r ON r.id = ri.recipe_id
                     WHERE ri.canonical = ingredient.canonical), 0)''')
    cur.execute('SELECT COUNT(DISTINCT category) FROM recipe')
    n_cats = cur.fetchone()[0] or 1
    cur.execute('SELECT canonical, recipe_count_expanded, category_count FROM ingredient')
    for canon, n_rec, n_cat in cur.fetchall():
        vs = round((n_cat / n_cats) * math.log(1 + n_rec), 3) if n_rec else 0
        cur.execute('UPDATE ingredient SET versatility_score = ? WHERE canonical = ?', (vs, canon))
    con.commit()

# =================================================================
# Sub-recipe expansion (shared)
# =================================================================
def expand_subrecipes(recipes, by_rec_id, sub_titles, max_depth=5):
    """For each direct sub-recipe reference, append scaled constituent
    ingredients to the parent's expanded_ingredients."""
    def expand(ing, depth, visited):
        if depth > max_depth: return []
        sub = None
        if ing.get('via_rec_id') and ing['via_rec_id'] in by_rec_id:
            sub = by_rec_id[ing['via_rec_id']]
        elif ing['canonical'] in sub_titles:
            sub = sub_titles[ing['canonical']]
        if sub is None: return []
        if sub.get('rec_id') and sub['rec_id'] in visited: return []
        parent_cups = cup_equivalent(ing.get('amount'), ing.get('unit'))
        sub_yield_cups = cup_equivalent(sub.get('serves_amount'), sub.get('serves_unit'))
        scale_known = parent_cups is not None and sub_yield_cups is not None and sub_yield_cups > 0
        scale = (parent_cups / sub_yield_cups) if scale_known else 1.0
        out = []
        new_visited = visited | ({sub['rec_id']} if sub.get('rec_id') else set())
        for sub_ing in sub.get('ingredients', []):
            scaled_amount = sub_ing['amount'] * scale if sub_ing.get('amount') is not None else None
            grams = sub_ing['grams_est'] * scale if sub_ing.get('grams_est') is not None else None
            new_ing = {
                'raw': f'[expanded from {sub["title"]}] {sub_ing["raw"]}',
                'amount': scaled_amount,
                'unit': sub_ing.get('unit'),
                'name_raw': sub_ing.get('name_raw'),
                'canonical': sub_ing['canonical'],
                'grams_est': grams,
                'normalized': sub_ing.get('normalized', False),
                'gram_source': sub_ing.get('gram_source'),
                'is_subrecipe_ref': False,
                'via_rec_id': sub.get('rec_id'),
                'scale_known': scale_known,
                'scale_factor': scale,
                'expansion_depth': depth,
            }
            out.append(new_ing)
            if sub_ing.get('is_subrecipe_ref') and sub_ing['canonical'] not in PANTRY_STAPLES:
                out.extend(expand(sub_ing, depth+1, new_visited))
        return out
    for r in recipes:
        expanded = []
        for ing in r.get('ingredients', []):
            if ing.get('is_subrecipe_ref') and ing['canonical'] not in PANTRY_STAPLES:
                expanded.extend(expand(ing, 1, set()))
        r['expanded_ingredients'] = expanded
