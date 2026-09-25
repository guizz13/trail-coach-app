/* SENSEI — page Préparer (bilan du dimanche) */
"use strict";

coque();

const form = $("#form");
const CRENEAUX_SQUASH = { soir: "soir", midi: "midi", journee: "journée" };
let bilan = null, seances = [], sante = "100%";

// ---- Formulaire des impératifs ------------------------------------------------
$("#squash").innerHTML = JOURS.map((j, i) => `<div class="ligne entre" style="${i ? "margin-top:8px" : ""}">
    <label class="coche" style="flex:1"><input type="checkbox" name="sq-${j}"><span style="text-transform:capitalize">${j}</span></label>
    <select name="sqc-${j}" style="width:130px">${Object.entries(CRENEAUX_SQUASH).map(([v, l]) =>
      `<option value="${v}" ${(i >= 5 ? v === "journee" : v === "soir") ? "selected" : ""}>${l}</option>`).join("")}</select>
  </div>`).join("");

function ajouterContrainte(c = {}) {
  const d = document.createElement("div");
  d.className = "contrainte";
  d.style.marginBottom = "12px";
  d.innerHTML = `<div class="champs-2">
      <select name="jour">${JOURS.map(j => `<option value="${j}" ${j === c.jour ? "selected" : ""}>${j}</option>`).join("")}</select>
      <select name="creneau">${Object.entries(CRENEAUX).map(([v, l]) => `<option value="${v}" ${v === c.creneau ? "selected" : ""}>${l}</option>`).join("")}</select>
    </div>
    <div class="ligne" style="margin-top:6px"><input name="raison" value="${esc(c.raison || "")}" placeholder="déplacement, réunion…">
      <button type="button" class="btn-icone" aria-label="Retirer"><i class="ti ti-x"></i></button></div>`;
  $("button", d).onclick = () => d.remove();
  $("#contraintes").appendChild(d);
}
$("#ajout-contrainte").onclick = () => ajouterContrainte();
["ressenti", "sommeil"].forEach(n => { form[n].oninput = () => { $("#v-" + n).textContent = form[n].value; }; });

function choisirSante(v) {
  sante = v;
  $$("#sante button").forEach(b => b.classList.toggle("actif", b.dataset.v === v));
  $("#zone-sante").classList.toggle("hidden", v === "100%");
}
$$("#sante button").forEach(b => { b.onclick = () => choisirSante(b.dataset.v); });

function lireImperatifs() {
  const fd = new FormData(form);
  const zone = (fd.get("zone") || "").trim();
  if (sante !== "100%" && !zone) throw new Error("Préciser la zone concernée.");
  return {
    semaine_debut: fd.get("semaine_debut"),
    squash: JOURS.filter(j => fd.get("sq-" + j)).map(j => ({ jour: j, creneau: fd.get("sqc-" + j) })),
    contraintes: $$(".contrainte").map(c => ({ jour: $("[name=jour]", c).value, creneau: $("[name=creneau]", c).value,
      raison: $("[name=raison]", c).value.trim() })).filter(c => c.raison),
    ressenti: Number(fd.get("ressenti")), sommeil: Number(fd.get("sommeil")),
    statut_sante: sante === "100%" ? "100%" : `${sante}:${zone}`,
    notes: fd.get("notes"),
  };
}

async function init() {
  const d = await api("GET", "/api/dimanche");
  form.semaine_debut.value = d.semaine_debut;
  const [niveau, zone] = (d.profil.statut_sante || "100%").split(":");
  choisirSante(niveau);
  form.zone.value = zone || "";
  const imp = d.imperatifs;
  if (!imp) return;
  (imp.squash_jours || []).forEach(x => { form["sq-" + x.jour].checked = true; form["sqc-" + x.jour].value = x.creneau; });
  (imp.contraintes || []).forEach(ajouterContrainte);
  ["ressenti", "sommeil"].forEach(n => { if (imp[n]) { form[n].value = imp[n]; $("#v-" + n).textContent = imp[n]; } });
  form.notes.value = imp.notes || "";
}

form.onsubmit = e => { e.preventDefault(); generer(); };

async function generer() {
  const res = $("#resultat");
  let imperatifs;
  try { imperatifs = lireImperatifs(); } catch (err) { erreurSimple(res, err); return; }
  $("#generer").disabled = true;
  reflexion(res);
  res.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    bilan = await api("POST", "/api/bilan", imperatifs);
    afficher();
  } catch (err) {
    res.innerHTML = "";
    res.appendChild(carteErreurLLM({ type: "reseau", message: err.message }, generer));
  } finally { $("#generer").disabled = false; }
}

// ---- Résultat ------------------------------------------------------------------
const liste = (titre, items) => items && items.length
  ? `<div class="section-label" style="margin-top:14px">${titre}</div>${items.map(i => `<div class="seance-detail" style="-webkit-line-clamp:unset;margin-top:4px">· ${esc(i)}</div>`).join("")}` : "";

function afficher() {
  const res = $("#resultat");
  if (!bilan.reponse) { res.innerHTML = ""; res.appendChild(carteErreurLLM(bilan.erreur_llm, generer)); return; }
  const r = bilan.reponse, b = r.bilan || {}, pp = r.position_prepa, ss = r.semaine_suivante || {};
  seances = (ss.seances || []).map(s => ({ ...s }));
  const st = (v, l) => `<div><b>${v}</b>${l}</div>`;
  res.innerHTML = `
    <div class="section-label">Semaine écoulée</div>
    <div class="carte">
      <p style="margin:0;line-height:1.5;color:#C8C8CC">${esc(b.resume)}</p>
      <div class="stats-inline">
        ${st(nb(b.volume_course_km, 1, "km"), "course")}${st(nb(b.d_plus_m, 0, "m"), "D+")}
        ${st(`<span style="color:${couleurRatio(b.acwr)}">${nb(b.acwr, 2)}</span>`, "équilibre de charge")}
        ${st(nb(bilan.indicateurs.charge_semaine), "charge")}
      </div>
      ${b.distribution_zones ? barreZones(b.distribution_zones) : ""}
      ${liste("Séances manquées", b.seances_manquees)}${liste("Points positifs", b.points_positifs)}${liste("Points de vigilance", b.points_de_vigilance)}
    </div>
    ${pp ? `<div class="carte"><div class="metrique"><span class="label">Position dans la prépa</span></div>
      <div class="ligne" style="margin-top:6px"><span class="badge orange">${esc(PHASES[pp.phase] || pp.phase)} ${esc(pp.semaine || "")}</span></div>
      <p class="seance-detail" style="-webkit-line-clamp:unset;margin:8px 0 0">${esc(pp.avance_retard || "")}</p>
      <p style="margin:6px 0 0;color:#C8C8CC">${esc(pp.decision || "")}</p></div>` : ""}
    ${messageCoach(r.message_coach)}
    <div class="ligne entre"><div class="section-label">Semaine proposée</div>
      <button type="button" class="btn petit" id="ajout-seance" style="margin-top:14px"><i class="ti ti-plus"></i>Séance</button></div>
    ${ss.objectif ? `<div class="secondaire" style="margin-bottom:8px">${esc(ss.objectif)}</div>` : ""}
    <div id="proposition"></div>
    ${(ss.alternatives || []).length ? `<div class="carte" style="margin-top:8px"><div class="metrique"><span class="label">Plans B</span></div>
      ${ss.alternatives.map(a => `<div class="seance-detail" style="-webkit-line-clamp:unset;margin-top:6px">Si ${esc(a.si)} → ${esc(a.alors)}</div>`).join("")}</div>` : ""}
    <div id="regles"></div>
    <div class="boutons"><button type="button" class="btn" id="modifier">Modifier</button><button type="button" class="btn principal" id="valider">Valider</button></div>
    <div id="validation"></div>`;
  rendreProposition();
  afficherRegles(bilan.regles);
  $("#ajout-seance").onclick = () => editer(null);
  $("#modifier").onclick = () => form.scrollIntoView({ behavior: "smooth" });
  $("#valider").onclick = valider;
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

// Édition locale d'une séance proposée (k = index, null = nouvelle)
function editer(k) {
  const s = k == null ? { jour: "lundi", creneau: "matin", type: "EF", detail: "", intensite: "", duree_min: 45 } : seances[k];
  const types = TYPES_PLANIFIABLES.includes(s.type) ? TYPES_PLANIFIABLES : [s.type, ...TYPES_PLANIFIABLES];
  const opt = (l, v, lib = {}) => l.map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lib[x] || x)}</option>`).join("");
  const d = feuille(`<h2>${k == null ? "Ajouter une séance" : "Modifier la séance"}</h2>
    <form>
      <div class="champs-2">
        <div><label>Jour</label><select name="jour">${opt(JOURS, s.jour)}</select></div>
        <div><label>Créneau</label><select name="creneau">${opt(Object.keys(CRENEAUX), s.creneau, CRENEAUX)}</select></div>
      </div>
      <label>Type</label><select name="type">${opt(types, s.type, TYPES)}</select>
      <div class="champs-2">
        <div><label>Durée (min)</label><input type="number" inputmode="numeric" name="duree_min" value="${esc(s.duree_min ?? "")}"></div>
        <div><label>Intensité</label><input name="intensite" value="${esc(s.intensite || "")}"></div>
      </div>
      <label>Détail</label><textarea name="detail">${esc(s.detail || "")}</textarea>
      <div class="boutons">${k == null ? "" : `<button type="button" class="btn danger" data-suppr>Retirer</button>`}
        <button type="submit" class="btn principal">OK</button></div>
    </form>`);
  $("form", d).onsubmit = e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    v.duree_min = v.duree_min === "" ? null : Number(v.duree_min);
    if (k == null) seances.push(v); else Object.assign(seances[k], v);
    d.close(); rendreProposition(); verifier();
  };
  const sup = $("[data-suppr]", d);
  if (sup) sup.onclick = () => { seances.splice(k, 1); d.close(); rendreProposition(); verifier(); };
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

async function valider() {
  const el = $("#validation");
  try {
    const v = await api("POST", `/api/bilan/${bilan.analyse_id}/valider`, { seances });
    el.innerHTML = `<div class="bandeau vert">Semaine du ${esc(dateFR(v.semaine_debut, { day: "numeric", month: "long" }))} enregistrée (${v.nb_seances} séances). <a href="/">Voir le planning</a></div>`;
    $("#valider").disabled = true;
  } catch (e) { erreurSimple(el, e); }
}

init().catch(e => erreurSimple($("#resultat"), e));
