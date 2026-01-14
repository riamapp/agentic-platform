################################################################################
# Music Analysis Lambda
# Triggered by S3 uploads to student-*/recordings/
# Outputs feedback JSON to student-*/feedback/
################################################################################

locals {
  music_analysis_lambda_zip_path = "${path.module}/../build/music_analysis_lambda.zip"
}

################################################################################
# CloudWatch Log Group
################################################################################

resource "aws_cloudwatch_log_group" "music_analysis_lambda_logs" {
  name              = "/aws/lambda/${var.app_name}-MusicAnalysis"
  retention_in_days = 30

  tags = {
    Name = "${var.app_name}-MusicAnalysis-logs"
  }
}

################################################################################
# Lambda Package Build
################################################################################

resource "null_resource" "music_analysis_lambda_package" {
  triggers = {
    handler_hash      = filemd5("${path.module}/../api/music_analysis/music_analysis_handler.py")
    requirements_hash = filemd5("${path.module}/../api/music_analysis/requirements.txt")
  }

  provisioner "local-exec" {
    command     = "cd ${path.module}/.. && make music-analysis-lambda-zip"
    interpreter = ["/bin/bash", "-c"]
  }
}

################################################################################
# Lambda Function
################################################################################

resource "aws_lambda_function" "music_analysis_lambda" {
  function_name = "${var.app_name}-MusicAnalysis"
  role          = aws_iam_role.music_analysis_lambda_role.arn
  handler       = "music_analysis_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 600  # 10 minutes for transcription + analysis
  memory_size   = 1024

  filename         = local.music_analysis_lambda_zip_path
  source_code_hash = filebase64sha256(local.music_analysis_lambda_zip_path)

  environment {
    variables = {
      S3_STUDENT_FEEDBACK_BUCKET = aws_s3_bucket.student_feedback.id
      BEDROCK_MODEL_ID           = "us.amazon.nova-pro-v1:0"
    }
  }

  depends_on = [
    null_resource.music_analysis_lambda_package,
    aws_cloudwatch_log_group.music_analysis_lambda_logs
  ]

  tags = {
    Name = "${var.app_name}-MusicAnalysis"
  }
}

################################################################################
# IAM Role
################################################################################

resource "aws_iam_role" "music_analysis_lambda_role" {
  name = "${var.app_name}-MusicAnalysisLambdaRole"

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

  tags = {
    Name = "${var.app_name}-MusicAnalysisLambdaRole"
  }
}

# Basic Lambda execution policy (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "music_analysis_lambda_basic" {
  role       = aws_iam_role.music_analysis_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Service-specific permissions
resource "aws_iam_role_policy" "music_analysis_lambda_permissions" {
  role = aws_iam_role.music_analysis_lambda_role.id
  name = "${var.app_name}-MusicAnalysisPermissionsPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadRecordings"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.student_feedback.arn}/student-*/recordings/*"
      },
      {
        Sid    = "S3WriteFeedback"
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.student_feedback.arn}/student-*/feedback/*"
      },
      {
        Sid    = "TranscribeAccess"
        Effect = "Allow"
        Action = [
          "transcribe:StartTranscriptionJob",
          "transcribe:GetTranscriptionJob",
          "transcribe:DeleteTranscriptionJob"
        ]
        Resource = "*"
      },
      {
        Sid    = "TranscribeS3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::*transcribe*"
      },
      {
        Sid    = "BedrockInvokeModel"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/us.amazon.nova-pro-v1:0",
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/*"
        ]
      }
    ]
  })
}

################################################################################
# S3 Event Trigger
################################################################################

# Allow S3 to invoke the Lambda function
resource "aws_lambda_permission" "s3_invoke_music_analysis" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.music_analysis_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.student_feedback.arn
}

# S3 bucket notification to trigger Lambda on uploads
resource "aws_s3_bucket_notification" "music_analysis_trigger" {
  bucket = aws_s3_bucket.student_feedback.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.music_analysis_lambda.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "student-"
  }

  depends_on = [aws_lambda_permission.s3_invoke_music_analysis]
}

################################################################################
# Outputs
################################################################################

output "music_analysis_lambda_arn" {
  description = "ARN of the Music Analysis Lambda function"
  value       = aws_lambda_function.music_analysis_lambda.arn
}

output "music_analysis_lambda_name" {
  description = "Name of the Music Analysis Lambda function"
  value       = aws_lambda_function.music_analysis_lambda.function_name
}
