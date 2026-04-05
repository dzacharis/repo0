package main

import future.keywords.in

# All Deployments must have resource limits set
deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits
  msg := sprintf("Deployment '%s': container '%s' is missing resource limits", [input.metadata.name, container.name])
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests
  msg := sprintf("Deployment '%s': container '%s' is missing resource requests", [input.metadata.name, container.name])
}

# No 'latest' image tags allowed
deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  endswith(container.image, ":latest")
  msg := sprintf("Deployment '%s': container '%s' uses ':latest' image tag", [input.metadata.name, container.name])
}

# Deployments must not run as root
deny[msg] {
  input.kind == "Deployment"
  not input.spec.template.spec.securityContext.runAsNonRoot
  msg := sprintf("Deployment '%s': pods must set runAsNonRoot: true", [input.metadata.name])
}

# All Ingresses must reference a TLS secret
warn[msg] {
  input.kind == "Ingress"
  count(input.spec.tls) == 0
  msg := sprintf("Ingress '%s': no TLS configuration found", [input.metadata.name])
}

# All containers should have liveness and readiness probes
warn[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.livenessProbe
  msg := sprintf("Deployment '%s': container '%s' is missing livenessProbe", [input.metadata.name, container.name])
}

warn[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.readinessProbe
  msg := sprintf("Deployment '%s': container '%s' is missing readinessProbe", [input.metadata.name, container.name])
}
