"""
BPACC - Étape 1 : Extraction des M(s) depuis les labels Docker Hub via skopeo
Produit : capability_catalog_raw.json

M(s) = <id, type, inputs, outputs, placement, qos, governance, Res(s)>
"""

import subprocess
import json
import sys
from datetime import datetime

DOCKER_USER = "anonymous-bpacc"

IMAGES = [
    "bpacc-ocr",
    "bpacc-data-structuring",
    "bpacc-qualification",
    "bpacc-web-search",
    "bpacc-notification",
    "bpacc-object-detection",
    "bpacc-audio-recording",
    "bpacc-video-capture",
    "bpacc-llm-text",
    "bpacc-tts",
    "bpacc-crm-storage",
    "bpacc-streamlit-ui",
    "bpacc-robot-actuation",
]

BPACC_PREFIX = "io.bpacc."


def extract_labels(image_ref: str) -> dict:
    """Appelle skopeo inspect et retourne les labels bruts."""
    cmd = ["skopeo", "inspect", f"docker://{image_ref}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"skopeo inspect failed for {image_ref}:\n{result.stderr.strip()}"
        )
    data = json.loads(result.stdout)
    return data.get("Labels", {})


def parse_bpacc_labels(labels: dict, image_name: str) -> dict:
    """
    Transforme les labels io.bpacc.* en M(s) structuré.

    M(s) = <id, type, inputs, outputs, placement, qos, governance, Res(s)>

    - inputs/outputs  : liste (split sur virgule)
    - placement       : liste de tiers (endpoint | edge | cloud)
    - qos             : dict des métriques QoS (latency, etc.)
    - governance      : dict des contraintes de gouvernance (data_locality, etc.)
    - Res(s)          : champ réservé — non encodé dans les labels actuels,
                        initialisé à null pour extension future
    """
    bpacc = {k[len(BPACC_PREFIX):]: v
             for k, v in labels.items()
             if k.startswith(BPACC_PREFIX)}

    # Champs scalaires
    service_id   = bpacc.get("id", image_name)
    service_type = bpacc.get("type", "unknown")
    description  = bpacc.get("description", "")
    version      = bpacc.get("version", "1")

    # Listes
    inputs  = [i.strip() for i in bpacc.get("inputs", "").split(",") if i.strip()]
    outputs = [o.strip() for o in bpacc.get("outputs", "").split(",") if o.strip()]
    placement = [p.strip() for p in bpacc.get("placement", "").split(",") if p.strip()]

    # QoS : tous les sous-champs io.bpacc.qos.*
    qos = {k[len("qos."):]: v
           for k, v in bpacc.items()
           if k.startswith("qos.")}

    # Governance : tous les sous-champs io.bpacc.governance.*
    governance = {k[len("governance."):]: v
                  for k, v in bpacc.items()
                  if k.startswith("governance.")}

    # Res(s) : non encore encodé dans les labels — réservé pour extension
    res = None

    return {
        "image": image_name,
        "id": service_id,
        "type": service_type,
        "description": description,
        "version": version,
        "inputs": inputs,
        "outputs": outputs,
        "placement": placement,
        "qos": qos,
        "governance": governance,
        "Res": res,
    }


def build_catalog(docker_user: str, images: list) -> dict:
    """Itère sur les images et construit le catalog M(s) complet."""
    services = []
    errors = []

    for img in images:
        image_ref = f"docker.io/{docker_user}/{img}:latest"
        print(f"  → Extraction : {image_ref}")
        try:
            labels = extract_labels(image_ref)
            ms = parse_bpacc_labels(labels, img)
            services.append(ms)
            print(f"    ✓ {ms['id']} [{ms['type']}] — placement: {ms['placement']}")
        except Exception as e:
            print(f"    ✗ ERREUR : {e}", file=sys.stderr)
            errors.append({"image": img, "error": str(e)})

    return {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "docker_user": docker_user,
            "total_services": len(services),
            "errors": errors,
        },
        "services": services,
    }


def main():
    print("\n=== BPACC — Extraction M(s) (Étape 1) ===\n")
    catalog = build_catalog(DOCKER_USER, IMAGES)

    output_path = "capability_catalog_raw.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Catalog écrit dans : {output_path}")
    print(f"   {catalog['meta']['total_services']} services extraits")
    if catalog["meta"]["errors"]:
        print(f"   ⚠️  {len(catalog['meta']['errors'])} erreur(s) : "
              f"{[e['image'] for e in catalog['meta']['errors']]}")


if __name__ == "__main__":
    main()