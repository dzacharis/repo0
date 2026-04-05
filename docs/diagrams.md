# Platform Diagrams

All diagrams use [Mermaid](https://mermaid.js.org/) and render natively on GitHub.

---

## 1. Overall Platform Architecture

```mermaid
graph TB
    subgraph Internet["Internet / Clients"]
        Browser["🌐 Browser / SPA"]
        APIClient["📱 API Client / Mobile"]
        Service["⚙️ External Service"]
    end

    subgraph CloudLB["Cloud Load Balancer"]
        LB["☁️ L4 Load Balancer\n(GCP: Regional LB / AWS: NLB)"]
    end

    subgraph KongNS["Namespace: kong"]
        Kong["🦍 Kong Ingress Controller\n─────────────────\nTLS Termination\nOIDC → Keycloak\nJWT Validation\nRate Limiting\nCORS\nRequest ID"]
    end

    subgraph CertNS["Namespace: cert-manager"]
        CertMgr["🔐 cert-manager\n─────────────────\nLet's Encrypt ACME\nAuto-renew TLS certs"]
    end

    subgraph KeycloakNS["Namespace: keycloak"]
        KC["🔑 Keycloak\n─────────────────\nOIDC / OAuth2\nRealm: myrealm\nClients: kong, frontend\nPostgreSQL backend"]
        KCDB[("🐘 PostgreSQL")]
        KC --- KCDB
    end

    subgraph AppsNS["Namespace: apps"]
        subgraph Pod["Application Pod"]
            App["📦 App Container\n:8080"]
            Dapr["🔷 Dapr Sidecar\nHTTP :3500\ngRPC :50001"]
        end
        App <-->|localhost| Dapr
    end

    subgraph DaprNS["Namespace: dapr-system"]
        DaprOp["Operator"]
        DaprSentry["Sentry (mTLS CA)"]
        DaprPlacement["Placement (Actors)"]
        DaprInjector["Sidecar Injector"]
    end

    subgraph RedisNS["Namespace: redis"]
        Redis[("🟥 Redis\nState Store\nPub/Sub")]
    end

    Browser & APIClient & Service --> LB
    LB --> Kong
    Kong -->|OIDC token check| KC
    Kong -->|"HTTP (authn passed)"| App
    CertMgr -.->|TLS cert| Kong
    Dapr -->|State / Pub-Sub| Redis
    Dapr -.->|mTLS cert| DaprSentry
    DaprInjector -.->|inject sidecar| Pod
```

---

## 2. Authentication Flow (OIDC via Kong + Keycloak)

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant Kong as Kong Gateway
    participant KC as Keycloak
    participant App as App Service

    User->>Kong: GET /api/v1/resource
    Kong->>Kong: Check Authorization header

    alt No token / invalid token
        Kong-->>User: 302 Redirect → Keycloak /auth
        User->>KC: GET /realms/myrealm/protocol/openid-connect/auth
        KC-->>User: Login page
        User->>KC: POST credentials
        KC-->>User: 302 Redirect with ?code=AUTH_CODE
        User->>Kong: GET /callback?code=AUTH_CODE
        Kong->>KC: POST /token (exchange code)
        KC-->>Kong: access_token + refresh_token + id_token
        Kong->>Kong: Validate token (sig, exp, aud)
        Kong-->>User: Set cookie, redirect to original URL
    end

    alt Valid Bearer token
        Kong->>KC: POST /token/introspect (optional)
        KC-->>Kong: {"active": true, "sub": "...", "roles": [...]}
    end

    Kong->>App: GET /api/v1/resource\nX-User-Id: <sub>\nX-User-Email: <email>\nX-User-Roles: admin,user
    App-->>Kong: 200 OK (response)
    Kong-->>User: 200 OK (response)
```

---

## 3. Dapr Runtime Architecture

```mermaid
graph LR
    subgraph Pod_A["Pod: service-a"]
        A_App["service-a\n:8080"]
        A_Dapr["dapr sidecar\n:3500 / :50001"]
        A_App <-->|localhost| A_Dapr
    end

    subgraph Pod_B["Pod: service-b"]
        B_App["service-b\n:8080"]
        B_Dapr["dapr sidecar\n:3500 / :50001"]
        B_App <-->|localhost| B_Dapr
    end

    subgraph DaprCP["Dapr Control Plane (dapr-system)"]
        Sentry["🔐 Sentry\n(mTLS CA)"]
        Operator["Operator\n(CRD watcher)"]
        Placement["Placement\n(Actor registry)"]
        Injector["Sidecar Injector\n(webhook)"]
    end

    subgraph Backing["Backing Services"]
        Redis[("Redis\nState + PubSub")]
        K8sSecrets[("K8s Secrets\nSecret Store")]
    end

    A_Dapr <-->|"mTLS (Dapr)"| B_Dapr
    A_Dapr & B_Dapr <-->|State API| Redis
    A_Dapr & B_Dapr <-->|Pub/Sub API| Redis
    A_Dapr & B_Dapr <-->|Secrets API| K8sSecrets
    Sentry -.->|issue workload certs| A_Dapr & B_Dapr
    Operator -.->|reconcile Components| A_Dapr & B_Dapr
    Placement -.->|actor location| A_Dapr & B_Dapr

    style Sentry fill:#d4edda
    style Redis fill:#ffcccc
```

---

## 4. CI/CD Pipeline

```mermaid
flowchart TD
    Dev["👩‍💻 Developer\npushes code"] --> PR["Pull Request"]

    subgraph CI["CI Workflow (ci.yaml) — runs on every push/PR"]
        Lint["📋 Lint\nkubeval / yamllint\nHelm dry-run"]
        Kustomize["🗂️ Kustomize\nkubeconform validate\ndev + prod overlays"]
        OPA["🛡️ OPA / Conftest\nresource limits\nno :latest tags\nrunAsNonRoot\nTLS required"]
        Trivy["🔍 Security Scan\nTrivy IaC (SARIF)\nCheckov policies"]
        Build["🐳 Build & Push\nDocker image\n→ GHCR\n(master branch only)"]
        ImageScan["🔍 Image Scan\nTrivy container scan\nfail on CRITICAL"]

        Lint --> Kustomize --> OPA --> Trivy --> Build --> ImageScan
    end

    subgraph DeployDev["Deploy Dev (deploy-dev.yaml) — auto on master merge"]
        DevInfra["🏗️ Infrastructure\ncert-manager → Kong\n→ Dapr → Keycloak"]
        DevApps["🚀 Applications\nkubectl apply\n(dev overlay)"]
        DevSmoke["✅ Smoke Tests\nhealth endpoint\ncurl through Kong"]

        DevInfra --> DevApps --> DevSmoke
    end

    subgraph DeployProd["Deploy Prod (deploy-prod.yaml) — manual + approval"]
        Approval["👤 Required Reviewer\nGitHub Environment\nprotection rule"]
        Confirm["🔒 Confirm string\n'deploy-prod'"]
        ProdInfra["🏗️ Infrastructure\nHA mode (3 replicas)"]
        ProdApps["🚀 Applications\nkustomize edit image\n(prod overlay)"]
        ProdSmoke["✅ Extended Tests\nOIDC flow\nDapr pub/sub roundtrip"]
        Rollback["⏪ Auto-Rollback\non failure"]

        Approval --> Confirm --> ProdInfra --> ProdApps --> ProdSmoke
        ProdApps -->|failure| Rollback
    end

    PR --> CI
    CI -->|merge to master| DeployDev
    DeployDev -->|tag vX.Y.Z| DeployProd
```

---

## 5. Cloud Provider Topology

### Google Cloud Platform (GKE)

```mermaid
graph TB
    subgraph GCP["Google Cloud Platform"]
        subgraph VPC["VPC Network"]
            subgraph Region["Region: us-central1"]
                subgraph GKE["GKE Autopilot Cluster"]
                    direction TB
                    Kong2["Kong\n(Workload Identity\n→ Cloud Armor)"]
                    Apps2["Apps + Dapr"]
                    KC2["Keycloak"]
                end

                subgraph ManagedSvcs["Managed Services"]
                    CloudSQL[("☁️ Cloud SQL\nPostgreSQL\n(Keycloak DB)"]
                    Memorystore[("☁️ Memorystore\nRedis\n(Dapr State/PubSub)"]
                    ArtifactReg["Artifact Registry\n(Container images)"]
                end

                GCLB["☁️ Cloud Load Balancer\n+ Cloud Armor WAF"]
            end
        end

        CloudDNS["Cloud DNS"]
        CertAuth["Google-Managed\nCertificates\n(or cert-manager\n+ Let's Encrypt)"]
        WorkloadID["Workload Identity\n(no key files)"]
        SecretMgr["Secret Manager\n(via ESO or\nDapr secret store)"]
    end

    Internet(("🌐")) --> CloudDNS --> GCLB --> Kong2
    Kong2 --> Apps2
    KC2 --- CloudSQL
    Apps2 -->|Dapr| Memorystore
    WorkloadID -.-> GKE
    SecretMgr -.-> GKE
```

### Amazon Web Services (EKS)

```mermaid
graph TB
    subgraph AWS["Amazon Web Services"]
        subgraph VPC2["VPC"]
            subgraph EKS["EKS Cluster (Fargate / Managed Nodes)"]
                Kong3["Kong\n(IRSA → AWS WAF)"]
                Apps3["Apps + Dapr"]
                KC3["Keycloak"]
            end

            subgraph ManagedSvcs2["Managed Services"]
                RDS[("☁️ RDS\nPostgreSQL\n(Keycloak DB)")]
                ElastiCache[("☁️ ElastiCache\nRedis\n(Dapr State/PubSub)")]
                ECR["ECR\n(Container images)"]
            end

            NLB["☁️ NLB\n(Kong proxy)"]
        end

        Route53["Route 53"]
        ACM["ACM\n(TLS certs)"]
        IRSA["IAM Roles for\nService Accounts"]
        ASM["AWS Secrets Manager\n(via ESO)"]
    end

    Internet2(("🌐")) --> Route53 --> NLB --> Kong3
    Kong3 --> Apps3
    KC3 --- RDS
    Apps3 -->|Dapr| ElastiCache
    IRSA -.-> EKS
    ASM -.-> EKS
```

### Rancher (Cloud-Agnostic)

```mermaid
graph TB
    subgraph Rancher["Rancher Management Plane"]
        RancherUI["Rancher UI / API"]
        Fleet["Fleet\n(GitOps)"]
        Monitoring["Rancher Monitoring\n(Prometheus + Grafana)"]
        Logging["Rancher Logging\n(Loki)"]
    end

    subgraph Downstream["Downstream Clusters"]
        subgraph RKE2["RKE2 Cluster"]
            Kong4["Kong"]
            Apps4["Apps + Dapr"]
            KC4["Keycloak"]
        end
    end

    subgraph GitRepo["Git Repository"]
        Manifests["k8s/ manifests\n.github/ workflows"]
    end

    Fleet -->|sync| RKE2
    GitRepo -->|webhook| Fleet
    RancherUI --> RKE2
    Monitoring & Logging -.-> RKE2
```

---

## 6. Namespace & Network Policy

```mermaid
graph LR
    subgraph Cluster["Kubernetes Cluster"]
        subgraph kong-ns["kong (namespace)"]
            KongPod["Kong pods"]
        end

        subgraph apps-ns["apps (namespace)\ndapr.io/enabled: true"]
            AppPod["App pods\n+ Dapr sidecar"]
        end

        subgraph dapr-ns["dapr-system (namespace)"]
            DaprPods["Dapr control plane"]
        end

        subgraph keycloak-ns["keycloak (namespace)"]
            KCPod["Keycloak pods"]
            PGPod["PostgreSQL pods"]
        end

        subgraph redis-ns["redis (namespace)"]
            RedisPod["Redis pods"]
        end

        subgraph cert-ns["cert-manager (namespace)"]
            CertPod["cert-manager pods"]
        end
    end

    KongPod -->|":8080 HTTP"| AppPod
    KongPod -->|":8080 HTTP"| KCPod
    AppPod -->|":6379 TCP (via Dapr)"| RedisPod
    DaprPods -.->|"webhook / mTLS"| AppPod
    KCPod --> PGPod
    CertPod -.->|"ACME challenge"| KongPod

    style kong-ns fill:#fff3cd
    style apps-ns fill:#d1ecf1
    style dapr-ns fill:#d4edda
    style keycloak-ns fill:#f8d7da
    style redis-ns fill:#ffe5e5
    style cert-ns fill:#e2e3e5
```
