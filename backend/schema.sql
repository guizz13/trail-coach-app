-- ============================================================================
-- Schéma de données — Coach Hybride
-- Compatible SQLite (V1 Replit) et PostgreSQL (migration ultérieure)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Profil de l'athlète (une seule ligne, mise à jour)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profil (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    poids_kg            REAL,
    fc_max              INTEGER NOT NULL DEFAULT 191,
    fc_seuil_bas        INTEGER NOT NULL DEFAULT 157,
    fc_seuil_haut       INTEGER NOT NULL DEFAULT 164,
    allure_seuil_kmh    REAL DEFAULT 12.5,
    vo2max              REAL,
    volume_course_max_km REAL DEFAULT 68,      -- record hebdo toléré
    dplus_max_m         REAL DEFAULT 2400,
    mode_actif          TEXT NOT NULL DEFAULT 'BASE' CHECK (mode_actif IN ('BASE','RACE_PREP')),
    statut_sante        TEXT NOT NULL DEFAULT '100%',   -- '100%' | 'vigilance:<zone>' | 'blessure:<zone>'
    notes_sante         TEXT,
    maj_le              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Événements (dossards, compétitions squash, autres)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evenements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL CHECK (type IN ('trail_race','squash_competition','other')),
    titre           TEXT NOT NULL,
    date_evt        TEXT NOT NULL,                 -- ISO date
    priorite        TEXT NOT NULL DEFAULT 'B' CHECK (priorite IN ('A','B','C')),
    distance_km     REAL,
    dplus_m         REAL,
    notes           TEXT,
    cree_le         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Plan macro de préparation (généré par reconstruction_evenements)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_prepa (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    evenement_id        INTEGER REFERENCES evenements(id) ON DELETE CASCADE,
    phase               TEXT NOT NULL CHECK (phase IN ('BASE','BUILD','PIC','AFFUTAGE')),
    du                  TEXT NOT NULL,
    au                  TEXT NOT NULL,
    objectif            TEXT,
    sortie_longue_cible TEXT,
    genere_le           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Impératifs saisis chaque dimanche pour la semaine suivante
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS imperatifs_semaine (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    semaine_debut   TEXT NOT NULL UNIQUE,          -- lundi ISO
    squash_jours    TEXT,                           -- JSON: ["mercredi","samedi"]
    contraintes     TEXT,                           -- JSON: [{"jour":"jeudi","creneau":"matin","raison":"déplacement"}]
    ressenti        INTEGER CHECK (ressenti BETWEEN 1 AND 10),
    sommeil         INTEGER CHECK (sommeil BETWEEN 1 AND 10),
    notes           TEXT,
    saisi_le        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Séances planifiées (générées par bilan_hebdo, modifiables par analyse_seance)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seances_planifiees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_seance     TEXT NOT NULL,
    creneau         TEXT NOT NULL CHECK (creneau IN ('matin','midi','soir','journee')),
    type            TEXT NOT NULL,                 -- EF | intervals | cotes | tempo | sortie_longue | squash | muscu_push | muscu_pull | muscu_jambes | velo | repos
    detail          TEXT,
    intensite       TEXT,
    duree_min       INTEGER,
    distance_km     REAL,
    dplus_m         REAL,
    statut          TEXT NOT NULL DEFAULT 'prevu' CHECK (statut IN ('prevu','realise','manque','modifie')),
    seance_realisee_id INTEGER REFERENCES seances_realisees(id),
    origine         TEXT,                           -- 'bilan_hebdo' | 'analyse_seance' | 'manuel'
    version         INTEGER NOT NULL DEFAULT 1,
    cree_le         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_planifiees_date ON seances_planifiees(date_seance);

-- ----------------------------------------------------------------------------
-- Séances réalisées (import fichiers Suunto)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seances_realisees (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_hash        TEXT NOT NULL UNIQUE,       -- SHA256 du fichier → anti-doublon
    fichier_nom         TEXT,
    activity_type_code  INTEGER NOT NULL,
    famille             TEXT NOT NULL,              -- course_outdoor | course_tapis | squash | velo | muscu | inconnu
    sous_type           TEXT,                       -- EF | intervals | cotes | tempo | sortie_longue (course uniquement)
    sous_type_confiance REAL,
    sous_type_confirme  INTEGER NOT NULL DEFAULT 0, -- 1 si validé par l'utilisateur ou le LLM
    date_debut          TEXT NOT NULL,
    duree_min           REAL NOT NULL,
    distance_km         REAL DEFAULT 0,
    dplus_m             REAL,
    dmoins_m            REAL,
    vitesse_moy_kmh     REAL,
    fc_moy              INTEGER,
    fc_max              INTEGER,
    temps_zones_s       TEXT,                       -- JSON {"z1":..,"z5":..}
    temps_zones_pct     TEXT,                       -- JSON
    epoc                REAL,
    recovery_time_h     REAL,
    peak_training_effect REAL,
    vo2max              REAL,
    energie_kcal        REAL,
    feeling             INTEGER,
    a_gps               INTEGER DEFAULT 0,
    a_fc                INTEGER DEFAULT 0,
    charge              REAL,                       -- calculée par metrics.charge_seance
    donnees_brutes      TEXT,                       -- JSON complet de SeanceExtraite
    importe_le          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_realisees_date ON seances_realisees(date_debut);
CREATE INDEX IF NOT EXISTS idx_realisees_famille ON seances_realisees(famille);

-- ----------------------------------------------------------------------------
-- Détail musculation (saisi par l'utilisateur après import d'une séance type 23)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS muscu_detail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seance_id       INTEGER NOT NULL REFERENCES seances_realisees(id) ON DELETE CASCADE,
    groupes         TEXT NOT NULL,                 -- JSON: ["pectoraux","triceps"]
    split           TEXT,                           -- 'push_a' | 'pull_a' | 'push_b' | 'pull_b' | 'jambes' | 'autre'
    charges         TEXT,                           -- JSON: [{"exo":"développé couché haltères","kg":28,"reps":8,"series":4}]
    notes           TEXT
);

-- ----------------------------------------------------------------------------
-- Analyses LLM (trace de chaque appel, pour audit et affichage)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyses_llm (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type_appel      TEXT NOT NULL CHECK (type_appel IN ('analyse_seance','bilan_hebdo','reconstruction_evenements')),
    seance_id       INTEGER REFERENCES seances_realisees(id),
    semaine_debut   TEXT,
    evenement_id    INTEGER REFERENCES evenements(id),
    verdict         TEXT,                           -- vert | orange | rouge (analyse_seance)
    reponse_json    TEXT NOT NULL,
    modele          TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cout_usd        REAL,
    valide_par_user INTEGER DEFAULT 0,              -- pour les verdicts rouges
    cree_le         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ----------------------------------------------------------------------------
-- Suivi poids (saisie manuelle ou import balance)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poids (
    date_mesure     TEXT PRIMARY KEY,
    poids_kg        REAL NOT NULL,
    masse_grasse_pct REAL
);

-- ----------------------------------------------------------------------------
-- Table de correspondance ActivityType (extensible depuis l'UI)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_types (
    code            INTEGER PRIMARY KEY,
    famille         TEXT NOT NULL,
    libelle         TEXT
);
INSERT OR IGNORE INTO activity_types VALUES
    (3,  'course_outdoor', 'Course / trail outdoor'),
    (93, 'course_tapis',   'Course sur tapis'),
    (37, 'squash',         'Squash'),
    (17, 'velo',           'Vélo en salle'),
    (23, 'muscu',          'Musculation');

-- ----------------------------------------------------------------------------
-- Profil initial
-- ----------------------------------------------------------------------------
INSERT OR IGNORE INTO profil (id, poids_kg, fc_max, mode_actif, statut_sante)
VALUES (1, 72, 191, 'BASE', '100%');
