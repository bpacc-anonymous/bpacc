"""
BPACC - Étape 5 : GraphRAG Index sur Tₙ
Section III-B(B1) : construction de l'index sémantique pour ρ(n)

Inputs : bpacc_tn.ttl + capability_catalog_standardized.json
Output : ./chroma_db/ (collection persistante "bpacc_capabilities")

Query time :
  from step5_graphrag_index import retrieve
  results = retrieve("read the visitor badge", top_k=3)
"""

import os
import json
import rdflib
from sentence_transformers import SentenceTransformer
import chromadb

_BASE        = os.path.dirname(os.path.abspath(__file__))
TN_PATH      = os.path.join(_BASE, "bpacc_tn.ttl")
CATALOG_PATH = os.path.join(_BASE, "capability_catalog_standardized.json")
CHROMA_DIR   = os.path.join(_BASE, "chroma_db")
COLLECTION   = "bpacc_capabilities"
SBERT_MODEL  = "all-MiniLM-L6-v2"

# Singleton SBERT — chargé une seule fois
_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(SBERT_MODEL)
    return _model

SPARQL = """
PREFIX bpacc: <http://bpacc.bpacc.com/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>

SELECT DISTINCT ?cap ?parent ?latency ?locality ?region ?targetNode ?paramName ?impl
WHERE {
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
        ?param bpacc:paramName ?paramName . }
}
"""

def extract_tn(g):
    """Extrait le voisinage structurel (Qc, Pc, Ic) depuis Tₙ via SPARQL."""
    caps = {}
    for row in g.query(SPARQL):
        name = str(row.cap).split("#")[-1]
        if name not in caps:
            caps[name] = {
                "parent": None, "latency": None, "locality": None,
                "region": None, "target": None, "inputs": [], "impl": None,
            }
        c = caps[name]
        if row.parent:     c["parent"]  = str(row.parent).split("#")[-1]
        if row.latency:    c["latency"] = str(row.latency)
        if row.locality:   c["locality"]= str(row.locality)
        if row.region:     c["region"]  = str(row.region)
        if row.targetNode: c["target"]  = str(row.targetNode).split("#")[-1]
        if row.impl:       c["impl"]    = str(row.impl).replace("implementations:", "").strip()
        if row.paramName:
            p = str(row.paramName)
            if p not in c["inputs"]:
                c["inputs"].append(p)
    return caps


def extract_descriptions(catalog_path):
    """
    Extrait les descriptions fonctionnelles depuis le catalog JSON.
    Retourne un dict {abstract_class → description} en agrégeant
    les descriptions de toutes les implémentations de la classe.
    """
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    desc_map = {}
    for service in catalog["services"]:
        abstract = service.get("abstract_class")
        desc     = service.get("description", "")
        if abstract and desc:
            # Si plusieurs implémentations, on concatène
            if abstract in desc_map:
                desc_map[abstract] += " " + desc
            else:
                desc_map[abstract] = desc
    return desc_map


def build_node_context(name: str, cap: dict, description: str) -> str:
    """
    Assemble le node context en deux parties :
    1. Description fonctionnelle (depuis catalog) — porte la sémantique métier
    2. Métadonnées structurelles (depuis Tₙ) — parent, Qc, Pc, Ic
    Aucune valeur hardcodée — seuls les champs présents sont inclus.
    """
    parts = []

    # 1. Description fonctionnelle — source principale du matching sémantique
    if description:
        parts.append(description.strip())

    # 2. Identité et parent
    label = name.replace("_Service", "").replace("_", " ")
    line = f"{label} is a capability"
    if cap["parent"]:
        parent_label = cap["parent"].replace("Service", " service").lower()
        line += f" of type {parent_label}"
    parts.append(line + ".")

    # 3. Inputs (Ic)
    if cap["inputs"]:
        parts.append(f"Required inputs: {', '.join(cap['inputs'])}.")

    # 4. Placement (Pc)
    if cap["target"]:
        parts.append(f"Deployed on: {cap['target'].replace('Node', ' node').lower()}.")

    # 5. QoS (Qc)
    if cap["latency"]:
        parts.append(f"Latency profile: {cap['latency']}.")

    # 6. Gouvernance (Pc)
    gov = []
    if cap["locality"]: gov.append(f"data locality: {cap['locality']}")
    if cap["region"]:   gov.append(f"region: {cap['region']}")
    if gov:
        parts.append(f"Governance: {', '.join(gov)}.")

    # 7. Implémentations
    if cap["impl"]:
        parts.append(f"Implemented by: {cap['impl']}.")

    return " ".join(parts)


def build_index(tn_path: str = TN_PATH, catalog_path: str = CATALOG_PATH):
    """Construit l'index ChromaDB. Idempotent."""
    g = rdflib.Graph()
    g.parse(tn_path, format="turtle")
    print(f"  ✓ Tₙ chargé — {len(g)} triplets")

    caps      = extract_tn(g)
    desc_map  = extract_descriptions(catalog_path)
    model     = get_model()
    print(f"  ✓ {len(caps)} capabilities | SBERT : {SBERT_MODEL}")

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )

    ids, embeddings, documents, metadatas = [], [], [], []

    for name, cap in caps.items():
        description = desc_map.get(name, "")
        context     = build_node_context(name, cap, description)
        embedding   = model.encode(context).tolist()

        ids.append(name)
        embeddings.append(embedding)
        documents.append(context)
        metadatas.append({
            "cap_name": name,
            "parent":   cap["parent"]  or "",
            "latency":  cap["latency"] or "",
            "locality": cap["locality"]or "",
            "region":   cap["region"]  or "",
            "target":   cap["target"]  or "",
            "inputs":   json.dumps(cap["inputs"]),
            "impl":     cap["impl"]    or "",
            "context":  context,
        })
        print(f"  → {name}")
        print(f"     {context[:120]}...")

    collection.add(ids=ids, embeddings=embeddings,
                   documents=documents, metadatas=metadatas)
    print(f"\n  ✓ Index ChromaDB : {len(ids)} capabilities → {CHROMA_DIR}/")
    return collection


def retrieve(task_description: str, top_k: int = 3,
             tn_path: str = TN_PATH, catalog_path: str = CATALOG_PATH) -> list:
    """
    ρ(n) — retrieval sémantique pour une description de tâche.
    Retourne top_k capabilities avec métadonnées complètes + distance cosinus.
    """
    model  = get_model()
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        collection = client.get_collection(COLLECTION)
    except Exception:
        print("  Index introuvable — construction...")
        collection = build_index(tn_path, catalog_path)

    query_emb = model.encode(task_description).tolist()
    results   = collection.query(
        query_embeddings=[query_emb],
        n_results=top_k,
        include=["metadatas", "distances"]
    )

    output = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        output.append({
            **meta,
            "inputs":   json.loads(meta["inputs"]),
            "distance": round(results["distances"][0][i], 4),
        })
    return output


if __name__ == "__main__":
    print("\n=== BPACC — Étape 5 : GraphRAG Index sur Tₙ ===\n")
    build_index()

    print("\n─── Test retrieval ρ(n) ───")
    test_queries = [
        "read the visitor badge",
        "detect if someone is present",
        "qualify the visitor as a lead",
        "make the robot speak",
        "save visitor data to the CRM",
        "search for information about the visitor on the web",
    ]
    for query in test_queries:
        print(f"\n  Query : \"{query}\"")
        for r in retrieve(query, top_k=2):
            print(f"    → {r['cap_name']:<35} distance={r['distance']}  target={r['target']}  locality={r['locality']}")