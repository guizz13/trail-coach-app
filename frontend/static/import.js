/* SENSEI — page Import */
"use strict";

coque();

const depot = $("#depot"), entree = $("#fichiers");
["dragenter", "dragover"].forEach(ev => depot.addEventListener(ev, e => { e.preventDefault(); depot.classList.add("survol"); }));
["dragleave", "drop"].forEach(ev => depot.addEventListener(ev, e => { e.preventDefault(); depot.classList.remove("survol"); }));
depot.addEventListener("drop", e => traiter([...e.dataTransfer.files]));
entree.addEventListener("change", () => { traiter([...entree.files]); entree.value = ""; });

async function traiter(fichiers) {
  fichiers = fichiers.filter(f => f.name.toLowerCase().endsWith(".json"));
  if (!fichiers.length) return;
  const zone = $("#cartes");
  const attente = document.createElement("div");
  zone.prepend(attente);
  reflexion(attente, `Lecture de ${fichiers.length} fichier${fichiers.length > 1 ? "s" : ""}…`);
  const fd = new FormData();
  fichiers.forEach(f => fd.append("fichiers", f));
  try {
    const [apercus, bruts] = await Promise.all([api("POST", "/api/import/apercu", fd), Promise.all(fichiers.map(lireJSON))]);
    attente.remove();
    apercus.map((a, i) => carte(a, fichiers[i], bruts[i])).reverse().forEach(c => zone.prepend(c));
  } catch (e) { erreurSimple(attente, e); }
}

// Lecture locale du fichier : sert uniquement à dessiner la trace GPS
async function lireJSON(f) {
  try { return JSON.parse(await f.text()); } catch { return null; }
}

function statsHTML(s, charge) {
  const st = (v, l) => `<div><b>${v}</b>${l}</div>`;
  return `<div class="stats-inline">
    ${st(esc(duree(s.duree_min)), "durée")}
    ${s.distance_km ? st(nb(s.distance_km, 2, "km"), "distance") : ""}
    ${s.d_plus_m ? st(nb(s.d_plus_m, 0, "m"), "D+") : ""}
    ${st(s.fc_moy_bpm ? `${s.fc_moy_bpm}` : "—", "FC moy")}
    ${st(s.recovery_time_h ? nb(s.recovery_time_h, 0, "h") : "—", "récupération estimée")}
    ${s.peak_training_effect ? st(nb(s.peak_training_effect, 1), "effet d'entraînement") : ""}
    ${st(nb(charge), "charge de la séance")}
  </div>`;
}

function formulaireMuscu(a) {
  const splits = ["push_a", "pull_a", "push_b", "pull_b", "jambes"];
  return `<label>Split</label>
    <div class="segments" data-split>${splits.map(s =>
      `<button type="button" data-v="${s}" class="${s === a.split_propose ? "actif" : ""}">${SPLITS[s]}</button>`).join("")}</div>
    <label>Groupes musculaires</label>
    <div class="grille-coches">${a.groupes_muscu.map(g =>
      `<label class="coche"><input type="checkbox" name="groupes" value="${esc(g)}">${esc(GROUPES[g] || g)}</label>`).join("")}</div>
    <details><summary><i class="ti ti-plus"></i> Ajouter des charges</summary>
      <div class="champs-4 sous-texte" style="margin-top:8px"><span>exercice</span><span>kg</span><span>reps</span><span>séries</span></div>
      ${[0, 1, 2].map(() => `<div class="champs-4" data-charge style="margin-top:6px">
        <input name="exo" placeholder="exercice"><input name="kg" inputmode="decimal"><input name="reps" inputmode="numeric"><input name="series" inputmode="numeric">
      </div>`).join("")}
    </details>`;
}

function carte(a, fichier, brut) {
  const el = document.createElement("div");
  el.className = "carte";
  el.style.marginBottom = "8px";
  if (a.erreur) { el.innerHTML = `<div class="seance-type">${esc(a.nom)}</div><div class="bandeau rouge">${esc(a.erreur)}</div>`; return el; }
  if (a.doublon) { el.innerHTML = `<div class="seance-type">${esc(a.nom)}</div><div class="bandeau gris">Déjà importé — ignoré</div>`; return el; }

  const s = a.seance, disc = disciplineFamille(s.famille);
  const estCourse = disc === "course";
  const trace = s.a_gps && brut ? traceSuunto(brut) : null;
  const titre = estCourse && s.sous_type && s.sous_type !== "inconnu" ? `${FAMILLES[s.famille]} · ${libelleType(s.sous_type)}` : FAMILLES[s.famille] || s.famille;
  const typesFamille = a.familles.filter(f => f !== "inconnu");

  el.innerHTML = `
    <div class="seance" style="cursor:default">${iconeDisc(disc)}
      <div class="seance-corps"><div class="seance-type">${esc(titre)}</div>
        <div class="seance-detail">${esc(dateFR(s.date_debut, { weekday: "long", day: "numeric", month: "long" }))} · ${esc(heure(s.date_debut))}</div></div>
      ${trace ? svgTrace(trace, 50, 35) : ""}
    </div>
    ${statsHTML(s, a.charge)}
    ${s.a_fc ? barreZones(zonesDepuisPct(s.temps_zones_pct)) : `<div class="bandeau gris">Pas de fréquence cardiaque dans ce fichier.</div>`}
    <form>
      ${a.demander_famille ? `<div class="bandeau orange">Type d'activité ${s.activity_type_code} inconnu : choisir la discipline (mémorisée pour la suite).</div>
        <label>Discipline</label><select name="famille" required><option value="">—</option>${typesFamille.map(f => `<option value="${f}">${esc(FAMILLES[f])}</option>`).join("")}</select>` : ""}
      ${estCourse && a.demander_sous_type ? `<div class="bandeau orange">Type détecté : <b>${esc(libelleType(s.sous_type))}</b> — corriger ?</div>
        <select name="sous_type" style="margin-top:8px">${a.sous_types.map(t => `<option value="${t}" ${t === s.sous_type ? "selected" : ""}>${esc(libelleType(t))}</option>`).join("")}</select>` : ""}
      ${s.famille === "muscu" ? formulaireMuscu(a) : ""}
      <button type="submit" class="btn principal" style="margin-top:14px"></button>
    </form>
    <div class="resultat"></div>`;

  const form = $("form", el), bouton = $("button[type=submit]", form);
  const libelleBouton = () => { bouton.textContent = $("#avec-llm").checked ? "Importer et analyser" : "Importer"; };
  libelleBouton();
  $("#avec-llm").addEventListener("change", libelleBouton);
  $$("[data-split] button", el).forEach(b => b.onclick = () => {
    $$("[data-split] button", el).forEach(x => x.classList.toggle("actif", x === b));
  });

  form.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(form);
    const opts = { analyser: $("#avec-llm").checked };
    if (fd.get("famille")) opts.famille = fd.get("famille");
    if (fd.get("sous_type")) opts.sous_type = fd.get("sous_type");
    if (s.famille === "muscu") {
      opts.muscu_detail = {
        split: $("[data-split] .actif", el)?.dataset.v || a.split_propose,
        groupes: fd.getAll("groupes"),
        charges: $$("[data-charge]", el).map(l => Object.fromEntries($$("input", l).map(i => [i.name, i.value]))),
      };
    }
    const envoi = new FormData();
    envoi.append("fichier", fichier);
    envoi.append("options", JSON.stringify(opts));
    const res = $(".resultat", el);
    bouton.disabled = true;
    reflexion(res, opts.analyser ? "Sensei réfléchit…" : "Import…");
    try {
      const r = await api("POST", "/api/import", envoi);
      if (!r.doublon && trace) stockage.ecrire("trace:" + r.seance.fichier_hash, trace);
      form.remove();
      afficherResultat(res, r, opts.analyser);
    } catch (err) {
      bouton.disabled = false;
      res.innerHTML = "";
      res.appendChild(carteErreurLLM({ type: "reseau", message: err.message }, () => form.requestSubmit()));
    }
  };
  return el;
}

function afficherResultat(el, r, analyseDemandee) {
  if (r.doublon) { el.innerHTML = `<div class="bandeau gris">Déjà importé — ignoré</div>`; return; }
  const a = r.analyse_llm, acwr = r.indicateurs.acwr;
  const signaux = (r.indicateurs.signaux || []).map(s => `<li>${esc(s.detail)}</li>`).join("");
  const appliques = Object.fromEntries((r.ajustements_appliques || []).map(x => [x.jour + x.seance_proposee, x]));
  const ajustements = (r.ajustements || []).map(x => {
    const ap = appliques[x.jour + x.seance_proposee];
    return `<div class="ajustement"><b style="text-transform:capitalize">${esc(x.jour)}</b> · ${esc(x.seance_initiale)}
      <span class="fleche">→</span> <b>${esc(x.seance_proposee)}</b>
      <div class="sous-texte">${esc(x.raison)}${ap ? ap.applique ? " · appliqué" : ` · non appliqué (${esc(ap.motif)})` : ""}</div></div>`;
  }).join("");

  el.innerHTML = `<div class="verdict-carte">
      <div class="tete ${r.verdict}"><span>${VERDICTS[r.verdict]}</span><span>Équilibre ${acwr.ratio == null ? "—" : nb(acwr.ratio, 2)}</span></div>
      <div class="corps">
        ${a ? texteReplie(a.analyse) : ""}
        ${signaux ? `<ul class="sous-texte" style="padding-left:16px;margin:0 0 8px">${signaux}</ul>` : ""}
        ${r.prevu ? `<div class="sous-texte">Rattachée à la séance prévue : ${esc(libelleType(r.prevu.type))}</div>` : `<div class="sous-texte">Aucune séance prévue ce jour-là.</div>`}
        ${ajustements ? `<div class="section-label" style="margin-top:12px">Ajustements proposés</div>${ajustements}` : ""}
        ${r.validation_requise ? `<div class="boutons"><button class="btn" data-d="0">Garder le plan</button><button class="btn principal" data-d="1">Accepter</button></div><div class="decision"></div>` : ""}
      </div></div>`;
  if (r.erreur_llm) {
    el.appendChild(carteErreurLLM(r.erreur_llm));
    el.insertAdjacentHTML("beforeend", `<div class="sous-texte" style="margin-top:6px">La séance est enregistrée ; seule l'analyse du coach a échoué.</div>`);
  } else if (!analyseDemandee) {
    el.insertAdjacentHTML("beforeend", `<div class="sous-texte" style="margin-top:6px">Séance enregistrée sans analyse du coach.</div>`);
  }
  $$("[data-d]", el).forEach(b => b.onclick = async () => {
    const zone = $(".decision", el);
    try {
      const d = await api("POST", `/api/analyses/${r.analyse_id}/decision`, { accepter: b.dataset.d === "1" });
      $$("[data-d]", el).forEach(x => { x.disabled = true; });
      zone.innerHTML = `<div class="bandeau ${d.accepte ? "vert" : "gris"}">${d.accepte ? "Ajustements appliqués au planning." : "Plan initial conservé."}</div>`;
    } catch (e) { erreurSimple(zone, e); }
  });
}
