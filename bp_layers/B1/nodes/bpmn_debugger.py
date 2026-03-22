"""BPACC - B1 Node 9 : bpmn_debugger"""

from __future__ import annotations
import re
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import generation_llm
from bpacc.bp_layers.B1.prompts.bpmn_debugger_prompt import (
    BPMN_DEBUGGER_SYSTEM, BPMN_DEBUGGER_PROMPT
)

MAX_DEBUG_ITERATIONS = 3


def _extract_error_line(bpmn_errors: list) -> str:
    """Extrait le numéro de ligne depuis les messages d'erreur XML."""
    for err in bpmn_errors:
        match = re.search(r'line\s+(\d+)', str(err))
        if match:
            return match.group(1)
    return "unknown"


def bpmn_debugger(state: BPACCState) -> dict:
    generated_bpmn  = state.get("generated_bpmn", "")
    bpmn_errors     = state.get("bpmn_errors", [])
    debug_iteration = state.get("debug_iteration", 0)
    engine_context  = state.get("engine_context", {})
    errors          = list(state.get("errors", []))

    engine     = engine_context.get("engine", "camunda")
    version    = engine_context.get("version", "8.8")
    error_line = _extract_error_line(bpmn_errors)

    print(f"  [bpmn_debugger] tentative {debug_iteration + 1}/{MAX_DEBUG_ITERATIONS} — erreur ligne {error_line}")

    llm   = generation_llm(system_prompt=BPMN_DEBUGGER_SYSTEM.format(engine=engine, version=version))
    fixed = llm.invoke(BPMN_DEBUGGER_PROMPT.format(
        engine         = engine,
        version        = version,
        bpmn_errors    = "\n".join(f"- {e}" for e in bpmn_errors),
        error_line     = error_line,
        generated_bpmn = generated_bpmn,
    )).strip().strip("```xml").strip("```").strip()

    if not fixed:
        errors.append(f"bpmn_debugger: réponse vide tentative {debug_iteration + 1}.")
        return {"debug_iteration": debug_iteration + 1, "errors": errors,
                "status": "running", "current_node": "bpmn_debugger"}

    print(f"  [bpmn_debugger] ✓ XML corrigé — {len(fixed)} chars")
    return {
        "generated_bpmn":  fixed,
        "debug_iteration": debug_iteration + 1,
        "errors":          errors,
        "status":          "running",
        "current_node":    "bpmn_debugger",
    }