"""
BPACC - B1 Node 3 : task_estimator
Estime le nombre maximum de tâches BPMN atomiques à extraire de la user story.
Produit task_count et task_hints utilisés par le node 4 (task_decomposer).
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.task_estimator_prompt import (
    TASK_ESTIMATOR_SYSTEM, TASK_ESTIMATOR_PROMPT
)



def task_estimator(state: BPACCState) -> dict:
    user_story = state.get("user_story", "").strip()
    errors     = list(state.get("errors", []))

    llm    = reformulation_llm(system_prompt=TASK_ESTIMATOR_SYSTEM)
    prompt = TASK_ESTIMATOR_PROMPT.format(user_story=user_story)
    result = llm.invoke_for_json(prompt)

    if not result:
        errors.append("task_estimator: LLM returned invalid JSON.")
        return {"errors": errors, "status": "failed", "current_node": "task_estimator"}

    task_count = result.get("task_count")
    task_hints = result.get("task_hints", [])

    if not isinstance(task_count, int) or task_count < 1:
        errors.append(f"task_estimator: task_count invalide ({task_count}).")
        return {"errors": errors, "status": "failed", "current_node": "task_estimator"}

    return {
        "task_count":     task_count,
        "task_hints":     task_hints,
        "task_iteration": 0,
        "tasks":          [],
        "errors":         errors,
        "status":         "running",
        "current_node":   "task_estimator",
    }