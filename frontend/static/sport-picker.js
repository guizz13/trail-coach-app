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

// Ouvre la feuille et résout avec l'id choisi (null si fermée sans choix).
// opts : { titre, sousTitre, propose (sport_id), categorie (catégorie proposée sans sport précis) }
async function choisirSport(opts = {}) {
  const cat = await CATALOGUE_PRET;
  if (!cat) return null;
  return new Promise(resoudre => {
    let choisi = null;
    const d = feuille(`<h2>${esc(opts.titre || "Quel sport ?")}</h2>
      ${opts.sousTitre ? `<p class="secondaire" style="margin:0 0 10px">${esc(opts.sousTitre)}</p>` : ""}
      <input type="search" class="picker-recherche" placeholder="Rechercher un sport" autocomplete="off">
      <div class="picker-liste"></div>`);
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
      choisi = b.dataset.id;
      d.close();
    });
    d.addEventListener("close", () => resoudre(choisi), { once: true });
  });
}
