"""
BPACC - B1 Business Intent Converter
State Definition (LangGraph 1.0)

GovernanceConstraints porte les contraintes extraites du user intent.
Ce sont les valeurs dynamiques qui instancient Qc au sens du papier :
  - region        : vocabulaire contrôlé issu de Tₙ → {"eu", "us", "apac"}
  - latency       : vocabulaire contrôlé issu du catalogue → {"critical", "standard", "best-effort", "low"}
  - target_node   : vocabulaire contrôlé Tₙ → {"EndpointNode", "EdgeNode", "CloudNode"}
  - data_type     : nature de la donnée traitée → {"biometric", "personal", "anonymous", "unknown"}
  - consent       : consentement explicite exprimé par l'utilisateur → {"true", "false"}
  - data_locality : contrainte de localisation exprimée → {"edge-only", "edge-preferred",
                    "endpoint-only", "strict", "none"} — vocabulaire catalogue raw
"""

from __future__ import annotations
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


# ── Vocabulaires contrôlés (issus de Tₙ et du catalogue raw) ────────────────
# Ces littéraux sont la source de vérité — aucune valeur libre n'est autorisée.

RegionLiteral      = Literal["eu", "us", "apac"]
LatencyLiteral     = Literal["critical", "standard", "best-effort", "low"]
TargetNodeLiteral  = Literal["EndpointNode", "EdgeNode", "CloudNode"]
DataTypeLiteral    = Literal["biometric", "personal", "anonymous", "unknown"]
ConsentLiteral     = Literal["true", "false"]
LocalityLiteral    = Literal["edge-only", "edge-preferred", "endpoint-only", "strict", "none"]


class GovernanceConstraints(TypedDict, total=False):
    """
    Contraintes de gouvernance extraites du user intent par intent_reformulator.
    Instancient Qc (SLOs) et complètent Pc (contraintes locales) au sens du papier.

    Séparation design-time / runtime :
      - data_locality est également encodé dans Pc (Tₙ, immuable par service).
        Ici il représente la contrainte exprimée par l'utilisateur —
        si elle est plus stricte que Pc, c'est la valeur utilisateur qui s'applique.
      - region, latency, target_node sont purement dynamiques (Σctx).
      - data_type et consent permettent d'activer les règles Rego R1/R2.
    """
    region:       RegionLiteral       # contrainte géographique RGPD
    latency:      LatencyLiteral      # profil de latence QoS
    target_node:  TargetNodeLiteral   # tier cible préférentiel
    data_type:    DataTypeLiteral     # nature des données traitées
    consent:      ConsentLiteral      # consentement explicite exprimé
    data_locality: LocalityLiteral    # contrainte de localisation des données


class TaskItem(TypedDict, total=False):
    label:        str
    description:  str
    task_type:    str        # "automated" | "human"
    dependencies: list[str]


class TaskMatch(TypedDict, total=False):
    label:      str
    cap_name:   str
    parent:     str
    target:     str
    latency:    str
    locality:   str
    region:     str
    inputs:     list
    impl:       str
    distance:   float
    matched:    bool


class EngineContext(TypedDict, total=False):
    engine:       str
    version:      str
    docs_snippet: str


class BPACCState(TypedDict, total=False):

    # ── Conversation ─────────────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Input ────────────────────────────────────────────────────────
    user_intent:   str
    uploaded_file: str
    input_type:    str   # "natural_language" | "bpmn_xml" | "both" | "structured_other"

    # ── Moteur d'exécution cible ─────────────────────────────────────
    engine_context: EngineContext

    # ── Node 2 : reformulation ───────────────────────────────────────
    user_story:             str
    governance_constraints: GovernanceConstraints   # ← NOUVEAU : extrait du user intent

    # ── Node 3 : estimation ──────────────────────────────────────────
    task_count:  int
    task_hints:  list[str]

    # ── Node 4 : décomposition incrémentale ──────────────────────────
    tasks:          list[TaskItem]
    task_iteration: int

    # ── Node 5 : retrieval ───────────────────────────────────────────
    task_matches:    list[TaskMatch]
    capability_gaps: list[str]

    # ── Node 5b : consolidation ──────────────────────────────────────
    consolidated_tasks:    list
    dropped_tasks:         list
    consolidation_summary: str

    # ── Node 6 : connector loader ────────────────────────────────────
    connectors: dict

    # ── Node 7 : génération BPMN (fragments LLM + assemblage Python) ─
    bpmn_parts:     list[str]
    generated_bpmn: str
    bpmn_iteration: int

    # ── Node 8/9 : validation & debug BPMN ───────────────────────────
    bpmn_valid:      bool
    bpmn_errors:     list[str]
    debug_iteration: int

    # ── Node 10 : persistance ────────────────────────────────────────
    bpmn_path:   str
    report_path: str

    # ── Node 11 : réponse ────────────────────────────────────────────
    response_summary: str

    # ── Node 12 : validation Business Analyst ────────────────────────
    validation_status: str   # "pending" | "approved" | "rejected"
    analyst_feedback:  str

    # ── Node 13 : gap handler ────────────────────────────────────────
    gap_notification_sent: bool

    # ── Node zeebe_deployer ──────────────────────────────────────────
    zeebe_deploy_status:             str   # "success" | "failed"
    zeebe_process_definition_key:    str
    zeebe_process_id:                str
    zeebe_version:                   str

    # ── Node zeebe_instance_launcher ─────────────────────────────────
    zeebe_instance_status:  str   # "success" | "failed"
    zeebe_instance_key:     str

    # ── Contrôle de flux ─────────────────────────────────────────────
    iteration:    int
    errors:       list[str]
    status:       str
    current_node: str