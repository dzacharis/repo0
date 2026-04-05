# Kubernetes Platform Infrastructure

A production-ready Kubernetes platform with Kong API Gateway, Dapr, Keycloak, OpenSearch, and
segregated CI/CD pipelines. Deployable on **GKE**, **EKS**, **AKS**, or **Rancher (RKE2)** —
or any Kubernetes v1.27+ cluster.

## Architecture Diagrams

See [docs/diagrams.md](docs/diagrams.md) for Mermaid diagrams (render natively on GitHub):

- **Platform overview** — full component graph with namespaces
- **OIDC auth sequence** — Kong + Keycloak token exchange, step-by-step
- **Dapr runtime** — sidecar mTLS, state/pub-sub, control plane
- **CI/CD pipelines** — segregated security / infrastructure / applications pipelines
- **Cloud topologies** — GKE, EKS, AKS, and Rancher diagrams
- **Log flow** — OpenSearch + Fluentbit + Dapr binding
- **Maltego auth sequence** — registration, token, discovery, execution
- **Separation of concerns** — what you write vs. what the platform provides
- **Transform request lifecycle** — which layer handles each step
- **Capability responsibility matrix** — quadrant chart of ownership
- **Platform layer model** — infrastructure → operators → middleware → services → business code
- **Architecture decision map** — why Kong, Dapr, Keycloak, OpenSearch were chosen (with rejected alternatives)

See [docs/developer-experience.md](docs/developer-experience.md) for the **batteries-included philosophy**
and a step-by-step guide to adding a new transform with zero boilerplate.

## Stack

| Component | Role | Version |
|-----------|------|---------|
| **Kong Ingress Controller** | API Gateway, routing, auth plugins | 3.6 / chart 0.4.x |
| **Dapr** | Distributed runtime (state, pub/sub, service invocation) | 1.13.x |
| **Keycloak** | Identity & Access Management (OIDC/OAuth2) | 24.0 |
| **OpenSearch** | Log aggregation, full-text search, security analytics | 2.14 |
| **OpenSearch Dashboards** | Kibana-compatible UI with Keycloak SSO | 2.14 |
| **Fluentbit** | DaemonSet log collector and router | 3.1 |
| **cert-manager** | Automatic TLS certificate provisioning | v1.14.x |
| **Redis** | Backing store for Dapr state & pub/sub | (bitnami/redis) |

## Cloud Provider Support

| Provider | Guide | Terraform | Managed Backing Services |
|----------|-------|-----------|--------------------------|
| **Google Cloud (GKE)** | [docs/cloud-providers/gcp.md](docs/cloud-providers/gcp.md) | `terraform/gcp/` | Cloud SQL · Memorystore · Artifact Registry · Secret Manager |
| **AWS (EKS)** | [docs/cloud-providers/aws.md](docs/cloud-providers/aws.md) | `terraform/aws/` | RDS · ElastiCache · ECR · Secrets Manager |
| **Azure (AKS)** | [docs/cloud-providers/azure.md](docs/cloud-providers/azure.md) | `terraform/azure/` | PostgreSQL Flexible · Azure Cache · ACR · Key Vault |
| **Rancher (RKE2)** | [docs/cloud-providers/rancher.md](docs/cloud-providers/rancher.md) | `terraform/rancher/` | Fleet GitOps · Monitoring · Logging built-in |
| **Generic K8s** | This README | — | Self-hosted Redis + Postgres |

Each cloud provider includes Terraform that provisions the cluster and all managed backing services,
Helm value overrides in `k8s/cloud-overlays/<provider>/` for cloud-specific annotations and endpoints,
and a step-by-step guide covering DNS, secret management, and GitHub Actions OIDC (no static keys).

## CI/CD Pipelines — Segregated by Concern

Three independent workflows, each triggered only by relevant file changes:

| Pipeline | File | Triggers | Responsibility |
|----------|------|----------|----------------|
| **Security** | `security.yaml` | All pushes + nightly cron | Secret detection (Gitleaks), IaC scan (Trivy), OPA policies, CIS benchmarks (Checkov), SBOM, image scan |
| **Infrastructure** | `infrastructure.yaml` | `k8s/kong/`, `k8s/dapr/`, `k8s/keycloak/`, `terraform/`, etc. | Validate manifests, Terraform plan (PR), deploy cert-manager/Kong/Dapr/Keycloak/OpenSearch (dev auto, prod manual) |
| **Applications** | `applications.yaml` | `k8s/apps/`, `src/`, `Dockerfile` | Build & push image, Trivy image scan (block on CRITICAL), deploy via Kustomize overlay, rollback on failure |

## Directory Structure

```
.
├── docs/
│   ├── diagrams.md             # Mermaid diagrams (8 diagrams)
│   ├── architecture.md         # Narrative architecture and design decisions
│   ├── observability.md        # OpenSearch setup, Fluentbit, index strategy, Dapr binding
│   ├── runbook.md              # Ops runbook: scaling, secret rotation, break-glass
│   └── cloud-providers/
│       ├── gcp.md              # GKE guide: Autopilot, Cloud SQL, Memorystore, WI Federation
│       ├── aws.md              # EKS guide: IRSA, RDS, ElastiCache, ESO, NLB
│       ├── azure.md            # AKS guide: Workload Identity, Key Vault CSI, PostgreSQL Flexible
│       └── rancher.md          # Rancher + RKE2 + Fleet GitOps guide
├── terraform/
│   ├── gcp/                    # GKE + Cloud SQL + Memorystore + Artifact Registry
│   ├── aws/                    # EKS + RDS + ElastiCache + ECR + Secrets Manager
│   ├── azure/                  # AKS + PostgreSQL Flexible + Azure Cache + ACR + Key Vault
│   └── rancher/                # Rancher cluster + Fleet + Monitoring
├── k8s/
│   ├── namespaces/             # All namespace definitions
│   ├── kong/
│   │   ├── helm-values.yaml    # Kong Helm configuration (base)
│   │   └── plugins/            # jwt-auth, rate-limiting, cors, oidc-keycloak
│   ├── dapr/
│   │   ├── helm-values.yaml    # Dapr control-plane (HA mode)
│   │   ├── dapr-configuration.yaml
│   │   └── components/         # statestore, pubsub, secretstore, resiliency
│   ├── keycloak/
│   │   ├── helm-values.yaml    # Keycloak + Postgres
│   │   ├── realm-config.yaml   # Realm: kong, frontend, sample-service clients
│   │   └── secrets.yaml        # Placeholders only — never commit real values
│   ├── cert-manager/           # Let's Encrypt staging + prod ClusterIssuers
│   ├── apps/sample-app/        # Deployment (Dapr sidecar), Service, Ingress, HPA
│   ├── kustomize/
│   │   ├── base/               # All manifests wired together
│   │   └── overlays/
│   │       ├── dev/            # 1 replica, smaller resources, dev image tag
│   │       └── prod/           # 3 replicas, production resources, pinned image
│   ├── opensearch/
│   │   ├── helm-values.yaml    # OpenSearch 3-node cluster
│   │   ├── dashboards-values.yaml  # Dashboards + Keycloak OIDC + Kong ingress
│   │   ├── index-policies.yaml # ISM: platform-logs (30d), security-events (90d)
│   │   ├── dapr-binding.yaml   # Dapr output binding for app audit events
│   │   └── namespace.yaml
│   ├── logging/
│   │   └── fluentbit-values.yaml  # DaemonSet: collect → enrich → route to OpenSearch
│   └── cloud-overlays/
│       ├── gcp/                # GKE: Cloud SQL, Memorystore TLS, NEG annotations
│       ├── aws/                # EKS: RDS, ElastiCache TLS, NLB + IRSA
│       ├── azure/              # AKS: PostgreSQL Flexible, Azure Cache TLS, Key Vault CSI
│       └── rancher/            # Rancher: Fleet bundle, Prometheus ServiceMonitor
├── policies/
│   └── deployments.rego        # OPA: resource limits, no :latest, runAsNonRoot, TLS
├── .github/workflows/
│   ├── security.yaml           # Gitleaks · Trivy IaC · OPA · Checkov · SBOM (all pushes)
│   ├── infrastructure.yaml     # Validate · Terraform plan · Deploy infra (path-filtered)
│   └── applications.yaml       # Build · Image scan · Deploy app · Rollback (path-filtered)
└── scripts/
    ├── install.sh              # Full bootstrap (--dry-run, --skip-infra, --skip-apps)
    └── teardown.sh             # Clean uninstall
```

## Quick Start (Generic Kubernetes)

### Prerequisites

- Kubernetes cluster v1.27+
- `kubectl` configured
- `helm` v3.14+

### 1. Create required secrets

```bash
kubectl create namespace keycloak redis apps

kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password='<strong-password>' \
  --namespace keycloak

kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=postgres-password='<pg-admin-password>' \
  --from-literal=password='<keycloak-db-password>' \
  --namespace keycloak

kubectl create secret generic redis-secret \
  --from-literal=redis-password='<redis-password>' \
  --namespace redis
```

### 2. Run the install script

```bash
./scripts/install.sh
```

| Flag | Effect |
|------|--------|
| `--skip-infra` | Only deploy apps (infra already installed) |
| `--skip-apps` | Only deploy infrastructure |
| `--dry-run` | Print commands without applying |

### 3. Configure DNS

```bash
kubectl get svc -n kong kong-kong-proxy
# Point api.example.com and auth.example.com at the EXTERNAL-IP
```

Update hostnames in:
- `k8s/keycloak/helm-values.yaml` → `ingress.hostname`
- `k8s/apps/sample-app/ingress.yaml` → `spec.rules[].host`
- `k8s/cert-manager/cluster-issuer.yaml` → `spec.acme.email`

## Cloud-Specific Quick Start

### Google Cloud (GKE)

```bash
cd terraform/gcp
cp terraform.tfvars.example terraform.tfvars  # edit with your project_id
terraform apply
$(terraform output -raw get_credentials_command)
./scripts/install.sh
# See docs/cloud-providers/gcp.md for full guide
```

### AWS (EKS)

```bash
cd terraform/aws
cp terraform.tfvars.example terraform.tfvars  # edit region, cluster_name
terraform apply
$(terraform output -raw get_credentials_command)
./scripts/install.sh
# See docs/cloud-providers/aws.md for full guide
```

### Rancher (RKE2)

```bash
cd terraform/rancher
# Edit terraform.tfvars with your Rancher API URL and token
terraform apply
# Fleet will automatically sync manifests from this repo
# See docs/cloud-providers/rancher.md for full guide
```

## GitHub Actions

Three pipelines with independent triggers — infra changes never re-deploy apps and vice versa.

| Pipeline | Trigger | Responsibility |
|----------|---------|----------------|
| `security.yaml` | All pushes + nightly 02:00 UTC | Gitleaks, Trivy IaC (SARIF), OPA/Conftest, Checkov CIS, SBOM (Syft+Grype), nightly image scan |
| `infrastructure.yaml` | Push/PR on `k8s/kong/`, `k8s/dapr/`, `k8s/keycloak/`, `terraform/`, etc. | kubeconform validate, Helm dry-run, Terraform plan (PR), deploy cert-manager/Kong/Dapr/Keycloak/OpenSearch/Fluentbit |
| `applications.yaml` | Push/PR on `k8s/apps/`, `src/`, `Dockerfile` | Build + push image (GHCR), Trivy image scan (block CRITICAL), Kustomize overlay deploy, auto-rollback |

### Required GitHub Secrets

| Secret | Used by | Description |
|--------|---------|-------------|
| `DEV_KUBECONFIG` | infra + apps | base64-encoded kubeconfig for dev cluster |
| `PROD_KUBECONFIG` | infra + apps | base64-encoded kubeconfig for prod cluster |
| `OPENSEARCH_ADMIN_PASSWORD` | infrastructure | OpenSearch cluster health check |

### Required GitHub Environments

Settings → Environments:
- `dev` — no required reviewers (auto-deploys on push to `master`)
- `prod` — add 1+ required reviewer(s); applies to both infra and app pipelines

## Maltego Transform Hub

An open-source replacement for the Maltego iTDS and the commercial on-prem ID subscription.
Operators authenticate to **Keycloak** (`maltego-hub` realm) via OAuth2 client credentials,
receive a 300 s bearer token, and call transform endpoints directly — zero Maltego cloud dependency.

| Layer | Detail |
|-------|--------|
| **Authentication** | Keycloak `maltego-hub` realm · scopes `transforms:execute` / `transforms:admin` |
| **Discovery** | `GET /api/v2/manifest` returns all transforms + token URL (iTDS replacement) |
| **Execution** | `POST /api/v2/transforms/{name}` — accepts TRX XML or JSON |
| **Registration** | `POST /api/v1/clients/register` — self-service, one Keycloak client per operator |
| **Built-in transforms** | `DomainToIP`, `DomainToMX`, `DomainToWhois`, `URLToDomain`, `IPToGeoLocation` |
| **Extend** | Drop a `.py` file in `src/transform-hub/transforms/` — auto-discovered on startup |

See [docs/transform-hub.md](docs/transform-hub.md) for the full guide, including Maltego desktop configuration.

## Security Notes

- **Never commit real secrets.** See `k8s/keycloak/secrets.yaml` for the placeholder pattern. Use Sealed Secrets, External Secrets Operator, or cloud-native secret managers in production.
- All sidecar-to-sidecar traffic uses **Dapr mTLS** (Sentry-issued certificates).
- Kong enforces **JWT/OIDC validation** at the edge — apps receive pre-validated user headers.
- Keycloak has **brute-force protection** enabled in the realm config.
- All pods run as **non-root** with `readOnlyRootFilesystem: true` and dropped capabilities.
- OPA policies (enforced in CI via Conftest) block deployments without resource limits or with `:latest` tags.
- RKE2 (Rancher) applies the **CIS Kubernetes Benchmark** profile by default.

## Documentation

All docs live in [`docs/`](docs/) and are validated on every PR by the **`docs.yaml`** pipeline:

| Check | Tool | Blocks merge? |
|-------|------|:---:|
| Markdown lint (style + formatting) | `markdownlint-cli2` | ✅ Yes |
| Broken internal & external links | `lychee` | ✅ Yes |
| Mermaid diagram syntax | `@mermaid-js/mermaid-cli` | ✅ Yes |
| Spell check | `cspell` | ⚠️ Warn only |
| Doc coverage (code changed without docs) | Custom script | ⚠️ Warn only |

## Onboarding

| Role | Start here |
|------|-----------|
| **New business developer** (writes transforms) | [docs/onboarding-developer.md](docs/onboarding-developer.md) |
| **New platform admin / maintainer** | [docs/onboarding-admin.md](docs/onboarding-admin.md) |

## Further Reading

- [Architecture & Design Decisions](docs/architecture.md)
- [Architecture Diagrams](docs/diagrams.md) — 14 Mermaid diagrams
- [Developer Experience — Batteries Included](docs/developer-experience.md)
- [Maltego Transform Hub](docs/transform-hub.md)
- [Observability — OpenSearch & Logging](docs/observability.md)
- [Operator Runbook](docs/runbook.md)
- [Bill of Materials](BILL-OF-MATERIALS.md)
- [GKE Setup Guide](docs/cloud-providers/gcp.md)
- [EKS Setup Guide](docs/cloud-providers/aws.md)
- [AKS Setup Guide](docs/cloud-providers/azure.md)
- [Rancher / RKE2 Guide](docs/cloud-providers/rancher.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full list of planned extensions, organized by theme:
transforms, infrastructure, security, developer experience, observability, multi-tenancy, AI/LLM,
packaging, and governance. Items are tagged with effort estimates (XS → XL).
