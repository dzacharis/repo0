variable "rancher_api_url" {
  description = "Rancher API URL (e.g. https://rancher.example.com)"
  type        = string
}

variable "rancher_token" {
  description = "Rancher API token (Bearer token)"
  type        = string
  sensitive   = true
}

variable "cluster_name" {
  description = "Name of the downstream RKE2 cluster"
  type        = string
  default     = "platform-cluster"
}

variable "environment" {
  description = "Environment (dev or prod)"
  type        = string
  default     = "dev"
}

variable "cloud_provider" {
  description = "Cloud provider for RKE2 node pools (aws, gcp, azure, vsphere, custom)"
  type        = string
  default     = "custom"
}

variable "kubernetes_version" {
  description = "RKE2 Kubernetes version"
  type        = string
  default     = "v1.30.2+rke2r1"
}

variable "node_count" {
  description = "Number of worker nodes"
  type        = number
  default     = 3
}

variable "enable_fleet_gitops" {
  description = "Enable Fleet GitOps for automatic manifest deployment"
  type        = bool
  default     = true
}

variable "fleet_repo_url" {
  description = "Git repository URL for Fleet to sync"
  type        = string
  default     = "https://github.com/dzacharis/repo0"
}

variable "fleet_repo_branch" {
  description = "Git branch for Fleet to sync"
  type        = string
  default     = "master"
}
