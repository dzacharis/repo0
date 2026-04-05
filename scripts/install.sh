#!/usr/bin/env bash
# install.sh — Bootstrap the full platform stack on a Kubernetes cluster
#
# Prerequisites:
#   - kubectl configured and pointing at your cluster
#   - helm v3.14+
#   - A running Kubernetes cluster (v1.27+)
#
# Usage:
#   ./scripts/install.sh [--skip-infra] [--skip-apps] [--dry-run]

set -euo pipefail

###############################################################################
# Config
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SKIP_INFRA=false
SKIP_APPS=false
DRY_RUN=false

# Parse args
for arg in "$@"; do
  case $arg in
    --skip-infra) SKIP_INFRA=true ;;
    --skip-apps)  SKIP_APPS=true  ;;
    --dry-run)    DRY_RUN=true    ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

KUBECTL="kubectl"
HELM="helm"
if [ "$DRY_RUN" = "true" ]; then
  KUBECTL="kubectl --dry-run=client"
  echo "[dry-run] Commands will not actually be applied."
fi

###############################################################################
# Helpers
###############################################################################
info()  { echo -e "\033[0;32m[INFO]\033[0m  $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }
step()  { echo -e "\n\033[1;34m===> $* \033[0m"; }

wait_for_rollout() {
  local ns="$1"
  local resource="$2"
  info "Waiting for $resource in namespace $ns..."
  kubectl rollout status "$resource" --namespace "$ns" --timeout=5m
}

###############################################################################
# Preflight checks
###############################################################################
step "Preflight checks"

command -v kubectl >/dev/null 2>&1 || error "kubectl is not installed"
command -v helm    >/dev/null 2>&1 || error "helm v3 is not installed"

KUBE_VERSION=$(kubectl version --short 2>/dev/null | grep "Server Version" | awk '{print $3}' || true)
info "Kubernetes server version: ${KUBE_VERSION:-unknown}"

###############################################################################
# Helm repos
###############################################################################
step "Adding Helm repositories"

helm repo add kong       https://charts.konghq.com
helm repo add dapr       https://dapr.github.io/helm-charts
helm repo add bitnami    https://charts.bitnami.com/bitnami
helm repo add jetstack   https://charts.jetstack.io
helm repo add redis      https://charts.bitnami.com/bitnami
helm repo update
info "Helm repos updated."

###############################################################################
# Infrastructure
###############################################################################
if [ "$SKIP_INFRA" = "false" ]; then

  step "Creating namespaces"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/namespaces/namespaces.yaml"

  # ---- cert-manager --------------------------------------------------------
  step "Deploying cert-manager"
  $HELM upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager \
    --values "${REPO_ROOT}/k8s/cert-manager/helm-values.yaml" \
    --wait --timeout 5m
  $KUBECTL apply -f "${REPO_ROOT}/k8s/cert-manager/cluster-issuer.yaml"
  info "cert-manager deployed."

  # ---- Redis (dependency for Dapr state/pubsub) ----------------------------
  step "Deploying Redis"
  $HELM upgrade --install redis bitnami/redis \
    --namespace redis --create-namespace \
    --set auth.existingSecret=redis-secret \
    --set auth.existingSecretPasswordKey=redis-password \
    --wait --timeout 5m
  info "Redis deployed."

  # ---- Kong ----------------------------------------------------------------
  step "Deploying Kong Ingress Controller"
  $HELM upgrade --install kong kong/ingress \
    --namespace kong \
    --values "${REPO_ROOT}/k8s/kong/helm-values.yaml" \
    --wait --timeout 5m
  $KUBECTL apply -f "${REPO_ROOT}/k8s/kong/plugins/"
  info "Kong deployed."

  # ---- Dapr ----------------------------------------------------------------
  step "Deploying Dapr"
  $HELM upgrade --install dapr dapr/dapr \
    --namespace dapr-system \
    --values "${REPO_ROOT}/k8s/dapr/helm-values.yaml" \
    --wait --timeout 10m
  $KUBECTL apply -f "${REPO_ROOT}/k8s/dapr/dapr-configuration.yaml"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/dapr/components/"
  info "Dapr deployed."

  # ---- Keycloak ------------------------------------------------------------
  step "Deploying Keycloak"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/keycloak/realm-config.yaml"

  warn "Make sure 'keycloak-admin-secret' and 'keycloak-postgresql-secret' exist in the keycloak namespace."
  warn "See k8s/keycloak/secrets.yaml for the required secret structure."

  $HELM upgrade --install keycloak bitnami/keycloak \
    --namespace keycloak \
    --values "${REPO_ROOT}/k8s/keycloak/helm-values.yaml" \
    --wait --timeout 10m
  info "Keycloak deployed."

fi  # SKIP_INFRA

###############################################################################
# Applications
###############################################################################
if [ "$SKIP_APPS" = "false" ]; then

  step "Deploying sample-app"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/apps/sample-app/service.yaml"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/apps/sample-app/deployment.yaml"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/apps/sample-app/ingress.yaml"
  $KUBECTL apply -f "${REPO_ROOT}/k8s/apps/sample-app/hpa.yaml"

  if [ "$DRY_RUN" = "false" ]; then
    wait_for_rollout apps "deployment/sample-app"
  fi
  info "sample-app deployed."

fi  # SKIP_APPS

###############################################################################
# Summary
###############################################################################
step "Deployment complete"
echo ""
kubectl get pods -A | grep -E "NAME|kong|dapr|keycloak|cert-manager|sample-app" || true
echo ""
info "Kong proxy:"
kubectl get svc -n kong -l app=kong-kong-proxy 2>/dev/null || true
info "Keycloak:"
kubectl get svc -n keycloak 2>/dev/null || true
echo ""
info "Access Keycloak admin at: https://auth.example.com/admin"
info "API Gateway:              https://api.example.com"
