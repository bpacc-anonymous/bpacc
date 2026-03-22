"""
BPACC - B1 Node 7 : bpmn_generator
Phase 1 : génère les fragments XML tâche par tâche (LLM)
Phase 2 : assemble le BPMN complet de façon déterministe (Python)
"""

from __future__ import annotations
import json
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import generation_llm
from bpacc.bp_layers.B1.prompts.bpmn_generator_prompt import (
    BPMN_GENERATOR_SYSTEM, BPMN_GENERATOR_PROMPT,
)
from bpacc.bp_layers.B1.nodes.bpmn_assembler import assemble_bpmn


def _get_match(label: str, task_matches: list, consolidated: list) -> dict:
    for m in task_matches:
        if m.get("label") == label:
            return m
    for ct in consolidated:
        if ct.get("label") == label:
            for orig in ct.get("merged_from", []):
                for m in task_matches:
                    if m.get("label") == orig:
                        return m
    return {}


def _tasks_summary(tasks: list, current_index: int) -> str:
    done = tasks[:current_index]
    if not done:
        return "None yet."
    return "\n".join(f"  task_{i+1}: {t.get('label','')}" for i, t in enumerate(done))


def bpmn_generator(state: BPACCState) -> dict:
    tasks          = state.get("consolidated_tasks") or state.get("tasks", [])
    task_matches   = state.get("task_matches", [])
    consolidated   = state.get("consolidated_tasks", [])
    connectors     = state.get("connectors", {})
    bpmn_parts     = list(state.get("bpmn_parts", []))
    bpmn_iteration = state.get("bpmn_iteration", 0)
    task_count     = state.get("task_count", len(tasks))
    engine_context = state.get("engine_context", {})
    user_story     = state.get("user_story", "")
    errors         = list(state.get("errors", []))

    engine       = engine_context.get("engine", "camunda")
    version      = engine_context.get("version", "8.8")
    docs_snippet = engine_context.get("docs_snippet", "")

    # ── Phase 1 : génération incrémentale des fragments ──────────────
    if bpmn_iteration < task_count:
        task     = tasks[bpmn_iteration]
        label    = task.get("label", "")
        cap_name = task.get("cap_name", "")

        match = _get_match(label, task_matches, consolidated)
        if not match and cap_name:
            match = next((m for m in task_matches if m.get("cap_name") == cap_name), {})

        conn = connectors.get(label, {})

        llm = generation_llm(system_prompt=BPMN_GENERATOR_SYSTEM.format(
            engine=engine, version=version
        ))

        fragment = llm.invoke(BPMN_GENERATOR_PROMPT.format(
            current_index    = bpmn_iteration + 1,
            task_count       = task_count,
            engine           = engine,
            version          = version,
            docs_snippet     = docs_snippet,
            task             = json.dumps(task, indent=2, ensure_ascii=False),
            capability_match = json.dumps(match, indent=2, ensure_ascii=False),
            connector        = json.dumps(conn, indent=2, ensure_ascii=False),
            bpmn_so_far      = _tasks_summary(tasks, bpmn_iteration),
        )).strip().strip("```xml").strip("```").strip()

        if fragment:
            bpmn_parts.append(fragment)
        else:
            # Fallback fragment minimal
            task_type = "bpmn:userTask" if task.get("task_type") == "human" else "bpmn:serviceTask"
            bpmn_parts.append(
                f'<{task_type} id="task_{bpmn_iteration+1}" name="{label}"/>'
            )
            errors.append(f"bpmn_generator: fragment vide pour '{label}' — fallback minimal utilisé.")

        print(f"  [bpmn_generator] {bpmn_iteration + 1}/{task_count} — {label}")
        return {
            "bpmn_parts":     bpmn_parts,
            "bpmn_iteration": bpmn_iteration + 1,
            "errors":         errors,
            "status":         "running",
            "current_node":   "bpmn_generator",
        }

    # ── Phase 2 : assemblage déterministe Python ──────────────────────
    print(f"  [bpmn_generator] assemblage Python déterministe...")

    generated_bpmn = assemble_bpmn(
        consolidated_tasks = tasks,
        bpmn_parts         = bpmn_parts,
        engine             = engine,
        title              = user_story[:80] if user_story else "BPACC Process",
    )

    print(f"  [bpmn_generator] ✓ BPMN assemblé — {len(generated_bpmn)} chars")
    return {
        "generated_bpmn": generated_bpmn,
        "bpmn_parts":     bpmn_parts,
        "bpmn_iteration": bpmn_iteration + 1,
        "errors":         errors,
        "status":         "running",
        "current_node":   "bpmn_generator",
    }