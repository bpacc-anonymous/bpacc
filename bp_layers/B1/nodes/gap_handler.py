"""
BPACC - B1 Node 12 : gap_handler
Notifie le Continuum Engineer des capability gaps détectés.
Activé si validation_status == "rejected" ou capability_gaps non vide.
"""

from __future__ import annotations
import json
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.gap_handler_prompt import (
    GAP_HANDLER_SYSTEM, GAP_HANDLER_PROMPT
)



def gap_handler(state: BPACCState) -> dict:
    capability_gaps  = state.get("capability_gaps", [])
    task_matches     = state.get("task_matches", [])
    analyst_feedback = state.get("analyst_feedback", "")
    user_story       = state.get("user_story", "")
    errors           = list(state.get("errors", []))

    task_matches_summary = "\n".join(
        f"  - {m.get('label')} → {m.get('cap_name')} (matched={m.get('matched')}, distance={m.get('distance')})"
        for m in task_matches
    ) or "None."

    llm = reformulation_llm(system_prompt=GAP_HANDLER_SYSTEM)

    prompt = GAP_HANDLER_PROMPT.format(
        title                = user_story[:80] if user_story else "BPACC Process",
        analyst_feedback     = analyst_feedback or "No feedback provided.",
        capability_gaps      = json.dumps(capability_gaps, ensure_ascii=False),
        task_matches_summary = task_matches_summary,
    )

    result = llm.invoke_for_json(prompt)

    if not result:
        result = {
            "notification_type": "capability_gap",
            "process_title":     user_story[:80],
            "gaps":              [{"task_label": g, "missing_capability": g} for g in capability_gaps],
            "action_required":   "Deploy missing services in the Services Repository and re-trigger the design-time pipeline.",
        }

    notification = json.dumps(result, indent=2, ensure_ascii=False)

    print(f"\n  [gap_handler] ⚠ {len(capability_gaps)} gap(s) notifiés au Continuum Engineer")
    for gap in result.get("gaps", []):
        print(f"    - {gap.get('task_label')} → {gap.get('suggested_service_id', '?')}")

    return {
        "gap_notification_sent": True,
        "errors":                errors,
        "status":                "done",
        "current_node":          "gap_handler",
    }