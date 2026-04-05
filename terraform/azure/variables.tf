variable "resource_group_name" {
  description = "Azure resource group name"
  type        = string
  default     = "platform-rg"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "cluster_name" {
  description = "AKS cluster name"
  type        = string
  default     = "platform-cluster"
}

variable "environment" {
  description = "Environment (dev or prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'"
  }
}

variable "kubernetes_version" {
  description = "AKS Kubernetes version"
  type        = string
  default     = "1.30"
}

variable "node_vm_size" {
  description = "VM size for AKS system node pool"
  type        = string
  default     = "Standard_D4s_v3"
}

variable "node_count" {
  description = "Number of nodes in the default node pool"
  type        = number
  default     = 2
}

variable "node_min_count" {
  description = "Minimum node count for autoscaler"
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Maximum node count for autoscaler"
  type        = number
  default     = 6
}

variable "postgres_sku" {
  description = "Azure Database for PostgreSQL Flexible Server SKU"
  type        = string
  default     = "B_Standard_B2s"
}

variable "redis_sku" {
  description = "Azure Cache for Redis SKU (Basic, Standard, Premium)"
  type        = string
  default     = "Standard"
}

variable "redis_family" {
  description = "Redis family (C for Basic/Standard, P for Premium)"
  type        = string
  default     = "C"
}

variable "redis_capacity" {
  description = "Redis cache capacity (0-6)"
  type        = number
  default     = 1
}

variable "vnet_cidr" {
  description = "Virtual Network address space"
  type        = string
  default     = "10.0.0.0/16"
}

variable "aks_subnet_cidr" {
  description = "Subnet CIDR for AKS nodes"
  type        = string
  default     = "10.0.0.0/20"
}

variable "domain" {
  description = "Base DNS domain"
  type        = string
  default     = "example.com"
}

variable "tags" {
  description = "Additional resource tags"
  type        = map(string)
  default     = {}
}
