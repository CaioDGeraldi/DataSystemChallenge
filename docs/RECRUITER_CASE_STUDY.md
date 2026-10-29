# Retorna — Technical Case Study

**Role of the repository:** a collaborative software engineering project developed for the Data System Challenge. This document explains the engineering problems visible in the code; it is not a statement that a single contributor implemented every feature.

## The product problem

A multi-company loyalty system needs to accept purchase events from external business systems, apply tenant/store-specific rules, maintain a reliable points history, and avoid issuing or spending the same points twice. A dashboard alone cannot demonstrate correctness: the central challenge is preserving business invariants when clients retry requests or requests arrive concurrently.

Retorna models companies and stores, point lots, customer balances, campaigns, loyalty tiers, redemptions and reversals in a modular Django application backed by PostgreSQL.

## Design choices with source evidence

### 1. Transactional, idempotent redemption

**Problem:** an integration may retry a redemption request, or two requests may try to spend the same balance.

**Approach in the code:** [`apps/fidelidade/resgates.py`](../apps/fidelidade/resgates.py) wraps redemption in `transaction.atomic`, derives a stable advisory-lock key from the store and external identifier, checks prior requests for idempotency, and uses row locks to serialize balance-changing operations. It consumes point lots in expiry order (FEFO). Database constraints complement application-level checks.

**Evidence:** [`test_concorrencia_resgates.py`](../apps/fidelidade/test_concorrencia_resgates.py) includes cases for repeated payloads, conflicting retries, concurrent spending attempts, and independently progressing customers. These tests explicitly require a real PostgreSQL database.

### 2. Separation of business rules and API surface

**Problem:** business rules must behave consistently whether an operation comes from an integration endpoint or a server-rendered interface.

**Approach in the code:** the project separates Django apps such as `empresas`, `fidelidade`, `clientes`, `api` and `auditoria`. Services implement domain operations; DRF exposes the integration surface through versioned URLs.

**Evidence:** [`apps/fidelidade/`](../apps/fidelidade/), [`apps/api/`](../apps/api/) and the [API contract](API.md) (in Portuguese).

### 3. Verification and delivery checks

**Problem:** regressions in migrations, API schemas and UI assets can invalidate a working integration.

**Approach in the code:** [GitHub Actions](../.github/workflows/ci.yml) runs separate backend/frontend jobs. Backend checks the dependency lockfile, Django configuration, pending migrations, OpenAPI schema and the complete Django test suite against a PostgreSQL service. Frontend checks its build and interface validators.

**Evidence:** [successful GitHub Actions execution, 28 September 2026](https://github.com/CaioDGeraldi/DataSystemChallenge/actions/runs/36492776096). A historical successful run is not a guarantee about later commits.

## Architecture snapshot

```text
External sales / commerce systems
              |
        Versioned REST API
              |
      Django business services
        /       |        \
   Companies  Loyalty   Customers
        \       |        /
            PostgreSQL
              |
        Audit and history

Django templates + frontend assets
        share domain services
```

The system is designed as a **modular monolith**, not a set of independently deployed microservices. This choice keeps application transactions and domain consistency within one deployable backend.

## How to review the project

1. Start with the [root README](../README.md) and its standalone development instructions.
2. Read the [redemption implementation](../apps/fidelidade/resgates.py) and [concurrency tests](../apps/fidelidade/test_concorrencia_resgates.py).
3. Review the [CI workflow](../.github/workflows/ci.yml) and its execution history.
4. Consult the [architecture documentation](ARQUITETURA_PRODUTO.md), [data model](MODELAGEM_DE_DADOS.md) and [API specification](API.md). These deeper reference documents are currently in Portuguese.
5. Review commits, pull requests and [the documented use of AI assistance](USO_DE_IA.md) when assessing contributions.

## Limits and attribution

- **Team project:** features, architecture and tests should not be attributed to one person without reviewing individual contributions.
- **AI assistance:** the team documents where AI was used and retains responsibility for decisions, review and verification. See [USO_DE_IA.md](USO_DE_IA.md).
- **Demonstration:** references to Heroku describe a demo deployment workflow, not guaranteed current availability or production customers.
- **Validation:** this case study is based on the repository implementation and a recorded successful CI run; it is not an independent security audit or a load test.

## Possible interview discussion

- Why use an advisory lock keyed by store and external redemption ID?
- How do row locks and uniqueness constraints protect different failure modes?
- Which invariants hold when requests retry or arrive simultaneously?
- Why prefer a modular monolith for the current scope?
- How would you measure contention, add observability and safely scale the API?

Be prepared to describe **your own concrete contributions** separately from the team's overall results.
