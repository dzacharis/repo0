# Rancher Setup Guide

Deploy the platform on Rancher with RKE2, using Fleet for GitOps-based manifest delivery.
This approach is cloud-agnostic and works on bare metal, VMware vSphere, or any cloud.

## What is Rancher?

[Rancher](https://rancher.com) is an open-source Kubernetes management platform by SUSE.
It provisions and manages multiple downstream clusters, provides a unified UI, and includes:

- **RKE2** — a hardened, FIPS-compliant Kubernetes distribution
- **Fleet** — built-in GitOps engine (similar to ArgoCD / Flux)
- **Rancher Monitoring** — Prometheus + Grafana, pre-wired to cluster metrics
- **Rancher Logging** — Fluentbit + Loki log aggregation
- **Longhorn** — cloud-native distributed storage (optional)
- **NeuVector** — container security (optional)

## Architecture

```
┌────────────────────────────────────────────────┐
│  Rancher Management Cluster (RKE2)             │
│  ┌────────────┐  ┌───────┐  ┌───────────────┐ │
│  │ Rancher UI │  │ Fleet │  │ Rancher Charts│ │
│  └─────┬──────┘  └───┬───┘  └───────────────┘ │
└────────┼─────────────┼──────────────────────────┘
         │ manage      │ sync manifests from git
         ▼             ▼
┌────────────────────────────────────────────────┐
│  Downstream Platform Cluster (RKE2)            │
│  kong / dapr-system / keycloak / apps          │
└────────────────────────────────────────────────┘
```

## Prerequisites

```bash
# Install tools
brew install helm kubectl rancher-cli terraform

# Rancher CLI login
rancher login https://rancher.example.com --token <your-api-token>
```

## Option A — Install Rancher on an existing cluster

If you already have a Kubernetes cluster (K3s, RKE2, cloud-managed):

```bash
# Add Rancher Helm repo
helm repo add rancher-stable https://releases.rancher.com/server-charts/stable
helm repo update

# Install cert-manager (Rancher dependency)
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set installCRDs=true --wait

# Install Rancher
helm upgrade --install rancher rancher-stable/rancher \
  --namespace cattle-system --create-namespace \
  --set hostname=rancher.example.com \
  --set replicas=3 \
  --set bootstrapPassword=<strong-initial-password> \
  --set ingress.tls.source=letsEncrypt \
  --set letsEncrypt.email=admin@example.com \
  --wait

echo "Rancher UI: https://rancher.example.com"
```

## Option B — Install Rancher + RKE2 via Terraform

```bash
cd terraform/rancher

cat > terraform.tfvars <<EOF
rancher_api_url     = "https://rancher.example.com"
rancher_token       = "token-xxxxx:xxxxxxxxxxxxxxxx"
cluster_name        = "platform-cluster"
environment         = "prod"
kubernetes_version  = "v1.30.2+rke2r1"
node_count          = 3
enable_fleet_gitops = true
fleet_repo_url      = "https://github.com/dzacharis/repo0"
fleet_repo_branch   = "master"
EOF

terraform init
terraform plan
terraform apply
```

This creates:
- A new RKE2 downstream cluster registered with Rancher
- Platform project with resource quotas
- Namespaces: kong, dapr-system, keycloak, apps
- Rancher Monitoring (Prometheus + Grafana)
- Rancher Logging (Fluentbit)
- Fleet GitOps agent configured to sync this repository

## Step 1 — Bootstrap the downstream cluster

After Terraform apply, get the kubeconfig:

```bash
# Via Rancher CLI
rancher cluster kubeconfig platform-cluster > ~/.kube/platform-cluster.yaml
export KUBECONFIG=~/.kube/platform-cluster.yaml

kubectl get nodes
```

Alternatively from the Rancher UI: Cluster → Download KubeConfig.

## Step 2 — Add Helm chart catalogs

```bash
# These are also managed by Terraform, but can be added manually:
rancher catalog add kong https://charts.konghq.com --cluster platform-cluster
rancher catalog add dapr https://dapr.github.io/helm-charts --cluster platform-cluster
rancher catalog add bitnami https://charts.bitnami.com/bitnami --cluster platform-cluster
```

## Step 3 — Create secrets

```bash
# Rancher Secrets (managed through Rancher project or directly via kubectl)
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password='<strong-password>' \
  --namespace keycloak

kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=postgres-password='<pg-admin-pass>' \
  --from-literal=password='<kc-db-pass>' \
  --namespace keycloak

kubectl create secret generic redis-secret \
  --from-literal=redis-password='<redis-pass>' \
  --namespace redis --create-namespace
```

Alternatively, use **Rancher's built-in Secret Management** (UI: Cluster → Storage → Secrets)
or integrate with Vault via the Rancher Vault Helm chart.

## Step 4 — Run the standard install script

```bash
./scripts/install.sh
```

The script works identically on Rancher/RKE2 as on any other Kubernetes cluster.

For Rancher-specific Kong metrics integration:
```bash
helm upgrade --install kong kong/ingress -n kong \
  -f k8s/kong/helm-values.yaml \
  -f k8s/cloud-overlays/rancher/kong-values.yaml \
  --wait
```

## Step 5 — Enable Fleet GitOps

Apply the Fleet bundle to automatically sync manifests from this git repo:

```bash
# On the Rancher management cluster
kubectl apply -f k8s/cloud-overlays/rancher/fleet-bundle.yaml

# Check sync status
kubectl get gitrepo -n fleet-local
kubectl get bundle -n fleet-local
```

After this, any push to the `master` branch will automatically reconcile the cluster state.
The Fleet bundle syncs:
- All namespaces
- Dapr components (statestore, pubsub, secretstore, resiliency)
- Kong plugins
- Keycloak realm ConfigMap
- Application manifests

## Step 6 — Rancher Monitoring

Grafana is installed by the Rancher Monitoring chart. Access it:

```bash
kubectl get svc -n cattle-monitoring-system rancher-monitoring-grafana
# Default credentials: admin / prom-operator (changed in Terraform values)
```

Pre-built dashboards available in Rancher UI:
- Cluster metrics (CPU, memory, network per namespace)
- Kong metrics (requests/sec, latency, error rates) via the Kong Prometheus plugin
- Dapr metrics (sidecar latency, state store ops) via `dapr.io/enable-metrics: "true"`

Enable Kong metrics scraping:
```bash
# Kong exposes Prometheus metrics on port 8100
# The cloud-overlay already adds the ServiceMonitor — just deploy it:
kubectl apply -f k8s/cloud-overlays/rancher/kong-values.yaml
```

## Step 7 — Rancher Continuous Delivery (Fleet) in CI/CD

Instead of using GitHub Actions to `kubectl apply`, Fleet watches the repo and syncs automatically.
Your GitHub Actions workflow simplifies to just building and pushing the image.

Update `.github/workflows/deploy-dev.yaml` to only update the image tag in the kustomization:

```yaml
- name: Update image tag for Fleet to pick up
  run: |
    cd k8s/kustomize/overlays/dev
    kustomize edit set image sample-app=ghcr.io/${{ github.repository }}/sample-app:${{ env.IMAGE_TAG }}
    git config user.email "ci@example.com"
    git config user.name "CI Bot"
    git add kustomization.yaml
    git commit -m "ci: update sample-app image to ${{ env.IMAGE_TAG }}"
    git push
# Fleet detects the commit and reconciles within ~15 seconds
```

## RKE2 Hardening Notes

RKE2 ships with CIS Benchmark hardening enabled by default:
- `profile: cis` in the cluster config applies CIS Kubernetes Benchmark v1.7 controls
- Pod Security Standards enforced: `restricted` profile in `apps` namespace
- Audit logging enabled by default
- etcd encryption at rest for secrets

For additional hardening, enable NeuVector:
```bash
helm upgrade --install neuvector neuvector/core \
  --namespace cattle-neuvector-system --create-namespace \
  --set k8s.platform=rke2 \
  --wait
```

## Rancher vs Self-Managed Kubernetes — When to Choose

| Scenario | Recommendation |
|----------|---------------|
| Single cluster, cloud-managed (GKE/EKS) | Use native cloud + `install.sh` |
| Multi-cluster management | Rancher (unified UI, Fleet GitOps) |
| On-premise / bare metal | Rancher + RKE2 + Longhorn |
| Air-gapped / regulated environments | Rancher (supports air-gap installs) |
| Teams new to Kubernetes | Rancher (better UX, built-in monitoring) |
| Maximum GitOps automation | Rancher + Fleet (reconciles drift automatically) |

## Useful Rancher CLI Commands

```bash
# List clusters
rancher cluster ls

# Switch context
rancher context switch

# Deploy app via Rancher CLI
rancher app install kong --namespace kong --values k8s/kong/helm-values.yaml

# Check Fleet sync status
rancher gitrepo list --all-namespaces

# View cluster alerts
rancher alert list --cluster platform-cluster
```
