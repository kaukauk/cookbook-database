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
CREATE TABLE sqlite_sequence(name,seq);
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
GROUP  BY canonical
/* v_ingredient_global_freq(canonical,n_direct,n_expanded,n_recipes_any_source) */;
CREATE VIEW v_ingredient_category_usage AS
SELECT ri.canonical,
       r.category,
       ri.source,
       COUNT(DISTINCT ri.recipe_id) AS n_recipes,
       (SELECT COUNT(*) FROM recipe r2 WHERE r2.category = r.category) AS total_in_category
FROM   recipe_ingredient ri
JOIN   recipe r ON r.id = ri.recipe_id
GROUP  BY ri.canonical, r.category, ri.source
/* v_ingredient_category_usage(canonical,category,source,n_recipes,total_in_category) */;
