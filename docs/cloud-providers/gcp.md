# Google Cloud Platform (GKE) Setup Guide

Deploy the platform on Google Kubernetes Engine with managed backing services.

## Architecture

| Component | GCP Service |
|-----------|------------|
| Kubernetes | GKE Autopilot (or Standard) |
| PostgreSQL (Keycloak) | Cloud SQL for PostgreSQL 15 |
| Redis (Dapr) | Memorystore for Redis 7 |
| Container Registry | Artifact Registry |
| TLS Certificates | cert-manager + Let's Encrypt (or Google-managed certs) |
| Secrets | Secret Manager + External Secrets Operator |
| DNS | Cloud DNS |
| Load Balancer | Cloud L4 External Load Balancer (via GKE) |
| Identity (pods) | Workload Identity (no key files) |

## Prerequisites

```bash
# Install tools
brew install google-cloud-sdk terraform kubectl helm

# Authenticate
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project YOUR_PROJECT_ID
```

## Step 1 — Provision infrastructure with Terraform

```bash
cd terraform/gcp

# Copy and edit the tfvars file
cat > terraform.tfvars <<EOF
project_id           = "your-gcp-project-id"
region               = "us-central1"
cluster_name         = "platform-cluster"
environment          = "prod"
gke_autopilot        = true
db_tier              = "db-custom-2-7680"   # 2 vCPU, 7.5 GB RAM
redis_memory_size_gb = 2
domain               = "example.com"
authorized_networks  = [
  { cidr_block = "YOUR_OFFICE_IP/32", display_name = "office" }
]
EOF

terraform init
terraform plan
terraform apply
```

After apply, note the outputs:

```bash
terraform output get_credentials_command   # configure kubectl
terraform output cloud_sql_private_ip      # needed for Keycloak values
terraform output memorystore_host          # needed for Dapr components
terraform output artifact_registry_url     # update CI image tags
terraform output dns_name_servers          # update your domain registrar
```

## Step 2 — Configure kubectl

```bash
# Copy the command from Terraform output, e.g.:
gcloud container clusters get-credentials platform-cluster \
  --region us-central1 --project your-gcp-project-id

kubectl get nodes
```

## Step 3 — Create Kubernetes secrets

```bash
# Keycloak admin password — pull from Secret Manager
KC_PASS=$(gcloud secrets versions access latest \
  --secret="platform-cluster-keycloak-admin-password")

kubectl create namespace keycloak
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password="$KC_PASS" \
  --namespace keycloak

# Keycloak DB password — pull from Secret Manager
KC_DB_PASS=$(gcloud secrets versions access latest \
  --secret="platform-cluster-keycloak-db-password")

kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=password="$KC_DB_PASS" \
  --namespace keycloak

# Memorystore Redis auth string
REDIS_PASS=$(gcloud redis instances describe platform-cluster-redis \
  --region us-central1 --format="value(authString)" 2>/dev/null || echo "")

kubectl create namespace redis
kubectl create secret generic redis-secret \
  --from-literal=redis-password="$REDIS_PASS" \
  --namespace redis
```

## Step 4 — Update cloud-specific values

Edit `k8s/cloud-overlays/gcp/keycloak-values.yaml`:

- Set `externalDatabase.host` to the `cloud_sql_private_ip` Terraform output

Edit `k8s/cloud-overlays/gcp/dapr-statestore.yaml`:

- Set both `redisHost` values to `<memorystore_host>:6379`

## Step 5 — Install the platform

```bash
# Run the standard install script (handles Helm chart installs)
./scripts/install.sh --skip-apps

# Apply GCP-specific overrides
kubectl apply -f k8s/cloud-overlays/gcp/dapr-statestore.yaml

# Deploy apps
./scripts/install.sh --skip-infra
```

Or use Helm directly with merged values:

```bash
# Kong with GKE overrides
helm upgrade --install kong kong/ingress -n kong \
  -f k8s/kong/helm-values.yaml \
  -f k8s/cloud-overlays/gcp/kong-values.yaml \
  --wait

# Keycloak with Cloud SQL
helm upgrade --install keycloak bitnami/keycloak -n keycloak \
  -f k8s/keycloak/helm-values.yaml \
  -f k8s/cloud-overlays/gcp/keycloak-values.yaml \
  --wait
```

## Step 6 — Configure DNS

```bash
# Get Kong proxy external IP
KONG_IP=$(kubectl get svc -n kong kong-kong-proxy \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Kong IP: $KONG_IP"

# Create DNS records in Cloud DNS
gcloud dns record-sets create "api.example.com." \
  --zone="example-com" --type="A" --ttl="300" --rrdatas="$KONG_IP"

gcloud dns record-sets create "auth.example.com." \
  --zone="example-com" --type="A" --ttl="300" --rrdatas="$KONG_IP"
```

## Step 7 — Set up GitHub Actions

Add these secrets to the repository (Settings → Secrets):

```bash
# Encode kubeconfig
KUBECONFIG_B64=$(cat ~/.kube/config | base64 -w 0)
# Add as: PROD_KUBECONFIG (or DEV_KUBECONFIG)
```

For Artifact Registry image pushes, use Workload Identity Federation (no static key):

1. Create a Workload Identity Pool in GCP IAM
2. Add the GitHub OIDC provider
3. Grant the pool access to Artifact Registry
4. Update CI workflow to use `google-github-actions/auth@v2` with WIF

## Workload Identity for Dapr (Secret Manager access)

```bash
# Annotate the Dapr service account to use WI
kubectl annotate serviceaccount dapr-operator \
  --namespace dapr-system \
  iam.gke.io/gcp-service-account=dapr-workload-identity@YOUR_PROJECT.iam.gserviceaccount.com
```

Then add a Dapr Secret Store component for Secret Manager:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: gcp-secretmanager
  namespace: apps
spec:
  type: secretstores.gcp.secretmanager
  version: v1
  metadata:
    - name: type
      value: serviceaccount
    - name: project_id
      value: YOUR_PROJECT_ID
    # With Workload Identity, no key file needed:
    - name: auth_provider_x509_cert_url
      value: ""
```

## Cost Estimates (us-central1, approximate)

| Resource | Size | Monthly Cost |
|----------|------|-------------|
| GKE Autopilot | 4 vCPU / 8GB baseline | ~$150 |
| Cloud SQL Postgres | db-custom-2-7680 (HA) | ~$130 |
| Memorystore Redis | 1 GB STANDARD_HA | ~$50 |
| Cloud Load Balancer | 1 LB | ~$20 |
| Artifact Registry | 10 GB storage | ~$1 |
| **Total estimate** | | **~$350/month** |

Use `db-g1-small` + `BASIC` Redis + 1-replica GKE for dev: ~$80/month.

## Useful GCP Commands

```bash
# Check GKE cluster status
gcloud container clusters describe platform-cluster --region us-central1

# View Cloud SQL connections
gcloud sql instances describe platform-cluster-keycloak-pg

# Monitor Memorystore
gcloud redis instances describe platform-cluster-redis --region us-central1

# View Secret Manager secrets
gcloud secrets list --filter="name~platform-cluster"

# Stream GKE logs
gcloud logging read "resource.type=k8s_container" --limit=50 --format=json | jq '.[] | .jsonPayload'
```
