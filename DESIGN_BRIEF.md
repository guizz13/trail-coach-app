# SENSEI — Brief design frontend

## Instructions pour Claude Code

Refais entièrement le frontend de l'application. Remplace tous les fichiers HTML/CSS/JS existants dans `frontend/`. Le backend (FastAPI, routes, services) ne change pas — seul le rendu visuel et le wording changent.

L'app s'appelle **Sensei**. C'est un coach sportif personnel pour un athlète hybride (trail, squash, musculation). L'app est utilisée exclusivement sur iPhone — design mobile-first, 375px de large, pensé pour être installé en PWA sur l'écran d'accueil.

---

## 1. Identité visuelle

### Nom et logo
- Nom : **SENSEI**
- Logo texte : lettres capitales, espacement large (letter-spacing: 3px), gradient bleu→violet
- Favicon / icône PWA : carré arrondi noir (#08080A) avec le "S" en gradient bleu→violet, simple et lisible à 60x60px

### Palette de couleurs

```css
:root {
  /* Fond */
  --bg-app: #08080A;
  --bg-card: #121215;
  --bg-card-hover: #18181C;
  --bg-surface: #1E1E23;

  /* Texte */
  --text-primary: #F0F0F2;
  --text-secondary: #A0A0A6;
  --text-muted: #606066;

  /* Accent principal */
  --accent: #4F8EF7;
  --accent-dim: #1A2940;

  /* Sémantiques */
  --green: #2DD4A0;
  --green-dim: #0A2E22;
  --orange: #F5A623;
  --orange-dim: #2E1F08;
  --red: #F04848;
  --red-dim: #2E0C0C;

  /* Disciplines */
  --course: #4F8EF7;       /* bleu */
  --course-dim: #1A2940;
  --squash: #9B6DFF;       /* violet */
  --squash-dim: #1A1030;
  --muscu: #A0A0A6;        /* gris clair */
  --muscu-dim: #1E1E23;
  --velo: #2DD4A0;         /* vert */
  --velo-dim: #0A2E22;

  /* Bordures et rayons */
  --border: #1E1E24;
  --radius: 14px;
  --radius-sm: 8px;
}
```

### Typographie
- Font : `-apple-system, 'SF Pro Display', system-ui, sans-serif`
- Titres de page : 22px, weight 700, letter-spacing -0.3px
- Section labels : 10px, uppercase, letter-spacing 1.2px, weight 700, couleur --text-muted
- Texte corps : 13px, weight 400/500
- Chiffres importants : 18-22px, weight 700, letter-spacing -0.5px
- Sous-texte : 11px, couleur --text-muted

### Principes de design
- Pas de gradients sur les fonds (sauf le logo texte)
- Pas de shadows, pas de glow, pas de blur (sauf le backdrop-filter de la tab bar)
- Coins arrondis généreux (14px sur les cartes, 8px sur les badges/inputs)
- Espacement aéré entre les cartes (6-8px de gap vertical)
- Icônes : Tabler Icons outline uniquement via le webfont (déjà chargé)
- Pas d'emojis

---

## 2. PWA — manifest et service worker

### manifest.json
```json
{
  "name": "Sensei",
  "short_name": "Sensei",
  "description": "Coach sportif personnel",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#08080A",
  "theme_color": "#08080A",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

### Service worker
Minimal — cache les assets statiques (CSS, JS, icônes) pour un chargement rapide. Pas de notifications push en V1.

### Icône PWA
Générer un PNG 512x512 : fond #08080A, lettre "S" centrée en gradient linéaire (de #4F8EF7 à #9B6DFF), police bold, coins du carré arrondis à ~20%.

---

## 3. Composants réutilisables

### Tab bar (bas de page, fixe)
```
Position : fixed bottom
Background : rgba(8,8,10,0.92) + backdrop-filter: blur(20px)
Bordure haute : 0.5px solid var(--border)
Padding : 6px 0 22px (safe area iOS)
5 onglets : Semaine | Import | Préparer | Objectifs | Stats
Icônes Tabler : ti-calendar | ti-upload | ti-adjustments | ti-target | ti-chart-line
Actif : couleur --accent, inactif : --text-muted
```

### Top bar (haut de chaque page)
```
Logo "SENSEI" à gauche (gradient)
Élément contextuel à droite selon la page :
  - Semaine : initiales avatar "GA" dans un cercle
  - Objectifs : mois courant
  - Stats : filtre période
  - Import / Préparer : rien
```

### Badge / tag
```
Font-size : 10px, weight 700, uppercase, letter-spacing 0.6px
Padding : 5px 10px, border-radius 8px
Variantes :
  - Mode libre : bg --accent-dim, text --accent, texte "Entraînement libre"
  - Prépa course : bg --orange-dim, text --orange, texte "Prépa [nom] J-xxx"
  - Santé 100% : bg --green-dim, text --green
  - Objectif principal : bg --orange-dim, text --orange
  - Course prévue : bg --accent-dim, text --accent
  - Participation : bg --bg-surface, text --text-secondary
```

### Carte de séance
```
Background : --bg-card, border-radius 14px, padding 12px 14px
Icône discipline : carré 28x28px, border-radius 8px, fond dim + icône colorée
  - Course : bg --course-dim, icône ti-run couleur --course
  - Squash : bg --squash-dim, icône ti-ball-tennis couleur --squash
  - Muscu : bg --muscu-dim, icône ti-barbell couleur --muscu
  - Vélo : bg --velo-dim, icône ti-bike couleur --velo
Type de séance : 13px weight 500
Détail : 11px --text-muted
Statut à droite :
  - "fait" : couleur --green
  - "à faire" : couleur --text-muted
  - "manqué" : couleur --red
Verdict (si séance analysée) :
  - Dot 6px + texte "vert/orange/rouge" en couleur correspondante
Trace GPX (si course outdoor avec GPS) :
  - Polyline SVG miniature 50x35px, stroke couleur --course
  - Stats inline : distance, D+, FC moy
Jour actuel : border 1px solid rgba(79,142,247,0.25), bg --bg-card-hover
```

### Carte métrique
```
Background : --bg-card, border-radius 14px, padding 14px
Label : 10px --text-muted uppercase letter-spacing 0.6px
Valeur : 18-22px weight 700, couleur sémantique selon la donnée
Sous-texte : 11px --text-muted
```

### Message coach (conditionnel — affiché uniquement après analyse ou bilan)
```
Background : linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)
Border-left : 3px solid --accent
Border-radius : 12px
Padding : 14px 16px
Label "Message du coach" : 10px uppercase, couleur --accent, weight 600
Texte : 13px, line-height 1.5, couleur #C8C8CC
```

### Formulaire
```
Inputs : bg --bg-surface, border 0.5px solid --border, radius 8px, padding 8px 10px
Labels : 10px --text-muted uppercase weight 600
Selects : même style que inputs
Bouton principal : bg --accent, text white, radius 10px, padding 12px, weight 600
Bouton secondaire : bg transparent, border 0.5px --border, radius 10px
```

---

## 4. Les 5 écrans

### 4.1 Semaine (`/`)

**Structure de haut en bas :**

1. Top bar : logo + avatar
2. Navigation semaine : `‹ [semaine du XX — XX xxx] ›` avec swipe horizontal
3. Badges en ligne : mode actif + compte à rebours prochain objectif principal + santé
4. Message coach (seulement si une analyse ou bilan a été fait cette semaine, sinon absent)
5. Section "État de forme" — grille 2 colonnes :
   - Équilibre de charge (jauge visuelle + ratio)
   - Répartition zones (barre colorée Z1-Z2/Z3/Z4+ avec pourcentages)
6. Courbe volume course (12 semaines, style Strava — line chart avec area fill gradient)
7. Section "Planning" — une carte par jour lundi→dimanche
8. Coût Sensei discret en bas : "Sensei 0.42 $ / 5.00 $ ce mois" en --text-muted, 10px

**Navigation entre semaines :**
- Flèches gauche/droite dans le header
- Swipe horizontal (optionnel, nice-to-have)
- Semaines passées : séances avec statuts réels et verdicts
- Semaines futures : séances planifiées

**Jauge équilibre de charge :**
- Track horizontal avec gradient de fond (rouge→orange→vert→vert→orange→rouge) en opacité 0.3
- Marqueur rond 12px positionné selon le ratio (0.0 à 2.0, centre = 1.05)
- Couleur du marqueur : vert si 0.8-1.3, orange si 1.3-1.5, rouge si >1.5 ou <0.8
- Sous la jauge : zones texte "sous-charge / optimal / danger"
- Ratio chiffré en dessous : "1.08 / 0.8—1.3"

**Courbe volume course :**
- SVG inline, viewBox proportionnel
- Polyline bleue (--course), stroke-width 2, stroke-linejoin round
- Area fill avec gradient vertical (--course à 25% → transparent)
- Point rond bleu sur la dernière semaine
- Labels en bas : S-12, S-8, S-4, Auj.
- Header : label "Volume course (km / semaine)" + valeur courante "XX km cette sem."

### 4.2 Import (`/import`)

**Structure :**

1. Top bar : logo
2. Titre "Importer des séances"
3. Zone drag & drop / tap :
   - Bordure dashed 2px --border, radius 14px, padding 40px
   - Icône ti-upload centrée, 32px, --text-muted
   - Texte : "Déposer les fichiers JSON Suunto" + "ou toucher pour choisir"
4. Case à cocher : "Analyser avec le coach" (cochée par défaut)
5. Après import — carte résumé par fichier :
   - Icône discipline + type détecté + durée + distance
   - Si muscu : formulaire inline (groupes musculaires en cases à cocher, charges optionnelles)
   - Si course outdoor avec GPS : mini trace GPX + stats
   - Si sous_type_confiance < 0.6 : bandeau orange "Type détecté : EF — corriger ?"
   - Si doublon : bandeau gris "Déjà importé — ignoré"
6. Si analyse LLM activée — carte verdict :
   - Bandeau coloré (vert/orange/rouge) en haut
   - Texte d'analyse (3-5 lignes)
   - Si ajustements proposés : liste des changements
   - Si rouge : boutons "Accepter" / "Garder le plan"

**Formulaire muscu (inline dans la carte) :**
```
Split proposé : affiché en badge, modifiable d'un tap (Push A / Pull A / Push B / Pull B / Jambes)
Groupes musculaires : grille de cases à cocher 2 colonnes
  pectoraux, triceps, épaules, dos, biceps, cuisses, ischios, mollets, abdos
Charges (optionnel, réduit par défaut, expand "Ajouter des charges") :
  3 lignes : [exercice] [kg] [reps] [séries]
```

### 4.3 Préparer (`/dimanche`)

**Structure :**

1. Top bar : logo
2. Titre "Préparer ta semaine"
3. Sélecteur de semaine : "Semaine du [lundi]" avec date picker
4. Section "Squash prévus" :
   - 7 lignes (lundi→dimanche), chaque ligne : case à cocher + jour + sélecteur créneau (soir/midi/journée)
   - Samedi/dimanche : créneau par défaut "journée" au lieu de "soir"
5. Section "Contraintes" :
   - Bouton "+ Contrainte" → ajoute une ligne : [jour] [créneau] [raison texte libre]
   - Lignes supprimables
6. Sliders :
   - Ressenti : 1-10, label + valeur affichée
   - Sommeil : 1-10, label + valeur affichée
7. Section "Statut santé" :
   - Sélecteur : 100% / Vigilance / Blessure
   - Si vigilance ou blessure : champ texte "zone concernée"
8. Notes libres : textarea
9. Bouton "Générer ma semaine" → appel LLM → affiche :
   - Bilan semaine écoulée (résumé, stats)
   - Semaine proposée (même format que l'écran Semaine, éditable)
   - Message coach
   - Bouton "Valider" / "Modifier"

### 4.4 Objectifs (`/evenements`)

**Structure :**

1. Top bar : logo + mois courant
2. Titre "Objectifs" + badge mode actif
3. Section "Timeline" — composant visuel :
   - Container card, padding 16px
   - En-tête : 6 mois affichés, mois courant en --accent
   - Barre horizontale 32px de haut, bg --bg-surface, radius 6px
   - Phases colorées à l'intérieur (Libre=bleu 15%, Build=orange 15-25%, Pic=violet 20%, Affûtage=vert 15%)
   - Marqueur "maintenant" : trait vertical blanc 2px avec dot 8px en haut
   - Marqueurs d'événements : dots ronds 14px colorés (orange=trail, violet=squash) positionnés sur la barre
   - Légende en dessous : dots + labels
4. Section "À venir" — cartes d'événements :
   - Border-left 3px colorée selon le type (orange=trail, violet=squash, gris=autre)
   - Nom + compte à rebours + badge importance
   - Stats : distance, D+, durée de prépa
   - Trace GPX miniature si importée (profil d'altitude en mini polyline)
   - Bouton "Importer la trace GPX" si pas encore fait
5. Section "Ajouter un objectif" — formulaire :
   - Type : Trail / Compétition squash / Autre
   - Importance : Objectif principal / Course prévue / Participation
   - Nom, Date, Distance, D+, Notes
   - Import GPX (optionnel) : bouton fichier
   - Bouton "Ajouter cet objectif"
6. Après ajout : reconstruction LLM → timeline mise à jour + conflits affichés

### 4.5 Stats (`/historique`)

**Structure :**

1. Top bar : logo + filtre période (4 sem / 12 sem / 6 mois)
2. Titre "Stats"
3. Section "Volume course" :
   - Courbe cumul km/semaine (même composant que sur le dashboard, en plus grand)
   - Valeurs moyennes affichées
4. Section "Équilibre de charge" :
   - Courbe ACWR sur la période, avec zones colorées (vert=optimal, orange, rouge)
5. Section "Poids" :
   - Courbe si données disponibles
   - Formulaire rapide d'ajout (date + kg)
6. Section "Musculation" :
   - Tableau des charges par exercice phare dans le temps
   - Graphique progression (optionnel V2)
7. Section "Séances" :
   - Liste filtrable par famille (tous / course / squash / muscu / vélo)
   - Chaque ligne : date, type, durée, distance, verdict
   - Tap → détail complet + analyse LLM associée

---

## 5. Wording complet — table de correspondance

Tout le code backend utilise les termes techniques. Le frontend traduit à l'affichage :

| Backend / System prompt | Frontend (affiché à l'utilisateur) |
|---|---|
| BASE | Entraînement libre |
| RACE_PREP | Prépa [nom de la course] |
| trail_race | Trail |
| squash_competition | Compétition squash |
| other | Autre |
| priorite A | Objectif principal |
| priorite B | Course prévue |
| priorite C | Participation |
| ACWR | Équilibre de charge |
| analyse_seance | Analyse |
| bilan_hebdo | Bilan |
| reconstruction_evenements | Reconstruction du plan |
| EF | Endurance fondamentale |
| intervals | Intervalles |
| cotes | Côtes |
| tempo | Tempo |
| sortie_longue | Sortie longue |
| muscu_push | Musculation Push |
| muscu_pull | Musculation Pull |
| muscu_jambes | Musculation Jambes |
| prevu | À faire |
| realise | Fait |
| manque | Manqué |
| modifie | Modifié |
| vert | (dot verte) + "conforme" |
| orange | (dot orange) + "attention" |
| rouge | (dot rouge) + "alerte" |
| recovery_time_h | Récupération estimée |
| peak_training_effect | Effet d'entraînement |
| charge | Charge de la séance |

---

## 6. Traces GPX — rendu minimaliste

Quand une séance de course outdoor (type 3) est importée, les coordonnées GPS existent dans les Samples. Extraire Latitude/Longitude, normaliser dans un viewBox SVG, tracer une polyline fine.

```
Style : stroke couleur --course (ou --orange pour un événement trail)
Stroke-width : 1.5px
Fill : none
Opacité : 0.7-0.8
ViewBox : calculé dynamiquement selon les bornes de la trace
Dimensions d'affichage : 50x35px dans une carte séance, 80x40px dans une carte événement
```

Pour les événements : si un fichier GPX de course est importé, extraire le profil d'altitude (élévation par point) et tracer une polyline de profil (pas la vue carte, la vue altitude). Même style, mêmes dimensions.

L'extracteur GPS est à ajouter dans `extractor.py` :
- Nouvelle fonction `extraire_trace(samples) -> list[tuple[float, float]]` qui retourne les coordonnées normalisées
- Nouvelle fonction `extraire_profil(samples) -> list[float]` qui retourne les altitudes
- Le frontend les consomme pour générer le SVG inline

---

## 7. Règles d'implémentation frontend

- **Mobile-first** : tout est conçu pour 375px. Pas de media queries desktop en V1.
- **Dark mode uniquement** : pas de light mode.
- **Pas de framework JS** : vanilla JS, pas de React/Vue/Angular.
- **Pas de bibliothèque CSS** : CSS custom, pas de Tailwind/Bootstrap.
- **Icônes** : Tabler Icons webfont uniquement, outline (pas filled).
- **Scrolling** : scroll vertical naturel, pas de scroll horizontal (sauf swipe semaine si implémenté).
- **Tab bar** : toujours visible, fixe en bas, backdrop blur.
- **Padding bottom** : chaque page a un padding-bottom de 80px minimum pour que le contenu ne soit pas caché par la tab bar.
- **Safe areas iOS** : `padding-top: env(safe-area-inset-top)`, `padding-bottom: env(safe-area-inset-bottom)` sur le body.
- **Transitions** : aucune animation complexe. Transitions CSS simples (0.2s ease) sur les hover/active des boutons et cartes.
- **Loading** : pendant les appels LLM (qui prennent 5-15 secondes), afficher un skeleton loader ou un spinner discret avec le texte "Sensei réfléchit..."
- **Erreurs LLM** : si le JSON retourné est invalide, afficher la réponse brute dans une card d'erreur avec un bouton "Réessayer".

---

## 8. Fichiers à créer/modifier

```
frontend/
├── index.html          → page Semaine (dashboard)
├── import.html         → page Import
├── dimanche.html       → page Préparer
├── evenements.html     → page Objectifs
├── historique.html     → page Stats
├── login.html          → page de connexion (déjà existante, adapter le style)
├── manifest.json       → PWA manifest
├── sw.js               → Service worker minimal
└── static/
    ├── style.css       → Palette + composants (tout le CSS)
    ├── app.js          → Logique commune (tab bar, auth, fetch helpers)
    ├── semaine.js      → Logique spécifique semaine
    ├── import.js       → Logique import + drag&drop + formulaire muscu
    ├── dimanche.js     → Logique formulaire préparer
    ├── evenements.js   → Logique objectifs + timeline
    ├── historique.js   → Logique stats + graphiques
    ├── icon-192.png    → Icône PWA 192x192
    └── icon-512.png    → Icône PWA 512x512
```

Le `<head>` de chaque page HTML doit inclure :
```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#08080A">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/dist/tabler-icons.min.css">
<link rel="stylesheet" href="/static/style.css">
```

---

## 9. Ce qui ne change PAS

- Le backend (FastAPI, routes, services, extracteur, métriques, LLM client, schéma DB)
- Le system prompt (`prompts/system_prompt_coach.md`)
- La logique d'authentification (juste restyler la page login)
- Les endpoints API — le frontend les appelle tels quels

Commit le résultat en une seule fois sur la branche `feat/design-sensei`, puis propose le merge.
