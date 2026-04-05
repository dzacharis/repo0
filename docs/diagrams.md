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

## 4. CI/CD Pipelines (Segregated)

Three independent pipelines, each with a single responsibility and its own trigger filters.

```mermaid
flowchart TD
    Dev["👩‍💻 Developer\npushes code"] --> PR["Pull Request / Push"]

    PR --> SecTrig{"security.yaml\ntrigger\n(all pushes +\nnightly cron)"}
    PR --> InfraTrig{"infrastructure.yaml\ntrigger\n(infra paths only)"}
    PR --> AppTrig{"applications.yaml\ntrigger\n(app paths only)"}

    subgraph SecPipeline["🔐 security.yaml"]
        S1["🔑 Gitleaks\nSecret Detection"]
        S2["🔍 Trivy IaC\nK8s + Terraform\n→ SARIF"]
        S3["🛡️ OPA/Conftest\nResource limits\nNo :latest\nrunAsNonRoot"]
        S4["📋 Checkov\nCIS Benchmarks\nK8s + Terraform"]
        S5["📦 Syft + Grype\nSBOM + vuln scan\n(master only)"]
        S6["🐳 Image Scan\nTrivy container\n(nightly)"]
        S1 --- S2 --- S3 --- S4
        S4 --- S5
        S6
    end

    subgraph InfraPipeline["🏗️ infrastructure.yaml"]
        I1["✅ Validate\nkubeconform\nHelm dry-run"]
        I2["📐 Terraform Plan\n(PR only, all providers)"]
        I3["🚀 Deploy Dev\ncert-manager→Redis\n→Kong→Dapr\n→Keycloak→OpenSearch"]
        I4["👤 Reviewer Gate\n(prod only)"]
        I5["🚀 Deploy Prod\nHA mode\n3 replicas"]
        I6["🩺 Infra Smoke Test\ncluster health\nOpenSearch health"]
        I1 --> I2
        I1 --> I3 --> I6
        I1 --> I4 --> I5 --> I6
    end

    subgraph AppPipeline["🚀 applications.yaml"]
        A1["✅ Validate\nApp manifests\nKustomize overlays"]
        A2["🧪 Unit Tests\n(your test runner)"]
        A3["🐳 Build & Push\nGHCR / ACR / ECR\nSLSA provenance\nSBOM attach"]
        A4["🔍 Image Scan\nTrivy CRITICAL\n→ block on fail"]
        A5["🚀 Deploy Dev\nkustomize edit image\nkubectl apply\n→ smoke test"]
        A6["👤 Reviewer Gate\n(prod)"]
        A7["🚀 Deploy Prod\nkustomize edit image\nkubectl apply\n→ extended test"]
        A8["⏪ Auto-Rollback\non failure"]
        A1 --> A2 --> A3 --> A4 --> A5
        A4 --> A6 --> A7
        A7 -->|failure| A8
    end

    SecTrig --> SecPipeline
    InfraTrig --> InfraPipeline
    AppTrig --> AppPipeline
```

### Pipeline responsibility matrix

| Concern | security.yaml | infrastructure.yaml | applications.yaml |
|---------|:---:|:---:|:---:|
| Secret / credential leak detection | ✅ | | |
| IaC misconfiguration scan | ✅ | | |
| OPA policy enforcement | ✅ | | |
| CIS benchmark checks | ✅ | | |
| SBOM generation | ✅ | | |
| Manifest validation (infra) | | ✅ | |
| Terraform plan / validate | | ✅ | |
| Helm chart deployments | | ✅ | |
| Kong / Dapr / Keycloak deploy | | ✅ | |
| OpenSearch / Fluentbit deploy | | ✅ | |
| App manifest validation | | | ✅ |
| Container image build & push | | | ✅ |
| Container vulnerability scan | | | ✅ |
| App deployment (Kustomize) | | | ✅ |
| Rollback on failure | | | ✅ |

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

---

## 7. Azure (AKS) Topology

```mermaid
graph TB
    subgraph Azure["Microsoft Azure"]
        subgraph RG["Resource Group: platform-rg"]
            subgraph VNET["Virtual Network (Azure CNI)"]
                subgraph AKS["AKS Cluster\n(Workload Identity + Defender)"]
                    direction TB
                    Kong5["Kong\n(Azure Standard LB)"]
                    Apps5["Apps + Dapr\n(Workload Identity)"]
                    KC5["Keycloak"]
                end

                subgraph ManagedSvcs3["Managed Services"]
                    PG[("Azure Database\nfor PostgreSQL\nFlexible Server\n(Keycloak DB)")]
                    Redis2[("Azure Cache\nfor Redis\nTLS :6380\n(Dapr State/PubSub)")]
                    ACR["Azure Container\nRegistry (ACR)"]
                end

                ALB["Azure Standard\nLoad Balancer"]
            end
        end

        KV["Azure Key Vault\n(CSI Secrets Provider)"]
        LA["Log Analytics\nWorkspace\n(AKS Monitor +\nDefender)"]
        DNS2["Azure DNS Zone"]
        WI["Azure Workload\nIdentity\n(no SPN secrets)"]
    end

    Internet3(("🌐")) --> DNS2 --> ALB --> Kong5
    Kong5 --> Apps5
    KC5 --- PG
    Apps5 -->|Dapr TLS| Redis2
    KV -.->|CSI mount| AKS
    LA -.->|OMS agent| AKS
    WI -.->|federated| AKS
```

---

## 8. Observability — Log Flow (OpenSearch)

```mermaid
flowchart LR
    subgraph Sources["Log Sources"]
        KongLog["Kong\nHTTP Log plugin\n→ Fluentbit HTTP"]
        AppLog["App Containers\n/var/log/containers\n(structured JSON)"]
        DaprLog["Dapr Sidecar\n(JSON)"]
        KCLog["Keycloak\naudit events"]
        DaprBind["App\n(Dapr binding\naudit events)"]
    end

    subgraph Collector["Namespace: logging"]
        FB2["Fluentbit DaemonSet\n─────────────────\nkubernetes filter\nrewrite_tag (security)\nJSON parser"]
    end

    subgraph OS["Namespace: opensearch"]
        OSNode["OpenSearch\n3-node cluster\nISM lifecycle policies"]
        OSDash["OpenSearch Dashboards\n(OIDC via Keycloak)"]
    end

    subgraph Indices2["Index Strategy"]
        PI["platform-logs-*\n30-day retention\n(hot→warm→delete)"]
        SI["security-events-*\n90-day retention\n(keycloak, cert-manager)"]
        AI["platform-audit\n(Dapr binding output)"]
    end

    KongLog & AppLog & DaprLog --> FB2
    KCLog --> FB2
    FB2 -->|app logs| PI
    FB2 -->|"security ns\n(rewrite_tag)"| SI
    DaprBind -->|POST /v1.0/bindings/opensearch-audit| AI
    PI & SI & AI --> OSNode
    OSNode --> OSDash
```

---

## 9. Maltego Transform Hub — Auth & Execution Flow

```mermaid
sequenceDiagram
    autonumber
    actor Op as Maltego Operator
    participant KC as Keycloak<br/>(maltego-hub realm)
    participant Hub as Transform Hub<br/>(FastAPI)
    participant T as Transform Logic<br/>(dnspython / RDAP / ip-api)

    rect rgb(240,248,255)
        Note over Op,Hub: One-time registration (admin scope required)
        Op->>Hub: POST /api/v1/clients/register<br/>Authorization: Bearer &lt;admin-token&gt;<br/>{"client_name": "alice-laptop"}
        Hub->>KC: POST /admin/realms/maltego-hub/clients<br/>(Keycloak Admin API)
        KC-->>Hub: 201 Created
        Hub-->>Op: {client_id, client_secret, token_url, instructions}
    end

    rect rgb(255,248,240)
        Note over Op,KC: Token acquisition (Maltego does this automatically)
        Op->>KC: POST /realms/maltego-hub/protocol/openid-connect/token<br/>grant_type=client_credentials<br/>scope=transforms:execute
        KC-->>Op: {access_token, expires_in: 300}
    end

    rect rgb(240,255,240)
        Note over Op,T: Transform discovery (import once into Maltego)
        Op->>Hub: GET /api/v2/manifest<br/>Authorization: Bearer &lt;token&gt;
        Hub-->>Op: {transforms: [...], tokenUrl, hubUrl}
        Note over Op: Maltego imports all transforms<br/>from manifest automatically
    end

    rect rgb(248,240,255)
        Note over Op,T: Transform execution
        Op->>Hub: POST /api/v2/transforms/DomainToIP<br/>Authorization: Bearer &lt;token&gt;<br/>Content-Type: application/xml<br/>&lt;MaltegoMessage&gt;...&lt;/MaltegoMessage&gt;
        Hub->>Hub: Validate JWT<br/>• RS256 sig vs JWKS<br/>• aud = transform-hub<br/>• scope: transforms:execute<br/>• exp not expired
        Hub->>T: DomainToIP.run(entity="example.com")
        T->>T: dns.resolver.resolve("example.com", "A")
        T-->>Hub: [IPv4Address: 93.184.216.34]
        Hub-->>Op: &lt;MaltegoTransformResponseMessage&gt;<br/>  &lt;Entity Type="maltego.IPv4Address"&gt;<br/>    &lt;Value&gt;93.184.216.34&lt;/Value&gt;<br/>  &lt;/Entity&gt;<br/>&lt;/MaltegoTransformResponseMessage&gt;
    end
```
