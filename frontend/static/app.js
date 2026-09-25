/* Coach Hybride — utilitaires partagés (vanilla JS, aucune dépendance) */
"use strict";

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function api(methode, url, corps) {
  const opts = { method: methode, headers: {}, credentials: "same-origin" };
  if (corps instanceof FormData) opts.body = corps;
  else if (corps !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(corps);
  }
  const r = await fetch(url, opts);
  if (r.status === 401) {
    location.href = "/login?suite=" + encodeURIComponent(location.pathname);
    throw new Error("Session expirée");
  }
  const texte = await r.text();
  let data;
  try { data = texte ? JSON.parse(texte) : null; } catch { data = { detail: texte }; }
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d || data));
  }
  return data;
}

// ---------------------------------------------------------------------------
// Échappement & formatage
// ---------------------------------------------------------------------------
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const $ = (sel, racine = document) => racine.querySelector(sel);
const $$ = (sel, racine = document) => [...racine.querySelectorAll(sel)];

const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
const FAMILLES = {
  course_outdoor: "Course / trail", course_tapis: "Tapis", squash: "Squash",
  velo: "Vélo", muscu: "Musculation", autre: "Autre", inconnu: "Inconnu",
};
const TYPES_SEANCE = ["EF", "intervals", "tempo", "cotes", "sortie_longue", "squash",
  "muscu_push", "muscu_pull", "muscu_jambes", "velo", "repos"];
const CRENEAUX = ["matin", "midi", "soir", "journee"];
const STATUTS = { prevu: "prévu", realise: "réalisé ✓", manque: "manqué", modifie: "modifié" };

function duree(min) {
  if (min == null) return "—";
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}` : `${m} min`;
}
function nb(v, dec = 0, unite = "") {
  if (v == null || v === "") return "—";
  return Number(v).toLocaleString("fr-FR", { maximumFractionDigits: dec, minimumFractionDigits: 0 }) + (unite ? " " + unite : "");
}
function dateFR(iso, opts = { weekday: "short", day: "numeric", month: "short" }) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString("fr-FR", opts);
}
function heureFR(iso) {
  return iso && iso.length > 10 ? iso.slice(11, 16) : "";
}
function allure(minKm) {
  if (!minKm) return "—";
  const m = Math.floor(minKm), s = Math.round((minKm - m) * 60);
  return `${m}'${String(s).padStart(2, "0")}/km`;
}

function badgeVerdict(v) {
  if (!v) return "";
  return `<span class="verdict ${esc(v)}">${esc(v)}</span>`;
}
const VERDICT_ACWR = { sous_charge: "vert", optimal: "vert", vigilance: "orange", danger: "rouge" };
const LIBELLE_ACWR = { sous_charge: "sous-charge", optimal: "optimal", vigilance: "vigilance", danger: "danger" };

function chargement(el, texte = "Chargement…") {
  el.innerHTML = `<p class="muted"><span class="chargement"></span> ${esc(texte)}</p>`;
}
function erreur(el, e) {
  el.innerHTML = `<div class="alerte rouge">${esc(e.message || e)}</div>`;
}

// Erreur LLM : message + réponse brute (JSON invalide, plafond, clé absente…)
function blocErreurLLM(err) {
  if (!err) return "";
  const titre = { json_invalide: "Réponse du coach illisible (JSON invalide)", plafond: "Plafond mensuel LLM atteint" }[err.type]
    || `Analyse LLM indisponible (${err.type})`;
  return `<div class="alerte rouge"><b>${esc(titre)}</b><pre class="brut">${esc(err.message)}</pre></div>`;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function navigation() {
  const liens = [["/", "◉", "Semaine"], ["/import", "⤒", "Import"], ["/dimanche", "☷", "Dimanche"],
    ["/evenements", "⚑", "Événements"], ["/historique", "≋", "Historique"]];
  const nav = document.createElement("nav");
  nav.className = "barre";
  nav.innerHTML = liens.map(([h, i, t]) =>
    `<a href="${h}" class="${location.pathname === h ? "actif" : ""}"><span aria-hidden="true">${i}</span>${t}</a>`).join("")
    + `<form method="post" action="/logout"><button type="submit">Déconnexion</button></form>`;
  document.body.prepend(nav);
}
document.addEventListener("DOMContentLoaded", navigation);

// ---------------------------------------------------------------------------
// Distribution des zones : barre empilée, libellés directs + légende
// ---------------------------------------------------------------------------
function barreZones(dist) {
  if (!dist || (!dist.z1_z2 && !dist.z3 && !dist.z4_z5)) return `<p class="muted small">Pas de données FC course.</p>`;
  const seg = (cls, v) => v > 0 ? `<div class="${cls}" style="flex:${v}" title="${nb(v, 1)} %">${v >= 12 ? nb(v, 0) + " %" : ""}</div>` : "";
  return `<div class="zones" role="img" aria-label="Z1-Z2 ${nb(dist.z1_z2, 1)} %, Z3 ${nb(dist.z3, 1)} %, Z4-Z5 ${nb(dist.z4_z5, 1)} %">
      ${seg("z12", dist.z1_z2)}${seg("z3", dist.z3)}${seg("z45", dist.z4_z5)}</div>
    <div class="legende">
      <span><i style="background:var(--series-1)"></i>Z1-Z2 ${nb(dist.z1_z2, 1)} %</span>
      <span><i style="background:var(--series-2)"></i>Z3 ${nb(dist.z3, 1)} %</span>
      <span><i style="background:var(--series-3)"></i>Z4-Z5 ${nb(dist.z4_z5, 1)} %</span>
    </div>`;
}

function zonesDepuisPct(pct) {
  pct = pct || {};
  return { z1_z2: (pct.z1 || 0) + (pct.z2 || 0), z3: pct.z3 || 0, z4_z5: (pct.z4 || 0) + (pct.z5 || 0) };
}

// ---------------------------------------------------------------------------
// Graphiques SVG (une série, un axe, infobulle au survol / toucher)
// ---------------------------------------------------------------------------
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

function _cadre(conteneur, points, opts) {
  conteneur.innerHTML = "";
  conteneur.classList.add("graph");
  const L = 340, H = 180, m = { g: 32, d: 8, h: 12, b: 22 };
  const svg = svgEl("svg", { viewBox: `0 0 ${L} ${H}`, role: "img", "aria-label": opts.titre || "" }, conteneur);
  const valeurs = points.map(p => p.valeur).filter(v => v != null);
  // opts.max est un plancher d'échelle : une valeur réelle plus haute l'élargit
  let min = opts.min ?? Math.min(0, ...valeurs), max = Math.max(opts.max ?? 1, ...valeurs) * (opts.max ? 1 : 1.05);
  if (opts.seuil != null) max = Math.max(max, opts.seuil * 1.08);
  if (opts.bande) max = Math.max(max, opts.bande[1] * 1.08);
  if (!opts.min && opts.plancherAuto && valeurs.length) {
    const lo = Math.min(...valeurs), hi = Math.max(...valeurs);
    const marge = Math.max((hi - lo) * 0.3, 0.5);
    min = Math.floor(lo - marge); max = Math.ceil(hi + marge);
  }
  const y = v => m.h + (H - m.h - m.b) * (1 - (v - min) / (max - min || 1));
  const larg = (L - m.g - m.d) / Math.max(points.length, 1);
  const x = i => m.g + larg * (i + 0.5);

  // Grille et axe Y (3 graduations)
  for (let k = 0; k <= 2; k++) {
    const v = min + (max - min) * k / 2;
    svgEl("line", { x1: m.g, x2: L - m.d, y1: y(v), y2: y(v), class: "grille-l" }, svg);
    const t = svgEl("text", { x: m.g - 4, y: y(v) + 3, "text-anchor": "end", class: "axe" }, svg);
    t.textContent = nb(v, max - min < 10 ? 1 : 0);
  }
  // Axe X : une étiquette sur trois
  points.forEach((p, i) => {
    if (i % 3 !== (points.length - 1) % 3) return;
    const t = svgEl("text", { x: x(i), y: H - 6, "text-anchor": "middle", class: "axe" }, svg);
    t.textContent = p.label;
  });

  const bulle = document.createElement("div");
  bulle.className = "infobulle hidden";
  conteneur.appendChild(bulle);
  const montrer = (i, px, py) => {
    const p = points[i];
    bulle.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = p.valeur == null ? "—" : nb(p.valeur, opts.dec ?? 1, opts.unite);
    const s = document.createElement("span");
    s.textContent = p.detail || p.label;
    bulle.append(b, s);
    bulle.classList.remove("hidden");
    const r = conteneur.getBoundingClientRect(), echelle = r.width / L;
    const gauche = Math.min(Math.max(px * echelle - bulle.offsetWidth / 2, 0), r.width - bulle.offsetWidth);
    bulle.style.left = gauche + "px";
    bulle.style.top = Math.max(py * echelle - bulle.offsetHeight - 10, 0) + "px";
  };
  const cacher = () => bulle.classList.add("hidden");
  return { svg, x, y, larg, montrer, cacher, m, L, H, min };
}

function graphBarres(conteneur, points, opts = {}) {
  if (!points.length) { conteneur.innerHTML = `<p class="muted small">Pas de données.</p>`; return; }
  const c = _cadre(conteneur, points, opts);
  const lb = Math.max(Math.min(c.larg - 6, 22), 4);
  points.forEach((p, i) => {
    if (!p.valeur) return;
    const y0 = c.y(Math.max(c.min, 0)), y1 = c.y(p.valeur), h = Math.max(y0 - y1, 1);
    const r = Math.min(4, h / 2), xg = c.x(i) - lb / 2;
    // Extrémité arrondie en haut, base ancrée à zéro
    const d = `M${xg},${y0} V${y1 + r} Q${xg},${y1} ${xg + r},${y1} H${xg + lb - r} Q${xg + lb},${y1} ${xg + lb},${y1 + r} V${y0} Z`;
    const bar = svgEl("path", { d, class: "barre", tabindex: 0 }, c.svg);
    const zone = svgEl("rect", { x: c.x(i) - c.larg / 2, y: c.m.h, width: c.larg, height: c.H - c.m.h - c.m.b, fill: "transparent" }, c.svg);
    for (const cible of [bar, zone]) {
      cible.addEventListener("pointerenter", () => c.montrer(i, c.x(i), y1));
      cible.addEventListener("pointerleave", c.cacher);
    }
    bar.addEventListener("focus", () => c.montrer(i, c.x(i), y1));
    bar.addEventListener("blur", c.cacher);
  });
}

function graphCourbe(conteneur, points, opts = {}) {
  const utiles = points.filter(p => p.valeur != null);
  if (!utiles.length) { conteneur.innerHTML = `<p class="muted small">Pas de données.</p>`; return; }
  const c = _cadre(conteneur, points, opts);
  if (opts.bande) {
    const [a, b] = opts.bande;
    svgEl("rect", { x: c.m.g, width: c.L - c.m.g - c.m.d, y: c.y(b), height: c.y(a) - c.y(b), class: "bande" }, c.svg);
    const t = svgEl("text", { x: c.L - c.m.d - 2, y: c.y(b) + 11, "text-anchor": "end", class: "seuil-t" }, c.svg);
    t.textContent = opts.bandeLibelle || "";
  }
  if (opts.seuil != null) {
    svgEl("line", { x1: c.m.g, x2: c.L - c.m.d, y1: c.y(opts.seuil), y2: c.y(opts.seuil), class: "seuil" }, c.svg);
    const t = svgEl("text", { x: c.L - c.m.d - 2, y: c.y(opts.seuil) - 3, "text-anchor": "end", class: "seuil-t" }, c.svg);
    t.textContent = opts.seuilLibelle || "";
  }
  // Tracé (interrompu sur les valeurs manquantes)
  let d = "", enCours = false;
  points.forEach((p, i) => {
    if (p.valeur == null) { enCours = false; return; }
    d += `${enCours ? "L" : "M"}${c.x(i)},${c.y(p.valeur)} `;
    enCours = true;
  });
  const idClip = "clip" + Math.random().toString(36).slice(2);
  const clip = svgEl("clipPath", { id: idClip }, svgEl("defs", {}, c.svg));
  svgEl("rect", { x: c.m.g - 6, y: c.m.h - 6, width: c.L - c.m.g - c.m.d + 12, height: c.H - c.m.h - c.m.b + 12 }, clip);
  const trace = svgEl("g", { "clip-path": `url(#${idClip})` }, c.svg);
  svgEl("path", { d, class: "courbe" }, trace);
  points.forEach((p, i) => { if (p.valeur != null) svgEl("circle", { cx: c.x(i), cy: c.y(p.valeur), r: 4, class: "point" }, trace); });

  // Viseur : suit le pointeur et s'aimante au point le plus proche
  const viseur = svgEl("line", { y1: c.m.h, y2: c.H - c.m.b, class: "viseur hidden" }, c.svg);
  const zone = svgEl("rect", { x: c.m.g, y: 0, width: c.L - c.m.g - c.m.d, height: c.H, fill: "transparent", tabindex: 0 }, c.svg);
  const viser = i => {
    const p = points[i];
    viseur.setAttribute("x1", c.x(i)); viseur.setAttribute("x2", c.x(i));
    viseur.classList.remove("hidden");
    c.montrer(i, c.x(i), p.valeur == null ? c.m.h : c.y(p.valeur));
  };
  zone.addEventListener("pointermove", ev => {
    const r = c.svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * c.L / r.width;
    const i = Math.max(0, Math.min(points.length - 1, Math.round((px - c.m.g) / c.larg - 0.5)));
    viser(i);
  });
  zone.addEventListener("pointerleave", () => { viseur.classList.add("hidden"); c.cacher(); });
  zone.addEventListener("focus", () => viser(points.length - 1));
  zone.addEventListener("blur", () => { viseur.classList.add("hidden"); c.cacher(); });
}

// ---------------------------------------------------------------------------
// Éditeur de séance planifiée (dialogue partagé)
// ---------------------------------------------------------------------------
function optionsHTML(valeurs, choisie, libelles = {}) {
  return valeurs.map(v => `<option value="${esc(v)}" ${v === choisie ? "selected" : ""}>${esc(libelles[v] || v)}</option>`).join("");
}

function editerSeance(p, surFin) {
  let dlg = $("#dlg-seance");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-seance";
    document.body.appendChild(dlg);
  }
  const types = TYPES_SEANCE.includes(p.type) ? TYPES_SEANCE : [p.type, ...TYPES_SEANCE];
  dlg.innerHTML = `<form method="dialog">
    <h2>${p.id ? "Modifier la séance" : "Nouvelle séance"}</h2>
    <div class="champs">
      <div><label>Date</label><input type="date" name="date_seance" value="${esc(p.date_seance)}" required></div>
      <div><label>Créneau</label><select name="creneau">${optionsHTML(CRENEAUX, p.creneau || "matin")}</select></div>
      <div><label>Type</label><select name="type">${optionsHTML(types, p.type || "EF")}</select></div>
      <div><label>Statut</label><select name="statut">${optionsHTML(Object.keys(STATUTS), p.statut || "prevu", STATUTS)}</select></div>
      <div><label>Durée (min)</label><input type="number" name="duree_min" min="0" value="${esc(p.duree_min ?? "")}"></div>
      <div><label>Distance (km)</label><input type="number" step="0.1" name="distance_km" value="${esc(p.distance_km ?? "")}"></div>
      <div class="plein"><label>Intensité</label><input name="intensite" value="${esc(p.intensite ?? "")}"></div>
      <div class="plein"><label>Détail</label><textarea name="detail">${esc(p.detail ?? "")}</textarea></div>
    </div>
    <p class="small muted">${p.version ? `Version ${p.version} · origine ${esc(p.origine || "—")}` : ""}</p>
    <div class="erreur"></div>
    <div class="ligne entre" style="margin-top:10px">
      ${p.id ? `<button type="button" class="danger" data-action="suppr">Supprimer</button>` : "<span></span>"}
      <div class="ligne"><button value="annuler">Annuler</button><button type="button" class="primaire" data-action="ok">Enregistrer</button></div>
    </div></form>`;
  const form = $("form", dlg);
  $("[data-action=ok]", dlg).onclick = async () => {
    const v = Object.fromEntries(new FormData(form));
    try {
      if (p.id) await api("PUT", `/api/planifiees/${p.id}`, v);
      else await api("POST", "/api/planifiees", v);
      dlg.close(); surFin && surFin();
    } catch (e) { erreur($(".erreur", dlg), e); }
  };
  const suppr = $("[data-action=suppr]", dlg);
  if (suppr) suppr.onclick = async () => {
    if (!confirm("Supprimer cette séance planifiée ?")) return;
    try { await api("DELETE", `/api/planifiees/${p.id}`); dlg.close(); surFin && surFin(); }
    catch (e) { erreur($(".erreur", dlg), e); }
  };
  dlg.showModal();
}

// Rendu compact d'une analyse de séance (import, historique)
function htmlAnalyseSeance(a) {
  if (!a) return "";
  const sig = (a.signaux || []).length ? `<ul>${a.signaux.map(s => `<li>${esc(typeof s === "string" ? s : s.detail)}</li>`).join("")}</ul>` : "";
  const aj = (a.ajustements || []).map(x =>
    `<tr><td>${esc(x.jour)}</td><td>${esc(x.seance_initiale)}</td><td><b>${esc(x.seance_proposee)}</b><br><span class="muted small">${esc(x.raison)}</span></td></tr>`).join("");
  return `<p>${esc(a.analyse)}</p>
    ${sig ? `<h3>Signaux</h3>${sig}` : ""}
    ${aj ? `<h3>Ajustements proposés</h3><div class="defile"><table><tr><th>Jour</th><th>Prévu</th><th>Proposé</th></tr>${aj}</table></div>` : ""}`;
}
