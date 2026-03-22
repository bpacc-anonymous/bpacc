"""
BPACC - B4 RabbitMQ Setup
Script one-shot : crée l'exchange, les queues et les bindings pour le Business Communication Bus.

Placement : racine du projet (même niveau que bpacc/)
Usage     : python rabbitmq_setup.py
Prérequis : pip install pika

Note : si un exchange existe déjà avec un type différent (ex: 'direct' au lieu de 'topic'),
       il est automatiquement supprimé puis recréé avec le bon type.
"""

import pika
import sys
import time

RABBITMQ_HOST = "localhost"
RABBITMQ_PORT = 5672
RABBITMQ_USER = "bpacc"
RABBITMQ_PASS = "bpacc"

EXCHANGE_NAME = "bpacc.intent"
EXCHANGE_TYPE = "topic"

QUEUES = {
    "bpacc.queue.endpoint": {
        "routing_key": "bpacc.queue.endpoint",
        "description": "Smart Listener — Pepper robot (NAOqi daemon)",
        "args": {
            "x-message-ttl": 30000,
            "x-dead-letter-exchange": "bpacc.dlx",
        },
    },
    "bpacc.queue.edge": {
        "routing_key": "bpacc.queue.edge",
        "description": "Smart Listener — Edge Kubernetes Operator (RKE2)",
        "args": {
            "x-message-ttl": 60000,
            "x-dead-letter-exchange": "bpacc.dlx",
        },
    },
    "bpacc.queue.cloud": {
        "routing_key": "bpacc.queue.cloud",
        "description": "Smart Listener — Cloud Kubernetes Operator (Harvester/Rancher)",
        "args": {
            "x-message-ttl": 120000,
            "x-dead-letter-exchange": "bpacc.dlx",
        },
    },
}

DLX_NAME = "bpacc.dlx"
DLQ_NAME = "bpacc.queue.rejected"


def connect(retries: int = 5) -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    for attempt in range(1, retries + 1):
        try:
            conn = pika.BlockingConnection(params)
            print(f"  ✓ Connecté à RabbitMQ {RABBITMQ_HOST}:{RABBITMQ_PORT} (user={RABBITMQ_USER})")
            return conn
        except Exception as e:
            print(f"  ✗ Tentative {attempt}/{retries} échouée : {e}")
            if attempt < retries:
                time.sleep(3)
    print("  ✗ Impossible de se connecter à RabbitMQ.")
    sys.exit(1)


def safe_exchange_declare(channel, exchange, exchange_type):
    """
    Tente de déclarer l'exchange. Si un conflit de type existe (406),
    supprime l'exchange existant et le recrée avec le bon type.
    Rouvre un channel frais après suppression car pika ferme le channel sur erreur 406.
    """
    try:
        channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)
        print(f"    ✓ exchange '{exchange}' ({exchange_type}, durable)")
        return channel
    except pika.exceptions.ChannelClosedByBroker as e:
        if e.args[0] == 406:
            print(f"    ⚠ exchange '{exchange}' existe avec un type différent — suppression...")
            # Le channel est fermé par le broker après 406 — rouvrir
            conn = channel.connection
            new_channel = conn.channel()
            new_channel.exchange_delete(exchange=exchange)
            print(f"    ✓ exchange '{exchange}' supprimé")
            new_channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)
            print(f"    ✓ exchange '{exchange}' recréé ({exchange_type}, durable)")
            return new_channel
        raise


def setup_topology(channel):
    # ── 1. Dead Letter Exchange ──────────────────────────────────────
    print(f"\n[1] Exchange DLX : {DLX_NAME}")
    channel = safe_exchange_declare(channel, DLX_NAME, "fanout")
    channel.queue_declare(queue=DLQ_NAME, durable=True)
    channel.queue_bind(queue=DLQ_NAME, exchange=DLX_NAME)
    print(f"    ✓ queue '{DLQ_NAME}' liée à '{DLX_NAME}'")

    # ── 2. Exchange principal ────────────────────────────────────────
    print(f"\n[2] Exchange principal : {EXCHANGE_NAME}")
    channel = safe_exchange_declare(channel, EXCHANGE_NAME, EXCHANGE_TYPE)

    # ── 3. Queues + bindings ─────────────────────────────────────────
    print(f"\n[3] Queues et bindings :")
    for queue_name, config in QUEUES.items():
        channel.queue_declare(queue=queue_name, durable=True, arguments=config["args"])
        channel.queue_bind(
            queue=queue_name,
            exchange=EXCHANGE_NAME,
            routing_key=config["routing_key"],
        )
        print(f"    ✓ '{queue_name}'  TTL={config['args']['x-message-ttl']}ms  — {config['description']}")

    print(f"\n  ✅ Topologie B4 créée avec succès.")
    return channel


def verify_topology(channel):
    print("\n[4] Vérification :")
    for queue_name in list(QUEUES.keys()) + [DLQ_NAME]:
        try:
            result = channel.queue_declare(queue=queue_name, passive=True)
            print(f"    ✓ '{queue_name}' — {result.method.message_count} message(s) en attente")
        except Exception as e:
            print(f"    ✗ '{queue_name}' — {e}")


def main():
    print("\n=== BPACC — B4 RabbitMQ Setup ===\n")
    conn = connect()
    ch = conn.channel()
    ch = setup_topology(ch)
    verify_topology(ch)
    ch.close()
    conn.close()
    print("\n  Connexion fermée proprement.")


if __name__ == "__main__":
    main()