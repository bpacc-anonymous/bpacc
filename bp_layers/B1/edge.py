"""
BPACC - B1 Edges conditionnels (LangGraph 1.0)

Graph flow :
  format_detector
    → intent_reformulator | capability_retriever
  intent_reformulator
    → task_estimator
  task_estimator
    → task_decomposer
  task_decomposer
    → task_decomposer (boucle) | capability_retriever
  capability_retriever
    → task_consolidator
  task_consolidator
    → instance_resolver          ← NOUVEAU
  instance_resolver
    → connector_loader
  connector_loader
    → bpmn_generator
  bpmn_generator
    → bpmn_generator (boucle) | bpmn_validator
  bpmn_validator
    → persist_bpmn | bpmn_debugger
  bpmn_debugger
    → bpmn_validator
  persist_bpmn
    → response_generator
  response_generator
    → human_validator [INTERRUPT]
  human_validator
    → zeebe_deployer | gap_handler
  zeebe_deployer
    → zeebe_instance_launcher | END
"""

from __future__ import annotations
from langgraph.graph import END
from bpacc.bp_layers.B1.state import BPACCState

MAX_DEBUG_ITERATIONS = 3


def route_after_format_detector(state: BPACCState) -> str:
    input_type = state.get("input_type")
    if input_type in ("natural_language", "both"):
        return "intent_reformulator"
    if input_type == "bpmn_xml":
        return "capability_retriever"
    return END


def route_after_intent_reformulator(state: BPACCState) -> str:
    if state.get("status") == "failed":
        return END
    return "task_estimator"


def route_after_task_estimator(state: BPACCState) -> str:
    if state.get("status") == "failed":
        return END
    return "task_decomposer"


def route_after_task_decomposer(state: BPACCState) -> str:
    if state.get("status") == "failed":
        return END
    if state.get("task_iteration", 0) < state.get("task_count", 0):
        return "task_decomposer"
    return "capability_retriever"


def route_after_capability_retriever(state: BPACCState) -> str:
    return "task_consolidator"


def route_after_task_consolidator(state: BPACCState) -> str:
    if state.get("status") == "failed":
        return END
    return "instance_resolver"          # ← NOUVEAU : était "connector_loader"


def route_after_instance_resolver(state: BPACCState) -> str:
    """
    Si la résolution d'instance échoue complètement (aucune tâche résolue),
    on stoppe le graph — il n'y a rien à déployer.
    Sinon on continue même avec des résolutions partielles (les tâches non
    résolues seront signalées comme gaps dans response_generator).
    """
    if state.get("status") == "failed":
        return END
    consolidated = state.get("consolidated_tasks", [])
    resolved = [t for t in consolidated if t.get("concrete_id")]
    if not resolved:
        return END
    return "connector_loader"


def route_after_bpmn_generator(state: BPACCState) -> str:
    if state.get("status") == "failed":
        return END
    bpmn_iteration = state.get("bpmn_iteration", 0)
    task_count     = state.get("task_count", 0)
    if bpmn_iteration <= task_count:
        return "bpmn_generator"
    return "bpmn_validator"


def route_after_bpmn_validator(state: BPACCState) -> str:
    if state.get("bpmn_valid"):
        return "persist_bpmn"
    if state.get("debug_iteration", 0) < MAX_DEBUG_ITERATIONS:
        return "bpmn_debugger"
    return "persist_bpmn"


def route_after_human_validator(state: BPACCState) -> str:
    if state.get("validation_status") == "approved":
        return "zeebe_deployer"
    return "gap_handler"


def route_after_zeebe_deployer(state: BPACCState) -> str:
    if state.get("zeebe_deploy_status") == "success":
        return "zeebe_instance_launcher"
    return END