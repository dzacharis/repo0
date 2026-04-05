output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  description = "GKE cluster API endpoint"
  value       = google_container_cluster.primary.endpoint
  sensitive   = true
}

output "cluster_ca_certificate" {
  description = "GKE cluster CA certificate (base64)"
  value       = google_container_cluster.primary.master_auth[0].cluster_ca_certificate
  sensitive   = true
}

output "get_credentials_command" {
  description = "Command to configure kubectl"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${var.region} --project ${var.project_id}"
}

output "cloud_sql_private_ip" {
  description = "Cloud SQL private IP for Keycloak"
  value       = google_sql_database_instance.keycloak.private_ip_address
}

output "memorystore_host" {
  description = "Memorystore Redis host for Dapr"
  value       = google_redis_instance.dapr.host
}

output "memorystore_port" {
  description = "Memorystore Redis port"
  value       = google_redis_instance.dapr.port
}

output "artifact_registry_url" {
  description = "Artifact Registry URL for container images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "keycloak_admin_password_secret" {
  description = "Secret Manager secret ID for Keycloak admin password"
  value       = google_secret_manager_secret.keycloak_admin_password.secret_id
}

output "dns_name_servers" {
  description = "Cloud DNS name servers — update your domain registrar with these"
  value       = google_dns_managed_zone.platform.name_servers
}
