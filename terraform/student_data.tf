################################################################################
# Student Data Resources
# RDS PostgreSQL database, DynamoDB table, and S3 buckets for student data
################################################################################

################################################################################
# RDS PostgreSQL Database
################################################################################

# Use VPC ID from created VPC or provided variable
locals {
  vpc_id_to_use         = var.create_vpc ? aws_vpc.main.id : var.vpc_id
  rds_subnet_ids_to_use = var.create_vpc ? aws_subnet.private[*].id : var.rds_subnet_ids
}

# DB Subnet Group
resource "aws_db_subnet_group" "students_db_subnet_group" {
  name       = "${var.app_name}-students-db-subnet-group"
  subnet_ids = local.rds_subnet_ids_to_use

  tags = {
    Name = "${var.app_name}-students-db-subnet-group"
  }
}

# Security Group for RDS
resource "aws_security_group" "students_db_sg" {
  name        = "${var.app_name}-students-db-sg"
  description = "Security group for students RDS database"
  vpc_id      = local.vpc_id_to_use

  ingress {
    description     = "PostgreSQL from Lambda"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.mcp_lambda_sg.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-students-db-sg"
  }
}

# Security Group for MCP Lambda (if VPC configuration is needed)
resource "aws_security_group" "mcp_lambda_sg" {
  name        = "${var.app_name}-mcp-lambda-sg"
  description = "Security group for MCP Lambda to access RDS"
  vpc_id      = local.vpc_id_to_use

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-mcp-lambda-sg"
  }
}

# RDS Instance
resource "aws_db_instance" "students_overture_db" {
  identifier            = "${var.app_name}-students-overture"
  engine                = "postgres"
  engine_version        = var.rds_engine_version
  instance_class        = var.rds_instance_class
  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.rds_database_name
  username = var.rds_master_username
  password = var.rds_master_password

  db_subnet_group_name    = aws_db_subnet_group.students_db_subnet_group.name
  vpc_security_group_ids  = [aws_security_group.students_db_sg.id]
  publicly_accessible     = var.rds_publicly_accessible
  multi_az                = var.rds_multi_az
  backup_retention_period = var.rds_backup_retention_period
  backup_window           = var.rds_backup_window
  maintenance_window      = var.rds_maintenance_window

  skip_final_snapshot       = var.rds_skip_final_snapshot
  final_snapshot_identifier = var.rds_skip_final_snapshot ? null : "${var.app_name}-students-overture-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  performance_insights_enabled = var.rds_performance_insights_enabled

  tags = {
    Name = "${var.app_name}-students-overture-db"
  }
}

# Secrets Manager Secret for RDS credentials
resource "aws_secretsmanager_secret" "rds_credentials" {
  name        = "${var.app_name}-rds-credentials"
  description = "RDS database credentials for students-overture database"

  tags = {
    Name = "${var.app_name}-rds-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    username = aws_db_instance.students_overture_db.username
    password = aws_db_instance.students_overture_db.password
    engine   = "postgres"
    host     = aws_db_instance.students_overture_db.address
    port     = aws_db_instance.students_overture_db.port
    dbname   = aws_db_instance.students_overture_db.db_name
  })
}

################################################################################
# DynamoDB Table for Students Skills Quadrant
################################################################################

resource "aws_dynamodb_table" "students_skills_quadrant" {
  name         = var.dynamodb_skills_quadrant_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "student_id"

  attribute {
    name = "student_id"
    type = "S"
  }

  # Enable point-in-time recovery for data protection
  point_in_time_recovery {
    enabled = true
  }

  # Server-side encryption
  server_side_encryption {
    enabled = true
  }

  tags = {
    Name = var.dynamodb_skills_quadrant_table
  }
}

################################################################################
# S3 Bucket for Student Feedback (one bucket per student pattern)
# Note: Individual student buckets will be created dynamically
# This creates a main bucket for managing student feedback
################################################################################

# Main S3 bucket for student feedback (optional - can be used for organization)
resource "aws_s3_bucket" "student_feedback" {
  bucket = "${var.app_name}-student-feedback"

  tags = {
    Name        = "${var.app_name}-student-feedback"
    Description = "Main bucket for student audio feedback files"
  }
}

resource "aws_s3_bucket_versioning" "student_feedback" {
  bucket = aws_s3_bucket.student_feedback.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "student_feedback" {
  bucket = aws_s3_bucket.student_feedback.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "student_feedback" {
  bucket = aws_s3_bucket.student_feedback.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Note: Individual student buckets (e.g., student-12345) should be created
# either manually or through a separate process. The accordo_audio_feedback_tool
# will work with any bucket name that matches the pattern stored in the
# student's DynamoDB profile.

################################################################################
# Outputs
################################################################################

output "rds_instance_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.students_overture_db.address
}

output "rds_secret_arn" {
  description = "ARN of Secrets Manager secret containing RDS credentials"
  value       = aws_secretsmanager_secret.rds_credentials.arn
  sensitive   = true
}

output "dynamodb_skills_quadrant_table_name" {
  description = "Name of the DynamoDB table for students skills quadrant"
  value       = aws_dynamodb_table.students_skills_quadrant.name
}

output "student_feedback_bucket_name" {
  description = "Name of the S3 bucket for student feedback"
  value       = aws_s3_bucket.student_feedback.id
}
