# Variables
variable "app_name" {
  description = "Application name"
  type        = string
}

variable "agent_runtime_version" {
  description = "Runtime version for PROD endpoint (DEV endpoint uses latest via lifecycle ignore_changes)"
  type        = string
  default     = "1"
}

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-west-2"
}

variable "cognito_user_pool_id" {
  description = "ID of the shared Cognito User Pool from agentic-auth"
  type        = string
}

variable "cognito_frontend_client_id" {
  description = "App client ID for browser/frontend auth (from agentic-auth)"
  type        = string
}

variable "cognito_m2m_client_id" {
  description = "Machine-to-machine app client ID used by the Agent Platform (from agentic-auth)"
  type        = string
}

variable "cognito_domain_url" {
  description = "Full Cognito domain URL from agentic-auth outputs (e.g. https://prefix.auth.us-west-2.amazoncognito.com)"
  type        = string
}

variable "cognito_client_secret" {
  description = "Client secret for the machine-to-machine Cognito app client"
  type        = string
  sensitive   = true
}

variable "cognito_scope" {
  description = "OAuth scope to request for machine-to-machine auth"
  type        = string
  default     = "openid"
}

variable "max_prompt_tokens" {
  description = "Maximum number of tokens allowed in the prompt (default: 160000)"
  type        = number
  default     = 160000
}

variable "browser_max_html_size" {
  description = "Maximum HTML content size in bytes for browser tool (default: 30000)"
  type        = number
  default     = 30000
}

variable "browser_max_text_size" {
  description = "Maximum text content size in bytes for browser tool (default: 50000)"
  type        = number
  default     = 50000
}

variable "browser_max_html_tokens" {
  description = "Maximum HTML content tokens for browser tool (default: 8000)"
  type        = number
  default     = 8000
}

variable "browser_max_text_tokens" {
  description = "Maximum text content tokens for browser tool (default: 12500)"
  type        = number
  default     = 12500
}

variable "token_warning_threshold" {
  description = "Token warning threshold as a fraction (default: 0.8, meaning warn at 80% of limit)"
  type        = number
  default     = 0.8
}

variable "rds_database_name" {
  description = "PostgreSQL database name (must begin with a letter and contain only alphanumeric characters, default: riamstudentsoverture)"
  type        = string
  default     = "riamstudentsoverture"
}

# Note: rds_secret_arn and rds_instance_endpoint are now outputs from student_data.tf
# They are no longer needed as input variables since we create the resources

variable "dynamodb_skills_quadrant_table" {
  description = "DynamoDB table name for students-skills-quadrant (default: students-skills-quadrant)"
  type        = string
  default     = "students-skills-quadrant"
}

# User Preferences Table (from agentic-user-api workspace)
variable "user_preferences_table_name" {
  description = "Name of the DynamoDB table for user preferences (from agentic-user-api)"
  type        = string
}

# VPC Configuration Variables
# If create_vpc is true, a new VPC will be created. If false, existing VPC resources must be provided.
variable "create_vpc" {
  description = "Whether to create a new VPC or use an existing one"
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (only used if create_vpc is true)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets (only used if create_vpc is true)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "List of CIDR blocks for private subnets (only used if create_vpc is true)"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

# Existing VPC Configuration (only used if create_vpc is false)
variable "vpc_id" {
  description = "VPC ID where RDS and Lambda will be deployed (only used if create_vpc is false)"
  type        = string
  default     = null
}

variable "rds_subnet_ids" {
  description = "List of subnet IDs for RDS subnet group (only used if create_vpc is false)"
  type        = list(string)
  default     = []
}

variable "rds_engine_version" {
  description = "PostgreSQL engine version for RDS (use full version like 15.15, 16.11, or leave empty for latest)"
  type        = string
  default     = "15.15"
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "Maximum allocated storage in GB (for autoscaling)"
  type        = number
  default     = 100
}

variable "rds_master_username" {
  description = "Master username for RDS database"
  type        = string
  default     = "postgres"
}

variable "rds_master_password" {
  description = "Master password for RDS database"
  type        = string
  sensitive   = true
}

variable "rds_publicly_accessible" {
  description = "Whether RDS instance should be publicly accessible"
  type        = bool
  default     = false
}

variable "rds_multi_az" {
  description = "Whether to deploy RDS in multiple availability zones"
  type        = bool
  default     = false
}

variable "rds_backup_retention_period" {
  description = "Number of days to retain backups"
  type        = number
  default     = 7
}

variable "rds_backup_window" {
  description = "Preferred backup window (UTC)"
  type        = string
  default     = "03:00-04:00"
}

variable "rds_maintenance_window" {
  description = "Preferred maintenance window (UTC)"
  type        = string
  default     = "mon:04:00-mon:05:00"
}

variable "rds_skip_final_snapshot" {
  description = "Whether to skip final snapshot when destroying RDS"
  type        = bool
  default     = true
}

variable "rds_performance_insights_enabled" {
  description = "Whether to enable Performance Insights"
  type        = bool
  default     = false
}

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}
