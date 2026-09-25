/* SENSEI — page Objectifs */
"use strict";

const aujourdhui = isoJour(new Date());
coque(`<span class="secondaire" style="text-transform:capitalize">${new Date().toLocaleDateString("fr-FR", { month: "long", year: "numeric" })}</span>`);

let etat = null;

async function charger() {
  etat = await api("GET", "/api/evenements");
  const prochainA = etat.evenements.find(e => e.priorite === "A");
  $("#mode").innerHTML = `<span class="badge ${etat.profil.mode_actif === "RACE_PREP" ? "orange" : "accent"}">${esc(libelleMode(etat.profil, prochainA))}</span>`;
  rendreTimeline(); rendreListe(); rendrePlan();
}

// ---- Timeline 6 mois ---------------------------------------------------------------
function rendreTimeline() {
  const debut = new Date(); debut.setDate(1); debut.setHours(12, 0, 0, 0);
  const fin = new Date(debut); fin.setMonth(fin.getMonth() + 6);
  const total = fin - debut;
  const pos = iso => Math.max(0, Math.min(100, 100 * (dateLocale(iso) - debut) / total));
  const mois = Array.from({ length: 6 }, (_, i) => {
    const m = new Date(debut); m.setMonth(m.getMonth() + i);
    const s = new Date(m); s.setMonth(s.getMonth() + 1);
    return { label: m.toLocaleDateString("fr-FR", { month: "short" }).replace(".", ""), larg: 100 * (s - m) / total, courant: i === 0 };
  });
  const finIso = isoJour(fin);
  const phases = etat.plan_prepa.filter(p => p.au >= isoJour(debut) && p.du < finIso);
  const evts = etat.evenements.filter(e => e.date_evt < finIso);
  $("#timeline").innerHTML = `
    <div class="tl-mois" style="grid-template-columns:${mois.map(m => m.larg + "%").join(" ")}">
      ${mois.map(m => `<span class="${m.courant ? "courant" : ""}">${esc(m.label)}</span>`).join("")}</div>
    <div class="tl-barre">
      <div class="tl-phase libre" style="left:0;right:0;border-radius:6px"></div>
      ${phases.map(p => { const g = pos(p.du), d = pos(p.au); return d > g
        ? `<div class="tl-phase ${esc(p.phase)}" style="left:${g}%;width:${d - g}%" title="${esc(PHASES[p.phase])}"></div>` : ""; }).join("")}
      <div class="tl-maintenant" style="left:${pos(aujourdhui)}%"></div>
      ${evts.map(e => `<span class="tl-evt ${esc(e.type)}" style="left:${pos(e.date_evt)}%" title="${esc(e.titre)}"></span>`).join("")}
    </div>
    <div class="tl-legende">
      <span><i style="background:rgba(79,142,247,.4)"></i>Libre</span>
      <span><i style="background:rgba(79,142,247,.7)"></i>Base</span>
      <span><i style="background:var(--orange);opacity:.7"></i>Build</span>
      <span><i style="background:var(--squash);opacity:.7"></i>Pic</span>
      <span><i style="background:var(--green);opacity:.7"></i>Affûtage</span>
      <span><i style="background:var(--orange)"></i>Trail</span>
      <span><i style="background:var(--squash)"></i>Squash</span>
    </div>`;
}

// ---- Liste des objectifs --------------------------------------------------------------
function dureePrepa(e) {
  if (e.type === "squash_competition") return "allègement J-3 à J-1";
  if (e.type !== "trail_race") return "";
  return { A: "prépa 12 semaines", B: "prépa 6 semaines", C: "affûtage court" }[e.priorite];
}

function rendreListe() {
  const el = $("#liste");
  if (!etat.evenements.length) { el.innerHTML = `<div class="carte vide">Aucun objectif à venir.</div>`; return; }
  el.innerHTML = "";
  for (const e of etat.evenements) {
    const profil = stockage.lire("gpx:" + e.id);
    const j = joursEntre(aujourdhui, e.date_evt);
    const c = document.createElement("div");
    c.className = `carte evenement ${e.type}`;
    c.innerHTML = `<div class="ligne entre" style="align-items:flex-start">
        <div style="min-width:0"><div class="nom">${esc(e.titre)}</div>
          <div class="sous-texte">${esc(TYPES_EVT[e.type])} · ${esc(dateFR(e.date_evt, { weekday: "short", day: "numeric", month: "long", year: "numeric" }))}</div></div>
        <div style="text-align:right"><div class="compte">J-${j}</div></div>
      </div>
      <div class="ligne entre" style="margin-top:10px;align-items:flex-end">
        <div>
          ${avecImportance(e.type) ? `<span class="badge ${CLASSE_PRIORITE[e.priorite]}">${esc(PRIORITES[e.priorite])}</span>` : ""}
          <div class="stats-inline">
            ${e.distance_km ? `<div><b>${nb(e.distance_km, 1)}</b>km</div>` : ""}
            ${e.dplus_m ? `<div><b>${nb(e.dplus_m)}</b>m D+</div>` : ""}
          </div>
          ${dureePrepa(e) ? `<div class="sous-texte" style="margin-top:6px"><i class="ti ti-calendar-time"></i> ${esc(dureePrepa(e))}</div>` : ""}
        </div>
        ${profil ? svgProfil(profil, 80, 40, e.type === "trail_race" ? "var(--orange)" : "var(--course)") : ""}
      </div>
      ${e.type === "trail_race" && !profil ? `<label class="btn petit" style="margin-top:10px;display:inline-flex;text-transform:none;letter-spacing:0;font-size:13px;color:var(--text-primary)">
        <i class="ti ti-route"></i>Importer la trace GPX<input type="file" accept=".gpx,application/gpx+xml" class="hidden"></label>` : ""}`;
    const gpx = $("input[type=file]", c);
    if (gpx) {
      gpx.onclick = ev => ev.stopPropagation();
      $("label", c).onclick = ev => ev.stopPropagation();
      gpx.onchange = async () => {
        try { const t = lireGPX(await gpx.files[0].text()); if (t.profil) stockage.ecrire("gpx:" + e.id, t.profil); rendreListe(); }
        catch (err) { alert(err.message); }
      };
    }
    c.onclick = () => editer(e);
    el.appendChild(c);
  }
}

function rendrePlan() {
  const ph = etat.plan_prepa;
  $("#plan").innerHTML = ph.length ? ph.map((p, i) => `<div class="${i ? "ajustement" : ""}" style="${i ? "" : "padding-bottom:8px"}">
      <div class="ligne entre"><span class="badge ${{ BASE: "accent", BUILD: "orange", PIC: "violet", AFFUTAGE: "vert" }[p.phase] || ""}">${esc(PHASES[p.phase] || p.phase)}</span>
        <span class="sous-texte">${esc(dateFR(p.du, { day: "numeric", month: "short" }))} → ${esc(dateFR(p.au, { day: "numeric", month: "short" }))}</span></div>
      ${p.objectif ? `<div class="secondaire" style="margin-top:6px">${esc(p.objectif)}</div>` : ""}
      ${p.sortie_longue_cible ? `<div class="sous-texte">Sortie longue : ${esc(p.sortie_longue_cible)}</div>` : ""}</div>`).join("")
    : `<div class="vide">Pas de plan de préparation : entraînement libre.</div>`;
}

// ---- Formulaire (ajout et modification) ------------------------------------------------
function champsHTML(e = {}) {
  const opt = (o, v) => Object.entries(o).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  return `<label style="margin-top:0">Type</label><select name="type">${opt(TYPES_EVT, e.type || "trail_race")}</select>
    <div class="champ-importance"><label>Importance</label><select name="priorite">${opt(PRIORITES, e.priorite || "B")}</select></div>
    <label>Nom</label><input name="titre" value="${esc(e.titre || "")}" required>
    <label>Date</label><input type="date" name="date_evt" value="${esc(e.date_evt || "")}" required>
    <div class="champs-2 champ-course">
      <div><label>Distance (km)</label><input name="distance_km" inputmode="decimal" value="${esc(e.distance_km ?? "")}"></div>
      <div><label>D+ (m)</label><input name="dplus_m" inputmode="numeric" value="${esc(e.dplus_m ?? "")}"></div>
    </div>
    <label>Notes</label><textarea name="notes">${esc(e.notes || "")}</textarea>
    <div class="champ-course"><label>Trace GPX (optionnel)</label><input type="file" name="gpx" accept=".gpx,application/gpx+xml">
    <div class="sous-texte gpx-info">Distance et D+ sont remplis depuis la trace. Le profil reste sur cet appareil.</div></div>`;
}

// Champs selon le type : distance/D+/GPX pour un trail seulement, importance masquée en squash
const avecDistance = type => type === "trail_race";
const avecImportance = type => type !== "squash_competition";
function brancherType(f) {
  const sel = f.elements.namedItem("type");
  const adapter = () => {
    $$(".champ-course", f).forEach(x => x.classList.toggle("hidden", !avecDistance(sel.value)));
    $(".champ-importance", f).classList.toggle("hidden", !avecImportance(sel.value));
  };
  sel.addEventListener("change", adapter);
  adapter();
}

// Lecture du GPX choisi : pré-remplit distance et D+, garde le profil en attente
function brancherGPX(f) {
  let profil = null;
  f.gpx.onchange = async () => {
    try {
      const t = lireGPX(await f.gpx.files[0].text());
      f.distance_km.value = t.distance_km;
      f.dplus_m.value = t.dplus_m;
      profil = t.profil;
      $(".gpx-info", f).textContent = `Trace lue : ${nb(t.distance_km, 1)} km, ${nb(t.dplus_m)} m D+.`;
    } catch (err) { $(".gpx-info", f).textContent = err.message; }
  };
  return () => profil;
}

function valeurs(f) {
  const v = Object.fromEntries(new FormData(f));
  delete v.gpx;
  // Un champ masqué ne doit pas envoyer une valeur saisie avant le changement de type
  if (!avecDistance(v.type)) { v.distance_km = ""; v.dplus_m = ""; }
  return v;
}

const form = $("#form");
function preparerForm() {
  form.innerHTML = champsHTML() + `<button type="submit" class="btn principal" style="margin-top:14px">Ajouter cet objectif</button>`;
  brancherType(form);
  const profil = brancherGPX(form);
  form.onsubmit = e => {
    e.preventDefault();
    executer(api("POST", "/api/evenements", valeurs(form)), r => {
      if (profil()) stockage.ecrire("gpx:" + r.evenement.id, profil());
      preparerForm();
    });
  };
}

function editer(e) {
  const d = feuille(`<h2>${esc(e.titre)}</h2><form>${champsHTML(e)}
    <div class="boutons"><button type="button" class="btn danger" data-suppr>Supprimer</button><button type="submit" class="btn principal">Enregistrer</button></div></form>`);
  const f = $("form", d);
  brancherType(f);
  const profil = brancherGPX(f);
  f.onsubmit = ev => {
    ev.preventDefault();
    d.close();
    executer(api("PUT", `/api/evenements/${e.id}`, valeurs(f)), () => { if (profil()) stockage.ecrire("gpx:" + e.id, profil()); });
  };
  $("[data-suppr]", d).onclick = () => {
    if (!confirm(`Supprimer « ${e.titre} » ?`)) return;
    d.close();
    executer(api("DELETE", `/api/evenements/${e.id}`), () => stockage.suppr("gpx:" + e.id));
  };
}

// Chaque modification déclenche la reconstruction du plan par le coach
async function executer(promesse, apres) {
  const zone = $("#reconstruction");
  reflexion(zone, "Sensei reconstruit le plan…");
  zone.scrollIntoView({ behavior: "smooth", block: "center" });
  try {
    const r = await promesse;
    apres && apres(r);
    await charger();
    afficherReconstruction(r.reconstruction || r);
  } catch (err) {
    zone.innerHTML = "";
    zone.appendChild(carteErreurLLM({ type: "reseau", message: err.message }));
  }
}

function afficherReconstruction(r) {
  const zone = $("#reconstruction");
  if (!r.reponse) {
    zone.innerHTML = "";
    zone.appendChild(carteErreurLLM(r.erreur_llm, () => executer(api("POST", "/api/reconstruire"))));
    return;
  }
  const x = r.reponse, conflit = x.analyse_conflits && !/^aucun/i.test(x.analyse_conflits.trim());
  zone.innerHTML = `<div class="bandeau ${conflit ? "orange" : "vert"}" style="margin-top:8px"><b>Conflits :</b> ${esc(x.analyse_conflits || "aucun")}</div>
    ${messageCoach(x.message_coach)}
    ${(x.evenements_integres || []).map(e => `<div class="carte" style="margin-top:8px"><div class="seance-type">${esc(e.evenement)}</div>
      <div class="sous-texte">${esc(PHASES[e.phase_concernee] || e.phase_concernee || "")}</div><div class="secondaire" style="margin-top:4px">${esc(e.impact)}</div></div>`).join("")}
    ${r.bascule_proposee ? `<div class="bandeau orange">Sensei recommande de passer en <b>${r.bascule_proposee.vers === "RACE_PREP" ? "préparation course" : "entraînement libre"}</b>${r.bascule_proposee.le ? " le " + esc(dateFR(r.bascule_proposee.le, { day: "numeric", month: "long" })) : ""}.
      <button type="button" class="btn principal" id="basculer" style="margin-top:10px">Changer de mode</button></div>` : ""}`;
  const b = $("#basculer");
  if (b) b.onclick = async () => {
    try { await api("PATCH", "/api/profil", { mode_actif: r.bascule_proposee.vers }); b.disabled = true; b.textContent = "Mode changé"; charger(); }
    catch (e) { erreurSimple(zone, e); }
  };
}

$("#reconstruire").onclick = () => executer(api("POST", "/api/reconstruire"));
preparerForm();
charger().catch(e => erreurSimple($("#liste"), e));
