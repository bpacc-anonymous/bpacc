"""
BPACC - B1 BPMN Persistence
Sauvegarde le BPMN généré et son rapport d'explication.

Appelé après bpmn_validator (si valide) ou après response_generator.
Produit deux fichiers dans output/ :
  - bpacc_process_{timestamp}.bpmn  : le BPMN XML exécutable
  - bpacc_process_{timestamp}.json  : le rapport complet (tâches, gaps, matches, résumé)
"""

from __future__ import annotations
import json
import os
import datetime
from pathlib import Path
from bpacc.bp_layers.B1.state import BPACCState

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output"


def persist_bpmn(state: BPACCState) -> dict:
    """
    Sauvegarde le BPMN XML et le rapport JSON dans output/.
    Idempotent — crée le répertoire si absent.
    """
    generated_bpmn     = state.get("generated_bpmn", "")
    bpmn_valid         = state.get("bpmn_valid", False)
    consolidated_tasks = state.get("consolidated_tasks", [])
    task_matches       = state.get("task_matches", [])
    capability_gaps    = state.get("capability_gaps", [])
    dropped_tasks      = state.get("dropped_tasks", [])
    consolidation_summary = state.get("consolidation_summary", "")
    response_summary   = state.get("response_summary", "")
    user_story         = state.get("user_story", "")
    engine_context     = state.get("engine_context", {})
    errors             = list(state.get("errors", []))

    if not generated_bpmn:
        errors.append("persist_bpmn: aucun BPMN à sauvegarder.")
        return {"errors": errors, "current_node": "persist_bpmn"}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Fichier BPMN XML ─────────────────────────────────────────────
    bpmn_path = OUTPUT_DIR / f"bpacc_process_{timestamp}.bpmn"
    with open(bpmn_path, "w", encoding="utf-8") as f:
        f.write(generated_bpmn)

    # ── Rapport JSON ─────────────────────────────────────────────────
    report = {
        "meta": {
            "generated_at":  datetime.datetime.now().isoformat(),
            "bpmn_valid":    bpmn_valid,
            "engine":        engine_context.get("engine", "camunda"),
            "version":       engine_context.get("version", "8.8"),
            "bpmn_file":     str(bpmn_path),
            "char_count":    len(generated_bpmn),
        },
        "process": {
            "title":         user_story[:120] if user_story else "BPACC Process",
            "task_count_original":     len(state.get("tasks", [])),
            "task_count_consolidated": len(consolidated_tasks),
            "gap_count":               len(capability_gaps),
        },
        "consolidated_tasks": [
            {
                "label":        t.get("label"),
                "cap_name":     t.get("cap_name"),
                "task_type":    t.get("task_type"),
                "dependencies": t.get("dependencies", []),
                "merged_from":  t.get("merged_from", []),
            }
            for t in consolidated_tasks
        ],
        "capability_matches": [
            {
                "label":    m.get("label"),
                "cap_name": m.get("cap_name"),
                "target":   m.get("target"),
                "latency":  m.get("latency"),
                "locality": m.get("locality"),
                "distance": m.get("distance"),
                "matched":  m.get("matched"),
            }
            for m in task_matches
        ],
        "capability_gaps":    capability_gaps,
        "dropped_tasks":      dropped_tasks,
        "consolidation_summary": consolidation_summary,
        "response_summary":   json.loads(response_summary) if response_summary else {},
    }

    report_path = OUTPUT_DIR / f"bpacc_process_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Symlinks "latest" pour faciliter l'accès
    latest_bpmn   = OUTPUT_DIR / "bpacc_process_latest.bpmn"
    latest_report = OUTPUT_DIR / "bpacc_process_latest.json"
    for link, target in [(latest_bpmn, bpmn_path), (latest_report, report_path)]:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)

    print(f"\n  [persist_bpmn] ✓ BPMN       → {bpmn_path}")
    print(f"  [persist_bpmn] ✓ Rapport    → {report_path}")
    print(f"  [persist_bpmn] ✓ Latest     → {latest_bpmn}")
    print(f"  [persist_bpmn] bpmn_valid={bpmn_valid} | {len(consolidated_tasks)} tâches | {len(capability_gaps)} gap(s)")

    return {
        "bpmn_path":    str(bpmn_path),
        "report_path":  str(report_path),
        "errors":       errors,
        "current_node": "persist_bpmn",
    }