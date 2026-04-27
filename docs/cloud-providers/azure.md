# Microsoft Azure (AKS) Setup Guide

Deploy the platform on Azure Kubernetes Service with fully managed backing services.

## Architecture

| Component | Azure Service |
|-----------|--------------|
| Kubernetes | AKS (Azure CNI, Calico network policy) |
| PostgreSQL (Keycloak) | Azure Database for PostgreSQL Flexible Server 15 |
| Redis (Dapr) | Azure Cache for Redis (Standard/Premium, TLS) |
| Container Registry | Azure Container Registry (ACR) |
| TLS Certificates | cert-manager + Let's Encrypt |
| Secrets | Azure Key Vault + CSI Secrets Provider (built into AKS) |
| DNS | Azure DNS |
| Load Balancer | Azure Standard Load Balancer |
| Pod Identity | Azure Workload Identity (no SPNs with client secrets) |
| Monitoring | Azure Monitor for Containers + Log Analytics |
| Security | Microsoft Defender for Containers |

## Prerequisites

```bash
# Install tools
brew install azure-cli terraform kubectl helm

# Login to Azure
az login
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

## Step 1 — Provision infrastructure with Terraform

```bash
cd terraform/azure

cat > terraform.tfvars <<EOF
resource_group_name = "platform-rg"
location            = "eastus"
cluster_name        = "platform-cluster"
environment         = "prod"
node_vm_size        = "Standard_D4s_v3"
node_count          = 3
node_min_count      = 2
node_max_count      = 8
postgres_sku        = "GP_Standard_D2s_v3"
redis_sku           = "Standard"
redis_capacity      = 1
domain              = "example.com"
EOF

terraform init
terraform plan
terraform apply
```

Key outputs:

```bash
terraform output get_credentials_command       # configure kubectl
terraform output postgres_fqdn                 # for Keycloak values
terraform output redis_hostname                # for Dapr components
terraform output redis_ssl_port                # 6380 for TLS
terraform output acr_login_server              # for image pushes
terraform output key_vault_uri                 # for secret references
terraform output workload_identity_client_id   # for pod annotations
terraform output dns_name_servers              # update your registrar
```

## Step 2 — Configure kubectl

```bash
az aks get-credentials \
  --resource-group platform-rg \
  --name platform-cluster

kubectl get nodes
```

## Step 3 — Mount Key Vault secrets via CSI driver

AKS ships with the Azure Key Vault CSI Secrets Provider enabled. Update the placeholder values in the SecretProviderClass:

```bash
# Fill in the values from Terraform outputs
CLIENT_ID=$(terraform -chdir=terraform/azure output -raw workload_identity_client_id)
TENANT_ID=$(terraform -chdir=terraform/azure output -raw workload_identity_tenant_id)
KV_NAME=$(terraform -chdir=terraform/azure output -raw key_vault_uri | sed 's|https://||;s|\.vault\.azure\.net/||')

sed -i "s|clientID: \"\"|clientID: \"$CLIENT_ID\"|g" \
  k8s/cloud-overlays/azure/secret-provider-class.yaml
sed -i "s|tenantId: \"\"|tenantId: \"$TENANT_ID\"|g" \
  k8s/cloud-overlays/azure/secret-provider-class.yaml
sed -i "s|keyvaultName: \"\"|keyvaultName: \"$KV_NAME\"|g" \
  k8s/cloud-overlays/azure/secret-provider-class.yaml

kubectl apply -f k8s/cloud-overlays/azure/secret-provider-class.yaml
```

The CSI provider auto-creates the Kubernetes Secrets (`keycloak-admin-secret`, `keycloak-postgresql-secret`, `redis-secret`) by mounting a volume with the SecretProviderClass into a dummy pod. Alternatively, create the K8s Secrets manually by pulling from Key Vault:

```bash
KC_PASS=$(az keyvault secret show --vault-name "${KV_NAME}" \
  --name keycloak-admin-password --query value -o tsv)

kubectl create namespace keycloak
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password="$KC_PASS" \
  --namespace keycloak

KC_DB_PASS=$(az keyvault secret show --vault-name "${KV_NAME}" \
  --name keycloak-db-password --query value -o tsv)

kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=password="$KC_DB_PASS" \
  --namespace keycloak

REDIS_KEY=$(az keyvault secret show --vault-name "${KV_NAME}" \
  --name redis-primary-key --query value -o tsv)

kubectl create namespace redis
kubectl create secret generic redis-secret \
  --from-literal=redis-password="$REDIS_KEY" \
  --namespace redis
```

## Step 4 — Update cloud-specific values

```bash
PG_FQDN=$(terraform -chdir=terraform/azure output -raw postgres_fqdn)
REDIS_HOST=$(terraform -chdir=terraform/azure output -raw redis_hostname)

# Update Keycloak values
sed -i "s|host: \"\"|host: \"$PG_FQDN\"|" \
  k8s/cloud-overlays/azure/keycloak-values.yaml

# Update Dapr statestore + pubsub
sed -i "s|value: \"\"|value: \"${REDIS_HOST}:6380\"|g" \
  k8s/cloud-overlays/azure/dapr-statestore.yaml
```

## Step 5 — Install the platform

```bash
./scripts/install.sh --skip-apps

kubectl apply -f k8s/cloud-overlays/azure/dapr-statestore.yaml

helm upgrade --install kong kong/ingress -n kong \
  -f k8s/kong/helm-values.yaml \
  -f k8s/cloud-overlays/azure/kong-values.yaml \
  --wait

helm upgrade --install keycloak bitnami/keycloak -n keycloak \
  -f k8s/keycloak/helm-values.yaml \
  -f k8s/cloud-overlays/azure/keycloak-values.yaml \
  --wait

./scripts/install.sh --skip-infra
```

## Step 6 — Configure DNS

```bash
KONG_IP=$(kubectl get svc -n kong kong-kong-proxy \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

az network dns record-set a add-record \
  --resource-group platform-rg \
  --zone-name example.com \
  --record-set-name "api" \
  --ipv4-address "$KONG_IP"

az network dns record-set a add-record \
  --resource-group platform-rg \
  --zone-name example.com \
  --record-set-name "auth" \
  --ipv4-address "$KONG_IP"
```

## GitHub Actions with ACR + Workload Identity Federation

No static client secrets needed — use OIDC:

1. Create a Workload Identity Federation credential in Azure AD for the GitHub repository:

```bash
APP_ID=$(az ad app create --display-name "github-actions-platform" \
  --query appId -o tsv)

# Trust GitHub OIDC tokens for the master branch
az ad app federated-credential create --id $APP_ID \
  --parameters '{
    "name": "github-master",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:dzacharis/repo0:ref:refs/heads/master",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# Grant ACR push permissions
az role assignment create \
  --assignee $APP_ID \
  --role AcrPush \
  --scope $(terraform -chdir=terraform/azure output -raw acr_login_server | xargs -I{} az acr show --name {} --query id -o tsv)
```

1. Add GitHub secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`

2. Update CI workflow:

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

- name: Login to ACR
  run: az acr login --name $(terraform output -raw acr_login_server | cut -d. -f1)
```

## Azure Policy (OPA Gatekeeper)

AKS with `azure_policy_enabled = true` deploys Gatekeeper automatically.
Azure Policy assignments enforce baseline controls. Our `policies/deployments.rego` overlaps
with Azure Policy; use one or the other:

```bash
# List assigned policies
az policy assignment list --scope /subscriptions/$(az account show --query id -o tsv)

# View Gatekeeper constraint violations
kubectl get constraints
kubectl get constrainttemplate
```

## Cost Estimates (eastus, approximate)

| Resource | Size | Monthly Cost |
|----------|------|-------------|
| AKS Standard tier (control plane) | — | ~$73 |
| VM nodes | 3× Standard_D4s_v3 | ~$420 |
| PostgreSQL Flexible | GP_Standard_D2s_v3 (HA) | ~$185 |
| Azure Cache for Redis | Standard C1 | ~$55 |
| Azure Load Balancer | Standard | ~$25 |
| ACR Standard | — | ~$20 |
| Key Vault | Standard | ~$5 |
| Log Analytics | ~5 GB/day | ~$50 |
| **Total estimate** | | **~$833/month** |

Dev (Free AKS tier, B2s VMs, Basic Redis, no HA Postgres): ~$150/month.

## Useful Azure Commands

```bash
# Check AKS cluster status
az aks show --resource-group platform-rg --name platform-cluster --output table

# View node pools
az aks nodepool list --resource-group platform-rg --cluster-name platform-cluster -o table

# Check PostgreSQL
az postgres flexible-server show --resource-group platform-rg \
  --name platform-cluster-keycloak-pg

# List Key Vault secrets
az keyvault secret list --vault-name platformclusterkv -o table

# Stream AKS logs via Log Analytics
az monitor log-analytics query \
  --workspace $(terraform output -raw log_analytics_workspace_id) \
  --analytics-query "ContainerLog | take 20"

# Scale node pool
az aks scale --resource-group platform-rg --name platform-cluster \
  --node-count 5 --nodepool-name system
```
