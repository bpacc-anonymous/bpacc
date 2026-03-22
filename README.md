# BPACC — Business Process Aware Computing Continuum

Implementation artifacts for the paper:
**"BPACC: A Business Process Aware Architecture for Intent-Based Orchestration Across the Compute Continuum"**
Submitted to IEEE SSE 2026.

## Architecture Overview

BPACC introduces a transversal Business Process Layer over the Compute Continuum, comprising:
- **B1** — Business Intent Converter (LangGraph + Kimi K2 + ChromaDB)
- **B2** — Business Process Execution Engine (Camunda 8 / Zeebe)
- **B3** — Business Policy Repository (OPA Gatekeeper)
- **B4** — Business Communication Bus (RabbitMQ)

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Docker + Kubernetes (KubeEdge for edge tier)
- Camunda 8 Self Managed (Zeebe)
- RabbitMQ
- OPA Gatekeeper

## Installation
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
```

## Environment Variables

Create a `. the root:
```
NVIDIA_API_KEY=your_api_key
RABBITMQ_URI=amqp://user:password@host:5672/
```

## Running the Design-Time Pipeline
```bash
uv run python run.py
```

This executes:
1. Service description extraction from OCI annotations
2. Semantic standardization (SemanticGrouper)
3. TBox extension and OWL reasoning
4. Capability Profile generation
5. B1 intent matching and BPMN generation

## Ontology Files

| File | Description |
|------|-------------|
| `design_time/bpacc_t0.ttl` | Base TBox T0 (SOSA-extended) |
| `design_time/bpacc_tn.ttl` | Extended TBox Tn |
| `design_time/bpacc_t0_converted.owl` | OWL version for Protégé/HermiT |

## Output

Generated BPMN files are stored in `output/` (excluded from this repo).
Capability Catalog is available in `design_time/capability_catalog_standardized.json`.

## Note on B3

B3 (OPA Gatekeeper) is modeled as a Validating Admission Webhook.
Rego policy files are not included in this release.
The formal properties of fvalidate are established by construction in theaper.


## Dependencies

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
No `pyproject.toml` is included in this release.

Main dependencies to install manually:
```bash
uv pip install langgraph chromadb pyzeebe pika owlready2 rdflib requests python-dotenv
```


## Note on B3 — Business Policy Repository

B3 (OPA Gatekeeper as Validating Admission Webhook with Rego rules) is not included
in this release. Its formal properties are established by construction in the paper (Section III-C3)
and evaluated qualitatively in Section IV-E.
