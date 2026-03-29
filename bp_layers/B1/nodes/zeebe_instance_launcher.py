"""
BPACC - B1 Node : zeebe_instance_launcher
Lance une instance de processus Zeebe après déploiement par zeebe_deployer.

Placement : bpacc/bp_layers/B1/nodes/zeebe_instance_launcher.py
Prérequis  : pip install httpx

Conformité architecturale (papier BPACC) :
  Les variables initiales injectées dans l'instance Zeebe instancient Σctx
  au sens du papier — elles émergent exclusivement de governance_constraints
  (produit par intent_reformulator depuis le user intent) et des tâches
  consolidées enrichies par instance_resolver.
  Aucune valeur métier n'est codée en dur — Zero-Trust approach.

Note Zeebe 8.8 : processDefinitionKey doit être passé en string (int64 trop grand).
"""

from __future__ import annotations
import json
import os
import httpx
from bpacc.bp_layers.B1.state import BPACCState

ZEEBE_REST_URL     = os.environ.get("ZEEBE_REST_URL", "http://localhost:8088")
INSTANCES_ENDPOINT = f"{ZEEBE_REST_URL}/v2/process-instances"
TIMEOUT_S          = 30

# Valeurs de repli — appliquées UNIQUEMENT si governance_constraints est absent
# du state (cas de démarrage partiel ou test hors-flux normal).
# Ces défauts sont alignés sur _DEFAULTS dans intent_reformulator.py.
_GOV_DEFAULTS = {
    "region":        "eu",
    "latency":       "standard",
    "target_node":   "EdgeNode",
    "data_type":     "personal",
    "consent":       "false",
    "data_locality": "none",
}


def _build_initial_variables(state: BPACCState) -> dict:
    """
    Construit les variables initiales à injecter dans l'instance Zeebe.

    Ordre de priorité pour les variables de gouvernance :
      1. governance_constraints du state (produit par intent_reformulator)
      2. Défauts de _GOV_DEFAULTS (fallback uniquement — jamais la source primaire)

    Les connecteurs BPACC (ex: bpacc-audiorecording.json) lisent ces variables
    via zeebe:input pour construire le Capability Profile Payload envoyé à RabbitMQ.
    Elles instancient Σctx = (region, latency, target_node) au sens du papier,
    complétées par data_type et consent qui activent les règles Rego R1/R2 dans B3.
    """
    gov = state.get("governance_constraints") or {}

    # ── Variables de gouvernance (Σctx) ──────────────────────────────
    region      = gov.get("region",        _GOV_DEFAULTS["region"])
    latency     = gov.get("latency",       _GOV_DEFAULTS["latency"])
    target_node = gov.get("target_node",   _GOV_DEFAULTS["target_node"])
    data_type   = gov.get("data_type",     _GOV_DEFAULTS["data_type"])
    consent     = gov.get("consent",       _GOV_DEFAULTS["consent"])
    locality    = gov.get("data_locality", _GOV_DEFAULTS["data_locality"])

    source_label = "governance_constraints (state)" if gov else "fallback (_GOV_DEFAULTS)"
    print(f"  [zeebe_instance_launcher] variables gouvernance ← {source_label}")
    print(f"    region={region!r}  latency={latency!r}  target_node={target_node!r}")
    print(f"    data_type={data_type!r}  consent={consent!r}  data_locality={locality!r}")

    variables: dict = {
        # Consommées par les connecteurs BPACC via zeebe:input (Σctx)
        "governance_region":        region,
        "governance_latency":       latency,
        "governance_target_node":   target_node,
        # Consommées par OPA Gatekeeper (B3) via les annotations du Pod
        "governance_data_type":     data_type,
        "governance_consent":       consent,
        "governance_data_locality": locality,
    }

    # ── Métadonnées process (contexte narratif, visible dans Operate) ─
    user_story = state.get("user_story", "")
    if user_story:
        variables["process_title"] = user_story[:200]

    # ── Tâches consolidées (traçabilité dans Operate) ─────────────────
    consolidated_tasks = state.get("consolidated_tasks", [])
    if consolidated_tasks:
        variables["task_count"]  = len(consolidated_tasks)
        variables["task_labels"] = [t.get("label", "") for t in consolidated_tasks]

        # Instances concrètes résolues par instance_resolver (s ∈ members(ID))
        # Permettent au Smart Listener de vérifier cap_id ↔ concrete_id sans LLM
        concrete_ids = [
            t.get("concrete_id") for t in consolidated_tasks if t.get("concrete_id")
        ]
        if concrete_ids:
            variables["concrete_instance_ids"] = concrete_ids

    # ── Capability gaps (information dans Operate) ────────────────────
    capability_gaps = state.get("capability_gaps", [])
    if capability_gaps:
        variables["capability_gaps"] = capability_gaps

    # ── Chemin du BPMN source (traçabilité) ──────────────────────────
    bpmn_path = state.get("bpmn_path", "")
    if bpmn_path:
        variables["bpmn_source_path"] = bpmn_path

    return variables


def _debug_pre_launch(payload: dict) -> None:
    """Affiche le payload et l'endpoint avant l'appel REST."""
    print(f"  [zeebe_instance_launcher] ── DEBUG PRÉ-LANCEMENT ──")
    print(f"  [zeebe_instance_launcher] INSTANCES_ENDPOINT = {INSTANCES_ENDPOINT}")
    print(f"  [zeebe_instance_launcher] payload (tronqué)  :")
    payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
    for line in payload_str.splitlines()[:30]:
        print(f"    {line}")
    if len(payload_str.splitlines()) > 30:
        print(f"    ... ({len(payload_str.splitlines())} lignes total)")
    print(f"  [zeebe_instance_launcher] ─────────────────────────")


def zeebe_instance_launcher(state: BPACCState) -> dict:
    """Lance une instance du processus déployé par zeebe_deployer."""
    process_definition_key = state.get("zeebe_process_definition_key", "")
    process_id             = state.get("zeebe_process_id", "")
    errors                 = list(state.get("errors", []))

    print(f"  [zeebe_instance_launcher] process_definition_key = '{process_definition_key}'")
    print(f"  [zeebe_instance_launcher] process_id             = '{process_id}'")

    # Zeebe 8.8 : lancement préférentiel par processDefinitionKey (int64 → string)
    # Fallback sur processDefinitionId si la key est absente
    if process_definition_key and process_definition_key != "unknown":
        payload = {
            "processDefinitionKey": str(process_definition_key),
            "variables":            _build_initial_variables(state),
        }
        print(f"  [zeebe_instance_launcher] stratégie : processDefinitionKey={process_definition_key}")
    elif process_id and process_id != "unknown":
        payload = {
            "processDefinitionId": process_id,
            "variables":           _build_initial_variables(state),
        }
        print(f"  [zeebe_instance_launcher] stratégie : processDefinitionId={process_id}")
    else:
        msg = (
            "zeebe_instance_launcher: processDefinitionKey et processDefinitionId "
            "absents ou 'unknown' — le déploiement a-t-il retourné une réponse valide ?"
        )
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")
        return {
            "zeebe_instance_status": "failed",
            "errors":                errors,
            "current_node":          "zeebe_instance_launcher",
        }

    _debug_pre_launch(payload)

    print(f"  [zeebe_instance_launcher] POST {INSTANCES_ENDPOINT}")
    try:
        response = httpx.post(INSTANCES_ENDPOINT, json=payload, timeout=TIMEOUT_S)

        print(f"  [zeebe_instance_launcher] HTTP {response.status_code}")
        print(f"  [zeebe_instance_launcher] headers réponse : {dict(response.headers)}")

        response.raise_for_status()
        data = response.json()
        print(f"  [zeebe_instance_launcher] payload réponse : {str(data)[:400]}")

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

    except httpx.ConnectError as e:
        msg = (
            f"zeebe_instance_launcher: ConnectError — Zeebe injoignable "
            f"sur {ZEEBE_REST_URL} : {e}"
        )
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")
        print(f"  [zeebe_instance_launcher]   → Vérifier ZEEBE_REST_URL.")

    except httpx.TimeoutException:
        msg = f"zeebe_instance_launcher: Timeout ({TIMEOUT_S}s) — Zeebe ne répond pas."
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")

    except httpx.HTTPStatusError as e:
        msg = (
            f"zeebe_instance_launcher: HTTP {e.response.status_code} "
            f"— {e.response.text[:400]}"
        )
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")
        print(f"  [zeebe_instance_launcher]   → Payload envoyé : {json.dumps(payload)[:300]}")

    except Exception as e:
        msg = f"zeebe_instance_launcher: erreur inattendue — {type(e).__name__}: {e}"
        errors.append(msg)
        print(f"  [zeebe_instance_launcher] ✗ {msg}")

    return {
        "zeebe_instance_status": "failed",
        "errors":                errors,
        "current_node":          "zeebe_instance_launcher",
    }