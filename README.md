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
uv pip install langgraph chromadb pyzeebe pika owlready2 rdflib requests python-dotenv
```

## Environment Variables

Create a `.env` file at the root:
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

## B3 — Business Policy Repository

B3 is implemented as an OPA Gatekeeper Validating Admission Webhook evaluating Rego policies.
Rego policy files are included in this repo under `b3/`.
The formal properties of `fvalidate` are established by construction in the paper (Section III-C3)
and evaluated qualitatively in Section IV-E.

## Dependencies

Main dependencies:
```bash
uv pip install langgraph chromadb pyzeebe pika owlready2 rdflib requests python-dotenv
```

Note: no `pyproject.toml` is included in this release.