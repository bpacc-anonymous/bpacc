"""
BPACC - B1 BPMN Assembler (déterministe)
Assemble les fragments de tâches en un BPMN 2.0 complet valide.

Règle Zeebe pour zeebe:input :
  - target="varName"         → variable process cible (OBLIGATOIRE, pas name=)
  - source="varName"         → variable process source
  - source="{{secrets.X}}"  → secret reference
  - source="= {FEEL}"       → expression FEEL complexe

Normalisations post-LLM dans _normalize_fragment() :
  Fix 1 : <extensionElements> sans préfixe → <bpmn:extensionElements>
  Fix 2 : zeebe:input value="..." → source="..."
  Fix 3 : <zeebe:taskHeader> dans <zeebe:taskHeaders> → <zeebe:header>
  Fix 4 : <zeebe:input .../> sans source ou source vide → supprimé
  Fix 5 : <bpmn:UserTask> (majuscule) → <bpmn:userTask>
  Fix 6 : source="= 'literal'" ou source="= \"literal\"" → source="literal"
  Fix 7 : zeebe:input name="..." → zeebe:input target="..."
  Fix 8 : caractères XML invalides dans source= (&, >, <, " non échappés)
"""

from __future__ import annotations
import re
import uuid

BPMN_NS = (
    'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
    'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
    'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
    'xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" '
    'xmlns:modeler="http://camunda.org/schema/modeler/1.0" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)

TASK_W, TASK_H = 160, 60
GW_W,   GW_H   = 50,  50
EVT_W,  EVT_H  = 36,  36
H_GAP          = 60
V_GAP          = 80
BASE_Y         = 200
BASE_X         = 60


def _sid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _escape_xml_in_source(val: str) -> str:
    """
    Échappe les caractères XML invalides dans une valeur source=.
    Ne touche pas les entités déjà échappées (&#34; &amp; etc.)
    """
    # D'abord, dé-encoder les entités existantes pour travailler sur le texte brut
    # puis ré-encoder proprement
    # Stratégie : on ne touche que & < > non échappés
    # & → &amp; (seulement si pas déjà &amp; ou &#...)
    val = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', val)
    # < → &lt; (sauf dans les balises FEEL qui ne devraient pas en avoir)
    val = val.replace('<', '&lt;')
    # > → &gt; (attention : >= est valide en FEEL mais invalide en XML attr)
    # On ne remplace > que s'il n'est pas précédé d'= (pour >=)
    # En FEEL, >= doit être écrit comme &gt;= dans un attribut XML
    val = re.sub(r'(?<!=)>(?!=)', '&gt;', val)  # > mais pas >= ni =>
    val = re.sub(r'>=', '&gt;=', val)            # >= → &gt;=
    return val


def _fix_source_value(val: str) -> str | None:
    """
    Normalise la valeur source= d'un zeebe:input.
    Retourne None si l'input doit être supprimé.
    """
    if val == "":
        return None

    if not val.startswith("="):
        return val  # variable reference ou secret, pas de traitement FEEL

    feel = val[1:].strip()

    # = 'literal' → literal
    m = re.match(r"^'(.*)'$", feel)
    if m:
        return m.group(1)

    # = "literal" → literal
    m = re.match(r'^"(.*)"$', feel)
    if m:
        return m.group(1)

    # = {{secrets.X}} → {{secrets.X}}
    if feel.startswith("{{") and feel.endswith("}}"):
        return feel

    # = {FEEL complex object} → garder avec le =
    if feel.startswith("{"):
        return val

    # = varName.path → garder
    return val


def _normalize_input_tag(m: re.Match) -> str:
    """Normalise un zeebe:input complet. Retourne '' pour suppression."""
    tag = m.group(0)

    src_match = re.search(r'source="([^"]*)"', tag)
    if not src_match:
        return ""

    val = src_match.group(1)
    fixed = _fix_source_value(val)

    if fixed is None:
        return ""

    # Fix 8 : échappe les caractères XML invalides dans la valeur finale
    fixed = _escape_xml_in_source(fixed)

    if fixed == val:
        return tag

    return tag.replace(f'source="{val}"', f'source="{fixed}"', 1)


def _normalize_fragment(fragment: str) -> str:
    """Normalise un fragment XML généré par le LLM pour le rendre conforme Zeebe."""

    # Fix 1 — extensionElements sans préfixe bpmn:
    fragment = re.sub(r'<extensionElements(\s|>)', r'<bpmn:extensionElements\1', fragment)
    fragment = re.sub(r'</extensionElements>', r'</bpmn:extensionElements>', fragment)

    # Fix 2 — zeebe:input value="..." → source="..."
    def _swap_value_to_source(m: re.Match) -> str:
        tag = m.group(0)
        if 'source=' in tag:
            return tag
        return tag.replace(' value=', ' source=', 1)
    fragment = re.sub(r'<zeebe:input\b[^>]*/?>',  _swap_value_to_source, fragment)

    # Fix 3 — <zeebe:taskHeader> dans <zeebe:taskHeaders> → <zeebe:header>
    def _fix_task_header_inside_task_headers(m: re.Match) -> str:
        inner = m.group(1)
        inner = re.sub(r'<zeebe:taskHeader\b', '<zeebe:header', inner)
        inner = re.sub(r'</zeebe:taskHeader>', '</zeebe:header>', inner)
        return f'<zeebe:taskHeaders>{inner}</zeebe:taskHeaders>'
    fragment = re.sub(
        r'<zeebe:taskHeaders>(.*?)</zeebe:taskHeaders>',
        _fix_task_header_inside_task_headers,
        fragment, flags=re.DOTALL
    )

    # Fix 5 — <bpmn:UserTask> → <bpmn:userTask>
    fragment = re.sub(r'<bpmn:UserTask\b', '<bpmn:userTask', fragment)
    fragment = re.sub(r'</bpmn:UserTask>', '</bpmn:userTask>', fragment)

    # Fix 4 + Fix 6 + Fix 8 — normalise source= et supprime les inputs invalides
    fragment = re.sub(r'<zeebe:input\b[^>]*/?>',  _normalize_input_tag, fragment)

    # Fix 7 — zeebe:input name="..." → zeebe:input target="..."
    fragment = re.sub(r'(<zeebe:input\s+)name=', r'\1target=', fragment)

    return fragment


def _clean_fragment(fragment: str, task_id: str, task_name: str, task_type: str) -> str:
    """Nettoie le fragment LLM — retire wrappers, force id et name, normalise XML."""
    frag = re.sub(r'<\?xml[^>]*\?>', '', fragment).strip()
    for tag in ['bpmn:definitions', '/bpmn:definitions', 'bpmn:process[^>]*',
                '/bpmn:process', 'definitions[^>]*', '/definitions',
                'process[^>]*', '/process']:
        frag = re.sub(f'<{tag}>', '', frag)
    frag = frag.strip()

    if not frag or len(frag) < 10:
        elem = "bpmn:userTask" if task_type == "human" else "bpmn:serviceTask"
        return f'<{elem} id="{task_id}" name="{task_name}"></{elem}>'

    frag = re.sub(r'\bid="[^"]*"', f'id="{task_id}"', frag, count=1)
    if f'id="{task_id}"' not in frag:
        frag = re.sub(
            r'(<(?:bpmn:)?(?:serviceTask|userTask|task)\b)',
            f'\\1 id="{task_id}"', frag, count=1
        )
    frag = re.sub(r'\bname="[^"]*"', f'name="{task_name}"', frag, count=1)
    frag = _normalize_fragment(frag)
    return frag


def assemble_bpmn(
    consolidated_tasks: list,
    bpmn_parts: list,
    engine: str = "camunda",
    title: str = "BPACC Process",
) -> str:

    n = len(consolidated_tasks)
    if n == 0:
        return ""

    label_to_idx = {t["label"]: i for i, t in enumerate(consolidated_tasks)}
    task_ids     = [f"task_{i+1}" for i in range(n)]

    successors   = {i: [] for i in range(n)}
    predecessors = {i: [] for i in range(n)}
    for i, task in enumerate(consolidated_tasks):
        for dep in task.get("dependencies", []):
            j = label_to_idx.get(dep)
            if j is not None:
                successors[j].append(i)
                predecessors[i].append(j)

    roots  = [i for i in range(n) if not predecessors[i]]
    leaves = [i for i in range(n) if not successors[i]]

    depth = {}
    queue = list(roots)
    for r in roots:
        depth[r] = 0
    while queue:
        cur = queue.pop(0)
        for s in successors[cur]:
            d = depth[cur] + 1
            if s not in depth or depth[s] < d:
                depth[s] = d
            queue.append(s)

    cols = {}
    for i in range(n):
        cols.setdefault(depth.get(i, 0), []).append(i)

    pos = {}
    for col_idx in sorted(cols.keys()):
        tasks_in_col = cols[col_idx]
        total_h = len(tasks_in_col) * TASK_H + (len(tasks_in_col) - 1) * V_GAP
        start_y = BASE_Y - total_h // 2
        x = BASE_X + col_idx * (TASK_W + H_GAP + GW_W + H_GAP)
        for row, i in enumerate(tasks_in_col):
            pos[i] = (x, start_y + row * (TASK_H + V_GAP))

    process_elements = []
    di_shapes        = []
    di_edges         = []
    flows            = []
    flow_count       = [0]

    def add_flow(src_id, tgt_id, src_pos=None, tgt_pos=None):
        fid = f"flow_{flow_count[0]}"
        flow_count[0] += 1
        flows.append(
            f'<bpmn:sequenceFlow id="{fid}" sourceRef="{src_id}" targetRef="{tgt_id}"/>'
        )
        wp = ""
        if src_pos and tgt_pos:
            wp = (f'<di:waypoint x="{src_pos[0]}" y="{src_pos[1]}"/>'
                  f'<di:waypoint x="{tgt_pos[0]}" y="{tgt_pos[1]}"/>')
        di_edges.append(
            f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{wp}</bpmndi:BPMNEdge>'
        )

    start_id = "StartEvent_1"
    start_x  = BASE_X - EVT_W // 2 - H_GAP - 20
    start_y  = BASE_Y + TASK_H // 2 - EVT_H // 2
    process_elements.append(f'<bpmn:startEvent id="{start_id}" name="Start"/>')
    di_shapes.append(
        f'<bpmndi:BPMNShape id="{start_id}_di" bpmnElement="{start_id}">'
        f'<dc:Bounds x="{start_x}" y="{start_y}" width="{EVT_W}" height="{EVT_H}"/>'
        f'</bpmndi:BPMNShape>'
    )
    for r in roots:
        rx, ry = pos[r]
        add_flow(start_id, task_ids[r],
                 (start_x + EVT_W, start_y + EVT_H // 2),
                 (rx, ry + TASK_H // 2))

    for i, (task, fragment) in enumerate(zip(consolidated_tasks, bpmn_parts)):
        tid     = task_ids[i]
        t_name  = task.get("label", f"Task {i+1}")
        t_type  = task.get("task_type", "automated")
        cleaned = _clean_fragment(fragment or "", tid, t_name, t_type)
        process_elements.append(cleaned)
        tx, ty = pos[i]
        di_shapes.append(
            f'<bpmndi:BPMNShape id="{tid}_di" bpmnElement="{tid}">'
            f'<dc:Bounds x="{tx}" y="{ty}" width="{TASK_W}" height="{TASK_H}"/>'
            f'</bpmndi:BPMNShape>'
        )

    for i in range(n):
        succs = successors[i]
        tx, ty = pos[i]
        if len(succs) == 0:
            pass
        elif len(succs) == 1:
            j = succs[0]
            jx, jy = pos[j]
            add_flow(task_ids[i], task_ids[j],
                     (tx + TASK_W, ty + TASK_H // 2),
                     (jx, jy + TASK_H // 2))
        else:
            gw_id = f"gw_split_{i}"
            gw_x  = tx + TASK_W + H_GAP
            gw_y  = ty + TASK_H // 2 - GW_H // 2
            process_elements.append(
                f'<bpmn:exclusiveGateway id="{gw_id}" name="" gatewayDirection="Diverging"/>'
            )
            di_shapes.append(
                f'<bpmndi:BPMNShape id="{gw_id}_di" bpmnElement="{gw_id}" isMarkerVisible="true">'
                f'<dc:Bounds x="{gw_x}" y="{gw_y}" width="{GW_W}" height="{GW_H}"/>'
                f'</bpmndi:BPMNShape>'
            )
            add_flow(task_ids[i], gw_id,
                     (tx + TASK_W, ty + TASK_H // 2),
                     (gw_x, gw_y + GW_H // 2))
            for j in succs:
                jx, jy = pos[j]
                add_flow(gw_id, task_ids[j],
                         (gw_x + GW_W, gw_y + GW_H // 2),
                         (jx, jy + TASK_H // 2))

    for i in range(n):
        preds = predecessors[i]
        if len(preds) <= 1:
            continue
        already = any(f'targetRef="{task_ids[i]}"' in f for f in flows)
        if already:
            continue
        gw_id = f"gw_join_{i}"
        tx, ty = pos[i]
        gw_x   = tx - H_GAP - GW_W
        gw_y   = ty + TASK_H // 2 - GW_H // 2
        process_elements.append(
            f'<bpmn:exclusiveGateway id="{gw_id}" name="" gatewayDirection="Converging"/>'
        )
        di_shapes.append(
            f'<bpmndi:BPMNShape id="{gw_id}_di" bpmnElement="{gw_id}" isMarkerVisible="true">'
            f'<dc:Bounds x="{gw_x}" y="{gw_y}" width="{GW_W}" height="{GW_H}"/>'
            f'</bpmndi:BPMNShape>'
        )
        new_flows, new_di_edges = [], []
        for f, e in zip(flows, di_edges):
            if f'targetRef="{task_ids[i]}"' in f:
                new_flows.append(
                    f.replace(f'targetRef="{task_ids[i]}"', f'targetRef="{gw_id}"')
                )
                new_di_edges.append(e)
            else:
                new_flows.append(f)
                new_di_edges.append(e)
        flows[:] = new_flows
        di_edges[:] = new_di_edges
        add_flow(gw_id, task_ids[i],
                 (gw_x + GW_W, gw_y + GW_H // 2),
                 (tx, ty + TASK_H // 2))

    max_x  = max(pos[i][0] for i in range(n))
    end_id = "EndEvent_1"
    end_x  = max_x + TASK_W + H_GAP
    end_y  = BASE_Y + TASK_H // 2 - EVT_H // 2
    process_elements.append(f'<bpmn:endEvent id="{end_id}" name="End"/>')
    di_shapes.append(
        f'<bpmndi:BPMNShape id="{end_id}_di" bpmnElement="{end_id}">'
        f'<dc:Bounds x="{end_x}" y="{end_y}" width="{EVT_W}" height="{EVT_H}"/>'
        f'</bpmndi:BPMNShape>'
    )
    for leaf in leaves:
        if not any(f'sourceRef="{task_ids[leaf]}"' in f for f in flows):
            lx, ly = pos[leaf]
            add_flow(task_ids[leaf], end_id,
                     (lx + TASK_W, ly + TASK_H // 2),
                     (end_x, end_y + EVT_H // 2))

    process_id = f"Process_{_sid()}"
    diagram_id = f"BPMNDiagram_{_sid()}"
    plane_id   = f"BPMNPlane_{_sid()}"

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions {BPMN_NS}
  id="Definitions_{_sid()}"
  targetNamespace="http://bpacc.bpacc.com/bpmn"
  exporter="BPACC B1"
  exporterVersion="1.0">

  <bpmn:process id="{process_id}" name="{title}" isExecutable="true">
    {chr(10).join(process_elements + flows)}
  </bpmn:process>

  <bpmndi:BPMNDiagram id="{diagram_id}">
    <bpmndi:BPMNPlane id="{plane_id}" bpmnElement="{process_id}">
      {chr(10).join(di_shapes)}
      {chr(10).join(di_edges)}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>

</bpmn:definitions>'''