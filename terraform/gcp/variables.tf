variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for the GKE cluster"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
  default     = "platform-cluster"
}

variable "environment" {
  description = "Environment name (dev or prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'"
  }
}

variable "gke_node_count" {
  description = "Number of nodes per zone (Standard mode)"
  type        = number
  default     = 1
}

variable "gke_machine_type" {
  description = "GCE machine type for GKE nodes"
  type        = string
  default     = "e2-standard-4"
}

variable "gke_autopilot" {
  description = "Use GKE Autopilot mode (recommended for production)"
  type        = bool
  default     = true
}

variable "db_tier" {
  description = "Cloud SQL instance tier for Keycloak PostgreSQL"
  type        = string
  default     = "db-g1-small"
}

variable "redis_memory_size_gb" {
  description = "Memorystore Redis memory size (GB)"
  type        = number
  default     = 1
}

variable "network_name" {
  description = "VPC network name"
  type        = string
  default     = "platform-vpc"
}

variable "subnet_cidr" {
  description = "Primary subnet CIDR"
  type        = string
  default     = "10.0.0.0/20"
}

variable "pods_cidr" {
  description = "Secondary range CIDR for GKE pods"
  type        = string
  default     = "10.1.0.0/16"
}

variable "services_cidr" {
  description = "Secondary range CIDR for GKE services"
  type        = string
  default     = "10.2.0.0/20"
}

variable "authorized_networks" {
  description = "CIDR blocks allowed to access the GKE master endpoint"
  type        = list(object({ cidr_block = string, display_name = string }))
  default     = [{ cidr_block = "0.0.0.0/0", display_name = "all" }]
}

variable "domain" {
  description = "Base domain for ingress hostnames (e.g. example.com)"
  type        = string
  default     = "example.com"
}
