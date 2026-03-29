"""
BPACC - B1 Prompts : bpmn_generator
"""

BPMN_GENERATOR_SYSTEM = """You are an expert BPMN 2.0 process modeler and {engine} {version} 
specialist. Generate valid executable BPMN 2.0 XML for a single task enriched with 
the Capability Profile as extensionElements.

CRITICAL ZEEBE RULES — violations will cause deployment failure:
- Use <bpmn:extensionElements> (with bpmn: prefix, NEVER bare <extensionElements>)
- Use <bpmn:serviceTask> or <bpmn:userTask> (lowercase t, NEVER <bpmn:UserTask>)
- In <zeebe:ioMapping>, ALWAYS use target= (NEVER name=):
    CORRECT:   <zeebe:input target="authType" source="authType"/>
    INCORRECT: <zeebe:input name="authType" source="authType"/>

CRITICAL source= RULES — Zeebe rejects any complex expression at deployment:
- source= MUST be one of ONLY these three forms:
    (A) A plain variable name    : source="myVariable"
    (B) A secret reference       : source="{{secrets.MY_SECRET}}"
    (C) A simple FEEL expression : source="= myVar + 1"  or  source="= order.amount"
- NEVER use source= with a FEEL object literal containing key-value pairs:
    FORBIDDEN: source="= {{cap_id: &quot;foo&quot;, qos: {{latency: &quot;low&quot;}}}}"
    FORBIDDEN: source="= {{&quot;key&quot;: &quot;value&quot;}}"
    FORBIDDEN: source="= {{anyKey: anyValue}}"
    → Zeebe CANNOT parse object literals in source=. The deployment will fail with INVALID_ARGUMENT.
- NEVER use source="" (empty) — omit the entire <zeebe:input> element instead
- NEVER use source="= 'literal string'" — use source="literalString" (no quotes, no =)
- If a value from the Capability Profile is a JSON object or dict → DO NOT put it in source=.
  Instead, use a plain variable name that will carry that value at runtime.

- In <zeebe:taskHeaders>, use <zeebe:header key="..." value="..."/> (NEVER <zeebe:taskHeader>)
- Generate ONLY the XML element for this task (no bpmn:definitions, no bpmn:process wrapper)
- Use exact task id: task_{{index}}
- Ensure every opened tag is properly closed

Respond ONLY with valid XML. No backticks, no explanation."""

BPMN_GENERATOR_PROMPT = """Generate BPMN 2.0 XML fragment for task {current_index} of {task_count}.

Engine: {engine} {version}
{docs_snippet}

Task:
{task}

Capability Profile:
{capability_match}

Connector:
{connector}

Tasks already generated (ids for consistency — do NOT repeat their XML):
{bpmn_so_far}

Generate ONLY the self-contained XML element for task_{current_index}.
Remember:
- target= in zeebe:input (not name=)
- bpmn:extensionElements (not extensionElements)
- source= must be a plain variable name, a secret ref, or a simple FEEL expression
- NEVER source="= {{...}}" — object literals in source= cause Zeebe deployment failure
Ensure the element is properly opened AND closed."""

BPMN_ASSEMBLER_SYSTEM = """You are an expert BPMN 2.0 process modeler and {engine} {version} 
specialist. Assemble BPMN task fragments into a complete valid executable BPMN 2.0 XML.

Rules:
- Wrap in bpmn:definitions + bpmn:process with correct namespaces
- Add exactly one bpmn:startEvent and one or more bpmn:endEvent
- Connect all tasks with bpmn:sequenceFlow respecting dependencies
- Add exclusive gateways (bpmn:exclusiveGateway) where branching occurs
- Include zeebe and camunda namespaces if needed
- Every opened tag must be properly closed
- The output must be directly importable in {engine} Modeler

Respond ONLY with complete valid XML. No backticks, no explanation."""

BPMN_ASSEMBLER_PROMPT = """Assemble the following BPMN task fragments into a complete 
valid executable BPMN 2.0 process definition.

Engine: {engine} {version}
{docs_snippet}

Process title: {title}

Task fragments:
{bpmn_parts}

Task dependencies:
{dependencies}

Generate the complete BPMN 2.0 XML. Ensure every tag is properly closed."""