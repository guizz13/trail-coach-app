/* SENSEI — page Stats */
"use strict";

const PERIODES = { 4: "4 sem", 12: "12 sem", 26: "6 mois" };
coque(`<div class="segments" id="periode">${Object.entries(PERIODES).map(([v, l]) => `<button type="button" data-v="${v}">${l}</button>`).join("")}</div>`);

const aujourdhui = isoJour(new Date());
let semaines = Number(stockage.lire("periode")) || 12;
let famille = "";
let graphiques = null;
let seances = [];
const PAGE = 25;
let affichees = PAGE;

function debutPeriode() { return ajouterJours(lundiDe(aujourdhui), -7 * (semaines - 1)); }

async function charger() {
  $$("#periode button").forEach(b => b.classList.toggle("actif", Number(b.dataset.v) === semaines));
  if (!graphiques) graphiques = await api("GET", "/api/graphiques");
  seances = await api("GET", `/api/seances?du=${debutPeriode()}`);
  rendreVolume(); rendreCharge(); rendrePoids();
  affichees = PAGE;
  rendreListe();
}

// ---- Volume : agrégé par semaine depuis les séances de la période --------------------
function rendreVolume() {
  const lundis = Array.from({ length: semaines }, (_, i) => ajouterJours(debutPeriode(), 7 * i));
  const course = seances.filter(s => disciplineFamille(s.famille) === "course");
  const pts = lundis.map(l => {
    const sem = course.filter(s => lundiDe(s.date_debut.slice(0, 10)) === l);
    return { valeur: Math.round(sem.reduce((a, s) => a + (s.distance_km || 0), 0) * 10) / 10,
      detail: `semaine du ${dateFR(l, { day: "numeric", month: "short" })} · ${nb(sem.reduce((a, s) => a + (s.dplus_m || 0), 0))} m D+` };
  });
  const total = pts.reduce((a, p) => a + p.valeur, 0);
  $("#km-moy").textContent = nb(total / semaines, 1);
  $("#km-total").textContent = nb(total, 0) + " km";
  $("#dplus-total").textContent = `${nb(course.reduce((a, s) => a + (s.dplus_m || 0), 0))} m D+ · ${course.length} sorties`;
  const n = pts.length;
  graphCourbe($("#g-volume"), pts, { aire: true, unite: "km", hauteur: 150, titre: "Volume course hebdomadaire",
    etiquettes: { 0: `S-${n - 1}`, [Math.round((n - 1) / 2)]: `S-${n - 1 - Math.round((n - 1) / 2)}`, [n - 1]: "Auj." } });
}

// ---- Équilibre de charge : l'API fournit les 12 dernières semaines ------------------------
function rendreCharge() {
  const sem = graphiques.semaines.slice(-Math.min(semaines, graphiques.semaines.length));
  const n = sem.length;
  graphCourbe($("#g-acwr"), sem.map(s => ({ valeur: s.acwr, detail: `semaine du ${dateFR(s.lundi, { day: "numeric", month: "short" })}` })), {
    min: 0, max: 2, dec: 2, hauteur: 150, couleur: "var(--text-primary)", titre: "Équilibre de charge",
    bandes: [
      { de: 0.8, a: 1.3, couleur: "rgba(45,212,160,.12)" },
      { de: 1.3, a: 1.5, couleur: "rgba(245,166,35,.12)" },
      { de: 1.5, a: 99, couleur: "rgba(240,72,72,.12)" },
    ],
    etiquettes: { 0: `S-${n - 1}`, [n - 1]: "Auj." },
  });
  $("#acwr-note").textContent = "Vert : 0,8—1,3 optimal · orange : vigilance · rouge : danger au-delà de 1,5"
    + (semaines > graphiques.semaines.length ? ` · ${graphiques.semaines.length} dernières semaines disponibles` : "");
}

// ---- Poids -----------------------------------------------------------------------------
function rendrePoids() {
  const pts = graphiques.poids.filter(p => p.date_mesure >= debutPeriode());
  graphCourbe($("#g-poids"), pts.map(p => ({ valeur: p.poids_kg, detail: dateFR(p.date_mesure, { day: "numeric", month: "long" }) })),
    { unite: "kg", plancherAuto: true, hauteur: 110, couleur: "var(--text-secondary)", titre: "Poids",
      etiquettes: pts.length > 1 ? { 0: dateFR(pts[0].date_mesure, { day: "numeric", month: "short" }), [pts.length - 1]: dateFR(pts[pts.length - 1].date_mesure, { day: "numeric", month: "short" }) } : {} });
}
const fp = $("#form-poids");
fp.date_mesure.value = aujourdhui;
fp.onsubmit = async e => {
  e.preventDefault();
  try {
    await api("POST", "/api/poids", Object.fromEntries(new FormData(fp)));
    fp.poids_kg.value = ""; $("#err-poids").innerHTML = "";
    graphiques = null; await charger();
  } catch (err) { erreurSimple($("#err-poids"), err); }
};

// ---- Musculation : charges par exercice -----------------------------------------------------
async function chargerMuscu() {
  const charges = await api("GET", "/api/muscu/charges");
  const exos = Object.keys(charges).sort();
  const el = $("#muscu");
  if (!exos.length) { el.innerHTML = `<div class="vide">Aucune charge saisie. Elles s'ajoutent à l'import d'une séance de musculation.</div>`; return; }
  el.innerHTML = `<select id="exo">${exos.map(x => `<option>${esc(x)}</option>`).join("")}</select><div id="t-charges" style="margin-top:8px"></div>`;
  const rendre = () => {
    const l = charges[$("#exo").value] || [];
    $("#t-charges").innerHTML = `<table><tr><th>Date</th><th>Split</th><th class="n">kg</th><th class="n">reps</th><th class="n">séries</th></tr>
      ${l.slice().reverse().map(c => `<tr><td>${esc(dateFR(c.date, { day: "numeric", month: "short" }))}</td><td>${esc(SPLITS[c.split] || c.split || "")}</td>
        <td class="n">${nb(c.kg, 1)}</td><td class="n">${nb(c.reps)}</td><td class="n">${nb(c.series)}</td></tr>`).join("")}</table>`;
  };
  $("#exo").onchange = rendre;
  rendre();
}

// ---- Liste des séances ------------------------------------------------------------------------
const verdicts = {};
async function rendreListe() {
  // L'API renvoie déjà les séances de la plus récente à la plus ancienne
  const liste = seances.filter(s => !famille || disciplineFamille(s.famille) === famille);
  const el = $("#liste");
  if (!liste.length) { el.innerHTML = `<div class="vide" style="padding:10px 0">Aucune séance sur la période.</div>`; return; }
  const visibles = liste.slice(0, affichees);
  // Verdict de chaque séance affichée (dernière analyse), chargé à la demande
  await Promise.all(visibles.filter(s => !(s.id in verdicts)).map(s =>
    api("GET", `/api/seances/${s.id}`).then(d => { verdicts[s.id] = d.analyses[0]?.verdict || null; }).catch(() => { verdicts[s.id] = null; })));
  el.innerHTML = "";
  for (const s of visibles) {
    const b = document.createElement("button");
    b.className = "liste-ligne";
    const titre = s.sous_type && s.sous_type !== "inconnu" ? libelleType(s.sous_type) : FAMILLES[s.famille] || s.famille;
    b.innerHTML = `${iconeDisc(disciplineFamille(s.famille))}
      <div class="seance-corps"><div class="seance-type">${esc(titre)}</div>
        <div class="seance-detail">${esc(dateFR(s.date_debut, { weekday: "short", day: "numeric", month: "short" }))} · ${esc(duree(s.duree_min))}${s.distance_km ? " · " + nb(s.distance_km, 1, "km") : ""}</div></div>
      <div class="seance-droite">${verdictHTML(verdicts[s.id])}<i class="ti ti-chevron-right muted"></i></div>`;
    b.onclick = () => ouvrir(s.id);
    el.appendChild(b);
  }
  if (liste.length > affichees) {
    const plus = document.createElement("button");
    plus.className = "btn petit";
    plus.style.margin = "8px auto";
    plus.textContent = `Afficher plus (${liste.length - affichees})`;
    plus.onclick = () => { affichees += PAGE; rendreListe(); };
    el.appendChild(plus);
  }
}

$$("#familles button").forEach(b => {
  b.onclick = () => {
    famille = b.dataset.v; affichees = PAGE;
    $$("#familles button").forEach(x => x.classList.toggle("actif", x === b));
    rendreListe();
  };
});
$$("#periode button").forEach(b => {
  b.onclick = () => { semaines = Number(b.dataset.v); stockage.ecrire("periode", semaines); charger(); };
});

// ---- Détail d'une séance -------------------------------------------------------------------------
async function ouvrir(id) {
  const d = feuille(`<div class="reflexion"><span class="spinner"></span>Chargement…</div>`);
  try {
    const x = await api("GET", `/api/seances/${id}`);
    const s = x.seance, m = x.muscu_detail, disc = disciplineFamille(s.famille);
    const trace = s.a_gps ? stockage.lire("trace:" + s.fichier_hash) : null;
    const titre = s.sous_type && s.sous_type !== "inconnu" ? `${FAMILLES[s.famille]} · ${libelleType(s.sous_type)}` : FAMILLES[s.famille] || s.famille;
    const st = (v, l) => `<div><b>${v}</b>${l}</div>`;
    d.innerHTML = `<div class="poignee"></div>
      <div class="seance" style="cursor:default">${iconeDisc(disc)}
        <div class="seance-corps"><h2>${esc(titre)}</h2>
          <div class="sous-texte">${esc(dateFR(s.date_debut, { weekday: "long", day: "numeric", month: "long", year: "numeric" }))} · ${esc(heure(s.date_debut))}</div></div>
        ${trace ? svgTrace(trace, 80, 56) : ""}</div>
      <div class="stats-inline">
        ${st(esc(duree(s.duree_min)), "durée")}
        ${s.distance_km ? st(nb(s.distance_km, 2, "km"), "distance") : ""}
        ${s.dplus_m ? st(nb(s.dplus_m, 0, "m"), "D+") : ""}
        ${st(s.fc_moy ? `${s.fc_moy}/${s.fc_max}` : "—", "FC moy/max")}
        ${st(nb(s.charge), "charge de la séance")}
        ${st(s.recovery_time_h ? nb(s.recovery_time_h, 0, "h") : "—", "récupération estimée")}
        ${s.peak_training_effect ? st(nb(s.peak_training_effect, 1), "effet d'entraînement") : ""}
        ${s.vo2max ? st(nb(s.vo2max, 1), "VO2max") : ""}
        ${s.energie_kcal ? st(nb(s.energie_kcal), "kcal") : ""}
      </div>
      ${s.a_fc ? barreZones(zonesDepuisPct(s.temps_zones_pct)) : ""}
      ${x.prevu ? `<div class="bandeau gris">Séance prévue : ${esc(libelleType(x.prevu.type))}${x.prevu.detail ? " — " + esc(x.prevu.detail) : ""}</div>` : ""}
      ${m ? `<div class="section-label">Musculation${m.split ? " · " + esc(SPLITS[m.split] || m.split) : ""}</div>
        <div class="badges">${(m.groupes || []).map(g => `<span class="badge">${esc(GROUPES[g] || g)}</span>`).join("")}</div>
        ${(m.charges || []).length ? `<table style="margin-top:8px"><tr><th>Exercice</th><th class="n">kg</th><th class="n">reps</th><th class="n">séries</th></tr>
          ${m.charges.map(c => `<tr><td>${esc(c.exo)}</td><td class="n">${nb(c.kg, 1)}</td><td class="n">${nb(c.reps)}</td><td class="n">${nb(c.series)}</td></tr>`).join("")}</table>` : ""}` : ""}
      <div class="section-label">Analyse</div>
      <div id="analyses"></div>`;
    const za = $("#analyses", d);
    if (!x.analyses.length) za.innerHTML = `<div class="vide">Pas d'analyse du coach pour cette séance.</div>`;
    for (const a of x.analyses) {
      const r = a.reponse_json || {};
      if (r.erreur) { za.appendChild(carteErreurLLM(r.erreur)); continue; }
      za.insertAdjacentHTML("beforeend", `<div class="verdict-carte">
        <div class="tete ${esc(a.verdict)}"><span>${VERDICTS[a.verdict] || ""}</span><span>${esc(dateFR(a.cree_le, { day: "numeric", month: "short" }))} · ${nb(a.cout_usd, 3)} $</span></div>
        <div class="corps"><p>${esc(r.analyse)}</p>
          ${(r.ajustements || []).map(j => `<div class="ajustement"><b style="text-transform:capitalize">${esc(j.jour)}</b> · ${esc(j.seance_initiale)} <span class="fleche">→</span> <b>${esc(j.seance_proposee)}</b><div class="sous-texte">${esc(j.raison)}</div></div>`).join("")}
          ${a.valide_par_user === -1 ? `<div class="sous-texte">Ajustements refusés — plan initial conservé.</div>` : ""}</div></div>`);
    }
  } catch (e) { erreurSimple(d, e); }
}

charger().then(() => { if (location.hash.slice(1)) ouvrir(Number(location.hash.slice(1))); }).catch(e => erreurSimple($("#liste"), e));
chargerMuscu().catch(e => erreurSimple($("#muscu"), e));
