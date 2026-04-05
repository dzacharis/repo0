output "cluster_id" {
  description = "Rancher cluster ID"
  value       = rancher2_cluster_v2.platform.id
}

output "cluster_name" {
  description = "RKE2 cluster name"
  value       = rancher2_cluster_v2.platform.name
}

output "kube_config" {
  description = "Kubeconfig for the downstream cluster"
  value       = rancher2_cluster_v2.platform.kube_config
  sensitive   = true
}

output "project_id" {
  description = "Rancher project ID for platform workloads"
  value       = rancher2_project.platform.id
}

output "get_kubeconfig" {
  description = "Command to get kubeconfig via Rancher CLI"
  value       = "rancher cluster kubeconfig ${var.cluster_name}"
}
