"""
BPACC - run.py  (point d'entrée CLI)

Usage :
  python3 -m bpacc.run

Flow :
  1. run_b1()     → lance le graph jusqu'à l'interrupt human_validator
                    → affiche la synthèse au Business Analyst
  2. L'utilisateur tape  "yes"  ou  "no <justification>"
  3. resume_b1()  → reprend le graph
                    → approved  : zeebe_deployer → zeebe_instance_launcher
                    → rejected  : gap_handler (notification Continuum Engineer)
"""

from __future__ import annotations
from bpacc.bp_layers.B1.graph import run_b1, resume_b1

THREAD_ID = "b1-demo"

USER_INTENT = """
We are a tech company exhibiting at a trade show. We want our Pepper robot to autonomously 
qualify visitors as sales leads. When Pepper detects someone in its activation zone, it 
should greet them, ask for consent to collect data, then conduct a short interview 
(name, company, role, current challenges, buying timeframe, budget). 
All data must be processed on-device to comply with GDPR. The robot must compute a 
Hot/Warm/Cold lead score locally, suggest an appropriate next action (book a meeting, 
send documentation, or note as cold), and push an encrypted summary to our CRM when 
the visitor leaves. Hot leads must trigger an immediate alert to the marketing team.
"""


def _parse_analyst_input(raw: str) -> tuple[str, str]:
    """
    Parse la saisie du BA.
    'yes'         → ('approved', '')
    'no <texte>'  → ('rejected', '<texte>')
    """
    raw = raw.strip()
    if raw.lower().startswith("yes"):
        return "approved", ""
    if raw.lower().startswith("no"):
        feedback = raw[2:].strip(" :—-")
        return "rejected", feedback
    # Toute autre saisie → rejetée avec le texte brut comme feedback
    return "rejected", raw


if __name__ == "__main__":

    # ── Phase 1 : génération + interrupt ────────────────────────────
    state = run_b1(
        user_intent = USER_INTENT,
        engine      = "camunda",
        version     = "8.8",
        thread_id   = THREAD_ID,
    )

    print(f"[run] status     : {state.get('status')}")
    print(f"[run] input_type : {state.get('input_type')}")
    print(f"[run] tasks      : {[t.get('label') for t in state.get('tasks', [])]}")
    print(f"[run] gaps       : {state.get('capability_gaps', [])}")
    print(f"[run] bpmn_valid : {state.get('bpmn_valid')}")

    # ── Phase 2 : saisie BA ──────────────────────────────────────────
    try:
        raw = input("Votre décision (yes / no <justification>) : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[run] Interruption — aucune décision saisie. Arrêt.")
        raise SystemExit(0)

    if not raw:
        print("[run] Aucune saisie — arrêt.")
        raise SystemExit(0)

    validation_status, feedback = _parse_analyst_input(raw)

    print(f"\n[run] validation_status = {validation_status}")
    if feedback:
        print(f"[run] feedback          = {feedback}")

    # ── Phase 3 : reprise du graph ───────────────────────────────────
    final_state = resume_b1(
        validation_status = validation_status,
        feedback          = feedback,
        thread_id         = THREAD_ID,
    )

    print(f"[run] status final : {final_state.get('status')}")