# Onboarding — Platform Admin / Maintainer

This guide covers everything an admin needs to take ownership of a running platform instance:
cluster access, secret management, Keycloak administration, CI/CD pipelines, observability,
and day-2 operations.

For narrative architecture context, start with [architecture.md](./architecture.md) and
[diagrams.md](./diagrams.md). For emergency runbook procedures, see [runbook.md](./runbook.md).

---

## Table of Contents

1. [Access Setup](#1-access-setup)
2. [Repository Layout](#2-repository-layout)
3. [Cluster Access](#3-cluster-access)
4. [Secrets and Credentials](#4-secrets-and-credentials)
5. [Keycloak Administration](#5-keycloak-administration)
6. [Deploying and Upgrading Components](#6-deploying-and-upgrading-components)
7. [CI/CD Pipelines](#7-cicd-pipelines)
8. [Observability](#8-observability)
9. [Certificate Management](#9-certificate-management)
10. [Adding a New Developer](#10-adding-a-new-developer)
11. [Common Day-2 Tasks](#11-common-day-2-tasks)
12. [Disaster Recovery Checklist](#12-disaster-recovery-checklist)

---

## 1. Access Setup

### Required tools

| Tool | Version | Install |
|------|---------|---------|
| `kubectl` | `>= 1.29` | [kubernetes.io/docs/tasks/tools](https://kubernetes.io/docs/tasks/tools/) |
| `helm` | `>= 3.14` | `brew install helm` / [helm.sh](https://helm.sh) |
| `kustomize` | `>= 5.3` | `brew install kustomize` |
| `terraform` | `>= 1.7` | `brew install terraform` |
| Cloud CLI | latest | See per-cloud section below |
| `jq` | any | `brew install jq` |

### Cloud CLI setup

```bash
# GCP
gcloud auth login && gcloud config set project <PROJECT_ID>
gcloud container clusters get-credentials <CLUSTER_NAME> --region <REGION>

# AWS
aws configure  # or assume-role
aws eks update-kubeconfig --name <CLUSTER_NAME> --region <REGION>

# Azure
az login
az aks get-credentials --resource-group <RG> --name <CLUSTER_NAME>

# Rancher
# Log in to Rancher UI → Cluster → Kubeconfig file → download and merge
```

### Verify access

```bash
kubectl get nodes
kubectl get namespaces
# Expected namespaces: kong, keycloak, dapr-system, cert-manager, apps, opensearch, logging
```

---

## 2. Repository Layout

```
.
├── BILL-OF-MATERIALS.md       # Complete software inventory
├── ROADMAP.md                 # Planned extensions
├── docs/                      # All platform documentation
│   ├── onboarding-developer.md   ← share with developers
│   ├── onboarding-admin.md       ← this file
│   ├── developer-experience.md
│   ├── architecture.md
│   ├── diagrams.md
│   ├── observability.md
│   ├── runbook.md
│   ├── transform-hub.md
│   └── cloud-providers/       # Per-cloud setup guides
├── k8s/                       # All Kubernetes manifests
│   ├── namespaces/
│   ├── kong/                  # Gateway + KongPlugin CRDs
│   ├── dapr/                  # Helm values + Components
│   ├── keycloak/              # Helm values + realm ConfigMaps
│   ├── cert-manager/          # ClusterIssuers
│   ├── opensearch/            # Helm values + ISM policies
│   ├── logging/               # Fluentbit DaemonSet
│   ├── apps/                  # Sample app + Transform Hub
│   ├── kustomize/             # Overlays: base / dev / prod
│   └── cloud-overlays/        # Per-cloud patches: gcp / aws / azure / rancher
├── terraform/                 # IaC per cloud: gcp / aws / azure / rancher
├── src/transform-hub/         # Application source code
├── policies/                  # OPA/Conftest policies
└── .github/workflows/         # CI/CD: security / infrastructure / applications / docs
```

---

## 3. Cluster Access

### Namespaces and what lives in each

| Namespace | Contents | Who touches it |
|-----------|----------|---------------|
| `kong` | Kong Ingress Controller, KongPlugin CRDs | Admin only |
| `keycloak` | Keycloak + PostgreSQL subchart | Admin only |
| `dapr-system` | Dapr control plane (Operator, Sentry, Placement, Injector) | Admin only |
| `cert-manager` | cert-manager controller + ClusterIssuers | Admin only |
| `opensearch` | OpenSearch cluster (3 nodes) + Dashboards | Admin only |
| `logging` | Fluentbit DaemonSet | Admin only |
| `apps` | Transform Hub + sample app | Admin (deploy), Dev (code) |

### Useful diagnostic commands

```bash
# Health overview
kubectl get pods -A | grep -v Running | grep -v Completed

# Kong
kubectl get kongplugins -A
kubectl logs -n kong deployment/kong-ingress-controller

# Dapr
dapr dashboard -n dapr-system    # opens browser UI
kubectl get components -n apps   # Dapr components registered to apps namespace
kubectl logs -n dapr-system deployment/dapr-operator

# Keycloak
kubectl logs -n keycloak statefulset/keycloak

# cert-manager
kubectl get certificaterequests -A
kubectl get certificates -A
kubectl describe certificate <name> -n kong
```

---

## 4. Secrets and Credentials

### Where secrets live

| Secret | Namespace | K8s Secret Name | What it contains |
|--------|-----------|----------------|-----------------|
| Keycloak admin password | `keycloak` | `keycloak-admin-secret` | `admin-password` |
| Keycloak DB password | `keycloak` | `keycloak-db-secret` | `password` |
| Transform Hub env secrets | `apps` | `transform-hub-secrets` | `KEYCLOAK_ADMIN_CLIENT_SECRET` |
| Kong OIDC plugin config | `kong` | `oidc-config` | `client_secret` |

### Viewing a secret value

```bash
kubectl get secret keycloak-admin-secret -n keycloak \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

### Creating / rotating a secret

```bash
# Rotate Keycloak admin password
NEW_PW=$(openssl rand -base64 32)
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password="$NEW_PW" \
  -n keycloak --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart statefulset/keycloak -n keycloak
```

For cloud-managed secret stores, see [runbook.md — Secret Rotation](./runbook.md).

---

## 5. Keycloak Administration

### Accessing the admin console

```bash
# Get the admin password
ADMIN_PW=$(kubectl get secret keycloak-admin-secret -n keycloak \
  -o jsonpath='{.data.admin-password}' | base64 -d)

# Port-forward if not accessible via Ingress
kubectl port-forward svc/keycloak -n keycloak 8080:80
open http://localhost:8080
# Login: admin / $ADMIN_PW
```

### Realm overview

| Realm | Purpose | Key clients |
|-------|---------|------------|
| `master` | Keycloak admin only — do not use for apps | — |
| `myrealm` | Platform applications | `kong` (OIDC), `frontend`, `sample-service` |
| `maltego-hub` | Transform Hub identity | `transform-hub` (bearer), `maltego-desktop` (user) |

### Creating a new developer client (maltego-hub realm)

1. Admin Console → `maltego-hub` realm → Clients → Create client
2. Client ID: `developer-<name>` (e.g., `developer-alice`)
3. Client authentication: ON
4. Service accounts roles: ON
5. After saving → Service accounts tab → Assign role `transforms:execute`
6. Credentials tab → Copy the generated secret; share securely with the developer

Or use the API:

```bash
# Get admin token
ADMIN_TOKEN=$(curl -s -X POST \
  "http://localhost:8080/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=$ADMIN_PW" \
  -d "grant_type=password" | jq -r .access_token)

# Create client
curl -s -X POST "http://localhost:8080/admin/realms/maltego-hub/clients" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "developer-alice",
    "enabled": true,
    "clientAuthenticatorType": "client-secret",
    "serviceAccountsEnabled": true,
    "standardFlowEnabled": false
  }'
```

### Revoking a client

Admin Console → `maltego-hub` → Clients → select client → Actions → Delete.

Or via API:
```bash
CLIENT_UUID=$(curl -s "http://localhost:8080/admin/realms/maltego-hub/clients?clientId=developer-alice" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.[0].id')
curl -s -X DELETE "http://localhost:8080/admin/realms/maltego-hub/clients/$CLIENT_UUID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 6. Deploying and Upgrading Components

### Standard upgrade flow (Helm chart upgrade)

```bash
# Example: upgrade Kong
helm repo update
helm upgrade kong kong/ingress \
  --namespace kong \
  --values k8s/kong/helm-values.yaml \
  --version 0.5.0   # ← new version
```

### Deploying application changes via Kustomize

```bash
# Dev overlay
kustomize build k8s/kustomize/overlays/dev | kubectl apply -f -

# Prod overlay
kustomize build k8s/kustomize/overlays/prod | kubectl apply -f -
```

In practice, the CI pipeline does this automatically on merge to `main`.

### Rolling back a deployment

```bash
kubectl rollout undo deployment/transform-hub -n apps
kubectl rollout status deployment/transform-hub -n apps
```

For Helm:
```bash
helm rollback kong 0 -n kong    # 0 = previous revision
```

### Applying a new Dapr component

```bash
kubectl apply -f k8s/dapr/components/my-new-component.yaml
# Components are hot-reloaded by Dapr — no pod restart needed
```

---

## 7. CI/CD Pipelines

### Pipeline overview

| Workflow | Trigger | Deploys to | Manual gate? |
|----------|---------|-----------|-------------|
| `security.yaml` | All pushes + nightly 02:00 UTC | — (scan only) | No |
| `infrastructure.yaml` | Changes in `k8s/`, `terraform/`, `policies/` | Dev auto, Prod manual | Yes (prod) |
| `applications.yaml` | Changes in `src/`, `k8s/apps/` | Dev auto, Prod manual | Yes (prod) |
| `docs.yaml` | Changes in `docs/`, `*.md` | — (lint only) | No |

### Required GitHub secrets

Set these under *Settings → Secrets and variables → Actions*:

| Secret | Used by | Value |
|--------|---------|-------|
| `KUBECONFIG_DEV` | infrastructure, applications | base64-encoded kubeconfig for dev cluster |
| `KUBECONFIG_PROD` | infrastructure, applications | base64-encoded kubeconfig for prod cluster |
| `GHCR_TOKEN` | applications | GitHub PAT with `write:packages` scope |
| `TF_VAR_project_id` | infrastructure (GCP) | GCP project ID |
| `TF_VAR_aws_region` | infrastructure (AWS) | AWS region |
| `TF_VAR_subscription_id` | infrastructure (Azure) | Azure subscription ID |

```bash
# Example: set KUBECONFIG_DEV
kubectl config view --raw | base64 -w 0 | gh secret set KUBECONFIG_DEV
```

### Viewing pipeline results

- **SARIF security reports**: GitHub → Security → Code scanning alerts
- **SBOM artifacts**: GitHub → Actions → Run → Artifacts
- **Terraform plan output**: PR comment (posted by `infrastructure.yaml`)
- **Doc coverage report**: PR comment (posted by `docs.yaml`)

### Granting prod deploy approval

Production deployments require a reviewer. Add approvers:
*Settings → Environments → prod → Required reviewers → add team/user*

---

## 8. Observability

### OpenSearch Dashboards

```
URL: https://logs.example.com
Auth: OIDC via Keycloak (myrealm)
Indices:
  platform-logs-*        — all application logs (30-day retention)
  security-events-*      — Keycloak + cert-manager logs (90-day retention)
```

### Key index patterns

```bash
# Check index health
curl -k -u admin:<password> https://localhost:9200/_cat/indices?v

# Check ISM policy status
curl -k -u admin:<password> https://localhost:9200/_plugins/_ism/policies
```

Port-forward OpenSearch if not reachable:
```bash
kubectl port-forward svc/opensearch-cluster-master -n opensearch 9200:9200
```

### Dapr observability

```bash
# Dapr dashboard (component health, actor distribution)
dapr dashboard -n dapr-system

# Distributed traces (Zipkin)
kubectl port-forward svc/zipkin -n dapr-system 9411:9411
open http://localhost:9411
```

### HPA and scaling status

```bash
kubectl get hpa -n apps
kubectl describe hpa transform-hub -n apps
```

---

## 9. Certificate Management

### Check certificate status

```bash
kubectl get certificates -A
kubectl get certificaterequests -A
# Look for READY=True
```

### Force renewal (if cert is near expiry)

```bash
kubectl annotate certificate <name> -n <ns> \
  cert-manager.io/issue-temporary-certificate="true" --overwrite
# cert-manager will re-issue automatically; remove the annotation after
```

### Check Let's Encrypt rate limits

cert-manager uses the staging issuer for testing. Switch to production in
`k8s/cert-manager/cluster-issuer.yaml` when ready:

```yaml
# prod issuer
server: https://acme-v02.api.letsencrypt.org/directory
```

---

## 10. Adding a New Developer

1. **Keycloak**: Create a client credential in `maltego-hub` realm (see [§5](#5-keycloak-administration)).
2. **GitHub**: Add to the repository with `Developer` role (read + PR rights, no branch protection bypass).
3. **Docs**: Share the following links:
   - [docs/onboarding-developer.md](./onboarding-developer.md) ← start here
   - [docs/developer-experience.md](./developer-experience.md)
   - [docs/transform-hub.md](./transform-hub.md)
4. **Secrets**: Share `client_id` and `client_secret` via a secure channel (1Password, Vault, etc.).
   Never send over Slack or email.

---

## 11. Common Day-2 Tasks

### Scale the Transform Hub

```bash
# Immediate manual scale
kubectl scale deployment/transform-hub -n apps --replicas=5

# Permanent change: edit k8s/apps/transform-hub/hpa.yaml and push
```

### Add a new Dapr component (e.g. a new data source binding)

1. Create `k8s/dapr/components/my-binding.yaml` following the existing pattern.
2. Apply: `kubectl apply -f k8s/dapr/components/my-binding.yaml`
3. Commit the file — CI will apply it on future deploys.

### Update the OPA policies

1. Edit `policies/deployments.rego`.
2. Test locally: `conftest test k8s/apps/sample-app/ --policy policies/`
3. Push — the `security.yaml` pipeline validates on every PR.

### Rotate the Keycloak DB password

See [runbook.md — Secret Rotation](./runbook.md).

### Investigate a transform failure

```bash
# 1. Check pod logs
kubectl logs -n apps deployment/transform-hub --since=1h | grep ERROR

# 2. Check Dapr sidecar logs
kubectl logs -n apps deployment/transform-hub -c daprd --since=1h

# 3. Check Kong access logs (includes rate-limit hits)
kubectl logs -n kong deployment/kong --since=1h | grep "transform"

# 4. Search OpenSearch
# Index: platform-logs-*  Field: log.level:error  Time: last 1h
```

### Add a new cloud overlay

1. Copy `k8s/cloud-overlays/gcp/` to `k8s/cloud-overlays/<provider>/`.
2. Add the corresponding Terraform module under `terraform/<provider>/`.
3. Add a cloud provider guide under `docs/cloud-providers/<provider>.md`.
4. Reference it from the cloud overlay table in `README.md`.

---

## 12. Disaster Recovery Checklist

Use this if a cluster is lost or a namespace is corrupted.

```bash
# 1. Re-provision infrastructure
cd terraform/<provider>
terraform init && terraform apply

# 2. Get cluster credentials
<cloud-cli> ... get-credentials ...

# 3. Bootstrap namespaces and platform
./scripts/install.sh

# 4. Restore Keycloak realms
kubectl apply -f k8s/keycloak/realm-config.yaml
kubectl apply -f k8s/keycloak/maltego-realm-config.yaml
kubectl rollout restart statefulset/keycloak -n keycloak

# 5. Re-apply secrets (from your secure secret store, not git)
kubectl create secret generic keycloak-admin-secret ...
kubectl create secret generic transform-hub-secrets ...

# 6. Verify
kubectl get pods -A
kubectl get certificates -A
curl -s https://api.example.com/transforms/api/v2/manifest | jq .
```

Detailed step-by-step recovery procedures are in [runbook.md](./runbook.md).

---

## Key Reference Links

| Resource | URL / Command |
|----------|--------------|
| Architecture diagrams | [docs/diagrams.md](./diagrams.md) |
| Architecture decisions | [diagrams.md — Decision Map](./diagrams.md#14-architecture-decision-map) |
| Bill of Materials | [BILL-OF-MATERIALS.md](../BILL-OF-MATERIALS.md) |
| Runbook | [docs/runbook.md](./runbook.md) |
| Observability guide | [docs/observability.md](./observability.md) |
| Roadmap | [ROADMAP.md](../ROADMAP.md) |
| Developer onboarding | [docs/onboarding-developer.md](./onboarding-developer.md) |
| Transform Hub guide | [docs/transform-hub.md](./transform-hub.md) |
