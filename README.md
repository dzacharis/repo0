# Kubernetes Platform Infrastructure

A production-ready Kubernetes platform with Kong API Gateway, Dapr, Keycloak, and automated CI/CD pipelines.

## Stack

| Component | Role | Version |
|-----------|------|---------|
| **Kong Ingress Controller** | API Gateway, routing, auth plugins | 3.6 / chart 0.4.x |
| **Dapr** | Distributed runtime (state, pub/sub, service invocation) | 1.13.x |
| **Keycloak** | Identity & Access Management (OIDC/OAuth2) | 24.0 |
| **cert-manager** | Automatic TLS certificate provisioning | v1.14.x |
| **Redis** | Backing store for Dapr state & pub/sub | (bitnami/redis) |

## Directory Structure

```
.
├── k8s/
│   ├── namespaces/         # All namespace definitions
│   ├── kong/
│   │   ├── helm-values.yaml        # Kong Helm configuration
│   │   └── plugins/
│   │       ├── jwt-auth.yaml       # JWT authentication plugin
│   │       ├── rate-limiting.yaml  # Rate limiting (global + strict)
│   │       ├── cors.yaml           # CORS headers
│   │       └── oidc-keycloak.yaml  # OIDC → Keycloak integration
│   ├── dapr/
│   │   ├── helm-values.yaml        # Dapr control-plane config (HA)
│   │   ├── dapr-configuration.yaml # Tracing, middleware pipeline
│   │   └── components/
│   │       ├── statestore.yaml     # Redis state store
│   │       ├── pubsub.yaml         # Redis pub/sub broker
│   │       ├── secretstore.yaml    # Kubernetes secret store
│   │       └── resiliency.yaml     # Retry / circuit-breaker policies
│   ├── keycloak/
│   │   ├── helm-values.yaml        # Keycloak + Postgres config
│   │   ├── realm-config.yaml       # ConfigMap with realm JSON (kong, frontend, sample-service clients)
│   │   └── secrets.yaml            # Secret placeholders (never commit real values)
│   ├── cert-manager/
│   │   ├── helm-values.yaml
│   │   └── cluster-issuer.yaml     # Let's Encrypt staging + prod issuers
│   └── apps/
│       └── sample-app/
│           ├── deployment.yaml     # App with Dapr sidecar annotations
│           ├── service.yaml
│           ├── ingress.yaml        # Kong ingress with plugins
│           └── hpa.yaml            # Horizontal Pod Autoscaler
├── .github/
│   └── workflows/
│       ├── ci.yaml                 # Lint, security scan, build & push image
│       ├── deploy-dev.yaml         # Auto-deploy to dev on push to master
│       └── deploy-prod.yaml        # Manual deploy to prod with approval gate
└── scripts/
    ├── install.sh                  # Bootstrap the full stack
    └── teardown.sh                 # Remove all components
```

## Quick Start

### Prerequisites

- Kubernetes cluster v1.27+
- `kubectl` configured
- `helm` v3.14+

### 1. Create required secrets

```bash
# Keycloak admin password
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password='<strong-password>' \
  --namespace keycloak

# Keycloak PostgreSQL passwords
kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=postgres-password='<pg-admin-password>' \
  --from-literal=password='<keycloak-db-password>' \
  --namespace keycloak

# Redis password
kubectl create secret generic redis-secret \
  --from-literal=redis-password='<redis-password>' \
  --namespace redis --create-namespace
```

### 2. Run the install script

```bash
./scripts/install.sh
```

Options:
- `--skip-infra` — skip infrastructure components, only deploy apps
- `--skip-apps`  — deploy infrastructure only
- `--dry-run`    — print commands without applying

### 3. Configure DNS

Point your domain records at the Kong proxy LoadBalancer IP:

```bash
kubectl get svc -n kong -l app=kong-kong-proxy
```

Update hostnames in:
- `k8s/keycloak/helm-values.yaml` → `ingress.hostname`
- `k8s/apps/sample-app/ingress.yaml` → `spec.rules[].host`
- `k8s/cert-manager/cluster-issuer.yaml` → `spec.acme.email`

## GitHub Actions

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci.yaml` | Every push / PR | Lint manifests, security scan (Trivy + Checkov), build & push image |
| `deploy-dev.yaml` | Push to `master` | Full infra + app deploy to dev cluster |
| `deploy-prod.yaml` | Manual (`workflow_dispatch`) | Requires approval gate + confirmation string |

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEV_KUBECONFIG` | kubeconfig for dev cluster (base64-encoded) |
| `PROD_KUBECONFIG` | kubeconfig for prod cluster (base64-encoded) |

### Required GitHub Environments

Create two environments in repository Settings → Environments:
- `dev` — no required reviewers
- `prod` — require 1+ reviewers before deploy

## Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────────────────┐
│  Kong Ingress Controller (LoadBalancer)     │
│  - JWT / OIDC auth (→ Keycloak)             │
│  - Rate limiting                            │
│  - CORS                                     │
│  - TLS termination (cert-manager)           │
└─────────────────────┬───────────────────────┘
                      │
          ┌───────────▼───────────┐
          │    apps namespace     │
          │                       │
          │  ┌─────────────────┐  │
          │  │   sample-app    │  │
          │  │  + dapr sidecar │  │
          │  └────────┬────────┘  │
          └───────────┼───────────┘
                      │ Dapr APIs
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
    State Store    Pub/Sub     Service Invocation
    (Redis)        (Redis)     (mTLS via Dapr)

Keycloak (keycloak namespace)
  - Realm: myrealm
  - Clients: kong, frontend, sample-service
  - Backed by PostgreSQL
```

## Security Notes

- **Never commit real secrets.** Use Sealed Secrets or External Secrets Operator in production.
- All inter-service communication inside the mesh uses Dapr mTLS.
- Kong enforces JWT/OIDC validation at the edge before traffic reaches apps.
- Keycloak brute-force protection is enabled in the realm config.
- All pods run as non-root with `readOnlyRootFilesystem: true`.
