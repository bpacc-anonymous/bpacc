"""
BPACC — Orchestrateur de Bout en Bout
Lance l'infrastructure d'écoute, génère le BPMN (B1), le déploie (B2),
lance l'instance, et observe la conformité (B3).

Flow :
  1. Démarrage du Smart Listener SANS key (Zero-Trust) sur edge + endpoint
  2. run_b1()    → B1 jusqu'à l'interrupt human_validator
  3. resume_b1() → zeebe_deployer → zeebe_instance_launcher
                 → zeebe_instance_key disponible dans final_state
  4. Redémarrage des Listeners AVEC PROCESS_INSTANCE_KEY injecté via env var
  5. Zeebe exécute le BPMN → connecteur RabbitMQ → Smart Listener
     → _fetch_zeebe_process_variables(key) → data_type + consent réels
     → OPA B3 évalue avec les vraies valeurs de gouvernance
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
import pika
from bpacc.bp_layers.B1.graph import run_b1, resume_b1

# ── Configuration ─────────────────────────────────────────────────────────────

processes: list[subprocess.Popen] = []
ZEEBE_REST_URL = os.environ.get("ZEEBE_REST_URL", "http://localhost:8088")
RABBITMQ_HOST  = os.environ.get("RABBITMQ_HOST",  "localhost")
RABBITMQ_USER  = os.environ.get("RABBITMQ_USER",  "bpacc")
RABBITMQ_PASS  = os.environ.get("RABBITMQ_PASS",  "bpacc")


# ── Smart Listeners ───────────────────────────────────────────────────────────

def _start_smart_listeners(process_instance_key: str = "") -> None:
    """
    Démarre les Smart Listeners sur edge + endpoint.

    Si process_instance_key est fourni, il est injecté via PROCESS_INSTANCE_KEY
    dans l'environnement du subprocess — le Listener pourra alors lire les
    variables de gouvernance depuis Zeebe REST pour chaque message traité.

    Si absent (premier démarrage avant lancement de l'instance Zeebe),
    les Listeners opèrent en mode Zero-Trust : data_type="unknown", consent="false".
    """
    # Arrêt des Listeners existants avant redémarrage
    for p in processes:
        p.terminate()
    processes.clear()

    env = os.environ.copy()
    if process_instance_key:
        env["PROCESS_INSTANCE_KEY"] = str(process_instance_key)
        print(f"  PROCESS_INSTANCE_KEY={process_instance_key} injecté dans les Listeners")
    else:
        env.pop("PROCESS_INSTANCE_KEY", None)

    for queue in ["bpacc.queue.edge", "bpacc.queue.endpoint"]:
        p = subprocess.Popen(
            [sys.executable, "-m", "bpacc.bp_layers.smart_listener", "--queue", queue],
            stdout=sys.stdout,
            stderr=sys.stderr,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        processes.append(p)
        print(f"  Smart Listener démarré sur {queue}")

    time.sleep(8)


# ── Monitor des verdicts B3 ───────────────────────────────────────────────────

def _start_rejection_monitor(stop_event: threading.Event) -> None:
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        conn = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
        )
        channel = conn.channel()

        def on_rejection(ch, method, properties, body):
            try:
                msg = json.loads(body)
                print(f"\n{'─'*60}")
                print(f"[B3 VERDICT] ❌  DENIED_BY_B3")
                print(f"  cap_id    : {msg.get('cap_id', '?')}")
                print(f"  intent_id : {msg.get('intent_id', '?')[:8]}")
                print(f"  reason    : {msg.get('reason', '?')}")
                print(f"  timestamp : {msg.get('timestamp', '?')}")
                print(f"{'─'*60}")
            except Exception as e:
                print(f"[B3 VERDICT] erreur parsing : {e}")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue="bpacc.queue.rejected", on_message_callback=on_rejection)
        print("[rejection_monitor] Écoute sur bpacc.queue.rejected...")

        while not stop_event.is_set():
            conn.process_data_events(time_limit=1)
        conn.close()

    except Exception as e:
        print(f"[rejection_monitor] erreur : {e}")


# ── Auto-completion des userTasks ─────────────────────────────────────────────

def _auto_complete_usertasks(process_instance_key: str, stop_event: threading.Event) -> None:
    print(f"[auto_complete] Démarrage sur instance {process_instance_key}")
    completed = set()

    while not stop_event.is_set():
        try:
            resp = httpx.post(
                f"{ZEEBE_REST_URL}/v2/user-tasks/search",
                json={"filter": {
                    "processInstanceKey": int(process_instance_key),
                    "state": "CREATED",
                }},
                timeout=5,
            )
            tasks = resp.json().get("items", [])
            for task in tasks:
                key  = task["userTaskKey"]
                name = task.get("name", task.get("elementId", "?"))
                if key in completed:
                    continue
                r = httpx.post(
                    f"{ZEEBE_REST_URL}/v2/user-tasks/{key}/completion",
                    json={},
                    timeout=5,
                )
                if r.status_code in (200, 204):
                    print(f"[auto_complete] ✓ userTask complétée : {name} ({key})")
                    completed.add(key)
                else:
                    print(f"[auto_complete] ✗ échec {name} ({key}) → HTTP {r.status_code}")
        except Exception as e:
            print(f"[auto_complete] erreur : {e}")

        stop_event.wait(timeout=2)

    print("[auto_complete] Arrêt.")


# ── Cleanup ───────────────────────────────────────────────────────────────────

def _cleanup(signum, frame) -> None:
    print("\nArrêt des processus en arrière-plan...")
    for p in processes:
        p.terminate()
    sys.exit(0)


signal.signal(signal.SIGINT, _cleanup)


# ── Orchestration principale ──────────────────────────────────────────────────

def main() -> None:
    # ── Phase 1 : Listeners sans key (Zero-Trust) ─────────────────────
    print("\n=== [1/3] Démarrage de l'Infrastructure BPACC ===")
    _start_smart_listeners(process_instance_key="")
    print("=== Infrastructure Prête (mode Zero-Trust) ===\n")

    user_intent = "I need to qualify visitors at a tech conference using a Pepper robot."
    thread_id   = "bpacc-e2e-demo-001"

    # ── Phase 2 : B1 jusqu'à l'interrupt human_validator ─────────────
    print("=== [2/3] Lancement de B1 (Business Intent Converter) ===")
    print(f"Requête : '{user_intent}'\n")

    initial_state = run_b1(
        user_intent=user_intent,
        engine="camunda",
        version="8.8",
        thread_id=thread_id,
    )

    print(f"\n[Orchestrateur] B1 en pause — interrupt human_validator atteint.")
    print(f"[Orchestrateur] Tâches : {[t.get('label') for t in initial_state.get('consolidated_tasks', [])]}")
    print(f"[Orchestrateur] Gaps   : {initial_state.get('capability_gaps', [])}")
    print(f"[Orchestrateur] BPMN valide : {initial_state.get('bpmn_valid')}")

    # ── Phase 3 : Approbation → déploiement → lancement instance ─────
    print("\n=== [3/3] Approbation et Déploiement ===")
    print("[Orchestrateur] Simulation validation Business Analyst → approved\n")

    final_state = resume_b1(
        validation_status="approved",
        feedback="",
        thread_id=thread_id,
    )

    process_instance_key = final_state.get("zeebe_instance_key", "")

    print(f"\n[Orchestrateur] Status final B1 : {final_state.get('status')}")
    print(f"[Orchestrateur] processInstanceKey : {process_instance_key}")

    if not process_instance_key:
        print("[Orchestrateur] ⚠ processInstanceKey absent — Listeners restent en mode Zero-Trust.")
    else:
        # ── Redémarrage des Listeners avec la key injectée ────────────
        print(f"\n[Orchestrateur] Redémarrage des Listeners avec PROCESS_INSTANCE_KEY={process_instance_key}")
        _start_smart_listeners(process_instance_key=process_instance_key)
        print("[Orchestrateur] Listeners opérationnels — data_type + consent lus depuis Zeebe.")

    print(
        "\n[Orchestrateur] Instance Zeebe lancée. "
        "Le moteur exécute le BPMN → connecteur RabbitMQ → Smart Listener → OPA B3."
    )
    print("Observez les logs ci-dessous (CTRL+C pour quitter)...\n")
    print("-" * 80)

    stop_event = threading.Event()

    if process_instance_key:
        threading.Thread(
            target=_auto_complete_usertasks,
            args=(process_instance_key, stop_event),
            daemon=True,
        ).start()
    else:
        print("[Orchestrateur] ⚠ auto-completion désactivée.")

    threading.Thread(
        target=_start_rejection_monitor,
        args=(stop_event,),
        daemon=True,
    ).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        _cleanup(None, None)


if __name__ == "__main__":
    main()