/* SENSEI — page Stats */
"use strict";

const PERIODES = { 4: "4 sem", 12: "12 sem", 26: "6 mois" };
coque(`<div class="segments" id="periode">${Object.entries(PERIODES).map(([v, l]) => `<button type="button" data-v="${v}">${l}</button>`).join("")}</div>`);

const aujourdhui = isoJour(new Date());
let semaines = Number(stockage.lire("periode")) || 12;
let categorie = "";          // filtre de la liste : une catégorie du catalogue, ou toutes
let graphiques = null;
let seances = [];
const PAGE = 25;
let affichees = PAGE;

function debutPeriode() { return ajouterJours(lundiDe(aujourdhui), -7 * (semaines - 1)); }

async function charger() {
  $$("#periode button").forEach(b => b.classList.toggle("actif", Number(b.dataset.v) === semaines));
  if (!graphiques) [graphiques] = await Promise.all([api("GET", "/api/graphiques"), CATALOGUE_PRET]);
  seances = await api("GET", `/api/seances?du=${debutPeriode()}`);
  rendreVolume(); rendreCharge(); rendrePoids();
  affichees = PAGE;
  rendreFiltres();
  rendreListe();
}

// ---- Volume : agrégé par semaine depuis les séances de la période --------------------
function rendreVolume() {
  const lundis = Array.from({ length: semaines }, (_, i) => ajouterJours(debutPeriode(), 7 * i));
  const course = seances.filter(s => sportInfo(s.sport_id).categorie === "course");
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
// Série quotidienne (un point par jour) ; jours de calibrage non tracés ; écrêtage à 2 avec marqueur
function rendreCharge() {
  const depuis = debutPeriode();
  const serie = graphiques.acwr_quotidien.filter(p => p.date >= depuis);
  const el = $("#g-acwr");
  if (!serie.some(p => p.ratio != null)) {
    el.innerHTML = `<div class="vide" style="padding:24px 0;text-align:center">Calibrage en cours</div>`;
    $("#acwr-note").textContent = "Le ratio s'affiche après 21 jours d'historique régulier.";
    return;
  }
  const n = serie.length;
  graphCourbe(el, serie.map(p => ({
    valeur: p.ratio == null ? null : Math.min(p.ratio, 2),
    marque: p.ratio > 2 ? "var(--red)" : null,
    detail: `${dateFR(p.date, { weekday: "short", day: "numeric", month: "short" })}${p.ratio > 2 ? ` · réel ${nb(p.ratio, 2)}` : ""}`,
  })), {
    min: 0, max: 2, dec: 2, hauteur: 150, couleur: "var(--text-primary)", titre: "Équilibre de charge",
    bandes: [
      { de: 0.8, a: 1.3, couleur: "rgba(45,212,160,.12)" },
      { de: 1.3, a: 1.5, couleur: "rgba(245,166,35,.12)" },
      { de: 1.5, a: 99, couleur: "rgba(240,72,72,.12)" },
    ],
    etiquettes: { 0: dateFR(serie[0].date, { day: "numeric", month: "short" }), [n - 1]: "Auj." },
  });
  $("#acwr-note").textContent = "Vert : 0,8—1,3 optimal · orange : vigilance · rouge : danger au-delà de 1,5"
    + " · valeurs au-delà de 2 écrêtées (point rouge)";
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
// Filtres : « Tous » puis une puce par catégorie présente sur la période
function rendreFiltres() {
  const presentes = new Set(seances.map(s => sportInfo(s.sport_id).categorie));
  if (categorie && !presentes.has(categorie)) categorie = "";
  const ordre = Object.keys(CATALOGUE?.categories || {}).filter(c => presentes.has(c));
  $("#categories").innerHTML = [["", "Tous"], ...ordre.map(c => [c, libelleCategorie(c)])]
    .map(([v, l]) => `<button type="button" data-v="${esc(v)}" class="${v === categorie ? "actif" : ""}">${esc(l)}</button>`).join("");
  $$("#categories button").forEach(b => {
    b.onclick = () => { categorie = b.dataset.v; affichees = PAGE; rendreFiltres(); rendreListe(); };
  });
}

async function rendreListe() {
  // L'API renvoie déjà les séances de la plus récente à la plus ancienne
  const liste = seances.filter(s => !categorie || sportInfo(s.sport_id).categorie === categorie);
  const el = $("#liste");
  if (!liste.length) { el.innerHTML = `<div class="vide" style="padding:10px 0">Aucune séance sur la période.</div>`; return; }
  const visibles = liste.slice(0, affichees);
  el.innerHTML = "";
  for (const s of visibles) {
    const b = document.createElement("button");
    b.className = "liste-ligne";
    b.innerHTML = `${iconeSport(s.sport_id)}
      <div class="seance-corps"><div class="seance-type">${esc(titreRealisee(s))}</div>
        <div class="seance-detail">${esc(dateFR(s.date_debut, { weekday: "short", day: "numeric", month: "short" }))} · ${esc(duree(s.duree_min))}${s.distance_km ? " · " + nb(s.distance_km, 1, "km") : ""}${s.source === "manuel" ? " · saisie" : ""}${s.prevue_le ? ` · prévue ${dateFR(s.prevue_le, { weekday: "long" })}` : ""}</div></div>
      <div class="seance-droite">${verdictHTML(s.verdict)}${pastillePreciser(s)}<i class="ti ti-chevron-right muted"></i></div>`;
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

$$("#periode button").forEach(b => {
  b.onclick = () => { semaines = Number(b.dataset.v); stockage.ecrire("periode", semaines); charger(); };
});

// Détail d'une séance : feuille partagée (seance.js), la liste se relit après une liaison
const ouvrir = id => ouvrirSeance(id, { apresChangement: charger });

// ---- Recalcul des verdicts (logique de seuils actuelle, sans appel au coach) -------------------------
$("#recalculer").onclick = async () => {
  if (!confirm("Recalculer le verdict de toutes les séances avec les seuils actuels ? Le texte des analyses ne change pas.")) return;
  const b = $("#recalculer"), zone = $("#recalcul-resultat");
  b.disabled = true;
  zone.textContent = "Recalcul en cours…";
  try {
    const r = await api("POST", "/api/admin/recalculate");
    const n = r.changements.length;
    const liens = (r.liaisons_corrigees || []).map(l => `${l.planifiee} : ${l.avant || "—"} → ${l.apres || "hors plan"}`);
    zone.textContent = `${r.seances} séance(s) recalculée(s), ${n} verdict(s) modifié(s), ${liens.length} liaison(s) corrigée(s)`
      + (liens.length ? ` (${liens.join(" ; ")})` : "") + ".";
    await charger();                                           // relecture des verdicts à jour
  } catch (e) { erreurSimple(zone, e); }
  finally { b.disabled = false; }
};

// ---- Codes d'activité appris (Suunto, Strava) → sport du catalogue ------------------------------------
const SOURCES = { suunto_json: "Suunto", strava: "Strava" };
$("#correspondances").onclick = () => feuilleCorrespondances();

async function feuilleCorrespondances() {
  const d = feuille(`<h2>Codes d'activité appris</h2>
    <p class="secondaire" style="margin:0 0 10px">Code reçu de la montre → sport. Toucher une ligne pour corriger.</p><div id="corr"></div>`);
  const zone = $("#corr", d);
  try {
    const [liste] = await Promise.all([api("GET", "/api/correspondances"), CATALOGUE_PRET]);
    zone.innerHTML = liste.map(c => `<button type="button" class="picker-sport" data-source="${esc(c.source)}" data-code="${esc(c.code)}" data-n="${c.seances}">
        ${iconeSport(c.sport_id)}<span>${esc(SOURCES[c.source] || c.source)} ${esc(c.code)} → <b>${esc(c.libelle)}</b>
        <span class="sous-texte">${c.seances} séance${c.seances > 1 ? "s" : ""}</span></span><i class="ti ti-pencil muted"></i></button>`).join("")
      || `<div class="vide">Aucun code appris.</div>`;
    $$("[data-code]", zone).forEach(b => b.onclick = async () => {
      const { source, code } = b.dataset, n = Number(b.dataset.n);
      const id = await choisirSport({ titre: `Code ${code} : quel sport ?` });
      if (!id) return feuilleCorrespondances();
      const reaffecter = n > 0 && confirm(`Réaffecter aussi les ${n} séance(s) déjà importée(s) avec ce code à « ${sportInfo(id).libelle} » ?`);
      try {
        await api("PUT", `/api/correspondances/${encodeURIComponent(source)}/${encodeURIComponent(code)}`, { sport_id: id, reaffecter });
        if (reaffecter) await charger();
      } catch (e) { alert(e.message); }
      feuilleCorrespondances();
    });
  } catch (e) { erreurSimple(zone, e); }
}

charger().then(() => {
  const ancre = location.hash.slice(1);
  if (/^\d+$/.test(ancre)) ouvrir(Number(ancre));
  else if (ancre === "admin") $("#admin").scrollIntoView({ block: "center" });
}).catch(e => erreurSimple($("#liste"), e));
chargerMuscu().catch(e => erreurSimple($("#muscu"), e));
