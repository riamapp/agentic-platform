################################################################################
# AgentCore Gateway IAM Roles
################################################################################

# Note: bedrock_agentcore_assume_role data source is already defined in bedrock_agentcore.tf
# Reusing it here to avoid duplication

resource "aws_iam_role" "agentcore_gateway_role" {
  name               = "${var.app_name}-AgentCoreGatewayRole"
  assume_role_policy = data.aws_iam_policy_document.bedrock_agentcore_assume_role.json
}

resource "aws_iam_role_policy_attachment" "agentcore_gateway_permissions" {
  role       = aws_iam_role.agentcore_gateway_role.name
  policy_arn = "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess"
}

resource "aws_iam_role_policy" "agentcore_gateway_lambda_invoke" {
  role = aws_iam_role.agentcore_gateway_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = ["lambda:InvokeFunction"]
      Effect   = "Allow"
      Resource = [aws_lambda_function.mcp_lambda.arn]
    }]
  })
}

locals {
  cognito_discovery_url = "https://cognito-idp.${var.aws_region}.amazonaws.com/${var.cognito_user_pool_id}/.well-known/openid-configuration"
}

################################################################################
# AgentCore Gateway
################################################################################

resource "aws_bedrockagentcore_gateway" "agentcore_gateway" {
  name            = "${var.app_name}-Gateway"
  protocol_type   = "MCP"
  role_arn        = aws_iam_role.agentcore_gateway_role.arn
  authorizer_type = "CUSTOM_JWT"
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = local.cognito_discovery_url
      allowed_clients = [var.cognito_m2m_client_id]
    }
  }
}

################################################################################
# MCP Lambda Function
################################################################################

# Package MCP Lambda function with dependencies
resource "null_resource" "mcp_lambda_package" {
  triggers = {
    handler_hash                  = filemd5("${path.module}/../mcp/lambda/handler.py")
    requirements_hash             = filemd5("${path.module}/../mcp/lambda/requirements.txt")
    students_overture_hash        = filemd5("${path.module}/../mcp/lambda/students_overture.py")
    students_skills_quadrant_hash = filemd5("${path.module}/../mcp/lambda/students_skills_quadrant.py")
    accordo_audio_feedback_hash   = filemd5("${path.module}/../mcp/lambda/accordo_audio_feedback.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make mcp-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}

# Zip file is created by Makefile in build/ directory
locals {
  mcp_lambda_zip_path = "${path.module}/../build/mcp_lambda.zip"
}

resource "aws_lambda_function" "mcp_lambda" {
  function_name = "${var.app_name}-McpLambda"
  description   = "Lambda function for Bedrock AgentCore Gateway that handles MCP tool invocations for student data queries."
  role          = aws_iam_role.mcp_lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.mcp_lambda_zip_path
  source_code_hash = filebase64sha256(local.mcp_lambda_zip_path)

  # VPC configuration to access RDS (if RDS is in a VPC)
  vpc_config {
    subnet_ids         = local.rds_subnet_ids_to_use
    security_group_ids = [aws_security_group.mcp_lambda_sg.id]
  }

  environment {
    variables = {
      RDS_DATABASE_NAME              = var.rds_database_name
      RDS_SECRET_ARN                 = aws_secretsmanager_secret.rds_credentials.arn
      RDS_INSTANCE_ENDPOINT          = aws_db_instance.students_overture_db.address
      DYNAMODB_SKILLS_QUADRANT_TABLE = aws_dynamodb_table.students_skills_quadrant.name
      S3_STUDENT_FEEDBACK_BUCKET     = aws_s3_bucket.student_feedback.id
    }
  }

  depends_on = [
    null_resource.mcp_lambda_package,
    aws_db_instance.students_overture_db,
    aws_dynamodb_table.students_skills_quadrant,
    aws_s3_bucket.student_feedback
  ]
}

# CRITICAL: Allow Bedrock AgentCore Gateway to invoke the Lambda
# The Gateway needs explicit permission via Lambda resource-based policy
resource "aws_lambda_permission" "allow_gateway_invoke" {
  statement_id  = "AllowBedrockAgentCoreGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp_lambda.function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  # Gateway ARN - use the gateway_arn attribute if available, otherwise construct it
  source_arn    = "${aws_bedrockagentcore_gateway.agentcore_gateway.gateway_arn}/*"
}

resource "aws_iam_role" "mcp_lambda_role" {
  name = "${var.app_name}-McpLambdaRole"

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

resource "aws_iam_role_policy_attachment" "mcp_lambda_basic_execution" {
  role       = aws_iam_role.mcp_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "mcp_lambda_vpc_execution" {
  role       = aws_iam_role.mcp_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "mcp_lambda_permissions" {
  role = aws_iam_role.mcp_lambda_role.id
  name = "${var.app_name}-McpLambdaPermissionsPolicy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RDSConnect"
        Effect = "Allow"
        Action = [
          "rds-db:connect"
        ]
        Resource = "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:*/*"
      },
      {
        Sid    = "SecretsManagerAccess"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = aws_secretsmanager_secret.rds_credentials.arn
      },
      {
        Sid    = "DynamoDBAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.students_skills_quadrant.arn
      },
      {
        Sid    = "S3ListBucket"
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.student_feedback.arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["student-*"]
          }
        }
      },
      {
        Sid    = "S3GetObject"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.student_feedback.arn}/student-*/*"
      }
    ]
  })
}

################################################################################
# Gateway Targets for Student Tools
################################################################################

# Gateway target for students-overture-tool
resource "aws_bedrockagentcore_gateway_target" "students_overture_target" {
  name               = "${var.app_name}-Overture"
  gateway_identifier = aws_bedrockagentcore_gateway.agentcore_gateway.gateway_id

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.mcp_lambda.arn

        tool_schema {
          inline_payload {
            name        = "students_overture"
            description = <<-EOT
              MCP tool for querying PostgreSQL RDS database riam-students-overture by student ID.
              This tool retrieves student information from the Overture database system.
              
              The userId is automatically extracted from the authenticated session by the Gateway.
              You do NOT need to provide it.
              
              Use this tool when you need to look up student information from the Overture database.
              The tool will return all available data for the specified student ID.
            EOT
            input_schema {
              type        = "object"
              description = "Input schema for querying student data from Overture database"
              property {
                name        = "student_id"
                type        = "string"
                description = "Numeric student ID to query"
                required    = true
              }
            }
          }
        }
      }
    }
  }
}

# Gateway target for students-skills-quadrant-tool
resource "aws_bedrockagentcore_gateway_target" "students_skills_quadrant_target" {
  name               = "${var.app_name}-SkillsQuadrant"
  gateway_identifier = aws_bedrockagentcore_gateway.agentcore_gateway.gateway_id

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.mcp_lambda.arn

        tool_schema {
          inline_payload {
            name        = "students_skills_quadrant"
            description = <<-EOT
              MCP tool for querying DynamoDB table students-skills-quadrant by student ID.
              This tool retrieves student skills and quadrant data stored in DynamoDB.
              
              The userId is automatically extracted from the authenticated session by the Gateway.
              You do NOT need to provide it.
              
              Use this tool when you need to look up a student's skills quadrant information.
              The tool will return all available data for the specified student ID, including
              their profile information which may contain S3 bucket references.
            EOT
            input_schema {
              type        = "object"
              description = "Input schema for querying student skills quadrant data"
              property {
                name        = "student_id"
                type        = "string"
                description = "Numeric student ID to query"
                required    = true
              }
            }
          }
        }
      }
    }
  }
}

# Gateway target for accordo-audio-feedback-tool
# Note: Force recreation if Lambda permission changes
resource "aws_bedrockagentcore_gateway_target" "accordo_audio_feedback_target" {
  name               = "${var.app_name}-AccordoFeedback"
  gateway_identifier = aws_bedrockagentcore_gateway.agentcore_gateway.gateway_id
  
  # Force target refresh when Lambda permission is added/changed
  lifecycle {
    replace_triggered_by = [
      aws_lambda_permission.allow_gateway_invoke.id
    ]
  }

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.mcp_lambda.arn

        tool_schema {
          inline_payload {
            name        = "accordo_audio_feedback"
            description = <<-EOT
              MCP tool for retrieving audio feedback files from S3 for a student.
              
              Uses a single S3 bucket with student-specific prefixes (student-{cognito_sub}/feedback/).
              Lists and reads all text files under the student's prefix containing feedback 
              generated by another model on the student's playing ability, and returns the 
              aggregated feedback.
              
              The Cognito sub is automatically extracted from the authentication context by the Gateway.
              The S3 path is constructed using the authenticated user's Cognito sub value.
              You do NOT need to provide any parameters - the tool automatically uses the authenticated user's context.
              
              Use this tool when you need to retrieve feedback about a student's audio/playing 
              performance. The tool will return all feedback files with their content, allowing 
              you to provide comprehensive feedback summaries to the user.
              
              [Updated: Force Gateway target refresh - Lambda verified working, investigating Gateway routing]
            EOT
            input_schema {
              type        = "object"
              description = "Input schema for retrieving student audio feedback. No parameters required - uses Cognito sub from auth context."
              # Empty object - no properties needed as Cognito sub is extracted from authentication context
              # Note: Some MCP implementations require at least one property, so we add an optional placeholder
              property {
                name        = "_placeholder"
                type        = "string"
                description = "Placeholder property - not used. Cognito sub is extracted from auth context."
                required    = false
              }
            }
          }
        }
      }
    }
  }

  # Ensure Lambda permission is created before Gateway target
  # This forces target refresh when permission is added
  depends_on = [
    aws_lambda_permission.allow_gateway_invoke
  ]
}
