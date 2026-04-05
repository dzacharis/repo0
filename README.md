# Kubernetes Platform Infrastructure

A production-ready Kubernetes platform with Kong API Gateway, Dapr, Keycloak, and automated CI/CD pipelines.
Deployable on **Google Cloud (GKE)**, **AWS (EKS)**, or **Rancher (RKE2)** — or any Kubernetes v1.27+ cluster.

## Architecture Diagrams

See [docs/diagrams.md](docs/diagrams.md) for Mermaid diagrams (render natively on GitHub):

- **Platform overview** — component topology and data flow
- **OIDC auth sequence** — Kong + Keycloak token exchange step-by-step
- **Dapr runtime** — sidecar communication, state/pub-sub, mTLS
- **CI/CD pipeline** — lint → scan → build → deploy-dev → deploy-prod
- **Cloud provider topologies** — GKE, EKS, and Rancher diagrams

## Stack

| Component | Role | Version |
|-----------|------|---------|
| **Kong Ingress Controller** | API Gateway, routing, auth plugins | 3.6 / chart 0.4.x |
| **Dapr** | Distributed runtime (state, pub/sub, service invocation) | 1.13.x |
| **Keycloak** | Identity & Access Management (OIDC/OAuth2) | 24.0 |
| **cert-manager** | Automatic TLS certificate provisioning | v1.14.x |
| **Redis** | Backing store for Dapr state & pub/sub | (bitnami/redis) |

## Cloud Provider Support

| Provider | Guide | Terraform | Backing Services |
|----------|-------|-----------|-----------------|
| **Google Cloud (GKE)** | [docs/cloud-providers/gcp.md](docs/cloud-providers/gcp.md) | `terraform/gcp/` | Cloud SQL + Memorystore + Artifact Registry |
| **AWS (EKS)** | [docs/cloud-providers/aws.md](docs/cloud-providers/aws.md) | `terraform/aws/` | RDS + ElastiCache + ECR |
| **Rancher (RKE2)** | [docs/cloud-providers/rancher.md](docs/cloud-providers/rancher.md) | `terraform/rancher/` | Fleet GitOps + Monitoring built-in |
| **Generic K8s** | This README | — | Self-hosted Redis + Postgres |

Each cloud provider has:
- A Terraform module that provisions the cluster and all managed backing services
- Helm value overrides in `k8s/cloud-overlays/<provider>/` that patch the base values for cloud-specific annotations and managed service endpoints
- A step-by-step guide with DNS, secret management, and GitHub Actions integration

## Directory Structure

```
.
├── docs/
│   ├── diagrams.md             # Mermaid architecture diagrams
│   ├── architecture.md         # Narrative architecture and design decisions
│   ├── runbook.md              # Ops runbook: scaling, secret rotation, break-glass
│   └── cloud-providers/
│       ├── gcp.md              # GKE setup guide (step-by-step)
│       ├── aws.md              # EKS setup guide (step-by-step)
│       └── rancher.md          # Rancher + RKE2 + Fleet guide
├── terraform/
│   ├── gcp/                    # GKE + Cloud SQL + Memorystore + Artifact Registry
│   ├── aws/                    # EKS + RDS + ElastiCache + ECR
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
│   └── cloud-overlays/
│       ├── gcp/                # GKE-specific: Cloud SQL, Memorystore, NLB annotations
│       ├── aws/                # EKS-specific: RDS, ElastiCache, NLB + IRSA
│       └── rancher/            # Rancher: Fleet bundle, Prometheus ServiceMonitor
├── policies/
│   └── deployments.rego        # OPA policies: resource limits, no :latest, runAsNonRoot
├── .github/workflows/
│   ├── ci.yaml                 # Lint → Kustomize validate → OPA → Trivy → build
│   ├── deploy-dev.yaml         # Auto-deploy on master push
│   └── deploy-prod.yaml        # Manual + confirmation + required reviewer
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

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci.yaml` | Every push / PR | Lint, Kustomize validate, OPA policies, Trivy/Checkov scan, image build |
| `deploy-dev.yaml` | Push to `master` | Full infra + app deploy to dev cluster |
| `deploy-prod.yaml` | Manual (`workflow_dispatch`) | Confirmation string + required reviewer gate + rollback on failure |

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEV_KUBECONFIG` | base64-encoded kubeconfig for dev cluster |
| `PROD_KUBECONFIG` | base64-encoded kubeconfig for prod cluster |

### Required GitHub Environments

Settings → Environments:
- `dev` — no required reviewers
- `prod` — add 1+ required reviewer(s)

## Security Notes

- **Never commit real secrets.** See `k8s/keycloak/secrets.yaml` for the placeholder pattern. Use Sealed Secrets, External Secrets Operator, or cloud-native secret managers in production.
- All sidecar-to-sidecar traffic uses **Dapr mTLS** (Sentry-issued certificates).
- Kong enforces **JWT/OIDC validation** at the edge — apps receive pre-validated user headers.
- Keycloak has **brute-force protection** enabled in the realm config.
- All pods run as **non-root** with `readOnlyRootFilesystem: true` and dropped capabilities.
- OPA policies (enforced in CI via Conftest) block deployments without resource limits or with `:latest` tags.
- RKE2 (Rancher) applies the **CIS Kubernetes Benchmark** profile by default.

## Further Reading

- [Architecture & Design Decisions](docs/architecture.md)
- [Operator Runbook](docs/runbook.md)
- [Architecture Diagrams](docs/diagrams.md)
- [GKE Setup Guide](docs/cloud-providers/gcp.md)
- [EKS Setup Guide](docs/cloud-providers/aws.md)
- [Rancher / RKE2 Guide](docs/cloud-providers/rancher.md)
