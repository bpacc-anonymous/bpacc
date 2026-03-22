"""
BPACC — Point d'entrée principal
Lancer depuis le répertoire parent de bpacc/ :
  cd /path/to/IEEE_SERVICES
  python -m bpacc.run
"""

from bpacc.bp_layers.B1.graph import run_b1

if __name__ == "__main__":
    state = run_b1(
        user_intent  = "I need to qualify visitors at a tech conference using a Pepper robot.",
        engine       = "camunda",
        version      = "8.8",
        docs_snippet = "",
        thread_id    = "b1-test-001",
    )
    print("\n[run] status     :", state.get("status"))
    print("[run] input_type :", state.get("input_type"))
    print("[run] tasks      :", [t.get("label") for t in state.get("tasks", [])])
    print("[run] gaps       :", state.get("capability_gaps"))
    print("[run] bpmn_valid :", state.get("bpmn_valid"))