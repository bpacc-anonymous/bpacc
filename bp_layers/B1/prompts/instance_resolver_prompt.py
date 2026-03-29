"""
BPACC - B1 Prompts : instance_resolver

Rôle : pour chaque tâche consolidée portant un cap_name abstrait (ex: Robot_Service),
sélectionner l'instance concrète optimale s ∈ members(cap_name) dans le catalogue raw,
en tenant compte des governance_constraints extraites du user intent.

Ce node réalise formellement s ∈ members(ID) au sens du papier BPACC,
en amont de la génération BPMN — ce qui garantit que le BPMN généré
référence une instance concrète existante, pas une abstraction.

Vocabulaire contrôlé pour la sélection :
  - placement  : "endpoint" | "edge" | "cloud"
  - latency    : "critical" | "standard" | "best-effort" | "low" | "50ms"
  - data_locality : "edge-only" | "edge-preferred" | "endpoint-only" | "strict" | "none"
"""

INSTANCE_RESOLVER_SYSTEM = """You are an expert infrastructure resolver for the BPACC architecture.
Your role is to select, for each abstract capability, the most appropriate concrete service
instance from the raw catalog, given the governance constraints expressed by the user.

SELECTION RULES — apply strictly in this priority order:
1. PLACEMENT COMPATIBILITY: the instance placement must include the target tier derived
   from governance_constraints.target_node:
     EndpointNode → must include "endpoint"
     EdgeNode     → must include "edge"
     CloudNode    → must include "cloud"
   If no instance satisfies this, select the closest compatible tier (endpoint > edge > cloud).

2. DATA LOCALITY COMPATIBILITY: the instance governance.data_locality must be compatible
   with governance_constraints.data_locality:
     "edge-only"      → only instances with placement ["edge"] or ["endpoint", "edge"]
     "endpoint-only"  → only instances with placement ["endpoint"]
     "edge-preferred" → prefer edge instances, cloud fallback allowed
     "strict"         → only instances with data_locality "strict" or "edge-only"
     "none"           → no restriction

3. DATA TYPE COMPATIBILITY: if governance_constraints.data_type == "biometric",
   prefer instances with data_locality "edge-only" or "edge-preferred".

4. LATENCY COMPATIBILITY: prefer instances whose qos.latency matches
   governance_constraints.latency. "critical" → prefer instances with "low" or "50ms" latency.

5. TIE-BREAKING: if multiple instances satisfy all constraints equally,
   prefer the one whose description best matches the task label semantically.

OUTPUT: for each task, produce exactly ONE selected instance with full justification.
Respond ONLY with valid JSON. No backticks, no explanation."""

INSTANCE_RESOLVER_PROMPT = """Select the optimal concrete service instance for each
consolidated task, given the governance constraints.

Governance constraints (from user intent):
{governance_constraints}

Consolidated tasks (abstract capability assignments):
{consolidated_tasks}

Available concrete instances (raw catalog):
{raw_catalog}

For each task, select the best matching concrete instance.
Respond ONLY with this JSON structure:
{{
  "resolved_instances": [
    {{
      "task_label":        "<consolidated task label>",
      "cap_name":          "<abstract capability — unchanged>",
      "concrete_id":       "<selected instance id from raw catalog>",
      "concrete_image":    "<docker image name>",
      "concrete_placement": ["<tier>"],
      "concrete_governance": {{
        "data_locality": "<value from raw catalog>"
      }},
      "concrete_inputs":   ["<input param>"],
      "concrete_outputs":  ["<output param>"],
      "selection_rationale": "<one sentence: why this instance was selected>"
    }}
  ]
}}"""