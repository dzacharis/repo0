# Developer Experience — Batteries Included Platform

> **TL;DR** — A business developer on this platform writes only value code: a Python class that
> performs a domain-specific operation (a *transform*). Every cross-cutting concern — authentication,
> rate limiting, audit logging, pub/sub, secret management, TLS, observability — is handled by
> no-code middleware configured at the platform level.

See [diagrams.md](./diagrams.md) for visual representations of the concepts described here
(diagrams 10–14).

---

## The Core Principle

```text
You write this ──────────────────────────────────────┐
                                                      │
  class DomainToIP(BaseTransform):                    │
      name = "DomainToIP"                             │
      meta = TransformMeta(                           │
          display_name="Domain To IP Address",        │
          input_entity="maltego.Domain",              │
      )                                               │
                                                      │
      def run(self, entity, request):                 │
          answers = dns.resolver.resolve(             │
              entity.value, "A"                       │   ← Your entire
          )                                           │     contribution
          response = TransformResponse()              │
          for r in answers:                           │
              response.add_entity(                    │
                  "maltego.IPv4Address",              │
                  {"value": str(r)}                   │
              )                                       │
          return response                             │
                                                      │
You get this for free ──────────────────────────────┐ │
                                                     │ │
  ✔ TLS termination                 (Kong)           │ │
  ✔ OIDC / JWT authentication       (Kong + KC)      │ │
  ✔ Rate limiting (cluster-wide)    (Kong + Redis)   │ │
  ✔ CORS headers                    (Kong)           │ │
  ✔ Distributed request tracing     (Dapr + Zipkin)  │ │
  ✔ Structured audit log            (Dapr → OS)      │ │
  ✔ Secret injection                (Dapr)           │ │
  ✔ Pub/Sub fan-out                 (Dapr)           │ │
  ✔ State management                (Dapr)           │ │
  ✔ Auto-scaling                    (HPA)            │ │
  ✔ Transform auto-discovery        (Hub manifest)   │ │
  ✔ Client self-registration        (Keycloak API)   │ │
```

---

## Layer Model

| Layer | Who configures | What it does |
|-------|---------------|-------------|
| **4 — Business code** | Developer | Transform logic, data-source calls, entity mapping |
| **3 — Platform services** | Platform team (once) | FastAPI shell, manifest API, client registry |
| **2 — Middleware** | Ops / Helm values | Kong, Dapr, Keycloak, OpenSearch — all no-code |
| **1 — Operators** | Ops / GitOps | cert-manager, Dapr Operator, OPA/Gatekeeper |
| **0 — Infrastructure** | Terraform | K8s cluster, managed databases, networking |

A developer works exclusively in layer 4. Layers 0–3 are owned by ops and change rarely.

---

## Adding a New Transform — Step by Step

### 1. Write the class

Create `src/transform-hub/transforms/my_transform.py`:

```python
from .base import BaseTransform, TransformMeta
from ..models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from . import register

@register
class MyTransform(BaseTransform):
    name = "MyTransform"
    meta = TransformMeta(
        display_name="My Custom Transform",
        description="Does something useful",
        input_entity="maltego.Domain",
        author="Your Name",
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        response = TransformResponse()
        # ... your logic here ...
        return response
```

### 2. Add dependencies (if any)

```bash
# src/transform-hub/requirements.txt
my-new-library==1.2.3
```

### 3. Push

```bash
git add src/transform-hub/transforms/my_transform.py
git commit -m "feat: add MyTransform"
git push
```

The CI pipeline automatically:

- Runs unit tests
- Builds and scans the Docker image
- Deploys via rolling update
- The `@register` decorator makes the transform appear in `GET /api/v2/manifest` immediately

### 4. Import in Maltego

In Maltego Desktop:

1. `Transform Hub → Add Server`
2. Enter `https://api.example.com/transforms` and your bearer token
3. All transforms appear — no manual registration

---

## What You Never Have to Write

### Authentication

You do **not** write JWT parsing code. Kong validates the token before the request reaches your
container. The Transform Hub's `verify_token` dependency (called once at the router layer) confirms
scope. Your `run()` method receives an already-authenticated request.

### Rate Limiting

You do **not** write throttle logic. The `rate-limiting` KongPlugin is applied at the Ingress level:

```yaml
# k8s/kong/plugins/rate-limiting.yaml
config:
  second: 10
  minute: 100
  policy: redis          # cluster-wide counter, not per-pod
```

One YAML change affects all transforms simultaneously.

### Audit Logging

You do **not** call a logging library. Dapr's output binding writes a structured event to
OpenSearch on every invocation:

```python
# called by the router, not by individual transforms
await dapr_client.invoke_binding("audit-log", "create", audit_payload)
```

Business code never touches this path.

### Secret Access

You do **not** read environment variables manually or import secret libraries. Dapr injects secrets
as environment variables at pod start:

```yaml
# k8s/dapr/components/secretstore.yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: kubernetes
spec:
  type: secretstores.kubernetes
```

Your code reads `os.environ["MY_API_KEY"]` — which was injected by Dapr from K8s Secrets, Vault,
or cloud secret managers, depending on the environment overlay.

### Pub/Sub

If a transform result needs to fan out to other services, publish via the Dapr API:

```python
# One call — Dapr handles broker, retry, dead-letter, subscriber discovery
await dapr_client.publish_event("pubsub", "transform-results", result.dict())
```

No Kafka client, no connection strings, no consumer group management.

---

## Swapping Backends Without Code Changes

Because Dapr uses named components, a backing service can be replaced by updating a YAML file:

| Capability | Default | Swap to |
|-----------|---------|---------|
| State store | Redis | PostgreSQL, CosmosDB, DynamoDB |
| Pub/Sub | Redis Streams | Kafka, Azure Service Bus, GCP Pub/Sub |
| Secret store | K8s Secrets | HashiCorp Vault, Azure Key Vault, AWS Secrets Manager |
| Audit log | OpenSearch binding | Any Dapr output binding |

Zero application code changes required.

---

## Operational Concerns Handled by the Platform

| Concern | Handled by | Config location |
|---------|-----------|----------------|
| TLS certificate issuance + renewal | cert-manager | `k8s/cert-manager/cluster-issuer.yaml` |
| Pod auto-scaling | HPA | `k8s/apps/*/hpa.yaml` |
| Pod disruption (zero-downtime updates) | PodDisruptionBudget | per deployment |
| Network policy enforcement | OPA Gatekeeper | `policies/deployments.rego` |
| Image vulnerability scanning | Trivy (CI) | `.github/workflows/security.yaml` |
| Secret scanning in code | Gitleaks (CI) | `.github/workflows/security.yaml` |
| mTLS between services | Dapr Sentry CA | `k8s/dapr/dapr-configuration.yaml` |
| Log retention | OpenSearch ISM | `k8s/opensearch/index-policies.yaml` |
| Multi-cloud portability | Kustomize overlays + Terraform modules | `k8s/cloud-overlays/*/`, `terraform/*/` |
