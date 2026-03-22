"""
BPACC - B1 Node : zeebe_deployer
Déploie automatiquement le BPMN généré vers Zeebe (Camunda 8 Self-Managed)
après approbation du Business Analyst dans human_validator.

Placement : bpacc/bp_layers/B1/nodes/zeebe_deployer.py
Prérequis : pip install httpx
"""

from __future__ import annotations
import os
import httpx
from pathlib import Path
from bpacc.bp_layers.B1.state import BPACCState

ZEEBE_REST_URL   = os.environ.get("ZEEBE_REST_URL", "http://localhost:8088")
DEPLOY_ENDPOINT  = f"{ZEEBE_REST_URL}/v2/deployments"
TIMEOUT_S        = 30


def zeebe_deployer(state: BPACCState) -> dict:
    bpmn_path = state.get("bpmn_path", "")
    bpmn_xml  = state.get("generated_bpmn", "")
    errors    = list(state.get("errors", []))

    # ── Résolution du contenu BPMN ───────────────────────────────────
    if bpmn_path and Path(bpmn_path).exists():
        with open(bpmn_path, encoding="utf-8") as f:
            bpmn_content = f.read()
        filename = Path(bpmn_path).name
        print(f"  [zeebe_deployer] source : fichier → {filename}")
    elif bpmn_xml:
        bpmn_content = bpmn_xml
        filename = "bpacc_process.bpmn"
        print(f"  [zeebe_deployer] source : state (generated_bpmn)")
    else:
        errors.append("zeebe_deployer: aucun BPMN disponible.")
        return {
            "zeebe_deploy_status": "failed",
            "errors": errors,
            "current_node": "zeebe_deployer",
        }

    # ── Appel REST API Zeebe ─────────────────────────────────────────
    try:
        response = httpx.post(
            DEPLOY_ENDPOINT,
            files={
                "resources": (
                    filename,
                    bpmn_content.encode("utf-8"),
                    "application/octet-stream",
                )
            },
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()

        deployments  = data.get("deployments", [])
        process_info = next(
            (d["process"] for d in deployments if "process" in d), {}
        )

        key      = str(process_info.get("processDefinitionKey", "unknown"))
        pid      = process_info.get("bpmnProcessId", "unknown")
        version  = str(process_info.get("version", "unknown"))

        print(f"  [zeebe_deployer] ✓ Déployé avec succès")
        print(f"    processDefinitionKey : {key}")
        print(f"    bpmnProcessId        : {pid}")
        print(f"    version              : {version}")
        print(f"    Operate              : {ZEEBE_REST_URL}/operate")

        return {
            "zeebe_deploy_status":             "success",
            "zeebe_process_definition_key":    key,
            "zeebe_process_id":                pid,
            "zeebe_version":                   version,
            "errors":                          errors,
            "status":                          "deployed",
            "current_node":                    "zeebe_deployer",
        }

    except httpx.HTTPStatusError as e:
        msg = f"zeebe_deployer: HTTP {e.response.status_code} — {e.response.text[:300]}"
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")

    except Exception as e:
        msg = f"zeebe_deployer: erreur — {e}"
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")

    return {
        "zeebe_deploy_status": "failed",
        "errors": errors,
        "current_node": "zeebe_deployer",
    }