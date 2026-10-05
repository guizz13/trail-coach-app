/* SENSEI — détail d'une séance réalisée en feuille (Semaine, Aujourd'hui, Stats) */
"use strict";

// ---- Détail d'une séance (feuille) -------------------------------------------------------------------
// opts.apresChangement : rappelé après une liaison, un déliage ou un remplacement (relecture de la page)
async function ouvrirSeance(id, opts = {}) {
  const d = feuille(`<div class="reflexion"><span class="spinner"></span>Chargement…</div>`);
  try {
    const x = await api("GET", `/api/seances/${id}`);
    const s = x.seance, m = x.muscu_detail, sport = sportInfo(s.sport_id);
    const trace = s.a_gps ? stockage.lire("trace:" + s.fichier_hash) : null;
    const titre = s.sport_a_preciser ? "Sport à préciser"
      : sport.categorie === "course" && s.sous_type && s.sous_type !== "inconnu" ? `${sport.libelle} · ${libelleType(s.sous_type)}` : sport.libelle;
    const st = (v, l) => `<div><b>${v}</b>${l}</div>`;
    d.innerHTML = `<div class="poignee"></div>
      <div class="seance" style="cursor:default">${iconeSport(s.sport_id)}
        <div class="seance-corps"><h2>${esc(titre)}</h2>
          <div class="sous-texte">${esc(dateFR(s.date_debut, { weekday: "long", day: "numeric", month: "long", year: "numeric" }))} · ${esc(heure(s.date_debut))}</div></div>
        ${trace ? svgTrace(trace, 80, 56) : ""}</div>
      <div class="stats-inline">
        ${st(esc(duree(s.duree_min)), "durée")}
        ${s.distance_km ? st(nb(s.distance_km, 2, "km"), "distance") : ""}
        ${s.dplus_m ? st(nb(s.dplus_m, 0, "m"), "D+") : ""}
        ${st(s.fc_moy ? `${s.fc_moy}/${s.fc_max}` : "—", "FC moy/max")}
        ${st(nb(s.charge), "charge de la séance")}
        ${s.rpe ? st(`${s.rpe}/10`, "effort ressenti") : ""}
        ${s.epoc ? st(nb(s.epoc), "EPOC") : ""}
        ${st(s.recovery_time_h ? nb(s.recovery_time_h, 0, "h") : "—", "récupération estimée")}
        ${s.peak_training_effect ? st(nb(s.peak_training_effect, 1), "effet d'entraînement") : ""}
        ${s.vo2max ? st(nb(s.vo2max, 1), "VO2max") : ""}
        ${s.energie_kcal ? st(nb(s.energie_kcal), "kcal") : ""}
      </div>
      ${s.a_fc ? barreZones(zonesDepuisPct(s.temps_zones_pct)) : ""}
      ${s.note ? `<p class="secondaire" style="margin:8px 0 0">${esc(s.note)}</p>` : ""}
      ${s.sport_a_preciser ? `<div style="margin-top:8px">${pastillePreciser(s)}</div>` : ""}
      <div id="liaison"></div>
      ${m ? `<div class="section-label">Musculation${m.split ? " · " + esc(SPLITS[m.split] || m.split) : ""}</div>
        <div class="badges">${(m.groupes || []).map(g => `<span class="badge">${esc(GROUPES[g] || g)}</span>`).join("")}</div>
        ${(m.charges || []).length ? `<table style="margin-top:8px"><tr><th>Exercice</th><th class="n">kg</th><th class="n">reps</th><th class="n">séries</th></tr>
          ${m.charges.map(c => `<tr><td>${esc(c.exo)}</td><td class="n">${nb(c.kg, 1)}</td><td class="n">${nb(c.reps)}</td><td class="n">${nb(c.series)}</td></tr>`).join("")}</table>` : ""}` : ""}
      <div class="section-label">Verdict</div>
      <div class="ligne wrap">${verdictHTML(s.verdict) || `<span class="vide">non calculé</span>`}
        ${s.douleur != null ? `<span class="badge ${s.douleur >= 4 ? "rouge" : ""}">douleur ${s.douleur}/10${s.douleur_zone ? " · " + esc(s.douleur_zone) : ""}</span>` : ""}</div>
      ${(s.signaux || []).filter(x => x.niveau !== "info").map(x => `<div class="seance-detail" style="-webkit-line-clamp:unset;margin-top:4px">· ${esc(x.detail)}</div>`).join("")}
      <div class="section-label">Analyse</div>
      <div id="analyses"></div>`;
    rendreLiaison(d, x, opts.apresChangement);
    const za = $("#analyses", d);
    if (!x.analyses.length) za.innerHTML = `<div class="vide">Pas d'analyse du coach pour cette séance.</div>`;
    for (const a of x.analyses) {
      const r = a.reponse_json || {};
      if (r.erreur) { za.appendChild(carteErreurLLM(r.erreur)); continue; }
      za.insertAdjacentHTML("beforeend", `<div class="verdict-carte">
        <div class="tete ${esc(a.verdict)}"><span>${VERDICTS[a.verdict] || ""}</span><span>${esc(dateFR(a.cree_le, { day: "numeric", month: "short" }))} · ${nb(a.cout_usd, 3)} $</span></div>
        <div class="corps">${texteReplie(r.analyse)}
          ${(r.ajustements || []).map(j => `<div class="ajustement"><b style="text-transform:capitalize">${esc(j.jour)}</b> · ${esc(j.seance_initiale)} <span class="fleche">→</span> <b>${esc(j.seance_proposee)}</b><div class="sous-texte">${esc(j.raison)}</div></div>`).join("")}
          ${a.valide_par_user === -1 ? `<div class="sous-texte">Ajustements refusés — plan initial conservé.</div>` : ""}</div></div>`);
    }
  } catch (e) { erreurSimple(d, e); }
}

// ---- Liaison réalisé ↔ prévu (dans le détail d'une séance) ---------------------------------------------
const libellePrevu = p => `${libelleType(p.type)} (${dateFR(p.date_seance, { weekday: "short" })} ${CRENEAUX[p.creneau] || p.creneau})`;

function rendreLiaison(d, x, apresChangement) {
  const el = $("#liaison", d), id = x.seance.id;
  const apres = async promesse => {
    try { const nx = await promesse; rendreLiaison(d, nx, apresChangement); if (apresChangement) await apresChangement(); }
    catch (e) { erreurSimple($(".liaison-erreur", el) || el, e); }
  };
  if (x.prevu) {
    el.innerHTML = `<div class="liaison"><span>Liée à : <b>${esc(libellePrevu(x.prevu))}</b>${x.seance.lien_manuel ? ` <span class="sous-texte">(manuel)</span>` : ""}</span>
      <button type="button" class="btn petit" data-delier>Délier</button></div>
      ${x.prevu.detail ? `<div class="sous-texte" style="margin-top:4px">Prévu : ${esc(x.prevu.detail)}</div>` : ""}
      ${x.substitution ? `<div class="sous-texte" style="margin-top:4px">${esc(x.substitution)}</div>` : ""}<div class="liaison-erreur"></div>`;
    $("[data-delier]", el).onclick = () => apres(api("POST", `/api/seances_realisees/${id}/delier`));
    return;
  }
  const remplace = x.seance.remplace || [];
  if (remplace.length) {
    el.innerHTML = `<div class="liaison"><span>Remplace : <b>${esc(remplace.map(libelleCourt).join(", "))}</b></span>
      <button type="button" class="btn petit" data-annuler>Annuler le remplacement</button></div><div class="liaison-erreur"></div>`;
    $("[data-annuler]", el).onclick = () => apres(api("POST", `/api/seances_realisees/${id}/annuler_remplacement`));
    return;
  }
  el.innerHTML = `<div class="liaison"><span class="secondaire">Hors plan</span>
    <button type="button" class="btn petit" data-lier>Lier à une séance prévue</button></div>
    <button type="button" class="btn petit" data-remplacer style="margin-top:6px"><i class="ti ti-switch-horizontal"></i>Remplace une séance prévue</button>
    <div class="liaison-choix"></div><div class="liaison-erreur"></div>`;
  // Remplacement : toutes catégories, plusieurs séances possibles (badminton au lieu d'EF + Push)
  $("[data-remplacer]", el).onclick = async () => {
    const zone = $(".liaison-choix", el);
    try {
      const c = await api("GET", `/api/seances_realisees/${id}/remplacables`);
      if (!c.length) { zone.innerHTML = `<div class="vide">Aucune séance prévue à remplacer cette semaine.</div>`; return; }
      zone.innerHTML = c.map(p => `<label class="coche" style="padding:8px 0"><input type="checkbox" value="${p.id}">
          ${esc(libellePrevu(p))}${p.duree_min ? ` · ${esc(duree(p.duree_min))}` : ""}</label>`).join("")
        + `<button type="button" class="btn principal petit" data-valider-remplacement style="margin-top:6px">Valider</button>`;
      $("[data-valider-remplacement]", zone).onclick = () => {
        const ids = $$("input:checked", zone).map(i => Number(i.value));
        if (!ids.length) return;
        apres(api("POST", `/api/seances_realisees/${id}/remplacer`, { seance_planifiee_ids: ids }));
      };
    } catch (e) { erreurSimple(zone, e); }
  };
  $("[data-lier]", el).onclick = async () => {
    const zone = $(".liaison-choix", el);
    try {
      const c = await api("GET", `/api/seances_realisees/${id}/candidats`);
      zone.innerHTML = c.length ? c.map(p => `<button type="button" class="objectif-ligne" data-p="${p.id}">
          <span class="seance-corps"><span class="seance-type">${esc(libellePrevu(p))}</span>
          ${p.detail ? `<span class="seance-detail">${esc(p.detail)}</span>` : ""}</span><i class="ti ti-link muted"></i></button>`).join("")
        : `<div class="vide">Aucune séance prévue de la même catégorie libre cette semaine.</div>`;
      $$("[data-p]", zone).forEach(b => {
        b.onclick = () => apres(api("POST", `/api/seances_realisees/${id}/lier`, { seance_planifiee_id: Number(b.dataset.p) }));
      });
    } catch (e) { erreurSimple(zone, e); }
  };
}

