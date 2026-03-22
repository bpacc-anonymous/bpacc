"""
BPACC - B1 Edges conditionnels (LangGraph 1.0)
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
    if state.get("status") == "failed": return END
    return "task_estimator"


def route_after_task_estimator(state: BPACCState) -> str:
    if state.get("status") == "failed": return END
    return "task_decomposer"


def route_after_task_decomposer(state: BPACCState) -> str:
    if state.get("status") == "failed": return END
    if state.get("task_iteration", 0) < state.get("task_count", 0):
        return "task_decomposer"
    return "capability_retriever"


def route_after_capability_retriever(state: BPACCState) -> str:
    return "task_consolidator"


def route_after_task_consolidator(state: BPACCState) -> str:
    if state.get("status") == "failed": return END
    return "connector_loader"


def route_after_bpmn_generator(state: BPACCState) -> str:
    if state.get("status") == "failed": return END
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
    """Lance l'instance uniquement si le déploiement a réussi."""
    if state.get("zeebe_deploy_status") == "success":
        return "zeebe_instance_launcher"
    return END