"""
BPACC - B1 Node 9 : bpmn_debugger (surgical patch mode)

Stratégie :
  1. Extraire un fragment de N lignes autour de la ligne fautive (via lxml ou fallback line-based)
  2. Envoyer UNIQUEMENT ce fragment au LLM pour correction
  3. Réinsérer le fragment corrigé chirurgicalement dans le document original
  4. Ne jamais confier l'intégralité du XML au LLM

Cela évite les régressions introduites par le LLM sur les parties non-fautives.
"""

from __future__ import annotations
import re
from bpacc.bp_layers.B1.state import BPACCState
from bpacc.bp_layers.B1.model.base_model import generation_llm
from bpacc.bp_layers.B1.prompts.bpmn_debugger_prompt import (
    BPMN_DEBUGGER_SYSTEM,
    BPMN_DEBUGGER_FRAGMENT_PROMPT,
)

MAX_DEBUG_ITERATIONS = 3
CONTEXT_LINES        = 8   # lignes de contexte de chaque côté de la ligne fautive


# ── Extraction du numéro de ligne ────────────────────────────────────────────

def _extract_error_line(bpmn_errors: list) -> int | None:
    """
    Extrait le premier numéro de ligne trouvé dans les messages d'erreur.
    Retourne None si aucun numéro trouvé.
    """
    for err in bpmn_errors:
        match = re.search(r'line\s+(\d+)', str(err), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


# ── Extraction chirurgicale du fragment fautif ───────────────────────────────

def _extract_fragment(xml: str, error_line: int, context: int = CONTEXT_LINES) -> tuple[str, int, int]:
    """
    Retourne (fragment, start_line_1indexed, end_line_1indexed).

    - fragment  : sous-chaîne du XML délimitée par des balises ouvrantes/fermantes complètes
    - start/end : indices 1-based des lignes extraites (pour la réinsertion)

    Stratégie : on prend [error_line - context .. error_line + context],
    puis on élargit vers le haut jusqu'à une balise ouvrante propre
    et vers le bas jusqu'à une balise fermante propre, afin que le
    fragment soit un XML parseable (ou au moins cohérent).
    """
    lines = xml.splitlines()
    total = len(lines)

    # Bornes initiales (1-based → 0-based pour les indices Python)
    raw_start = max(0,         error_line - 1 - context)
    raw_end   = min(total - 1, error_line - 1 + context)

    # Élargir vers le haut jusqu'à une ligne qui ouvre une balise
    start = raw_start
    while start > 0 and not re.search(r'<\w', lines[start]):
        start -= 1

    # Élargir vers le bas jusqu'à une ligne qui ferme une balise
    end = raw_end
    while end < total - 1 and not re.search(r'</\w|/>', lines[end]):
        end += 1

    fragment = "\n".join(lines[start:end + 1])
    return fragment, start + 1, end + 1   # retour en 1-based


# ── Réinsertion chirurgicale ──────────────────────────────────────────────────

def _patch_xml(original: str, corrected_fragment: str, start_1: int, end_1: int) -> str:
    """
    Remplace les lignes [start_1..end_1] (1-based, inclusives) du XML original
    par corrected_fragment, puis retourne le document XML reconstitué.
    """
    lines   = original.splitlines()
    before  = lines[:start_1 - 1]
    after   = lines[end_1:]              # end_1 est inclusif → on part de end_1 (0-based = end_1)
    patched = before + corrected_fragment.splitlines() + after
    return "\n".join(patched)


# ── Nettoyage de la réponse LLM ──────────────────────────────────────────────

def _clean_llm_fragment(raw: str) -> str:
    """Retire les backticks et espaces parasites de la réponse LLM."""
    raw = raw.strip()
    raw = re.sub(r'^```(?:xml)?\s*', '', raw)
    raw = re.sub(r'\s*```$',         '', raw)
    return raw.strip()


# ── Node principal ────────────────────────────────────────────────────────────

def bpmn_debugger(state: BPACCState) -> dict:
    generated_bpmn  = state.get("generated_bpmn", "")
    bpmn_errors     = state.get("bpmn_errors", [])
    debug_iteration = state.get("debug_iteration", 0)
    engine_context  = state.get("engine_context", {})
    errors          = list(state.get("errors", []))

    engine  = engine_context.get("engine",  "camunda")
    version = engine_context.get("version", "8.8")

    error_line = _extract_error_line(bpmn_errors)
    line_label = str(error_line) if error_line else "unknown"

    print(f"  [bpmn_debugger] tentative {debug_iteration + 1}/{MAX_DEBUG_ITERATIONS} "
          f"— erreur ligne {line_label}")

    # ── Cas dégradé : pas de numéro de ligne détecté ─────────────────
    # On ne confie JAMAIS tout le BPMN au LLM.
    # Si on ne peut pas localiser l'erreur, on log et on abandonne cette tentative.
    if error_line is None:
        msg = (f"bpmn_debugger: numéro de ligne introuvable dans les erreurs "
               f"({bpmn_errors}) — tentative {debug_iteration + 1} abandonnée.")
        errors.append(msg)
        print(f"  [bpmn_debugger] ✗ {msg}")
        return {
            "debug_iteration": debug_iteration + 1,
            "errors":          errors,
            "status":          "running",
            "current_node":    "bpmn_debugger",
        }

    # ── Extraction du fragment fautif ─────────────────────────────────
    fragment, frag_start, frag_end = _extract_fragment(generated_bpmn, error_line)

    print(f"  [bpmn_debugger] fragment extrait : lignes {frag_start}–{frag_end} "
          f"({frag_end - frag_start + 1} lignes)")

    # ── Appel LLM sur le fragment uniquement ─────────────────────────
    llm = generation_llm(system_prompt=BPMN_DEBUGGER_SYSTEM.format(
        engine=engine, version=version
    ))

    corrected_raw = llm.invoke(BPMN_DEBUGGER_FRAGMENT_PROMPT.format(
        engine        = engine,
        version       = version,
        bpmn_errors   = "\n".join(f"- {e}" for e in bpmn_errors),
        error_line    = error_line,
        frag_start    = frag_start,
        frag_end      = frag_end,
        fragment      = fragment,
    )).strip()

    corrected_fragment = _clean_llm_fragment(corrected_raw)

    if not corrected_fragment:
        msg = f"bpmn_debugger: réponse LLM vide — tentative {debug_iteration + 1} abandonnée."
        errors.append(msg)
        print(f"  [bpmn_debugger] ✗ {msg}")
        return {
            "debug_iteration": debug_iteration + 1,
            "errors":          errors,
            "status":          "running",
            "current_node":    "bpmn_debugger",
        }

    # ── Réinsertion chirurgicale ──────────────────────────────────────
    patched_bpmn = _patch_xml(generated_bpmn, corrected_fragment, frag_start, frag_end)

    print(f"  [bpmn_debugger] ✓ patch appliqué — "
          f"{len(patched_bpmn)} chars (était {len(generated_bpmn)})")

    return {
        "generated_bpmn":  patched_bpmn,
        "debug_iteration": debug_iteration + 1,
        "errors":          errors,
        "status":          "running",
        "current_node":    "bpmn_debugger",
    }