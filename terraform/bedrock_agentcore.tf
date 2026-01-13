################################################################################
# ECR Repository
################################################################################
resource "aws_ecr_repository" "agentcore_terraform_runtime" {
  name                 = "bedrock-agentcore/${lower(var.app_name)}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}

data "aws_ecr_authorization_token" "token" {}

locals {
  src_files = fileset("${path.module}/../src", "**")
  src_hashes = [
    for f in local.src_files :
    filesha256("${path.module}/../src/${f}")
  ]

  # Include pyproject.toml and Dockerfile in hash calculation to trigger rebuilds when dependencies change
  pyproject_hash  = filesha256("${path.module}/../pyproject.toml")
  dockerfile_hash = filesha256("${path.module}/../Dockerfile")

  # Collapse all file hashes into one
  src_hash = sha256(join("", concat(local.src_hashes, [local.pyproject_hash, local.dockerfile_hash])))
}

resource "null_resource" "docker_image" {
  depends_on = [aws_ecr_repository.agentcore_terraform_runtime]

  triggers = {
    src_hash = local.src_hash
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    environment = {
      AWS_PROFILE = "default"
      VERSION_TAG = local.src_hash
    }
    command = <<EOF
      source ~/.bash_profile || source ~/.profile || true

      if ! command -v docker &> /dev/null; then
        echo "Docker is not installed or not in PATH. Please install Docker and try again."
        exit 1
      fi

      aws ecr get-login-password --profile default | docker login --username AWS --password-stdin ${data.aws_ecr_authorization_token.token.proxy_endpoint}

      IMAGE_URI=${aws_ecr_repository.agentcore_terraform_runtime.repository_url}

      docker build -t $IMAGE_URI:latest -t $IMAGE_URI:$VERSION_TAG ${path.module}/..

      docker push $IMAGE_URI:latest
      docker push $IMAGE_URI:$VERSION_TAG
    EOF
  }
}

################################################################################
# AgentCore Runtime IAM Roles
################################################################################

data "aws_iam_policy_document" "bedrock_agentcore_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "agentcore_runtime_execution_role" {
  name        = "${var.app_name}-AgentCoreRuntimeRole"
  description = "Execution role for Bedrock AgentCore Runtime"

  assume_role_policy = data.aws_iam_policy_document.bedrock_agentcore_assume_role.json
}

# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html#runtime-permissions-execution
resource "aws_iam_role_policy" "agentcore_runtime_execution_role_policy" {
  role = aws_iam_role.agentcore_runtime_execution_role.id
  name = "${var.app_name}-AgentCoreRuntimeExecutionPolicy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRImageAccess"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [
          "arn:aws:ecr:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:repository/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:DescribeLogStreams",
          "logs:CreateLogGroup",
        ]
        Resource = [
          "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
        ]
        Resource = [
          "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
        ]
      },
      {
        Sid    = "ECRTokenAccess"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ]
        Resource = [
          "*",
        ]
      },
      {
        Effect   = "Allow"
        Resource = "*"
        Action   = "cloudwatch:PutMetricData"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "bedrock-agentcore"
          }
        }
      },
      {
        Sid    = "GetAgentAccessToken"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
          "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/agentName-*",
        ]
      },
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*",
        ]
      },
      {
        Sid    = "AWSMarketplaceAccess"
        Effect = "Allow"
        Action = [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe",
        ]
        Resource = "*"
      },
      {
        Sid    = "CodeInterpreterSession"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:StartCodeInterpreterSession",
          "bedrock-agentcore:InvokeCodeInterpreter"
        ]
        Resource = "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:aws:code-interpreter/aws.codeinterpreter.v1"
      },
      {
        Sid    = "BrowserSession"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:CreateBrowser",
          "bedrock-agentcore:ListBrowsers",
          "bedrock-agentcore:GetBrowser",
          "bedrock-agentcore:DeleteBrowser",
          "bedrock-agentcore:StartBrowserSession",
          "bedrock-agentcore:ListBrowserSessions",
          "bedrock-agentcore:GetBrowserSession",
          "bedrock-agentcore:StopBrowserSession",
          "bedrock-agentcore:UpdateBrowserStream",
          "bedrock-agentcore:ConnectBrowserAutomationStream",
          "bedrock-agentcore:ConnectBrowserLiveViewStream",
          "bedrock-agentcore:GetBrowserAutomationStream"
        ]
        Resource = "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:*"
      },
      {
        Sid    = "DynamoDBConversationTableAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = [
          "arn:aws:dynamodb:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.app_name}-Conversations"
        ]
      },
      {
        Sid    = "AgentCoreMemoryAccess"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:UpdateEvent",
          "bedrock-agentcore:DeleteEvent"
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:memory/${aws_bedrockagentcore_memory.agentcore_memory.id}"
        ]
      },
    ]
  })
}


################################################################################
# AgentCore Memory
################################################################################
resource "aws_bedrockagentcore_memory" "agentcore_memory" {
  name                  = "agenticPoc_Memory"
  description           = "Memory resource with 30 days event expiry"
  event_expiry_duration = 30
}

# Built-in SUMMARY strategy to maintain short-term conversational context per actor/session.
# This lets AgentCore create and use running summaries of each conversation.
resource "aws_bedrockagentcore_memory_strategy" "summary" {
  name        = "summary_strategy"
  memory_id   = aws_bedrockagentcore_memory.agentcore_memory.id
  type        = "SUMMARIZATION"
  description = "Conversation summarisation strategy per actor/session"

  # Namespace pattern recommended for summaries; AgentCore fills in {actorId} and {sessionId}.
  namespaces = ["/sessions/{actorId}/{sessionId}"]
}

################################################################################
# DynamoDB table for conversational transcripts (short-term context)
################################################################################

resource "aws_dynamodb_table" "conversation_table" {
  name         = "${var.app_name}-Conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sessionId"
  range_key    = "timestamp"

  attribute {
    name = "sessionId"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}

################################################################################
# AgentCore Runtime
################################################################################
resource "aws_bedrockagentcore_agent_runtime" "agentcore_runtime" {
  agent_runtime_name = "agenticPoc_Agent"
  role_arn           = aws_iam_role.agentcore_runtime_execution_role.arn

  agent_runtime_artifact {
    container_configuration {
      # Use versioned tag to force runtime update when source changes
      # The VERSION_TAG is based on source file hash, so it changes when code changes
      container_uri = "${aws_ecr_repository.agentcore_terraform_runtime.repository_url}:${local.src_hash}"
    }
  }

  depends_on = [
    null_resource.docker_image,
    aws_bedrockagentcore_memory.agentcore_memory,
    aws_iam_role.agentcore_runtime_execution_role
  ]

  network_configuration {
    network_mode = "PUBLIC"
  }
  environment_variables = {
    AWS_REGION                = data.aws_region.current.region
    MEMORY_ID                 = aws_bedrockagentcore_memory.agentcore_memory.id
    CONVERSATION_TABLE        = aws_dynamodb_table.conversation_table.name
    COGNITO_CLIENT_ID         = var.cognito_m2m_client_id
    COGNITO_CLIENT_SECRET     = var.cognito_client_secret
    COGNITO_TOKEN_URL         = "https://${replace(var.cognito_domain_url, "https://", "")}/oauth2/token"
    COGNITO_SCOPE             = var.cognito_scope
    LOG_LEVEL                 = "DEBUG"
    MAX_PROMPT_TOKENS         = tostring(var.max_prompt_tokens)
    BROWSER_MAX_HTML_SIZE      = tostring(var.browser_max_html_size)
    BROWSER_MAX_TEXT_SIZE      = tostring(var.browser_max_text_size)
    BROWSER_MAX_HTML_TOKENS    = tostring(var.browser_max_html_tokens)
    BROWSER_MAX_TEXT_TOKENS    = tostring(var.browser_max_text_tokens)
    TOKEN_WARNING_THRESHOLD    = tostring(var.token_warning_threshold)
  }

  # Force runtime to update when container image changes
  # The container_uri uses src_hash, so changing source files will trigger a new runtime version
  lifecycle {
    create_before_destroy = true
  }
}


################################################################################
# AgentCore Runtime Endpoints
################################################################################
resource "aws_bedrockagentcore_agent_runtime_endpoint" "dev_endpoint" {
  name             = "DEV"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id
  # DEV endpoint always uses the latest runtime version
  # The runtime's agent_runtime_version attribute reflects the current/latest version
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_version
}


resource "aws_bedrockagentcore_agent_runtime_endpoint" "prod_endpoint" {
  name                  = "PROD"
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.agentcore_runtime.agent_runtime_id
  agent_runtime_version = var.agent_runtime_version
  depends_on            = [aws_bedrockagentcore_agent_runtime_endpoint.dev_endpoint] # Prevents ConflictException
}
