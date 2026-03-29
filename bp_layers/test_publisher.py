"""
BPACC - B2 Simulator (Test Publisher)
Simule l'émission d'Intentions d'Exécution depuis le moteur BPMN vers RabbitMQ (B4).
"""

import pika
import json
import time
from datetime import datetime

# ── Configuration ────────────────────────────────────────────────────────────
RABBITMQ_HOST = "localhost"
RABBITMQ_USER = "bpacc"
RABBITMQ_PASS = "bpacc"
QUEUE_NAME    = "bpacc.queue.edge"

def publish_intent(channel, scenario_name, payload):
    print(f"\n[ÉMISSION B2] Scénario : {scenario_name}")
    channel.basic_publish(
        exchange="",
        routing_key=QUEUE_NAME,
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            delivery_mode=2,  # Message persistant
            content_type="application/json"
        )
    )
    print(f"  -> Message envoyé dans {QUEUE_NAME}")
    time.sleep(2) # Pause de 2 secondes pour laisser le temps au Listener de traiter et d'afficher

def main():
    # 1. Connexion sécurisée à RabbitMQ
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
    
    try:
        conn = pika.BlockingConnection(parameters)
    except Exception as e:
        print(f"[ERREUR] Impossible de se connecter à RabbitMQ : {e}")
        return
        
    channel = conn.channel()

    # ── Scénario 1 : NOMINAL ─────────────────────────────────────────────────
    # Tout est conforme : On traite de la biométrie en Europe AVEC le consentement
    scenario_1 = {
        "cap_id": "bpacc:VisitorQualification_Service", 
        "governance": {
            "region": "eu",
            "target_node": "EdgeNode"
        },
        "params": {
            "data_type": "biometric",
            "consent": "true",           # Consentement métier validé
            "rglobal_mock": "edge-only"  # Simule la politique globale de l'entreprise
        }
    }
    publish_intent(channel, "1. NOMINAL (Doit être ADMITTED par B3)", scenario_1)

    # ── Scénario 2 : VIOLATION RGPD (Consentement) ───────────────────────────
    # On traite de la biométrie SANS le consentement du visiteur
    scenario_2 = {
        "cap_id": "bpacc:VisitorQualification_Service",
        "governance": {
            "region": "eu",
            "target_node": "EdgeNode"
        },
        "params": {
            "data_type": "biometric",
            "consent": "false",  # Le visiteur a refusé, mais le process tente de déployer
            "rglobal_mock": "edge-only"
        }
    }
    publish_intent(channel, "2. VIOLATION CONSENTEMENT (Doit être DENIED par B3)", scenario_2)

    # ── Scénario 3 : VIOLATION SOUVERAINETÉ (Routage) ────────────────────────
    # On traite de la biométrie (avec consentement) mais on l'envoie sur un Cloud US
    scenario_3 = {
        "cap_id": "bpacc:VisitorQualification_Service",
        "governance": {
            "region": "us-east", # Tentative de routage hors UE
            "target_node": "CloudNode"
        },
        "params": {
            "data_type": "biometric",
            "consent": "true",
            "rglobal_mock": "edge-only"
        }
    }
    publish_intent(channel, "3. VIOLATION SOUVERAINETÉ (Doit être DENIED par B3)", scenario_3)

    # Fermeture propre
    conn.close()
    print("\nTests terminés. Vérifiez les logs dans le terminal du Smart Listener.")

if __name__ == "__main__":
    main()