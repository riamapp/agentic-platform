################################################################################
# WebSocket API Gateway for Real-time Job Updates
################################################################################

resource "aws_apigatewayv2_api" "websocket_api" {
  name                       = "${var.app_name}-WebSocket"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

# WebSocket $connect route
resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$connect"

  target = "integrations/${aws_apigatewayv2_integration.connect.id}"
}

# WebSocket $disconnect route
resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$disconnect"

  target = "integrations/${aws_apigatewayv2_integration.disconnect.id}"
}

# WebSocket $default route (for custom messages if needed)
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$default"

  target = "integrations/${aws_apigatewayv2_integration.default.id}"
}

# Lambda integration for $connect
resource "aws_apigatewayv2_integration" "connect" {
  api_id           = aws_apigatewayv2_api.websocket_api.id
  integration_type = "AWS_PROXY"

  integration_uri = aws_lambda_function.websocket_connect_lambda.invoke_arn
}

# Lambda integration for $disconnect
resource "aws_apigatewayv2_integration" "disconnect" {
  api_id           = aws_apigatewayv2_api.websocket_api.id
  integration_type = "AWS_PROXY"

  integration_uri = aws_lambda_function.websocket_disconnect_lambda.invoke_arn
}

# Lambda integration for $default
resource "aws_apigatewayv2_integration" "default" {
  api_id           = aws_apigatewayv2_api.websocket_api.id
  integration_type = "AWS_PROXY"

  integration_uri = aws_lambda_function.websocket_connect_lambda.invoke_arn
}

# WebSocket Stage
resource "aws_apigatewayv2_stage" "websocket_stage" {
  api_id      = aws_apigatewayv2_api.websocket_api.id
  name        = "dev"
  auto_deploy = true
}

################################################################################
# WebSocket Connect Lambda
################################################################################

resource "null_resource" "websocket_connect_lambda_package" {
  triggers = {
    handler_hash = filemd5("${path.module}/../api/websocket/connect_handler.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make websocket-connect-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}

# Zip files are created by Makefile in build/ directory
locals {
  websocket_connect_lambda_zip_path    = "${path.module}/../build/websocket_connect_lambda.zip"
  websocket_disconnect_lambda_zip_path = "${path.module}/../build/websocket_disconnect_lambda.zip"
}

resource "aws_lambda_function" "websocket_connect_lambda" {
  function_name = "${var.app_name}-WebSocketConnect"
  role          = aws_iam_role.websocket_lambda_role.arn
  handler       = "connect_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.websocket_connect_lambda_zip_path
  source_code_hash = filebase64sha256(local.websocket_connect_lambda_zip_path)

  environment {
    variables = {
      CONNECTIONS_TABLE_NAME = aws_dynamodb_table.connections_table.name
      WEBSOCKET_API_ENDPOINT = "https://${replace(aws_apigatewayv2_api.websocket_api.api_endpoint, "wss://", "")}/${aws_apigatewayv2_stage.websocket_stage.name}"
    }
  }

  depends_on = [
    aws_apigatewayv2_api.websocket_api,
    null_resource.websocket_connect_lambda_package
  ]
}

################################################################################
# WebSocket Disconnect Lambda
################################################################################

resource "null_resource" "websocket_disconnect_lambda_package" {
  triggers = {
    handler_hash = filemd5("${path.module}/../api/websocket/disconnect_handler.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make websocket-disconnect-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}


resource "aws_lambda_function" "websocket_disconnect_lambda" {
  function_name = "${var.app_name}-WebSocketDisconnect"
  role          = aws_iam_role.websocket_lambda_role.arn
  handler       = "disconnect_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.websocket_disconnect_lambda_zip_path
  source_code_hash = filebase64sha256(local.websocket_disconnect_lambda_zip_path)

  environment {
    variables = {
      CONNECTIONS_TABLE_NAME = aws_dynamodb_table.connections_table.name
    }
  }

  depends_on = [
    null_resource.websocket_disconnect_lambda_package
  ]
}

resource "aws_iam_role" "websocket_lambda_role" {
  name = "${var.app_name}-WebSocketLambdaRole"

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

resource "aws_iam_role_policy_attachment" "websocket_lambda_basic" {
  role       = aws_iam_role.websocket_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "websocket_lambda_dynamodb" {
  role = aws_iam_role.websocket_lambda_role.id
  name = "${var.app_name}-WebSocketDynamoDBPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.connections_table.arn,
          "${aws_dynamodb_table.connections_table.arn}/index/*"
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

# Lambda permissions for WebSocket API to invoke connect/disconnect handlers
resource "aws_lambda_permission" "websocket_connect_invoke" {
  statement_id  = "AllowWebSocketConnectInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.websocket_connect_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket_api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "websocket_disconnect_invoke" {
  statement_id  = "AllowWebSocketDisconnectInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.websocket_disconnect_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket_api.execution_arn}/*/*"
}

################################################################################
# Outputs
################################################################################

output "websocket_api_endpoint" {
  description = "WebSocket API endpoint URL (includes stage)"
  value       = "${aws_apigatewayv2_api.websocket_api.api_endpoint}/${aws_apigatewayv2_stage.websocket_stage.name}"
}
