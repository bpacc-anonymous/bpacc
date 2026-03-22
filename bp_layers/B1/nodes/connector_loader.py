"""
BPACC - B1 Node 6 : connector_loader
Charge les connecteurs JSON pour chaque tâche consolidée.
Itère sur consolidated_tasks (post-consolidation) si disponible,
sinon fallback sur task_matches.
Pas de LLM — chargement déterministe depuis le filesystem.
"""

from __future__ import annotations
import json, os
from pathlib import Path
from bpacc.bp_layers.B1.state import BPACCState

import sys

# Chemin absolu depuis la racine du projet
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # remonte 4 niveaux depuis nodes/
CONNECTORS_DIR = str(_PROJECT_ROOT / "bpacc" / "capability_profiles_builder" / "design_time" / "camunda-templates")

# DEBUG chemins — à retirer après validation
print(f"  DEBUG CONNECTORS_DIR={CONNECTORS_DIR}")
print(f"  DEBUG exists={os.path.exists(CONNECTORS_DIR)}")


def _connector_path(cap_name: str) -> str:
    slug = cap_name.lower().replace("_service", "").replace("_", "-")
    return os.path.join(CONNECTORS_DIR, f"bpacc-{slug}.json")


def _find_connector(cap_name: str) -> tuple[str, dict]:
    # Tentative 1 : chemin dérivé direct
    path = _connector_path(cap_name)
    print(f"  DEBUG trying path={path}")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return path, json.load(f)

    # Tentative 2 : recherche par pattern dans le répertoire
    if os.path.isdir(CONNECTORS_DIR):
        slug = cap_name.lower().replace("_service", "").replace("_", "-")
        for fname in os.listdir(CONNECTORS_DIR):
            if fname.endswith(".json") and slug in fname.lower():
                full_path = os.path.join(CONNECTORS_DIR, fname)
                with open(full_path, encoding="utf-8") as f:
                    return full_path, json.load(f)

    return "", {}


def connector_loader(state: BPACCState) -> dict:
    consolidated = state.get("consolidated_tasks", [])
    task_matches = state.get("task_matches", [])
    source       = consolidated if consolidated else [m for m in task_matches if m.get("matched")]
    errors       = list(state.get("errors", []))
    connectors   = {}

    for task in source:
        label    = task.get("label", "")
        cap_name = task.get("cap_name", "")

        if not cap_name:
            errors.append(f"connector_loader: cap_name manquant pour '{label}'")
            print(f"  [connector_loader] ✗ {label:<40} → cap_name manquant")
            continue

        path, content = _find_connector(cap_name)

        if not content:
            errors.append(f"connector_loader: introuvable pour '{cap_name}'")
            print(f"  [connector_loader] ✗ {label:<40} → {cap_name} (introuvable)")
            continue

        connectors[label] = content
        print(f"  [connector_loader] ✓ {label:<40} → {os.path.basename(path)}")

    return {
        "connectors":   connectors,
        "errors":       errors,
        "status":       "running",
        "current_node": "connector_loader",
    }