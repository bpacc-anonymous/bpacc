"""
BPACC - B1 Node 1 : format_detector
Détecte le type d'input fourni par l'utilisateur.
Pas de LLM — logique déterministe uniquement.

input_type :
  "natural_language"  — texte brut uniquement
  "bpmn_xml"          — XML BPMN uniquement (uploadé ou collé)
  "both"              — texte + fichier XML fournis
  "structured_other"  — JSON, CSV, ou autre format structuré non-BPMN
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState


# Marqueurs XML caractéristiques d'un BPMN
_BPMN_MARKERS = (
    "<definitions", "<bpmn:definitions", "<bpmn2:definitions",
    "<process", "<bpmn:process",
)

# Extensions considérées comme "structured_other"
_STRUCTURED_EXTENSIONS = (".json", ".csv", ".yaml", ".yml", ".xml")


def _is_bpmn(text: str) -> bool:
    """Détecte si une chaîne est du XML BPMN."""
    stripped = text.strip().lower()
    return any(marker in stripped for marker in _BPMN_MARKERS)


def _is_structured_other(text: str) -> bool:
    """Détecte si une chaîne est du JSON, CSV ou autre format structuré non-BPMN."""
    stripped = text.strip()
    return (
        (stripped.startswith("{") or stripped.startswith("["))  # JSON
        or ("," in stripped.splitlines()[0] if stripped else False)  # CSV heuristique
    )


def format_detector(state: BPACCState) -> dict:
    user_intent   = state.get("user_intent", "").strip()
    uploaded_file = state.get("uploaded_file", "").strip()
    errors        = list(state.get("errors", []))

    if not user_intent and not uploaded_file:
        errors.append("format_detector: aucun input fourni.")
        return {"input_type": None, "errors": errors,
                "status": "failed", "current_node": "format_detector"}

    intent_is_bpmn       = _is_bpmn(user_intent)
    intent_is_structured = not intent_is_bpmn and _is_structured_other(user_intent)
    file_is_bpmn         = _is_bpmn(uploaded_file) if uploaded_file else False

    # Cas "both" : texte naturel + fichier BPMN uploadé
    if user_intent and not intent_is_bpmn and not intent_is_structured and file_is_bpmn:
        input_type = "both"

    # BPMN collé directement dans user_intent
    elif intent_is_bpmn:
        input_type = "bpmn_xml"

    # Fichier BPMN uploadé sans texte naturel
    elif file_is_bpmn and not user_intent:
        input_type = "bpmn_xml"

    # Format structuré non-BPMN
    elif intent_is_structured or (uploaded_file and not file_is_bpmn):
        input_type = "structured_other"

    # Texte naturel
    else:
        input_type = "natural_language"

    return {
        "input_type":   input_type,
        "errors":       errors,
        "status":       "running",
        "current_node": "format_detector",
    }