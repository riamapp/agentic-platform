terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.19"
    }
  }

  required_version = ">= 1.2"
}

provider "aws" {
  region  = var.aws_region
  profile = "default"
}

# API Gateway outputs are now defined in api_gateway.tf

output "cognito_frontend_client_id" {
  description = "Cognito Frontend Client ID (use for VITE_COGNITO_CLIENT_ID)"
  value       = var.cognito_frontend_client_id
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID (use for VITE_COGNITO_USER_POOL_ID)"
  value       = var.cognito_user_pool_id
}

output "cognito_domain" {
  description = "Cognito Domain name only"
  value       = replace(var.cognito_domain_url, "https://", "")
}

output "cognito_domain_url" {
  description = "Full Cognito Domain URL (use for VITE_COGNITO_DOMAIN)"
  value       = var.cognito_domain_url
}

output "aws_region" {
  description = "AWS Region (use for VITE_AWS_REGION)"
  value       = data.aws_region.current.region
}
