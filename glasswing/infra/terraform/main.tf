terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

resource "aws_vpc" "main" {
  cidr_block = "10.40.0.0/16"
  tags       = { Name = "glasswing-${var.environment}" }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.40.1.0/24"
  availability_zone = "${var.region}a"
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.40.2.0/24"
  availability_zone = "${var.region}b"
}

resource "aws_kms_key" "data" {
  description = "Glasswing tenant data"
}

resource "aws_s3_bucket" "documents" {
  bucket = "glasswing-${var.environment}-documents"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
  }
}

resource "aws_sqs_queue" "evaluate_dlq" {
  name = "glasswing-${var.environment}-evaluate-dlq"
}

resource "aws_sqs_queue" "evaluate" {
  name = "glasswing-${var.environment}-evaluate"
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.evaluate_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_cloudwatch_event_bus" "domain" {
  name = "glasswing-${var.environment}"
}

resource "aws_ecr_repository" "app" {
  name = "glasswing-${var.environment}"
}

resource "aws_ecs_cluster" "main" {
  name = "glasswing-${var.environment}"
}

resource "aws_cognito_user_pool" "users" {
  name = "glasswing-${var.environment}"
}

resource "aws_db_subnet_group" "postgres" {
  name       = "glasswing-${var.environment}"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_security_group" "postgres" {
  name   = "glasswing-${var.environment}-postgres"
  vpc_id = aws_vpc.main.id
}

resource "aws_db_instance" "postgres" {
  identifier             = "glasswing-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  db_name                = "glasswing"
  username               = "glasswing"
  password               = "change-me"
  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.postgres.id]
  storage_encrypted      = true
  kms_key_id             = aws_kms_key.data.arn
  skip_final_snapshot    = true
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "glasswing-${var.environment}"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_wafv2_web_acl" "edge" {
  name  = "glasswing-${var.environment}"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "glasswing"
    sampled_requests_enabled   = true
  }
}

output "document_bucket" {
  value = aws_s3_bucket.documents.bucket
}
