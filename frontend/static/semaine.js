/* SENSEI — page Semaine */
"use strict";

coque(`<span class="avatar">GA</span>`);

let tableau = null;          // /api/dashboard (semaine courante)
let graphiques = null;       // /api/graphiques (12 semaines)
let lundiAffiche = null;
let objectifs = null;       // /api/evenements (événements à venir + plan de prépa)

async function charger(lundi) {
  try {
    if (!tableau) [tableau, graphiques, objectifs] = await Promise.all([api("GET", "/api/dashboard"), api("GET", "/api/graphiques"), api("GET", "/api/evenements"), CATALOGUE_PRET]);
    lundiAffiche = lundi || tableau.lundi;
    const courante = lundiAffiche === tableau.lundi;
    const dimanche = ajouterJours(lundiAffiche, 6);
    const [jours, realisees, bilan, cap] = await Promise.all([
      courante ? tableau.semaine : api("GET", `/api/semaine?lundi=${lundiAffiche}`),
      api("GET", `/api/seances?du=${lundiAffiche}&au=${dimanche}`),
      courante ? tableau.bilan_semaine : api("GET", `/api/bilan_semaine?lundi=${lundiAffiche}`),
      courante ? tableau.cap_semaine : api("GET", `/api/cap_semaine?lundi=${lundiAffiche}`),
    ]);
    // Verdict stocké sur chaque séance réalisée (recalculé à chaque changement)
    const verdicts = Object.fromEntries(realisees.map(s => [s.id, s.verdict]));
    rendreEntete(dimanche);
    rendreObjectifProche();
    rendreCap(cap, dimanche);
    rendreForme(courante, realisees, dimanche);
    rendreVolume(courante, realisees);
    rendreBilanSemaine(bilan);
    rendrePlanning(jours, realisees, verdicts);
    rendreReajuster(courante);
    if (courante) reprendreAjustement().catch(() => {});
    $("#ajouter").classList.toggle("hidden", !courante);   // ajout : semaine en cours uniquement
    $("#ajouter-realisee").classList.toggle("hidden", !courante);
  } catch (e) { erreurSimple($("#planning"), e); }
}

function rendreEntete(dimanche) {
  const memeMois = lundiAffiche.slice(5, 7) === dimanche.slice(5, 7);
  $("#titre-semaine").textContent = `Semaine du ${dateFR(lundiAffiche, memeMois ? { day: "numeric" } : { day: "numeric", month: "short" })} — ${dateFR(dimanche, { day: "numeric", month: "short" })}`;

  const p = tableau.profil, a = tableau.prochain_a;
  const badges = [];
  if (p.mode_actif === "RACE_PREP") badges.push(`<span class="badge prepa">${esc(libelleMode(p, a))}${a ? ` J-${a.dans_jours}` : ""}</span>`);
  else {
    badges.push(`<span class="badge accent">Entraînement libre</span>`);
    if (a) badges.push(`<span class="badge orange">${esc(a.titre)} J-${a.dans_jours}</span>`);
  }
  if (tableau.phase) badges.push(`<span class="badge">${esc(PHASES[tableau.phase.phase] || tableau.phase.phase)}</span>`);
  const sante = tableau.sante;
  badges.push(`<button type="button" class="badge ${esc(sante.couleur)}" id="pastille-sante">${esc(sante.texte)}</button>`);
  $("#badges").innerHTML = badges.join("");
  $("#pastille-sante").onclick = () => feuilleSante(sante);
}

// Objectif A ou B dans les 28 prochains jours : carte sous les badges, sinon rien
const STYLE_EVT = {
  trail_race: { icone: "ti-run", c: "var(--orange)", dim: "var(--orange-dim)" },
  squash_competition: { icone: "ti-ball-tennis", c: "var(--squash)", dim: "var(--squash-dim)" },
  other: { icone: "ti-calendar-event", c: "var(--text-secondary)", dim: "var(--bg-surface)" },
};
const COULEUR_PHASE = { BASE: ["var(--accent)", "var(--accent-dim)"], BUILD: ["var(--orange)", "var(--orange-dim)"],
  PIC: ["var(--phase-pic)", "var(--phase-pic-dim)"], AFFUTAGE: ["var(--green)", "var(--green-dim)"] };

function rendreObjectifProche() {
  const el = $("#objectif-proche"), jour = tableau.aujourdhui;
  const e = objectifs.evenements.find(x => ["A", "B"].includes(x.priorite) && joursEntre(jour, x.date_evt) <= 28);
  if (!e) { el.innerHTML = ""; return; }
  const st = STYLE_EVT[e.type] || STYLE_EVT.other;
  const lieu = (e.notes || "").match(/^Lieu : (.*)/);
  const ligne2 = e.type === "trail_race" ? [e.distance_km && nb(e.distance_km, 1, "km"), e.dplus_m && nb(e.dplus_m, 0, "m D+")].filter(Boolean).join(" · ")
    : lieu ? lieu[1] : dateFR(e.date_evt, { weekday: "long", day: "numeric", month: "long" });
  // Phase en cours et semaine de prépa, d'après les phases rattachées à cet objectif
  const phases = objectifs.plan_prepa.filter(p => p.evenement_id === e.id);
  const phase = phases.find(p => p.du <= jour && jour <= p.au);
  let ligne3 = "";
  if (phase) {
    const debut = phases[0].du, [c, dim] = COULEUR_PHASE[phase.phase] || ["var(--text-secondary)", "var(--bg-surface)"];
    const total = Math.ceil(joursEntre(debut, e.date_evt) / 7), n = Math.min(total, Math.floor(joursEntre(debut, jour) / 7) + 1);
    ligne3 = `<div class="ligne" style="margin-top:6px"><span class="badge badge-mini" style="background:${dim};color:${c}">${esc(PHASES[phase.phase] || phase.phase)}</span>
      <span class="sous-texte" style="font-size:10px">semaine ${n}/${total}</span></div>`;
  }
  el.innerHTML = `<a class="objectif-proche" href="/evenements">
      <span class="type-grand" style="background:${st.dim};color:${st.c}"><i class="ti ${st.icone}"></i></span>
      <div style="flex:1;min-width:0">
        <div class="ligne entre"><span class="op-nom">${esc(e.titre)}</span><span class="op-compte" style="color:${st.c}">J-${joursEntre(jour, e.date_evt)}</span></div>
        ${ligne2 ? `<div class="op-detail">${esc(ligne2)}</div>` : ""}
        ${ligne3}
      </div>
      <i class="ti ti-chevron-right op-chevron"></i></a>`;
}

// Message du coach : seulement si une analyse ou un bilan date de la semaine affichée
// Cap de la semaine : résumé du plan validé (ou du réajustement appliqué) ; tap → message complet
function rendreCap(cap, dimanche) {
  const el = $("#coach");
  if (!cap || !cap.plan) {
    // Semaine passée sans plan : rien à proposer ; à venir ou en cours : direction Préparer
    el.innerHTML = dimanche < tableau.aujourdhui ? "" : `<div class="carte cap-semaine vide-plan">
        <div class="cap-phrase" style="margin-top:0">Pas encore de plan pour cette semaine.</div>
        <a class="btn petit" href="/preparer" style="margin-top:10px"><i class="ti ti-adjustments"></i>Préparer</a></div>`;
    return;
  }
  el.innerHTML = `<button type="button" class="carte cap-semaine" id="cap">
      <div class="cap-titre">${esc(cap.titre)}</div>
      ${cap.phrase ? `<div class="cap-phrase">${esc(cap.phrase)}</div>` : ""}
      ${cap.focus.length ? `<div class="pill-row" style="margin-top:10px">${cap.focus.map(f => `<span class="pill">${esc(f)}</span>`).join("")}</div>` : ""}
      ${cap.ajuste_le ? `<div class="cap-mention">Ajusté le ${esc(dateFR(cap.ajuste_le, { weekday: "long" }))}</div>` : ""}
    </button>`;
  $("#cap").onclick = () => feuille(`<h2>${esc(cap.titre)}</h2>
    ${messageCoach(cap.message_coach, cap.ajuste_le ? "Réajustement de Sensei" : "Message du coach")}
    ${cap.message_bilan ? messageCoach(cap.message_bilan, "Plan de la semaine") : ""}`);
}

function rendreForme(courante, realisees, dimanche) {
  // Équilibre de charge : valeur du jour pour la semaine courante, fin de semaine sinon.
  // Pendant le calibrage : jauge grisée, ni valeur ni couleur.
  let a = null, sous = "";
  if (courante) {
    a = tableau.acwr;
    if (!enCalibrage(a)) sous = `aiguë ${nb(a.charge_aigue)} · chronique ${nb(a.charge_chronique)}`;
  } else {
    const s = graphiques.semaines.find(x => x.lundi === lundiAffiche);
    a = s ? { ratio: s.acwr, zone: s.acwr_zone, jours_historique: s.jours_historique, jours_calibrage: 21 } : null;
    sous = s ? "en fin de semaine" : dimanche > tableau.aujourdhui ? "semaine à venir" : "hors des 12 dernières semaines";
  }
  const calib = enCalibrage(a);
  $("#charge").innerHTML = `<div class="label">Équilibre de charge</div>
    <div class="valeur" style="color:${calib ? "var(--text-muted)" : couleurRatio(a.ratio)}${calib ? ";font-size:15px" : ""}">${
      calib ? (a && a.zone === "calibrage" ? esc(libelleCalibrage(a)) : "—") : nb(a.ratio, 2)}</div>
    ${jaugeCharge(a)}
    <div class="sous-texte" style="margin-top:6px">${calib ? "ratio affiché après 21 jours d'historique" : nb(a.ratio, 2) + " / 0,8—1,3"}</div>
    ${sous ? `<div class="sous-texte">${esc(sous)}</div>` : ""}`;

  // Répartition des zones (course) : calculée par l'API pour la semaine courante,
  // agrégée depuis les temps par zone des séances pour les autres semaines
  let dist = courante ? tableau.distribution : null;
  if (!courante) {
    const tot = { z1: 0, z2: 0, z3: 0, z4: 0, z5: 0 };
    realisees.filter(s => sportInfo(s.sport_id).categorie === "course")
      .forEach(s => Object.entries(s.temps_zones_s || {}).forEach(([z, v]) => { tot[z] = (tot[z] || 0) + v; }));
    const t = Object.values(tot).reduce((a, b) => a + b, 0);
    if (t) dist = { z1_z2: 100 * (tot.z1 + tot.z2) / t, z3: 100 * tot.z3 / t, z4_z5: 100 * (tot.z4 + tot.z5) / t };
  }
  $("#zones").innerHTML = `<div class="label">Répartition zones</div>
    <div class="valeur" style="color:${!dist || !dist.z1_z2 ? "var(--text-muted)" : dist.z1_z2 >= 70 ? "var(--green)" : dist.z1_z2 >= 60 ? "var(--orange)" : "var(--red)"}">${dist && dist.z1_z2 ? nb(dist.z1_z2) + "%" : "—"}</div>
    <div class="sous-texte">en Z1-Z2 · cible 80 %</div>${barreZones(dist)}`;
}

function rendreVolume(courante, realisees) {
  const km = realisees.filter(s => sportInfo(s.sport_id).categorie === "course").reduce((a, s) => a + (s.distance_km || 0), 0);
  $("#km-semaine").innerHTML = `<b style="color:var(--text-primary)">${nb(km, 1)} km</b> ${courante ? "cette sem." : "cette semaine-là"}`;
  const sem = graphiques.semaines;
  graphCourbe($("#g-volume"), sem.map(s => ({ valeur: s.km, detail: `semaine du ${dateFR(s.lundi, { day: "numeric", month: "short" })} · ${nb(s.dplus)} m D+` })),
    { aire: true, unite: "km", titre: "Volume course hebdomadaire", hauteur: 110,
      etiquettes: { 0: `S-${sem.length - 1}`, [sem.length - 8]: `S-7`, [sem.length - 4]: "S-3", [sem.length - 1]: "Auj." } });
  const c = tableau.cout_llm;
  const deux = v => Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $("#cout").textContent = `Sensei ${deux(c.cout_usd)} $ / ${deux(c.plafond_usd)} $ ce mois`;
}

// ---- Bilan de la semaine : réalisé / prévu par catégorie (carte partagée, app.js) ---------------
function rendreBilanSemaine(b) {
  const html = bilanSemaineHTML(b);
  $("#bilan-semaine").innerHTML = html ? `<div class="section-label">Bilan de la semaine</div>${html}` : "";
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
      b.onclick = () => { location.href = `/historique#${r.id}`; };
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
      ${realisee ? `<a class="btn petit" style="margin-top:10px" href="/historique#${realisee.id}"><i class="ti ti-chart-line"></i>Voir la séance réalisée</a>` : ""}
      <div class="sous-texte" style="margin-top:12px">Seules les séances de la semaine en cours se modifient.</div>`);
    return;
  }
  const types = TYPES_PLANIFIABLES.includes(p.type) ? TYPES_PLANIFIABLES : [p.type, ...TYPES_PLANIFIABLES];
  const optTypes = v => types.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(libelleType(x))}</option>`).join("");
  const opt = (liste, v, lib = {}) => liste.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lib[x] || x)}</option>`).join("");
  const d = feuille(`<h2>${p.id ? "Modifier la séance" : "Nouvelle séance"}</h2>
    ${p.version ? `<div class="sous-texte">version ${p.version} · ${esc(p.origine || "")} · ${esc(STATUTS[p.statut] || p.statut)}</div>` : ""}
    ${realisee ? `<a class="btn petit" style="margin-top:10px" href="/historique#${realisee.id}"><i class="ti ti-chart-line"></i>Voir la séance réalisée</a>` : ""}
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
$("#ajouter").onclick = () => editer({ date_seance: tableau && lundiAffiche === tableau.lundi ? tableau.aujourdhui : lundiAffiche, creneau: "matin", type: "EF", statut: "prevu" });
let depart = null;
document.addEventListener("touchstart", e => { const t = e.touches[0]; depart = [t.clientX, t.clientY]; }, { passive: true });
document.addEventListener("touchend", e => {
  if (!depart || $("#feuille")?.open || e.target.closest(".graph")) return;
  const t = e.changedTouches[0], dx = t.clientX - depart[0], dy = t.clientY - depart[1];
  if (Math.abs(dx) > 70 && Math.abs(dy) < 40) decaler(dx < 0 ? 1 : -1);
  depart = null;
}, { passive: true });

charger(null);
