"""
BPACC - B1 Node 8 : bpmn_validator
Valide syntaxiquement le BPMN XML généré.
Tolérant aux extensions moteur (Zeebe, Camunda, Signavio).
Pas de LLM — validation déterministe via lxml.

Si invalide → route vers bpmn_debugger.
Si valide   → route vers response_generator.
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState

try:
    from lxml import etree
    LXML_AVAILABLE = True
except ImportError:
    import xml.etree.ElementTree as ET
    LXML_AVAILABLE = False

# Namespaces BPMN 2.0 + extensions moteurs courants
BPMN_NAMESPACES = {
    "bpmn":    "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmn2":   "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "zeebe":   "http://camunda.org/schema/zeebe/1.0",
    "camunda": "http://camunda.org/schema/1.0/bpmn",
    "modeler": "http://camunda.org/schema/modeler/1.0",
    "dc":      "http://www.omg.org/spec/DD/20100524/DC",
    "di":      "http://www.omg.org/spec/DD/20100524/DI",
}

MAX_DEBUG_ITERATIONS = 3


def _validate_xml(xml_str: str) -> tuple[bool, list[str]]:
    """
    Parse le XML et retourne (is_valid, errors).
    Utilise lxml si disponible pour des erreurs plus précises.
    """
    errors = []
    try:
        if LXML_AVAILABLE:
            parser = etree.XMLParser(recover=False)
            etree.fromstring(xml_str.encode("utf-8"), parser)
        else:
            ET.fromstring(xml_str)
        return True, []
    except Exception as e:
        errors.append(str(e))
        return False, errors


def _check_bpmn_structure(xml_str: str) -> list[str]:
    """
    Vérifie la présence des éléments BPMN minimaux :
    - au moins un process
    - au moins un startEvent
    - au moins un endEvent
    """
    warnings = []
    lower = xml_str.lower()
    if "startevent" not in lower:
        warnings.append("Aucun startEvent détecté.")
    if "endevent" not in lower:
        warnings.append("Aucun endEvent détecté.")
    if "process" not in lower:
        warnings.append("Aucun élément process détecté.")
    return warnings


def bpmn_validator(state: BPACCState) -> dict:
    generated_bpmn  = state.get("generated_bpmn", "").strip()
    debug_iteration = state.get("debug_iteration", 0)
    errors          = list(state.get("errors", []))

    if not generated_bpmn:
        errors.append("bpmn_validator: generated_bpmn vide.")
        return {
            "bpmn_valid":      False,
            "bpmn_errors":     errors,
            "errors":          errors,
            "status":          "failed",
            "current_node":    "bpmn_validator",
        }

    is_valid, xml_errors   = _validate_xml(generated_bpmn)
    structure_warnings     = _check_bpmn_structure(generated_bpmn)
    all_errors             = xml_errors + structure_warnings

    if is_valid and not structure_warnings:
        print(f"  [bpmn_validator] ✓ BPMN valide")
        return {
            "bpmn_valid":      True,
            "bpmn_errors":     [],
            "errors":          errors,
            "status":          "running",
            "current_node":    "bpmn_validator",
        }

    print(f"  [bpmn_validator] ✗ BPMN invalide — {len(all_errors)} erreur(s)")
    for e in all_errors:
        print(f"    - {e}")

    return {
        "bpmn_valid":      False,
        "bpmn_errors":     all_errors,
        "debug_iteration": debug_iteration,
        "errors":          errors,
        "status":          "running",
        "current_node":    "bpmn_validator",
    }