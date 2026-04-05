output "resource_group_name" {
  description = "Azure resource group name"
  value       = azurerm_resource_group.platform.name
}

output "cluster_name" {
  description = "AKS cluster name"
  value       = azurerm_kubernetes_cluster.platform.name
}

output "get_credentials_command" {
  description = "Command to configure kubectl"
  value       = "az aks get-credentials --resource-group ${azurerm_resource_group.platform.name} --name ${azurerm_kubernetes_cluster.platform.name}"
}

output "postgres_fqdn" {
  description = "PostgreSQL Flexible Server FQDN for Keycloak"
  value       = azurerm_postgresql_flexible_server.keycloak.fqdn
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname for Dapr"
  value       = azurerm_redis_cache.dapr.hostname
}

output "redis_ssl_port" {
  description = "Azure Cache for Redis SSL port"
  value       = azurerm_redis_cache.dapr.ssl_port
}

output "acr_login_server" {
  description = "Azure Container Registry login server URL"
  value       = azurerm_container_registry.platform.login_server
}

output "key_vault_uri" {
  description = "Azure Key Vault URI"
  value       = azurerm_key_vault.platform.vault_uri
}

output "workload_identity_client_id" {
  description = "Client ID of the Workload Identity managed identity"
  value       = azurerm_user_assigned_identity.workload.client_id
}

output "workload_identity_tenant_id" {
  description = "Tenant ID for Workload Identity"
  value       = azurerm_user_assigned_identity.workload.tenant_id
}

output "oidc_issuer_url" {
  description = "AKS OIDC issuer URL (for Workload Identity federation)"
  value       = azurerm_kubernetes_cluster.platform.oidc_issuer_url
}

output "log_analytics_workspace_id" {
  description = "Log Analytics Workspace ID"
  value       = azurerm_log_analytics_workspace.platform.id
}

output "dns_name_servers" {
  description = "Azure DNS name servers — update your domain registrar"
  value       = azurerm_dns_zone.platform.name_servers
}
