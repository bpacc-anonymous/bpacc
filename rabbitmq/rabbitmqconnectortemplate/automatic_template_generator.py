import json
import os
import copy
import rdflib

def generate_connectors_hybrid(ttl_file, generic_template_file, output_dir):
    """
    Génère les connecteurs BPACC en mutant le template générique RabbitMQ 
    à partir des définitions de l'ontologie.
    """
    # 1. Chargement du modèle sémantique (TTL)
    g = rdflib.Graph()
    g.parse(ttl_file, format="turtle")
    
    # 2. Chargement du socle générique (JSON)
    with open(generic_template_file, 'r', encoding='utf-8') as f:
        base_template = json.load(f)

    # Requêtes SPARQL
    query_capabilities = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX bpacc: <http://anonymous.org/research/bpacc#>

    SELECT ?cap ?label ?desc ?target
    WHERE {
        ?cap rdfs:subClassOf* bpacc:BusinessCapability .
        ?cap rdfs:label ?label .
        ?cap rdfs:comment ?desc .
        ?cap bpacc:targetNode ?target .
    }
    """
    
    query_params = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX bpacc: <http://anonymous.org/research/bpacc#>

    SELECT ?paramName ?paramLabel ?paramType
    WHERE {
        ?capClass rdfs:subClassOf* bpacc:BusinessCapability .
        ?targetCap rdfs:subClassOf* ?capClass .
        ?capClass bpacc:hasInputParameter ?paramNode .
        ?paramNode bpacc:paramName ?paramName ;
                   bpacc:paramLabel ?paramLabel ;
                   bpacc:paramType ?paramType .
    }
    """

    capabilities = g.query(query_capabilities)
    os.makedirs(output_dir, exist_ok=True)

    # Propriétés statiques BPACC à injecter dans chaque connecteur
    bpacc_custom_properties = [
        {
            "id": "constraints.region",
            "label": "Data Region",
            "description": "Geographic region constraint for data sovereignty",
            "value": "eu",
            "group": "constraints",
            "binding": {"name": "constraints.region", "type": "zeebe:input"},
            "type": "Dropdown",
            "choices": [
                {"name": "European Union (GDPR)", "value": "eu"},
                {"name": "United States", "value": "us"},
                {"name": "Asia-Pacific", "value": "apac"}
            ]
        },
        {
            "id": "constraints.latency",
            "label": "Latency Profile",
            "description": "Required latency tier for this capability",
            "value": "standard",
            "group": "constraints",
            "binding": {"name": "constraints.latency", "type": "zeebe:input"},
            "type": "Dropdown",
            "choices": [
                {"name": "Critical (< 20ms)", "value": "critical"},
                {"name": "Standard (< 500ms)", "value": "standard"},
                {"name": "Best-effort (> 500ms)", "value": "best-effort"}
            ]
        }
    ]

    for row in capabilities:
        cap_uri = row.cap
        label = str(row.label)
        desc = str(row.desc)
        target = row.target.split("#")[-1]
        
        cap_short_name = cap_uri.split("#")[-1].replace("_Service", "")
        connector_id = f"io.bpacc.connectors.{cap_short_name}.v1"
        routing_key = "queue-edge" if target == "EdgeGateway" else "queue-cloud"
        
        # Extraction des paramètres
        params_result = g.query(query_params, initBindings={'targetCap': cap_uri})
        param_keys = []
        param_descriptions = []
        for p in params_result:
            p_name = str(p.paramName)
            param_keys.append(p_name)
            param_descriptions.append(f"- {p.paramLabel} ({p_name}): {str(p.paramType).split('#')[-1]}")

        # Formulation du Payload
        params_json_str = ", ".join([f'"{k}": ""' for k in param_keys])
        domain = "service" # Valeur par défaut, à affiner via SPARQL si besoin selon le sous-domaine
        cap_id_internal = f"cap:{domain}.{cap_short_name.lower()}"
        feel_payload = f'= {{"cap_id": "{cap_id_internal}", "constraints": {{"region": constraints.region, "latency": constraints.latency}}, "params": {{{params_json_str}}}}}'
        payload_desc = "Parameters:\n" + "\n".join(param_descriptions) if param_descriptions else ""

        # 3. Clonage du modèle de base
        new_template = copy.deepcopy(base_template)
        
        # Surcharge des métadonnées globales
        new_template["name"] = f"BPACC | {label}"
        new_template["id"] = connector_id
        new_template["description"] = desc
        new_template["version"] = 1 # Force version 1 pour les connecteurs BPACC
        
        # Ajout du groupe 'constraints' s'il n'existe pas
        if not any(g.get("id") == "constraints" for g in new_template["groups"]):
            # Insertion juste avant "connector" pour respecter la hiérarchie visuelle
            idx = next((i for i, g in enumerate(new_template["groups"]) if g["id"] == "connector"), len(new_template["groups"]))
            new_template["groups"].insert(idx, {"id": "constraints", "label": "Constraints"})
            
        # Modification du libellé du groupe message pour correspondre aux JSON cibles
        for g_dict in new_template["groups"]:
            if g_dict["id"] == "message":
                g_dict["label"] = "Capability Parameters"

        # 4. Surcharge des propriétés
        mutated_properties = []
        for prop in new_template["properties"]:
            pid = prop.get("id")
            
            # Forcer authType à "uri" et le cacher (retrait des choix conditionnels)
            if pid == "authentication.authType":
                prop["type"] = "Hidden"
                prop["value"] = "uri"
                prop.pop("choices", None)
                prop.pop("label", None)
            
            # Surcharge de l'URI RabbitMQ
            elif pid == "authentication.uri":
                prop["value"] = "secrets.RABBITMQ_URI"
                prop["optional"] = False
                prop.pop("condition", None)
                
            # Suppression des propriétés d'auth par credentials (inutiles dans BPACC)
            elif pid in ["authentication.userName", "authentication.password", "routing.virtualHost", "routing.hostName", "routing.port"]:
                continue # N'est pas ajouté à la liste finale
                
            # Masquage et forçage de l'exchange
            elif pid == "routing.exchange":
                prop["type"] = "Hidden"
                prop["value"] = "bpacc.intent"
                prop.pop("label", None)
                prop.pop("description", None)
                prop.pop("constraints", None)
                
            # Masquage et forçage de la routing key selon TBox
            elif pid == "routing.routingKey":
                prop["type"] = "Hidden"
                prop["value"] = routing_key
                prop.pop("label", None)
                prop.pop("description", None)
                prop.pop("constraints", None)
                
            # Surcharge dynamique du payload
            elif pid == "message.body":
                prop["value"] = feel_payload
                prop["description"] = payload_desc
                prop["label"] = "Capability Parameters"
                
            # Surcharge des IDs et Versions du connecteur Zeebe natif
            elif pid == "id":
                prop["value"] = connector_id
            elif pid == "version":
                prop["value"] = "1"
            
            # Surcharge du resultExpression pour s'aligner sur BPACC
            elif pid == "resultExpression":
                prop["value"] = '= {status: response.body.status, result: response.body.result}'
                
            mutated_properties.append(prop)

        # Ajout des nouvelles propriétés BPACC
        mutated_properties.extend(bpacc_custom_properties)
        
        # Remplacement de la liste des propriétés
        new_template["properties"] = mutated_properties

        # 5. Écriture sur disque
        file_path = os.path.join(output_dir, f"bpacc-{cap_short_name.lower()}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(new_template, f, indent=2, ensure_ascii=False)
            
        print(f"[SUCCESS] Généré: {file_path} via surcharge dynamique.")

if __name__ == "__main__":
    generate_connectors_hybrid(
        ttl_file="bpacc_V3.ttl", 
        generic_template_file="rabbitmq-outbound-connector-hybrid.json", 
        output_dir="./camunda-templates"
    )