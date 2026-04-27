# Amazon Web Services (EKS) Setup Guide

Deploy the platform on Amazon Elastic Kubernetes Service with managed backing services.

## Architecture

| Component | AWS Service |
|-----------|------------|
| Kubernetes | EKS (Managed Node Groups) |
| PostgreSQL (Keycloak) | RDS for PostgreSQL 15 |
| Redis (Dapr) | ElastiCache for Redis 7 (cluster mode off) |
| Container Registry | ECR (Elastic Container Registry) |
| TLS Certificates | cert-manager + Let's Encrypt (or ACM) |
| Secrets | AWS Secrets Manager + External Secrets Operator |
| DNS | Route 53 |
| Load Balancer | AWS NLB (via AWS Load Balancer Controller) |
| Pod Identity | IRSA (IAM Roles for Service Accounts) |

## Prerequisites

```bash
# Install tools
brew install awscli terraform kubectl helm eksctl

# Configure AWS credentials
aws configure
# or: export AWS_PROFILE=my-profile
```

## Step 1 — Provision infrastructure with Terraform

```bash
cd terraform/aws

cat > terraform.tfvars <<EOF
region             = "us-east-1"
cluster_name       = "platform-cluster"
environment        = "prod"
node_instance_type = "t3.xlarge"
node_desired_size  = 3
node_min_size      = 2
node_max_size      = 8
db_instance_class  = "db.t3.medium"
redis_node_type    = "cache.t3.medium"
domain             = "example.com"
availability_zones = ["us-east-1a", "us-east-1b", "us-east-1c"]
EOF

terraform init
terraform plan
terraform apply
```

Key outputs to note:

```bash
terraform output get_credentials_command   # configure kubectl
terraform output rds_endpoint              # for Keycloak values
terraform output redis_endpoint            # for Dapr components
terraform output ecr_url                   # update CI image tags
terraform output eso_role_arn              # for External Secrets Operator
```

## Step 2 — Install AWS Load Balancer Controller

The AWS LBC is required for NLB provisioning by Kong:

```bash
# Configure kubectl
aws eks update-kubeconfig --name platform-cluster --region us-east-1

# Install AWS LBC via Helm
helm repo add eks https://aws.github.io/eks-charts
helm repo update

# Get VPC ID
VPC_ID=$(aws eks describe-cluster --name platform-cluster \
  --query "cluster.resourcesVpcConfig.vpcId" --output text)

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --set clusterName=platform-cluster \
  --set serviceAccount.create=true \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=$(terraform output -raw eso_role_arn) \
  --set region=us-east-1 \
  --set vpcId=$VPC_ID \
  --wait
```

## Step 3 — Install External Secrets Operator

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets --create-namespace \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=$(terraform output -raw eso_role_arn) \
  --wait

# Create a ClusterSecretStore pointing to AWS Secrets Manager
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secretsmanager
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
EOF
```

## Step 4 — Sync secrets from AWS Secrets Manager

```bash
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: keycloak-admin-secret
  namespace: keycloak
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: ClusterSecretStore
  target:
    name: keycloak-admin-secret
  data:
    - secretKey: admin-password
      remoteRef:
        key: platform-cluster/keycloak-admin-password
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: keycloak-postgresql-secret
  namespace: keycloak
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: ClusterSecretStore
  target:
    name: keycloak-postgresql-secret
  data:
    - secretKey: password
      remoteRef:
        key: platform-cluster/keycloak-db-password
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: redis-secret
  namespace: redis
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: ClusterSecretStore
  target:
    name: redis-secret
  data:
    - secretKey: redis-password
      remoteRef:
        key: platform-cluster/redis-auth-token
EOF
```

## Step 5 — Update cloud-specific values

Edit `k8s/cloud-overlays/aws/keycloak-values.yaml`:

- Set `externalDatabase.host` to the `rds_endpoint` Terraform output (hostname only, no port)

Edit `k8s/cloud-overlays/aws/dapr-statestore.yaml`:

- Set `redisHost` values to `<redis_endpoint>:6379`

## Step 6 — Install the platform

```bash
./scripts/install.sh --skip-apps

# Apply AWS-specific overrides
kubectl apply -f k8s/cloud-overlays/aws/dapr-statestore.yaml

# Deploy apps
./scripts/install.sh --skip-infra
```

Or with explicit Helm merges:

```bash
helm upgrade --install kong kong/ingress -n kong \
  -f k8s/kong/helm-values.yaml \
  -f k8s/cloud-overlays/aws/kong-values.yaml \
  --wait

helm upgrade --install keycloak bitnami/keycloak -n keycloak \
  -f k8s/keycloak/helm-values.yaml \
  -f k8s/cloud-overlays/aws/keycloak-values.yaml \
  --wait
```

## Step 7 — Configure DNS

```bash
# Get Kong NLB hostname
KONG_HOST=$(kubectl get svc -n kong kong-kong-proxy \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "Kong NLB: $KONG_HOST"

# Get Route 53 hosted zone ID
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name example.com --query 'HostedZones[0].Id' --output text | cut -d/ -f3)

# Create CNAME records pointing to the NLB
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.example.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "'$KONG_HOST'"}]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "auth.example.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "'$KONG_HOST'"}]
      }
    }
  ]
}'
```

## GitHub Actions with ECR + OIDC

Use GitHub OIDC (no static AWS credentials) in your CI:

```yaml
# In .github/workflows/ci.yaml, replace docker login with:
- name: Configure AWS credentials (OIDC)
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::123456789:role/github-actions-role
    aws-region: us-east-1

- name: Login to ECR
  uses: aws-actions/amazon-ecr-login@v2

# Then push to: 123456789.dkr.ecr.us-east-1.amazonaws.com/platform-cluster/sample-app:sha-abc
```

Create the OIDC trust IAM role with:

```bash
# This allows github.com/dzacharis/repo0 to assume the role
aws iam create-role --role-name github-actions-role \
  --assume-role-policy-document file://trust-policy.json
```

## Cost Estimates (us-east-1, approximate)

| Resource | Size | Monthly Cost |
|----------|------|-------------|
| EKS Cluster | control plane | ~$73 |
| EC2 Nodes | 3× t3.xlarge | ~$450 |
| RDS PostgreSQL | db.t3.medium Multi-AZ | ~$100 |
| ElastiCache Redis | cache.t3.medium (2 nodes) | ~$100 |
| NLB | 1 LB | ~$20 |
| ECR | 10 GB storage | ~$1 |
| **Total estimate** | | **~$744/month** |

Dev environment (1 node, db.t3.small, single-AZ Redis): ~$200/month.

## Useful AWS Commands

```bash
# Check EKS node group status
aws eks describe-nodegroup --cluster-name platform-cluster --nodegroup-name platform-cluster-nodes

# View RDS instance
aws rds describe-db-instances --db-instance-identifier platform-cluster-keycloak

# Check ElastiCache cluster
aws elasticache describe-replication-groups --replication-group-id platform-cluster-dapr

# View Secrets Manager secrets
aws secretsmanager list-secrets --filter Key=name,Values=platform-cluster

# Get a secret value
aws secretsmanager get-secret-value --secret-id platform-cluster/keycloak-admin-password \
  --query SecretString --output text
```
