################################################################################
# DynamoDB Tables for Jobs and WebSocket Connections
################################################################################

# Jobs table for tracking long-running agent operations
resource "aws_dynamodb_table" "jobs_table" {
  name         = "${var.app_name}-Jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jobId"

  attribute {
    name = "jobId"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {}
}

# Connections table for WebSocket connections
resource "aws_dynamodb_table" "connections_table" {
  name         = "${var.app_name}-Connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  # GSI for querying by sessionId
  attribute {
    name = "sessionId"
    type = "S"
  }

  global_secondary_index {
    name            = "SessionIdIndex"
    hash_key        = "sessionId"
    projection_type = "ALL"
  }

  tags = {}
}

################################################################################
# Job Get Lambda (GET /jobs/{jobId} endpoint)
################################################################################

resource "null_resource" "job_get_lambda_package" {
  triggers = {
    handler_hash = filemd5("${path.module}/../api/jobs/get_handler.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make job-get-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}

# Zip files are created by Makefile in build/ directory
locals {
  job_get_lambda_zip_path    = "${path.module}/../build/job_get_lambda.zip"
  job_cancel_lambda_zip_path = "${path.module}/../build/job_cancel_lambda.zip"
  job_submit_lambda_zip_path = "${path.module}/../build/job_submit_lambda.zip"
  job_worker_lambda_zip_path = "${path.module}/../build/job_worker_lambda.zip"
}

resource "aws_lambda_function" "job_get_lambda" {
  function_name = "${var.app_name}-JobGet"
  role          = aws_iam_role.job_get_lambda_role.arn
  handler       = "get_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.job_get_lambda_zip_path
  source_code_hash = filebase64sha256(local.job_get_lambda_zip_path)

  environment {
    variables = {
      JOBS_TABLE_NAME = aws_dynamodb_table.jobs_table.name
    }
  }

  depends_on = [
    null_resource.job_get_lambda_package
  ]
}

resource "aws_iam_role" "job_get_lambda_role" {
  name = "${var.app_name}-JobGetLambdaRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "job_get_lambda_basic" {
  role       = aws_iam_role.job_get_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "job_get_lambda_dynamodb" {
  role = aws_iam_role.job_get_lambda_role.id
  name = "${var.app_name}-JobGetDynamoDBPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem"
        ]
        Resource = [
          aws_dynamodb_table.jobs_table.arn
        ]
      }
    ]
  })
}

# Lambda permission for API Gateway to invoke get handler
resource "aws_lambda_permission" "job_get_api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.job_get_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api_gateway.execution_arn}/*/*"
}

################################################################################
# Job Cancel Lambda (DELETE /jobs/{jobId} endpoint)
################################################################################

resource "null_resource" "job_cancel_lambda_package" {
  triggers = {
    handler_hash = filemd5("${path.module}/../api/jobs/cancel_handler.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make job-cancel-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}


resource "aws_lambda_function" "job_cancel_lambda" {
  function_name = "${var.app_name}-JobCancel"
  role          = aws_iam_role.job_cancel_lambda_role.arn
  handler       = "cancel_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.job_cancel_lambda_zip_path
  source_code_hash = filebase64sha256(local.job_cancel_lambda_zip_path)

  environment {
    variables = {
      JOBS_TABLE_NAME = aws_dynamodb_table.jobs_table.name
    }
  }

  depends_on = [
    null_resource.job_cancel_lambda_package
  ]
}

resource "aws_iam_role" "job_cancel_lambda_role" {
  name = "${var.app_name}-JobCancelLambdaRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "job_cancel_lambda_basic" {
  role       = aws_iam_role.job_cancel_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "job_cancel_lambda_dynamodb" {
  role = aws_iam_role.job_cancel_lambda_role.id
  name = "${var.app_name}-JobCancelDynamoDBPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.jobs_table.arn
        ]
      }
    ]
  })
}

# Lambda permission for API Gateway to invoke cancel handler
resource "aws_lambda_permission" "job_cancel_api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.job_cancel_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api_gateway.execution_arn}/*/*"
}

################################################################################
# Job Submit Lambda (POST /jobs endpoint)
################################################################################

resource "null_resource" "job_submit_lambda_package" {
  triggers = {
    handler_hash      = filemd5("${path.module}/../api/jobs/submit_handler.py")
    requirements_hash = filemd5("${path.module}/../api/jobs/requirements.txt")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make job-submit-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}


resource "aws_lambda_function" "job_submit_lambda" {
  function_name = "${var.app_name}-JobSubmit"
  role          = aws_iam_role.job_submit_lambda_role.arn
  handler       = "submit_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30 # Quick operation - just creates job record

  filename         = local.job_submit_lambda_zip_path
  source_code_hash = filebase64sha256(local.job_submit_lambda_zip_path)

  environment {
    variables = {
      JOBS_TABLE_NAME             = aws_dynamodb_table.jobs_table.name
      CONNECTIONS_TABLE_NAME      = aws_dynamodb_table.connections_table.name
      WORKER_LAMBDA_FUNCTION_NAME = aws_lambda_function.job_worker_lambda.function_name
    }
  }

  depends_on = [
    null_resource.job_submit_lambda_package
  ]
}

resource "aws_iam_role" "job_submit_lambda_role" {
  name = "${var.app_name}-JobSubmitLambdaRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "job_submit_lambda_basic" {
  role       = aws_iam_role.job_submit_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "job_submit_lambda_permissions" {
  role = aws_iam_role.job_submit_lambda_role.id
  name = "${var.app_name}-JobSubmitPermissionsPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.jobs_table.arn,
          "${aws_dynamodb_table.connections_table.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.job_worker_lambda.arn
      }
    ]
  })
}


################################################################################
# Job Worker Lambda (processes jobs asynchronously)
################################################################################

resource "null_resource" "job_worker_lambda_package" {
  triggers = {
    handler_hash      = filemd5("${path.module}/../api/jobs/worker_handler.py")
    requirements_hash = filemd5("${path.module}/../api/jobs/requirements.txt")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make job-worker-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}


resource "aws_lambda_function" "job_worker_lambda" {
  function_name = "${var.app_name}-JobWorker"
  role          = aws_iam_role.job_worker_lambda_role.arn
  handler       = "worker_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900 # 15 minutes - maximum for Lambda

  filename         = local.job_worker_lambda_zip_path
  source_code_hash = filebase64sha256(local.job_worker_lambda_zip_path)

  environment {
    variables = {
      JOBS_TABLE_NAME          = aws_dynamodb_table.jobs_table.name
      CONNECTIONS_TABLE_NAME   = aws_dynamodb_table.connections_table.name
      WEBSOCKET_API_ENDPOINT   = "https://${replace(aws_apigatewayv2_api.websocket_api.api_endpoint, "wss://", "")}/${aws_apigatewayv2_stage.websocket_stage.name}"
      AGENT_RUNTIME_ARN        = aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_arn
      AGENT_ENDPOINT_QUALIFIER = aws_bedrockagentcore_agent_runtime_endpoint.dev_endpoint.name
      # AWS_REGION is automatically set by Lambda, don't include it here
    }
  }

  depends_on = [
    aws_bedrockagentcore_agent_runtime.agentcore_runtime,
    aws_apigatewayv2_api.websocket_api,
    null_resource.job_worker_lambda_package
  ]
}

resource "aws_iam_role" "job_worker_lambda_role" {
  name = "${var.app_name}-JobWorkerLambdaRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "job_worker_lambda_basic" {
  role       = aws_iam_role.job_worker_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "job_worker_lambda_permissions" {
  role = aws_iam_role.job_worker_lambda_role.id
  name = "${var.app_name}-JobWorkerPermissionsPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.jobs_table.arn,
          "${aws_dynamodb_table.connections_table.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = aws_dynamodb_table.connections_table.arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime"
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:runtime/${aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id}",
          "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:runtime/${aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id}/runtime-endpoint/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "arn:aws:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${aws_apigatewayv2_api.websocket_api.id}/*"
      }
    ]
  })
}

