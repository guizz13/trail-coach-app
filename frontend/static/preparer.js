/* SENSEI — page Préparer : un écran par étape, puis aperçu de la semaine générée */
"use strict";

coque();

const ETAPES = [
  ["semaine", "Ta semaine écoulée"], ["forme", "Comment tu te sens"], ["sante", "Santé"],
  ["squash", "Squash et compétitions"], ["contraintes", "Contraintes"], ["recap", "Récapitulatif"],
];
const CRENEAUX_SQUASH = { matin: "matin", midi: "midi", soir: "soir" };
const JOURS_SL = { samedi: "Samedi", dimanche: "Dimanche", indifferent: "Peu importe" };
const NOTE_MAX = 200;
const reduit = matchMedia("(prefers-reduced-motion: reduce)").matches;

let d = null;           // /api/preparer
let etat = null;        // saisie en cours (sauvegardée en brouillon)
let etape = 0;
let bilan = null;       // semaine générée, pas encore validée
let seances = [];       // séances de la proposition (éditables avant « Valider »)

const cleBrouillon = () => `brouillon_preparer_${etat.semaine_debut}`;
const sauver = () => ecrireBrouillon(cleBrouillon(), { etat, etape });

// ---- État initial : semaine précédente et profil ------------------------------------------------------
function etatInitial() {
  const imp = d.imperatifs || d.imperatifs_precedents || {};
  const squash = {};
  (imp.squash_jours || []).forEach(x => { squash[x.jour] = CRENEAUX_SQUASH[x.creneau] ? x.creneau : "soir"; });
  const contraintes = {};
  (imp.contraintes || []).filter(c => c.contraintes).forEach(c => { contraintes[c.jour] = [...c.contraintes]; });
  const s = d.sante || {};
  return {
    semaine_debut: d.semaine_debut,
    ressenti: imp.ressenti || 7, sommeil: imp.sommeil || 7, fatigue_pro: imp.fatigue_pro || 5,
    vfc_ms: d.imperatifs?.vfc_ms ?? "",
    sante_inchangee: true,
    sante: { niveau: s.niveau || "100", zones: [...(s.zones || [])], note: s.note || "", protocole: s.protocole || "" },
    douleur_max: d.imperatifs?.douleur_max ?? 0,
    squash, contraintes,
    sortie_longue: { jour: "indifferent", duree_max_min: "", ...(imp.sortie_longue || {}) },
    autres_sports: (imp.autres_sports || []).map(x => ({ ...x })),
    notes: d.imperatifs?.notes || "",
  };
}

function charge() {
  return {
    semaine_debut: etat.semaine_debut,
    ressenti: etat.ressenti, sommeil: etat.sommeil, fatigue_pro: etat.fatigue_pro, vfc_ms: etat.vfc_ms,
    ...(etat.sante_inchangee ? {} : { sante: etat.sante, douleur_max: etat.douleur_max }),
    squash: JOURS.filter(j => etat.squash[j]).map(j => ({ jour: j, creneau: etat.squash[j] })),
    contraintes: JOURS.filter(j => (etat.contraintes[j] || []).length).map(j => ({ jour: j, contraintes: etat.contraintes[j] })),
    sortie_longue: etat.sortie_longue,
    autres_sports: etat.autres_sports,
    notes: etat.notes,
  };
}

// ---- Modes de la page : étapes, attente, aperçu ------------------------------------------------------
function mode(m) {
  $("#tete").classList.toggle("hidden", m !== "etapes");
  $("#pied").classList.toggle("hidden", m !== "etapes");
  $("#etapes").classList.toggle("hidden", m !== "etapes");
  $("#attente").classList.toggle("hidden", m !== "attente");
  $("#apercu").classList.toggle("hidden", m !== "apercu");
  window.scrollTo(0, 0);
}

function allerA(n) {
  const sens = n > etape ? "gauche" : "droite";
  etape = Math.max(0, Math.min(ETAPES.length - 1, n));
  sauver();
  rendreEtape(sens);
}

function rendreEtape(sens) {
  mode("etapes");
  const [cle, titre] = ETAPES[etape];
  $("#compteur").textContent = `${etape + 1} / ${ETAPES.length}`;
  $("#barre").style.width = `${100 * (etape + 1) / ETAPES.length}%`;
  $("#retour").style.visibility = etape ? "visible" : "hidden";
  $("#suivant").textContent = cle === "recap" ? "Générer ma semaine" : "Suivant";
  const el = $("#etapes");
  el.innerHTML = `<h1>${esc(titre)}</h1><div class="etape-corps">${RENDUS[cle]()}</div>`;
  LIAISONS[cle](el);
  if (sens && !reduit) {
    el.classList.remove("glisse-gauche", "glisse-droite");
    void el.offsetWidth;                                   // relance l'animation
    el.classList.add(`glisse-${sens}`);
  }
}

// ---- Étape 1 : semaine écoulée ------------------------------------------------------------------------
const libelleSemaine = l => `Semaine du ${dateFR(l, { day: "numeric", month: "long" })}`;
const RENDUS = {
  semaine: () => `
    ${bilanSemaineHTML(d.bilan_semaine) || `<div class="carte"><div class="vide">Aucune séance prévue ni réalisée la semaine dernière.</div></div>`}
    ${d.sans_donnees.length ? `<div class="bandeau orange">${d.sans_donnees.length} séance${d.sans_donnees.length > 1 ? "s" : ""} prévue${d.sans_donnees.length > 1 ? "s" : ""} sans données (${esc(d.sans_donnees.join(", "))}). Importe-les d'abord ou continue.
      <a class="btn petit" href="/import" style="margin-top:8px"><i class="ti ti-upload"></i>Importer</a></div>` : ""}
    <div class="section-label">Semaine à planifier</div>
    <select id="semaine">${d.semaines_possibles.map(l => `<option value="${l}" ${l === etat.semaine_debut ? "selected" : ""}>${esc(libelleSemaine(l))}</option>`).join("")}</select>`,

  // ---- Étape 2 : forme ----
  forme: () => `
    ${curseur("ressenti", "Ressenti général")}${curseur("sommeil", "Sommeil")}${curseur("fatigue_pro", "Fatigue pro")}
    <div class="section-label">VFC nocturne (moyenne 7 jours)</div>
    <div class="carte"><div class="ligne"><input id="vfc" inputmode="decimal" placeholder="ms (facultatif)" value="${esc(etat.vfc_ms)}" style="flex:1">
      <span id="tendance-vfc" class="tendance"></span></div>
      <div class="sous-texte" style="margin-top:6px">${d.vfc_moyenne_4_semaines ? `Moyenne des 4 dernières semaines saisies : ${nb(d.vfc_moyenne_4_semaines)} ms. Sensei raisonne sur la tendance, pas sur la valeur.` : "La tendance s'affichera dès qu'une semaine précédente aura une VFC."}</div></div>`,

  // ---- Étape 3 : santé ----
  sante: () => {
    const s = d.sante;
    return `<div class="carte"><div class="ligne entre"><span class="secondaire">Statut actuel</span><span class="badge ${esc(s.couleur || "")}">${esc(NIVEAUX_SANTE[s.niveau] || s.niveau)}${(s.zones || []).length ? " · " + esc(s.zones.join(", ")) : ""}</span></div>
      <button type="button" class="btn principal" id="rien" style="margin-top:12px">Rien de changé</button></div>
    <div class="section-label">Ou mettre à jour</div>
    <div class="carte">
      <div class="segments" id="niveau">${Object.entries(NIVEAUX_SANTE).map(([v, l]) => `<button type="button" data-v="${v}" class="${!etat.sante_inchangee && etat.sante.niveau === v ? "actif" : ""}">${esc(l)}</button>`).join("")}</div>
      <div id="zones-bloc" class="${etat.sante.niveau === "100" ? "hidden" : ""}"><label>Zones</label><div class="chips" id="zones"></div></div>
      ${curseur("douleur_max", "Douleur max de la semaine", 0, 10, false)}
      <label>Note</label><textarea id="sante-note" placeholder="ex. gêne au réveil, disparaît après 10 min">${esc(etat.sante.note)}</textarea>
      <label>Protocole kiné</label><textarea id="sante-protocole" placeholder="ex. course 30 min max, +5 min par semaine si 0 douleur J+1">${esc(etat.sante.protocole)}</textarea>
    </div>`;
  },

  // ---- Étape 4 : squash ----
  squash: () => `
    ${d.competitions.length ? d.competitions.map(e => `<div class="bandeau gris"><i class="ti ti-trophy"></i> ${esc(e.titre)} · ${esc(dateFR(e.date_evt, { weekday: "long", day: "numeric" }))}</div>`).join("") : ""}
    <div class="carte">${JOURS.map(j => `<div class="jour-ligne">
      <label class="coche"><input type="checkbox" data-sq="${j}" ${etat.squash[j] ? "checked" : ""}><span style="text-transform:capitalize">${j}</span></label>
      <div class="segments mini ${etat.squash[j] ? "" : "inactif"}" data-sqc="${j}">${Object.entries(CRENEAUX_SQUASH).map(([v, l]) =>
        `<button type="button" data-v="${v}" class="${etat.squash[j] === v ? "actif" : ""}">${l}</button>`).join("")}</div></div>`).join("")}</div>`,

  // ---- Étape 5 : contraintes ----
  contraintes: () => `
    <div class="carte">${JOURS.map(j => `<div class="jour-contraintes"><div class="jour-nom">${j}</div>
      <div class="chips">${Object.entries(d.contraintes_possibles).map(([v, l]) =>
        `<button type="button" data-j="${j}" data-c="${v}" class="${(etat.contraintes[j] || []).includes(v) ? "actif" : ""}">${esc(l)}</button>`).join("")}</div></div>`).join("")}</div>
    <div class="section-label">Sortie longue</div>
    <div class="carte"><div class="segments" id="sl-jour">${Object.entries(JOURS_SL).map(([v, l]) =>
      `<button type="button" data-v="${v}" class="${etat.sortie_longue.jour === v ? "actif" : ""}">${l}</button>`).join("")}</div>
      <label>Durée max disponible (min)</label><input id="sl-duree" inputmode="numeric" value="${esc(etat.sortie_longue.duree_max_min ?? "")}" placeholder="ex. 150"></div>
    <div class="section-label">Autres sports prévus</div>
    <div class="carte"><div id="autres"></div><button type="button" class="btn petit" id="ajout-sport" style="margin-top:8px"><i class="ti ti-plus"></i>Sport</button></div>
    <div class="section-label">Note pour Sensei</div>
    <textarea id="note" maxlength="${NOTE_MAX}" placeholder="Facultatif">${esc(etat.notes)}</textarea>
    <div class="sous-texte" id="note-compteur" style="text-align:right"></div>`,

  // ---- Étape 6 : récapitulatif ----
  recap: () => {
    const bloc = (n, titre, texte) => `<button type="button" class="recap-bloc" data-aller="${n}"><span class="recap-titre">${esc(titre)}</span>
      <span class="recap-texte">${texte}</span><i class="ti ti-chevron-right muted"></i></button>`;
    const contr = JOURS.filter(j => (etat.contraintes[j] || []).length)
      .map(j => `${j} : ${etat.contraintes[j].map(c => d.contraintes_possibles[c]).join(", ")}`);
    const sl = etat.sortie_longue;
    return `<div class="carte" style="padding:4px 14px">
      ${bloc(0, "Semaine", esc(libelleSemaine(etat.semaine_debut)))}
      ${bloc(1, "Forme", `ressenti ${etat.ressenti} · sommeil ${etat.sommeil} · fatigue pro ${etat.fatigue_pro}${etat.vfc_ms ? ` · VFC ${esc(etat.vfc_ms)} ms` : ""}`)}
      ${bloc(2, "Santé", etat.sante_inchangee ? "rien de changé" : esc([NIVEAUX_SANTE[etat.sante.niveau], etat.sante.zones.join(", "), `douleur max ${etat.douleur_max}/10`].filter(Boolean).join(" · ")))}
      ${bloc(3, "Squash", esc(JOURS.filter(j => etat.squash[j]).map(j => `${j} ${etat.squash[j]}`).join(", ") || "aucun"))}
      ${bloc(4, "Contraintes", esc([...contr, `sortie longue ${JOURS_SL[sl.jour].toLowerCase()}${sl.duree_max_min ? ` (${sl.duree_max_min} min max)` : ""}`,
        ...etat.autres_sports.map(x => `${sportInfo(x.sport_id).libelle.toLowerCase()} ${x.jour}`), etat.notes ? `« ${etat.notes} »` : ""].filter(Boolean).join(" · ")))}
    </div>`;
  },
};

function curseur(nom, libelle, min = 1, max = 10, carte = true) {
  return `<div class="${carte ? "carte " : ""}curseur"><div class="ligne entre" style="${carte ? "" : "margin-top:12px"}"><label style="margin:0">${esc(libelle)}</label><span class="chiffre" data-val="${nom}">${etat[nom]}</span></div>
    <input type="range" data-curseur="${nom}" min="${min}" max="${max}" value="${etat[nom]}"></div>`;
}

function lierCurseurs(el) {
  $$("[data-curseur]", el).forEach(i => i.oninput = () => {
    etat[i.dataset.curseur] = Number(i.value);
    $(`[data-val="${i.dataset.curseur}"]`, el).textContent = i.value;
    if (i.dataset.curseur === "douleur_max") etat.sante_inchangee = false;
    sauver();
  });
}

function tendanceVFC() {
  const el = $("#tendance-vfc"), v = Number(String(etat.vfc_ms).replace(",", ".")), moy = d.vfc_moyenne_4_semaines;
  if (!el) return;
  if (!v || !moy) { el.innerHTML = ""; return; }
  const ecart = 100 * (v - moy) / moy;
  const [icone, classe, texte] = ecart > 5 ? ["ti-arrow-up", "vert", "en hausse"] : ecart < -5 ? ["ti-arrow-down", "orange", "en baisse"] : ["ti-arrow-right", "", "stable"];
  el.className = `tendance ${classe}`;
  el.innerHTML = `<i class="ti ${icone}"></i>${texte} (${ecart > 0 ? "+" : ""}${nb(ecart)} %)`;
}

function rendreZones() {
  $("#zones").innerHTML = ZONES_SANTE.map(z => `<button type="button" data-z="${esc(z)}" class="${etat.sante.zones.includes(z) ? "actif" : ""}">${esc(z)}</button>`).join("");
  $$("#zones button").forEach(b => b.onclick = () => {
    const z = etat.sante.zones;
    z.includes(b.dataset.z) ? z.splice(z.indexOf(b.dataset.z), 1) : z.push(b.dataset.z);
    etat.sante_inchangee = false;
    rendreZones(); sauver();
  });
}

function rendreAutres() {
  $("#autres").innerHTML = etat.autres_sports.map((x, k) => `<div class="ligne" style="margin-bottom:6px">${iconeSport(x.sport_id)}
      <span style="flex:1">${esc(sportInfo(x.sport_id).libelle)}</span>
      <select data-autre-jour="${k}" style="width:130px">${JOURS.map(j => `<option ${j === x.jour ? "selected" : ""}>${j}</option>`).join("")}</select>
      <button type="button" class="btn-icone" data-autre-suppr="${k}" aria-label="Retirer"><i class="ti ti-x"></i></button></div>`).join("")
    || `<div class="vide">Aucun (ex. badminton samedi).</div>`;
  $$("[data-autre-jour]").forEach(s => s.onchange = () => { etat.autres_sports[Number(s.dataset.autreJour)].jour = s.value; sauver(); });
  $$("[data-autre-suppr]").forEach(b => b.onclick = () => { etat.autres_sports.splice(Number(b.dataset.autreSuppr), 1); rendreAutres(); sauver(); });
}

const LIAISONS = {
  semaine: el => {
    $("#semaine", el).onchange = e => init(e.target.value);
  },
  forme: el => {
    lierCurseurs(el);
    $("#vfc", el).oninput = e => { etat.vfc_ms = e.target.value.trim(); tendanceVFC(); sauver(); };
    tendanceVFC();
  },
  sante: el => {
    $("#rien", el).onclick = () => {
      const s = d.sante;
      etat.sante_inchangee = true;
      etat.sante = { niveau: s.niveau || "100", zones: [...(s.zones || [])], note: s.note || "", protocole: s.protocole || "" };
      allerA(etape + 1);
    };
    $$("#niveau button", el).forEach(b => b.onclick = () => {
      etat.sante.niveau = b.dataset.v;
      etat.sante_inchangee = false;
      $$("#niveau button", el).forEach(x => x.classList.toggle("actif", x === b));
      $("#zones-bloc", el).classList.toggle("hidden", b.dataset.v === "100");
      sauver();
    });
    rendreZones();
    lierCurseurs(el);
    $("#sante-note", el).oninput = e => { etat.sante.note = e.target.value; etat.sante_inchangee = false; sauver(); };
    $("#sante-protocole", el).oninput = e => { etat.sante.protocole = e.target.value; etat.sante_inchangee = false; sauver(); };
  },
  squash: el => {
    $$("[data-sq]", el).forEach(c => c.onchange = () => {
      const j = c.dataset.sq;
      etat.squash[j] = c.checked ? (etat.squash[j] || (JOURS.indexOf(j) >= 5 ? "matin" : "soir")) : null;
      sauver(); rendreEtape();
    });
    $$("[data-sqc] button", el).forEach(b => b.onclick = () => {
      const j = b.closest("[data-sqc]").dataset.sqc;
      etat.squash[j] = b.dataset.v;
      sauver(); rendreEtape();
    });
  },
  contraintes: el => {
    $$("[data-c]", el).forEach(b => b.onclick = () => {
      const liste = etat.contraintes[b.dataset.j] = etat.contraintes[b.dataset.j] || [];
      liste.includes(b.dataset.c) ? liste.splice(liste.indexOf(b.dataset.c), 1) : liste.push(b.dataset.c);
      b.classList.toggle("actif");
      sauver();
    });
    $$("#sl-jour button", el).forEach(b => b.onclick = () => {
      etat.sortie_longue.jour = b.dataset.v;
      $$("#sl-jour button", el).forEach(x => x.classList.toggle("actif", x === b));
      sauver();
    });
    $("#sl-duree", el).oninput = e => { etat.sortie_longue.duree_max_min = e.target.value.trim(); sauver(); };
    rendreAutres();
    $("#ajout-sport", el).onclick = async () => {
      const id = await choisirSport({ titre: "Sport prévu cette semaine" });
      if (!id) return;
      etat.autres_sports.push({ jour: "samedi", sport_id: id });
      rendreAutres(); sauver();
    };
    const compteur = () => { $("#note-compteur", el).textContent = `${etat.notes.length} / ${NOTE_MAX}`; };
    $("#note", el).oninput = e => { etat.notes = e.target.value.slice(0, NOTE_MAX); compteur(); sauver(); };
    compteur();
  },
  recap: el => {
    $$("[data-aller]", el).forEach(b => b.onclick = () => allerA(Number(b.dataset.aller)));
  },
};

$("#suivant").onclick = () => (ETAPES[etape][0] === "recap" ? generer() : allerA(etape + 1));
$("#retour").onclick = () => allerA(etape - 1);

// ---- Génération (tâche de fond) -----------------------------------------------------------------------
async function generer() {
  const bouton = $("#suivant");
  if (!etat.sante_inchangee && etat.sante.niveau !== "100" && !etat.sante.zones.length) {
    alert("Santé : choisis au moins une zone concernée.");
    allerA(2);
    return;
  }
  bouton.disabled = true;
  try {
    const t = await api("POST", "/api/bilan", charge());
    effacerBrouillon(cleBrouillon());               // la saisie est enregistrée côté serveur
    attendre(t);
  } catch (e) {
    alert(e.message);
  } finally { bouton.disabled = false; }
}

function attendre(tache) {
  mode("attente");
  $("#attente").innerHTML = `<h1>${esc(libelleSemaine(etat.semaine_debut))}</h1><div id="attente-zone"></div>
    <p class="sous-texte" style="text-align:center">Tu peux changer d'onglet ou fermer l'app : le plan t'attendra ici.</p>
    <div class="admin"><button type="button" class="btn-discret" id="modifier-saisie"><i class="ti ti-pencil"></i> Modifier la saisie</button></div>`;
  $("#modifier-saisie").onclick = () => { etat = etatInitial(); allerA(ETAPES.length - 1); };
  tacheDansZone($("#attente-zone"), tache, MESSAGES_BILAN, r => { bilan = r; afficherApercu(); });
}

// ---- Aperçu : cap de la semaine, jours, « Valider le plan » / « Ajuster » ----------------------------------
function afficherApercu() {
  mode("apercu");
  const r = bilan.reponse || {}, ss = r.semaine_suivante || {}, cap = r.resume_semaine || {};
  seances = (ss.seances || []).map(s => ({ ...s }));
  const ajust = r.ajustement_proposition;
  $("#apercu").innerHTML = `
    <h1>${esc(libelleSemaine(bilan.semaine_debut))}</h1>
    <div class="carte cap-semaine">
      <div class="cap-titre">${esc(cap.titre || ss.objectif || "Ta semaine")}</div>
      ${cap.phrase ? `<div class="cap-phrase">${esc(cap.phrase)}</div>` : ""}
      ${(cap.focus || []).length ? `<div class="pill-row" style="margin-top:10px">${cap.focus.slice(0, 3).map(f => `<span class="pill">${esc(f)}</span>`).join("")}</div>` : ""}
    </div>
    ${ajust ? messageCoach(ajust.message_coach, "Ajustement") : messageCoach(r.message_coach)}
    <div class="ligne entre"><div class="section-label">Séances</div>
      <button type="button" class="btn petit" id="ajout-seance" style="margin-top:14px"><i class="ti ti-plus"></i>Séance</button></div>
    <div id="proposition"></div>
    <div id="regles"></div>
    <div id="ajustement"></div>
    <div class="boutons"><button type="button" class="btn" id="ajuster">Ajuster</button><button type="button" class="btn principal" id="valider">Valider le plan</button></div>
    <div id="validation"></div>
    <div class="admin"><button type="button" class="btn-discret" id="recommencer"><i class="ti ti-refresh"></i> Reprendre la saisie</button></div>`;
  rendreProposition();
  afficherRegles(bilan.regles);
  $("#ajout-seance").onclick = () => editer(null);
  $("#valider").onclick = valider;
  $("#ajuster").onclick = ajuster;
  $("#recommencer").onclick = () => { etat = etatInitial(); allerA(0); };
  reprendreAjustement();
}

const ordre = s => JOURS.indexOf(s.jour) * 10 + Object.keys(CRENEAUX).indexOf(s.creneau);

function rendreProposition() {
  seances.sort((a, b) => ordre(a) - ordre(b));
  const lundi = bilan.semaine_debut, repos = (bilan.reponse.semaine_suivante || {}).jour_repos;
  const el = $("#proposition");
  el.innerHTML = "";
  JOURS.forEach((j, i) => {
    const carte = document.createElement("div");
    carte.className = "jour";
    carte.innerHTML = `<div class="jour-titre"><b>${j} ${esc(dateFR(ajouterJours(lundi, i), { day: "numeric" }))}</b>${j === repos ? "<span>repos</span>" : ""}</div>`;
    const duJour = seances.map((s, k) => [s, k]).filter(([s]) => s.jour === j);
    duJour.forEach(([s, k]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "seance";
      b.innerHTML = seanceHTML({ ...s, statut: "prevu" });
      $(".seance-droite", b).innerHTML = `<i class="ti ti-pencil muted"></i>`;
      b.onclick = () => editer(k);
      carte.appendChild(b);
    });
    if (!duJour.length) carte.insertAdjacentHTML("beforeend", `<div class="jour-vide">${j === repos ? "Repos complet" : "Rien de prévu"}</div>`);
    el.appendChild(carte);
  });
}

// Édition locale d'une séance proposée (k = index, null = nouvelle), avant validation
function editer(k) {
  const s = k == null ? { jour: "lundi", creneau: "matin", type: "EF", detail: "", intensite: "", duree_min: 45 } : seances[k];
  const types = TYPES_PLANIFIABLES.includes(s.type) ? TYPES_PLANIFIABLES : [s.type, ...TYPES_PLANIFIABLES];
  const opt = (l, v, lib = {}) => l.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lib[x] || x)}</option>`).join("");
  const f = feuille(`<h2>${k == null ? "Ajouter une séance" : "Modifier la séance"}</h2>
    <form>
      <div class="champs-2">
        <div><label>Jour</label><select name="jour">${opt(JOURS, s.jour)}</select></div>
        <div><label>Créneau</label><select name="creneau">${opt(Object.keys(CRENEAUX), s.creneau, CRENEAUX)}</select></div>
      </div>
      <label>Type</label>
      <div class="ligne"><select name="type" style="flex:1">${types.map(x => `<option value="${esc(x)}" ${x === s.type ? "selected" : ""}>${esc(libelleType(x))}</option>`).join("")}</select>
        <button type="button" class="btn petit" data-autre-sport><i class="ti ti-search"></i>Sport</button></div>
      <div class="champs-2">
        <div><label>Durée (min)</label><input type="number" inputmode="numeric" name="duree_min" value="${esc(s.duree_min ?? "")}"></div>
        <div><label>Intensité</label><input name="intensite" value="${esc(s.intensite || "")}"></div>
      </div>
      <label>Détail</label><textarea name="detail">${esc(s.detail || "")}</textarea>
      <div class="boutons">${k == null ? "" : `<button type="button" class="btn danger" data-suppr>Retirer</button>`}
        <button type="submit" class="btn principal">OK</button></div>
    </form>`);
  $("[data-autre-sport]", f).onclick = async () => {
    const id = await choisirSport({ titre: "Sport prévu" });
    if (!id) return;
    const select = $("[name=type]", f);
    if (![...select.options].some(o => o.value === id)) select.insertAdjacentHTML("afterbegin", `<option value="${esc(id)}">${esc(libelleType(id))}</option>`);
    select.value = id;
  };
  $("form", f).onsubmit = e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    v.duree_min = v.duree_min === "" ? null : Number(v.duree_min);
    if (k == null) seances.push(v); else Object.assign(seances[k], v);
    f.close(); rendreProposition(); verifier();
  };
  const sup = $("[data-suppr]", f);
  if (sup) sup.onclick = () => { seances.splice(k, 1); f.close(); rendreProposition(); verifier(); };
}

function afficherRegles(regles) {
  const el = $("#regles");
  if (!regles) { el.innerHTML = ""; return; }
  el.innerHTML = (regles.bloquantes.length
      ? `<div class="bandeau rouge"><b>Règles dures non respectées — validation impossible</b><ul>${regles.bloquantes.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`
      : `<div class="bandeau vert">Règles dures respectées : repos, 2 muscu haut du corps, pas de sortie longue en semaine.</div>`)
    + (regles.avertissements.length ? `<div class="bandeau orange"><ul>${regles.avertissements.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "");
  $("#valider").disabled = regles.bloquantes.length > 0;
}

let minuteur;
function verifier() {
  clearTimeout(minuteur);
  minuteur = setTimeout(async () => {
    try { afficherRegles(await api("POST", `/api/bilan/${bilan.analyse_id}/verifier`, { seances })); }
    catch (e) { erreurSimple($("#regles"), e); }
  }, 200);
}

// Le plan n'est écrit dans le planning qu'ici
async function valider() {
  const el = $("#validation");
  try {
    const v = await api("POST", `/api/bilan/${bilan.analyse_id}/valider`, { seances });
    el.innerHTML = `<div class="bandeau vert">Semaine du ${esc(dateFR(v.semaine_debut, { day: "numeric", month: "long" }))} enregistrée (${v.nb_seances} séances).
      <a class="btn petit" href="/" style="margin-top:8px"><i class="ti ti-calendar"></i>Voir le planning</a></div>`;
    $("#valider").disabled = true;
    $("#ajuster").disabled = true;
  } catch (e) { erreurSimple(el, e); }
}

// « Ajuster » : note libre → ajustement_semaine sur la proposition (tâche de fond)
function ajuster() {
  const f = feuille(`<h2>Ajuster la semaine</h2>
    <p class="secondaire" style="margin:0 0 10px">Dis à Sensei ce qui ne va pas ; il revoit la proposition sans casser les règles dures.</p>
    <textarea id="note-ajustement" maxlength="300" placeholder="ex. pas de vélo mardi, piscine plutôt"></textarea>
    <button type="button" class="btn principal" id="envoyer-ajustement" style="margin-top:12px">Ajuster</button>`);
  $("#envoyer-ajustement", f).onclick = async () => {
    const note = $("#note-ajustement", f).value.trim();
    f.close();
    try { suivreAjustement(await api("POST", `/api/bilan/${bilan.analyse_id}/ajuster`, { note })); }
    catch (e) { erreurSimple($("#ajustement"), e); }
  };
}

function suivreAjustement(tache) {
  $("#ajuster").disabled = $("#valider").disabled = true;
  const zone = $("#ajustement");
  tacheDansZone(zone, tache, ["Sensei relit la proposition...", "Prise en compte de ta demande...", "Vérification des règles..."], r => {
    if (r.ok) { bilan = r; afficherApercu(); return; }
    zone.innerHTML = `<div class="bandeau gris">${esc(r.message || "Ajustement impossible.")}</div>`;
    $("#ajuster").disabled = false;
    afficherRegles(bilan.regles);
  });
}

async function reprendreAjustement() {
  const [t] = await api("GET", `/api/taches?cle=ajustement_semaine:proposition:${bilan.analyse_id}`).catch(() => []);
  if (t && (t.statut === "en_cours" || !t.vue)) suivreAjustement(t);
}

// ---- Chargement : tâche en cours, proposition en attente, sinon parcours (brouillon restauré) -------------
async function init(semaine) {
  [d] = await Promise.all([api("GET", `/api/preparer${semaine ? `?semaine=${semaine}` : ""}`), CATALOGUE_PRET]);
  const brouillon = lireBrouillon(`brouillon_preparer_${d.semaine_debut}`);
  etat = brouillon?.etat || etatInitial();
  etat.semaine_debut = d.semaine_debut;
  etape = semaine ? 0 : (brouillon?.etape || 0);
  if (d.tache?.statut === "en_cours") { attendre(d.tache); return; }
  // Une proposition en attente prime sur une génération plus ancienne qui a échoué
  const recente = d.proposition && (!d.tache || d.proposition.cree_le >= d.tache.cree_le);
  if (d.tache?.statut === "erreur" && !recente) { attendre(d.tache); return; }
  if (d.tache) api("POST", `/api/taches/${d.tache.id}/vue`).catch(() => {});
  if (d.proposition && !semaine) { bilan = d.proposition; afficherApercu(); return; }
  rendreEtape();
}

init().catch(e => erreurSimple($("#etapes"), e));
