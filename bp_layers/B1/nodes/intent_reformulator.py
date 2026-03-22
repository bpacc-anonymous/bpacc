"""
BPACC - B1 Node 2 : intent_reformulator
Transforme le user_intent en une user story détaillée et structurée.
Activé uniquement si input_type == "natural_language" | "both".
"""

from __future__ import annotations
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import reformulation_llm
from bpacc.bp_layers.B1.prompts.intent_reformulator_prompt import (
    INTENT_REFORMULATOR_SYSTEM, INTENT_REFORMULATOR_PROMPT
)


def intent_reformulator(state: BPACCState) -> dict:
    user_intent = state.get("user_intent", "").strip()
    errors      = list(state.get("errors", []))

    llm    = reformulation_llm(system_prompt=INTENT_REFORMULATOR_SYSTEM)
    prompt = INTENT_REFORMULATOR_PROMPT.format(user_intent=user_intent)
    result = llm.invoke_for_json(prompt)

    if not result:
        errors.append("intent_reformulator: LLM returned invalid JSON.")
        return {"errors": errors, "status": "failed", "current_node": "intent_reformulator"}

    user_story_data = result.get("user_story", {})
    user_story      = user_story_data.get("formatted_description", "")

    if not user_story:
        errors.append("intent_reformulator: formatted_description manquant.")
        return {"errors": errors, "status": "failed", "current_node": "intent_reformulator"}

    return {
        "user_story":   user_story,
        "errors":       errors,
        "status":       "running",
        "current_node": "intent_reformulator",
    }