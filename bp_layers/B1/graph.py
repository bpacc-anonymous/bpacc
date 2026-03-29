"""
BPACC - B1 Business Intent Converter
Graph Assembly (LangGraph 1.0)

Nodes :
  1.  format_detector
  2.  intent_reformulator         (+ extraction GovernanceConstraints)
  3.  task_estimator
  4.  task_decomposer             (boucle × task_count)
  5.  capability_retriever
  5b. task_consolidator
  5c. instance_resolver           (NOUVEAU — s ∈ members(ID) au sens du papier)
  6.  connector_loader
  7.  bpmn_generator              (boucle × task_count + assemblage Python)
  8.  bpmn_validator
  9.  bpmn_debugger               (boucle ≤ MAX_DEBUG_ITERATIONS)
  10. persist_bpmn
  11. response_generator
  12. human_validator             (interrupt — Business Analyst)
  13. zeebe_deployer              (déploiement auto vers Zeebe si approved)
  14. zeebe_instance_launcher     (lancement instance si déploiement OK)
  15. gap_handler                 (notification Continuum Engineer si rejected)
"""

from __future__ import annotations
import json
import textwrap
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.edge import (
    route_after_format_detector,
    route_after_intent_reformulator,
    route_after_task_estimator,
    route_after_task_decomposer,
    route_after_capability_retriever,
    route_after_task_consolidator,
    route_after_instance_resolver,
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
from bpacc.bp_layers.B1.nodes.instance_resolver       import instance_resolver
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
    g.add_node("instance_resolver",        instance_resolver)
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
    g.add_conditional_edges("instance_resolver",    route_after_instance_resolver)
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


# ── Présentation structurée au Business Analyst ──────────────────────────────

def _present_to_analyst(state: dict) -> None:
    SEP  = "─" * 70
    SEP2 = "═" * 70

    response_summary   = state.get("response_summary", "")
    consolidated_tasks = state.get("consolidated_tasks", [])
    capability_gaps    = state.get("capability_gaps", [])
    bpmn_valid         = state.get("bpmn_valid", False)
    bpmn_path          = state.get("bpmn_path", "(en mémoire uniquement)")
    task_matches       = state.get("task_matches", [])
    gov                = state.get("governance_constraints", {})

    summary_obj = {}
    if response_summary:
        try:
            summary_obj = json.loads(response_summary)
        except json.JSONDecodeError:
            pass

    print(f"\n{SEP2}")
    print("  BPACC — RAPPORT AU BUSINESS ANALYST")
    print(f"{SEP2}\n")

    status_label = {
        "success": "✅  SUCCÈS COMPLET",
        "partial": "⚠️   SUCCÈS PARTIEL (gaps détectés)",
        "failed":  "❌  ÉCHEC",
    }.get(summary_obj.get("status", ""), "ℹ️   RÉSULTAT")
    print(f"  Statut        : {status_label}")
    print(f"  BPMN valide   : {'✓ oui' if bpmn_valid else '✗ non'}")
    print(f"  Fichier BPMN  : {bpmn_path}")

    if gov:
        print(f"\n{SEP}")
        print("  CONTRAINTES DE GOUVERNANCE EXTRAITES DU USER INTENT\n")
        labels = {
            "region":        "Région géographique",
            "latency":       "Profil de latence",
            "target_node":   "Tier cible",
            "data_type":     "Type de données",
            "consent":       "Consentement explicite",
            "data_locality": "Localisation des données",
        }
        for k, label in labels.items():
            if k in gov:
                print(f"    {label:<30} : {gov[k]}")

    if summary_obj.get("summary"):
        print(f"\n{SEP}")
        print("  RÉSUMÉ\n")
        for line in textwrap.wrap(summary_obj["summary"], width=66):
            print(f"    {line}")

    print(f"\n{SEP}")
    print(f"  TÂCHES GÉNÉRÉES DANS LE BPMN ({len(consolidated_tasks)})\n")
    for i, t in enumerate(consolidated_tasks, 1):
        deps         = ", ".join(t.get("dependencies", [])) or "—"
        concrete_id  = t.get("concrete_id") or "non résolu"
        concrete_img = t.get("concrete_image") or "?"
        print(f"    {i:>2}. [{t.get('task_type','?'):9}] {t.get('label','')}")
        print(f"          Abstrait  : {t.get('cap_name', '?')}")
        print(f"          Instance  : {concrete_id} ({concrete_img})")
        print(f"          Dépend    : {deps}")

    if capability_gaps:
        print(f"\n{SEP}")
        print(f"  ⚠️  CAPABILITY GAPS ({len(capability_gaps)}) — tâches non couvertes\n")
        for gap in capability_gaps:
            match = next((m for m in task_matches if m.get("label") == gap), {})
            dist  = match.get("distance", "?")
            best  = match.get("cap_name", "?")
            print(f"    ✗  {gap}")
            print(f"       Meilleur service trouvé : {best} (distance={dist})")
            print(f"       → Aucun service suffisamment proche dans le catalogue.")
        if summary_obj.get("gap_explanation"):
            print()
            for line in textwrap.wrap(summary_obj["gap_explanation"], width=66):
                print(f"    {line}")
    else:
        print(f"\n{SEP}")
        print("  ✅  Aucun capability gap — toutes les tâches sont couvertes.")

    if summary_obj.get("next_steps"):
        print(f"\n{SEP}")
        print("  PROCHAINES ÉTAPES\n")
        for line in textwrap.wrap(summary_obj["next_steps"], width=66):
            print(f"    {line}")

    print(f"\n{SEP2}")
    print("  VALIDATION REQUISE\n")
    print("  Répondez :")
    print("    yes              → approuve et lance le déploiement Zeebe")
    print("    no <justification> → rejette et notifie le Continuum Engineer")
    print(f"{SEP2}\n")


# ── run_b1 ───────────────────────────────────────────────────────────────────

def run_b1(
    user_intent:   str,
    engine:        str = "camunda",
    version:       str = "8.8",
    docs_snippet:  str = "",
    uploaded_file: str = "",
    thread_id:     str = "b1-default",
) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    state = b1_graph.invoke({
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

    _present_to_analyst(state)
    return state


# ── resume_b1 ─────────────────────────────────────────────────────────────────

def resume_b1(
    validation_status: str,
    feedback:          str = "",
    thread_id:         str = "b1-default",
) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    human_response = {
        "validation_status": validation_status.lower().strip(),
        "feedback":          feedback.strip(),
    }
    print(f"\n  [resume_b1] reprise du graph — validation_status={human_response['validation_status']}")
    if feedback:
        print(f"  [resume_b1] feedback BA : {feedback[:120]}")

    final_state = b1_graph.invoke(Command(resume=human_response), config=config)
    _print_final_outcome(final_state)
    return final_state


def _print_final_outcome(state: dict) -> None:
    SEP2 = "═" * 70
    print(f"\n{SEP2}")
    print("  BPACC — RÉSULTAT FINAL")
    print(f"{SEP2}\n")

    validation = state.get("validation_status", "?")
    if validation == "approved":
        deploy_status   = state.get("zeebe_deploy_status", "?")
        instance_status = state.get("zeebe_instance_status", "?")
        key             = state.get("zeebe_process_definition_key", "?")
        pid             = state.get("zeebe_process_id", "?")
        instance_key    = state.get("zeebe_instance_key", "?")

        if deploy_status == "success":
            print(f"  ✅  Déploiement Zeebe        : succès")
            print(f"      processDefinitionKey      : {key}")
            print(f"      processDefinitionId       : {pid}")
        else:
            print(f"  ❌  Déploiement Zeebe        : ÉCHEC")

        if instance_status == "success":
            print(f"  ✅  Instance lancée          : succès")
            print(f"      processInstanceKey        : {instance_key}")
        elif deploy_status == "success":
            print(f"  ❌  Lancement instance       : ÉCHEC")
    else:
        gap_sent = state.get("gap_notification_sent", False)
        print(f"  ℹ️   Validation               : rejetée")
        print(f"  {'✅' if gap_sent else '❌'}  Notification Continuum Eng. : {'envoyée' if gap_sent else 'non envoyée'}")

    errors = state.get("errors", [])
    if errors:
        print(f"\n  Erreurs ({len(errors)}) :")
        for e in errors[-5:]:
            print(f"    - {e}")

    print(f"\n{SEP2}\n")