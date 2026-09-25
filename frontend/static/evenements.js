/* SENSEI — page Objectifs */
"use strict";

const aujourdhui = isoJour(new Date());
coque(`<span class="secondaire" style="text-transform:capitalize">${new Date().toLocaleDateString("fr-FR", { month: "long", year: "numeric" })}</span>`);

let etat = null;

async function charger() {
  etat = await api("GET", "/api/evenements");
  const prochainA = etat.evenements.find(e => e.priorite === "A");
  $("#mode").innerHTML = `<span class="badge ${etat.profil.mode_actif === "RACE_PREP" ? "orange" : "accent"}">${esc(libelleMode(etat.profil, prochainA))}</span>`;
  rendreTimeline(); rendrePrincipal(); rendrePlan(); rendreAutres();
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

// ---- Objectif principal ---------------------------------------------------------------
const principalDe = evts => evts.find(e => e.priorite === "A") || null;
const SEMAINES_PREPA = { A: 12, B: 6 };
const ICONES_EVT = { trail_race: "ti-run", squash_competition: "ti-ball-tennis", other: "ti-calendar-event" };

// Bouton d'import GPX d'un objectif : le profil d'altitude reste sur l'appareil
function boutonGPX(e, apres) {
  const l = document.createElement("label");
  l.className = "btn petit";
  l.style.cssText = "margin-top:12px;display:inline-flex;text-transform:none;letter-spacing:0;font-size:13px;color:var(--text-primary)";
  l.innerHTML = `<i class="ti ti-route"></i>Importer la trace GPX<input type="file" accept=".gpx,application/gpx+xml" class="hidden">`;
  l.onclick = ev => ev.stopPropagation();
  const input = $("input", l);
  input.onchange = async () => {
    try { const t = lireGPX(await input.files[0].text()); if (t.profil) stockage.ecrire("gpx:" + e.id, t.profil); apres(); }
    catch (err) { alert(err.message); }
  };
  return l;
}

function rendrePrincipal() {
  const el = $("#principal"), e = principalDe(etat.evenements);
  if (!e) {
    el.innerHTML = `<div class="carte vide">Aucun objectif principal. Ajoute un trail en « Objectif principal » avec le bouton +.</div>`;
    return;
  }
  const profil = stockage.lire("gpx:" + e.id);
  const sem = SEMAINES_PREPA[e.priorite];
  el.innerHTML = `<div class="carte objectif-principal">
      <div class="ligne entre" style="align-items:flex-start">
        <div style="min-width:0"><div class="nom">${esc(e.titre)}</div>
          <div class="date">${esc(dateFR(e.date_evt, { weekday: "long", day: "numeric", month: "long", year: "numeric" }))}</div>
          <span class="badge orange" style="margin-top:8px">${esc(PRIORITES.A)}</span></div>
        <div class="compte">J-${joursEntre(aujourdhui, e.date_evt)}</div>
      </div>
      <div class="ligne entre" style="align-items:flex-end">
        <div class="stats-grandes">
          ${e.distance_km ? `<div><b>${nb(e.distance_km, 1)}</b><span>km</span></div>` : ""}
          ${e.dplus_m ? `<div><b>${nb(e.dplus_m)}</b><span>m D+</span></div>` : ""}
          ${sem ? `<div><b>${sem}</b><span>sem. prépa</span></div>` : ""}
        </div>
        ${profil ? svgProfil(profil, 80, 35, "var(--orange)") : ""}
      </div>
    </div>`;
  const carte = $(".objectif-principal", el);
  if (e.type === "trail_race" && !profil) carte.appendChild(boutonGPX(e, rendrePrincipal));
  carte.onclick = () => ouvrirModale(e);
}

// ---- Plan de préparation : cartes compactes -----------------------------------------------
// Les repères chiffrés sont lus dans le texte « objectif » (format fixé par le system prompt §10.3)
function plage(m) {
  if (!m) return null;
  const n = x => nb(Number(String(x).replace(/\s/g, "")));
  return m[2] ? `${n(m[1])} — ${n(m[2])}` : n(m[1]);
}
function reperesPhase(p) {
  const t = p.objectif || "";
  const nombre = "(\\d[\\d\\s\\u202f]*?)";
  const ecart = `${nombre}(?:\\s*(?:-|–|—|à)\\s*${nombre})?`;
  const volume = t.match(new RegExp(`volume\\D{0,12}?${ecart}\\s*km`, "i")) || t.match(new RegExp(`${ecart}\\s*km\\s*\\/\\s*sem`, "i"));
  const dplus = t.match(new RegExp(`D\\+\\D{0,12}?${ecart}\\s*m\\b`, "i"));
  const squash = t.match(/squash\D{0,12}?(\d+)\s*\/\s*sem/i);
  return {
    volume: plage(volume) && `${plage(volume)} km`,
    dplus: plage(dplus) && `${plage(dplus)} m`,
    longue: p.sortie_longue_cible || null,
    squash: squash ? `${squash[1]}/sem` : null,
  };
}

function rendrePlan() {
  const el = $("#plan"), ph = etat.plan_prepa;
  if (!ph.length) { el.innerHTML = `<div class="carte vide">Pas de plan de préparation : entraînement libre.</div>`; return; }
  el.innerHTML = "";
  for (const p of ph) {
    const r = reperesPhase(p);
    const donnees = [["Volume", r.volume], ["D+", r.dplus], ["Longue", r.longue], ["Squash", r.squash]]
      .filter(([, v]) => v).map(([l, v]) => `<span>${l} <b>${esc(v)}</b></span>`).join("");
    const c = document.createElement("div");
    c.className = `phase-carte ${esc(p.phase)}-c`;
    c.innerHTML = `<div class="phase-barre"></div>
      <div class="phase-corps">
        <div class="ligne entre"><span class="badge">${esc(PHASES[p.phase] || p.phase)}</span>
          <span class="sous-texte">${esc(dateFR(p.du, { day: "numeric", month: "short" }))} → ${esc(dateFR(p.au, { day: "numeric", month: "short" }))}</span></div>
        ${donnees ? `<div class="phase-donnees">${donnees}</div>` : ""}
        ${p.objectif ? `<button type="button" class="phase-details">Détails</button><div class="phase-texte hidden">${esc(p.objectif)}</div>` : ""}
      </div>`;
    const b = $(".phase-details", c);
    if (b) b.onclick = () => { const t = $(".phase-texte", c); t.classList.toggle("hidden"); b.textContent = t.classList.contains("hidden") ? "Détails" : "Masquer"; };
    el.appendChild(c);
  }
}

// ---- Autres objectifs : une ligne chacun ------------------------------------------------------
function rendreAutres() {
  const principal = principalDe(etat.evenements);
  const autres = etat.evenements.filter(e => e !== principal);
  $("#bloc-autres").classList.toggle("hidden", !autres.length);
  const el = $("#autres");
  el.innerHTML = "";
  for (const e of autres) {
    const b = document.createElement("button");
    b.className = "objectif-ligne";
    b.innerHTML = `<span class="type-carre ${esc(e.type)}"><i class="ti ${ICONES_EVT[e.type] || ICONES_EVT.other}"></i></span>
      <div class="seance-corps"><div class="seance-type">${esc(e.titre)}</div>
        <div class="seance-detail">${esc(dateFR(e.date_evt, { weekday: "short", day: "numeric", month: "short", year: "numeric" }))} · J-${joursEntre(aujourdhui, e.date_evt)}${lieuDe(e) ? " · " + esc(lieuDe(e)) : ""}</div></div>
      ${e.type === "trail_race" ? `<span class="badge ${CLASSE_PRIORITE[e.priorite]}">${esc(PRIORITES[e.priorite])}</span>` : ""}`;
    b.onclick = () => ouvrirModale(e);
    el.appendChild(b);
  }
}

// ---- Modale d'ajout / de modification ---------------------------------------------------------
const TYPES_MODALE = [["trail_race", "Trail", "ti-run"], ["squash_competition", "Squash", "ti-ball-tennis"], ["other", "Autre", "ti-calendar-event"]];

// Le lieu d'une compétition squash n'a pas de colonne en base : il est rangé en tête des notes
const RE_LIEU = /^Lieu : (.*)(?:\n|$)/;
function separerLieu(notes) {
  const m = (notes || "").match(RE_LIEU);
  return m ? { lieu: m[1], notes: notes.slice(m[0].length) } : { lieu: "", notes: notes || "" };
}
const lieuDe = e => separerLieu(e.notes).lieu;

function ouvrirModale(e) {
  const init = e ? separerLieu(e.notes) : { lieu: "", notes: "" };
  const etatM = { type: e ? e.type : "trail_race", priorite: e ? e.priorite : "B", profil: null };
  const d = feuille(`
    <div class="ligne entre modale-tete"><h2>${e ? "Modifier l'objectif" : "Nouvel objectif"}</h2>
      <button type="button" class="btn-icone" data-fermer aria-label="Fermer"><i class="ti ti-x"></i></button></div>
    <form class="modale">
      <div class="choix-type">${TYPES_MODALE.map(([v, l, i]) => `<button type="button" data-type="${v}"><i class="ti ${i}"></i>${l}</button>`).join("")}</div>
      <div data-importance><label>Importance</label>
        <div class="choix-importance">${Object.entries(PRIORITES).map(([v, l]) => `<button type="button" data-prio="${v}">${esc(l)}</button>`).join("")}</div></div>
      <label>Nom</label><input name="titre" value="${esc(e ? e.titre : "")}" required>
      <label>Date</label><input type="date" name="date_evt" value="${esc(e ? e.date_evt : "")}" required>
      <div class="champs-2" data-trail>
        <div><label>Distance (km)</label><input name="distance_km" inputmode="decimal" value="${esc(e?.distance_km ?? "")}"></div>
        <div><label>D+ (m)</label><input name="dplus_m" inputmode="numeric" value="${esc(e?.dplus_m ?? "")}"></div>
      </div>
      <div data-trail><label>Trace GPX (optionnel)</label><input type="file" name="gpx" accept=".gpx,application/gpx+xml">
        <div class="sous-texte gpx-info">Distance et D+ sont remplis depuis la trace. Le profil reste sur cet appareil.</div></div>
      <div data-squash><label>Lieu</label><input name="lieu" value="${esc(init.lieu)}" placeholder="club, ville…"></div>
      <label>Notes</label><textarea name="notes">${esc(init.notes)}</textarea>
      <button type="submit" class="btn principal modale-valider">${e ? "Enregistrer" : "Ajouter cet objectif"}</button>
      ${e ? `<button type="button" class="btn danger" data-suppr style="margin-top:8px">Supprimer</button>` : ""}
    </form>`);
  const f = $("form", d);

  // Champs selon le type : importance, distance, D+ et GPX pour un trail seulement ; lieu pour le squash
  const adapter = () => {
    $$("[data-type]", d).forEach(b => b.classList.toggle("actif", b.dataset.type === etatM.type));
    $$("[data-prio]", d).forEach(b => b.classList.toggle("actif", b.dataset.prio === etatM.priorite));
    $("[data-importance]", d).classList.toggle("hidden", etatM.type !== "trail_race");
    $$("[data-trail]", d).forEach(x => x.classList.toggle("hidden", etatM.type !== "trail_race"));
    $("[data-squash]", d).classList.toggle("hidden", etatM.type !== "squash_competition");
  };
  $$("[data-type]", d).forEach(b => { b.onclick = () => { etatM.type = b.dataset.type; adapter(); }; });
  $$("[data-prio]", d).forEach(b => { b.onclick = () => { etatM.priorite = b.dataset.prio; adapter(); }; });
  adapter();

  f.gpx.onchange = async () => {
    try {
      const t = lireGPX(await f.gpx.files[0].text());
      f.distance_km.value = t.distance_km;
      f.dplus_m.value = t.dplus_m;
      etatM.profil = t.profil;
      $(".gpx-info", f).textContent = `Trace lue : ${nb(t.distance_km, 1)} km, ${nb(t.dplus_m)} m D+.`;
    } catch (err) { $(".gpx-info", f).textContent = err.message; }
  };

  $("[data-fermer]", d).onclick = () => d.close();
  f.onsubmit = ev => {
    ev.preventDefault();
    const trail = etatM.type === "trail_race";
    const lieu = f.lieu.value.trim();
    const notes = f.notes.value.trim();
    const v = {
      type: etatM.type, titre: f.titre.value, date_evt: f.date_evt.value,
      // Squash et autre : pas d'importance dans le formulaire, le backend applique sa valeur par défaut
      ...(trail ? { priorite: etatM.priorite, distance_km: f.distance_km.value, dplus_m: f.dplus_m.value } : {}),
      notes: etatM.type === "squash_competition" && lieu ? `Lieu : ${lieu}\n${notes}` : notes,
    };
    d.close();
    const req = e ? api("PUT", `/api/evenements/${e.id}`, v) : api("POST", "/api/evenements", v);
    executer(req, r => { if (trail && etatM.profil) stockage.ecrire("gpx:" + (e ? e.id : r.evenement.id), etatM.profil); });
  };
  const sup = $("[data-suppr]", d);
  if (sup) sup.onclick = () => {
    if (!confirm(`Supprimer « ${e.titre} » ?`)) return;
    d.close();
    executer(api("DELETE", `/api/evenements/${e.id}`), () => stockage.suppr("gpx:" + e.id));
  };
}

// Chaque modification déclenche la reconstruction du plan par le coach
async function executer(promesse, apres) {
  const zone = $("#reconstruction");
  chargeurIA(zone);
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
$("#ajouter").onclick = () => ouvrirModale(null);
charger().catch(e => erreurSimple($("#principal"), e));
