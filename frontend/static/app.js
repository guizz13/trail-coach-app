/* SENSEI — socle commun : API, wording, composants, graphiques, traces */
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
  if (r.status === 401 || r.redirected && r.url.includes("/login")) {
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
// Outils
// ---------------------------------------------------------------------------
const $ = (sel, racine = document) => racine.querySelector(sel);
const $$ = (sel, racine = document) => [...racine.querySelectorAll(sel)];
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const stockage = {
  lire(cle) { try { return JSON.parse(localStorage.getItem("sensei:" + cle)); } catch { return null; } },
  ecrire(cle, v) { try { localStorage.setItem("sensei:" + cle, JSON.stringify(v)); } catch { /* stockage indisponible */ } },
  suppr(cle) { try { localStorage.removeItem("sensei:" + cle); } catch { /* idem */ } },
};

// ---------------------------------------------------------------------------
// Wording (termes techniques du backend → libellés affichés)
// ---------------------------------------------------------------------------
const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
const TYPES = {
  EF: "Endurance fondamentale", intervals: "Intervalles", cotes: "Côtes", tempo: "Tempo",
  sortie_longue: "Sortie longue", muscu_push: "Musculation Push", muscu_pull: "Musculation Pull",
  muscu_jambes: "Musculation Jambes", squash: "Squash", velo: "Vélo", repos: "Repos",
};
const TYPES_PLANIFIABLES = Object.keys(TYPES);
const FAMILLES = {
  course_outdoor: "Course", course_tapis: "Course sur tapis", squash: "Squash", velo: "Vélo",
  muscu: "Musculation", autre: "Autre", inconnu: "Inconnu",
};
const STATUTS = { prevu: "À faire", realise: "Fait", manque: "Manqué", modifie: "Modifié" };
const VERDICTS = { vert: "conforme", orange: "attention", rouge: "alerte" };
const PRIORITES = { A: "Objectif principal", B: "Course prévue", C: "Participation" };
const CLASSE_PRIORITE = { A: "orange", B: "accent", C: "" };
const TYPES_EVT = { trail_race: "Trail", squash_competition: "Compétition squash", other: "Autre" };
const APPELS = { analyse_seance: "Analyse", bilan_hebdo: "Bilan", reconstruction_evenements: "Reconstruction du plan" };
const SPLITS = { push_a: "Push A", pull_a: "Pull A", push_b: "Push B", pull_b: "Pull B", jambes: "Jambes", autre: "Autre" };
const CRENEAUX = { matin: "matin", midi: "midi", soir: "soir", journee: "journée" };
const PHASES = { BASE: "Base", BUILD: "Build", PIC: "Pic", AFFUTAGE: "Affûtage" };
const GROUPES = { pectoraux: "Pectoraux", triceps: "Triceps", epaules: "Épaules", dos: "Dos", biceps: "Biceps",
  cuisses: "Cuisses", ischios: "Ischios", mollets: "Mollets", abdos: "Abdos" };

const libelleType = t => TYPES[t] || t;
function libelleMode(profil, prochainA) {
  if (profil.mode_actif !== "RACE_PREP") return "Entraînement libre";
  return prochainA ? `Prépa ${prochainA.titre}` : "Prépa course";
}

// Disciplines : classe CSS + icône Tabler
const ICONES = { course: "ti-run", squash: "ti-ball-tennis", muscu: "ti-barbell", velo: "ti-bike", repos: "ti-zzz", autre: "ti-activity" };
function disciplineType(type) {
  const t = (type || "").toLowerCase();
  if (t.startsWith("muscu")) return "muscu";
  if (t === "squash" || t === "velo" || t === "repos") return t;
  if (t === "autre") return "autre";
  return "course";
}
function disciplineFamille(f) {
  if (f === "course_outdoor" || f === "course_tapis") return "course";
  return ICONES[f] ? f : "autre";
}
const iconeDisc = d => `<span class="disc ${d}"><i class="ti ${ICONES[d] || ICONES.autre}"></i></span>`;

// ---------------------------------------------------------------------------
// Formatage
// ---------------------------------------------------------------------------
function nb(v, dec = 0, unite = "") {
  if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("fr-FR", { maximumFractionDigits: dec }) + (unite ? " " + unite : "");
}
function duree(min) {
  if (min == null) return "—";
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}` : `${m} min`;
}
const dateLocale = iso => new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
function dateFR(iso, opts = { weekday: "short", day: "numeric", month: "short" }) {
  return iso ? dateLocale(iso).toLocaleDateString("fr-FR", opts) : "—";
}
const heure = iso => (iso && iso.length > 10 ? iso.slice(11, 16) : "");
function isoJour(d) {
  const z = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function ajouterJours(iso, n) { const d = dateLocale(iso); d.setDate(d.getDate() + n); return isoJour(d); }
function lundiDe(iso) { const d = dateLocale(iso); return ajouterJours(iso, -((d.getDay() + 6) % 7)); }
function joursEntre(a, b) { return Math.round((dateLocale(b) - dateLocale(a)) / 86400000); }

// ---------------------------------------------------------------------------
// Coque : top bar + tab bar
// ---------------------------------------------------------------------------
const ONGLETS = [["/", "ti-calendar", "Semaine"], ["/import", "ti-upload", "Import"],
  ["/dimanche", "ti-adjustments", "Préparer"], ["/evenements", "ti-target", "Objectifs"], ["/historique", "ti-chart-line", "Stats"]];

function coque(droiteHTML = "") {
  const top = document.createElement("header");
  top.className = "topbar";
  top.innerHTML = `<div class="logo-box"><div class="logo-icon" aria-hidden="true">先</div><span class="logo-text">Sensei</span></div>
    <div id="topbar-droite">${droiteHTML}</div>`;
  $("main").prepend(top);
  const nav = document.createElement("nav");
  nav.className = "tabbar";
  nav.innerHTML = ONGLETS.map(([h, i, t]) =>
    `<a href="${h}" class="${location.pathname === h ? "actif" : ""}"><i class="ti ${i}"></i>${t}</a>`).join("");
  document.body.appendChild(nav);
}

// ---------------------------------------------------------------------------
// Composants
// ---------------------------------------------------------------------------
const verdictHTML = v => v ? `<span class="verdict ${esc(v)}">${VERDICTS[v] || esc(v)}</span>` : "";

// Texte du coach replié sur 2 lignes ; « Voir plus » n'apparaît que s'il dépasse
function texteReplie(texte, style = "") {
  if (!texte) return "";
  return `<div class="repliable"><p class="texte" style="${style}">${esc(texte)}</p><button type="button" class="voir-plus hidden">Voir plus</button></div>`;
}

function activerRepliables(racine) {
  $$(".repliable:not([data-pret])", racine).forEach(r => {
    r.dataset.pret = "1";
    const t = $(".texte", r), b = $(".voir-plus", r);
    requestAnimationFrame(() => { if (t.scrollHeight > t.clientHeight + 1) b.classList.remove("hidden"); });
    b.onclick = () => { const ouvert = r.classList.toggle("deplie"); b.textContent = ouvert ? "Réduire" : "Voir plus"; };
  });
}
// Les pages injectent leur contenu dynamiquement : on active chaque bloc dès son insertion
new MutationObserver(() => activerRepliables(document)).observe(document.documentElement, { childList: true, subtree: true });

function messageCoach(textes, titre = "Message du coach") {
  const t = (Array.isArray(textes) ? textes : [textes]).filter(Boolean);
  if (!t.length) return "";
  return `<div class="coach"><div class="titre">${esc(titre)}</div>${texteReplie(t.join(" "))}</div>`;
}

function reflexion(el, texte = "Sensei réfléchit…") {
  el.innerHTML = `<div class="reflexion"><span class="spinner"></span>${esc(texte)}</div>`;
}

// Chargeur des appels au coach (5 à 15 s) : blocs pulsants + message qui tourne toutes les 3 s
const loadingMessages = [
  "Sensei analyse ton historique...",
  "Construction des phases...",
  "Vérification des contraintes...",
  "Finalisation du plan...",
];
const MESSAGES_ANALYSE = [
  "Sensei analyse ta séance...",
  "Comparaison avec le plan...",
  "Vérification des seuils...",
  "Rédaction de l'analyse...",
];
const MESSAGES_BILAN = [
  "Sensei analyse ton historique...",
  "Bilan de la semaine écoulée...",
  "Vérification des contraintes...",
  "Construction de ta semaine...",
];
function chargeurIA(el, messages = loadingMessages) {
  el.innerHTML = `<div class="skeleton" aria-busy="true">
      ${[40, 60, 40, 50].map(h => `<div class="skeleton-block" style="height:${h}px"></div>`).join("")}
      <p class="skeleton-texte" role="status">${esc(messages[0])}</p></div>`;
  const texte = $(".skeleton-texte", el);
  let i = 0;
  const minuteur = setInterval(() => {
    if (!texte.isConnected) { clearInterval(minuteur); return; }   // résultat affiché : on s'arrête
    i = (i + 1) % messages.length;
    texte.textContent = messages[i];
  }, 3000);
}

function erreurSimple(el, e) {
  el.innerHTML = `<div class="bandeau rouge">${esc(e.message || e)}</div>`;
}

// Erreur LLM : titre, réponse brute, bouton Réessayer si l'action est rejouable
function carteErreurLLM(err, reessayer) {
  const titres = { json_invalide: "Réponse du coach illisible", plafond: "Plafond mensuel atteint" };
  const div = document.createElement("div");
  div.className = "erreur-carte";
  div.innerHTML = `<div class="titre">${esc(titres[err.type] || "Sensei indisponible")}</div>
    <pre class="brut">${esc(err.message)}</pre>
    ${reessayer ? `<div class="boutons"><button class="btn petit" type="button"><i class="ti ti-refresh"></i>Réessayer</button></div>` : ""}`;
  if (reessayer) $("button", div).onclick = reessayer;
  return div;
}

function barreZones(dist) {
  if (!dist || (!dist.z1_z2 && !dist.z3 && !dist.z4_z5)) return `<div class="vide" style="margin-top:14px">Pas de données cardio course.</div>`;
  const seg = (cls, v) => v > 0 ? `<div class="${cls}" style="flex:${v}"></div>` : "";
  return `<div class="zones" role="img" aria-label="Z1-Z2 ${nb(dist.z1_z2)} %, Z3 ${nb(dist.z3)} %, Z4+ ${nb(dist.z4_z5)} %">
      ${seg("z12", dist.z1_z2)}${seg("z3", dist.z3)}${seg("z45", dist.z4_z5)}</div>
    <div class="zones-legende">
      <span><b>${nb(dist.z1_z2)}%</b><i class="z12"></i>Z1-Z2</span>
      <span><b>${nb(dist.z3)}%</b><i class="z3"></i>Z3</span>
      <span><b>${nb(dist.z4_z5)}%</b><i class="z45"></i>Z4+</span>
    </div>`;
}
const zonesDepuisPct = p => ({ z1_z2: (p?.z1 || 0) + (p?.z2 || 0), z3: p?.z3 || 0, z4_z5: (p?.z4 || 0) + (p?.z5 || 0) });

function couleurRatio(r) {
  if (r == null) return "var(--text-muted)";
  if (r > 1.5 || r < 0.8) return "var(--red)";
  if (r > 1.3) return "var(--orange)";
  return "var(--green)";
}

// Jauge équilibre de charge : 0 → 2, marqueur coloré selon la zone
function jaugeCharge(ratio) {
  const pos = ratio == null ? 50 : Math.max(0, Math.min(100, ratio / 2 * 100));
  return `<div class="jauge" role="img" aria-label="Équilibre de charge ${ratio == null ? "indisponible" : nb(ratio, 2)}">
      <div class="marqueur" style="left:${pos}%;background:${couleurRatio(ratio)}"></div></div>
    <div class="jauge-zones"><span>sous-charge</span><span>optimal</span><span>danger</span></div>`;
}

// Feuille modale (bas d'écran)
function feuille(html) {
  let d = $("#feuille");
  if (!d) {
    d = document.createElement("dialog");
    d.id = "feuille";
    d.className = "feuille";
    d.addEventListener("click", e => { if (e.target === d) d.close(); });
    document.body.appendChild(d);
  }
  d.innerHTML = `<div class="poignee"></div>${html}`;
  d.showModal();
  return d;
}

// ---------------------------------------------------------------------------
// Traces GPS et profils (calculés côté navigateur, conservés sur l'appareil)
// ---------------------------------------------------------------------------
function reduire(points, max = 160) {
  if (points.length <= max) return points;
  const pas = points.length / max;
  return Array.from({ length: max }, (_, i) => points[Math.floor(i * pas)]);
}

// Suunto : Latitude/Longitude en radians dans les Samples
function traceSuunto(data) {
  const s = data?.DeviceLog?.Samples || [];
  const pts = s.filter(x => x.Latitude && x.Longitude).map(x => [x.Longitude, x.Latitude]);
  if (pts.length < 10) return null;
  const latMoy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  return reduire(pts.map(([lon, lat]) => [lon * Math.cos(latMoy), -lat]));
}
function profilSuunto(data) {
  const s = data?.DeviceLog?.Samples || [];
  const alt = s.map(x => x.Altitude ?? x.GPSAltitude).filter(v => v != null);
  return alt.length >= 10 ? reduire(alt, 120) : null;
}

// GPX : distance, D+ et profil d'altitude
function lireGPX(texte) {
  const doc = new DOMParser().parseFromString(texte, "application/xml");
  const pts = [...doc.querySelectorAll("trkpt, rtept")].map(p => ({
    lat: parseFloat(p.getAttribute("lat")), lon: parseFloat(p.getAttribute("lon")),
    ele: parseFloat(p.querySelector("ele")?.textContent),
  })).filter(p => !Number.isNaN(p.lat) && !Number.isNaN(p.lon));
  if (pts.length < 2) throw new Error("Fichier GPX sans points de trace.");
  const rad = x => x * Math.PI / 180;
  let dist = 0, dplus = 0, ref = pts[0].ele;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
    dist += 2 * 6371 * Math.asin(Math.sqrt(h));
    // D+ avec hystérésis de 3 m pour ignorer le bruit d'altitude
    if (!Number.isNaN(b.ele) && !Number.isNaN(ref)) {
      if (b.ele - ref >= 3) { dplus += b.ele - ref; ref = b.ele; } else if (ref - b.ele >= 3) ref = b.ele;
    }
  }
  const alt = pts.map(p => p.ele).filter(v => !Number.isNaN(v));
  return { distance_km: Math.round(dist * 10) / 10, dplus_m: Math.round(dplus), profil: alt.length >= 10 ? reduire(alt, 120) : null };
}

// Polyline SVG dans un cadre L×H
function svgTrace(points, L, H, couleur = "var(--course)") {
  if (!points || points.length < 2) return "";
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const e = Math.max(x1 - x0, y1 - y0) || 1;       // même échelle sur x et y : trace non déformée
  const m = 2, k = Math.min((L - 2 * m) / ((x1 - x0) || e), (H - 2 * m) / ((y1 - y0) || e));
  const ox = (L - (x1 - x0) * k) / 2, oy = (H - (y1 - y0) * k) / 2;
  const d = points.map(([x, y]) => `${(ox + (x - x0) * k).toFixed(1)},${(oy + (y - y0) * k).toFixed(1)}`).join(" ");
  return `<svg class="trace" width="${L}" height="${H}" viewBox="0 0 ${L} ${H}" aria-hidden="true"><polyline points="${d}" stroke="${couleur}"/></svg>`;
}
function svgProfil(altitudes, L, H, couleur = "var(--orange)") {
  if (!altitudes || altitudes.length < 2) return "";
  const min = Math.min(...altitudes), max = Math.max(...altitudes), e = (max - min) || 1;
  const d = altitudes.map((a, i) => `${(i / (altitudes.length - 1) * L).toFixed(1)},${(H - 2 - (a - min) / e * (H - 4)).toFixed(1)}`).join(" ");
  return `<svg class="trace" width="${L}" height="${H}" viewBox="0 0 ${L} ${H}" aria-hidden="true"><polyline points="${d}" stroke="${couleur}"/></svg>`;
}

// ---------------------------------------------------------------------------
// Graphique courbe (une série, un axe, infobulle au toucher)
// opts : couleur, aire, bandes [{de, a, couleur}], min, max, dec, unite, etiquettes {index: texte}
// ---------------------------------------------------------------------------
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

function graphCourbe(conteneur, points, opts = {}) {
  conteneur.innerHTML = "";
  conteneur.classList.add("graph");
  const valeurs = points.map(p => p.valeur).filter(v => v != null);
  if (!valeurs.length) { conteneur.innerHTML = `<div class="vide">Pas encore de données.</div>`; return; }
  const L = 340, H = opts.hauteur || 120, m = { g: 26, d: 6, h: 8, b: 18 };
  const svg = svgEl("svg", { viewBox: `0 0 ${L} ${H}`, role: "img", "aria-label": opts.titre || "" }, conteneur);
  let min = opts.min ?? 0, max = Math.max(opts.max ?? 0, ...valeurs) * (opts.max ? 1 : 1.12) || 1;
  if (opts.plancherAuto) { const lo = Math.min(...valeurs), hi = Math.max(...valeurs), marge = Math.max((hi - lo) * .3, .5); min = lo - marge; max = hi + marge; }
  const y = v => m.h + (H - m.h - m.b) * (1 - (v - min) / ((max - min) || 1));
  const x = i => points.length === 1 ? (m.g + L - m.d) / 2 : m.g + (L - m.g - m.d) * i / (points.length - 1);

  for (const b of opts.bandes || []) {
    const hautB = Math.min(b.a, max), basB = Math.max(b.de, min);
    if (hautB > basB) svgEl("rect", { x: m.g, width: L - m.g - m.d, y: y(hautB), height: y(basB) - y(hautB), fill: b.couleur }, svg);
  }
  for (let k = 0; k <= 2; k++) {
    const v = min + (max - min) * k / 2;
    svgEl("line", { x1: m.g, x2: L - m.d, y1: y(v), y2: y(v), class: "grille-l" }, svg);
    svgEl("text", { x: m.g - 5, y: y(v) + 3, "text-anchor": "end", class: "axe" }, svg).textContent = nb(v, max - min < 5 ? 1 : 0);
  }
  for (const [i, t] of Object.entries(opts.etiquettes || {})) {
    const anc = Number(i) === 0 ? "start" : Number(i) === points.length - 1 ? "end" : "middle";
    svgEl("text", { x: x(Number(i)), y: H - 4, "text-anchor": anc, class: "axe" }, svg).textContent = t;
  }

  const couleur = opts.couleur || "var(--course)";
  const segs = [];
  let courant = [];
  points.forEach((p, i) => { if (p.valeur == null) { if (courant.length) segs.push(courant); courant = []; } else courant.push([x(i), y(p.valeur)]); });
  if (courant.length) segs.push(courant);
  if (opts.aire) {
    const id = "deg" + Math.random().toString(36).slice(2);
    const g = svgEl("linearGradient", { id, x1: 0, x2: 0, y1: 0, y2: 1 }, svgEl("defs", {}, svg));
    svgEl("stop", { offset: "0%", "stop-color": couleur, "stop-opacity": .25 }, g);
    svgEl("stop", { offset: "100%", "stop-color": couleur, "stop-opacity": 0 }, g);
    for (const s of segs) {
      if (s.length < 2) continue;
      svgEl("path", { d: `M${s[0][0]},${y(min)} L${s.map(p => p.join(",")).join(" L")} L${s[s.length - 1][0]},${y(min)} Z`, fill: `url(#${id})` }, svg);
    }
  }
  for (const s of segs) svgEl("polyline", { points: s.map(p => p.join(",")).join(" "), class: "courbe", stroke: couleur }, svg);
  const dernier = points.map((p, i) => [p, i]).filter(([p]) => p.valeur != null).pop();
  if (dernier) svgEl("circle", { cx: x(dernier[1]), cy: y(dernier[0].valeur), r: 3.5, fill: couleur }, svg);

  // Infobulle : le viseur s'aimante au point le plus proche
  const viseur = svgEl("line", { y1: m.h, y2: H - m.b, class: "viseur", visibility: "hidden" }, svg);
  const bulle = document.createElement("div");
  bulle.className = "infobulle hidden";
  conteneur.appendChild(bulle);
  const zone = svgEl("rect", { x: 0, y: 0, width: L, height: H, fill: "transparent" }, svg);
  const montrer = ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * L / r.width;
    const i = Math.max(0, Math.min(points.length - 1, Math.round((px - m.g) / ((L - m.g - m.d) / Math.max(points.length - 1, 1)))));
    const p = points[i];
    viseur.setAttribute("x1", x(i)); viseur.setAttribute("x2", x(i)); viseur.setAttribute("visibility", "visible");
    bulle.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = p.valeur == null ? "—" : nb(p.valeur, opts.dec ?? 1, opts.unite);
    const s = document.createElement("span");
    s.textContent = p.detail || p.label || "";
    bulle.append(b, s);
    bulle.classList.remove("hidden");
    const k = r.width / L;
    bulle.style.left = Math.min(Math.max(x(i) * k - bulle.offsetWidth / 2, 0), r.width - bulle.offsetWidth) + "px";
    bulle.style.top = Math.max((p.valeur == null ? m.h : y(p.valeur)) * k - bulle.offsetHeight - 10, -8) + "px";
  };
  const cacher = () => { viseur.setAttribute("visibility", "hidden"); bulle.classList.add("hidden"); };
  zone.addEventListener("pointerdown", montrer);
  zone.addEventListener("pointermove", montrer);
  zone.addEventListener("pointerleave", cacher);
}

// ---------------------------------------------------------------------------
// Séance (carte) — partagée entre Semaine et Préparer
// ---------------------------------------------------------------------------
// p : séance planifiée ; r : séance réalisée liée (facultative) ; verdict facultatif
function seanceHTML(p, r, verdict) {
  const disc = r ? disciplineFamille(r.famille) : disciplineType(p.type);
  const titre = p ? libelleType(p.type) : (r.sous_type ? libelleType(r.sous_type) : FAMILLES[r.famille] || r.famille);
  const trace = r && r.a_gps ? stockage.lire("trace:" + r.fichier_hash) : null;
  const stats = r ? [r.distance_km ? nb(r.distance_km, 1, "km") : duree(r.duree_min), r.dplus_m ? nb(r.dplus_m, 0, "m D+") : "",
    r.fc_moy ? `${r.fc_moy} bpm` : ""].filter(Boolean).join(" · ") : "";
  const detail = p ? [p.creneau && CRENEAUX[p.creneau], p.duree_min && duree(p.duree_min), p.distance_km && nb(p.distance_km, 1, "km"), p.detail].filter(Boolean).join(" · ")
    : `${heure(r.date_debut)} · hors plan`;
  const statut = p ? p.statut : "realise";
  return `${iconeDisc(disc)}
    <div class="seance-corps"><div class="seance-type">${esc(titre)}</div>
      <div class="seance-detail">${esc(detail)}</div>
      ${stats ? `<div class="seance-stats">${esc(stats)}</div>` : ""}</div>
    ${trace ? svgTrace(trace, 50, 35) : ""}
    <div class="seance-droite">${p && p.type === "repos" ? "" : `<span class="statut ${statut}">${STATUTS[statut]}</span>`}${verdictHTML(verdict)}</div>`;
}
