################################################################################
# Feedback API Lambda Function
################################################################################

resource "null_resource" "feedback_lambda_package" {
  triggers = {
    handler_hash = filemd5("${path.module}/../api/feedback/feedback_handler.py")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make feedback-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}

locals {
  feedback_lambda_zip_path = "${path.module}/../build/feedback_lambda.zip"
}

resource "aws_lambda_function" "feedback_lambda" {
  function_name = "${var.app_name}-Feedback"
  role          = aws_iam_role.feedback_lambda_role.arn
  handler       = "feedback_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30

  filename         = local.feedback_lambda_zip_path
  source_code_hash = filebase64sha256(local.feedback_lambda_zip_path)

  environment {
    variables = {
      PREFERENCES_TABLE_NAME      = var.user_preferences_table_name
      S3_STUDENT_FEEDBACK_BUCKET = aws_s3_bucket.student_feedback.id
    }
  }

  depends_on = [
    null_resource.feedback_lambda_package,
    aws_s3_bucket.student_feedback
  ]
}

resource "aws_iam_role" "feedback_lambda_role" {
  name = "${var.app_name}-FeedbackLambdaRole"

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

resource "aws_iam_role_policy_attachment" "feedback_lambda_basic" {
  role       = aws_iam_role.feedback_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "feedback_lambda_permissions" {
  role = aws_iam_role.feedback_lambda_role.id
  name = "${var.app_name}-FeedbackLambdaPermissionsPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBGetPreferences"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem"
        ]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.user_preferences_table_name}"
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
          "s3:GetObject",
          "s3:HeadObject"
        ]
        Resource = "${aws_s3_bucket.student_feedback.arn}/student-*/*"
      },
      {
        Sid    = "S3PutObject"
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.student_feedback.arn}/student-*/upload/*"
      }
    ]
  })
}

################################################################################
# Lambda Permission for API Gateway
################################################################################

resource "aws_lambda_permission" "api_gateway_feedback_invoke" {
  statement_id  = "AllowAPIGatewayFeedbackInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.feedback_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api_gateway.execution_arn}/*/*"
}
