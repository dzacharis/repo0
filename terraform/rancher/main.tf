# ── Rancher Cluster (RKE2) ────────────────────────────────────────────────────
resource "rancher2_cluster_v2" "platform" {
  name              = var.cluster_name
  kubernetes_version = var.kubernetes_version
  enable_network_policy = true

  rke_config {
    machine_global_config = <<-EOT
      cni: canal
      disable-kube-proxy: false
      etcd-expose-metrics: false
      profile: cis
    EOT

    machine_selector_config {
      label_selector {}
      config = <<-EOT
        protect-kernel-defaults: true
      EOT
    }

    # Upgrade strategy
    upgrade_strategy {
      control_plane_concurrency  = "1"
      control_plane_drain_options {
        enabled                  = true
        delete_empty_dir_data    = true
        pod_selector             = ""
        skip_wait_for_delete_timeout_seconds = 60
        ignore_daemonsets        = true
      }
      worker_concurrency = "10%"
      worker_drain_options {
        enabled                  = true
        delete_empty_dir_data    = true
        ignore_daemonsets        = true
        skip_wait_for_delete_timeout_seconds = 60
      }
    }

    etcd {
      snapshot_schedule_cron = "0 */6 * * *"
      snapshot_retention     = 5
    }
  }

  labels = {
    environment = var.environment
    managed-by  = "terraform"
    platform    = "rancher"
  }
}

# ── Rancher Project for platform workloads ────────────────────────────────────
resource "rancher2_project" "platform" {
  name       = "platform"
  cluster_id = rancher2_cluster_v2.platform.cluster_v1_id

  resource_quota {
    project_limit {
      limits_cpu       = "16000m"
      limits_memory    = "32768Mi"
      requests_storage = "100Gi"
    }
    namespace_default_limit {
      limits_cpu    = "2000m"
      limits_memory = "4096Mi"
    }
  }

  container_resource_limit {
    limits_cpu      = "200m"
    limits_memory   = "256Mi"
    requests_cpu    = "50m"
    requests_memory = "64Mi"
  }
}

# ── Rancher Namespaces ────────────────────────────────────────────────────────
resource "rancher2_namespace" "kong" {
  name       = "kong"
  project_id = rancher2_project.platform.id
  labels     = { "app.kubernetes.io/managed-by" = "rancher" }
}

resource "rancher2_namespace" "dapr_system" {
  name       = "dapr-system"
  project_id = rancher2_project.platform.id
}

resource "rancher2_namespace" "keycloak" {
  name       = "keycloak"
  project_id = rancher2_project.platform.id
}

resource "rancher2_namespace" "apps" {
  name       = "apps"
  project_id = rancher2_project.platform.id
  labels = {
    "dapr-enabled"                  = "true"
    "app.kubernetes.io/managed-by"  = "rancher"
  }
}

# ── Rancher Monitoring (Prometheus + Grafana) ─────────────────────────────────
resource "rancher2_app_v2" "monitoring" {
  cluster_id    = rancher2_cluster_v2.platform.cluster_v1_id
  name          = "rancher-monitoring"
  namespace     = "cattle-monitoring-system"
  repo_name     = "rancher-charts"
  chart_name    = "rancher-monitoring"
  chart_version = "103.1.0"

  values = <<-EOT
    prometheus:
      prometheusSpec:
        retention: 7d
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: longhorn
              resources:
                requests:
                  storage: 20Gi
    grafana:
      enabled: true
      adminPassword: "CHANGE_ME"
      ingress:
        enabled: true
        ingressClassName: kong
        hosts:
          - grafana.example.com
  EOT
}

# ── Rancher Logging (Loki) ────────────────────────────────────────────────────
resource "rancher2_app_v2" "logging" {
  cluster_id    = rancher2_cluster_v2.platform.cluster_v1_id
  name          = "rancher-logging"
  namespace     = "cattle-logging-system"
  repo_name     = "rancher-charts"
  chart_name    = "rancher-logging"
  chart_version = "103.1.0"

  values = <<-EOT
    fluentd:
      enabled: false
    fluentbit:
      enabled: true
  EOT
}

# ── Fleet GitOps ──────────────────────────────────────────────────────────────
resource "rancher2_app_v2" "fleet_agent" {
  count         = var.enable_fleet_gitops ? 1 : 0
  cluster_id    = rancher2_cluster_v2.platform.cluster_v1_id
  name          = "fleet-agent"
  namespace     = "cattle-fleet-system"
  repo_name     = "rancher-charts"
  chart_name    = "fleet-agent"
  chart_version = "104.0.0"

  values = <<-EOT
    apiServerURL: ${var.rancher_api_url}
  EOT
}

# ── Catalog (Helm charts repository) ─────────────────────────────────────────
resource "rancher2_catalog_v2" "kong" {
  cluster_id = rancher2_cluster_v2.platform.cluster_v1_id
  name       = "kong"
  url        = "https://charts.konghq.com"
}

resource "rancher2_catalog_v2" "dapr" {
  cluster_id = rancher2_cluster_v2.platform.cluster_v1_id
  name       = "dapr"
  url        = "https://dapr.github.io/helm-charts"
}

resource "rancher2_catalog_v2" "bitnami" {
  cluster_id = rancher2_cluster_v2.platform.cluster_v1_id
  name       = "bitnami"
  url        = "https://charts.bitnami.com/bitnami"
}

resource "rancher2_catalog_v2" "jetstack" {
  cluster_id = rancher2_cluster_v2.platform.cluster_v1_id
  name       = "jetstack"
  url        = "https://charts.jetstack.io"
}
