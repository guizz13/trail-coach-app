/* SENSEI — page Semaine */
"use strict";

coque();

let tableau = null;          // /api/dashboard (semaine courante)
let lundiAffiche = null;
let bilanOuvert = false;     // carte « Bilan de la semaine » repliée par défaut

async function charger(lundi) {
  try {
    if (!tableau) [tableau] = await Promise.all([api("GET", "/api/dashboard"), CATALOGUE_PRET]);
    lundiAffiche = lundi || tableau.lundi;
    const courante = lundiAffiche === tableau.lundi;
    const dimanche = ajouterJours(lundiAffiche, 6);
    const [jours, realisees, bilan] = await Promise.all([
      courante ? tableau.semaine : api("GET", `/api/semaine?lundi=${lundiAffiche}`),
      api("GET", `/api/seances?du=${lundiAffiche}&au=${dimanche}`),
      courante ? tableau.bilan_semaine : api("GET", `/api/bilan_semaine?lundi=${lundiAffiche}`),
    ]);
    // Verdict stocké sur chaque séance réalisée (recalculé à chaque changement)
    const verdicts = Object.fromEntries(realisees.map(s => [s.id, s.verdict]));
    rendreEntete(dimanche);
    rendreBilanSemaine(bilan);
    rendrePlanning(jours, realisees, verdicts);
    rendreReajuster(courante);
    if (courante) reprendreAjustement().catch(() => {});
    $("#ajouter").classList.toggle("hidden", !courante);   // ajout : semaine en cours uniquement
    $("#ajouter-realisee").classList.toggle("hidden", !courante);
    $("#preparer-suivante").classList.toggle("hidden", !courante);
  } catch (e) { erreurSimple($("#planning"), e); }
}

function rendreEntete(dimanche) {
  const memeMois = lundiAffiche.slice(5, 7) === dimanche.slice(5, 7);
  $("#titre-semaine").textContent = `Semaine du ${dateFR(lundiAffiche, memeMois ? { day: "numeric" } : { day: "numeric", month: "short" })} — ${dateFR(dimanche, { day: "numeric", month: "short" })}`;
}

// ---- Bilan de la semaine : réalisé / prévu par catégorie (carte partagée, app.js) ---------------
// Repliée par défaut : seule la ligne de synthèse (statut, séances faites) reste visible
function rendreBilanSemaine(b) {
  const html = bilanSemaineHTML(b), el = $("#bilan-semaine");
  if (!html) { el.innerHTML = ""; return; }
  const [classe, texte] = statutSemaine(b);
  el.innerHTML = `<details class="bilan-replie" ${bilanOuvert ? "open" : ""}>
      <summary><span class="section-label" style="margin:0">Bilan de la semaine</span>
        <span class="ligne" style="gap:6px">${b.seances.prevues ? `<span class="sous-texte">${b.seances.faites}/${b.seances.prevues}</span>` : ""}
        <span class="badge ${classe}">${esc(texte)}</span><i class="ti ti-chevron-down muted"></i></span></summary>
      ${html}</details>`;
  $("details", el).ontoggle = e => { bilanOuvert = e.target.open; };
}

// Ouverture : défilement vers le jour demandé (#2026-10-07, depuis Aujourd'hui) ou vers aujourd'hui
function defilerVersJour(iso) {
  const carte = document.getElementById(`jour-${iso}`);
  if (carte) carte.scrollIntoView({ block: "start" });
}

function rendrePlanning(jours, realisees, verdicts) {
  const parId = Object.fromEntries(realisees.map(s => [s.id, s]));
  // Séance décalée : la prévue reste à sa date (« Décalée à dimanche »), la réalisée s'affiche à la sienne
  const prevueDe = Object.fromEntries(jours.flatMap(j => j.planifiees).filter(p => p.seance_realisee_id).map(p => [p.seance_realisee_id, p]));
  const jourDe = iso => dateFR(iso, { weekday: "long" });
  const el = $("#planning");
  el.innerHTML = "";
  for (const j of jours) {
    const carte = document.createElement("div");
    carte.className = "jour" + (j.date === tableau.aujourdhui ? " aujourdhui" : "");
    carte.id = `jour-${j.date}`;
    carte.innerHTML = `<div class="jour-titre"><b>${esc(j.jour)} ${esc(dateFR(j.date, { day: "numeric" }))}</b>
      ${j.date === tableau.aujourdhui ? "<span>aujourd'hui</span>" : ""}</div>`;
    for (const p of j.planifiees) {
      const r = p.seance_realisee_id ? parId[p.seance_realisee_id] : null;
      const decalee = r && r.date_debut.slice(0, 10) !== p.date_seance;
      const b = document.createElement("button");
      b.className = "seance";
      const remplacante = p.remplacee_par ? parId[p.remplacee_par] : null;
      b.innerHTML = decalee ? seanceHTML(p, null, null, { statut: `Décalée à ${jourDe(r.date_debut.slice(0, 10))}` })
        : remplacante ? seanceHTML(p, null, null, { statut: `Remplacée par ${sportInfo(remplacante.sport_id).libelle.toLowerCase()}` })
        : seanceHTML(p, r, r && verdicts[r.id]);
      b.onclick = () => editer(p, r);
      carte.appendChild(b);
    }
    // Réalisées ce jour-là : hors plan, ou liées à une séance prévue un autre jour
    const aAfficher = realisees.filter(r => r.date_debut.slice(0, 10) === j.date
      && (!prevueDe[r.id] || prevueDe[r.id].date_seance !== j.date));
    for (const r of aAfficher) {
      const p = prevueDe[r.id];
      const b = document.createElement("button");
      b.className = "seance";
      const mention = p ? `prévue ${jourDe(p.date_seance)}`
        : (r.remplace || []).length ? `remplace ${r.remplace.map(libelleCourt).join(", ")}` : null;
      b.innerHTML = seanceHTML(null, r, verdicts[r.id], mention ? { mention } : {});
      b.onclick = () => ouvrirSeance(r.id, { apresChangement: recharger });
      carte.appendChild(b);
    }
    if (!j.planifiees.length && !aAfficher.length) carte.insertAdjacentHTML("beforeend", `<div class="jour-vide">Rien de prévu</div>`);
    el.appendChild(carte);
  }
}

// ---- Édition d'une séance planifiée (feuille) --------------------------------
// Modifiable uniquement dans la semaine en cours ; le statut est recalculé (jamais saisi)
const dansSemaineCourante = iso => tableau && iso >= tableau.lundi && iso <= ajouterJours(tableau.lundi, 6);

function editer(p, realisee) {
  if (p.id && !dansSemaineCourante(p.date_seance)) {
    feuille(`<h2>${esc(libelleType(p.type))}</h2>
      <div class="sous-texte">${esc(dateFR(p.date_seance, { weekday: "long", day: "numeric", month: "long" }))} · ${esc(CRENEAUX[p.creneau] || p.creneau)} · ${esc(STATUTS[p.statut] || p.statut)}</div>
      ${p.detail ? `<p class="secondaire">${esc(p.detail)}</p>` : ""}
      ${realisee ? `<button type="button" class="btn petit" style="margin-top:10px" data-voir-realisee><i class="ti ti-chart-line"></i>Voir la séance réalisée</button>` : ""}
      <div class="sous-texte" style="margin-top:12px">Seules les séances de la semaine en cours se modifient.</div>`);
    const v = $("#feuille [data-voir-realisee]");
    if (v) v.onclick = () => ouvrirSeance(realisee.id, { apresChangement: recharger });
    return;
  }
  const types = TYPES_PLANIFIABLES.includes(p.type) ? TYPES_PLANIFIABLES : [p.type, ...TYPES_PLANIFIABLES];
  const optTypes = v => types.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(libelleType(x))}</option>`).join("");
  const opt = (liste, v, lib = {}) => liste.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lib[x] || x)}</option>`).join("");
  const d = feuille(`<h2>${p.id ? "Modifier la séance" : "Nouvelle séance"}</h2>
    ${p.version ? `<div class="sous-texte">version ${p.version} · ${esc(p.origine || "")} · ${esc(STATUTS[p.statut] || p.statut)}</div>` : ""}
    ${realisee ? `<button type="button" class="btn petit" style="margin-top:10px" data-voir-realisee><i class="ti ti-chart-line"></i>Voir la séance réalisée</button>` : ""}
    <form>
      <div class="champs-2">
        <div><label>Date</label><input type="date" name="date_seance" value="${esc(p.date_seance)}" min="${tableau.lundi}" max="${ajouterJours(tableau.lundi, 6)}" required></div>
        <div><label>Créneau</label><select name="creneau">${opt(Object.keys(CRENEAUX), p.creneau || "matin", CRENEAUX)}</select></div>
      </div>
      <label>Type</label>
      <div class="ligne"><select name="type" style="flex:1">${optTypes(p.type || "EF")}</select>
        <button type="button" class="btn petit" data-autre-sport><i class="ti ti-search"></i>Sport</button></div>
      <div class="champs-2">
        <div><label>Durée (min)</label><input type="number" inputmode="numeric" name="duree_min" value="${esc(p.duree_min ?? "")}"></div>
        <div><label>Distance (km)</label><input type="number" inputmode="decimal" step="0.1" name="distance_km" value="${esc(p.distance_km ?? "")}"></div>
      </div>
      <label>Description</label><textarea name="detail">${esc(p.detail ?? "")}</textarea>
      <label>Intensité</label><input name="intensite" value="${esc(p.intensite ?? "")}">
      <div class="erreur"></div>
      <div class="boutons">${p.id ? `<button type="button" class="btn danger" data-suppr>Supprimer</button>` : ""}
        <button type="submit" class="btn principal">Enregistrer</button></div>
    </form>`);
  // Tout sport du catalogue se planifie (badminton, natation…) : le type devient l'id du sport
  $("[data-autre-sport]", d).onclick = async () => {
    const id = await choisirSport({ titre: "Sport prévu" });
    if (!id) return;
    const select = $("[name=type]", d);
    if (![...select.options].some(o => o.value === id)) select.insertAdjacentHTML("afterbegin", `<option value="${esc(id)}">${esc(libelleType(id))}</option>`);
    select.value = id;
  };
  const voir = $("[data-voir-realisee]", d);
  if (voir) voir.onclick = () => ouvrirSeance(realisee.id, { apresChangement: recharger });
  $("form", d).onsubmit = async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    try {
      if (p.id) await api("PATCH", `/api/seances_planifiees/${p.id}`, v); else await api("POST", "/api/seances_planifiees", v);
      d.close(); recharger();
    } catch (err) { erreurSimple($(".erreur", d), err); }
  };
  const s = $("[data-suppr]", d);
  if (s) s.onclick = async () => {
    if (!confirm("Supprimer cette séance ?")) return;
    try { await api("DELETE", `/api/seances_planifiees/${p.id}`); d.close(); recharger(); }
    catch (err) { erreurSimple($(".erreur", d), err); }    // liée : « délie-la d'abord »
  };
}

// ---- Réajuster avec Sensei (LLM, à la demande) ------------------------------------------------------------
const MESSAGES_AJUSTEMENT = ["Sensei relit ta semaine...", "Prise en compte du réalisé...", "Vérification des règles...", "Réajustement des jours restants..."];

function rendreReajuster(courante) {
  const el = $("#reajuster"), a = tableau.ajustement, c = tableau.cout_llm;
  if (!courante || !a || !a.possible) { el.innerHTML = ""; return; }
  const budget = c.cout_usd >= c.plafond_usd;
  el.innerHTML = `<button type="button" class="btn" id="btn-reajuster" style="margin-top:8px" ${budget ? "disabled" : ""}>
      <i class="ti ti-wand"></i>${budget ? "Budget IA du mois atteint" : "Réajuster avec Sensei"}</button>
    <div class="sous-texte" style="text-align:center;margin-top:4px">${esc(a.raisons.join(" · "))}</div>
    <div id="apercu-ajustement"></div>`;
  if (!budget) $("#btn-reajuster").onclick = reajuster;
}

async function reajuster() {
  const zone = $("#apercu-ajustement"), bouton = $("#btn-reajuster");
  bouton.disabled = true;
  chargeurIA(zone, MESSAGES_AJUSTEMENT);
  try { suivreAjustement(await api("POST", "/api/semaine/ajuster", {})); }
  catch (e) { zone.innerHTML = ""; zone.appendChild(carteErreurLLM({ type: "reseau", message: e.message }, reajuster)); bouton.disabled = false; }
}

// Réajustement en tâche de fond : repris au retour sur la page (en cours, ou prêt et pas encore vu)
function suivreAjustement(tache) {
  const zone = $("#apercu-ajustement"), bouton = $("#btn-reajuster");
  if (!zone || !bouton) return;
  bouton.disabled = true;
  tacheDansZone(zone, tache, MESSAGES_AJUSTEMENT, r => afficherAjustement(r));
}

async function reprendreAjustement() {
  if (lundiAffiche !== tableau.lundi || !$("#btn-reajuster")) return;
  const [t] = await api("GET", `/api/taches?cle=ajustement_semaine:${tableau.lundi}`);
  if (t && (t.statut === "en_cours" || !t.vue)) suivreAjustement(t);
}

function afficherAjustement(r) {
  const zone = $("#apercu-ajustement"), bouton = $("#btn-reajuster");
  try {
    if (!r.ok) { zone.innerHTML = `<div class="bandeau gris">${esc(r.message)}</div>`; bouton.disabled = false; return; }
    zone.innerHTML = `${messageCoach(r.message_coach, "Proposition de Sensei")}
      <div class="carte" style="margin-top:8px"><div class="metrique"><span class="label">Changements</span></div>
        ${(r.changements || []).map(x => `<div class="seance-detail" style="-webkit-line-clamp:unset;margin-top:6px">· ${esc(x)}</div>`).join("") || `<div class="vide">Aucun changement listé.</div>`}
      </div>
      <div class="boutons"><button type="button" class="btn" data-annuler>Annuler</button><button type="button" class="btn principal" data-appliquer>Appliquer</button></div>`;
    $("[data-annuler]", zone).onclick = () => { zone.innerHTML = ""; bouton.disabled = false; };
    $("[data-appliquer]", zone).onclick = async () => {
      try { await api("POST", `/api/semaine/ajustements/${r.analyse_id}/appliquer`); recharger(); }
      catch (e) { erreurSimple(zone, e); }
    };
  } finally { if (!zone.querySelector("[data-appliquer]")) bouton.disabled = false; }
}

function recharger() { const l = lundiAffiche; tableau = null; charger(l); }

// ---- Navigation entre semaines : flèches et balayage ----------------------------
const decaler = n => charger(ajouterJours(lundiAffiche, 7 * n));
$("#prec").onclick = () => decaler(-1);
$("#suiv").onclick = () => decaler(1);
// Séance réalisée sans fichier (badminton, séance oubliée…) : saisie manuelle, puis relecture de la semaine
$("#ajouter-realisee").onclick = async () => {
  const r = await feuilleSeanceManuelle({ date: tableau?.aujourdhui, sante: tableau?.sante });
  if (!r) return;
  tableau = null;
  await charger(lundiAffiche);
};
// Aussi appelée par le bouton + de la barre d'onglets (app.js)
function ajouterSeancePrevue() {
  editer({ date_seance: tableau && lundiAffiche === tableau.lundi ? tableau.aujourdhui : lundiAffiche, creneau: "matin", type: "EF", statut: "prevu" });
}
$("#ajouter").onclick = ajouterSeancePrevue;
let depart = null;
document.addEventListener("touchstart", e => { const t = e.touches[0]; depart = [t.clientX, t.clientY]; }, { passive: true });
document.addEventListener("touchend", e => {
  if (!depart || $("#feuille")?.open || e.target.closest(".graph")) return;
  const t = e.changedTouches[0], dx = t.clientX - depart[0], dy = t.clientY - depart[1];
  if (Math.abs(dx) > 70 && Math.abs(dy) < 40) decaler(dx < 0 ? 1 : -1);
  depart = null;
}, { passive: true });

const ancre = /^\d{4}-\d{2}-\d{2}$/.test(location.hash.slice(1)) ? location.hash.slice(1) : null;
charger(ancre ? lundiDe(ancre) : null).then(() => {
  // Arrivée depuis le + d'un autre onglet : « Ajouter une séance prévue »
  if (new URLSearchParams(location.search).get("ajouter")) { history.replaceState(null, "", "/semaine"); ajouterSeancePrevue(); return; }
  defilerVersJour(ancre || tableau.aujourdhui);
});
