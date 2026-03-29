"""
BPACC - B1 Node : zeebe_deployer
Déploie automatiquement le BPMN généré vers Zeebe (Camunda 8 Self-Managed)
après approbation du Business Analyst dans human_validator.

Placement : bpacc/bp_layers/B1/nodes/zeebe_deployer.py
Prérequis : pip install httpx

Note Zeebe 8.8 : la réponse /v2/deployments utilise "processDefinition" (pas "process")
et "processDefinitionId" (pas "bpmnProcessId") comme clés internes.
"""

from __future__ import annotations
import os
import httpx
from pathlib import Path
from bpacc.bp_layers.B1.state import BPACCState

ZEEBE_REST_URL   = os.environ.get("ZEEBE_REST_URL", "http://localhost:8088")
DEPLOY_ENDPOINT  = f"{ZEEBE_REST_URL}/v2/deployments"
TIMEOUT_S        = 30


def _parse_deployment_response(data: dict) -> dict:
    """
    Parse la réponse /v2/deployments de Zeebe 8.8.

    Zeebe 8.8 retourne :
      {
        "deployments": [
          {
            "processDefinition": {          ← clé = "processDefinition" (pas "process")
              "processDefinitionKey":  "...",
              "processDefinitionId":   "...",  ← pas "bpmnProcessId"
              "processDefinitionVersion": 1,
              "resourceName": "...",
              "tenantId": "..."
            }
          }
        ]
      }

    Retourne un dict normalisé avec les clés attendues par le reste du graph.
    """
    deployments = data.get("deployments", [])

    # Zeebe 8.8 — clé "processDefinition"
    process_info = next(
        (d["processDefinition"] for d in deployments if "processDefinition" in d),
        None
    )

    # Fallback Zeebe < 8.8 — clé "process" (rétrocompatibilité)
    if process_info is None:
        process_info = next(
            (d["process"] for d in deployments if "process" in d),
            {}
        )

    if not process_info:
        return {}

    return {
        # Zeebe 8.8 : processDefinitionKey (identique entre les deux versions)
        "key":     str(process_info.get("processDefinitionKey", "unknown")),
        # Zeebe 8.8 : processDefinitionId  |  Zeebe < 8.8 : bpmnProcessId
        "pid":     process_info.get("processDefinitionId")
                   or process_info.get("bpmnProcessId", "unknown"),
        # Zeebe 8.8 : processDefinitionVersion  |  Zeebe < 8.8 : version
        "version": str(process_info.get("processDefinitionVersion")
                       or process_info.get("version", "unknown")),
    }


def _debug_connectivity() -> None:
    """
    Vérifie la connectivité vers le gateway Zeebe REST avant le déploiement.
    Tente un GET sur /v2/topology pour diagnostiquer les problèmes réseau.
    """
    topology_url = f"{ZEEBE_REST_URL}/v2/topology"
    print(f"  [zeebe_deployer] ── DEBUG CONNECTIVITÉ ──")
    print(f"  [zeebe_deployer] ZEEBE_REST_URL  = {ZEEBE_REST_URL}")
    print(f"  [zeebe_deployer] DEPLOY_ENDPOINT = {DEPLOY_ENDPOINT}")
    print(f"  [zeebe_deployer] Sonde topology  → {topology_url}")
    try:
        resp = httpx.get(topology_url, timeout=5)
        print(f"  [zeebe_deployer] topology HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            brokers = data.get("brokers", [])
            print(f"  [zeebe_deployer] brokers actifs : {len(brokers)}")
            for b in brokers:
                print(f"    broker {b.get('nodeId')} — {b.get('host')}:{b.get('port')} "
                      f"version={b.get('version','?')}")
        else:
            print(f"  [zeebe_deployer] ⚠ topology réponse inattendue : {resp.text[:200]}")
    except httpx.ConnectError as e:
        print(f"  [zeebe_deployer] ✗ ConnectError — Zeebe injoignable : {e}")
        print(f"  [zeebe_deployer]   → Vérifier que le gateway Zeebe REST tourne sur {ZEEBE_REST_URL}")
        print(f"  [zeebe_deployer]   → Variables d'env : export ZEEBE_REST_URL=http://<host>:8088")
    except httpx.TimeoutException:
        print(f"  [zeebe_deployer] ✗ Timeout (5s) — Zeebe ne répond pas sur {ZEEBE_REST_URL}")
    except Exception as e:
        print(f"  [zeebe_deployer] ✗ Erreur inattendue lors de la sonde : {type(e).__name__}: {e}")
    print(f"  [zeebe_deployer] ─────────────────────────")


def zeebe_deployer(state: BPACCState) -> dict:
    bpmn_path = state.get("bpmn_path", "")
    bpmn_xml  = state.get("generated_bpmn", "")
    errors    = list(state.get("errors", []))

    # ── Debug connectivité avant tout appel ──────────────────────────
    _debug_connectivity()

    # ── Résolution du contenu BPMN ───────────────────────────────────
    if bpmn_path and Path(bpmn_path).exists():
        with open(bpmn_path, encoding="utf-8") as f:
            bpmn_content = f.read()
        filename = Path(bpmn_path).name
        print(f"  [zeebe_deployer] source       : fichier → {filename}")
        print(f"  [zeebe_deployer] taille       : {len(bpmn_content)} chars")
    elif bpmn_xml:
        bpmn_content = bpmn_xml
        filename     = "bpacc_process.bpmn"
        print(f"  [zeebe_deployer] source       : state (generated_bpmn)")
        print(f"  [zeebe_deployer] taille       : {len(bpmn_content)} chars")
    else:
        msg = "zeebe_deployer: aucun BPMN disponible (bpmn_path vide et generated_bpmn vide)."
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")
        return {
            "zeebe_deploy_status": "failed",
            "errors":              errors,
            "current_node":        "zeebe_deployer",
        }

    # ── Appel REST API Zeebe ─────────────────────────────────────────
    print(f"  [zeebe_deployer] POST {DEPLOY_ENDPOINT}")
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

        print(f"  [zeebe_deployer] HTTP {response.status_code}")
        print(f"  [zeebe_deployer] headers réponse : {dict(response.headers)}")

        response.raise_for_status()
        data = response.json()
        print(f"  [zeebe_deployer] payload réponse : {str(data)[:400]}")

        # ── Parsing normalisé Zeebe 8.8 / < 8.8 ─────────────────────
        parsed = _parse_deployment_response(data)

        if not parsed:
            msg = (f"zeebe_deployer: impossible de parser la réponse deployments — "
                   f"clés trouvées : {[list(d.keys()) for d in data.get('deployments', [])]}")
            errors.append(msg)
            print(f"  [zeebe_deployer] ✗ {msg}")
            return {
                "zeebe_deploy_status": "failed",
                "errors":              errors,
                "current_node":        "zeebe_deployer",
            }

        key     = parsed["key"]
        pid     = parsed["pid"]
        version = parsed["version"]

        print(f"  [zeebe_deployer] ✓ Déployé avec succès")
        print(f"    processDefinitionKey : {key}")
        print(f"    processDefinitionId  : {pid}")
        print(f"    version              : {version}")
        print(f"    Operate              : {ZEEBE_REST_URL}/operate")

        return {
            "zeebe_deploy_status":          "success",
            "zeebe_process_definition_key": key,
            "zeebe_process_id":             pid,
            "zeebe_version":                version,
            "errors":                       errors,
            "status":                       "deployed",
            "current_node":                 "zeebe_deployer",
        }

    except httpx.ConnectError as e:
        msg = f"zeebe_deployer: ConnectError — Zeebe injoignable sur {ZEEBE_REST_URL} : {e}"
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")
        print(f"  [zeebe_deployer]   → Vérifier ZEEBE_REST_URL et que le gateway est démarré.")

    except httpx.TimeoutException:
        msg = f"zeebe_deployer: Timeout ({TIMEOUT_S}s) — Zeebe ne répond pas."
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")

    except httpx.HTTPStatusError as e:
        msg = (f"zeebe_deployer: HTTP {e.response.status_code} "
               f"— {e.response.text[:400]}")
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")

    except Exception as e:
        msg = f"zeebe_deployer: erreur inattendue — {type(e).__name__}: {e}"
        errors.append(msg)
        print(f"  [zeebe_deployer] ✗ {msg}")

    return {
        "zeebe_deploy_status": "failed",
        "errors":              errors,
        "current_node":        "zeebe_deployer",
    }