"""
BPACC — Smart Listener v2

Rôle formel :
  Consomme les Execution Intents (B2 → RabbitMQ) et soumet l'artefact
  adraft = ⟨s, Qc, Pc, Ic⟩ à B3 (OPA Gatekeeper via K8s Admission Control).

Contrat de message entrant (connecteur Camunda RabbitMQ — immuable) :
  {
    "cap_id":     "bpacc:AudioRecording_Service",
    "qos":        {"latency": "standard"},
    "governance": {
      "region":        "eu",
      "data_locality": "edge-only",    ← Pc — encodé en dur dans le connecteur
      "target_node":   "EdgeNode"      ← Qc — variable Zeebe
    },
    "params": { ... }
  }

Ce que le message ne porte PAS (connecteurs immuables) :
  - data_type, consent → lus depuis les variables de l'instance Zeebe
    via POST /v2/variables/search avec filter.scopeKey=<processInstanceKey>
    (injectées par zeebe_instance_launcher depuis governance_constraints)
  - process_instance_key → injecté par l'orchestrateur via PROCESS_INSTANCE_KEY
    au démarrage du subprocess Listener

Scalabilité :
  - Aucun catalogue chargé au démarrage — zéro état global
  - Lecture Zeebe REST par message, uniquement pour data_type + consent
  - Horizontalement scalable : N instances du Listener sont stateless

Règles Rego évaluées par B3 (OPA Gatekeeper) :
  R1 — Art. 9§1 + 9§2a : données biométriques → consentement explicite requis
  R2 — Art. 44-46 : données biométriques → routage EU uniquement
  R3 — Art. 5§1(f) + Art. 24 : Rglobal prend le dessus sur Pc en cas de conflit
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

import httpx
import pika
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# ── Configuration Cloud-Native ───────────────────────────────────────────────

RABBITMQ_HOST        = os.environ.get("RABBITMQ_HOST",        "localhost")
RABBITMQ_USER        = os.environ.get("RABBITMQ_USER",        "bpacc")
RABBITMQ_PASS        = os.environ.get("RABBITMQ_PASS",        "bpacc")
K8S_NAMESPACE        = os.environ.get("K8S_NAMESPACE",        "default")
ZEEBE_REST_URL       = os.environ.get("ZEEBE_REST_URL",       "http://localhost:8088")
REJECTED_QUEUE       = "bpacc.queue.rejected"
ZEEBE_TIMEOUT        = 5

# Injecté par l'orchestrateur via env var au démarrage du subprocess.
# Absent lors du premier run (avant lancement de l'instance Zeebe) —
# les valeurs Zero-Trust s'appliquent alors.
PROCESS_INSTANCE_KEY = os.environ.get("PROCESS_INSTANCE_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("smart_listener")


# ── Résolution Zeebe — data_type + consent ───────────────────────────────────

def _fetch_zeebe_process_variables(process_instance_key: Optional[str]) -> dict:
    """
    Interroge l'API Zeebe 8.8 pour récupérer les variables de gouvernance.

    Endpoint confirmé : POST /v2/variables/search
    Body              : {"filter": {"scopeKey": "<processInstanceKey>"}}
    Réponse           : {"items": [{"name": "...", "value": "\"...\""}]}

    Les valeurs Zeebe sont JSON-encodées ("\"personal\"" → "personal") —
    désérialisées via json.loads avant retour.

    Race condition : les premières tâches BPMN s'exécutent quasi-instantanément
    après le lancement de l'instance, avant que Zeebe ait indexé les variables
    dans /v2/variables/search. Un retry avec backoff exponentiel est appliqué
    tant que les variables de gouvernance cibles sont absentes de la réponse.

    Retry : 4 tentatives — délais 0.1s, 0.2s, 0.4s, 0.8s (total max ~1.5s).
    Si après 4 tentatives les variables sont toujours absentes, les valeurs
    Zero-Trust s'appliquent — comportement intentionnel (safe default).

    Fallback Zero-Trust si key absente ou Zeebe injoignable :
      data_type="unknown", consent="false"
    """
    _safe_defaults = {
        "governance_data_type":     "unknown",
        "governance_consent":       "false",
        "governance_data_locality": "none",
    }
    _target_keys = {"governance_data_type", "governance_consent"}

    if not process_instance_key:
        log.warning("  [zeebe_vars] process_instance_key absent — valeurs Zero-Trust appliquées")
        return _safe_defaults

    url        = f"{ZEEBE_REST_URL}/v2/variables/search"
    max_retry  = 4
    delay      = 0.1   # secondes — doublement à chaque tentative

    for attempt in range(max_retry):
        try:
            resp = httpx.post(
                url,
                json={"filter": {"scopeKey": str(process_instance_key)}},
                timeout=ZEEBE_TIMEOUT,
            )

            if resp.status_code != 200:
                log.warning(
                    f"  [zeebe_vars] HTTP {resp.status_code} scopeKey={process_instance_key} "
                    f"— valeurs Zero-Trust appliquées"
                )
                return _safe_defaults

            # Les valeurs Zeebe sont JSON-encodées — json.loads les désérialise
            items = resp.json().get("items", [])
            variables = {}
            for item in items:
                name = item.get("name", "")
                raw  = item.get("value", "null")
                try:
                    variables[name] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    variables[name] = raw

            # Si les variables cibles ne sont pas encore indexées → retry
            if not _target_keys.issubset(variables.keys()):
                if attempt < max_retry - 1:
                    log.info(
                        f"  [zeebe_vars] variables governance absentes "
                        f"(tentative {attempt + 1}/{max_retry}) — retry dans {delay:.1f}s"
                    )
                    import time
                    time.sleep(delay)
                    delay *= 2
                    continue
                else:
                    log.warning(
                        f"  [zeebe_vars] variables governance toujours absentes après "
                        f"{max_retry} tentatives — valeurs Zero-Trust appliquées"
                    )
                    return _safe_defaults

            result = {
                "governance_data_type":     str(variables.get("governance_data_type",     _safe_defaults["governance_data_type"])),
                "governance_consent":       str(variables.get("governance_consent",       _safe_defaults["governance_consent"])),
                "governance_data_locality": str(variables.get("governance_data_locality", _safe_defaults["governance_data_locality"])),
            }

            log.info(
                f"  [zeebe_vars] ✓ scopeKey={process_instance_key} "
                f"(tentative {attempt + 1}) → "
                f"data_type={result['governance_data_type']} "
                f"consent={result['governance_consent']}"
            )
            return result

        except httpx.TimeoutException:
            log.warning(f"  [zeebe_vars] Timeout ({ZEEBE_TIMEOUT}s) — valeurs Zero-Trust appliquées")
            return _safe_defaults
        except Exception as e:
            log.warning(f"  [zeebe_vars] Erreur ({type(e).__name__}: {e}) — valeurs Zero-Trust appliquées")
            return _safe_defaults

    return _safe_defaults


# ── Intelligence de Placement ─────────────────────────────────────────────────

def _resolve_target_tier(placement: list[str], requested_node: str) -> str:
    tier_map = {"EndpointNode": "endpoint", "EdgeNode": "edge", "CloudNode": "cloud"}
    req_tier = tier_map.get(requested_node, "edge")

    if req_tier in placement:
        return req_tier

    for tier in ("endpoint", "edge", "cloud"):
        if tier in placement:
            return tier

    return "edge"


# ── Construction du manifeste Pod (adraft) ────────────────────────────────────

def _build_k8s_manifest(message: dict, zeebe_vars: dict, intent_id: str) -> dict:
    """
    Construit adraft = ⟨s, Qc, Pc, Ic⟩ sous forme de manifeste Pod K8s.

    Sources :
      pc_locality ← message.governance.data_locality  (Pc, connecteur immuable)
      data_type   ← zeebe_vars.governance_data_type   (Qc, user intent → B1 → Zeebe)
      consent     ← zeebe_vars.governance_consent     (Qc, user intent → B1 → Zeebe)
    """
    cap_id = message.get("cap_id", "unknown")
    gov    = message.get("governance", {})
    params = message.get("params", {})
    qos    = message.get("qos", {})

    safe_name   = cap_id.replace("bpacc:", "").replace("_", "-").lower()[:40]
    region      = gov.get("region",        "unknown")
    target_node = gov.get("target_node",   "EdgeNode")
    pc_locality = gov.get("data_locality", "none")

    placement_from_locality = {
        "edge-only":      ["edge"],
        "endpoint-only":  ["endpoint"],
        "edge-preferred": ["endpoint", "edge"],
        "strict":         ["edge"],
        "none":           ["endpoint", "edge", "cloud"],
    }
    placement   = placement_from_locality.get(pc_locality, ["edge"])
    target_tier = _resolve_target_tier(placement, target_node)

    data_type = str(zeebe_vars.get("governance_data_type", "unknown"))
    consent   = str(zeebe_vars.get("governance_consent",   "false")).lower()
    image     = params.get("concrete_image") or _derive_image_name(cap_id)

    annotations = {
        "bpacc.io/cap-id":      cap_id,
        "bpacc.io/target-tier": target_tier,
        "bpacc.io/pc-locality": pc_locality,
        "bpacc.io/data-type":   data_type,
        "bpacc.io/consent":     consent,
        "bpacc.io/region":      region,
        "bpacc.io/latency":     qos.get("latency", "best-effort"),
        "bpacc.io/intent-id":   intent_id,
    }

    if "rglobal_mock" in params:
        annotations["bpacc.io/rglobal-locality"] = params["rglobal_mock"]

    env_vars = [
        {"name": str(k).upper(), "value": str(v)}
        for k, v in params.items()
        if k != "rglobal_mock"
    ]

    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"bpacc-{safe_name}-{intent_id[:8]}",
            "labels": {"app": "bpacc", "tier": target_tier, "cap-id": safe_name},
            "annotations": annotations,
        },
        "spec": {
            "restartPolicy": "Never",
            "nodeSelector":  {"topology.kubernetes.io/region": region},
            "containers": [{
                "name":            safe_name,
                "image":           image,
                "imagePullPolicy": "IfNotPresent",
                "env":             env_vars,
            }],
        },
    }


def _derive_image_name(cap_id: str) -> str:
    name = cap_id.replace("bpacc:", "").replace("_Service", "").replace("_", "-").lower()
    return f"bpacc-{name}"


# ── Interface Kubernetes & Admission Control (B3) ─────────────────────────────

def _init_kubernetes() -> None:
    try:
        config.load_kube_config()
        log.info("Client Kubernetes initialisé (kubeconfig local).")
    except Exception:
        try:
            config.load_incluster_config()
            log.info("Client Kubernetes initialisé (in-cluster).")
        except Exception as e:
            log.error(f"Échec initialisation Kubernetes : {e}")
            sys.exit(1)


def _submit_to_kubernetes(manifest: dict) -> tuple[bool, str]:
    v1 = client.CoreV1Api()
    try:
        v1.create_namespaced_pod(namespace=K8S_NAMESPACE, body=manifest)
        return True, "Pod scheduled successfully."
    except ApiException as e:
        if e.status == 403:
            try:
                reason = json.loads(e.body).get("message", e.reason)
                return False, f"B3 ADMISSION REJECTED: {reason}"
            except json.JSONDecodeError:
                return False, f"B3 ADMISSION REJECTED: {e.reason}"
        return False, f"K8s API Error: {e.status} - {e.reason}"


# ── Consumer RabbitMQ ─────────────────────────────────────────────────────────

def _publish_rejection(channel, cap_id: str, intent_id: str, reason: str) -> None:
    payload = {
        "intent_id": intent_id,
        "cap_id":    cap_id,
        "status":    "DENIED_BY_B3",
        "reason":    reason,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    channel.basic_publish(
        exchange="",
        routing_key=REJECTED_QUEUE,
        body=json.dumps(payload),
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )


def on_message(channel, method, properties, body) -> None:
    intent_id = str(uuid.uuid4())
    log.info(f"\n{'─'*60}\n[{intent_id[:8]}] Execution Intent reçu (B2)")

    try:
        message = json.loads(body)
        cap_id  = message.get("cap_id", "")
    except json.JSONDecodeError:
        log.error(f"[{intent_id[:8]}] JSON invalide — message ignoré.")
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    if not cap_id:
        log.error(f"[{intent_id[:8]}] cap_id absent — message ignoré.")
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    log.info(f"[{intent_id[:8]}] cap_id={cap_id}")

    # PROCESS_INSTANCE_KEY injecté par l'orchestrateur via env var
    zeebe_vars  = _fetch_zeebe_process_variables(PROCESS_INSTANCE_KEY or None)
    manifest    = _build_k8s_manifest(message, zeebe_vars, intent_id)
    target_tier = manifest["metadata"]["labels"]["tier"]
    image       = manifest["spec"]["containers"][0]["image"]
    data_type   = manifest["metadata"]["annotations"]["bpacc.io/data-type"]
    consent     = manifest["metadata"]["annotations"]["bpacc.io/consent"]

    log.info(
        f"[{intent_id[:8]}] adraft prêt — "
        f"image={image} tier={target_tier} "
        f"data_type={data_type} consent={consent}"
    )

    log.info(f"[{intent_id[:8]}] Soumission K8s (évaluation B3 en cours)...")
    admitted, k8s_message = _submit_to_kubernetes(manifest)

    if admitted:
        log.info(f"[{intent_id[:8]}] ✅ VERDICT B3 : ADMITTED. {k8s_message}")
    else:
        log.warning(f"[{intent_id[:8]}] ❌ VERDICT B3 : REJECTED. {k8s_message}")
        _publish_rejection(channel, cap_id, intent_id, k8s_message)

    channel.basic_ack(delivery_tag=method.delivery_tag)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="BPACC Smart Listener v2")
    parser.add_argument(
        "--queue",
        default="bpacc.queue.edge",
        choices=["bpacc.queue.endpoint", "bpacc.queue.edge", "bpacc.queue.cloud"],
    )
    args = parser.parse_args()

    _init_kubernetes()

    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters  = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
    )

    try:
        conn = pika.BlockingConnection(parameters)
    except Exception as e:
        log.error(f"Impossible de se connecter à RabbitMQ ({RABBITMQ_USER}@{RABBITMQ_HOST}): {e}")
        sys.exit(1)

    channel = conn.channel()
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=args.queue, on_message_callback=on_message)

    log.info(f"Smart Listener v2 opérationnel — écoute sur {args.queue}")
    log.info(f"  Zeebe REST           : {ZEEBE_REST_URL}")
    log.info(f"  K8s NS               : {K8S_NAMESPACE}")
    log.info(f"  process_instance_key : {PROCESS_INSTANCE_KEY or '(non défini — Zero-Trust)'}")

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        conn.close()
        log.info("Arrêt propre du Listener.")


if __name__ == "__main__":
    main()