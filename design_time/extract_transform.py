"""
BPACC - Étape 4 : Extract & Transform (µ1→µ5)
Tₙ → Camunda Element Templates (un connecteur par C ∈ Kₙ)

Usage : python step4_generate_connectors.py
Inputs : bpacc_tn.ttl + rabbitmq-outbound-connector-hybrid.json
Output : ./camunda-templates/bpacc-{service}.json
"""

import json, os, copy, rdflib
from datetime import datetime

TN_PATH       = "bpacc_tn.ttl"
TEMPLATE_PATH = "rabbitmq-outbound-connector-hybrid.json"
OUTPUT_DIR    = "./camunda-templates"

# Seules constantes légitimes : infrastructure RabbitMQ/Camunda (µ5)
EXCHANGE       = "bpacc.intent"
ROUTING_PREFIX = "bpacc.queue"  # + .endpoint / .edge / .cloud selon targetNode

SPARQL = """
PREFIX bpacc: <http://bpacc.bpacc.com/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>

SELECT DISTINCT ?cap ?latency ?locality ?region ?targetNode ?paramName ?paramType
WHERE {
    # Capabilities = sous-classes directes d'une super-classe de ContinuumService
    # ayant au moins une implémentation (rdfs:comment "implementations:...")
    ?cap a owl:Class ;
         rdfs:subClassOf ?parent ;
         rdfs:comment ?impl .
    ?parent rdfs:subClassOf* bpacc:ContinuumService .
    FILTER(STRSTARTS(?impl, "implementations:"))

    OPTIONAL {
        ?cap rdfs:subClassOf [ owl:onProperty bpacc:latencyProfile ; owl:hasValue ?latency ] }
    OPTIONAL {
        ?cap rdfs:subClassOf [ owl:onProperty bpacc:dataLocality   ; owl:hasValue ?locality ] }
    OPTIONAL {
        ?cap rdfs:subClassOf [ owl:onProperty bpacc:region         ; owl:hasValue ?region ] }
    OPTIONAL {
        ?cap rdfs:subClassOf [ owl:onProperty bpacc:targetNode     ; owl:someValuesFrom ?targetNode ] }
    OPTIONAL {
        ?cap rdfs:subClassOf [ owl:onProperty bpacc:hasInputParameter ; owl:hasValue ?param ] .
        ?param bpacc:paramName ?paramName .
        OPTIONAL { ?param bpacc:paramType ?paramType } }
}
"""

def extract(g):
    caps = {}
    for row in g.query(SPARQL):
        name = str(row.cap).split("#")[-1]
        if name not in caps:
            caps[name] = {"latency": None, "locality": None,
                          "region": "eu", "target": None, "inputs": []}
        c = caps[name]
        if row.latency:    c["latency"]  = str(row.latency)
        if row.locality:   c["locality"] = str(row.locality)
        if row.region:     c["region"]   = str(row.region)
        if row.targetNode: c["target"]   = str(row.targetNode).split("#")[-1]
        if row.paramName:
            entry = {"name": str(row.paramName),
                     "type": str(row.paramType).split("#")[-1] if row.paramType else "string"}
            if entry not in c["inputs"]:
                c["inputs"].append(entry)
    return caps

def build(name, cap, base):
    short       = name.replace("_Service", "")
    target      = cap["target"] or "EdgeNode"
    routing_key = f"{ROUTING_PREFIX}.{target.replace('Node','').lower()}"
    params_feel = ", ".join(f'"{p["name"]}": {p["name"]}' for p in cap["inputs"])
    payload = (
        f'= {{"cap_id": "bpacc:{name}", '
        f'"qos": {{"latency": governance_latency}}, '
        f'"governance": {{"region": governance_region, '
        f'"data_locality": "{cap["locality"]}", '
        f'"target_node": governance_target_node}}, '
        f'"params": {{{params_feel}}}}}'
    )

    t = copy.deepcopy(base)
    t["name"]    = f"BPACC | {short.replace('_', ' ')}"
    t["id"]      = f"io.bpacc.connectors.{short}.v1"
    t["version"] = 1
    t["engines"] = {"camunda": "^8.8"}
    t["groups"]  = [
        {"id": "authentication", "label": "Authentication"},
        {"id": "routing",        "label": "Routing"},
        {"id": "message",        "label": "Message"},
        {"id": "qos",            "label": "Quality of Service"},
        {"id": "governance",     "label": "Governance"},
        {"id": "params",         "label": "Capability Parameters"},
        {"id": "output",         "label": "Output mapping"},
        {"id": "error",          "label": "Error handling"},
        {"id": "retries",        "label": "Retries"},
    ]
    t["properties"] = [
        # µ5 — infrastructure fixe
        {"id": "taskDefinitionType", "value": "io.camunda:connector-rabbitmq:1",
         "binding": {"property": "type", "type": "zeebe:taskDefinition"}, "type": "String"},
        {"id": "authentication.authType", "value": "uri", "group": "authentication",
         "binding": {"name": "authentication.authType", "type": "zeebe:input"}, "type": "Hidden"},
        {"id": "authentication.uri", "label": "RabbitMQ URI", "value": "{{secrets.RABBITMQ_URI}}",
         "group": "authentication", "optional": False,
         "binding": {"name": "authentication.uri", "type": "zeebe:input"}, "type": "String"},
        {"id": "routing.exchange", "value": EXCHANGE, "group": "routing",
         "binding": {"name": "routing.exchange", "type": "zeebe:input"}, "type": "Hidden"},
        {"id": "routing.routingKey", "value": routing_key, "group": "routing",   # µ4
         "binding": {"name": "routing.routingKey", "type": "zeebe:input"}, "type": "Hidden"},
        # µ1+µ2+µ3+µ4 — payload c = ⟨ID, Qc, Pc, Ic⟩
        {"id": "message.body", "label": "Capability Profile Payload", "value": payload,
         "group": "message", "optional": False,
         "binding": {"name": "message.body", "type": "zeebe:input"}, "type": "Text"},
        # µ3 — Qc
        {"id": "governance_latency", "label": "Latency Profile",
         "value": cap["latency"] or "standard", "group": "qos",
         "binding": {"name": "governance_latency", "type": "zeebe:input"},
         "type": "Dropdown", "choices": [
             {"name": "Critical",    "value": "critical"},
             {"name": "Standard",    "value": "standard"},
             {"name": "Best-effort", "value": "best-effort"}]},
        # µ4 — Pc
        {"id": "governance_region", "label": "Region",
         "value": cap["region"], "group": "governance", "optional": True,
         "binding": {"name": "governance_region", "type": "zeebe:input"},
         "type": "Dropdown", "choices": [
             {"name": "EU (GDPR)", "value": "eu"},
             {"name": "US",        "value": "us"},
             {"name": "APAC",      "value": "apac"}]},
        {"id": "governance_target_node", "label": "Target Node",
         "value": target, "group": "governance", "optional": True,
         "binding": {"name": "governance_target_node", "type": "zeebe:input"},
         "type": "Dropdown", "choices": [
             {"name": "Endpoint", "value": "EndpointNode"},
             {"name": "Edge",     "value": "EdgeNode"},
             {"name": "Cloud",    "value": "CloudNode"}]},
        # µ2 — Ic
        *[{"id": p["name"], "label": p["name"].replace("_", " ").title(),
           "description": f"Type: {p['type']}", "optional": False, "group": "params",
           "binding": {"name": p["name"], "type": "zeebe:input"}, "type": "String"}
          for p in cap["inputs"]],
        # output / error / retries
        {"id": "resultExpression", "label": "Result expression", "group": "output",
         "value": "= {status: response.body.status, result: response.body.result}",
         "binding": {"key": "resultExpression", "type": "zeebe:taskHeader"}, "type": "String"},
        {"id": "errorExpression", "label": "Error expression", "group": "error",
         "binding": {"key": "errorExpression", "type": "zeebe:taskHeader"}, "type": "Text"},
        {"id": "retryCount", "label": "Retries", "value": "3", "group": "retries",
         "binding": {"property": "retries", "type": "zeebe:taskDefinition"}, "type": "String"},
    ]
    if "icon" in base:
        t["icon"] = base["icon"]
    return t

def main():
    g = rdflib.Graph()
    g.parse(TN_PATH, format="turtle")

    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        base = json.load(f)

    caps = extract(g)
    print(f"{len(caps)} capabilities extraites depuis Tₙ")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, cap in caps.items():
        connector = build(name, cap, base)
        slug = name.lower().replace("_service", "").replace("_", "-")
        path = os.path.join(OUTPUT_DIR, f"bpacc-{slug}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(connector, f, indent=2, ensure_ascii=False)
        print(f"  ✓ {path}  target={cap['target']}  inputs={[p['name'] for p in cap['inputs']]}")

if __name__ == "__main__":
    main()