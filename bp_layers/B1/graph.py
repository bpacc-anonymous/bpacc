"""
BPACC - B1 Business Intent Converter
Graph Assembly (LangGraph 1.0)

Nodes :
  1.  format_detector
  2.  intent_reformulator
  3.  task_estimator
  4.  task_decomposer          (boucle × task_count)
  5.  capability_retriever
  5b. task_consolidator
  6.  connector_loader
  7.  bpmn_generator           (boucle × task_count + assemblage Python)
  8.  bpmn_validator
  9.  bpmn_debugger            (boucle ≤ MAX_DEBUG_ITERATIONS)
  10. persist_bpmn
  11. response_generator
  12. human_validator          (interrupt — Business Analyst)
  13. zeebe_deployer           (déploiement auto vers Zeebe si approved)
  14. zeebe_instance_launcher  (lancement instance si déploiement OK)
  15. gap_handler              (notification Continuum Engineer si rejected)
"""

from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.edge import (
    route_after_format_detector,
    route_after_intent_reformulator,
    route_after_task_estimator,
    route_after_task_decomposer,
    route_after_capability_retriever,
    route_after_task_consolidator,
    route_after_bpmn_generator,
    route_after_bpmn_validator,
    route_after_human_validator,
    route_after_zeebe_deployer,
)
from bpacc.bp_layers.B1.nodes.format_detector         import format_detector
from bpacc.bp_layers.B1.nodes.intent_reformulator     import intent_reformulator
from bpacc.bp_layers.B1.nodes.task_estimator          import task_estimator
from bpacc.bp_layers.B1.nodes.task_decomposer         import task_decomposer
from bpacc.bp_layers.B1.nodes.capability_retriever    import capability_retriever
from bpacc.bp_layers.B1.nodes.task_consolidator       import task_consolidator
from bpacc.bp_layers.B1.nodes.connector_loader        import connector_loader
from bpacc.bp_layers.B1.nodes.bpmn_generator          import bpmn_generator
from bpacc.bp_layers.B1.nodes.bpmn_validator          import bpmn_validator
from bpacc.bp_layers.B1.nodes.bpmn_debugger           import bpmn_debugger
from bpacc.bp_layers.B1.nodes.bpmn_persistence        import persist_bpmn
from bpacc.bp_layers.B1.nodes.response_generator      import response_generator
from bpacc.bp_layers.B1.nodes.human_validator         import human_validator
from bpacc.bp_layers.B1.nodes.zeebe_deployer          import zeebe_deployer
from bpacc.bp_layers.B1.nodes.zeebe_instance_launcher import zeebe_instance_launcher
from bpacc.bp_layers.B1.nodes.gap_handler             import gap_handler


def build_b1_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    g = StateGraph(BPACCState)

    # ── Nodes ────────────────────────────────────────────────────────
    g.add_node("format_detector",          format_detector)
    g.add_node("intent_reformulator",      intent_reformulator)
    g.add_node("task_estimator",           task_estimator)
    g.add_node("task_decomposer",          task_decomposer)
    g.add_node("capability_retriever",     capability_retriever)
    g.add_node("task_consolidator",        task_consolidator)
    g.add_node("connector_loader",         connector_loader)
    g.add_node("bpmn_generator",           bpmn_generator)
    g.add_node("bpmn_validator",           bpmn_validator)
    g.add_node("bpmn_debugger",            bpmn_debugger)
    g.add_node("persist_bpmn",             persist_bpmn)
    g.add_node("response_generator",       response_generator)
    g.add_node("human_validator",          human_validator)
    g.add_node("zeebe_deployer",           zeebe_deployer)
    g.add_node("zeebe_instance_launcher",  zeebe_instance_launcher)
    g.add_node("gap_handler",              gap_handler)

    # ── Entry ────────────────────────────────────────────────────────
    g.add_edge(START, "format_detector")

    # ── Edges conditionnels ──────────────────────────────────────────
    g.add_conditional_edges("format_detector",      route_after_format_detector)
    g.add_conditional_edges("intent_reformulator",  route_after_intent_reformulator)
    g.add_conditional_edges("task_estimator",       route_after_task_estimator)
    g.add_conditional_edges("task_decomposer",      route_after_task_decomposer)
    g.add_conditional_edges("capability_retriever", route_after_capability_retriever)
    g.add_conditional_edges("task_consolidator",    route_after_task_consolidator)
    g.add_conditional_edges("bpmn_generator",       route_after_bpmn_generator)
    g.add_conditional_edges("bpmn_validator",       route_after_bpmn_validator)
    g.add_conditional_edges("human_validator",      route_after_human_validator)
    g.add_conditional_edges("zeebe_deployer",       route_after_zeebe_deployer)

    # ── Edges fixes ──────────────────────────────────────────────────
    g.add_edge("connector_loader",         "bpmn_generator")
    g.add_edge("bpmn_debugger",            "bpmn_validator")
    g.add_edge("persist_bpmn",             "response_generator")
    g.add_edge("response_generator",       "human_validator")
    g.add_edge("zeebe_instance_launcher",  END)
    g.add_edge("gap_handler",              END)

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_validator"],
    )


b1_graph = build_b1_graph()


def run_b1(
    user_intent:   str,
    engine:        str = "camunda",
    version:       str = "8.8",
    docs_snippet:  str = "",
    uploaded_file: str = "",
    thread_id:     str = "b1-default",
):
    config = {"configurable": {"thread_id": thread_id}}
    return b1_graph.invoke({
        "messages":        [],
        "user_intent":     user_intent,
        "uploaded_file":   uploaded_file,
        "engine_context":  {"engine": engine, "version": version, "docs_snippet": docs_snippet},
        "task_iteration":  0,
        "bpmn_iteration":  0,
        "debug_iteration": 0,
        "tasks":           [],
        "bpmn_parts":      [],
        "errors":          [],
        "status":          "running",
        "current_node":    "START",
    }, config=config)