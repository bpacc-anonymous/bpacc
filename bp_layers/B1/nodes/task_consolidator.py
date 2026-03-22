"""
BPACC - B1 Node 5b : task_consolidator
Regroupe les tâches selon les résultats du retrieval ρ(n).
- Fusionne les tâches qui mappent sur le même service
- Documente les gaps
- Produit consolidated_tasks sur lesquelles le BPMN sera généré
"""

from __future__ import annotations
import json
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.task_consolidator_prompt import (
    TASK_CONSOLIDATOR_SYSTEM, TASK_CONSOLIDATOR_PROMPT
)


def task_consolidator(state: BPACCState) -> dict:
    tasks           = state.get("tasks", [])
    task_matches    = state.get("task_matches", [])
    capability_gaps = state.get("capability_gaps", [])
    errors          = list(state.get("errors", []))

    task_matches_detail = []
    for match in task_matches:
        task_matches_detail.append({
            "label":    match.get("label"),
            "cap_name": match.get("cap_name"),
            "matched":  match.get("matched"),
            "distance": match.get("distance"),
            "target":   match.get("target"),
            "task_type": next(
                (t.get("task_type") for t in tasks if t.get("label") == match.get("label")),
                "automated"
            ),
            "dependencies": next(
                (t.get("dependencies") for t in tasks if t.get("label") == match.get("label")),
                []
            ),
        })

    llm    = reformulation_llm(system_prompt=TASK_CONSOLIDATOR_SYSTEM)
    result = llm.invoke_for_json(TASK_CONSOLIDATOR_PROMPT.format(
        task_matches_detail = json.dumps(task_matches_detail, indent=2, ensure_ascii=False),
        capability_gaps     = json.dumps(capability_gaps, ensure_ascii=False),
    ))

    if not result:
        errors.append("task_consolidator: LLM invalide — fallback sur tâches matchées.")
        consolidated = [
            {
                "label":        m.get("label"),
                "cap_name":     m.get("cap_name"),
                "task_type":    "automated",
                "dependencies": [],
                "merged_from":  [m.get("label")],
                "justification": "No consolidation — fallback.",
            }
            for m in task_matches if m.get("matched")
        ]
        result = {
            "consolidated_tasks":    consolidated,
            "dropped_tasks":         [{"label": g, "reason": "capability gap"} for g in capability_gaps],
            "consolidation_summary": "Fallback consolidation — no merging applied.",
        }

    consolidated_tasks = result.get("consolidated_tasks", [])
    dropped_tasks      = result.get("dropped_tasks", [])
    summary            = result.get("consolidation_summary", "")

    print(f"\n  [task_consolidator] {len(consolidated_tasks)} tâches consolidées "
          f"({len(task_matches)} matchées → {len(consolidated_tasks)} finales)")
    print(f"  [task_consolidator] {len(dropped_tasks)} tâche(s) supprimée(s)")
    print(f"  [task_consolidator] {summary[:120]}...")

    # DEBUG dépendances — à retirer après validation
    print("\n  [task_consolidator] DEBUG dépendances :")
    for ct in consolidated_tasks:
        print(f"    {ct['label']!r} → deps={ct.get('dependencies', [])}")

    return {
        "consolidated_tasks":    consolidated_tasks,
        "dropped_tasks":         dropped_tasks,
        "consolidation_summary": summary,
        "task_count":            len(consolidated_tasks),
        "errors":                errors,
        "status":                "running",
        "current_node":          "task_consolidator",
    }