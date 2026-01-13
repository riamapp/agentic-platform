################################################################################
# API Gateway REST API (supports response streaming)
################################################################################

resource "aws_api_gateway_rest_api" "api_gateway" {
  name        = "${var.app_name}-ApiGateway"
  description = "API Gateway REST API for AgentCore frontend integration with response streaming support"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

################################################################################
# Cognito Authorizer
################################################################################

resource "aws_api_gateway_authorizer" "cognito_authorizer" {
  name                   = "${var.app_name}-CognitoAuthorizer"
  rest_api_id            = aws_api_gateway_rest_api.api_gateway.id
  type                   = "COGNITO_USER_POOLS"
  provider_arns          = ["arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/${var.cognito_user_pool_id}"]
  identity_source        = "method.request.header.Authorization"
  authorizer_credentials = null
}

################################################################################
# API Gateway Resources and Methods
################################################################################

resource "aws_api_gateway_resource" "jobs" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  parent_id   = aws_api_gateway_rest_api.api_gateway.root_resource_id
  path_part   = "jobs"
}

# Resource for /jobs/{jobId}
resource "aws_api_gateway_resource" "jobs_jobid" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  parent_id   = aws_api_gateway_resource.jobs.id
  path_part   = "{jobId}"
}



# POST /jobs method
resource "aws_api_gateway_method" "jobs_post" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  resource_id   = aws_api_gateway_resource.jobs.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id

  authorization_scopes = ["openid", "email", "profile", "aws.cognito.signin.user.admin"]

  request_parameters = {
    "method.request.header.Authorization" = true
  }
}

# GET /jobs/{jobId} method
resource "aws_api_gateway_method" "jobs_jobid_get" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  resource_id   = aws_api_gateway_resource.jobs_jobid.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id

  authorization_scopes = ["openid", "email", "profile", "aws.cognito.signin.user.admin"]

  request_parameters = {
    "method.request.header.Authorization" = true
    "method.request.path.jobId"           = true
  }
}

# DELETE /jobs/{jobId} method
resource "aws_api_gateway_method" "jobs_jobid_delete" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  resource_id   = aws_api_gateway_resource.jobs_jobid.id
  http_method   = "DELETE"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id

  authorization_scopes = ["openid", "email", "profile", "aws.cognito.signin.user.admin"]

  request_parameters = {
    "method.request.header.Authorization" = true
    "method.request.path.jobId"           = true
  }
}

# OPTIONS /jobs method for CORS
resource "aws_api_gateway_method" "jobs_options" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  resource_id   = aws_api_gateway_resource.jobs.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# OPTIONS /jobs/{jobId} method for CORS
resource "aws_api_gateway_method" "jobs_jobid_options" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  resource_id   = aws_api_gateway_resource.jobs_jobid.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}



################################################################################
# API Gateway Integration
################################################################################

# GET /jobs/{jobId} integration
resource "aws_api_gateway_integration" "jobs_jobid_get_integration" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_get.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.job_get_lambda.invoke_arn
}

# DELETE /jobs/{jobId} integration
resource "aws_api_gateway_integration" "jobs_jobid_delete_integration" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_delete.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.job_cancel_lambda.invoke_arn
}

# POST /jobs integration
resource "aws_api_gateway_integration" "jobs_integration" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_post.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.job_submit_lambda.invoke_arn
}


# OPTIONS /jobs integration for CORS
resource "aws_api_gateway_integration" "jobs_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_options.http_method

  type = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# OPTIONS /jobs/{jobId} integration for CORS
resource "aws_api_gateway_integration" "jobs_jobid_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_options.http_method

  type = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

################################################################################
# Method Responses and Integration Responses
################################################################################

# POST /jobs method responses
resource "aws_api_gateway_method_response" "jobs_post_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_post.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
    "method.response.header.Content-Type"                = true
  }
}

resource "aws_api_gateway_method_response" "jobs_post_401" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_post.http_method
  status_code = "401"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
  }
}

resource "aws_api_gateway_integration_response" "jobs_post_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_post.http_method
  status_code = aws_api_gateway_method_response.jobs_post_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = "'*'"
  }

  depends_on = [aws_api_gateway_integration.jobs_integration]
}

resource "aws_api_gateway_integration_response" "jobs_post_401" {
  rest_api_id       = aws_api_gateway_rest_api.api_gateway.id
  resource_id       = aws_api_gateway_resource.jobs.id
  http_method       = aws_api_gateway_method.jobs_post.http_method
  status_code       = aws_api_gateway_method_response.jobs_post_401.status_code
  selection_pattern = "401"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
  }

  depends_on = [aws_api_gateway_integration.jobs_integration]
}

# GET /jobs/{jobId} method responses
resource "aws_api_gateway_method_response" "jobs_jobid_get_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_get.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
    "method.response.header.Content-Type"                = true
  }
}

resource "aws_api_gateway_method_response" "jobs_jobid_get_404" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_get.http_method
  status_code = "404"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
  }
}

# DELETE /jobs/{jobId} method responses
resource "aws_api_gateway_method_response" "jobs_jobid_delete_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_delete.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
    "method.response.header.Content-Type"                = true
  }
}

resource "aws_api_gateway_method_response" "jobs_jobid_delete_400" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_delete.http_method
  status_code = "400"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
  }
}

resource "aws_api_gateway_method_response" "jobs_jobid_delete_404" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_delete.http_method
  status_code = "404"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin" = true
  }
}

# OPTIONS /jobs/{jobId} method response
resource "aws_api_gateway_method_response" "jobs_jobid_options_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Max-Age"       = true
  }
}

# OPTIONS /jobs/{jobId} integration response
resource "aws_api_gateway_integration_response" "jobs_jobid_options_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs_jobid.id
  http_method = aws_api_gateway_method.jobs_jobid_options.http_method
  status_code = aws_api_gateway_method_response.jobs_jobid_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,DELETE,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Max-Age"       = "'300'"
  }

  depends_on = [aws_api_gateway_integration.jobs_jobid_options_integration]
}

# OPTIONS /jobs method response
resource "aws_api_gateway_method_response" "jobs_options_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Max-Age"       = true
  }
}

resource "aws_api_gateway_integration_response" "jobs_options_200" {
  rest_api_id = aws_api_gateway_rest_api.api_gateway.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.jobs_options.http_method
  status_code = aws_api_gateway_method_response.jobs_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Max-Age"       = "'300'"
  }

  depends_on = [aws_api_gateway_integration.jobs_options_integration]
}

################################################################################
# Lambda Permission
################################################################################

resource "aws_lambda_permission" "api_gateway_jobs_invoke" {
  statement_id  = "AllowAPIGatewayJobsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.job_submit_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api_gateway.execution_arn}/*/*"
}

################################################################################
# Gateway Response for CORS on Authorization Errors
################################################################################

# Configure gateway response for UNAUTHORIZED to include CORS headers
resource "aws_api_gateway_gateway_response" "unauthorized" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  response_type = "UNAUTHORIZED"
  status_code   = "401"

  response_templates = {
    "application/json" = "{\"message\":$context.error.messageString}"
  }

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'"
  }
}

# Configure gateway response for ACCESS_DENIED (403) to include CORS headers
resource "aws_api_gateway_gateway_response" "access_denied" {
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  response_type = "ACCESS_DENIED"
  status_code   = "403"

  response_templates = {
    "application/json" = "{\"message\":$context.error.messageString}"
  }

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'"
  }
}

################################################################################
# API Gateway Deployment
################################################################################

resource "aws_api_gateway_deployment" "api_deployment" {
  depends_on = [
    aws_api_gateway_integration.jobs_integration,
    aws_api_gateway_integration.jobs_options_integration,
    aws_api_gateway_integration.jobs_jobid_options_integration,
    aws_api_gateway_integration.jobs_jobid_get_integration,
    aws_api_gateway_integration.jobs_jobid_delete_integration,
    aws_api_gateway_integration_response.jobs_post_200,
    aws_api_gateway_integration_response.jobs_post_401,
    aws_api_gateway_integration_response.jobs_jobid_options_200,
    aws_api_gateway_integration_response.jobs_options_200,
    aws_api_gateway_gateway_response.unauthorized,
    aws_api_gateway_gateway_response.access_denied,
  ]

  rest_api_id = aws_api_gateway_rest_api.api_gateway.id

  lifecycle {
    create_before_destroy = true
  }

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.jobs.id,
      aws_api_gateway_resource.jobs_jobid.id,
      aws_api_gateway_method.jobs_post.id,
      aws_api_gateway_method.jobs_options.id,
      aws_api_gateway_method.jobs_jobid_get.id,
      aws_api_gateway_method.jobs_jobid_delete.id,
      aws_api_gateway_method.jobs_jobid_options.id,
      aws_api_gateway_integration.jobs_integration.id,
      aws_api_gateway_integration.jobs_jobid_get_integration.id,
      aws_api_gateway_integration.jobs_jobid_delete_integration.id,
      aws_api_gateway_integration.jobs_jobid_options_integration.id,
      aws_api_gateway_gateway_response.unauthorized.id,
      aws_api_gateway_gateway_response.access_denied.id,
    ]))
  }
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.api_gateway.id
  stage_name    = "dev"

  xray_tracing_enabled = false
}

################################################################################
# Outputs
################################################################################

output "api_gateway_url" {
  description = "API Gateway base URL"
  value       = aws_api_gateway_stage.api_stage.invoke_url
}

output "api_gateway_jobs_url" {
  description = "API Gateway jobs URL (POST /jobs)"
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}/jobs"
}

