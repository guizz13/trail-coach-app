/* SENSEI — page Semaine */
"use strict";

coque(`<span class="avatar">GA</span>`);

let tableau = null;          // /api/dashboard (semaine courante)
let graphiques = null;       // /api/graphiques (12 semaines)
let lundiAffiche = null;
let objectifs = null;       // /api/evenements (événements à venir + plan de prépa)

async function charger(lundi) {
  try {
    if (!tableau) [tableau, graphiques, objectifs] = await Promise.all([api("GET", "/api/dashboard"), api("GET", "/api/graphiques"), api("GET", "/api/evenements")]);
    lundiAffiche = lundi || tableau.lundi;
    const courante = lundiAffiche === tableau.lundi;
    const dimanche = ajouterJours(lundiAffiche, 6);
    const [jours, realisees] = await Promise.all([
      courante ? tableau.semaine : api("GET", `/api/semaine?lundi=${lundiAffiche}`),
      api("GET", `/api/seances?du=${lundiAffiche}&au=${dimanche}`),
    ]);
    const verdicts = await verdictsDe(realisees);
    rendreEntete(dimanche);
    rendreObjectifProche();
    rendreCoach(dimanche);
    rendreForme(courante, realisees, dimanche);
    rendreVolume(courante, realisees);
    rendrePlanning(jours, realisees, verdicts);
  } catch (e) { erreurSimple($("#planning"), e); }
}

// Verdict de la dernière analyse de chaque séance réalisée
async function verdictsDe(realisees) {
  const details = await Promise.all(realisees.map(s => api("GET", `/api/seances/${s.id}`).catch(() => null)));
  const v = {};
  details.forEach(d => { if (d && d.analyses.length) v[d.seance.id] = d.analyses[0].verdict; });
  return v;
}

function rendreEntete(dimanche) {
  const memeMois = lundiAffiche.slice(5, 7) === dimanche.slice(5, 7);
  $("#titre-semaine").textContent = `Semaine du ${dateFR(lundiAffiche, memeMois ? { day: "numeric" } : { day: "numeric", month: "short" })} — ${dateFR(dimanche, { day: "numeric", month: "short" })}`;

  const p = tableau.profil, a = tableau.prochain_a, sante = p.statut_sante || "100%";
  const badges = [];
  if (p.mode_actif === "RACE_PREP") badges.push(`<span class="badge prepa">${esc(libelleMode(p, a))}${a ? ` J-${a.dans_jours}` : ""}</span>`);
  else {
    badges.push(`<span class="badge accent">Entraînement libre</span>`);
    if (a) badges.push(`<span class="badge orange">${esc(a.titre)} J-${a.dans_jours}</span>`);
  }
  if (tableau.phase) badges.push(`<span class="badge">${esc(PHASES[tableau.phase.phase] || tableau.phase.phase)}</span>`);
  const [niveau, zone] = sante.split(":");
  badges.push(niveau === "100%" ? `<span class="badge vert">Santé 100%</span>`
    : `<span class="badge ${niveau === "blessure" ? "rouge" : "orange"}">${niveau === "blessure" ? "Blessure" : "Vigilance"} ${esc(zone || "")}</span>`);
  $("#badges").innerHTML = badges.join("");
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
function rendreCoach(dimanche) {
  const a = tableau.derniere_analyse, el = $("#coach");
  const r = a && a.reponse_json;
  const jour = a && a.cree_le.slice(0, 10);
  if (!r || r.erreur || jour < lundiAffiche || jour > dimanche) { el.innerHTML = ""; return; }
  el.innerHTML = messageCoach(r.message_coach || r.analyse, `${APPELS[a.type_appel] || "Message"} du coach`);
}

function rendreForme(courante, realisees, dimanche) {
  // Équilibre de charge : valeur du jour pour la semaine courante, fin de semaine sinon
  let ratio = null, sous = "";
  if (courante) {
    // Historique trop court : le ratio n'est pas fiable, on ne l'affiche pas
    const insuffisant = tableau.acwr.zone === "insuffisant";
    ratio = insuffisant ? null : tableau.acwr.ratio;
    sous = insuffisant ? "historique insuffisant pour évaluer"
      : `aiguë ${nb(tableau.acwr.charge_aigue)} · chronique ${nb(tableau.acwr.charge_chronique)}`;
  } else {
    const s = graphiques.semaines.find(x => x.lundi === lundiAffiche);
    ratio = s ? s.acwr : null;
    sous = s ? "en fin de semaine" : dimanche > tableau.aujourdhui ? "semaine à venir" : "hors des 12 dernières semaines";
  }
  $("#charge").innerHTML = `<div class="label">Équilibre de charge</div>
    <div class="valeur" style="color:${couleurRatio(ratio)}">${ratio == null ? "—" : nb(ratio, 2)}</div>
    ${jaugeCharge(ratio)}
    <div class="sous-texte" style="margin-top:6px">${ratio == null ? "" : nb(ratio, 2) + " / "}0,8—1,3</div>
    <div class="sous-texte">${esc(sous)}</div>`;

  // Répartition des zones (course) : calculée par l'API pour la semaine courante,
  // agrégée depuis les temps par zone des séances pour les autres semaines
  let dist = courante ? tableau.distribution : null;
  if (!courante) {
    const tot = { z1: 0, z2: 0, z3: 0, z4: 0, z5: 0 };
    realisees.filter(s => disciplineFamille(s.famille) === "course")
      .forEach(s => Object.entries(s.temps_zones_s || {}).forEach(([z, v]) => { tot[z] = (tot[z] || 0) + v; }));
    const t = Object.values(tot).reduce((a, b) => a + b, 0);
    if (t) dist = { z1_z2: 100 * (tot.z1 + tot.z2) / t, z3: 100 * tot.z3 / t, z4_z5: 100 * (tot.z4 + tot.z5) / t };
  }
  $("#zones").innerHTML = `<div class="label">Répartition zones</div>
    <div class="valeur" style="color:${!dist || !dist.z1_z2 ? "var(--text-muted)" : dist.z1_z2 >= 70 ? "var(--green)" : dist.z1_z2 >= 60 ? "var(--orange)" : "var(--red)"}">${dist && dist.z1_z2 ? nb(dist.z1_z2) + "%" : "—"}</div>
    <div class="sous-texte">en Z1-Z2 · cible 80 %</div>${barreZones(dist)}`;
}

function rendreVolume(courante, realisees) {
  const km = realisees.filter(s => disciplineFamille(s.famille) === "course").reduce((a, s) => a + (s.distance_km || 0), 0);
  $("#km-semaine").innerHTML = `<b style="color:var(--text-primary)">${nb(km, 1)} km</b> ${courante ? "cette sem." : "cette semaine-là"}`;
  const sem = graphiques.semaines;
  graphCourbe($("#g-volume"), sem.map(s => ({ valeur: s.km, detail: `semaine du ${dateFR(s.lundi, { day: "numeric", month: "short" })} · ${nb(s.dplus)} m D+` })),
    { aire: true, unite: "km", titre: "Volume course hebdomadaire", hauteur: 110,
      etiquettes: { 0: `S-${sem.length - 1}`, [sem.length - 8]: `S-7`, [sem.length - 4]: "S-3", [sem.length - 1]: "Auj." } });
  const c = tableau.cout_llm;
  const deux = v => Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $("#cout").textContent = `Sensei ${deux(c.cout_usd)} $ / ${deux(c.plafond_usd)} $ ce mois`;
}

function rendrePlanning(jours, realisees, verdicts) {
  const parId = Object.fromEntries(realisees.map(s => [s.id, s]));
  const el = $("#planning");
  el.innerHTML = "";
  for (const j of jours) {
    const carte = document.createElement("div");
    carte.className = "jour" + (j.date === tableau.aujourdhui ? " aujourdhui" : "");
    carte.innerHTML = `<div class="jour-titre"><b>${esc(j.jour)} ${esc(dateFR(j.date, { day: "numeric" }))}</b>
      ${j.date === tableau.aujourdhui ? "<span>aujourd'hui</span>" : ""}</div>`;
    for (const p of j.planifiees) {
      const r = p.seance_realisee_id ? parId[p.seance_realisee_id] : null;
      const b = document.createElement("button");
      b.className = "seance";
      b.innerHTML = seanceHTML(p, r, r && verdicts[r.id]);
      b.onclick = () => editer(p, r);
      carte.appendChild(b);
    }
    for (const r of j.realisees_hors_plan) {
      const b = document.createElement("button");
      b.className = "seance";
      b.innerHTML = seanceHTML(null, r, verdicts[r.id]);
      b.onclick = () => { location.href = `/historique#${r.id}`; };
      carte.appendChild(b);
    }
    if (!j.planifiees.length && !j.realisees_hors_plan.length) carte.insertAdjacentHTML("beforeend", `<div class="jour-vide">Rien de prévu</div>`);
    el.appendChild(carte);
  }
}

// ---- Édition d'une séance planifiée (feuille) --------------------------------
function editer(p, realisee) {
  const types = TYPES_PLANIFIABLES.includes(p.type) ? TYPES_PLANIFIABLES : [p.type, ...TYPES_PLANIFIABLES];
  const opt = (liste, v, lib = {}) => liste.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lib[x] || x)}</option>`).join("");
  const d = feuille(`<h2>${p.id ? "Modifier la séance" : "Nouvelle séance"}</h2>
    ${p.version ? `<div class="sous-texte">version ${p.version} · ${esc(p.origine || "")}</div>` : ""}
    ${realisee ? `<a class="btn petit" style="margin-top:10px" href="/historique#${realisee.id}"><i class="ti ti-chart-line"></i>Voir la séance réalisée</a>` : ""}
    <form>
      <div class="champs-2">
        <div><label>Date</label><input type="date" name="date_seance" value="${esc(p.date_seance)}" required></div>
        <div><label>Créneau</label><select name="creneau">${opt(Object.keys(CRENEAUX), p.creneau || "matin", CRENEAUX)}</select></div>
      </div>
      <label>Type</label><select name="type">${opt(types, p.type || "EF", TYPES)}</select>
      <div class="champs-2">
        <div><label>Durée (min)</label><input type="number" inputmode="numeric" name="duree_min" value="${esc(p.duree_min ?? "")}"></div>
        <div><label>Distance (km)</label><input type="number" inputmode="decimal" step="0.1" name="distance_km" value="${esc(p.distance_km ?? "")}"></div>
      </div>
      <label>Statut</label><select name="statut">${opt(Object.keys(STATUTS), p.statut || "prevu", STATUTS)}</select>
      <label>Détail</label><textarea name="detail">${esc(p.detail ?? "")}</textarea>
      <label>Intensité</label><input name="intensite" value="${esc(p.intensite ?? "")}">
      <div class="erreur"></div>
      <div class="boutons">${p.id ? `<button type="button" class="btn danger" data-suppr>Supprimer</button>` : ""}
        <button type="submit" class="btn principal">Enregistrer</button></div>
    </form>`);
  $("form", d).onsubmit = async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    try {
      if (p.id) await api("PUT", `/api/planifiees/${p.id}`, v); else await api("POST", "/api/planifiees", v);
      d.close(); recharger();
    } catch (err) { erreurSimple($(".erreur", d), err); }
  };
  const s = $("[data-suppr]", d);
  if (s) s.onclick = async () => {
    if (!confirm("Supprimer cette séance ?")) return;
    try { await api("DELETE", `/api/planifiees/${p.id}`); d.close(); recharger(); } catch (err) { erreurSimple($(".erreur", d), err); }
  };
}

function recharger() { const l = lundiAffiche; tableau = null; charger(l); }

// ---- Navigation entre semaines : flèches et balayage ----------------------------
const decaler = n => charger(ajouterJours(lundiAffiche, 7 * n));
$("#prec").onclick = () => decaler(-1);
$("#suiv").onclick = () => decaler(1);
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
