# Architecture

> **Visual diagrams**: See [diagrams.md](./diagrams.md) for Mermaid diagrams covering the overall
> platform topology, OIDC auth flow, Dapr runtime, CI/CD pipeline, and cloud provider topologies.
> All diagrams render natively on GitHub.

## Overview

This platform is a Kubernetes-native infrastructure stack composed of:

- **Kong** — edge API gateway and ingress controller
- **Dapr** — distributed application runtime (state, pub/sub, secrets, service invocation)
- **Keycloak** — identity and access management (OIDC/OAuth2)
- **cert-manager** — automated TLS certificate lifecycle
- **Redis** — shared backing store for Dapr state/pub/sub and Kong rate-limiting

## Traffic Flow

```
Client (browser / API consumer)
        │
        │ HTTPS (TLS terminated at Kong)
        ▼
┌───────────────────────────────────────────────┐
│  Kong Ingress Controller  (namespace: kong)   │
│                                               │
│  1. TLS termination (cert-manager cert)       │
│  2. OIDC token validation → Keycloak          │
│  3. Rate limiting (Redis-backed, cluster-wide)│
│  4. CORS headers                              │
│  5. Request ID injection                      │
│  6. Route to upstream service                 │
└─────────────────────┬─────────────────────────┘
                      │ HTTP (plain, inside cluster)
                      ▼
┌───────────────────────────────────────────────┐
│  Application Pod  (namespace: apps)           │
│                                               │
│  ┌───────────────┐   ┌─────────────────────┐ │
│  │  App container│◄──│  Dapr sidecar       │ │
│  │  :8080        │   │  :3500 (HTTP API)   │ │
│  └───────┬───────┘   │  :50001 (gRPC API)  │ │
│          │           │  :9090 (metrics)    │ │
│          └───────────┤                     │ │
│                      └──────────┬──────────┘ │
└─────────────────────────────────┼────────────┘
                                  │ Dapr APIs (mTLS)
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
      ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
      │ State Store  │  │   Pub/Sub        │  │ Secret Store │
      │ (Redis)      │  │   (Redis)        │  │ (K8s Secrets)│
      └──────────────┘  └──────────────────┘  └──────────────┘
```

## Namespace Layout

| Namespace | Contents |
|-----------|----------|
| `kong` | Kong Ingress Controller pods, CRDs |
| `dapr-system` | Dapr operator, sentry, placement, sidecar injector |
| `keycloak` | Keycloak + PostgreSQL |
| `cert-manager` | cert-manager + webhook |
| `redis` | Redis (shared) |
| `apps` | Application workloads (Dapr-injection enabled) |

## Authentication Flow (OIDC via Kong + Keycloak)

```
1. Client requests a protected endpoint through Kong
2. Kong's OIDC plugin checks for a valid Bearer token in Authorization header
3. If absent/invalid → Kong redirects to Keycloak authorization endpoint
4. User authenticates with Keycloak (username/password, MFA, social login, etc.)
5. Keycloak issues an authorization code → Kong exchanges it for tokens
6. Kong validates the access token (signature, expiry, audience)
7. Kong forwards user claims (sub, email, roles) as HTTP headers to the upstream app
8. App trusts these headers — no direct Keycloak dependency in app code
```

Configured Keycloak clients:
- `kong` — confidential client used by the Kong OIDC plugin
- `frontend` — public client for browser SPAs
- `sample-service` — bearer-only client for backend service token validation

## Dapr Application Runtime

Dapr injects a sidecar proxy into each pod in namespaces with `dapr.io/enabled: "true"`.

Applications interact with Dapr via localhost HTTP/gRPC — no SDK required:

```
# Save state
PUT http://localhost:3500/v1.0/state/statestore

# Publish event
POST http://localhost:3500/v1.0/publish/pubsub/order-events

# Invoke another service
POST http://localhost:3500/v1.0/invoke/other-service/method/endpoint

# Get secret
GET http://localhost:3500/v1.0/secrets/kubernetes/my-secret
```

All sidecar-to-sidecar traffic is encrypted with mTLS (Dapr Sentry CA).

## mTLS Boundaries

| Traffic path | Encryption |
|---|---|
| Client → Kong | TLS (cert-manager / Let's Encrypt) |
| Kong → App pod | Plain HTTP (cluster-internal) |
| App sidecar → App sidecar (Dapr service invocation) | Dapr mTLS (Sentry-issued certs) |
| Kong → Redis (rate-limit) | Plain (cluster-internal); enable TLS for compliance |
| Dapr → Redis | Plain (cluster-internal); enable TLS for compliance |

## Design Decisions

### Why Dapr over a service mesh (Istio)?

Dapr provides application-level abstractions (state, pub/sub, secrets) that a pure network mesh doesn't. Adding Istio later for L4/L7 observability is compatible — disable Dapr mTLS and let Istio handle it.

### Why Kong over Nginx Ingress?

Kong's native plugin ecosystem (OIDC, rate-limiting, request transformation, correlation IDs) requires no custom annotations or Lua hacks. The `KongPlugin` CRD makes plugin config declarative and git-trackable.

### Why Keycloak self-hosted?

Full control over realm configuration, client definitions, and token claims. The `realm-export.json` approach makes the entire realm config reproducible from git.

### Why Kustomize for app manifests (not Helm)?

Kustomize overlays produce clean, reviewable diffs in PRs. Helm is reserved for third-party components where the chart encapsulates significant complexity.

### Redis shared between Dapr and Kong

Acceptable for dev/staging. For production at scale, split into two instances to avoid noisy-neighbor problems on rate-limiting vs. state store workloads.
