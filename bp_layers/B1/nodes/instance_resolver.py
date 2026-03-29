"""
BPACC - B1 Node 5c : instance_resolver

Rôle formel : réalise s ∈ members(ID) au sens du papier BPACC.
Pour chaque tâche consolidée portant un cap_name abstrait, sélectionne
l'instance concrète optimale dans le catalogue raw en tenant compte
des governance_constraints extraites du user intent.

Position dans le graph :
  task_consolidator → instance_resolver → connector_loader

Le résultat enrichit consolidated_tasks avec les champs concrets :
  concrete_id, concrete_image, concrete_placement,
  concrete_governance, concrete_inputs, concrete_outputs

Le Smart Listener reçoit ensuite un cap_id résolu vers une instance
concrète connue — sa résolution devient déterministe et sans LLM.

Placement : bpacc/bp_layers/B1/nodes/instance_resolver.py
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.instance_resolver_prompt import (
    INSTANCE_RESOLVER_SYSTEM,
    INSTANCE_RESOLVER_PROMPT,
)

# ── Chemin du catalogue raw ───────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
RAW_CATALOG_PATH = (
    _PROJECT_ROOT
    / "bpacc"
    / "capability_profiles_builder"
    / "design_time"
    / "capability_catalog_raw.json"
)


def _load_raw_catalog() -> list[dict]:
    """Charge le catalogue raw. Retourne une liste vide si absent."""
    if not RAW_CATALOG_PATH.exists():
        return []
    with open(RAW_CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("services", [])


def _derive_abstract_class(service_id: str) -> str:
    """
    Dérive le nom de classe abstraite depuis le concrete id du catalogue raw.
    Convention : Robot_Behavior_Interaction → Robot_Service
                 TextToSpeech_NAOqi_Pepper  → TextToSpeech_Service
                 AudioRecording_NAOqi_Pepper → AudioRecording_Service

    Stratégie : prend le premier segment du id avant le deuxième '_',
    puis ajoute '_Service'.
    Ex : OCR_LLM_Mistral           → OCR_Service
         DataStructuring_LLM_Mistral → DataStructuring_Service
         VisitorQualification_LLM_Mistral → VisitorQualification_Service
         Robot_Behavior_Interaction → Robot_Service
    """
    parts = service_id.split("_")
    if len(parts) >= 2:
        # Cas composés connus : DataStructuring, VisitorQualification, etc.
        # On prend les segments jusqu'au premier segment qui ressemble à une implémentation
        # (LLM, NAOqi, Filter, Streamlit, Behavior, etc.)
        impl_markers = {"LLM", "NAOqi", "Filter", "Streamlit", "Behavior", "Whisper"}
        prefix_parts = []
        for part in parts:
            if part in impl_markers:
                break
            prefix_parts.append(part)
        if prefix_parts:
            return "_".join(prefix_parts) + "_Service"
    return parts[0] + "_Service"


def _build_members_index(raw_catalog: list[dict]) -> dict[str, list[dict]]:
    """
    Construit l'index members(ID) :
      abstract_class → [concrete_instance_1, concrete_instance_2, ...]

    Chaque entrée conserve toutes les métadonnées M(s) du catalogue raw
    plus le champ abstract_class dérivé.
    """
    index: dict[str, list[dict]] = {}
    for service in raw_catalog:
        abstract = _derive_abstract_class(service["id"])
        service_enriched = {**service, "abstract_class": abstract}
        index.setdefault(abstract, []).append(service_enriched)
    return index


def _filter_candidates(
    cap_name: str,
    members_index: dict[str, list[dict]],
    governance: dict,
) -> list[dict]:
    """
    Filtre les instances candidates pour cap_name selon les governance_constraints.
    Applique les règles de sélection du prompt dans l'ordre de priorité.
    Retourne toutes les instances compatibles triées par compatibilité décroissante.
    """
    candidates = members_index.get(cap_name, [])
    if not candidates:
        return []

    target_node   = governance.get("target_node", "EdgeNode")
    data_locality = governance.get("data_locality", "none")
    data_type     = governance.get("data_type", "personal")
    latency       = governance.get("latency", "standard")

    # Mapping target_node → tier requis
    tier_map = {
        "EndpointNode": "endpoint",
        "EdgeNode":     "edge",
        "CloudNode":    "cloud",
    }
    required_tier = tier_map.get(target_node, "edge")

    def score(s: dict) -> int:
        placement = s.get("placement", [])
        loc       = s.get("governance", {}).get("data_locality", "none")
        lat       = s.get("qos", {}).get("latency", "standard")
        score_val = 0

        # Règle 1 — placement
        if required_tier in placement:
            score_val += 4

        # Règle 2 — data locality
        locality_compat = {
            "edge-only":     {"edge-only"},
            "endpoint-only": {"endpoint-only"},
            "edge-preferred":{"edge-only", "edge-preferred"},
            "strict":        {"strict", "edge-only"},
            "none":          {"edge-only", "edge-preferred", "endpoint-only", "strict", "none"},
        }
        if loc in locality_compat.get(data_locality, set()):
            score_val += 3

        # Règle 3 — data type biométrique
        if data_type == "biometric" and loc in ("edge-only", "edge-preferred"):
            score_val += 2

        # Règle 4 — latence
        latency_compat = {
            "critical":   {"critical", "low", "50ms"},
            "low":        {"low", "50ms", "standard"},
            "standard":   {"standard", "low", "50ms", "best-effort"},
            "best-effort":{"best-effort", "standard", "low", "50ms"},
        }
        if lat in latency_compat.get(latency, set()):
            score_val += 1

        return score_val

    return sorted(candidates, key=score, reverse=True)


def instance_resolver(state: BPACCState) -> dict:
    consolidated_tasks     = state.get("consolidated_tasks", [])
    governance_constraints = state.get("governance_constraints", {})
    errors                 = list(state.get("errors", []))

    # ── Chargement du catalogue raw ───────────────────────────────────
    raw_catalog = _load_raw_catalog()
    if not raw_catalog:
        errors.append(
            f"instance_resolver: catalogue raw introuvable à {RAW_CATALOG_PATH} "
            f"— résolution d'instance impossible."
        )
        return {
            "errors":       errors,
            "status":       "failed",
            "current_node": "instance_resolver",
        }

    members_index = _build_members_index(raw_catalog)

    print(f"  [instance_resolver] catalogue raw : {len(raw_catalog)} services "
          f"→ {len(members_index)} classes abstraites")

    # ── Tentative de résolution déterministe (sans LLM) ──────────────
    # Si chaque cap_name a exactement une instance compatible,
    # on résout sans appel LLM pour économiser des tokens.
    resolved_deterministic: dict[str, dict] = {}
    needs_llm = False

    for task in consolidated_tasks:
        cap_name   = task.get("cap_name", "")
        candidates = _filter_candidates(cap_name, members_index, governance_constraints)

        if not candidates:
            print(f"  [instance_resolver] ✗ {cap_name} — aucune instance dans le raw")
            needs_llm = True
            break
        elif len(candidates) == 1:
            resolved_deterministic[task["label"]] = candidates[0]
        else:
            # Plusieurs candidats — on garde le meilleur scoré mais on logue
            best = candidates[0]
            resolved_deterministic[task["label"]] = best
            print(f"  [instance_resolver] {cap_name} — {len(candidates)} candidats, "
                  f"meilleur: {best['id']} (score déterministe)")

    # ── Appel LLM si résolution déterministe insuffisante ────────────
    # Le LLM intervient uniquement pour les cas ambigus ou manquants.
    if needs_llm:
        print(f"  [instance_resolver] résolution LLM activée pour les cas ambigus")

        # Sous-ensemble du catalogue raw pertinent pour les tâches
        relevant_caps = {t.get("cap_name", "") for t in consolidated_tasks}
        relevant_raw  = [
            s for s in raw_catalog
            if _derive_abstract_class(s["id"]) in relevant_caps
        ]

        llm    = reformulation_llm(system_prompt=INSTANCE_RESOLVER_SYSTEM)
        result = llm.invoke_for_json(INSTANCE_RESOLVER_PROMPT.format(
            governance_constraints = json.dumps(governance_constraints, indent=2, ensure_ascii=False),
            consolidated_tasks     = json.dumps(consolidated_tasks,     indent=2, ensure_ascii=False),
            raw_catalog            = json.dumps(relevant_raw,           indent=2, ensure_ascii=False),
        ))

        if result:
            for entry in result.get("resolved_instances", []):
                label = entry.get("task_label", "")
                if label:
                    resolved_deterministic[label] = {
                        "id":         entry.get("concrete_id", ""),
                        "image":      entry.get("concrete_image", ""),
                        "placement":  entry.get("concrete_placement", []),
                        "governance": entry.get("concrete_governance", {}),
                        "inputs":     entry.get("concrete_inputs", []),
                        "_rationale": entry.get("selection_rationale", ""),
                    }
        else:
            errors.append("instance_resolver: LLM returned invalid JSON — fallback déterministe conservé.")

    # ── Enrichissement des consolidated_tasks ────────────────────────
    enriched_tasks = []
    for task in consolidated_tasks:
        label    = task.get("label", "")
        instance = resolved_deterministic.get(label)

        if instance:
            enriched = {
                **task,
                "concrete_id":        instance.get("id", ""),
                "concrete_image":     instance.get("image", ""),
                "concrete_placement": instance.get("placement", []),
                "concrete_governance": instance.get("governance", {}),
                "concrete_inputs":    instance.get("inputs", []),
            }
            rationale = instance.get("_rationale", "")
            print(f"  [instance_resolver] ✓ {label:<45} → {instance.get('id', '?')}"
                  + (f" ({rationale})" if rationale else ""))
        else:
            # Pas d'instance trouvée — tâche conservée sans résolution
            enriched = {**task, "concrete_id": None, "concrete_image": None}
            errors.append(
                f"instance_resolver: aucune instance concrète trouvée pour "
                f"'{label}' (cap_name={task.get('cap_name', '?')})."
            )
            print(f"  [instance_resolver] ✗ {label:<45} → non résolu")

        enriched_tasks.append(enriched)

    resolved_count   = sum(1 for t in enriched_tasks if t.get("concrete_id"))
    unresolved_count = len(enriched_tasks) - resolved_count

    print(f"\n  [instance_resolver] {resolved_count}/{len(enriched_tasks)} tâches résolues "
          f"({unresolved_count} non résolues)")

    return {
        "consolidated_tasks": enriched_tasks,
        "errors":             errors,
        "status":             "running",
        "current_node":       "instance_resolver",
    }