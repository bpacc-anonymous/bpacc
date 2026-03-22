"""
BPACC - B1 Business Intent Converter
State Definition (LangGraph 1.0)
"""

from __future__ import annotations
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


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
    user_story: str

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