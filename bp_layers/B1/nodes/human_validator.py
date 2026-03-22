"""
BPACC - B1 Node 11 : human_validator
Point d'interruption LangGraph — attend la validation du Business Analyst.

Si approuvé  → le BPMN est soumis au Smart Listener (runtime B2)
Si rejeté    → notifie le Continuum Engineer via gap_handler
"""

from __future__ import annotations
from langgraph.types import interrupt
from bpacc.bp_layers.B1.state import BPACCState


def human_validator(state: BPACCState) -> dict:
    response_summary = state.get("response_summary", "")
    generated_bpmn   = state.get("generated_bpmn", "")
    capability_gaps  = state.get("capability_gaps", [])
    errors           = list(state.get("errors", []))

    # Interruption LangGraph — suspend le graph et expose les données à l'interface
    human_input = interrupt({
        "response_summary": response_summary,
        "generated_bpmn":   generated_bpmn,
        "capability_gaps":  capability_gaps,
        "question":         (
            "Please review the generated BPMN process. "
            "Do you approve it for submission to the execution engine? "
            "Reply with 'approved' or 'rejected' and optionally provide feedback."
        ),
    })

    validation_status = human_input.get("validation_status", "rejected").lower()
    analyst_feedback  = human_input.get("feedback", "")

    print(f"  [human_validator] validation_status={validation_status}")

    return {
        "validation_status": validation_status,
        "analyst_feedback":  analyst_feedback,
        "errors":            errors,
        "status":            "running",
        "current_node":      "human_validator",
    }