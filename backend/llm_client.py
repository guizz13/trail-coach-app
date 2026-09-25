"""
Client Claude API pour le coach.

Trois types d'appels, tous en JSON strict (voir prompts/system_prompt_coach.md §10) :
  - analyse_seance             → à chaque import de fichier
  - bilan_hebdo                → chaque dimanche
  - reconstruction_evenements  → à chaque ajout/modification d'événement

Stratégie de coût :
  - System prompt mis en cache (cache_control) → 10 % du prix input aux appels suivants
  - Modèle : claude-fable-5-1 partout (décision : le meilleur à chaque étape, budget < 5 $/mois)
  - Compteur de tokens persisté → alerte à 5 $ cumulés dans le mois

Vérifier la syntaxe SDK à jour : https://docs.claude.com/en/api/overview
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODELE_PAR_APPEL = {
    "analyse_seance": "claude-fable-5-1",
    "bilan_hebdo": "claude-fable-5-1",
    "reconstruction_evenements": "claude-fable-5-1",
}

# Tarifs USD par million de tokens (à mettre à jour si Anthropic change)
TARIFS = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_write": 12.5},
    "claude-opus-5-5":  {"input": 4.0,  "output": 20.0, "cache_read": 0.4,  "cache_write": 5.0},
    "claude-sonnet-5":  {"input": 2.0,  "output": 10.0, "cache_read": 0.2,  "cache_write": 2.5},
}

MAX_TOKENS_PAR_APPEL = {
    "analyse_seance": 1500,
    "bilan_hebdo": 4000,
    "reconstruction_evenements": 4000,
}

PLAFOND_MENSUEL_USD = 5.0
FICHIER_COMPTEUR = Path(os.getenv("COACH_DATA_DIR", ".")) / "usage_llm.json"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md"


# ---------------------------------------------------------------------------
# Compteur de coût
# ---------------------------------------------------------------------------
@dataclass
class Usage:
    mois: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cout_usd: float = 0.0
    nb_appels: int = 0


def _charger_usage() -> Usage:
    mois = date.today().strftime("%Y-%m")
    if FICHIER_COMPTEUR.exists():
        d = json.loads(FICHIER_COMPTEUR.read_text())
        if d.get("mois") == mois:
            return Usage(**d)
    return Usage(mois=mois)


def _sauver_usage(u: Usage) -> None:
    FICHIER_COMPTEUR.write_text(json.dumps(u.__dict__, indent=2))


def _cout(modele: str, usage_api: Any) -> float:
    t = TARIFS[modele]
    inp = getattr(usage_api, "input_tokens", 0)
    out = getattr(usage_api, "output_tokens", 0)
    cr = getattr(usage_api, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage_api, "cache_creation_input_tokens", 0) or 0
    return (inp * t["input"] + out * t["output"] + cr * t["cache_read"] + cw * t["cache_write"]) / 1_000_000


def cout_du_mois() -> Usage:
    return _charger_usage()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class CoachLLM:
    def __init__(self, api_key: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # ---- Appels publics --------------------------------------------------
    def analyse_seance(self, seance: dict, prevu: dict | None, semaine: list[dict],
                       indicateurs: dict, profil: dict, statut_sante: str, mode: str) -> dict:
        ctx = {
            "seance_importee": seance,
            "seance_prevue": prevu,
            "reste_de_la_semaine": semaine,
            "indicateurs_calcules": indicateurs,
        }
        return self._appel("analyse_seance", ctx, profil, statut_sante, mode)

    def bilan_hebdo(self, semaine_ecoulee: list[dict], plan_prevu: list[dict],
                    imperatifs: dict, historique_4sem: list[dict], evenements: list[dict],
                    indicateurs: dict, profil: dict, statut_sante: str, mode: str,
                    phase_prepa: dict | None) -> dict:
        ctx = {
            "semaine_ecoulee": semaine_ecoulee,
            "plan_prevu": plan_prevu,
            "imperatifs_semaine_suivante": imperatifs,
            "historique_4_semaines": historique_4sem,
            "evenements_a_venir": evenements,
            "indicateurs_calcules": indicateurs,
            "phase_prepa": phase_prepa,
        }
        return self._appel("bilan_hebdo", ctx, profil, statut_sante, mode)

    def reconstruction_evenements(self, evenements: list[dict], historique: list[dict],
                                  plan_actuel: dict | None, profil: dict,
                                  statut_sante: str, mode: str) -> dict:
        ctx = {
            "evenements": evenements,
            "historique_recent": historique,
            "plan_prepa_actuel": plan_actuel,
        }
        return self._appel("reconstruction_evenements", ctx, profil, statut_sante, mode)

    # ---- Cœur ------------------------------------------------------------
    def _appel(self, type_appel: str, contexte: dict, profil: dict,
               statut_sante: str, mode: str) -> dict:
        usage = _charger_usage()
        if usage.cout_usd >= PLAFOND_MENSUEL_USD:
            raise RuntimeError(
                f"Plafond mensuel LLM atteint ({usage.cout_usd:.2f} $ / {PLAFOND_MENSUEL_USD} $). "
                "Appel refusé. Relever PLAFOND_MENSUEL_USD ou attendre le mois prochain."
            )

        modele = MODELE_PAR_APPEL[type_appel]
        user_msg = (
            f"<type_appel>{type_appel}</type_appel>\n"
            f"<mode>{mode}</mode>\n"
            f"<statut_sante>{statut_sante}</statut_sante>\n"
            f"<profil_actuel>{json.dumps(profil, ensure_ascii=False)}</profil_actuel>\n"
            f"<date_du_jour>{date.today().isoformat()}</date_du_jour>\n"
            f"<contexte>{json.dumps(contexte, ensure_ascii=False, default=str)}</contexte>\n\n"
            "Réponds uniquement avec le JSON du schéma correspondant au type d'appel."
        )

        resp = self.client.messages.create(
            model=modele,
            max_tokens=MAX_TOKENS_PAR_APPEL[type_appel],
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )

        # Comptabilité
        usage.input_tokens += resp.usage.input_tokens
        usage.output_tokens += resp.usage.output_tokens
        usage.cache_read_tokens += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        usage.cache_write_tokens += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        usage.cout_usd += _cout(modele, resp.usage)
        usage.nb_appels += 1
        _sauver_usage(usage)

        # Parsing JSON strict
        texte = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        texte = texte.removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(texte)
        except json.JSONDecodeError as e:
            raise ValueError(f"Réponse LLM non-JSON pour {type_appel} : {e}\n{texte[:500]}") from e
