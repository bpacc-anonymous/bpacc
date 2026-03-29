import pika
import json
from kubernetes import client, config
from kubernetes.client import V1Job, V1JobSpec, V1PodTemplateSpec
from kubernetes.client import V1ObjectMeta, V1PodSpec, V1Container

# Chargement config Kubernetes
config.load_kube_config()  # ou config.load_incluster_config()
batch_v1 = client.BatchV1Api()

def create_job_from_message(data):
    """
    Crée un Job Kubernetes à partir du message.
    Le message peut contenir :
      - name
      - image
      - command
      - namespace
    """
    job_name = data.get("name", "job-generated")
    image = data.get("image", "busybox")
    command = data.get("command", ["echo", "hello"])
    namespace = data.get("namespace", "default")

    job_manifest = V1Job(
        metadata=V1ObjectMeta(name=job_name),
        spec=V1JobSpec(
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"job": job_name}),
                spec=V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        V1Container(
                            name="main",
                            image=image,
                            command=command
                        )
                    ]
                )
            ),
            backoff_limit=3
        )
    )

    try:
        batch_v1.create_namespaced_job(namespace=namespace, body=job_manifest)
        print(f"Job {job_name} créé dans {namespace}")
    except Exception as e:
        print(f"Erreur création job: {e}")

def callback(ch, method, properties, body):
    message = body.decode()
    print(f"Message reçu: {message}")

    try:
        data = json.loads(message)
    except Exception:
        data = {"name": message.strip()}

    create_job_from_message(data)
    ch.basic_ack(delivery_tag=method.delivery_tag)

# Connexion RabbitMQ
connection = pika.BlockingConnection(
    pika.ConnectionParameters(host=os.environ.get('RABBITMQ_HOST', 'localhost'))
)
channel = connection.channel()

channel.queue_declare(queue='queue-edge', durable=True)
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='queue-edge', on_message_callback=callback)

print("En attente de messages...")
channel.start_consuming()