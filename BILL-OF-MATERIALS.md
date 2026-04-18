# Bill of Materials

Complete inventory of every software component, tool, and external dependency used by this
platform. Sections follow the [NTIA minimum elements](https://www.ntia.gov/sites/default/files/publications/sbom_minimum_elements_report_0.pdf)
for an SBOM.

> **Auto-generated alternative**: the `applications.yaml` CI pipeline attaches a machine-readable
> SPDX SBOM (via Syft) to every container image release. This document is the human-readable
> companion.

---

## Runtime — Kubernetes Platform Components

All components are deployed via Helm unless noted.

| Component | Role | Version | Helm Chart | Chart Repo |
|-----------|------|---------|-----------|-----------|
| **Kong Ingress Controller** | API gateway, TLS, auth plugins, rate-limiting | `3.6` | `kong/ingress 0.4.x` | `https://charts.konghq.com` |
| **Dapr** | Distributed app runtime (state, pub/sub, secrets, bindings) | `1.13.x` | `dapr/dapr 1.13.x` | `https://dapr.github.io/helm-charts` |
| **Keycloak** | OIDC / OAuth2 identity provider | `24.0` | `bitnami/keycloak 21.x` | `https://charts.bitnami.com/bitnami` |
| **cert-manager** | Automated TLS certificate provisioning (Let's Encrypt) | `v1.14.x` | `cert-manager/cert-manager v1.14.x` | `https://charts.jetstack.io` |
| **OpenSearch** | Log aggregation, search, security analytics | `2.14` | `opensearch/opensearch 2.x` | `https://opensearch-project.github.io/helm-charts` |
| **OpenSearch Dashboards** | Kibana-compatible analytics UI | `2.14` | `opensearch/opensearch-dashboards 2.x` | `https://opensearch-project.github.io/helm-charts` |
| **Fluent Bit** | DaemonSet log collector and router | `3.1` | `fluent/fluent-bit 0.47.x` | `https://fluent.github.io/helm-charts` |
| **Redis** | Backing store for Dapr state/pub-sub and Kong rate-limiting | `7.2` | `bitnami/redis` | `https://charts.bitnami.com/bitnami` |

---

## Runtime — Application (Transform Hub)

### Container Base Image

| Component | Version | Source | Purpose |
|-----------|---------|--------|---------|
| `python` | `3.12-slim` | Docker Hub official | Application runtime |
| `libxml2` | OS package | Debian bookworm | XML parsing (lxml) |
| `libxslt1.1` | OS package | Debian bookworm | XSLT transforms (lxml) |

### Python Dependencies (`src/transform-hub/requirements.txt`)

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| `fastapi` | `0.111.0` | MIT | HTTP API framework |
| `uvicorn[standard]` | `0.29.0` | BSD-3 | ASGI server |
| `httpx` | `0.27.0` | BSD-3 | Async HTTP client (JWKS fetch) |
| `pydantic` | `2.7.1` | MIT | Data validation and settings |
| `pydantic-settings` | `2.2.1` | MIT | Settings from env vars |
| `python-jose[cryptography]` | `3.3.0` | MIT | JWT decode and validation |
| `lxml` | `5.2.1` | BSD-3 | Maltego XML serialisation |
| `requests` | `2.31.0` | Apache-2.0 | Sync HTTP (Keycloak Admin API) |
| `python-multipart` | `0.0.9` | Apache-2.0 | Form-data parsing |
| `cachetools` | `5.3.3` | MIT | JWKS TTL cache |
| `dnspython` | `2.6.1` | ISC | DNS resolution transforms |

---

## Infrastructure — Terraform Providers

| Provider | Version Constraint | Registry | Used By |
|----------|--------------------|----------|---------|
| `hashicorp/google` | `~> 5.0` | registry.terraform.io | `terraform/gcp/` |
| `hashicorp/aws` | `~> 5.0` | registry.terraform.io | `terraform/aws/` |
| `hashicorp/azurerm` | `~> 3.100` | registry.terraform.io | `terraform/azure/` |
| `rancher/rancher2` | `~> 4.0` | registry.terraform.io | `terraform/rancher/` |
| `hashicorp/kubernetes` | `~> 2.27` | registry.terraform.io | all modules |
| `hashicorp/helm` | `~> 2.13` | registry.terraform.io | all modules |
| `hashicorp/random` | `~> 3.6` | registry.terraform.io | password generation |
| `terraform-aws-modules/vpc` | `~> 5.0` | registry.terraform.io | `terraform/aws/` |
| `terraform-aws-modules/eks` | `~> 20.0` | registry.terraform.io | `terraform/aws/` |

### Terraform CLI

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| Terraform | `>= 1.7` | Used in CI via `hashicorp/setup-terraform@v3` |

---

## CI/CD — GitHub Actions

### Reusable Actions

| Action | Version Pinned | Purpose | Used In |
|--------|---------------|---------|---------|
| `actions/checkout` | `v4` | Repository checkout | all workflows |
| `actions/upload-artifact` | `v4` | Upload SARIF/SBOM/reports | security, docs |
| `actions/setup-node` | `v4` | Node.js for mermaid-js | docs |
| `actions/github-script` | `v7` | Post PR comments | docs |
| `docker/setup-buildx-action` | `v3` | Multi-arch Docker builds | applications |
| `docker/login-action` | `v3` | GHCR authentication | applications |
| `docker/metadata-action` | `v5` | Image tags + labels | applications |
| `docker/build-push-action` | `v5` | Build and push images | applications |
| `azure/setup-helm` | `v4` | Helm CLI | infrastructure |
| `azure/k8s-set-context` | `v4` | Kubeconfig from secret | infrastructure, applications |
| `hashicorp/setup-terraform` | `v3` | Terraform CLI | infrastructure |
| `aquasecurity/trivy-action` | `master` | IaC + image vulnerability scan | security, applications |
| `gitleaks/gitleaks-action` | `v2` | Secret scanning | security |
| `bridgecrewio/checkov-action` | `master` | CIS benchmark checks | security |
| `anchore/sbom-action/download-syft` | `v0` | Generate SPDX SBOM | security |
| `anchore/scan-action` | `v3` | Grype CVE scan | security |
| `github/codeql-action/upload-sarif` | `v3` | Upload SARIF to GitHub Security tab | security, applications |
| `DavidAnson/markdownlint-cli2-action` | `v16` | Markdown linting | docs |
| `lycheeverse/lychee-action` | `v1` | Link checking | docs |
| `streetsidesoftware/cspell-action` | `v6` | Spell checking | docs |

### CLI Tools (installed at runtime in CI)

| Tool | Version | Purpose | Workflow |
|------|---------|---------|---------|
| `kubectl` | latest stable | Kubernetes CLI | infrastructure, applications |
| `helm` | latest stable | Chart management | infrastructure |
| `kustomize` | latest stable | Overlay rendering | applications |
| `kubeconform` | latest | Manifest schema validation | infrastructure |
| `conftest` | latest | OPA policy testing | security |
| `mmdc` (mermaid-js) | `@latest` | Mermaid diagram validation | docs |
| `lychee` | (via action) | Dead-link checker | docs |
| `markdownlint-cli2` | (via action) | Markdown linter | docs |

---

## External Services and Integrations

| Service | Type | Purpose | Authentication |
|---------|------|---------|---------------|
| Let's Encrypt (ACME) | Public CA | TLS certificate issuance | ACME HTTP-01 challenge via Kong |
| GHCR (GitHub Container Registry) | OCI registry | Store and distribute container images | `GITHUB_TOKEN` (CI) |
| ip-api.com | REST API | IP geolocation (transform) | None (rate-limited, no key) |
| rdap.org | REST API | WHOIS/RDAP domain lookups | None (public) |

---

## Policy and Compliance

| Policy | Tool | Location | What it enforces |
|--------|------|----------|-----------------|
| Resource limits required | OPA / Conftest | `policies/deployments.rego` | All containers must declare CPU + memory limits |
| No `latest` image tags | OPA / Conftest | `policies/deployments.rego` | Images must use pinned tags |
| `runAsNonRoot: true` | OPA / Conftest | `policies/deployments.rego` | No root containers |
| TLS on all Ingress | OPA / Conftest | `policies/deployments.rego` | All ingress objects must have TLS configured |
| CIS Kubernetes Benchmark | Checkov | CI (`security.yaml`) | IaC hardening |
| Image CVE threshold | Trivy / Grype | CI (`security.yaml`, `applications.yaml`) | CRITICAL CVEs block image promotion |
| Secret scanning | Gitleaks | CI (`security.yaml`) | No credentials committed to git |

---

## License Summary

| License | Packages / Tools |
|---------|-----------------|
| MIT | FastAPI, Pydantic, pydantic-settings, python-jose, cachetools |
| BSD-3 | uvicorn, httpx, lxml, dnspython |
| Apache-2.0 | requests, python-multipart |
| ISC | dnspython (dual MIT/ISC) |
| Apache-2.0 | Kong, Dapr, cert-manager, Fluentbit, Keycloak, OpenSearch |
| SSPL-1.0* | Redis (server binary) — *note: client libs are MIT* |

> **SSPL note**: Redis 7.x server is SSPL-licensed. The platform uses Bitnami's Redis Helm chart
> which packages the official binary. If SSPL is a concern for your deployment model, consider
> Valkey (Linux Foundation fork, BSD-3) as a drop-in replacement via the Dapr component YAML.

---

## Version Update Policy

| Component type | Update cadence | Automated? |
|---------------|---------------|-----------|
| Python dependencies | Monthly | Renovate / Dependabot (ROADMAP item D-03) |
| Helm chart versions | Quarterly or on CVE | Manual PR |
| GitHub Actions | Quarterly | Renovate (ROADMAP item G-03) |
| Base Docker image | Monthly | Renovate |
| Terraform providers | Quarterly | Renovate |
| Kubernetes version | Annual (per cloud provider LTS) | Manual |
