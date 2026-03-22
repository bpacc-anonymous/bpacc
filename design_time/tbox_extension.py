"""
BPACC - Étape 3b : Extension dynamique du TBox
Section III-B(3) du papier : Tₙ = T₀ ∪ Kₙ

À partir de :
  - bpacc_t0.ttl                        : TBox de base validé sous Protégé
  - capability_catalog_standardized.json : 13 classes abstraites + super-classes

Le script :
  1. Charge T₀ via owlready2 (conversion Turtle → RDF/XML via rdflib)
  2. Vérifie la cohérence de T₀ avant extension
  3. Pour chaque classe abstraite dans Kₙ :
     a. Crée la sous-classe OWL avec subsomption vers la super-classe correcte
     b. Hérite automatiquement les axiomes de placement par subsomption
     c. Encode les contraintes de gouvernance et QoS depuis M(s)
     d. Vérifie Tₙ ⊭ ⊥ via HermiT après chaque ajout
     e. Sur inconsistance → retire la classe, préserve Tₙ₋₁
  4. Exécute un test de contradiction formel (Section III garantie by design)
  5. Sérialise bpacc_tn.ttl

Outputs :
  - bpacc_tn.ttl                 : TBox étendu Tₙ
  - tbox_extension_report.json   : rapport admis/rejetés + test de contradiction
    → convertible en DataFrame : pd.DataFrame(report["admitted"] + report["rejected"])
"""

import json
import sys
import os
import time
import copy
from datetime import datetime
from pathlib import Path

# ── owlready2 ────────────────────────────────────────────────────────────────
try:
    from owlready2 import (
        get_ontology, sync_reasoner_hermit,
        types, destroy_entity
    )
    import owlready2
    OWLREADY2_AVAILABLE = True
except ImportError:
    OWLREADY2_AVAILABLE = False
    print("✗ owlready2 non installé : uv pip install owlready2")
    sys.exit(1)

# ── Constantes ────────────────────────────────────────────────────────────────

T0_PATH      = "bpacc_t0.ttl"
CATALOG_PATH = "capability_catalog_standardized.json"
TN_PATH      = "bpacc_tn.ttl"
REPORT_PATH  = "tbox_extension_report.json"

BPACC_NS = "http://bpacc.bpacc.com/ontology#"

# Mapping super-classe TBox (Ss/Sa/Sp/Sd/Si) → nom de classe OWL dans T₀
SUPERCLASS_MAP = {
    "Ss": "SensingService",
    "Sa": "ActuationService",
    "Sp": "ProcessingService",
    "Sd": "StorageService",
    "Si": "InteractionService",
}

# ── Services de test pour la validation de contradiction ──────────────────────
# Ces services fictifs violent intentionnellement les axiomes de placement
# pour valider la garantie formelle du papier (Section III)
CONTRADICTION_TESTS = [
    {
        "class":       "TextToSpeech_BadPlacement_Service",
        "super_class": "Sa",                          # ActuationService → allValuesFrom EndpointNode
        "placement":   ["edge", "cloud"],             # VIOLATION : edge/cloud interdit pour Sa
        "data_locality": ["edge-only"],
        "latencies":   ["50ms"],
        "implementations": ["TextToSpeech_FakeImpl"],
        "expected":    "rejected",
        "reason":      "ActuationService allValuesFrom EndpointNode violated by edge/cloud placement",
    },
    {
        "class":       "OCR_GoodPlacement_Service",
        "super_class": "Sp",                          # ProcessingService → Edge ∪ Cloud
        "placement":   ["edge", "cloud"],             # CONFORME
        "data_locality": ["edge-only"],
        "latencies":   ["50ms"],
        "implementations": ["OCR_FakeImpl"],
        "expected":    "admitted",
        "reason":      "ProcessingService allValuesFrom EdgeNode ⊔ CloudNode — placement conforme",
    },
    {
        "class":       "Processing_EndpointOnly_Service",
        "super_class": "Sp",                          # ProcessingService → Edge ∪ Cloud uniquement
        "placement":   ["endpoint"],                  # VIOLATION : endpoint interdit pour Sp
        "data_locality": ["none"],
        "latencies":   ["standard"],
        "implementations": ["Processing_FakeImpl"],
        "expected":    "rejected",
        "reason":      "ProcessingService allValuesFrom EdgeNode ⊔ CloudNode violated by endpoint placement",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# CHARGEMENT T₀
# ══════════════════════════════════════════════════════════════════════════════

def load_t0(t0_path: str):
    """
    owlready2 ne supporte pas Turtle nativement.
    Conversion préalable Turtle → RDF/XML via rdflib, puis chargement owlready2.
    """
    import rdflib

    abs_path = Path(t0_path).resolve()
    if not abs_path.exists():
        raise FileNotFoundError(f"T₀ introuvable : {abs_path}")

    owl_path = str(abs_path).replace(".ttl", "_converted.owl")
    print(f"  Conversion Turtle → RDF/XML via rdflib...")
    g = rdflib.Graph()
    g.parse(str(abs_path), format="turtle")
    g.serialize(destination=owl_path, format="xml")
    print(f"  ✓ Converti : {owl_path}")

    iri  = f"file://{owl_path}"
    onto = get_ontology(iri).load()
    print(f"  ✓ T₀ chargé — {len(list(onto.classes()))} classes")
    return onto


# ══════════════════════════════════════════════════════════════════════════════
# VÉRIFICATION DE COHÉRENCE HermiT
# ══════════════════════════════════════════════════════════════════════════════

def check_consistency(onto) -> tuple:
    """
    Lance HermiT via owlready2.
    Retourne (is_consistent: bool, latency_ms: float, error: str|None)

    Section III-B(3) : vérifier Tₙ ⊭ ⊥
    Sur inconsistance → rejeter, préserver Tₙ₋₁
    """
    t = time.perf_counter()
    try:
        with onto:
            sync_reasoner_hermit(infer_property_values=True)
        latency_ms = round((time.perf_counter() - t) * 1000, 2)

        unsatisfiable = list(owlready2.default_world.inconsistent_classes())
        if unsatisfiable:
            names = [c.name for c in unsatisfiable if hasattr(c, 'name')]
            return False, latency_ms, f"Classes insatisfiables : {names}"

        return True, latency_ms, None

    except Exception as e:
        latency_ms = round((time.perf_counter() - t) * 1000, 2)
        error_msg  = str(e)
        if "inconsistent" in error_msg.lower() or "unsatisfiable" in error_msg.lower():
            return False, latency_ms, error_msg
        return False, latency_ms, f"Erreur HermiT : {error_msg}"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_superclass(onto, super_cls_code: str):
    class_name = SUPERCLASS_MAP.get(super_cls_code)
    if not class_name:
        raise ValueError(f"Super-classe inconnue : {super_cls_code}")
    cls = onto.search_one(iri=f"{BPACC_NS}{class_name}")
    if cls is None:
        raise ValueError(f"Classe OWL introuvable dans T₀ : {class_name}")
    return cls


def build_service_metadata(services: list, abstract_class: str) -> dict:
    placements    = set()
    data_locality = set()
    latencies     = set()
    inputs        = []  # Ic — depuis M(s).inputs de l'implémentation de référence

    for s in services:
        if s.get("abstract_class") == abstract_class:
            for p in s.get("placement", []):
                placements.add(p)
            gov = s.get("governance", {})
            if gov.get("data_locality"):
                data_locality.add(gov["data_locality"])
            qos = s.get("qos", {})
            if qos.get("latency"):
                latencies.add(qos["latency"])
            # Ic : inputs de la première implémentation de référence
            if not inputs and s.get("inputs"):
                inputs = s["inputs"]

    # ── Dérivation déterministe targetNode depuis M(s).placement ────────────────
    # Règle : on cible le tier le plus bas disponible dans placement
    # endpoint seul        → EndpointNode  (actuation physique)
    # edge présent         → EdgeNode      (traitement local)
    # cloud seul           → CloudNode     (traitement distant)
    # Cette règle est reproductible depuis M(s) sans information supplémentaire.
    if "endpoint" in placements and len(placements) == 1:
        target_node = "EndpointNode"
    elif "edge" in placements:
        target_node = "EdgeNode"
    else:
        target_node = "CloudNode"

    # ── Dérivation déterministe latencyProfile depuis M(s).qos.latency ──────────
    # Règle : mapping depuis les valeurs brutes M(s) vers le vocabulaire T₀
    # "50ms", "100ms", "low"  → "critical"   (contrainte temps-réel)
    # "standard"              → "standard"   (contrainte normale)
    # autres                  → "best-effort" (pas de contrainte stricte)
    # Cette règle est reproductible depuis M(s) sans information supplémentaire.
    latency_raw = next(iter(latencies), "standard")
    if latency_raw in ("50ms", "100ms", "low"):
        latency_profile = "critical"
    elif latency_raw == "standard":
        latency_profile = "standard"
    else:
        latency_profile = "best-effort"

    return {
        "placements":      sorted(placements),
        "data_locality":   sorted(data_locality),
        "latencies":       sorted(latencies),
        "latency_profile": latency_profile,
        "target_node":     target_node,
        "inputs":          inputs,
    }


def add_class_to_onto(onto, class_name: str, parent_cls, meta: dict,
                      implementations: list) -> object:
    """
    Crée une nouvelle classe OWL dans l'ontologie et encode le Capability Profile
    ⟨ID, Ic, Qc, Pc⟩ via les propriétés structurées de T₀ v0.2.0.

    - Ic : hasInputParameter + paramName pour chaque input de M(s)
    - Qc : latencyProfile
    - Pc : dataLocality, targetNode, region (eu par défaut)
    """
    # Récupère les propriétés structurées depuis T₀
    latency_profile_prop = onto.search_one(iri=f"{BPACC_NS}latencyProfile")
    data_locality_prop   = onto.search_one(iri=f"{BPACC_NS}dataLocality")
    target_node_prop     = onto.search_one(iri=f"{BPACC_NS}targetNode")
    region_prop          = onto.search_one(iri=f"{BPACC_NS}region")
    has_input_prop       = onto.search_one(iri=f"{BPACC_NS}hasInputParameter")
    param_name_prop      = onto.search_one(iri=f"{BPACC_NS}paramName")
    param_type_prop      = onto.search_one(iri=f"{BPACC_NS}paramType")
    input_param_cls      = onto.search_one(iri=f"{BPACC_NS}InputParameter")
    target_node_cls      = onto.search_one(iri=f"{BPACC_NS}{meta['target_node']}")

    with onto:
        new_cls = types.new_class(class_name, (parent_cls,))
        new_cls.namespace = onto.get_namespace(BPACC_NS)

        # Qc — latencyProfile
        if latency_profile_prop and meta.get("latency_profile"):
            new_cls.latencyProfile = [meta["latency_profile"]]

        # Pc — dataLocality
        if data_locality_prop and meta.get("data_locality"):
            new_cls.dataLocality = [meta["data_locality"][0]]

        # Pc — region (eu par défaut — contextualisable par B1 depuis le BPMN)
        if region_prop:
            new_cls.region = ["eu"]

        # Pc — targetNode (classe OWL, pas une chaîne)
        if target_node_prop and target_node_cls:
            new_cls.targetNode = [target_node_cls]

        # Ic — hasInputParameter pour chaque input de M(s)
        if has_input_prop and input_param_cls and meta.get("inputs"):
            for input_name in meta["inputs"]:
                param_instance = input_param_cls()
                if param_name_prop:
                    param_instance.paramName = [input_name]
                if param_type_prop:
                    param_instance.paramType = ["string"]
                new_cls.hasInputParameter.append(param_instance)

        # Annotation implementations — conservée pour traçabilité
        new_cls.comment.append(
            f"implementations: {', '.join(implementations)}"
        )

    return new_cls


# ══════════════════════════════════════════════════════════════════════════════
# EXTENSION DYNAMIQUE Tₙ = T₀ ∪ Kₙ
# ══════════════════════════════════════════════════════════════════════════════

def extend_tbox(onto, abstract_classes: dict, services: list) -> dict:
    """
    Étend T₀ avec les classes abstraites de Kₙ.
    Vérifie Tₙ ⊭ ⊥ après chaque ajout.
    Sur inconsistance → retire la classe, préserve Tₙ₋₁.
    """
    report = {
        "admitted":   [],
        "rejected":   [],
        "t0_classes": len(list(onto.classes())),
    }

    print(f"\n  Extension de T₀ avec {len(abstract_classes)} classes abstraites...")

    for abstract_class_name, implementations in abstract_classes.items():
        print(f"\n  → Ajout : {abstract_class_name}")

        super_cls_code = None
        for s in services:
            if s.get("abstract_class") == abstract_class_name:
                super_cls_code = s.get("super_class")
                break

        if not super_cls_code:
            print(f"    ✗ super_class introuvable — ignoré")
            report["rejected"].append({
                "class":    abstract_class_name,
                "reason":   "super_class_not_found",
                "admitted": False,
                "test_type": "nominal",
            })
            continue

        try:
            parent_cls = get_superclass(onto, super_cls_code)
        except ValueError as e:
            print(f"    ✗ {e}")
            report["rejected"].append({
                "class":    abstract_class_name,
                "reason":   str(e),
                "admitted": False,
                "test_type": "nominal",
            })
            continue

        meta    = build_service_metadata(services, abstract_class_name)
        new_cls = add_class_to_onto(onto, abstract_class_name, parent_cls,
                                    meta, implementations)

        print(f"    parent={parent_cls.name}  "
              f"targetNode={meta['target_node']}  "
              f"latency={meta['latency_profile']}  "
              f"data_locality={meta['data_locality']}  "
              f"inputs={meta['inputs']}")
        print(f"    ⏳ HermiT vérifie Tₙ ⊭ ⊥ ...")

        is_consistent, latency_ms, error = check_consistency(onto)

        if is_consistent:
            print(f"    ✓ Cohérent — {latency_ms} ms")
            report["admitted"].append({
                "class":           abstract_class_name,
                "parent":          parent_cls.name,
                "super_cls_code":  super_cls_code,
                "implementations": implementations,
                "metadata":        meta,
                "hermit_ms":       latency_ms,
                "admitted":        True,
                "test_type":       "nominal",
            })
        else:
            print(f"    ✗ Inconsistance : {error}")
            print(f"    → Classe rejetée, Tₙ₋₁ préservé")
            with onto:
                destroy_entity(new_cls)
            report["rejected"].append({
                "class":           abstract_class_name,
                "parent":          parent_cls.name,
                "super_cls_code":  super_cls_code,
                "reason":          error,
                "hermit_ms":       latency_ms,
                "admitted":        False,
                "test_type":       "nominal",
            })

    report["tn_classes"]   = len(list(onto.classes()))
    report["kn_admitted"]  = len(report["admitted"])
    report["kn_rejected"]  = len(report["rejected"])
    return report


# ══════════════════════════════════════════════════════════════════════════════
# TEST DE CONTRADICTION FORMELLE
# Valide la garantie "Architectural Compliance Guarantee by design"
# Section III du papier
# ══════════════════════════════════════════════════════════════════════════════

def run_contradiction_tests(onto, report: dict) -> list:
    """
    Injecte des services fictifs avec des placements intentionnellement
    non conformes pour valider que HermiT détecte les violations d'axiomes.

    Résultat attendu par test :
      - expected='rejected' → HermiT doit détecter une inconsistance ✓
      - expected='admitted' → HermiT doit valider la cohérence ✓
    """
    print(f"\n{'═'*60}")
    print(f"  TEST DE CONTRADICTION FORMELLE")
    print(f"  Validation : Architectural Compliance Guarantee by design")
    print(f"  Section III du papier")
    print(f"{'═'*60}")

    test_results = []

    for test in CONTRADICTION_TESTS:
        class_name = test["class"]
        super_cls_code = test["super_class"]
        expected = test["expected"]

        print(f"\n  ▶ Test : {class_name}")
        print(f"    super_class={super_cls_code}  "
              f"placement={test['placement']}  "
              f"expected={expected.upper()}")
        print(f"    axiome testé : {test['reason']}")

        try:
            parent_cls = get_superclass(onto, super_cls_code)
        except ValueError as e:
            print(f"    ✗ Setup error : {e}")
            test_results.append({
                **test,
                "actual":    "error",
                "passed":    False,
                "hermit_ms": 0,
                "error":     str(e),
                "test_type": "contradiction",
                "admitted":  False,
            })
            continue

        meta = {
            "placements":      test["placement"],
            "data_locality":   test["data_locality"],
            "latencies":       test["latencies"],
            # Dérivation déterministe depuis placement — même règle que build_service_metadata
            "target_node":     (
                "EndpointNode" if test["placement"] == ["endpoint"]
                else "EdgeNode" if "edge" in test["placement"]
                else "CloudNode"
            ),
            "latency_profile": (
                "critical" if test["latencies"][0] in ("50ms", "100ms", "low")
                else "standard" if test["latencies"][0] == "standard"
                else "best-effort"
            ),
            "inputs":          [],
        }

        new_cls = add_class_to_onto(onto, class_name, parent_cls,
                                    meta, test["implementations"])

        print(f"    ⏳ HermiT vérifie Tₙ ⊭ ⊥ ...")
        is_consistent, latency_ms, error = check_consistency(onto)

        actual = "admitted" if is_consistent else "rejected"
        passed = actual == expected

        status_icon = "✅" if passed else "❌"
        print(f"    {status_icon} Résultat : {actual.upper()}  "
              f"(attendu : {expected.upper()})  "
              f"— {latency_ms} ms  "
              f"{'PASS' if passed else 'FAIL'}")

        if not is_consistent:
            print(f"    Raison HermiT : {error}")

        # Retire la classe de test pour ne pas polluer Tₙ final
        with onto:
            destroy_entity(new_cls)
        print(f"    → Classe de test retirée de Tₙ")

        test_results.append({
            "class":           class_name,
            "super_class":     super_cls_code,
            "parent":          parent_cls.name,
            "placement":       test["placement"],
            "data_locality":   test["data_locality"],
            "axiom_tested":    test["reason"],
            "expected":        expected,
            "actual":          actual,
            "passed":          passed,
            "hermit_ms":       latency_ms,
            "hermit_error":    error,
            "admitted":        is_consistent,
            "test_type":       "contradiction",
        })

    # Résumé
    n_pass = sum(1 for t in test_results if t["passed"])
    n_fail = sum(1 for t in test_results if not t["passed"])
    print(f"\n  {'─'*50}")
    print(f"  Résultats tests de contradiction : "
          f"{n_pass}/{len(test_results)} PASS  |  {n_fail} FAIL")

    guarantee_validated = n_fail == 0
    print(f"  Garantie formelle BPACC : "
          f"{'✅ VALIDÉE' if guarantee_validated else '❌ NON VALIDÉE'}")

    report["contradiction_tests"]        = test_results
    report["guarantee_validated"]        = guarantee_validated
    report["contradiction_tests_pass"]   = n_pass
    report["contradiction_tests_fail"]   = n_fail

    return test_results


# ══════════════════════════════════════════════════════════════════════════════
# SÉRIALISATION Tₙ
# ══════════════════════════════════════════════════════════════════════════════

def serialize_tn(onto, tn_path: str) -> None:
    try:
        import rdflib
        tmp_xml = tn_path.replace(".ttl", "_tmp.owl")
        onto.save(file=tmp_xml, format="rdfxml")
        g = rdflib.Graph()
        g.parse(tmp_xml, format="xml")
        g.serialize(destination=tn_path, format="turtle")
        os.remove(tmp_xml)
        print(f"  ✓ Tₙ sérialisé en Turtle : {tn_path}")
    except ImportError:
        tn_owl = tn_path.replace(".ttl", ".owl")
        onto.save(file=tn_owl, format="rdfxml")
        print(f"  ✓ Tₙ sérialisé en RDF/XML : {tn_owl}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n=== BPACC — Extension dynamique TBox (Étape 3b) ===")
    print(f"    Tₙ = T₀ ∪ Kₙ\n")

    # ── Chargement catalog ────────────────────────────────────────────────────
    try:
        with open(CATALOG_PATH, encoding="utf-8") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        print(f"✗ Catalog introuvable : {CATALOG_PATH}", file=sys.stderr)
        sys.exit(1)

    abstract_classes = catalog["abstract_classes"]
    services         = catalog["services"]
    print(f"  {len(abstract_classes)} classes abstraites chargées depuis {CATALOG_PATH}")

    # ── Chargement T₀ ────────────────────────────────────────────────────────
    print(f"\n─── Chargement T₀ ───")
    onto = load_t0(T0_PATH)

    # ── Vérification T₀ ──────────────────────────────────────────────────────
    print(f"\n─── Vérification cohérence T₀ ───")
    is_consistent, latency_ms, error = check_consistency(onto)
    if not is_consistent:
        print(f"✗ T₀ inconsistant avant extension : {error}")
        sys.exit(1)
    print(f"  ✓ T₀ cohérent — HermiT {latency_ms} ms")

    # ── Extension nominale ────────────────────────────────────────────────────
    print(f"\n─── Extension Tₙ = T₀ ∪ Kₙ ───")
    t_total = time.perf_counter()
    report  = extend_tbox(onto, abstract_classes, services)

    # ── Tests de contradiction ────────────────────────────────────────────────
    run_contradiction_tests(onto, report)

    total_ms = round((time.perf_counter() - t_total) * 1000, 2)

    # ── Sérialisation Tₙ ──────────────────────────────────────────────────────
    print(f"\n─── Sérialisation Tₙ ───")
    serialize_tn(onto, TN_PATH)

    # ── Rapport ───────────────────────────────────────────────────────────────
    report_full = {
        "meta": {
            "generated_at":    datetime.utcnow().isoformat() + "Z",
            "t0_path":         T0_PATH,
            "catalog_path":    CATALOG_PATH,
            "tn_path":         TN_PATH,
            "total_latency_ms": total_ms,
        },
        "summary": {
            "t0_classes":                report["t0_classes"],
            "tn_classes":                report["tn_classes"],
            "kn_admitted":               report["kn_admitted"],
            "kn_rejected":               report["kn_rejected"],
            "contradiction_tests_pass":  report.get("contradiction_tests_pass", 0),
            "contradiction_tests_fail":  report.get("contradiction_tests_fail", 0),
            "guarantee_validated":       report.get("guarantee_validated", False),
        },
        # ── Sections DataFrame-ready ──────────────────────────────────────────
        # pd.DataFrame(report["admitted"])
        "admitted": report["admitted"],
        # pd.DataFrame(report["rejected"])
        "rejected": report["rejected"],
        # pd.DataFrame(report["contradiction_tests"])
        "contradiction_tests": report.get("contradiction_tests", []),
        # pd.DataFrame(report["admitted"] + report["rejected"] +
        #              report["contradiction_tests"])  → vue complète
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_full, f, indent=2, ensure_ascii=False)

    # ── Résumé console ────────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  RÉSUMÉ FINAL")
    print(f"{'═'*60}")
    print(f"  T₀ classes              : {report['t0_classes']}")
    print(f"  Kₙ admises              : {report['kn_admitted']}")
    print(f"  Kₙ rejetées             : {report['kn_rejected']}")
    print(f"  Tₙ classes              : {report['tn_classes']}")
    print(f"  Tests contradiction     : "
          f"{report.get('contradiction_tests_pass',0)} PASS / "
          f"{report.get('contradiction_tests_fail',0)} FAIL")
    print(f"  Garantie formelle       : "
          f"{'✅ VALIDÉE' if report.get('guarantee_validated') else '❌ NON VALIDÉE'}")
    print(f"  Latence totale          : {total_ms} ms")

    print(f"\n✅ Tₙ sérialisé        → {TN_PATH}")
    print(f"✅ Rapport d'extension → {REPORT_PATH}")

    print(f"\n  💡 DataFrame :")
    print(f"     import pandas as pd, json")
    print(f"     r = json.load(open('{REPORT_PATH}'))")
    print(f"     df_nominal      = pd.DataFrame(r['admitted'] + r['rejected'])")
    print(f"     df_contradiction = pd.DataFrame(r['contradiction_tests'])")
    print(f"     df_all           = pd.concat([df_nominal, df_contradiction])")


if __name__ == "__main__":
    main()