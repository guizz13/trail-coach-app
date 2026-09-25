# SENSEI — Brief final : identité violet + logo + corrections

Applique toutes les modifications ci-dessous en une seule passe. Branche : `feat/violet-identity`. Commit par section. Pousse sur origin.

---

## 1. Logo et icônes PWA

### Concept retenu : D — asymétrique sport

Génère les icônes PWA en SVG inline converti en PNG (utilise un canvas ou une bibliothèque Python) :

**icon-192.png** et **icon-512.png** :
- Fond : carré arrondi (rx ~20%), gradient linéaire diagonal de #8B5CF6 (haut-gauche) à #5B21B6 (bas-droite)
- Kanji 先 : blanc, centré légèrement vers la droite (x ~48%), bold 800, taille ~62% de la hauteur
- Texte "SENSEI" : blanc, opacity 0.9, centré en bas (~75% de la hauteur), font-weight 800, letter-spacing 5px, taille ~10% de la hauteur
- Traits de vitesse à gauche du kanji : 3 lignes horizontales blanches, longueurs décroissantes (haut→bas), opacity décroissante (0.35, 0.25, 0.15), stroke-width décroissant (2.5, 2, 1.5), stroke-linecap round, positionnées verticalement au milieu du kanji

Enregistre dans `frontend/static/icon-192.png` et `frontend/static/icon-512.png`.

### Apple touch icon
Copie icon-192.png en `frontend/static/apple-touch-icon.png`.

### Favicon
Génère un `frontend/static/favicon.svg` avec le même design en SVG pur (pas besoin de PNG pour le favicon, le SVG est supporté par les navigateurs modernes).

---

## 2. Nouvelle palette — pivot violet

Remplace TOUTE la palette dans `style.css`. Le violet devient la couleur d'accent principale partout.

```css
:root {
  /* Fonds */
  --bg-app: #09090C;
  --bg-card: #1A1A20;
  --bg-card-hover: #222228;
  --bg-surface: #26262D;

  /* Texte */
  --text-primary: #F5F5F7;
  --text-secondary: #CDCDD4;
  --text-muted: #9494A0;

  /* Bordures */
  --border: #32323A;

  /* Accent principal — violet */
  --accent: #8B5CF6;
  --accent-light: #A78BFA;
  --accent-dim: #1E1040;

  /* Sémantiques — inchangés */
  --green: #2DD4A0;
  --green-dim: #0D3326;
  --orange: #F5A623;
  --orange-dim: #2E1F08;
  --red: #F04848;
  --red-dim: #2E0C0C;

  /* Disciplines */
  --course: #8B5CF6;
  --course-dim: #1E1040;
  --squash: #E879F9;
  --squash-dim: #2E1038;
  --muscu: #A0A0A6;
  --muscu-dim: #1E1E23;
  --velo: #2DD4A0;
  --velo-dim: #0D3326;

  /* Layout */
  --radius: 14px;
  --radius-sm: 8px;
}
```

### Ce qui change concrètement partout dans le CSS et le HTML

- Onglet actif tab bar : passe de bleu à `var(--accent)` (#8B5CF6)
- Bordure du jour actuel : passe de `rgba(79,142,247,0.25)` à `rgba(139,92,246,0.35)`
- Icône course (ti-run) : couleur `var(--course)` (violet) au lieu de bleu
- Fond icône course : `var(--course-dim)` au lieu de bleu dim
- Courbe de volume SVG : stroke et fill en #8B5CF6 au lieu de bleu
- Boutons principaux : background `var(--accent)` au lieu de bleu
- Logo texte "SENSEI" : couleur `var(--accent-light)` (#A78BFA)
- Badge mode prépa : fond `var(--accent-dim)`, texte `var(--accent-light)`
- Liens "Voir plus" : couleur `var(--accent)`
- Focus rings inputs : `var(--accent)`
- Toute occurrence de #4F8EF7 ou #3B82F6 dans le CSS → remplacer par var(--accent)
- Toute occurrence de #1A2940 → remplacer par var(--accent-dim)

### Le squash se distingue

Le squash passe en rose-violet (#E879F9, dim #2E1038) pour se différencier visuellement de la course (qui est maintenant en violet aussi). Si les deux étaient en violet identique, on ne distinguerait plus les disciplines.

---

## 3. Logo dans l'app — top bar

Le top bar de CHAQUE page affiche le logo ainsi :

```html
<div class="logo-box">
  <div class="logo-icon">先</div>
  <span class="logo-text">Sensei</span>
</div>
```

CSS :
```css
.logo-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #8B5CF6, #5B21B6);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic', sans-serif;
  font-size: 18px;
  font-weight: 800;
  color: #FFFFFF;
}
.logo-text {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--accent-light);
}
```

Remplace l'ancien logo gradient-text par ce composant sur toutes les pages.

---

## 4. Manifest PWA — mise à jour

```json
{
  "name": "Sensei",
  "short_name": "Sensei",
  "description": "Coach sportif personnel",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#09090C",
  "theme_color": "#8B5CF6",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

Le `theme_color` passe en violet — c'est ce qui colore la barre de statut iOS/Android.

---

## 5. Corrections en attente (du brief v3, si pas encore appliquées)

### 5.1 Contraste
Vérifie que les nouvelles valeurs de texte sont bien appliquées partout :
- --text-secondary: #CDCDD4 (ratio ~8:1 sur bg-card)
- --text-muted: #9494A0 (ratio ~5.5:1 sur bg-card)
- Placeholders inputs : #7A7A84
- Toutes les cartes ont `border: 0.5px solid var(--border)`

### 5.2 Page Objectifs
- Formulaire inline supprimé → FAB + modale
- Objectif principal en carte large
- Plan de prépa en cartes compactes avec barre latérale colorée
- Formulaire dynamique (pas de distance/D+ pour le squash)

### 5.3 Carte objectif sur Semaine
- Affichée si événement A ou B dans les 28 jours
- Sous les badges, avant l'état de forme

### 5.4 Messages IA concis
- System prompt : contraintes de longueur ajoutées
- Frontend : expand/collapse sur les messages

### 5.5 Loader LLM
- Skeleton blocks pulsants + messages rotatifs

### 5.6 Textes qui dépassent
- Cartes de phase : chaque ligne de données a `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;`
- Ou mieux : données structurées en grille 2 colonnes avec largeurs fixes

---

## 6. Vérification finale

Avant de commit la dernière section, vérifie :
- [ ] Plus aucune trace de bleu #4F8EF7 ou #3B82F6 dans le CSS (sauf éventuellement dans des graphiques spécifiques non liés à l'accent)
- [ ] Le logo kanji 先 s'affiche sur toutes les pages
- [ ] Les icônes PWA existent et sont référencées dans le manifest et les meta tags
- [ ] Le theme_color est #8B5CF6 dans le manifest ET dans la meta tag
- [ ] L'onglet actif de la tab bar est en violet
- [ ] La courbe de volume est en violet
- [ ] Les icônes course (ti-run) sont en violet
- [ ] Les icônes squash (ti-ball-tennis) sont en rose-violet #E879F9
- [ ] Le bouton principal (Ajouter, Générer, etc.) est en violet
- [ ] Le jour actuel a une bordure violette subtile
- [ ] Aucun texte n'est en dessous de #9494A0 sur un fond en dessous de #26262D

Commit et pousse sur `feat/violet-identity`.
