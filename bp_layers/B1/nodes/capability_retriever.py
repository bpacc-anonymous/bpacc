"""
BPACC - B1 Node 5 : capability_retriever
Pour chaque tâche, appelle retrieve() de l'étape 5 (GraphRAG sur Tₙ).
Produit task_matches et capability_gaps.
Pas de LLM — retrieval sémantique via ChromaDB + SBERT.
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState, TaskMatch
from bpacc.capability_profiles_builder.design_time.graph_rag import retrieve

THETA_SIM = 0.65  # Seuil de distance cosinus — au-delà : capability gap


def capability_retriever(state: BPACCState) -> dict:
    tasks  = state.get("tasks", [])
    errors = list(state.get("errors", []))

    task_matches:    list[TaskMatch] = []
    capability_gaps: list[str]       = []

    for task in tasks:
        label       = task.get("label", "")
        description = task.get("description", "")

        # On retrieve sur la description enrichie — pas le label brut
        results = retrieve(description, top_k=1)

        if not results:
            errors.append(f"capability_retriever: aucun résultat pour '{label}'.")
            capability_gaps.append(label)
            continue

        top = results[0]
        matched = top["distance"] < THETA_SIM

        match: TaskMatch = {
            "label":    label,
            "cap_name": top.get("cap_name", ""),
            "parent":   top.get("parent", ""),
            "target":   top.get("target", ""),
            "latency":  top.get("latency", ""),
            "locality": top.get("locality", ""),
            "region":   top.get("region", ""),
            "inputs":   top.get("inputs", []),
            "impl":     top.get("impl", ""),
            "distance": top["distance"],
            "matched":  matched,
        }

        task_matches.append(match)

        status = "✓" if matched else "✗ GAP"
        print(f"  [retriever] {label:<35} → {top['cap_name']:<30} distance={top['distance']} {status}")

        if not matched:
            capability_gaps.append(label)

    return {
        "task_matches":    task_matches,
        "capability_gaps": capability_gaps,
        "errors":          errors,
        "status":          "running",
        "current_node":    "capability_retriever",
    }