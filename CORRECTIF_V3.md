# SENSEI — Brief correctif v3

Applique toutes les modifications ci-dessous. Branche : `feat/objectifs-v3`. Commit à chaque section terminée. Pousse sur origin.

Le backend ne change pas. Seuls le frontend et le system prompt sont modifiés.

---

## 1. Contraste — valeurs finales

Dans `style.css`, remplace TOUTES les variables de couleur par celles-ci :

```css
:root {
  --bg-app: #09090C;
  --bg-card: #1A1A20;
  --bg-card-hover: #222228;
  --bg-surface: #26262D;

  --text-primary: #F5F5F7;
  --text-secondary: #CDCDD4;   /* ratio ~8:1 sur bg-card */
  --text-muted: #9494A0;       /* ratio ~5.5:1 sur bg-card */

  --border: #32323A;

  /* Les couleurs accent/sémantiques/disciplines ne changent pas */
}
```

Vérification : aucun texte dans toute l'app ne doit utiliser une couleur plus sombre que --text-muted (#9494A0) sur un fond plus sombre que --bg-surface (#26262D). Si tu trouves des exceptions (labels, placeholders, légendes), remonte-les à --text-muted minimum.

Les placeholders des inputs peuvent rester un cran en dessous : #7A7A84. Rien d'autre.

---

## 2. Page Objectifs (`evenements.html` + `evenements.js`) — restructuration complète

### 2.1 Supprimer le formulaire inline

Le formulaire "Ajouter un objectif" qui est actuellement affiché en permanence sur la page doit être SUPPRIMÉ de la page. Il est remplacé par la modale (section 3).

### 2.2 Nouvelle structure de la page (de haut en bas)

1. **Top bar** : logo SENSEI + mois courant
2. **Titre** "Objectifs" + badge mode actif
3. **Timeline 6 mois** (composant existant, inchangé)
4. **Section "Objectif principal"** : la carte de l'événement de priorité A, en format large :
   - Border-left 3px solid --orange, border-radius 0 14px 14px 0
   - Nom en 18px font-weight 700
   - Date en 12px --text-secondary
   - Badge importance (Objectif principal) en orange
   - J-XXX en 28px font-weight 700 couleur --orange, aligné à droite du header
   - Stats en ligne : distance (20px bold) + D+ (20px bold) + durée prépa (20px bold) avec labels en 10px --text-muted
   - Trace GPX si importée (mini polyline 80x35, stroke --orange)
   - Bouton "Importer la trace GPX" si pas de trace
5. **Section "Plan de préparation"** : cartes compactes par phase (voir 2.3)
6. **Section "Autres objectifs"** : liste compacte des événements B et C (si existants)
   - Format : une ligne par événement, icône type + nom + date + badge importance
7. **Bouton flottant (FAB)** : rond 52px, fond --accent, icône ti-plus blanche, position absolute bottom 86px right 20px, z-index 10. Au tap → ouvre la modale.

### 2.3 Plan de préparation — format cartes compactes

Chaque phase du plan_prepa est affichée comme une carte avec :
- Une barre verticale colorée à gauche (4px, border-radius 2px) :
  - BASE : --accent (bleu)
  - BUILD : --orange
  - PIC : --purple
  - AFFUTAGE : --green
- À droite de la barre :
  - Ligne 1 : badge phase (même couleur que la barre, fond dim) + dates alignées à droite en 11px --text-muted
  - Ligne 2-3 : données clés en 11px --text-secondary, valeurs en font-weight 600 --text-primary. Format :
    - "Volume [30 — 42 km]" + "D+ [700 — 1 100 m]"
    - "Longue [18-22 km / 800-1 000 m]" + "Squash [1/sem]"
  - PAS de texte explicatif (le champ "objectif" du LLM n'est pas affiché par défaut)
  - Optionnel : lien "Détails" en 10px --text-muted qui expand le texte objectif du LLM au tap

Espacement entre les cartes de phase : 6px.
Background des cartes : --bg-card. Border-radius : 14px. Padding : 14px.
Gap entre barre et contenu : 12px.

### 2.4 Bouton "Reconstruire le plan"

Reste en bas de la section plan de préparation, sous la dernière carte de phase. Style : bouton secondaire (bg transparent, border 0.5px --border, radius 12px).

---

## 3. Modale d'ajout d'objectif

### 3.1 Déclenchement

Le FAB (bouton "+") ouvre la modale. La modale est un overlay plein écran :
- Fond : rgba(0, 0, 0, 0.6) couvrant toute la page
- Contenu : div montant du bas (bottom sheet), fond --bg-card, border-radius 20px 20px 0 0 sur les coins hauts
- Poignée visuelle en haut : barre 36x4px, fond --bg-surface, border-radius 2px, centrée, margin-bottom 16px

### 3.2 Header modale

"Nouvel objectif" en 18px font-weight 700, bouton fermer (icône ti-x) à droite.

### 3.3 Sélection du type — boutons segmentés

3 boutons côte à côte (flex, gap 8px) :
- Trail : icône ti-run
- Squash : icône ti-ball-tennis
- Autre : icône ti-calendar-event

Le bouton actif a le fond --accent et le texte blanc. Les inactifs ont le fond --bg-surface et le texte --text-secondary.

### 3.4 Formulaire dynamique selon le type

**Si Trail sélectionné :**
- Importance : 3 boutons segmentés (Objectif principal / Course prévue / Participation). Actif : border 1px solid --accent, couleur --accent. Inactifs : fond --bg-surface.
- Champs : Nom, Date, Distance (km), D+ (m), Trace GPX (optionnel), Notes
- Style inputs : fond --bg-surface, border 0.5px solid --border, radius 10px, padding 12px 14px, font-size 14px

**Si Squash sélectionné :**
- PAS de champ importance (la compétition squash n'a pas de priorité A/B/C)
- Champs : Nom, Date, Lieu, Notes
- PAS de distance, D+, trace GPX

**Si Autre sélectionné :**
- PAS de champ importance
- Champs : Nom, Date, Notes
- PAS de distance, D+, trace GPX

### 3.5 Bouton submit

"Ajouter cet objectif" — pleine largeur, fond --accent, texte blanc, radius 12px, padding 14px, font-weight 600.

### 3.6 Comportement après ajout

La modale se ferme. La page Objectifs se rafraîchit. Si l'événement ajouté est de type trail_race priorité A, l'appel LLM reconstruction_evenements se déclenche avec le loader (section 5).

---

## 4. Carte objectif sur l'écran Semaine (`index.html` + `semaine.js`)

### 4.1 Condition d'affichage

Si un événement de priorité A ou B a sa date dans les 28 prochains jours, afficher la carte. Sinon, rien.

### 4.2 Position

Sous les badges (mode + santé), AVANT la section "État de forme". Si pas d'événement proche, l'état de forme remonte directement sous les badges.

### 4.3 Format de la carte

```
Background : --bg-card
Border : 0.5px solid --border
Border-radius : 14px
Padding : 12px 14px
Cursor : pointer (tap → navigation vers /evenements)
```

Contenu (flex horizontal) :
- À gauche : carré 40x40px, border-radius 10px, fond couleur discipline dim (--orange-dim pour trail, --purple-dim pour squash), icône centrée (ti-run ou ti-ball-tennis)
- Au centre (flex:1) :
  - Ligne 1 : nom de l'événement (14px font-weight 600) + J-XX aligné à droite (18px font-weight 700, couleur discipline)
  - Ligne 2 : distance / D+ en 11px --text-secondary
  - Ligne 3 : badge phase actuelle (9px, fond dim, couleur phase) + "semaine X/Y" en 10px --text-muted
- À droite : chevron ti-chevron-right en 16px --text-muted

### 4.4 Affichage du mode

Quand un événement A est dans les 12 semaines, le badge mode en haut de la page passe de "Entraînement libre" à "Prépa [nom]" en --orange. Ce changement est piloté par le champ mode_actif du profil en base, pas calculé côté frontend.

---

## 5. Loader LLM amélioré (`style.css` + `app.js`)

### 5.1 Skeleton loader

Remplace le spinner/texte actuel par des rectangles grisés qui pulsent :
- 3 à 4 rectangles empilés, hauteurs variées (40px, 60px, 40px, 50px)
- Fond --bg-surface, border-radius 10px
- Animation CSS "pulse" : opacity oscille entre 0.4 et 0.8 sur 1.5s ease-in-out infinite

```css
@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}
.skeleton-block {
  background: var(--bg-surface);
  border-radius: 10px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}
```

### 5.2 Texte rotatif

Sous le skeleton, un texte en 12px --text-muted, centré, qui change toutes les 3 secondes en cycle :

```javascript
const loadingMessages = [
  "Sensei analyse ton historique...",
  "Construction des phases...",
  "Vérification des contraintes...",
  "Finalisation du plan..."
];
```

### 5.3 Appliquer partout

Ce loader remplace l'ancien partout où un appel LLM est en cours :
- Import avec analyse cochée
- Bilan du dimanche → "Générer ma semaine"
- Reconstruction événements → "Reconstruire le plan"

---

## 6. Messages IA concis

### 6.1 System prompt (`prompts/system_prompt_coach.md`)

Dans la section 10, ajouter ces contraintes de format à CHAQUE type d'appel :

Pour `analyse_seance` :
```
Le champ "analyse" fait 2 phrases maximum (40 mots max). Pas de données chiffrées redondantes avec ce que l'app affiche déjà (zones %, EPOC, FC, distance). Va droit au point : ce qui va, ce qui dérive, quoi corriger.
```

Pour `bilan_hebdo` :
```
Le champ "resume" du bilan fait 3 phrases maximum (50 mots max).
Le champ "message_coach" fait 1 à 2 phrases maximum (30 mots max). Direct et actionnable.
Le champ "objectif" de la semaine suivante fait 1 phrase (15 mots max).
```

Pour `reconstruction_evenements` :
```
Le champ "analyse_conflits" fait 1 à 2 phrases maximum.
Le champ "objectif" de chaque phase du plan_macro fait 1 phrase maximum (20 mots).
Le champ "message_coach" fait 2 phrases maximum (40 mots max).
```

### 6.2 Affichage expand/collapse côté frontend

Pour les messages coach et les analyses LLM :
- Affichage par défaut : tronqué à 2 lignes avec `overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;`
- Lien "Voir plus" en 11px --accent, dessous le texte tronqué
- Au tap : le texte se déplie complètement, le lien devient "Réduire"
- Si le texte fait 2 lignes ou moins naturellement, pas de lien "Voir plus"

---

## 7. Vérification finale contraste

Avant de commit, fais une passe sur TOUTES les pages et vérifie :
- Aucun texte en dessous de #9494A0 sur un fond en dessous de #26262D
- Les labels de formulaires utilisent --text-muted (#9494A0) pas moins
- Les badges ont un contraste suffisant (texte coloré sur fond dim de la même couleur — vérifier visuellement)
- Les icônes Tabler dans les cartes de séance sont en couleur discipline (pas en --text-muted)
- Le texte des inputs a la couleur --text-primary (#F5F5F7)
- Les placeholders des inputs : #7A7A84 minimum

---

## Récapitulatif des fichiers modifiés

- `frontend/static/style.css` — palette contraste + skeleton loader
- `frontend/static/app.js` — loader rotatif, expand/collapse messages
- `frontend/evenements.html` — restructuration complète
- `frontend/static/evenements.js` — modale, formulaire dynamique, plan compact, FAB
- `frontend/index.html` — carte objectif
- `frontend/static/semaine.js` — logique carte objectif conditionnelle
- `prompts/system_prompt_coach.md` — contraintes de concision

Commit et pousse sur `feat/objectifs-v3`.
