/* SENSEI — accueil « Aujourd'hui » : cap de la semaine, séance du jour, bande de la semaine, forme */
"use strict";

coque();

const LETTRES = ["L", "M", "M", "J", "V", "S", "D"];
// Une pastille de focus qui parle de santé passe en orange
const MOTS_SANTE = ["achille", "tendon", "mollet", "genou", "fascia", "hanche", "douleur", "sante", "kine", "blessure", "dos", "epaule"];
const estSante = t => MOTS_SANTE.some(m => sansAccents(t).includes(m));
const majuscule = t => t.charAt(0).toUpperCase() + t.slice(1);
let e = null;           // /api/aujourdhui

async function charger() {
  [e] = await Promise.all([api("GET", "/api/aujourdhui"), CATALOGUE_PRET]);
  rendreTitre();
  rendreCap();
  rendreSeance();
  rendreBande();
  rendreForme();
}

// ---- Titre : date, compte à rebours, pastilles hors de l'état normal ------------------------------------
function rendreTitre() {
  $("#date-jour").textContent = majuscule(dateFR(e.date, { weekday: "long", day: "numeric", month: "long" }));
  const a = e.prochain_a;
  $("#compte-a").textContent = a ? `${a.titre} J-${a.dans_jours}` : "";
  const pastilles = [];
  if (e.profil.mode_actif === "RACE_PREP") pastilles.push(`<span class="badge prepa">${esc(libelleMode(e.profil, a))}${e.phase ? ` · ${esc(PHASES[e.phase.phase] || e.phase.phase)}` : ""}</span>`);
  if (e.sante.niveau !== "100") pastilles.push(`<button type="button" class="badge ${esc(e.sante.couleur)}" id="pastille-sante">${esc(e.sante.texte)}</button>`);
  $("#pastilles").innerHTML = pastilles.join("");
  $("#pastilles").classList.toggle("hidden", !pastilles.length);
  if ($("#pastille-sante")) $("#pastille-sante").onclick = () => feuilleSante(e.sante);
  $("#bandeau-preparer").innerHTML = e.preparer_semaine_prochaine
    ? `<a class="bandeau-tache pret" href="/preparer"><span>Prépare ta semaine prochaine</span><i class="ti ti-chevron-right"></i></a>` : "";
}

// ---- Cap de la semaine ---------------------------------------------------------------------------------
function rendreCap() {
  const c = e.cap_semaine, el = $("#cap");
  if (!c.plan) { el.innerHTML = ""; return; }
  el.innerHTML = `<button type="button" class="cap-carte" id="cap-carte">
      <div class="cap-tete"><span class="cap-etiquette">Cap de la semaine</span><i class="ti ti-chevron-right"></i></div>
      ${c.titre ? `<div class="cap-titre">${esc(c.titre)}</div>` : ""}
      ${c.phrase ? `<div class="cap-phrase">${esc(c.phrase)}</div>` : ""}
      ${c.focus.length ? `<div class="pill-row" style="margin-top:8px">${c.focus.map(f => `<span class="pill ${estSante(f) ? "orange" : ""}">${esc(f)}</span>`).join("")}</div>` : ""}
      ${c.ajuste_le ? `<div class="cap-mention">Ajusté le ${esc(dateFR(c.ajuste_le, { weekday: "long" }))}</div>` : ""}
    </button>`;
  $("#cap-carte").onclick = () => feuille(`<div class="cap-etiquette">Cap de la semaine</div>
    ${c.titre ? `<h2 style="margin-top:6px">${esc(c.titre)}</h2>` : ""}
    ${messageCoach(c.message_coach, c.ajuste_le ? "Réajustement de Sensei" : "Message du coach")}
    ${c.message_bilan ? messageCoach(c.message_bilan, "Plan de la semaine") : ""}`);
}

// ---- Séance du jour, sinon la prochaine -------------------------------------------------------------------
const infosSeance = p => [p.creneau && CRENEAUX[p.creneau], p.duree_min && duree(p.duree_min), p.intensite].filter(Boolean).join(" · ");
const iconeCategorie = (cat, taille = "") => `<span class="disc ${esc(cat || "autre")} ${taille}"><i class="ti ${esc(CATALOGUE?.categories[cat]?.icone || "ti-activity")}"></i></span>`;

function rendreSeance() {
  const el = $("#seance-jour"), p = e.seance;
  const faites = e.faites_aujourdhui.map(r => `<button type="button" class="fait-carte" data-realisee="${r.id}">
      ${iconeSport(r.sport_id)}<span class="seance-corps"><span class="ligne entre"><span class="seance-type">${esc(titreRealisee(r))}</span>${verdictHTML(r.verdict)}</span>
      ${r.analyse_coach ? `<span class="fait-analyse">${esc(r.analyse_coach.texte)}</span>` : ""}</span></button>`).join("");
  let html = faites ? `<div class="section-label">Fait aujourd'hui</div>${faites}` : "";
  if (p) {
    const libelle = e.quand === "aujourdhui" ? "Aujourd'hui" : `Prochaine séance · ${dateFR(p.date_seance, { weekday: "long" })}`;
    html += `${e.demain.length ? `<div class="demain">Demain : ${esc(e.demain.join(", "))}</div>` : ""}
      <div class="section-label">${esc(libelle)}</div>
      <div class="carte heros">
        <div class="ligne" style="gap:12px">${iconeCategorie(p.categorie, "grand")}
          <div class="seance-corps"><div class="heros-titre">${esc(libelleType(p.type))}</div>
            <div class="sous-texte">${esc(infosSeance(p))}</div></div></div>
        ${p.detail ? `<p class="heros-detail">${esc(p.detail)}</p>` : ""}
        <div class="boutons"><button type="button" class="btn" id="detail-seance">Détail</button>
          ${e.decalable && e.jours_decalage.length ? `<button type="button" class="btn" id="decaler">Décaler</button>` : ""}</div>
      </div>`;
  } else if (!e.plan_semaine && !e.cap_semaine.plan) {
    html += `<div class="carte vide-plan"><div class="cap-phrase" style="margin-top:0">Pas encore de plan cette semaine.</div>
      <a class="btn petit" href="/preparer" style="margin-top:10px"><i class="ti ti-adjustments"></i>Préparer</a></div>`;
  } else {
    html += `<div class="carte"><div class="vide">Plus rien de prévu cette semaine.</div></div>`;
  }
  el.innerHTML = html;
  $$("[data-realisee]", el).forEach(b => b.onclick = () => ouvrirSeance(Number(b.dataset.realisee), { apresChangement: charger }));
  if (!p) return;
  $("#detail-seance").onclick = () => feuille(`<div class="ligne" style="gap:12px">${iconeCategorie(p.categorie, "grand")}
      <div><h2 style="margin:0">${esc(libelleType(p.type))}</h2>
      <div class="sous-texte">${esc(majuscule(dateFR(p.date_seance, { weekday: "long", day: "numeric", month: "long" })))} · ${esc(CRENEAUX[p.creneau] || p.creneau)}</div></div></div>
    <div class="stats-inline">
      ${p.duree_min ? `<div><b>${esc(duree(p.duree_min))}</b>durée</div>` : ""}
      ${p.distance_km ? `<div><b>${nb(p.distance_km, 1, "km")}</b>distance</div>` : ""}
      ${p.dplus_m ? `<div><b>${nb(p.dplus_m, 0, "m")}</b>D+</div>` : ""}
      ${p.intensite ? `<div><b>${esc(p.intensite)}</b>intensité</div>` : ""}
    </div>
    ${p.detail ? `<p class="secondaire" style="margin:10px 0 0;line-height:1.5">${esc(p.detail)}</p>` : ""}`);
  const dec = $("#decaler");
  if (dec) dec.onclick = () => {
    const d = feuille(`<h2>Décaler à…</h2><p class="secondaire" style="margin:0 0 8px">${esc(libelleType(p.type))} · le planning se recalcule.</p>
      ${e.jours_decalage.map(j => `<button type="button" class="action-ligne" data-jour="${j}">
        <span class="seance-corps"><span class="seance-type">${esc(majuscule(dateFR(j, { weekday: "long", day: "numeric", month: "long" })))}</span></span>
        <i class="ti ti-chevron-right muted"></i></button>`).join("")}`);
    $$("[data-jour]", d).forEach(b => b.onclick = async () => {
      try { await api("PATCH", `/api/seances_planifiees/${p.id}`, { date_seance: b.dataset.jour }); d.close(); charger(); }
      catch (err) { erreurSimple(d, err); }
    });
  };
}

// ---- Bande de la semaine -------------------------------------------------------------------------------
const ICONE_ETAT = { fait: "ti-check", repos: "ti-zzz", decale: "ti-arrow-right", libre: "" };

function rendreBande() {
  const b = e.bilan_semaine;
  const pastilles = e.bande.map((j, i) => {
    const icone = ICONE_ETAT[j.etat] ?? (CATALOGUE?.categories[j.categorie]?.icone || "ti-activity");
    return `<a class="jour-pastille" href="/semaine#${j.date}" aria-label="${esc(j.jour)} : ${esc(j.etat)}">
      <span class="jour-lettre ${j.aujourdhui ? "actif" : ""}">${LETTRES[i]}</span>
      <span class="rond ${esc(j.etat)}">${icone ? `<i class="ti ${esc(icone)}"></i>` : ""}</span></a>`;
  }).join("");
  let statut = "";
  if (b.respect_global === "en_cours") statut = b.seances_en_retard ? `en cours, ${b.seances_en_retard} en retard` : "en cours, à jour";
  else if (b.respect_global) statut = (RESPECT[b.respect_global] || ["", ""])[1].toLowerCase();
  $("#bande").innerHTML = `<div class="section-label">Ta semaine</div>
    <div class="bande">${pastilles}</div>
    ${b.seances.prevues ? `<div class="bande-resume ${b.sous_statut === "en_retard" ? "orange" : ""}">${b.seances.faites} / ${b.seances.prevues} séances${statut ? ` · ${esc(statut)}` : ""}</div>` : ""}`;
}

// ---- État de forme compact ---------------------------------------------------------------------------------
const ZONES_ACWR = { sous_charge: "sous-charge", optimal: "optimal", vigilance: "vigilance", danger: "danger" };

function rendreForme() {
  const a = e.forme.acwr, dist = e.forme.distribution || {};
  $("#alerte").innerHTML = e.alerte ? `<div class="bandeau orange" style="margin-top:14px">${esc(e.alerte)}</div>` : "";
  const calib = enCalibrage(a);
  const z12 = dist.z1_z2;
  $("#forme").innerHTML = `
    <a class="carte metrique tuile" href="/historique"><div class="label">Équilibre de charge</div>
      <div class="valeur" style="color:${calib ? "var(--text-muted)" : couleurRatio(a.ratio)}${calib ? ";font-size:15px" : ""}">${calib ? esc(libelleCalibrage(a)) : nb(a.ratio, 2)}</div>
      <div class="sous-texte">${calib ? "ratio après 21 jours" : esc(ZONES_ACWR[a.zone] || a.zone)}</div></a>
    <a class="carte metrique tuile" href="/historique"><div class="label">Zones course</div>
      <div class="valeur" style="color:${!z12 ? "var(--text-muted)" : z12 >= 70 ? "var(--green)" : z12 >= 60 ? "var(--orange)" : "var(--red)"}">${z12 ? nb(z12) + " %" : "—"}</div>
      <div class="sous-texte">en Z1-Z2 · cible 80 %</div></a>`;
}

charger().catch(err => erreurSimple($("#seance-jour"), err));
