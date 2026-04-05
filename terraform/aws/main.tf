# ── VPC ───────────────────────────────────────────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i + 10)]

  enable_nat_gateway     = true
  single_nat_gateway     = var.environment == "dev"  # save cost in dev
  one_nat_gateway_per_az = var.environment == "prod"
  enable_dns_hostnames   = true
  enable_dns_support     = true

  # Required tags for EKS
  public_subnet_tags = {
    "kubernetes.io/role/elb"                        = "1"
    "kubernetes.io/cluster/${var.cluster_name}"     = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"               = "1"
    "kubernetes.io/cluster/${var.cluster_name}"     = "shared"
  }
}

# ── EKS Cluster ───────────────────────────────────────────────────────────────
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  vpc_id                         = module.vpc.vpc_id
  subnet_ids                     = module.vpc.private_subnets
  cluster_endpoint_public_access = true

  # Enable IRSA (IAM Roles for Service Accounts)
  enable_irsa = true

  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent    = true
      before_compute = true
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = aws_iam_role.ebs_csi.arn
    }
  }

  eks_managed_node_groups = {
    main = {
      name            = "${var.cluster_name}-nodes"
      instance_types  = [var.node_instance_type]
      min_size        = var.node_min_size
      max_size        = var.node_max_size
      desired_size    = var.node_desired_size
      ami_type        = "AL2_x86_64"
      disk_size       = 50
      capacity_type   = "ON_DEMAND"

      iam_role_additional_policies = {
        AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
      }

      labels = {
        Environment = var.environment
        NodeGroup   = "main"
      }

      taints = []
    }
  }

  # Allow cluster admin access from Terraform caller
  enable_cluster_creator_admin_permissions = true
}

# ── IAM Roles (IRSA) ──────────────────────────────────────────────────────────

# EBS CSI Driver role
resource "aws_iam_role" "ebs_csi" {
  name = "${var.cluster_name}-ebs-csi"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:kube-system:ebs-csi-controller-sa"
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  role       = aws_iam_role.ebs_csi.name
}

# AWS Secrets Manager access role for External Secrets Operator
resource "aws_iam_role" "eso" {
  name = "${var.cluster_name}-eso"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = module.eks.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:external-secrets:external-secrets"
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "eso_secrets" {
  name = "eso-secrets-access"
  role = aws_iam_role.eso.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:${var.region}:*:secret:${var.cluster_name}/*"
    }]
  })
}

# ── RDS PostgreSQL (Keycloak) ─────────────────────────────────────────────────
resource "aws_db_subnet_group" "keycloak" {
  name       = "${var.cluster_name}-keycloak"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "rds" {
  name        = "${var.cluster_name}-rds"
  description = "Allow PostgreSQL from EKS nodes"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "random_password" "keycloak_db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "keycloak" {
  identifier              = "${var.cluster_name}-keycloak"
  engine                  = "postgres"
  engine_version          = "15.6"
  instance_class          = var.db_instance_class
  allocated_storage       = 20
  max_allocated_storage   = 100
  storage_encrypted       = true
  db_name                 = "keycloak"
  username                = "keycloak"
  password                = random_password.keycloak_db.result
  db_subnet_group_name    = aws_db_subnet_group.keycloak.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  skip_final_snapshot     = var.environment != "prod"
  deletion_protection     = var.environment == "prod"
  backup_retention_period = var.environment == "prod" ? 7 : 1
  multi_az                = var.environment == "prod"
  publicly_accessible     = false

  tags = {
    Name = "${var.cluster_name}-keycloak-pg"
  }
}

# ── ElastiCache Redis (Dapr) ──────────────────────────────────────────────────
resource "aws_elasticache_subnet_group" "dapr" {
  name       = "${var.cluster_name}-dapr-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "redis" {
  name        = "${var.cluster_name}-redis"
  description = "Allow Redis from EKS nodes"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_elasticache_replication_group" "dapr" {
  replication_group_id = "${var.cluster_name}-dapr"
  description          = "Redis for Dapr state store and pub/sub"
  node_type            = var.redis_node_type
  num_cache_clusters   = var.environment == "prod" ? 2 : 1
  engine_version       = "7.0"
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.dapr.name
  security_group_ids   = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true   # TLS
  auth_token                 = random_password.redis_auth.result
  automatic_failover_enabled = var.environment == "prod"

  tags = {
    Name = "${var.cluster_name}-dapr-redis"
  }
}

resource "random_password" "redis_auth" {
  length  = 32
  special = false
}

# ── AWS Secrets Manager ───────────────────────────────────────────────────────
resource "random_password" "keycloak_admin" {
  length  = 32
  special = true
}

resource "aws_secretsmanager_secret" "keycloak_admin" {
  name = "${var.cluster_name}/keycloak-admin-password"
}

resource "aws_secretsmanager_secret_version" "keycloak_admin" {
  secret_id     = aws_secretsmanager_secret.keycloak_admin.id
  secret_string = random_password.keycloak_admin.result
}

resource "aws_secretsmanager_secret" "keycloak_db" {
  name = "${var.cluster_name}/keycloak-db-password"
}

resource "aws_secretsmanager_secret_version" "keycloak_db" {
  secret_id     = aws_secretsmanager_secret.keycloak_db.id
  secret_string = random_password.keycloak_db.result
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name = "${var.cluster_name}/redis-auth-token"
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
}

# ── ECR Repository ────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "sample_app" {
  name                 = "${var.cluster_name}/sample-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# ── Route 53 ──────────────────────────────────────────────────────────────────
resource "aws_route53_zone" "platform" {
  name = var.domain
}
