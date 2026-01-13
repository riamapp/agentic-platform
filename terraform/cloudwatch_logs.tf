################################################################################
# CloudWatch Log Groups with 30-Day Retention
################################################################################

# Lambda Function Log Groups
# Note: Lambda functions automatically create log groups when they run, but we
# explicitly create them here to set retention policies before the first execution.

# Job Get Lambda
resource "aws_cloudwatch_log_group" "job_get_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.job_get_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# Job Cancel Lambda
resource "aws_cloudwatch_log_group" "job_cancel_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.job_cancel_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# Job Submit Lambda
resource "aws_cloudwatch_log_group" "job_submit_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.job_submit_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# Job Worker Lambda
resource "aws_cloudwatch_log_group" "job_worker_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.job_worker_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# WebSocket Connect Lambda
resource "aws_cloudwatch_log_group" "websocket_connect_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.websocket_connect_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# WebSocket Disconnect Lambda
resource "aws_cloudwatch_log_group" "websocket_disconnect_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.websocket_disconnect_lambda.function_name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# Bedrock AgentCore Runtime Log Groups
# Note: Bedrock AgentCore automatically creates log groups with the pattern:
# /aws/bedrock-agentcore/runtimes/{runtime-name}-{runtime-id}-{endpoint-name}
# The runtime-name is "agenticPoc_Agent" (hardcoded in bedrock_agentcore.tf)
# We create them explicitly here to set retention before first use.

# DEV Endpoint Log Group
resource "aws_cloudwatch_log_group" "agentcore_runtime_dev" {
  name              = "/aws/bedrock-agentcore/runtimes/agenticPoc_Agent-${aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id}-${aws_bedrockagentcore_agent_runtime_endpoint.dev_endpoint.name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_bedrockagentcore_agent_runtime.agentcore_runtime,
    aws_bedrockagentcore_agent_runtime_endpoint.dev_endpoint
  ]
}

# PROD Endpoint Log Group
resource "aws_cloudwatch_log_group" "agentcore_runtime_prod" {
  name              = "/aws/bedrock-agentcore/runtimes/agenticPoc_Agent-${aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id}-${aws_bedrockagentcore_agent_runtime_endpoint.prod_endpoint.name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_bedrockagentcore_agent_runtime.agentcore_runtime,
    aws_bedrockagentcore_agent_runtime_endpoint.prod_endpoint
  ]
}

# API Gateway Access Logs (if enabled)
# Note: API Gateway logs are typically configured at the stage level
# This log group will be used if access logging is enabled on the API Gateway
resource "aws_cloudwatch_log_group" "api_gateway_access_logs" {
  name              = "/aws/apigateway/${aws_api_gateway_rest_api.api_gateway.name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

# WebSocket API Gateway Access Logs (if enabled)
resource "aws_cloudwatch_log_group" "websocket_api_access_logs" {
  name              = "/aws/apigateway/${aws_apigatewayv2_api.websocket_api.name}"
  retention_in_days = 30

  lifecycle {
    create_before_destroy = true
  }
}

