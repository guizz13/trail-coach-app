# SENSEI — Correctif v4 : charge, liaison des séances, édition, pastilles

Branche : `fix/charge-v4` (depuis `main`). Un commit par section. Lance les tests à chaque section. Pousse sur origin à la fin, pas de merge sur `main` sans validation de Guillaume.

Lis toutes les sections avant de commencer : les sections 1 à 3 changent les calculs que les sections 4 et 5 réutilisent.

---

## 0. Diagnostic (pour comprendre ce qu'on corrige)

Cinq causes expliquent les fausses alertes et le bug du mercredi.

1. **La charge d'une séance est l'EPOC Suunto, additionné.** L'EPOC est un pic d'excès d'oxygène, pas une dose cumulable. 35 min de squash en Z4-Z5 donnent un EPOC énorme ; additionnés sur 7 jours, ça explose la charge aiguë.
2. **L'ACWR est calculé sur des semaines vides.** La charge chronique = moyenne des 4 semaines précédentes. Avec un historique qui démarre mi-septembre, 2 à 3 de ces semaines valent 0, donc la chronique est minuscule et le ratio monte à 4 ou 7. Ce n'est pas un signal, c'est un artefact.
3. **L'ACWR sert de verdict à chaque séance.** Un indicateur de tendance sur 4 semaines n'a pas à rendre une séance individuelle « alerte ». Une EF de 35 min ne peut pas être rouge à cause d'un ratio.
4. **La règle « deux oranges = rouge » (prompt section 9)** et des seuils de zones appliqués au squash multiplient les rouges.
5. **La liaison réalisé ↔ prévu ignore la discipline.** La course de lundi a été liée à « Pull A » (muscu prévue lundi). Résultat : la muscu de mercredi n'a plus de séance prévue disponible, elle apparaît « hors plan », et la muscu prévue mercredi passe « manqué ».

Point d'honnêteté à garder en tête : une fois le calcul corrigé, l'ACWR restera un vrai garde-fou. Quand Guillaume repassera d'un volume de rééducation à des semaines plus longues, le ratio montera légitimement vers 1,3-1,5 si la reprise est trop rapide. On supprime les artefacts, pas le signal.

---

## 1. Liaison réalisé ↔ prévu par famille de discipline

Section en premier car c'est le bug visible (« manqué » à tort).

### 1.1 Familles

Dans `backend/services.py` (ou un nouveau `backend/liaison.py`), définis :

```python
FAMILLES = {
    "course": {"EF", "intervals", "cotes", "tempo", "sortie_longue", "course"},
    "muscu":  {"muscu", "muscu_push", "muscu_pull", "muscu_jambes", "muscu_full"},
    "squash": {"squash"},
    "velo":   {"velo", "velo_ef", "velo_intervals"},
}

def famille(type_seance: str) -> str | None:
    for f, types in FAMILLES.items():
        if type_seance in types:
            return f
    return None
```

Le type réalisé vient de l'extracteur : ActivityType 3 et 93 donnent `course`, 23 donne `muscu`, 37 donne `squash`, 17 donne `velo`. Une séance réalisée ne peut être liée qu'à une séance prévue de la même famille. Une muscu réalisée (type 23) peut se lier à n'importe quelle muscu prévue du jour (push, pull, jambes) : la montre ne sait pas ce qui a été fait.

### 1.2 Algorithme de liaison automatique

Pour chaque séance réalisée non liée manuellement :

1. Candidats = séances prévues **même date**, **même famille**, pas déjà liées.
2. Créneau de la séance réalisée selon l'heure de début : avant 11h = matin, 11h-14h = midi, 14h-17h = après-midi, après 17h = soir.
3. Si plusieurs candidats, choisir celui dont le créneau correspond ; sinon le plus proche dans l'ordre matin, midi, après-midi, soir.
4. Aucun candidat : la séance est `hors_plan`. Pas de liaison sur une autre date en automatique.

Traiter les séances réalisées dans l'ordre chronologique, pour que deux séances du même jour ne se disputent pas le même prévu.

### 1.3 Statut des séances prévues

- `realise` : une séance réalisée y est liée.
- `manque` : date strictement antérieure à aujourd'hui (fuseau Europe/Paris) et aucune séance liée.
- `a_faire` : date aujourd'hui ou future, rien de lié.

Aujourd'hui n'est jamais « manqué ».

### 1.4 Liaison manuelle : boutons Lier / Délier

Schéma (migration idempotente dans `db.py`) :

```sql
ALTER TABLE seances_realisees ADD COLUMN lien_manuel INTEGER NOT NULL DEFAULT 0;
```

(`seance_planifiee_id` existe déjà ; sinon, l'ajouter en nullable.)

Endpoints :
- `POST /api/seances_realisees/{id}/lier` body `{"seance_planifiee_id": int}` : vérifie même famille et même semaine (lundi-dimanche), pose `lien_manuel=1`, recalcule le verdict.
- `POST /api/seances_realisees/{id}/delier` : met `seance_planifiee_id=NULL`, `lien_manuel=1` (pour que la liaison auto ne la recolle pas), verdict `hors_plan`.

Frontend, dans le détail d'une séance réalisée :
- Si liée : ligne « Liée à : Pull A (mer. matin) » + bouton secondaire « Délier ».
- Si hors plan : bouton « Lier à une séance prévue » qui ouvre une liste des séances prévues non liées de la même famille dans la semaine. Tap = lien.

La liaison automatique ne touche jamais une séance avec `lien_manuel=1`.

### 1.5 Recalcul admin

La route admin de recalcul existante doit : remettre à zéro les liaisons où `lien_manuel=0`, relancer la liaison automatique sur tout l'historique, puis recalculer charges (section 2), ACWR (section 3) et verdicts (section 4). Elle n'appelle pas le LLM.

### 1.6 Tests

- Semaine du 28 sept. : lundi course réalisée + Pull A prévue lundi : la course ne se lie pas à Pull A. Mercredi muscu réalisée : liée à la muscu prévue mercredi, statut `realise`.
- Deux séances le même jour (muscu matin + squash soir) : chacune liée à la bonne.
- Séance avec `lien_manuel=1` : intacte après recalcul admin.

---

## 2. Charge d'une séance : TRIMP Edwards au lieu de l'EPOC

Dans `backend/metrics.py`, remplace `charge_seance`.

```python
POIDS_ZONES = {"Z1": 1, "Z2": 2, "Z3": 3, "Z4": 4, "Z5": 5}

def charge_seance(seance) -> float:
    """TRIMP d'Edwards : somme des minutes passées dans chaque zone × poids de la zone."""
    zones = seance.zones_minutes  # dict {"Z1": min, ..., "Z5": min}
    if zones and sum(zones.values()) > 0:
        return round(sum(POIDS_ZONES[z] * m for z, m in zones.items()), 1)
    return round(seance.duree_min * 2, 1)  # pas de FC : hypothèse Z2 moyenne
```

Notes :
- Les zones viennent de `_calculer_zones` (FCmax 191). Le temps sous Z1 compte en Z1.
- L'EPOC reste stocké et affiché dans le détail de séance, mais il ne participe plus à aucun calcul de charge.
- Une colonne `charge` (REAL) est recalculée pour toutes les séances existantes par le recalcul admin.

Ordre de grandeur attendu : EF de 45 min en Z2 ≈ 90 ; squash de 60 min majoritairement Z4 ≈ 220 ; sortie longue de 3 h ≈ 400-500. Le squash pèse lourd et c'est voulu : c'est une vraie charge.

Test : séance squash 35 min dont 20 min Z4 et 10 min Z5 donne une charge ≈ 140-150, et ne génère plus de rouge à elle seule (section 4).

---

## 3. ACWR : EWMA + période de calibrage

### 3.1 Calcul

Remplace `calculer_acwr` par une moyenne mobile exponentielle (Williams et al. 2017), calculée jour par jour sur la charge quotidienne totale (toutes disciplines, 0 les jours sans séance).

```python
LAMBDA_AIGU = 2 / (7 + 1)      # 0,25
LAMBDA_CHRONIQUE = 2 / (28 + 1)  # ≈ 0,069

def serie_acwr(charges_par_jour: list[tuple[date, float]]) -> list[dict]:
    aigu = chronique = None
    serie = []
    for jour, charge in charges_par_jour:      # jours consécutifs, sans trou
        if aigu is None:
            aigu = chronique = charge
        else:
            aigu = aigu + LAMBDA_AIGU * (charge - aigu)
            chronique = chronique + LAMBDA_CHRONIQUE * (charge - chronique)
        ratio = aigu / chronique if chronique and chronique > 1 else None
        serie.append({"date": jour, "aigu": aigu, "chronique": chronique, "ratio": ratio})
    return serie
```

La série démarre au jour de la première séance importée, puis remplit chaque jour jusqu'à aujourd'hui (0 si rien).

### 3.2 Calibrage

Le ratio n'est affiché et utilisé que si l'historique est fiable :

- la première séance importée date d'au moins 21 jours,
- et aucun trou de plus de 10 jours consécutifs sans séance dans les 28 derniers jours.

Sinon, statut `calibrage`. Pendant le calibrage :
- Semaine et Stats : jauge grisée, libellé « Calibrage · J X/21 », pas de valeur ni de couleur.
- Le ratio n'est pas transmis au LLM.
- Aucun verdict ni message ne peut s'appuyer dessus.

Avec un historique qui commence le 15 sept., le calibrage se termine autour du 6 oct.

### 3.3 Zones

| Statut | Ratio | Couleur |
|---|---|---|
| calibrage | — | gris (`--text-muted`) |
| sous_charge | < 0,8 | gris-violet (`--accent-light` à 60 %), pas rouge |
| optimal | 0,8 – 1,3 | vert |
| vigilance | 1,3 – 1,5 | orange |
| danger | > 1,5 | rouge |

La sous-charge n'est pas un danger en rééducation : pas de rouge à gauche de la jauge. Modifie la jauge de la carte « Équilibre de charge » : dégradé gris → vert → orange → rouge (plus de rouge à gauche).

### 3.4 Graphique Stats

Le graphique « Équilibre de charge » trace la série quotidienne (un point par jour, ligne), pas un point unique. Axe Y fixe 0 – 2, valeurs au-delà écrêtées à 2 avec un marqueur. Bandes de fond : vert 0,8-1,3, orange 1,3-1,5, rouge > 1,5. Les jours en calibrage ne sont pas tracés ; afficher « Calibrage en cours » à la place si aucun point.

### 3.5 Tests

- Historique de 17 jours : statut `calibrage`, ratio non exposé par l'API.
- 6 semaines régulières à charge constante : ratio ≈ 1,0.
- Semaine doublée après 4 semaines stables : ratio entre 1,3 et 1,6 (signal réel conservé).

---

## 4. Verdict de séance découplé de l'ACWR

Dans `metrics.evaluer_seance`, retire le paramètre `acwr`. Nouvelle signature :

```python
def evaluer_seance(realise, prevu, sante, prochaine_qualite_dans_h) -> tuple[str, list[str]]:
```

### 4.1 Verdicts possibles

- `conforme` (vert)
- `ecart` (orange)
- `alerte` (rouge)
- `hors_plan` (gris neutre) : aucune séance prévue liée. Pas de seuil appliqué, pas de couleur d'alerte, sauf signal de sécurité (4.3).

### 4.2 Signaux orange (orange maximum, jamais rouge seuls ou cumulés)

Course uniquement (les seuils de zones ne s'appliquent jamais au squash, à la muscu ni au vélo) :
- EF prévue : temps en Z3 et au-dessus > 25 %.
- Sortie longue prévue : temps en Z4-Z5 > 30 %.
- Intervals prévus : temps en Z4-Z5 < 8 % (séance qualité ratée, pas dangereuse).

Toutes disciplines :
- Écart de durée ou de distance vs prévu > 25 %.

### 4.3 Signaux rouges (sécurité uniquement)

- Douleur déclarée ≥ 4/10 sur la séance, ou douleur sur une zone en Vigilance/Blessure.
- Séance de course réalisée alors que le statut santé est « Blessure » sur une zone du bas du corps.
- RecoveryTime Suunto > 48 h ET une séance qualité prévue tombe dans cette fenêtre.

Supprime la règle « deux oranges = rouge ».

### 4.4 Analyse LLM

- `analyse_seance` ne reçoit plus l'ACWR dans son contexte.
- Le verdict affiché est celui calculé par le backend. Le LLM peut proposer un verdict, mais le backend garde le plus bas des deux sauf si le LLM cite un signal de sécurité de 4.3. Si le texte de l'analyse LLM mentionne ACWR, ratio ou charge chronique pour justifier une alerte, ignorer son verdict.

### 4.5 Prompt (`prompts/system_prompt_coach.md`)

Remplace la section 9 par :

```markdown
## 9. SEUILS D'ALERTE

Le backend calcule le verdict de chaque séance. Tu le reçois, tu ne le contredis pas sans signal de sécurité.

Orange (ajustement ciblé possible, jamais rouge même cumulés) :
- Course EF : temps ≥ Z3 > 25 %
- Course sortie longue : Z4-Z5 > 30 %
- Course intervals : Z4-Z5 < 8 % (qualité non atteinte)
- Écart de durée ou distance vs prévu > 25 %

Rouge (sécurité uniquement) :
- Douleur ≥ 4/10, ou douleur sur une zone en Vigilance/Blessure
- Course réalisée en statut Blessure bas du corps
- RecoveryTime > 48 h chevauchant une séance qualité

Le squash, la muscu et le vélo n'ont pas de seuils de zones : un squash en Z4-Z5 est normal.
L'ACWR est un indicateur hebdomadaire. Tu ne l'utilises jamais pour juger une séance isolée. Tu ne le commentes que dans le bilan hebdo, et seulement s'il est fourni (absent = calibrage en cours).
```

Dans la section 5, règle dure 6, remplace la définition : « Le ratio ACWR (EWMA aiguë 7 j / chronique 28 j, charge TRIMP toutes disciplines) doit rester entre 0,8 et 1,3 en tendance. Au-delà de 1,5, tu réduis la semaine suivante. Pendant le calibrage, tu raisonnes sur la progression de volume (section 6). »

Dans la section 8, paragraphe Récupération : la phrase sur EPOC devient « RecoveryTime (Suunto) guide la tolérance à la charge suivante. L'EPOC est une information de séance, pas une mesure de charge. »

---

## 5. Modifier la semaine après validation

Deux niveaux : recalcul automatique sans IA à chaque modification, et réajustement IA à la demande.

### 5.1 Endpoints d'édition

- `POST /api/seances_planifiees` (ajout)
- `PATCH /api/seances_planifiees/{id}` (date, créneau, type, durée, distance, description)
- `DELETE /api/seances_planifiees/{id}`

Les dates sont limitées à la semaine en cours. Une séance prévue déjà liée à une séance réalisée ne peut pas être supprimée (proposer « Délier » d'abord).

### 5.2 Recalcul automatique (sans LLM)

Après chaque création, modification ou suppression de séance prévue, et après chaque import ou chaque Lier/Délier, appeler `services.recalculer_semaine(lundi)` :

1. Relance la liaison automatique de la semaine (section 1, en respectant `lien_manuel`).
2. Recalcule les statuts `realise` / `manque` / `a_faire`.
3. Recalcule les verdicts des séances réalisées de la semaine.
4. Recalcule les totaux de la semaine (volume prévu vs réalisé, distribution zones).
5. Pose `plan_modifie = 1` sur la semaine si la modification vient de l'utilisateur.

Ajoute la colonne : `ALTER TABLE imperatifs_semaine ADD COLUMN plan_modifie INTEGER NOT NULL DEFAULT 0;` (ou la table qui porte l'état de la semaine).

Le bilan hebdo suivant (`bilan_hebdo`) reçoit le plan **tel que modifié**, plus la liste des modifications, et pas le plan initial.

### 5.3 Bouton « Réajuster avec Sensei »

Affiché sur l'écran Semaine sous le planning quand `plan_modifie = 1`, ou quand il existe une séance `manque` ou une séance `hors_plan` dans la semaine en cours, et qu'il reste au moins un jour.

Au tap, nouvel appel LLM `ajustement_semaine` :
- Modèle : `claude-sonnet-5`, `max_tokens` 8000, même system prompt (cache).
- Contexte : plan actuel, modifications faites, réalisé de la semaine avec verdicts, statut santé, impératifs, jours restants.
- Le LLM ne renvoie que les jours à partir de demain (ou d'aujourd'hui si rien n'est réalisé aujourd'hui).

Schéma de sortie, à ajouter dans la section 10 du prompt (10.4) :

```json
{
  "jours": [
    {
      "date": "2026-10-03",
      "seances": [
        {"type": "EF", "creneau": "matin", "duree_min": 45, "distance_km": 7,
         "intensite": "Z2", "description": "EF tapis, cadence 170+"}
      ]
    }
  ],
  "changements": ["Pull B déplacée de jeudi à vendredi", "..."],
  "message_coach": "1 à 2 phrases, 30 mots max."
}
```

Consigne du prompt pour 10.4 : « Tu réajustes les jours restants à partir de ce qui a réellement été fait. Tu ne rattrapes jamais mécaniquement une séance manquée. Tu respectes les règles dures. Tu ne touches pas aux jours passés. »

Validation backend avant affichage (règles dures vérifiables en code) :
- au moins 1 jour de repos sur la semaine complète,
- au moins 2 muscu sur la semaine complète,
- course > 1h15 uniquement samedi ou dimanche,
- muscu + course le même jour uniquement le week-end,
- aucune date passée.

Si une règle est violée : un seul nouvel essai avec l'erreur ajoutée au message. Si le second échoue : on garde le plan actuel et on affiche « Sensei n'a pas trouvé d'ajustement valide, ton plan actuel est conservé. »

Affichage : aperçu des changements (liste `changements` + message) avec deux boutons « Appliquer » et « Annuler ». « Appliquer » remplace les séances prévues non liées des jours concernés, puis lance `recalculer_semaine` et remet `plan_modifie = 0`.

Le coût passe par le compteur `usage_llm.json` et respecte le plafond mensuel. Si le plafond est atteint, le bouton est grisé avec « Budget IA du mois atteint ».

### 5.4 Tests

- Modifier la date d'une muscu de mercredi à jeudi : relink immédiat, plus de « manqué » à tort.
- Supprimer une séance prévue liée : refusé.
- Ajustement LLM simulé (mock) qui place une course de 1h30 un mardi : rejeté, nouvel essai déclenché.

---

## 6. Pastilles qui débordent + statut santé structuré

### 6.1 CSS des pastilles

Toutes les pastilles (`.pill`, `.badge`, `.chip`, badge mode, badge santé, badge phase) :

```css
.pill {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
}
.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}
```

Les conteneurs de pastilles (entête Semaine, carte « Position dans la prépa ») utilisent `.pill-row`. Vérifie sur une largeur de 360 px.

### 6.2 Statut santé structuré

Aujourd'hui la note santé libre s'affiche dans la pastille et la fait déborder. Remplace par des champs structurés dans `profil` :

```sql
ALTER TABLE profil ADD COLUMN sante_niveau TEXT NOT NULL DEFAULT '100';   -- '100' | 'vigilance' | 'blessure'
ALTER TABLE profil ADD COLUMN sante_zones TEXT NOT NULL DEFAULT '[]';     -- JSON array
ALTER TABLE profil ADD COLUMN sante_note TEXT;
ALTER TABLE profil ADD COLUMN sante_protocole TEXT;                       -- consignes du kiné
```

Migrer la valeur existante : le texte libre actuel va dans `sante_note`, le niveau est déduit s'il contient « vigilance » ou « blessure ».

Formulaire santé (écran Préparer) :
- Niveau : 3 boutons segmentés (100 % / Vigilance / Blessure).
- Zones : multi-sélection en chips, visibles seulement si Vigilance ou Blessure : Achille G, Achille D, Fascia G, Fascia D, Mollet G, Mollet D, Genou G, Genou D, Hanche, Dos, Épaule, Autre.
- Note libre (optionnelle).
- Protocole kiné (optionnel) : texte libre, avec aide « ex. : course 30 min max, +5 min par semaine si 0 douleur J+1 ».

Pastille courte générée côté backend (`sante_libelle_court`) :
- 100 % : « Santé 100 % » en vert.
- Vigilance : « Vigilance · Achille D+G » en orange (zones regroupées : Achille G + Achille D donne « Achille D+G » ; au-delà de 2 zones, « Vigilance · 3 zones »).
- Blessure : même logique en rouge.

Tap sur la pastille : bottom sheet avec niveau, zones, note et protocole complets.

Le LLM reçoit `<statut_sante>` avec niveau, zones, note et protocole.

### 6.3 Phase de prépa : code fermé + détail

Dans le prompt (sections 10.2 et 10.3), `position_prepa.phase` devient une énumération stricte : `BASE`, `BUILD`, `PIC`, `AFFUTAGE`, `LIBRE`. Ajoute un champ `position_prepa.detail` (texte, 12 mots max) pour toute précision (« reprise post-Achille, semaine 2/4 »).

Backend : si `phase` n'est pas dans l'énumération, tenter une correspondance par mot-clé (« affût » donne AFFUTAGE, « base » ou « reprise » donne BASE, etc.), sinon `LIBRE`, et déplacer le texte d'origine dans `detail`.

Affichage carte « Position dans la prépa » : pastille de phase courte (code) sur la ligne 1, `detail` en texte 12 px `--text-secondary` limité à 2 lignes en dessous, jamais dans la pastille.

---

## 7. Règle de progression en Vigilance

Remplace dans le prompt, section 6, la ligne « Progression de volume plafonnée à +5 %/semaine » par :

```markdown
- Si un protocole kiné est renseigné dans <statut_sante>, il prime sur toute autre règle de progression : tu le suis à la lettre et tu ne le dépasses jamais.
- Sans protocole : progression du volume de course (minutes) plafonnée à +10 % par semaine par rapport à la moyenne des 3 dernières semaines réalisées.
- Toute douleur ≥ 3/10 pendant, après ou le lendemain gèle la progression la semaine suivante.
```

Backend : dans la validation de `bilan_hebdo` et `ajustement_semaine`, si `sante_niveau = 'vigilance'` et pas de protocole, rejeter un plan dont le volume de course prévu dépasse 1,10 × la moyenne des minutes de course des 3 dernières semaines (même mécanique de second essai qu'en 5.3).

---

## 8. Vérifications finales

Après merge local de toutes les sections, lancer le recalcul admin, puis vérifier sur les données réelles :

- [ ] Semaine du 28 sept. : la muscu de mercredi est liée et `realise` ; plus aucune muscu `manque` à tort.
- [ ] La course de lundi n'est plus affichée comme « Pull A ».
- [ ] La carte Équilibre de charge affiche « Calibrage · J X/21 » (historique < 21 jours) ; aucune valeur 4,2 ni zone rouge.
- [ ] Le graphique Stats n'affiche plus un point isolé à 4,2.
- [ ] L'EF du 15 sept. n'est plus en `alerte` (au pire `ecart` ou `hors_plan`).
- [ ] Les squashs n'ont jamais de verdict basé sur les zones.
- [ ] Aucune séance `alerte` sans signal de sécurité (douleur, Blessure, RecoveryTime chevauchant).
- [ ] Modifier une séance prévue relance la liaison et les verdicts sans appel LLM.
- [ ] Le bouton « Réajuster avec Sensei » apparaît après une modification et l'aperçu s'affiche avant application.
- [ ] Pastilles : aucune ne dépasse à 360 px de large ; la pastille santé reste courte.
- [ ] Carte « Position dans la prépa » : code de phase dans la pastille, détail en dessous.
- [ ] Tous les tests passent (`pytest`), y compris les nouveaux.

Commit final, push sur `fix/charge-v4`, puis résume à Guillaume ce qui a changé et ce qui reste à vérifier sur son téléphone.
