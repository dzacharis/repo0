# Operator Runbook

## Initial Cluster Setup

### Prerequisites

- Kubernetes v1.27+ cluster with a LoadBalancer provider
- `kubectl` configured and pointing at the cluster
- `helm` v3.14+
- DNS records pointing at your cluster's LoadBalancer IP

### Steps

1. **Create required secrets** (never stored in git):

```bash
# Keycloak admin
kubectl create namespace keycloak
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password='<strong-random-password>' \
  --namespace keycloak

# Keycloak PostgreSQL
kubectl create secret generic keycloak-postgresql-secret \
  --from-literal=postgres-password='<pg-admin-password>' \
  --from-literal=password='<keycloak-db-password>' \
  --namespace keycloak

# Redis
kubectl create namespace redis
kubectl create secret generic redis-secret \
  --from-literal=redis-password='<redis-password>' \
  --namespace redis

# Kong OIDC client secret (must match Keycloak realm config)
kubectl create namespace apps
kubectl create secret generic kong-oidc-secret \
  --from-literal=client-secret='kong-client-secret-change-me' \
  --namespace apps

# Sample app secrets
kubectl create secret generic sample-app-secrets \
  --from-literal=keycloak-client-secret='sample-service-secret-change-me' \
  --namespace apps
```

1. **Run the install script**:

```bash
./scripts/install.sh
```

1. **Verify all components are running**:

```bash
kubectl get pods -n kong
kubectl get pods -n dapr-system
kubectl get pods -n keycloak
kubectl get pods -n cert-manager
kubectl get pods -n redis
```

1. **Configure GitHub Actions secrets** in repository Settings → Secrets:
   - `DEV_KUBECONFIG` — base64-encoded kubeconfig for dev cluster: `cat ~/.kube/config | base64 -w 0`
   - `PROD_KUBECONFIG` — base64-encoded kubeconfig for prod cluster
   - `KEYCLOAK_ADMIN_PASSWORD`
   - `REDIS_PASSWORD`

2. **Configure GitHub Environments** in Settings → Environments:
   - `dev` — no required reviewers
   - `prod` — add required reviewer(s); enable "Required reviewers"

---

## Secret Rotation

### Rotating the Keycloak Admin Password

```bash
# Update the K8s secret
kubectl create secret generic keycloak-admin-secret \
  --from-literal=admin-password='<new-password>' \
  --namespace keycloak \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart Keycloak to pick up the new secret
kubectl rollout restart deployment/keycloak -n keycloak
kubectl rollout status deployment/keycloak -n keycloak --timeout=5m

# Update the GitHub Actions secret to match
# (Settings → Secrets → KEYCLOAK_ADMIN_PASSWORD)
```

### Rotating the Redis Password

```bash
kubectl create secret generic redis-secret \
  --from-literal=redis-password='<new-password>' \
  --namespace redis \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart Redis and Dapr components
kubectl rollout restart statefulset/redis-master -n redis
# Dapr reloads secret store components dynamically — no restart needed
# Kong requires a config reload:
kubectl rollout restart deployment/kong-kong -n kong
```

### Rotating the Kong OIDC Client Secret

1. Update the client secret in Keycloak Admin UI (Clients → kong → Credentials → Regenerate Secret)
2. Update the Kubernetes secret:

```bash
kubectl create secret generic kong-oidc-secret \
  --from-literal=client-secret='<new-secret>' \
  --namespace apps \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/kong-kong -n kong
```

---

## Scaling

### Manually scaling an application

```bash
kubectl scale deployment/sample-app --replicas=5 -n apps
```

### Adjusting HPA bounds

Edit `k8s/apps/sample-app/hpa.yaml`, change `minReplicas`/`maxReplicas`, commit, and push — the deploy pipeline will apply the change.

### Scaling Kong

```bash
# Temporarily
kubectl scale deployment/kong-kong -n kong --replicas=4

# Permanently — update helm-values.yaml and re-deploy:
helm upgrade kong kong/ingress -n kong -f k8s/kong/helm-values.yaml --set replicaCount=4
```

---

## Keycloak Realm Changes

The realm is bootstrapped from `k8s/keycloak/realm-config.yaml` **on first boot only**. For incremental changes:

### Option A: Admin UI (immediate, not tracked in git)

1. Open `https://auth.example.com/admin`
2. Make changes
3. Export the realm: Realm Settings → Action → Partial export (include clients, groups, roles)
4. Save the exported JSON to `k8s/keycloak/realm-config.yaml` (update the ConfigMap data)
5. Commit and push

### Option B: Keycloak Admin CLI (scriptable)

```bash
# Port-forward to Keycloak
kubectl port-forward svc/keycloak -n keycloak 8080:8080

# Get admin token
TOKEN=$(curl -s -X POST http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "client_id=admin-cli&grant_type=password&username=admin&password=$KEYCLOAK_ADMIN_PASSWORD" \
  | jq -r .access_token)

# Example: add a new client
curl -s -X POST http://localhost:8080/admin/realms/myrealm/clients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"clientId":"new-service","enabled":true,"bearerOnly":true}'
```

---

## Break-Glass Access

### Kong Admin API

```bash
kubectl port-forward svc/kong-kong-admin -n kong 8001:8001
# Now accessible at http://localhost:8001
curl http://localhost:8001/services
curl http://localhost:8001/plugins
```

### Keycloak Admin Console

```bash
kubectl port-forward svc/keycloak -n keycloak 8080:8080
# Open http://localhost:8080/admin
```

### Dapr Dashboard

```bash
dapr dashboard -k
# Opens the Dapr dashboard in your browser
```

### Exec into a Dapr sidecar

```bash
POD=$(kubectl get pod -n apps -l app=sample-app -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $POD -n apps -c daprd -- /bin/sh
```

---

## Disaster Recovery

### Redis — restore from snapshot

1. Scale down Dapr-annotated pods to stop writes:

```bash
kubectl scale deployment/sample-app -n apps --replicas=0
```

1. Restore the PVC from your cloud snapshot (cloud-specific procedure)
2. Scale pods back up:

```bash
kubectl scale deployment/sample-app -n apps --replicas=2
```

### Full cluster rebuild

1. Ensure all secrets are stored in your secrets manager (not just in the cluster)
2. Provision a new cluster
3. Re-create secrets (see "Initial Cluster Setup" above)
4. Run `./scripts/install.sh`
5. Re-trigger the latest deploy pipeline run

---

## Useful Diagnostic Commands

```bash
# Check Dapr sidecar status for all pods
kubectl get pods -n apps -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.dapr\.io/app-id}{"\n"}{end}'

# Check Kong plugin status
kubectl get kongplugins -A
kubectl get kongclusterplugins

# Check cert-manager certificate status
kubectl get certificates -A
kubectl get certificaterequests -A

# Check Keycloak realm clients
kubectl exec -it deploy/keycloak -n keycloak -- \
  /opt/bitnami/keycloak/bin/kcadm.sh get clients -r myrealm --server http://localhost:8080 \
  --user admin --password $KEYCLOAK_ADMIN_PASSWORD

# View Dapr component health
kubectl get components -n apps
kubectl describe component statestore -n apps
```
