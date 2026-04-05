#!/usr/bin/env bash
# teardown.sh — Remove all platform components from the cluster
#
# WARNING: This is destructive and will delete all platform resources.
# Usage:
#   ./scripts/teardown.sh [--confirm]

set -euo pipefail

CONFIRM=false
for arg in "$@"; do
  case $arg in
    --confirm) CONFIRM=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

if [ "$CONFIRM" = "false" ]; then
  echo "This will uninstall Kong, Dapr, Keycloak, cert-manager, and all applications."
  echo "Run with --confirm to proceed."
  exit 1
fi

echo "Starting teardown..."

helm uninstall keycloak   --namespace keycloak    2>/dev/null || true
helm uninstall dapr       --namespace dapr-system 2>/dev/null || true
helm uninstall kong       --namespace kong        2>/dev/null || true
helm uninstall redis      --namespace redis       2>/dev/null || true
helm uninstall cert-manager --namespace cert-manager 2>/dev/null || true

kubectl delete -f k8s/apps/sample-app/ --ignore-not-found
kubectl delete -f k8s/dapr/components/ --ignore-not-found
kubectl delete -f k8s/dapr/dapr-configuration.yaml --ignore-not-found
kubectl delete -f k8s/kong/plugins/ --ignore-not-found
kubectl delete -f k8s/cert-manager/cluster-issuer.yaml --ignore-not-found
kubectl delete -f k8s/keycloak/realm-config.yaml --ignore-not-found
kubectl delete -f k8s/namespaces/namespaces.yaml --ignore-not-found

echo "Teardown complete."
