"""
BPACC - B1 Node : zeebe_instance_launcher
Lance une instance de processus Zeebe après déploiement par zeebe_deployer.

Placement : bpacc/bp_layers/B1/nodes/zeebe_instance_launcher.py
Prérequis  : pip install httpx

Note Zeebe 8.8 : processDefinitionKey doit être passé en string (int64 trop grand).
"""

from __future__ import annotations
import os
import httpx
from bpacc.bp_layers.B1.state import BPACCState

ZEEBE_REST_URL     = os.environ.get("ZEEBE_REST_URL", "http://localhost:8088")
INSTANCES_ENDPOINT = f"{ZEEBE_REST_URL}/v2/process-instances"
TIMEOUT_S          = 30


def _build_initial_variables(state: BPACCState) -> dict:
    """Construit les variables initiales à injecter dans l'instance."""
    variables = {
        "governance_region":      "eu",
        "governance_latency":     "standard",
        "governance_target_node": "EdgeNode",
    }

    user_story = state.get("user_story", "")
    if user_story:
        variables["process_title"] = user_story[:200]

    capability_gaps = state.get("capability_gaps", [])
    if capability_gaps:
        variables["capability_gaps"] = capability_gaps

    consolidated_tasks = state.get("consolidated_tasks", [])
    if consolidated_tasks:
        variables["task_count"]  = len(consolidated_tasks)
        variables["task_labels"] = [t.get("label", "") for t in consolidated_tasks]

    bpmn_path = state.get("bpmn_path", "")
    if bpmn_path:
        variables["bpmn_source_path"] = bpmn_path

    return variables


def zeebe_instance_launcher(state: BPACCState) -> dict:
    """Lance une instance du processus déployé par zeebe_deployer."""
    process_definition_key = state.get("zeebe_process_definition_key", "")
    process_id             = state.get("zeebe_process_id", "")
    errors                 = list(state.get("errors", []))

    if not process_definition_key or process_definition_key == "unknown":
        if not process_id:
            msg = "zeebe_instance_launcher: processDefinitionKey et processId absents."
            errors.append(msg)
            print(f"  [zeebe_instance_launcher] ✗ {msg}")
            return {
                "zeebe_instance_status": "failed",
                "errors": errors,
                "current_node": "zeebe_instance_launcher",
            }
        payload = {
            "bpmnProcessId": process_id,
            "variables":     _build_initial_variables(state),
        }
        print(f"  [zeebe_instance_launcher] lancement par bpmnProcessId={process_id}")
    else:
        # Zeebe 8.8 : la key int64 doit être passée en string dans le JSON
        payload = {
            "processDefinitionKey": str(process_definition_key),
            "variables":            _build_initial_variables(state),
        }
        print(f"  [zeebe_instance_launcher] lancement par key={process_definition_key}")

    try:
        response = httpx.post(INSTANCES_ENDPOINT, json=payload, timeout=TIMEOUT_S)
        response.raise_for_status()
        data = response.json()

        instance_key = str(data.get("processInstanceKey", "unknown"))
        pid          = data.get("processDefinitionId", process_id)
        version      = str(data.get("processDefinitionVersion", "unknown"))

        print(f"  [zeebe_instance_launcher] ✓ Instance lancée")
        print(f"    processInstanceKey  : {instance_key}")
        print(f"    processDefinitionId : {pid}")
        print(f"    version             : {version}")
        print(f"    Operate             : {ZEEBE_REST_URL}/operate")

        return {
            "zeebe_instance_status": "success",
            "zeebe_instance_key":    instance_key,
            "zeebe_process_id":      pid,
            "zeebe_version":         version,
            "errors":                errors,
            "status":                "running",
            "current_node":          "zeebe_instance_launcher",
        }

    except httpx.HTTPStatusError as e:
        msg = f"zeebe_instance_launcher: HTTP {e.response.status_code} — {e.response.text[:300]}"
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")

    except Exception as e:
        msg = f"zeebe_instance_launcher: erreur — {e}"
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")

    return {
        "zeebe_instance_status": "failed",
        "errors":                errors,
        "current_node":          "zeebe_instance_launcher",
    }