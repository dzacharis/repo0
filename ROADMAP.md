# Platform Roadmap

This file tracks ideas, planned features, and interesting extensions for the platform.
Items are grouped by theme. Each item includes a short rationale and a rough effort estimate.

> **Effort key**: XS < 1 day · S = 1–3 days · M = 1 week · L = 2–4 weeks · XL = 1+ month

---

## 🔬 Transform Library

Expanding the set of built-in OSINT and enrichment transforms available out of the box.

| # | Transform | Input → Output | Effort | Notes |
|---|-----------|---------------|--------|-------|
| T-01 | **Certificate Transparency** | Domain → TLS Cert (SANs, issuer, expiry) | S | crt.sh API or Google CT |
| T-02 | **ASN to BGP prefixes** | AS number → CIDR ranges | S | RIPE / ARIN REST API |
| T-03 | **Shodan host lookup** | IP → Open ports, banners, CVEs | S | Shodan API key required |
| T-04 | **VirusTotal domain report** | Domain / IP / Hash → Threat intel | S | VT API key required |
| T-05 | **GitHub user to repos** | Email / Username → Repos, commits, orgs | S | GitHub REST API |
| T-06 | **LinkedIn company to employees** | Company name → Person entities | M | Scraping or API; rate-limit sensitive |
| T-07 | **Passive DNS** | IP → Domains (historical A records) | S | SecurityTrails / CIRCL passiveDNS |
| T-08 | **Email to breach data** | Email → Breach records | S | HaveIBeenPwned v3 API |
| T-09 | **Domain to tech stack** | Domain → Technologies, CMS, CDN | S | BuiltWith / Wappalyzer API |
| T-10 | **IP to threat feeds** | IP → Blocklist membership (AbuseIPDB, etc.) | S | Multiple feed APIs |
| T-11 | **MITRE ATT&CK lookup** | Technique ID / Group → ATT&CK data | M | MITRE CTI TAXII or JSON |
| T-12 | **Social media profile** | Username → Accounts across platforms | M | Per-platform APIs |
| T-13 | **Document metadata** | File hash / URL → EXIF / PDF metadata | S | Apache Tika |
| T-14 | **Wayback Machine** | URL → Snapshot history | XS | Wayback Availability API |
| T-15 | **Reverse image search** | Image URL → Matching pages | M | Google Vision or TinEye |

---

## 🏗️ Platform Infrastructure

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| I-01 | **Karpenter / Cluster Autoscaler** | Node-level auto-scaling to match transform burst workloads | M |
| I-02 | **KEDA (K8s Event-Driven Autoscaling)** | Scale transform pods to zero when idle; scale on queue depth | M |
| I-03 | **Istio service mesh** (optional overlay) | Fine-grained L7 policies between namespaces if Dapr mTLS is insufficient | L |
| I-04 | **Velero backup** | Cluster-state and PVC backup to object store; disaster recovery | S |
| I-05 | **Crossplane** | Provision managed services (DB, cache) from K8s manifests instead of separate Terraform runs | L |
| I-06 | **External Secrets Operator** | Replace Dapr K8s secret store with ESO for richer sync from Vault / cloud KMS | M |
| I-07 | **ArgoCD or Flux** | Full GitOps loop: every merge to main auto-syncs cluster state | M |
| I-08 | **Multi-cluster federation** | Run transforms in geographically distributed clusters; route by latency | XL |
| I-09 | **Spot / preemptible node pools** | Run transform workloads on cheaper interruptible nodes with graceful drain | M |
| I-10 | **Network policies (Calico/Cilium)** | Namespace-level egress/ingress deny-all + allow rules; currently overlay-only | M |

---

## 🔒 Security

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| S-01 | **SLSA Level 3** | Non-forgeable build provenance; move from SLSA 1 to 3 with hermetic builds | L |
| S-02 | **Supply chain policy (Sigstore/Cosign)** | Verify image signatures before Kubernetes admission | M |
| S-03 | **Runtime threat detection (Falco)** | Detect anomalous syscall patterns in transform pods | M |
| S-04 | **mTLS for all egress** | Force outbound transform calls through a proxy that enforces mTLS (Envoy/SPIFFE) | L |
| S-05 | **Keycloak MFA enforcement** | Require TOTP / WebAuthn for admin realm; policy per-realm | S |
| S-06 | **Audit log tamper-evidence** | Hash-chain or Merkle-tree audit entries in OpenSearch for non-repudiation | M |
| S-07 | **RBAC for transforms** | Per-transform scope (`transforms:DomainToIP`) rather than global `transforms:execute` | S |
| S-08 | **Secrets versioning** | Track secret versions; auto-rotate DB passwords via Vault dynamic secrets | M |
| S-09 | **Pod Security Standards (restricted)** | Enforce `restricted` PSS across all namespaces, not just OPA rules | S |
| S-10 | **CVE SLA enforcement** | Block deploy if CRITICAL CVE is older than N days (Grype in CI as gate) | S |

---

## 👨‍💻 Developer Experience

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| D-01 | **`make new-transform` scaffold** | Generate the boilerplate class, test file, and manifest entry from a prompt | S |
| D-02 | **Local dev stack (docker-compose)** | Full platform stack on laptop — Kong, Dapr, Keycloak, Redis — for rapid iteration | M |
| D-03 | **Transform SDK package** | Publish `transform-hub-sdk` to PyPI; developers `pip install` instead of copying base classes | M |
| D-04 | **OpenAPI / AsyncAPI spec generation** | Auto-generate API specs from transform registry for third-party client code generation | S |
| D-05 | **Transform unit-test harness** | `TransformTestCase` base class with fixture entities and assertion helpers | S |
| D-06 | **Hot-reload in development** | Uvicorn `--reload` + volume mount for instant transform iteration without rebuild | XS |
| D-07 | **Transform playground UI** | Simple web UI to invoke any transform with arbitrary input, see output — no Maltego needed | M |
| D-08 | **VS Code devcontainer** | `.devcontainer/` with all tools pre-installed (kubectl, helm, terraform, poetry) | S |
| D-09 | **Transform versioning** | `v1/DomainToIP` and `v2/DomainToIP` side-by-side; clients pin to a version | M |
| D-10 | **Async transform support** | Long-running transforms (>30s) return a job ID; client polls or subscribes via Dapr pub/sub | L |

---

## 📊 Observability

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| O-01 | **Grafana dashboards** | Visual dashboards over OpenSearch data: RPS, error rates, P99 latency per transform | M |
| O-02 | **Jaeger / Tempo distributed tracing** | End-to-end trace from Kong through Hub to data source; Dapr emits OTLP spans | M |
| O-03 | **SLO / error budget** | Define per-transform SLOs (availability, latency); track error budget burn | M |
| O-04 | **Anomaly detection in OpenSearch** | ML-based alert on unusual transform invocation patterns (potential abuse) | L |
| O-05 | **Kong Analytics dashboard** | Traffic patterns, top consumers, top transforms, rate-limit hits | S |
| O-06 | **Cost attribution** | Tag K8s resource usage per transform / per client for chargeback | L |
| O-07 | **Synthetic monitoring** | Scheduled probe that runs all transforms with known-good inputs; alerts on failure | M |

---

## 🌐 Multi-Tenancy

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| MT-01 | **Per-tenant Keycloak realm** | Isolate client organizations completely; each gets its own OIDC issuer | M |
| MT-02 | **Per-tenant rate-limit quotas** | Different plans (free/pro/enterprise) with different RPS limits via Kong consumer groups | M |
| MT-03 | **Tenant-scoped transform visibility** | Some transforms visible only to specific tenants (licensed data sources) | M |
| MT-04 | **Namespace-per-tenant isolation** | Run transform pods in tenant namespaces with Calico network policies | L |
| MT-05 | **Usage metering API** | Expose per-tenant invocation counts for billing integration | M |

---

## 🤖 AI / LLM Integration

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| A-01 | **LLM-powered transform generation** | Given a description, generate a transform class skeleton using Claude API | M |
| A-02 | **Natural-language query to transform chain** | "Find all IPs for this company" → auto-chains Domain→IP, Org→Domain transforms | L |
| A-03 | **Semantic entity deduplication** | Use embeddings to detect when two entities are likely the same real-world object | L |
| A-04 | **Automated OSINT report generation** | Given a graph of entities, generate a prose report via LLM summarisation | M |
| A-05 | **Transform result explanation** | Each transform result includes a short natural-language explanation of the finding | S |

---

## 📦 Packaging / Distribution

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| P-01 | **Helm chart for the full platform** | Single `helm install platform .` deploys everything; versioned releases | L |
| P-02 | **OCI artifact for the SDK** | Publish the Python SDK as an OCI artifact alongside the container image | S |
| P-03 | **GitHub Release automation** | Tag → build → GitHub Release with SBOM, SLSA provenance, and changelog | S |
| P-04 | **Operator pattern for transforms** | CRD `Transform` resource; the operator deploys and registers transforms declaratively | XL |

---

## 📋 Process / Governance

| # | Item | Rationale | Effort |
|---|------|-----------|--------|
| G-01 | **Architecture Decision Records (ADRs)** | Formalise decisions already made (Kong, Dapr, Keycloak choices) as searchable ADRs | S |
| G-02 | **Transform review process** | PR template + checklist for new transforms: data source licence, privacy impact, rate-limit | S |
| G-03 | **Dependency update automation** | Renovate or Dependabot for Python deps, Helm chart versions, Terraform providers | S |
| G-04 | **Chaos engineering** | Scheduled Chaos Mesh experiments: pod kill, network latency, DNS failure | L |
| G-05 | **Incident response runbook** | Extend `docs/runbook.md` with transform-specific failure scenarios and recovery steps | M |
| G-06 | **SLA definition document** | Define platform SLAs for uptime, transform latency, auth availability | S |

---

## 🔌 MCP (Model Context Protocol) — Priority Track

Expose the platform as a first-class MCP server so AI assistants (Claude, Cursor, VS Code
Copilot, etc.) can invoke transforms and query the graph as native tools — no Maltego client
required.

> **Background**: [MCP](https://modelcontextprotocol.io) is the open standard for connecting
> AI models to external tools and data sources. Each transform is a natural MCP tool; the
> manifest endpoint already provides structured discovery.

| # | Item | Description | Effort |
|---|------|-------------|--------|
| MCP-01 | **MCP server endpoint in Transform Hub** | Implement `GET /mcp` (server info) and `POST /mcp` (JSON-RPC 2.0) alongside the existing Maltego API. Reuse `@register` transforms as MCP tool definitions auto-generated from `TransformMeta`. | M |
| MCP-02 | **Transform → MCP tool schema mapping** | Each transform's `TransformMeta` maps to an MCP `Tool` JSON schema: `input_entity` becomes the `inputSchema`, output entities become the return type. No transform code changes required. | S |
| MCP-03 | **Authentication via MCP `Authorization` header** | Reuse the existing Keycloak JWKS validation (`auth.py`) for MCP bearer token auth — same token, same scopes (`transforms:execute`). | S |
| MCP-04 | **MCP resource: entity graph queries** | Expose Neo4j as an MCP `Resource` — AI assistants can query `entity-graph://domain/example.com` to get all related entities as JSON without writing Cypher. | M |
| MCP-05 | **MCP resource: OpenSearch entity lookup** | Expose `entity-search://<type>/<query>` as an MCP resource backed by OpenSearch full-text search. | S |
| MCP-06 | **Claude Desktop / claude.ai config snippet** | Generate a ready-to-paste `claude_desktop_config.json` entry from the manifest endpoint so users can add the hub in one step. | XS |
| MCP-07 | **VS Code / Cursor MCP config generation** | Same as MCP-06 for editor-based MCP clients. | XS |
| MCP-08 | **Streaming MCP responses** | For long-running transforms, use MCP's streaming response format rather than blocking. Pairs with roadmap item D-10 (async transforms). | L |
| MCP-09 | **MCP server in Docker Compose** | Add `mcp-server` service to the local dev stack (D-02) so developers can test AI ↔ transform interaction on a laptop. | S |
| MCP-10 | **MCP tool versioning** | Expose `v1/DomainToIP` and `v2/DomainToIP` as distinct MCP tools when transform versioning (D-09) is implemented. | S |

### MCP Architecture (planned)

```
AI Assistant (Claude / Cursor / etc.)
        │  MCP JSON-RPC 2.0
        │  Authorization: Bearer <keycloak-token>
        ▼
  Kong Gateway  ─── rate-limit, OIDC validation ───►  Transform Hub
                                                          │
                          ┌───────────────────────────────┤
                          │                               │
                   MCP handler                   Maltego handler
                  /mcp  (new)                  /api/v2/transforms (existing)
                          │
              ┌───────────┴───────────┐
              │                       │
        Tools (transforms)      Resources (graph/search)
    @register → Tool schema     entity-graph://...
                                entity-search://...
```

---

## Done ✅

Items from the initial roadmap that have been implemented.

| Item | Completed |
|------|-----------|
| Kubernetes base infrastructure (Kong, Dapr, Keycloak, cert-manager) | ✅ |
| Multi-cloud Terraform (GCP, AWS, Azure, Rancher) | ✅ |
| Kustomize overlays (base, dev, prod) | ✅ |
| OPA / Conftest security policies | ✅ |
| Segregated CI/CD (security / infrastructure / applications) | ✅ |
| OpenSearch logging with Fluentbit | ✅ |
| Maltego Transform Hub (iTDS replacement) | ✅ |
| JWT authentication via Keycloak JWKS | ✅ |
| Transform auto-discovery via `@register` decorator | ✅ |
| Client self-registration via Keycloak Admin API | ✅ |
| Docs CI pipeline (lint, links, mermaid, spell, coverage) | ✅ |
| Architecture diagrams (platform, auth, Dapr, CI/CD, clouds, Maltego) | ✅ |
| Separation-of-concerns diagrams (DX philosophy) | ✅ |
| Managed ingestion to OpenSearch + Neo4j (network-isolated, schema-driven) | ✅ |
| Bill of Materials (SBOM companion) | ✅ |
| Developer onboarding guide | ✅ |
| Admin / maintainer onboarding guide | ✅ |
