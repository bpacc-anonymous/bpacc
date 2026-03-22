"""
BPACC - B1 Node 4 : task_decomposer
Extrait les tâches BPMN une par une de façon incrémentale.

Boucle : appelé task_count fois par le graph.
À chaque itération i :
  - a en contexte les tâches 0..i-1 déjà extraites
  - produit la tâche i
  - incrémente task_iteration

Le graph route vers capability_retriever quand task_iteration == task_count.
"""

from __future__ import annotations
import json
from bpacc.bp_layers.B1.state import BPACCState, TaskItem
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.task_decomposer_prompt import (
    TASK_DECOMPOSER_SYSTEM, TASK_DECOMPOSER_PROMPT
)


def task_decomposer(state: BPACCState) -> dict:
    user_story      = state.get("user_story", "").strip()
    task_count      = state.get("task_count", 0)
    task_iteration  = state.get("task_iteration", 0)
    tasks           = list(state.get("tasks", []))
    task_hints      = state.get("task_hints", [])
    errors          = list(state.get("errors", []))

    # Contexte : tâches déjà extraites
    extracted_tasks = json.dumps(
        [{"label": t["label"], "description": t["description"]} for t in tasks],
        indent=2, ensure_ascii=False
    ) if tasks else "None yet."

    prompt = TASK_DECOMPOSER_PROMPT.format(
        current_index   = task_iteration + 1,
        task_count      = task_count,
        user_story      = user_story,
        extracted_tasks = extracted_tasks,
        task_hints      = json.dumps(task_hints, ensure_ascii=False),
    )

    llm    = reformulation_llm(system_prompt=TASK_DECOMPOSER_SYSTEM)
    result = llm.invoke_for_json(prompt)

    if not result:
        errors.append(f"task_decomposer: LLM returned invalid JSON at iteration {task_iteration}.")
        return {"errors": errors, "status": "failed", "current_node": "task_decomposer"}

    task: TaskItem = {
        "label":        result.get("label", f"Task_{task_iteration + 1}"),
        "description":  result.get("description", ""),
        "task_type":    result.get("task_type", "automated"),
        "dependencies": result.get("dependencies", []),
    }

    tasks.append(task)

    print(f"  [task_decomposer] {task_iteration + 1}/{task_count} — {task['label']}")

    return {
        "tasks":          tasks,
        "task_iteration": task_iteration + 1,
        "errors":         errors,
        "status":         "running",
        "current_node":   "task_decomposer",
    }