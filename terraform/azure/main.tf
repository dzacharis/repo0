locals {
  common_tags = merge({
    Environment = var.environment
    Project     = "platform"
    ManagedBy   = "terraform"
    Cluster     = var.cluster_name
  }, var.tags)
}

# ── Resource Group ────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "platform" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# ── Virtual Network ───────────────────────────────────────────────────────────
resource "azurerm_virtual_network" "platform" {
  name                = "${var.cluster_name}-vnet"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  address_space       = [var.vnet_cidr]
  tags                = local.common_tags
}

resource "azurerm_subnet" "aks" {
  name                 = "${var.cluster_name}-aks-subnet"
  resource_group_name  = azurerm_resource_group.platform.name
  virtual_network_name = azurerm_virtual_network.platform.name
  address_prefixes     = [var.aks_subnet_cidr]
}

resource "azurerm_subnet" "postgres" {
  name                 = "${var.cluster_name}-postgres-subnet"
  resource_group_name  = azurerm_resource_group.platform.name
  virtual_network_name = azurerm_virtual_network.platform.name
  address_prefixes     = ["10.0.16.0/24"]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# ── Managed Identities ────────────────────────────────────────────────────────
resource "azurerm_user_assigned_identity" "aks_control_plane" {
  name                = "${var.cluster_name}-aks-identity"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  tags                = local.common_tags
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = "${var.cluster_name}-workload-identity"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  tags                = local.common_tags
}

# Allow AKS identity to manage networking
resource "azurerm_role_assignment" "aks_network" {
  scope                = azurerm_virtual_network.platform.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks_control_plane.principal_id
}

# ── Azure Container Registry ──────────────────────────────────────────────────
resource "azurerm_container_registry" "platform" {
  name                = replace("${var.cluster_name}acr", "-", "")
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  sku                 = var.environment == "prod" ? "Premium" : "Standard"
  admin_enabled       = false
  tags                = local.common_tags
}

# Allow AKS to pull from ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.platform.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.aks_control_plane.principal_id
}

# ── AKS Cluster ───────────────────────────────────────────────────────────────
resource "azurerm_kubernetes_cluster" "platform" {
  name                = var.cluster_name
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  dns_prefix          = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = var.environment == "prod" ? "Standard" : "Free"

  default_node_pool {
    name                 = "system"
    vm_size              = var.node_vm_size
    node_count           = var.node_count
    min_count            = var.node_min_count
    max_count            = var.node_max_count
    enable_auto_scaling  = true
    vnet_subnet_id       = azurerm_subnet.aks.id
    os_disk_size_gb      = 100
    type                 = "VirtualMachineScaleSets"
    zones                = var.environment == "prod" ? ["1", "2", "3"] : []
    node_labels = {
      "nodepool-type" = "system"
      "environment"   = var.environment
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks_control_plane.id]
  }

  # Workload Identity (replaces AAD Pod Identity)
  workload_identity_enabled = true
  oidc_issuer_enabled       = true

  network_profile {
    network_plugin    = "azure"   # Azure CNI
    network_policy    = "calico"
    load_balancer_sku = "standard"
    outbound_type     = "loadBalancer"
    service_cidr      = "10.100.0.0/16"
    dns_service_ip    = "10.100.0.10"
  }

  # Azure Monitor for containers
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.platform.id
  }

  # Microsoft Defender for containers
  microsoft_defender {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.platform.id
  }

  # Azure Policy add-on (enforces OPA Gatekeeper policies)
  azure_policy_enabled = true

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  maintenance_window {
    allowed {
      day   = "Sunday"
      hours = [1, 2, 3]
    }
  }

  auto_upgrade_profile {
    upgrade_channel = var.environment == "prod" ? "stable" : "rapid"
  }

  tags = local.common_tags

  depends_on = [
    azurerm_role_assignment.aks_network,
    azurerm_role_assignment.aks_acr_pull,
  ]

  lifecycle {
    ignore_changes = [
      default_node_pool[0].node_count,
      kubernetes_version,
    ]
  }
}

# Federated Identity for Workload Identity
resource "azurerm_federated_identity_credential" "workload" {
  name                = "${var.cluster_name}-workload-federated"
  resource_group_name = azurerm_resource_group.platform.name
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.platform.oidc_issuer_url
  parent_id           = azurerm_user_assigned_identity.workload.id
  subject             = "system:serviceaccount:apps:sample-app"
}

# ── Log Analytics (AKS monitoring + Defender) ─────────────────────────────────
resource "azurerm_log_analytics_workspace" "platform" {
  name                = "${var.cluster_name}-logs"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  sku                 = "PerGB2018"
  retention_in_days   = var.environment == "prod" ? 90 : 30
  tags                = local.common_tags
}

# ── Azure Database for PostgreSQL Flexible Server (Keycloak) ──────────────────
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.cluster_name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.platform.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${var.cluster_name}-postgres-dns-link"
  resource_group_name   = azurerm_resource_group.platform.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.platform.id
  registration_enabled  = false
}

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "keycloak" {
  name                          = "${var.cluster_name}-keycloak-pg"
  resource_group_name           = azurerm_resource_group.platform.name
  location                      = azurerm_resource_group.platform.location
  version                       = "15"
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  administrator_login           = "keycloak"
  administrator_password        = random_password.postgres.result
  sku_name                      = var.postgres_sku
  storage_mb                    = 32768
  backup_retention_days         = var.environment == "prod" ? 7 : 1
  geo_redundant_backup_enabled  = var.environment == "prod"
  zone                          = "1"

  high_availability {
    mode                      = var.environment == "prod" ? "ZoneRedundant" : "Disabled"
    standby_availability_zone = var.environment == "prod" ? "2" : null
  }

  maintenance_window {
    day_of_week  = 0  # Sunday
    start_hour   = 2
    start_minute = 0
  }

  tags       = local.common_tags
  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "keycloak" {
  name      = "keycloak"
  server_id = azurerm_postgresql_flexible_server.keycloak.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# ── Azure Cache for Redis (Dapr) ──────────────────────────────────────────────
resource "azurerm_redis_cache" "dapr" {
  name                = "${var.cluster_name}-dapr-redis"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku
  enable_non_ssl_port = false  # TLS only
  minimum_tls_version = "1.2"

  redis_configuration {
    maxmemory_policy = "allkeys-lru"
  }

  patch_schedule {
    day_of_week    = "Sunday"
    start_hour_utc = 3
  }

  tags = local.common_tags
}

# ── Azure Key Vault ───────────────────────────────────────────────────────────
data "azurerm_client_config" "current" {}

resource "random_password" "keycloak_admin" {
  length  = 32
  special = true
}

resource "azurerm_key_vault" "platform" {
  name                          = "${replace(var.cluster_name, "-", "")}kv"
  resource_group_name           = azurerm_resource_group.platform.name
  location                      = azurerm_resource_group.platform.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = var.environment == "prod"
  soft_delete_retention_days    = 7
  tags                          = local.common_tags
}

# Terraform caller can manage secrets
resource "azurerm_role_assignment" "kv_terraform_admin" {
  scope                = azurerm_key_vault.platform.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

# AKS Workload Identity reads secrets
resource "azurerm_role_assignment" "kv_workload_read" {
  scope                = azurerm_key_vault.platform.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

resource "azurerm_key_vault_secret" "keycloak_admin_password" {
  name         = "keycloak-admin-password"
  value        = random_password.keycloak_admin.result
  key_vault_id = azurerm_key_vault.platform.id
  depends_on   = [azurerm_role_assignment.kv_terraform_admin]
}

resource "azurerm_key_vault_secret" "keycloak_db_password" {
  name         = "keycloak-db-password"
  value        = random_password.postgres.result
  key_vault_id = azurerm_key_vault.platform.id
  depends_on   = [azurerm_role_assignment.kv_terraform_admin]
}

resource "azurerm_key_vault_secret" "redis_primary_key" {
  name         = "redis-primary-key"
  value        = azurerm_redis_cache.dapr.primary_access_key
  key_vault_id = azurerm_key_vault.platform.id
  depends_on   = [azurerm_role_assignment.kv_terraform_admin]
}

# ── Azure DNS ─────────────────────────────────────────────────────────────────
resource "azurerm_dns_zone" "platform" {
  name                = var.domain
  resource_group_name = azurerm_resource_group.platform.name
  tags                = local.common_tags
}
