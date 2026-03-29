"""
BPACC - B1 Node 2 : intent_reformulator
Transforme le user_intent en une user story détaillée et structurée,
ET extrait les GovernanceConstraints dans le vocabulaire contrôlé de Tₙ.

Activé uniquement si input_type == "natural_language" | "both".

Sorties ajoutées au state :
  - user_story             : str (inchangé)
  - governance_constraints : GovernanceConstraints (NOUVEAU)
    → instancie Qc (SLOs) et complète Pc (contraintes locales) au sens du papier
    → utilise exclusivement le vocabulaire contrôlé issu de Tₙ et du catalogue raw
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState, GovernanceConstraints
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.intent_reformulator_prompt import (
    INTENT_REFORMULATOR_SYSTEM, INTENT_REFORMULATOR_PROMPT
)

# ── Vocabulaires contrôlés (miroir de state.py) ──────────────────────────────
# Toute valeur hors vocabulaire est rejetée et remplacée par le défaut.

_VALID_REGION        = {"eu", "us", "apac"}
_VALID_LATENCY       = {"critical", "standard", "best-effort", "low"}
_VALID_TARGET_NODE   = {"EndpointNode", "EdgeNode", "CloudNode"}
_VALID_DATA_TYPE     = {"biometric", "personal", "anonymous", "unknown"}
_VALID_CONSENT       = {"true", "false"}
_VALID_DATA_LOCALITY = {"edge-only", "edge-preferred", "endpoint-only", "strict", "none"}

_DEFAULTS: GovernanceConstraints = {
    "region":        "eu",
    "latency":       "standard",
    "target_node":   "EdgeNode",
    "data_type":     "personal",
    "consent":       "false",
    "data_locality": "none",
}


def _validate_governance(raw: dict, errors: list) -> GovernanceConstraints:
    """
    Valide et normalise les governance_constraints produites par le LLM.
    Toute valeur hors vocabulaire contrôlé est remplacée par le défaut
    et une erreur non-bloquante est loggée.
    """
    validated: GovernanceConstraints = {}

    checks = [
        ("region",        _VALID_REGION,        "region"),
        ("latency",       _VALID_LATENCY,        "latency"),
        ("target_node",   _VALID_TARGET_NODE,    "target_node"),
        ("data_type",     _VALID_DATA_TYPE,      "data_type"),
        ("consent",       _VALID_CONSENT,        "consent"),
        ("data_locality", _VALID_DATA_LOCALITY,  "data_locality"),
    ]

    for field, valid_set, key in checks:
        val = str(raw.get(field, "")).strip().lower()

        # Normalisation casse pour target_node (EndpointNode, EdgeNode, CloudNode)
        if field == "target_node":
            val_normalized = {v.lower(): v for v in valid_set}.get(val)
            if val_normalized:
                validated[key] = val_normalized  # type: ignore[literal-required]
                continue
        else:
            if val in valid_set:
                validated[key] = val  # type: ignore[literal-required]
                continue

        # Valeur hors vocabulaire → défaut + log
        default = _DEFAULTS[key]  # type: ignore[literal-required]
        errors.append(
            f"intent_reformulator: governance.{field}={raw.get(field)!r} "
            f"hors vocabulaire contrôlé → défaut '{default}' appliqué."
        )
        validated[key] = default  # type: ignore[literal-required]

    return validated


def intent_reformulator(state: BPACCState) -> dict:
    user_intent = state.get("user_intent", "").strip()
    errors      = list(state.get("errors", []))

    llm    = reformulation_llm(system_prompt=INTENT_REFORMULATOR_SYSTEM)
    prompt = INTENT_REFORMULATOR_PROMPT.format(user_intent=user_intent)
    result = llm.invoke_for_json(prompt)

    if not result:
        errors.append("intent_reformulator: LLM returned invalid JSON.")
        return {"errors": errors, "status": "failed", "current_node": "intent_reformulator"}

    # ── User story ────────────────────────────────────────────────────
    user_story_data = result.get("user_story", {})
    user_story      = user_story_data.get("formatted_description", "")

    if not user_story:
        errors.append("intent_reformulator: formatted_description manquant.")
        return {"errors": errors, "status": "failed", "current_node": "intent_reformulator"}

    # ── Governance constraints ────────────────────────────────────────
    raw_governance = result.get("governance_constraints", {})

    if not raw_governance:
        errors.append(
            "intent_reformulator: governance_constraints absent de la réponse LLM "
            "— valeurs par défaut appliquées."
        )
        raw_governance = {}

    governance_constraints = _validate_governance(raw_governance, errors)

    # ── Log de synthèse ───────────────────────────────────────────────
    print(f"  [intent_reformulator] governance_constraints extrait :")
    for k, v in governance_constraints.items():
        print(f"    {k:15} = {v}")

    return {
        "user_story":             user_story,
        "governance_constraints": governance_constraints,
        "errors":                 errors,
        "status":                 "running",
        "current_node":           "intent_reformulator",
    }