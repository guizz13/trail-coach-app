# Coach Hybride — Spec projet

Application personnelle de coaching pour un athlète hybride (trail, squash, musculation).
Un seul utilisateur. Priorité à la fiabilité de la logique de coaching, pas à l'esthétique.

## Ce qui existe déjà et ne doit PAS être réécrit

| Fichier | Rôle | Statut |
|---------|------|--------|
| `prompts/system_prompt_coach.md` | Cerveau du LLM. Toute la logique de coaching. | Validé, ne pas modifier sans accord |
| `backend/extractor.py` | Parse les JSON Suunto → `SeanceExtraite`. Classification course niveau 1. | Validé sur 5 types réels |
| `backend/metrics.py` | Charge, ACWR, distribution zones, évaluation des seuils. | Validé |
| `backend/llm_client.py` | Appels Claude avec cache, routage, compteur de coût. | Prêt, à tester avec clé API |
| `backend/schema.sql` | Base de données. | Validé SQLite |

Ces modules sont la couche métier. Le travail restant est l'assemblage, l'API HTTP et l'interface.

## Stack imposée

- Backend : Python 3.11+, **FastAPI**, SQLite (fichier `data/coach.db`)
- Frontend : HTML + JS vanilla (ou htmx). Pas de framework lourd. Mobile-first : l'app sera surtout consultée sur téléphone.
- Dépendances Python : `fastapi`, `uvicorn`, `anthropic`, `python-multipart`
- Variables d'environnement : `ANTHROPIC_API_KEY`, `COACH_DATA_DIR` (défaut `./data`)

## Architecture

```
trail-coach-app/
├── CLAUDE.md                     ← ce fichier
├── prompts/system_prompt_coach.md
├── backend/
│   ├── extractor.py              ← existant
│   ├── metrics.py                ← existant
│   ├── llm_client.py             ← existant
│   ├── schema.sql                ← existant
│   ├── db.py                     ← À CRÉER : connexion, helpers CRUD
│   ├── services.py               ← À CRÉER : orchestration (import, bilan, événements)
│   └── main.py                   ← À CRÉER : FastAPI, routes
├── frontend/
│   ├── index.html                ← dashboard
│   ├── import.html
│   ├── dimanche.html
│   ├── evenements.html
│   ├── historique.html
│   └── static/app.js, style.css
└── data/                         ← DB + usage_llm.json (gitignore)
```

## Les 5 écrans

### 1. Dashboard (`/`)
- Semaine en cours : 7 colonnes lundi→dimanche, chaque séance planifiée avec son statut (prévu / réalisé ✓ / manqué / modifié)
- Bandeau haut : mode actif (BASE / RACE_PREP), phase de prépa si applicable, compte à rebours prochain événement A, statut santé
- Indicateurs de la semaine : ACWR (avec zone colorée), distribution Z1-Z2 / Z3 / Z4-Z5 des séances course, charge cumulée
- Dernière analyse LLM (verdict coloré + message_coach)
- Compteur coût LLM du mois

### 2. Import (`/import`)
- Zone drag & drop multi-fichiers (JSON Suunto)
- Pour chaque fichier : hash SHA256 → si déjà importé, ignorer avec message
- Appel `extractor.extraire()` → affichage carte résumé (famille, durée, distance, FC, zones, EPOC)
- Si `famille == "muscu"` : formulaire inline
  - Split proposé = prochain dans la rotation (push_a → pull_a → push_b → pull_b) d'après la dernière séance muscu enregistrée
  - Cases à cocher groupes : pectoraux, triceps, épaules, dos, biceps, cuisses, ischios, mollets, abdos
  - Charges optionnelles : 3 lignes libres (exo, kg, reps, séries)
- Si `famille == "inconnu"` : demander la famille et enregistrer dans `activity_types`
- Si `famille` course et `sous_type_confiance < 0.6` : proposer le sous_type détecté, laisser corriger
- Bouton « Analyser » → `services.importer_et_analyser()` → affiche verdict + analyse + ajustements proposés
- Si verdict rouge : boutons « Accepter les ajustements » / « Garder le plan initial »

### 3. Dimanche (`/dimanche`)
- Formulaire impératifs semaine suivante :
  - Squash prévus : sélecteur multi-jours + créneau (soir/midi/week-end)
  - Contraintes : lignes (jour, créneau, raison) — déplacement, réunion, etc.
  - Ressenti 1-10, sommeil 1-10
  - Statut santé : 100% / vigilance [zone] / blessure [zone]
  - Notes libres
- Bouton « Générer ma semaine » → `services.bilan_hebdo()` → affiche bilan + semaine proposée
- Bouton « Valider » → écrit dans `seances_planifiees`
- Possibilité d'éditer une séance manuellement avant validation

### 4. Événements (`/evenements`)
- Liste des événements à venir (triés par date)
- Formulaire ajout : type, titre, date, priorité, distance, D+, notes
- À chaque ajout/modification/suppression → `services.reconstruire()` → affiche plan macro + conflits détectés
- Vue timeline : phases de prépa colorées sur un calendrier des 6 prochains mois

### 5. Historique (`/historique`)
- Liste des séances réalisées, filtrable par famille et par période
- Clic → détail complet + analyse LLM associée
- Graphiques simples : volume course hebdo (12 semaines), ACWR (12 semaines), poids
- Muscu : tableau des charges par exercice phare dans le temps

## Services à implémenter (`backend/services.py`)

### `importer_et_analyser(fichier_bytes, nom, muscu_detail=None) -> dict`
1. Hash, anti-doublon
2. `extractor.extraire()` → insérer dans `seances_realisees` avec `charge = metrics.charge_seance()`
3. Si muscu_detail fourni → insérer dans `muscu_detail`
4. Chercher la séance planifiée du même jour (± même famille) → `prevu`
5. Calculer `acwr = metrics.calculer_acwr(toutes les séances des 35 derniers jours)`
6. Calculer `prochaine_qualite_dans_h` depuis `seances_planifiees`
7. `verdict, signaux = metrics.evaluer_seance(...)`
8. Appel `llm.analyse_seance(...)` avec `indicateurs = {acwr, signaux, distribution_semaine}`
9. Enregistrer dans `analyses_llm`
10. Si `prevu` trouvé → marquer `statut = 'realise'` et lier
11. Si ajustements proposés et verdict ≠ rouge → appliquer directement sur `seances_planifiees` (statut modifié, version+1)
12. Retourner {seance, verdict, analyse_llm, ajustements, validation_requise}

### `bilan_hebdo(imperatifs: dict) -> dict`
1. Sauver `imperatifs_semaine`
2. Charger : séances réalisées de la semaine écoulée, plan prévu, historique 4 semaines, événements à venir, phase prépa active
3. Calculer indicateurs : `acwr`, `distribution_hebdo` (course), volume km / D+ / charge, séances manquées
4. Appel `llm.bilan_hebdo(...)`
5. Enregistrer dans `analyses_llm`
6. Retourner la réponse pour affichage ; l'écriture dans `seances_planifiees` se fait au « Valider »

### `reconstruire() -> dict`
1. Charger tous les événements futurs, historique 8 semaines, plan_prepa actuel
2. Appel `llm.reconstruction_evenements(...)`
3. Écraser `plan_prepa` avec le nouveau plan macro
4. Si `mode_recommande` ≠ mode actuel → proposer la bascule (ne pas l'appliquer automatiquement)
5. Enregistrer dans `analyses_llm`

## Règles d'implémentation

- **Jamais** modifier le system prompt depuis le code. Il est chargé tel quel.
- Le LLM répond en JSON strict. Toujours parser avec try/except et afficher l'erreur brute si le JSON est invalide.
- Vérifier après chaque `bilan_hebdo` que la semaine générée respecte les règles dures (1 repos, 2 muscu, pas de longue en semaine). Si violation → afficher un avertissement rouge et refuser la validation. C'est une double sécurité côté code.
- Toutes les dates en ISO 8601, timezone Europe/Paris.
- La FC est en Hz dans les fichiers Suunto. `extractor.py` gère la conversion. Ne jamais la refaire ailleurs.
- Les zones FC sont dans `extractor.ZONES_BPM`. En V2 elles seront lues depuis `profil`.
- Anti-doublon strict sur le hash fichier.
- Log chaque appel LLM avec tokens et coût dans `analyses_llm`.
- Le plafond mensuel de 5 $ est géré par `llm_client.py` ; afficher le compteur sur le dashboard.

## Rotation muscu par défaut

`push_a → pull_a → push_b → pull_b → push_a …`
Le split proposé à l'import est le suivant dans la rotation par rapport à la dernière séance muscu enregistrée.

## Données de test

Cinq fichiers Suunto réels sont disponibles pour les tests (types 3, 93, 37, 17, 23). Les utiliser pour valider l'import de bout en bout avant de brancher le LLM.

## Hors périmètre V1

- Import automatique Strava (architecture prévue pour, module `extractor` isolé)
- Multi-utilisateur, authentification
- Nutrition détaillée (juste le poids en V1)
- Notifications push
