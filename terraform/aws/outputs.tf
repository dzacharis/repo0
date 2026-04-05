output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
  sensitive   = true
}

output "get_credentials_command" {
  description = "Command to configure kubectl"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint for Keycloak"
  value       = aws_db_instance.keycloak.endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint for Dapr"
  value       = aws_elasticache_replication_group.dapr.primary_endpoint_address
}

output "ecr_url" {
  description = "ECR repository URL for sample-app images"
  value       = aws_ecr_repository.sample_app.repository_url
}

output "eso_role_arn" {
  description = "IAM role ARN for External Secrets Operator"
  value       = aws_iam_role.eso.arn
}

output "route53_name_servers" {
  description = "Route 53 name servers — update your domain registrar with these"
  value       = aws_route53_zone.platform.name_servers
}

output "keycloak_admin_secret_arn" {
  description = "AWS Secrets Manager ARN for Keycloak admin password"
  value       = aws_secretsmanager_secret.keycloak_admin.arn
}
