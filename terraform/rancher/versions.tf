terraform {
  required_version = ">= 1.7"

  required_providers {
    rancher2 = {
      source  = "rancher/rancher2"
      version = "~> 4.1"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.27"
    }
  }

  # backend "s3" { ... } or backend "gcs" { ... } as needed
}

provider "rancher2" {
  api_url    = var.rancher_api_url
  token_key  = var.rancher_token
  insecure   = false
}
