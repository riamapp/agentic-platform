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

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}
