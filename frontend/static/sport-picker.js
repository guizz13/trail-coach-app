/* SENSEI — catalogue des sports et sélecteur réutilisable (bottom sheet « Quel sport ? ») */
"use strict";

// Catalogue chargé une fois par page (backend/sports.py) : catégories, sports, 6 derniers utilisés
let CATALOGUE = null;
const CATALOGUE_PRET = api("GET", "/api/sports").then(c => {
  CATALOGUE = { ...c, parId: Object.fromEntries(c.sports.map(s => [s.id, s])) };
  return CATALOGUE;
}).catch(() => null);

const SPORT_AUTRE = { id: "autre", libelle: "Autre sport", categorie: "autre", impact: "modere", icone: "ti-activity", distance: false };
const sportInfo = id => (CATALOGUE && CATALOGUE.parId[id]) || SPORT_AUTRE;
const libelleCategorie = cat => (CATALOGUE && CATALOGUE.categories[cat]?.libelle) || cat;
// Pastille d'icône : couleur de la catégorie, icône du sport
const iconeSport = id => { const s = sportInfo(id); return `<span class="disc ${esc(s.categorie)}"><i class="ti ${esc(s.icone)}"></i></span>`; };

// Recherche insensible à la casse et aux accents
const sansAccents = t => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Pastille « Sport à préciser » (cartes de séance) : choix du sport, puis analyse suspendue relancée
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-preciser-id]");
  if (!b) return;
  e.preventDefault();
  e.stopPropagation();                 // la carte elle-même ouvre le détail
  const id = await choisirSport({ sousTitre: "Mémorisé pour les prochains fichiers avec ce code." });
  if (!id) return;
  b.textContent = "Analyse…";
  try {
    await api("POST", `/api/seances_realisees/${b.dataset.preciserId}/sport`, { sport_id: id });
    location.reload();
  } catch (err) { b.textContent = "Sport à préciser"; alert(err.message); }
}, true);

// Ouvre la feuille et résout avec l'id choisi (null si fermée sans choix).
// opts : { titre, sousTitre, propose (sport_id), categorie (catégorie proposée sans sport précis) }
async function choisirSport(opts = {}) {
  const cat = await CATALOGUE_PRET;
  if (!cat) return null;
  return new Promise(resoudre => {
    // Résolution immédiate au choix : l'événement close peut être différé (onglet en arrière-plan)
    let fini = false;
    const terminer = v => { if (!fini) { fini = true; resoudre(v); } };
    const d = feuille(`<h2>${esc(opts.titre || "Quel sport ?")}</h2>
      ${opts.sousTitre ? `<p class="secondaire" style="margin:0 0 10px">${esc(opts.sousTitre)}</p>` : ""}
      <input type="search" class="picker-recherche" placeholder="Rechercher un sport" autocomplete="off">
      <div class="picker-liste"></div>`, "feuille-sport");
    const liste = $(".picker-liste", d), champ = $(".picker-recherche", d);

    const ligne = s => `<button type="button" class="picker-sport ${s.id === opts.propose ? "propose" : ""}" data-id="${esc(s.id)}">
      ${iconeSport(s.id)}<span>${esc(s.libelle)}</span>${s.id === opts.propose ? `<span class="badge accent">proposé</span>` : ""}</button>`;
    const groupe = (titre, sports, id = "") => sports.length
      ? `<div class="section-label" ${id ? `data-cat="${esc(id)}"` : ""}>${esc(titre)}</div>${sports.map(ligne).join("")}` : "";

    function dessiner() {
      const q = sansAccents(champ.value.trim());
      if (q) {
        const trouves = cat.sports.filter(s => sansAccents(s.libelle).includes(q) || sansAccents(s.id).includes(q));
        liste.innerHTML = trouves.length ? trouves.map(ligne).join("") : `<div class="vide">Aucun sport ne correspond. Choisir « Autre sport ».</div>${ligne(SPORT_AUTRE)}`;
        return;
      }
      const propose = opts.propose && cat.parId[opts.propose];
      const recents = (cat.recents || []).filter(id => id !== opts.propose).map(id => cat.parId[id]).filter(Boolean);
      // La catégorie proposée (ex. raquette sans sport précis) passe en tête
      const ordre = Object.keys(cat.categories).sort((a, b) => (b === opts.categorie) - (a === opts.categorie));
      liste.innerHTML = (propose ? groupe("Proposition", [propose]) : "") + groupe("Récents", recents)
        + ordre.map(c => groupe(cat.categories[c].libelle + (c === opts.categorie ? " · proposé" : ""),
          cat.sports.filter(s => s.categorie === c), c)).join("");
    }
    dessiner();
    champ.addEventListener("input", dessiner);
    liste.addEventListener("click", e => {
      const b = e.target.closest("[data-id]");
      if (!b) return;
      terminer(b.dataset.id);
      d.close();
    });
    d.addEventListener("close", () => terminer(null), { once: true });
  });
}

// ---------------------------------------------------------------------------
// Brouillons de formulaires (localStorage, peut être indisponible : navigation privée, quota)
// ---------------------------------------------------------------------------
const CLE_BROUILLON_SEANCE = "brouillon_seance_manuelle";
function lireBrouillon(cle) {
  try { return JSON.parse(localStorage.getItem(cle) || "null"); } catch { return null; }
}
function ecrireBrouillon(cle, valeur) {
  try { localStorage.setItem(cle, JSON.stringify(valeur)); } catch { /* stockage indisponible */ }
}
function effacerBrouillon(cle) {
  try { localStorage.removeItem(cle); } catch { /* stockage indisponible */ }
}

// ---------------------------------------------------------------------------
// Saisie manuelle d'une séance réalisée (sans fichier)
// ---------------------------------------------------------------------------
// opts : { date (ISO jour par défaut), sante ({niveau}) }. Résout avec la réponse de l'API, ou null.
async function feuilleSeanceManuelle(opts = {}) {
  await CATALOGUE_PRET;
  const maintenantLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const debut = opts.date && opts.date !== maintenantLocal.slice(0, 10) ? `${opts.date}T18:00` : maintenantLocal;
  const douleurOuverte = opts.sante && opts.sante.niveau && opts.sante.niveau !== "100";
  let sportId = (CATALOGUE?.recents || [])[0] || null;

  return new Promise(resoudre => {
    let fini = false;
    const terminer = v => { if (!fini) { fini = true; resoudre(v); } };
    const d = feuille(`<h2>Séance réalisée</h2>
      <form id="saisie">
        <label>Sport</label>
        <button type="button" class="picker-sport" data-sport></button>
        <div class="champs-2">
          <div><label>Début</label><input type="datetime-local" name="debut" value="${debut}" required></div>
          <div><label>Durée (min)</label><input type="number" name="duree_min" min="1" max="1440" inputmode="numeric" required></div>
        </div>
        <label>Effort ressenti (RPE) : <b data-rpe>5</b>/10</label>
        <input type="range" name="rpe" min="1" max="10" value="5">
        <div class="champs-2">
          <div><label>FC moyenne (facultatif)</label><input type="number" name="fc_moy" min="30" max="230" inputmode="numeric"></div>
        </div>
        <div class="champs-2" data-distance>
          <div><label>Distance (km)</label><input name="distance_km" inputmode="decimal"></div>
          <div><label>D+ (m)</label><input name="dplus_m" inputmode="numeric"></div>
        </div>
        <details ${douleurOuverte ? "open" : ""}><summary><i class="ti ti-plus"></i> Douleur</summary>
          <div class="champs-2" style="margin-top:8px">
            <div><label>Douleur (0-10)</label><input type="number" name="douleur" min="0" max="10" inputmode="numeric"></div>
            <div><label>Zone</label><select name="douleur_zone"><option value="">—</option>${ZONES_SANTE.map(z => `<option>${esc(z)}</option>`).join("")}</select></div>
          </div>
        </details>
        <label>Note</label><textarea name="note" rows="2"></textarea>
        <label class="coche" style="margin-top:10px"><input type="checkbox" name="analyser" checked>Analyser avec le coach</label>
        <button type="submit" class="btn principal" style="margin-top:14px">Enregistrer</button>
        <div data-erreur></div>
      </form>`);
    const form = $("#saisie", d), boutonSport = $("[data-sport]", form);
    const rendreSport = () => {
      boutonSport.innerHTML = sportId ? `${iconeSport(sportId)}<span>${esc(sportInfo(sportId).libelle)}</span><i class="ti ti-chevron-down muted"></i>`
        : `<span class="disc autre"><i class="ti ti-help"></i></span><span>Choisir un sport</span><i class="ti ti-chevron-down muted"></i>`;
      $("[data-distance]", form).classList.toggle("hidden", !sportId || !sportInfo(sportId).distance);
    };
    rendreSport();
    // Le sélecteur s'ouvre par-dessus la saisie (feuille empilée)
    boutonSport.onclick = async () => {
      const choix = await choisirSport({ propose: sportId });
      if (choix) { sportId = choix; rendreSport(); ecrireBrouillon(CLE_BROUILLON_SEANCE, { ...(lireBrouillon(CLE_BROUILLON_SEANCE) || {}), sport_id: choix }); }
    };
    $("[name=rpe]", form).oninput = e => { $("[data-rpe]", form).textContent = e.target.value; };
    // Brouillon : la saisie survit à un changement d'onglet ou à la mise en veille de l'app
    const brouillon = lireBrouillon(CLE_BROUILLON_SEANCE);
    if (brouillon) {
      if (brouillon.sport_id && CATALOGUE?.parId[brouillon.sport_id]) sportId = brouillon.sport_id;
      Object.entries(brouillon.champs || {}).forEach(([k, v]) => { if (form.elements[k] && form.elements[k].type !== "checkbox") form.elements[k].value = v; });
      $("[data-rpe]", form).textContent = form.rpe.value;
      rendreSport();
    }
    const sauver = () => ecrireBrouillon(CLE_BROUILLON_SEANCE,
      { sport_id: sportId, champs: Object.fromEntries([...new FormData(form)].filter(([k]) => k !== "analyser")) });
    form.addEventListener("input", sauver);
    form.addEventListener("change", sauver);
    form.onsubmit = async e => {
      e.preventDefault();
      if (!sportId) { erreurSimple($("[data-erreur]", form), new Error("Choisir un sport.")); return; }
      const fd = new FormData(form), corps = { sport_id: sportId, analyser: fd.get("analyser") === "on" };
      ["debut", "duree_min", "rpe", "fc_moy", "distance_km", "dplus_m", "douleur", "douleur_zone", "note"]
        .forEach(k => { const v = fd.get(k); if (v !== null && v !== "") corps[k] = v; });
      const bouton = $("button[type=submit]", form);
      bouton.disabled = true;
      bouton.textContent = corps.analyser ? "Analyse en cours…" : "Enregistrement…";
      try {
        const resultat = await api("POST", "/api/seances_realisees", corps);
        effacerBrouillon(CLE_BROUILLON_SEANCE);
        terminer(resultat);
        d.close();
      } catch (err) {
        bouton.disabled = false;
        bouton.textContent = "Enregistrer";
        erreurSimple($("[data-erreur]", form), err);
      }
    };
    d.addEventListener("close", () => terminer(null), { once: true });
  });
}
