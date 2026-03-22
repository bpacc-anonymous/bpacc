"""
BPACC - Étape 2 : Standardisation — Version multi-groupers
Section III-B(2) du papier

Trois approches de groupement comparées :
  1. PrefixFallback  — dérivation depuis le préfixe fonctionnel de M(s).id
  2. BERTopic        — clustering sémantique sur descriptions (toutes partitions)
  3. LLMKimi         — Kimi K2 via NVIDIA API, appel unique sur tous les services

Outputs :
  - capability_catalog_standardized.json  : catalog opérationnel (grouper retenu = fallback)
  - capability_catalog_evaluation.json    : rapport overhead + justesse des 3 groupers
"""

import json
import os
import sys
import time
import re
from datetime import datetime
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── Dépendances optionnelles BERTopic ────────────────────────────────────────
try:
    from bertopic import BERTopic
    from sentence_transformers import SentenceTransformer
    from hdbscan import HDBSCAN
    BERTOPIC_AVAILABLE = True
except ImportError:
    BERTOPIC_AVAILABLE = False
    print("⚠️  BERTopic non installé — grouper BERTopic désactivé.\n")

# ── Constantes ────────────────────────────────────────────────────────────────

INPUT_PATH     = "capability_catalog_raw.json"
OUTPUT_CATALOG = "capability_catalog_standardized.json"
OUTPUT_EVAL    = "capability_catalog_evaluation.json"

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL       = "moonshotai/kimi-k2-instruct"

TYPE_TO_SUPERCLASS = {
    "sensing":     "Ss",
    "actuation":   "Sa",
    "processing":  "Sp",
    "storage":     "Sd",
    "interaction": "Si",
}

THETA_BT = 3

# Grouper retenu pour le catalog opérationnel
# Le fallback est le chemin principal (Section VII du papier)
OPERATIONAL_GROUPER = "fallback"


# ══════════════════════════════════════════════════════════════════════════════
# GROUPER 1 — PrefixFallback
# ══════════════════════════════════════════════════════════════════════════════

def derive_abstract_class_from_id(service_id: str) -> str:
    """
    Convention papier : FunctionalConcept_Implementation[_qualifier]
    Extrait le premier token avant '_' et suffixe '_Service'.
    """
    prefix = service_id.split("_")[0]
    return f"{prefix}_Service"


def grouper_fallback(services: list) -> tuple:
    """
    Groupe les services par préfixe fonctionnel de M(s).id.
    Retourne : (mapping {service_id → abstract_class}, latency_ms)
    """
    t = time.perf_counter()
    mapping = {s["id"]: derive_abstract_class_from_id(s["id"]) for s in services}
    latency_ms = round((time.perf_counter() - t) * 1000, 3)
    return mapping, latency_ms


# ══════════════════════════════════════════════════════════════════════════════
# GROUPER 2 — BERTopic
# ══════════════════════════════════════════════════════════════════════════════

def _bertopic_label_to_class(bertopic_name: str) -> str:
    parts = bertopic_name.split("_")[1:]
    if not parts:
        return "Unknown_Service"
    return f"{parts[0].capitalize()}_Service"


def grouper_bertopic(services: list) -> tuple:
    """
    Groupe les services via BERTopic sur toutes les partitions.
    Partitions trop petites ou clustering raté → fallback interne par service.
    Retourne : (mapping {service_id → abstract_class}, latency_ms, meta)
    """
    if not BERTOPIC_AVAILABLE:
        mapping, lat = grouper_fallback(services)
        return mapping, lat, {
            "status": "unavailable",
            "fallback_reason": "package_missing"
        }

    t_global = time.perf_counter()

    partitions: dict = defaultdict(list)
    for s in services:
        super_cls = TYPE_TO_SUPERCLASS.get(s["type"], "Unknown")
        partitions[super_cls].append(s)

    full_mapping   = {}
    partition_meta = {}

    for pname, part_services in partitions.items():
        n            = len(part_services)
        ids          = [s["id"]          for s in part_services]
        descriptions = [s["description"] for s in part_services]
        t_part       = time.perf_counter()

        if n < 2:
            for s in part_services:
                full_mapping[s["id"]] = derive_abstract_class_from_id(s["id"])
            partition_meta[pname] = {
                "n": n, "method": "fallback_size",
                "latency_ms": round((time.perf_counter() - t_part) * 1000, 2),
            }
            continue

        try:
            embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            embeddings      = embedding_model.encode(descriptions, show_progress_bar=False)

            hdbscan_model = HDBSCAN(
                min_cluster_size=2, min_samples=1, prediction_data=True
            )
            topic_model = BERTopic(
                hdbscan_model=hdbscan_model, min_topic_size=2, verbose=False
            )
            topics, _ = topic_model.fit_transform(descriptions, embeddings)

            non_noise = [t for t in topics if t != -1]
            if not non_noise:
                for s in part_services:
                    full_mapping[s["id"]] = derive_abstract_class_from_id(s["id"])
                partition_meta[pname] = {
                    "n": n, "method": "fallback_all_noise",
                    "latency_ms": round((time.perf_counter() - t_part) * 1000, 2),
                }
                continue

            topic_info  = topic_model.get_topic_info()
            topic_names = {
                row["Topic"]: _bertopic_label_to_class(row["Name"])
                for _, row in topic_info.iterrows()
                if row["Topic"] != -1
            }

            for sid, topic_id in zip(ids, topics):
                full_mapping[sid] = (
                    topic_names.get(topic_id, derive_abstract_class_from_id(sid))
                    if topic_id != -1
                    else derive_abstract_class_from_id(sid)
                )

            partition_meta[pname] = {
                "n": n,
                "method": "bertopic_success",
                "n_topics": len(set(t for t in topics if t != -1)),
                "latency_ms": round((time.perf_counter() - t_part) * 1000, 2),
            }

        except Exception as e:
            for s in part_services:
                full_mapping[s["id"]] = derive_abstract_class_from_id(s["id"])
            partition_meta[pname] = {
                "n": n,
                "method": f"fallback_exception",
                "error": str(e),
                "latency_ms": round((time.perf_counter() - t_part) * 1000, 2),
            }

    total_latency_ms = round((time.perf_counter() - t_global) * 1000, 2)
    return full_mapping, total_latency_ms, {
        "status": "ran", "partitions": partition_meta
    }


# ══════════════════════════════════════════════════════════════════════════════
# GROUPER 3 — LLM Kimi K2
# ══════════════════════════════════════════════════════════════════════════════

LLM_SYSTEM_PROMPT = """You are a semantic service classifier for a distributed computing continuum architecture.

You will receive a list of services, each with an id, type, and description.

Your task is to group them into abstract capability classes based on FUNCTIONAL EQUIVALENCE —
services that do the same thing regardless of their implementation technology or naming convention.

The services belong to exactly one of these five super-classes:
- Ss (sensing)     : services that capture data from the physical world (audio, video, sensors)
- Sa (actuation)   : services that act on the physical world (speech, motion, actuators)
- Sp (processing)  : services that transform, analyze, or enrich data (OCR, LLM, search, scoring)
- Sd (storage)     : services that persist or retrieve data (databases, file storage, CRM)
- Si (interaction) : services that interface with human users (UI, dashboards, forms)

Rules:
1. Group services by functional equivalence, NOT by implementation similarity
2. Two services doing the same thing with different tools must share the same abstract class
3. Abstract class names must be in PascalCase suffixed with _Service (e.g. OCR_Service)
4. Abstract class names must reflect the FUNCTION, not the technology
5. Each service belongs to exactly one abstract class

Respond ONLY with a valid JSON object. No explanation, no markdown, no backticks.
Format:
{
  "Ss": { "service_id": "AbstractClass_Service", ... },
  "Sa": { "service_id": "AbstractClass_Service", ... },
  "Sp": { "service_id": "AbstractClass_Service", ... },
  "Sd": { "service_id": "AbstractClass_Service", ... },
  "Si": { "service_id": "AbstractClass_Service", ... }
}"""


def _parse_llm_json(raw: str, services: list) -> dict | None:
    """
    Parsing robuste en 3 niveaux :
      1. json.loads direct
      2. extraction regex entre { ... }
      3. None si échec total
    """
    raw = raw.strip()

    # Niveau 1
    try:
        parsed = json.loads(raw)
        return _flatten_llm_output(parsed, services)
    except json.JSONDecodeError:
        pass

    # Niveau 2
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            return _flatten_llm_output(parsed, services)
        except json.JSONDecodeError:
            pass

    return None


def _flatten_llm_output(parsed: dict, services: list) -> dict:
    """
    Transforme la sortie LLM structurée par super-classe
    en mapping plat {service_id → abstract_class}.
    Fallback par service si absent de la réponse LLM.
    """
    flat = {}
    for super_cls, assignments in parsed.items():
        if isinstance(assignments, dict):
            for sid, abstract_class in assignments.items():
                flat[sid] = abstract_class

    # Garantie de complétude
    for s in services:
        if s["id"] not in flat:
            flat[s["id"]] = derive_abstract_class_from_id(s["id"])

    return flat


def grouper_llm(services: list) -> tuple:
    """
    Groupe tous les services en un seul appel Kimi K2.
    Retourne : (mapping {service_id → abstract_class}, latency_ms, meta)
    """
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("  ⚠️  NVIDIA_API_KEY manquant — LLM grouper désactivé.")
        mapping, lat = grouper_fallback(services)
        return mapping, lat, {
            "status": "unavailable", "fallback_reason": "no_api_key"
        }

    service_list = [
        {"id": s["id"], "type": s["type"], "description": s["description"]}
        for s in services
    ]

    client = OpenAI(api_key=api_key, base_url=NVIDIA_BASE_URL)

    t = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(
                    {"services": service_list}, indent=2, ensure_ascii=False
                )},
            ],
            temperature=0.2,
            max_tokens=1024,
            stream=False,
        )
        latency_ms = round((time.perf_counter() - t) * 1000, 2)
        raw        = response.choices[0].message.content

        mapping = _parse_llm_json(raw, services)
        if mapping is None:
            print(f"  ⚠️  LLM JSON parse failed — fallback activé.")
            print(f"  Réponse brute :\n{raw[:400]}")
            fb_mapping, _ = grouper_fallback(services)
            return fb_mapping, latency_ms, {
                "status": "parse_failed", "raw_response": raw[:500]
            }

        return mapping, latency_ms, {
            "status":        "success",
            "model":         LLM_MODEL,
            "input_tokens":  response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        }

    except Exception as e:
        latency_ms = round((time.perf_counter() - t) * 1000, 2)
        print(f"  ✗ LLM exception : {e}")
        fb_mapping, _ = grouper_fallback(services)
        return fb_mapping, latency_ms, {"status": f"exception: {e}"}


# ══════════════════════════════════════════════════════════════════════════════
# COMPARAISON DE JUSTESSE
# ══════════════════════════════════════════════════════════════════════════════

def compare_groupers(
    mapping_a: dict, mapping_b: dict, name_a: str, name_b: str
) -> dict:
    """
    Compare deux mappings service_id → abstract_class.
    Retourne taux d'accord et détail des divergences.
    """
    all_ids  = set(mapping_a.keys()) | set(mapping_b.keys())
    matching  = 0
    diverging = []

    for sid in sorted(all_ids):
        cls_a = mapping_a.get(sid, "—")
        cls_b = mapping_b.get(sid, "—")
        if cls_a == cls_b:
            matching += 1
        else:
            diverging.append({
                "service": sid,
                name_a:    cls_a,
                name_b:    cls_b,
            })

    total = len(all_ids)
    return {
        "total":             total,
        "matching":          matching,
        "diverging":         len(diverging),
        "agreement_rate":    round(matching / total, 3) if total > 0 else None,
        "diverging_details": diverging,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BUILD OUTPUTS
# ══════════════════════════════════════════════════════════════════════════════

def build_outputs(raw_catalog: dict) -> tuple:
    services = raw_catalog["services"]

    print("\n─── Grouper 1 : PrefixFallback ───")
    fb_mapping, fb_latency = grouper_fallback(services)
    print(f"  ✓ {len(set(fb_mapping.values()))} classes  |  {fb_latency:.3f} ms")

    print("\n─── Grouper 2 : BERTopic ───")
    bt_mapping, bt_latency, bt_meta = grouper_bertopic(services)
    print(f"  ✓ {len(set(bt_mapping.values()))} classes  |  {bt_latency:.1f} ms")
    for pname, pmeta in bt_meta.get("partitions", {}).items():
        print(f"    [{pname}] {pmeta['method']}  {pmeta['latency_ms']} ms")

    print("\n─── Grouper 3 : LLM Kimi K2 ───")
    llm_mapping, llm_latency, llm_meta = grouper_llm(services)
    print(f"  ✓ {len(set(llm_mapping.values()))} classes  |  {llm_latency:.1f} ms")
    print(f"    status={llm_meta.get('status')}  "
          f"tokens={llm_meta.get('input_tokens','?')}+"
          f"{llm_meta.get('output_tokens','?')}")

    # ── Catalog opérationnel (grouper retenu = fallback) ─────────────────────
    enriched_services        = []
    abstract_classes_summary = defaultdict(list)

    for s in services:
        super_cls      = TYPE_TO_SUPERCLASS.get(s["type"], "Unknown")
        abstract_class = fb_mapping.get(s["id"], derive_abstract_class_from_id(s["id"]))
        enriched_services.append({
            **s,
            "abstract_class":         abstract_class,
            "super_class":            super_cls,
            "standardization_method": OPERATIONAL_GROUPER,
        })
        abstract_classes_summary[abstract_class].append(s["id"])

    catalog = {
        "meta": {
            **raw_catalog["meta"],
            "standardized_at":        datetime.utcnow().isoformat() + "Z",
            "theta_bt":               THETA_BT,
            "operational_grouper":    OPERATIONAL_GROUPER,
            "total_abstract_classes": len(abstract_classes_summary),
        },
        "abstract_classes": dict(abstract_classes_summary),
        "services":         enriched_services,
    }

    # ── Comparaisons ─────────────────────────────────────────────────────────
    comp_fb_bt  = compare_groupers(fb_mapping, bt_mapping,  "fallback", "bertopic")
    comp_fb_llm = compare_groupers(fb_mapping, llm_mapping, "fallback", "llm_kimi")
    comp_bt_llm = compare_groupers(bt_mapping, llm_mapping, "bertopic", "llm_kimi")

    # ── Rapport d'évaluation ─────────────────────────────────────────────────
    evaluation = {
        "meta": {
            "evaluated_at":       datetime.utcnow().isoformat() + "Z",
            "theta_bt":           THETA_BT,
            "bertopic_available": BERTOPIC_AVAILABLE,
            "llm_model":          LLM_MODEL,
        },
        "groupers": {
            "fallback": {
                "latency_ms": fb_latency,
                "n_classes":  len(set(fb_mapping.values())),
                "classes":    fb_mapping,
            },
            "bertopic": {
                "latency_ms": bt_latency,
                "n_classes":  len(set(bt_mapping.values())),
                "classes":    bt_mapping,
                "meta":       bt_meta,
            },
            "llm_kimi": {
                "latency_ms": llm_latency,
                "n_classes":  len(set(llm_mapping.values())),
                "classes":    llm_mapping,
                "meta":       llm_meta,
            },
        },
        "comparison": {
            "fallback_vs_bertopic": comp_fb_bt,
            "fallback_vs_llm_kimi": comp_fb_llm,
            "bertopic_vs_llm_kimi": comp_bt_llm,
        },
        # Résumé plat — directement transformable en DataFrame pandas
        # pd.DataFrame(evaluation["dataframe_rows"])
        "dataframe_rows": [
            {
                "comparison":       "fallback_vs_bertopic",
                "grouper_a":        "fallback",
                "grouper_b":        "bertopic",
                "total":            comp_fb_bt["total"],
                "matching":         comp_fb_bt["matching"],
                "diverging":        comp_fb_bt["diverging"],
                "agreement_rate":   comp_fb_bt["agreement_rate"],
                "latency_a_ms":     fb_latency,
                "latency_b_ms":     bt_latency,
                "speedup_a_over_b": round(bt_latency / fb_latency, 1)
                                    if fb_latency > 0 else None,
            },
            {
                "comparison":       "fallback_vs_llm_kimi",
                "grouper_a":        "fallback",
                "grouper_b":        "llm_kimi",
                "total":            comp_fb_llm["total"],
                "matching":         comp_fb_llm["matching"],
                "diverging":        comp_fb_llm["diverging"],
                "agreement_rate":   comp_fb_llm["agreement_rate"],
                "latency_a_ms":     fb_latency,
                "latency_b_ms":     llm_latency,
                "speedup_a_over_b": round(llm_latency / fb_latency, 1)
                                    if fb_latency > 0 else None,
            },
            {
                "comparison":       "bertopic_vs_llm_kimi",
                "grouper_a":        "bertopic",
                "grouper_b":        "llm_kimi",
                "total":            comp_bt_llm["total"],
                "matching":         comp_bt_llm["matching"],
                "diverging":        comp_bt_llm["diverging"],
                "agreement_rate":   comp_bt_llm["agreement_rate"],
                "latency_a_ms":     bt_latency,
                "latency_b_ms":     llm_latency,
                "speedup_a_over_b": round(llm_latency / bt_latency, 1)
                                    if bt_latency > 0 else None,
            },
        ],
    }

    return catalog, evaluation


# ── Validation ────────────────────────────────────────────────────────────────

EXPECTED_ABSTRACT_CLASSES = {
    "OCR_Service", "DataStructuring_Service", "VisitorQualification_Service",
    "WebSearch_Service", "SalesNotification_Service", "ObjectDetection_Service",
    "AudioRecording_Service", "VideoCapture_Service", "LLMText_Service",
    "TextToSpeech_Service", "CRM_Service", "VisitorInteraction_Service",
    "Robot_Service",
}


def validate_catalog(catalog: dict) -> bool:
    produced = set(catalog["abstract_classes"].keys())
    missing  = EXPECTED_ABSTRACT_CLASSES - produced
    extra    = produced - EXPECTED_ABSTRACT_CLASSES
    matching = produced & EXPECTED_ABSTRACT_CLASSES
    print("\n=== Validation catalog (fallback) ===")
    print(f"  ✓ {len(matching)}/13 classes attendues présentes")
    if missing:
        print(f"  ✗ Manquantes : {sorted(missing)}")
    if extra:
        print(f"  ⚠️  Supplémentaires : {sorted(extra)}")
    success = len(missing) == 0
    print(f"  Résultat : {'✅ PASS' if success else '❌ FAIL'}")
    return success


def print_evaluation_summary(evaluation: dict) -> None:
    print("\n=== Rapport d'évaluation — 3 groupers ===")
    g = evaluation["groupers"]
    print(f"\n  {'Grouper':<15} {'Classes':>8} {'Latence':>14}")
    print(f"  {'─'*15} {'─'*8} {'─'*14}")
    for name, data in g.items():
        print(f"  {name:<15} {data['n_classes']:>8} {data['latency_ms']:>12.1f} ms")

    print(f"\n  {'Comparaison':<25} {'Accord':>8} {'Divergences':>12}")
    print(f"  {'─'*25} {'─'*8} {'─'*12}")
    for row in evaluation["dataframe_rows"]:
        rate = row["agreement_rate"]
        print(f"  {row['comparison']:<25} "
              f"{rate*100:>7.1f}% "
              f"{row['diverging']:>12}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n=== BPACC — Standardisation M(s) (Étape 2) — 3 groupers ===\n")

    try:
        with open(INPUT_PATH, encoding="utf-8") as f:
            raw_catalog = json.load(f)
    except FileNotFoundError:
        print(f"✗ Fichier introuvable : {INPUT_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"  {raw_catalog['meta']['total_services']} services chargés depuis {INPUT_PATH}")

    catalog, evaluation = build_outputs(raw_catalog)

    with open(OUTPUT_CATALOG, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Catalog standardisé   → {OUTPUT_CATALOG}")

    with open(OUTPUT_EVAL, "w", encoding="utf-8") as f:
        json.dump(evaluation, f, indent=2, ensure_ascii=False)
    print(f"✅ Rapport d'évaluation  → {OUTPUT_EVAL}")

    validate_catalog(catalog)
    print_evaluation_summary(evaluation)

    print("\n  💡 DataFrame :")
    print("     import pandas as pd, json")
    print(f"     df = pd.DataFrame(json.load(open('{OUTPUT_EVAL}'))['dataframe_rows'])")


if __name__ == "__main__":
    main()