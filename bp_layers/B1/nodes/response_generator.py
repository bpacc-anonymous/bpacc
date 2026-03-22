"""
BPACC - B1 Node 10 : response_generator
Produit une explication claire pour le Business Analyst :
- ce qui a été généré
- les capability gaps éventuels
- les prochaines étapes
Puis attend la validation ou le rejet de l'utilisateur.
"""

from __future__ import annotations
import json
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.response_generator_prompt import (
    RESPONSE_GENERATOR_SYSTEM, RESPONSE_GENERATOR_PROMPT
)


def response_generator(state: BPACCState) -> dict:
    tasks            = state.get("tasks", [])
    task_matches     = state.get("task_matches", [])
    capability_gaps  = state.get("capability_gaps", [])
    bpmn_valid       = state.get("bpmn_valid", False)
    user_story       = state.get("user_story", "")
    errors           = list(state.get("errors", []))

    # Résumé des matches pour le prompt
    task_matches_summary = "\n".join(
        f"  - {m.get('label')} → {m.get('cap_name')} "
        f"(distance={m.get('distance')}, matched={m.get('matched')})"
        for m in task_matches
    ) or "None."

    llm = reformulation_llm(system_prompt=RESPONSE_GENERATOR_SYSTEM)

    prompt = RESPONSE_GENERATOR_PROMPT.format(
        title                = user_story[:80] if user_story else "BPACC Process",
        bpmn_valid           = bpmn_valid,
        task_count           = len(tasks),
        capability_gaps      = json.dumps(capability_gaps, ensure_ascii=False),
        errors               = json.dumps(errors[-5:], ensure_ascii=False),  # dernières erreurs
        task_matches_summary = task_matches_summary,
    )

    result = llm.invoke_for_json(prompt)

    if not result:
        # Fallback déterministe si le LLM échoue
        result = {
            "status":           "partial" if capability_gaps else ("success" if bpmn_valid else "failed"),
            "summary":          f"Process generated with {len(tasks)} tasks. "
                                f"{len(capability_gaps)} capability gap(s) detected.",
            "matched_tasks":    [f"{m.get('label')} → {m.get('cap_name')}" for m in task_matches if m.get("matched")],
            "gap_explanation":  f"Missing capabilities: {', '.join(capability_gaps)}" if capability_gaps else None,
            "next_steps":       "Validate the generated BPMN or notify the Continuum Engineer for missing capabilities.",
        }

    response_summary = json.dumps(result, indent=2, ensure_ascii=False)

    print(f"\n  [response_generator] status={result.get('status')}")
    print(f"  {result.get('summary', '')}")

    return {
        "response_summary":  response_summary,
        "validation_status": "pending",
        "errors":            errors,
        "status":            "waiting_human",
        "current_node":      "response_generator",
    }