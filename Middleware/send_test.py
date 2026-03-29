import pika
import json

def send_message(message: dict):
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=os.environ.get('RABBITMQ_HOST', 'localhost'))
    )
    channel = connection.channel()

    channel.queue_declare(queue='queue-edge', durable=True)

    body = json.dumps(message)
    channel.basic_publish(
        exchange='bpacc.intent',
        routing_key='queue-edge',
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2  # message persistant
        )
    )

    print(f"Message envoyé: {body}")
    connection.close()

if __name__ == "__main__":
    msg = {
        "name": "job-test-001",
        "image": "busybox",
        "command": ["echo", "hello from rabbit"],
        "namespace": "default"
    }

    send_message(msg)