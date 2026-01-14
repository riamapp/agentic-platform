#!/bin/bash

# AWS Music Analysis Deployment Script
# Uses AWS Transcribe + Bedrock Nova Pro (no external API keys)

set -e

REGION="us-west-2"
ACCOUNT_ID="871442305974"
FUNCTION_NAME="MusicAnalysisAWS"
BUCKET_NAME="music-analysis-recordings-${ACCOUNT_ID}"
TABLE_NAME="MusicAnalysisFeedback"
ROLE_NAME="RIAMAnalysisLambdaRole"

echo "==================================="
echo "AWS Music Analysis Deployment"
echo "==================================="
echo ""
echo "Configuration:"
echo "  Region: ${REGION}"
echo "  Account: ${ACCOUNT_ID}"
echo "  Function: ${FUNCTION_NAME}"
echo "  Bucket: ${BUCKET_NAME}"
echo "  Table: ${TABLE_NAME}"
echo ""

# Step 1: Create S3 bucket if it doesn't exist
echo "[1/8] Checking S3 bucket..."
if aws s3 ls "s3://${BUCKET_NAME}" --region ${REGION} 2>&1 | grep -q 'NoSuchBucket'; then
    echo "Creating S3 bucket: ${BUCKET_NAME}"
    aws s3 mb "s3://${BUCKET_NAME}" --region ${REGION}
else
    echo "Bucket already exists: ${BUCKET_NAME}"
fi

# Step 2: Create DynamoDB table if it doesn't exist
echo "[2/8] Checking DynamoDB table..."
if aws dynamodb describe-table --table-name ${TABLE_NAME} --region ${REGION} 2>&1 | grep -q 'ResourceNotFoundException'; then
    echo "Creating DynamoDB table: ${TABLE_NAME}"
    aws dynamodb create-table \
        --table-name ${TABLE_NAME} \
        --attribute-definitions \
            AttributeName=recordingId,AttributeType=S \
            AttributeName=studentId,AttributeType=S \
            AttributeName=createdAt,AttributeType=S \
        --key-schema \
            AttributeName=recordingId,KeyType=HASH \
        --global-secondary-indexes \
            "[{
                \"IndexName\": \"studentId-createdAt-index\",
                \"KeySchema\": [
                    {\"AttributeName\": \"studentId\", \"KeyType\": \"HASH\"},
                    {\"AttributeName\": \"createdAt\", \"KeyType\": \"RANGE\"}
                ],
                \"Projection\": {\"ProjectionType\": \"ALL\"},
                \"ProvisionedThroughput\": {\"ReadCapacityUnits\": 5, \"WriteCapacityUnits\": 5}
            }]" \
        --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
        --region ${REGION}

    echo "Waiting for table to be active..."
    aws dynamodb wait table-exists --table-name ${TABLE_NAME} --region ${REGION}
else
    echo "Table already exists: ${TABLE_NAME}"
fi

# Step 3: Check/Create IAM role
echo "[3/8] Checking IAM role..."
if aws iam get-role --role-name ${ROLE_NAME} 2>&1 | grep -q 'NoSuchEntity'; then
    echo "Creating IAM role: ${ROLE_NAME}"

    # Create trust policy
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    aws iam create-role \
        --role-name ${ROLE_NAME} \
        --assume-role-policy-document file:///tmp/trust-policy.json

    # Attach policies
    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess

    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/AmazonTranscribeFullAccess

    echo "Waiting for IAM role to propagate..."
    sleep 10
else
    echo "IAM role already exists: ${ROLE_NAME}"

    # Ensure Transcribe permissions are attached
    echo "Ensuring Transcribe permissions..."
    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/AmazonTranscribeFullAccess 2>/dev/null || true
fi

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# Step 4: Package Lambda
echo "[4/8] Packaging Lambda function..."
rm -rf package function.zip
mkdir package

# Install dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt -t package/ -q

# Copy Lambda code
cp lambda_function.py package/

# Create deployment package
cd package && zip -r ../function.zip . -q && cd ..

PACKAGE_SIZE=$(ls -lh function.zip | awk '{print $5}')
echo "Package size: ${PACKAGE_SIZE}"

# Step 5: Upload to S3 if needed
if [ -f function.zip ]; then
    FILE_SIZE=$(stat -f%z function.zip 2>/dev/null || stat -c%s function.zip 2>/dev/null)
    if [ ${FILE_SIZE} -gt 50000000 ]; then
        echo "[5/8] Package too large, uploading to S3..."
        aws s3 cp function.zip "s3://${BUCKET_NAME}/lambda-code/function.zip" --region ${REGION}
        USE_S3=true
    else
        echo "[5/8] Package size OK for direct upload"
        USE_S3=false
    fi
else
    echo "Error: function.zip not found"
    exit 1
fi

# Step 6: Create or update Lambda function
echo "[6/8] Deploying Lambda function..."
if aws lambda get-function --function-name ${FUNCTION_NAME} --region ${REGION} 2>&1 | grep -q 'ResourceNotFoundException'; then
    echo "Creating Lambda function: ${FUNCTION_NAME}"

    if [ "$USE_S3" = true ]; then
        aws lambda create-function \
            --function-name ${FUNCTION_NAME} \
            --runtime python3.12 \
            --role ${ROLE_ARN} \
            --handler lambda_function.lambda_handler \
            --timeout 600 \
            --memory-size 1024 \
            --environment "Variables={BUCKET_NAME=${BUCKET_NAME},TABLE_NAME=${TABLE_NAME}}" \
            --code S3Bucket=${BUCKET_NAME},S3Key=lambda-code/function.zip \
            --region ${REGION}
    else
        aws lambda create-function \
            --function-name ${FUNCTION_NAME} \
            --runtime python3.12 \
            --role ${ROLE_ARN} \
            --handler lambda_function.lambda_handler \
            --timeout 600 \
            --memory-size 1024 \
            --environment "Variables={BUCKET_NAME=${BUCKET_NAME},TABLE_NAME=${TABLE_NAME}}" \
            --zip-file fileb://function.zip \
            --region ${REGION}
    fi
else
    echo "Updating Lambda function: ${FUNCTION_NAME}"

    if [ "$USE_S3" = true ]; then
        aws lambda update-function-code \
            --function-name ${FUNCTION_NAME} \
            --s3-bucket ${BUCKET_NAME} \
            --s3-key lambda-code/function.zip \
            --region ${REGION}
    else
        aws lambda update-function-code \
            --function-name ${FUNCTION_NAME} \
            --zip-file fileb://function.zip \
            --region ${REGION}
    fi

    # Update environment variables
    aws lambda update-function-configuration \
        --function-name ${FUNCTION_NAME} \
        --environment "Variables={BUCKET_NAME=${BUCKET_NAME},TABLE_NAME=${TABLE_NAME}}" \
        --region ${REGION}
fi

echo "Waiting for Lambda to be ready..."
sleep 5

# Step 7: Configure S3 trigger
echo "[7/8] Configuring S3 trigger..."

# Add Lambda permission for S3
aws lambda add-permission \
    --function-name ${FUNCTION_NAME} \
    --principal s3.amazonaws.com \
    --statement-id s3-trigger-permission \
    --action lambda:InvokeFunction \
    --source-arn "arn:aws:s3:::${BUCKET_NAME}" \
    --region ${REGION} 2>/dev/null || echo "Permission already exists"

# Configure S3 notification
cat > /tmp/s3-notification.json <<EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "MusicAnalysisAutoTrigger",
      "LambdaFunctionArn": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {
              "Name": "prefix",
              "Value": "recordings/"
            }
          ]
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-notification-configuration \
    --bucket ${BUCKET_NAME} \
    --notification-configuration file:///tmp/s3-notification.json \
    --region ${REGION}

echo "S3 trigger configured successfully"

# Step 8: Summary
echo ""
echo "==================================="
echo "✅ Deployment Complete!"
echo "==================================="
echo ""
echo "Resources:"
echo "  Lambda: ${FUNCTION_NAME}"
echo "  S3 Bucket: ${BUCKET_NAME}"
echo "  DynamoDB: ${TABLE_NAME}"
echo "  Region: ${REGION}"
echo ""
echo "How to test:"
echo "  1. Upload audio file:"
echo "     aws s3 cp your-audio.mp3 s3://${BUCKET_NAME}/recordings/S001/test.mp3 --region ${REGION}"
echo ""
echo "  2. Watch logs:"
echo "     aws logs tail /aws/lambda/${FUNCTION_NAME} --follow --region ${REGION}"
echo ""
echo "  3. Check results:"
echo "     aws dynamodb scan --table-name ${TABLE_NAME} --region ${REGION} --max-items 1"
echo ""
echo "Lambda will automatically:"
echo "  1. Transcribe audio with AWS Transcribe"
echo "  2. Analyze transcript with Bedrock Nova Pro"
echo "  3. Store feedback in DynamoDB"
echo ""
