# Music Analysis with AWS Transcribe + Bedrock Nova Pro

100% AWS-native solution for analyzing music performance recordings. No external API keys needed.

## Architecture

```
┌─────────────────┐
│  Upload Audio   │
│   to S3 Bucket  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  S3 Trigger     │
│  Auto-invokes   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AWS Lambda     │
│  Handler        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AWS Transcribe │
│  Audio → Text   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Bedrock Nova   │
│  Text Analysis  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  DynamoDB       │
│  Store Results  │
└─────────────────┘
```

## Key Features

- **AWS Transcribe**: Converts audio to text transcript
- **Bedrock Nova Pro**: Analyzes transcript and provides structured feedback
- **DynamoDB**: Stores analysis results with student indexing
- **S3 Auto-trigger**: Automatic processing on file upload
- **No External APIs**: Pure AWS solution with IAM-based authentication

## How It Works

1. **Audio Upload**: Student recordings uploaded to S3 (`recordings/{studentId}/*.mp3`)
2. **Transcription**: AWS Transcribe converts audio to text (supports mp3, wav, m4a, flac)
3. **AI Analysis**: Bedrock Nova Pro analyzes transcript and generates:
   - Technical score (0-100)
   - Expressive score (0-100)
   - Technique score (0-100)
   - Overall score (0-100)
   - Strengths list
   - Areas for improvement with severity
   - Practice recommendations
   - Encouraging message
4. **Storage**: Results saved to DynamoDB with GSI on studentId + createdAt

## Prerequisites

- AWS CLI configured with credentials
- Python 3.12+ installed
- IAM permissions for Lambda, S3, DynamoDB, Transcribe, Bedrock

## Quick Deployment

```bash
# Navigate to directory
cd music-analysis-aws

# Run deployment script
./deploy.sh
```

The script will:
1. Create S3 bucket: `music-analysis-recordings-871442305974`
2. Create DynamoDB table: `MusicAnalysisFeedback`
3. Create/verify IAM role with all required permissions
4. Package Lambda with dependencies
5. Deploy Lambda function: `MusicAnalysisAWS`
6. Configure S3 trigger for automatic invocation

## Manual Steps (if needed)

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Package Lambda

```bash
rm -rf package function.zip
mkdir package
pip3 install -r requirements.txt -t package/
cp lambda_function.py package/
cd package && zip -r ../function.zip . && cd ..
```

### 3. Create Infrastructure

**S3 Bucket:**
```bash
aws s3 mb s3://music-analysis-recordings-871442305974 --region us-west-2
```

**DynamoDB Table:**
```bash
aws dynamodb create-table \
  --table-name MusicAnalysisFeedback \
  --attribute-definitions \
      AttributeName=recordingId,AttributeType=S \
      AttributeName=studentId,AttributeType=S \
      AttributeName=createdAt,AttributeType=S \
  --key-schema AttributeName=recordingId,KeyType=HASH \
  --global-secondary-indexes \
      '[{
          "IndexName": "studentId-createdAt-index",
          "KeySchema": [
              {"AttributeName": "studentId", "KeyType": "HASH"},
              {"AttributeName": "createdAt", "KeyType": "RANGE"}
          ],
          "Projection": {"ProjectionType": "ALL"},
          "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
      }]' \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
  --region us-west-2
```

**IAM Role:**
```bash
# Ensure RIAMAnalysisLambdaRole has these policies:
# - AWSLambdaBasicExecutionRole
# - AmazonS3FullAccess
# - AmazonDynamoDBFullAccess
# - AmazonBedrockFullAccess
# - AmazonTranscribeFullAccess
```

### 4. Deploy Lambda

```bash
aws lambda create-function \
  --function-name MusicAnalysisAWS \
  --runtime python3.12 \
  --role arn:aws:iam::871442305974:role/RIAMAnalysisLambdaRole \
  --handler lambda_function.lambda_handler \
  --timeout 600 \
  --memory-size 1024 \
  --environment "Variables={BUCKET_NAME=music-analysis-recordings-871442305974,TABLE_NAME=MusicAnalysisFeedback}" \
  --zip-file fileb://function.zip \
  --region us-west-2
```

### 5. Configure S3 Trigger

**Add Lambda permission:**
```bash
aws lambda add-permission \
  --function-name MusicAnalysisAWS \
  --principal s3.amazonaws.com \
  --statement-id s3-trigger-permission \
  --action lambda:InvokeFunction \
  --source-arn arn:aws:s3:::music-analysis-recordings-871442305974 \
  --region us-west-2
```

**Configure S3 notification:**
```bash
cat > s3-notification.json <<'EOF'
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "MusicAnalysisAutoTrigger",
      "LambdaFunctionArn": "arn:aws:lambda:us-west-2:871442305974:function:MusicAnalysisAWS",
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
  --bucket music-analysis-recordings-871442305974 \
  --notification-configuration file://s3-notification.json \
  --region us-west-2
```

## Testing

### Automatic Processing (Recommended)

Upload an audio file and Lambda will automatically process it:

```bash
# Upload piano recording
aws s3 cp "Piano student recording.mp3" \
  s3://music-analysis-recordings-871442305974/recordings/S001/test.mp3 \
  --region us-west-2

# Watch logs in real-time
aws logs tail /aws/lambda/MusicAnalysisAWS --follow --region us-west-2
```

### Manual Invocation

```bash
# Create test payload
cat > test-payload.json <<'EOF'
{
  "bucket": "music-analysis-recordings-871442305974",
  "key": "recordings/S001/test.mp3",
  "studentId": "S001",
  "recordingId": "test-manual-123"
}
EOF

# Invoke Lambda
aws lambda invoke \
  --function-name MusicAnalysisAWS \
  --cli-binary-format raw-in-base64-out \
  --payload file://test-payload.json \
  --region us-west-2 \
  response.json

# View response
cat response.json | python3 -m json.tool
```

## Check Results

### View All Feedback

```bash
aws dynamodb scan \
  --table-name MusicAnalysisFeedback \
  --region us-west-2 \
  --max-items 5
```

### Get Specific Recording

```bash
aws dynamodb get-item \
  --table-name MusicAnalysisFeedback \
  --key '{"recordingId": {"S": "rec-1736848571"}}' \
  --region us-west-2
```

### Query by Student

```bash
aws dynamodb query \
  --table-name MusicAnalysisFeedback \
  --index-name studentId-createdAt-index \
  --key-condition-expression "studentId = :sid" \
  --expression-attribute-values '{":sid": {"S": "S001"}}' \
  --scan-index-forward false \
  --max-items 10 \
  --region us-west-2
```

## Response Format

DynamoDB items will have this structure:

```json
{
  "recordingId": "rec-1736848571",
  "studentId": "S001",
  "createdAt": "2026-01-14T10:30:45",
  "status": "completed",
  "s3Key": "recordings/S001/test.mp3",
  "s3Bucket": "music-analysis-recordings-871442305974",
  "transcript": "The student performed the piece with good timing...",
  "analysisModel": "bedrock-nova-pro",
  "aiFeedback": {
    "technicalScore": 85,
    "expressiveScore": 82,
    "techniqueScore": 87,
    "overallScore": 85,
    "strengths": [
      "Excellent tempo consistency",
      "Good hand coordination",
      "Clear articulation"
    ],
    "areasForImprovement": [
      {
        "issue": "Slight hesitation in measures 12-14",
        "severity": "minor",
        "recommendation": "Practice this section slowly with metronome at 80 BPM"
      }
    ],
    "practiceRecommendations": [
      "Practice scales daily for 10 minutes",
      "Record yourself to self-assess",
      "Focus on smooth transitions between chords"
    ],
    "encouragingMessage": "Great progress! Your technique is developing well."
  }
}
```

## Monitoring

### CloudWatch Logs

```bash
# View recent logs
aws logs tail /aws/lambda/MusicAnalysisAWS --since 10m --region us-west-2

# Follow logs in real-time
aws logs tail /aws/lambda/MusicAnalysisAWS --follow --region us-west-2
```

### Lambda Metrics

```bash
# View invocation count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=MusicAnalysisAWS \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum \
  --region us-west-2
```

### S3 Files

```bash
# List uploaded recordings
aws s3 ls s3://music-analysis-recordings-871442305974/recordings/ --recursive --region us-west-2
```

## Cost Estimate

Per recording analysis:

- **AWS Transcribe**: ~$0.024 per minute of audio (first 60 mins/month free)
- **Bedrock Nova Pro**: ~$0.008 per 1000 input tokens, ~$0.032 per 1000 output tokens
- **Lambda**: ~$0.001 per execution (600s @ 1024 MB)
- **S3**: ~$0.005 per GB/month storage
- **DynamoDB**: ~$0.001 per write

**Estimated total: $0.05-0.15 per recording** (varies by audio length)

## Troubleshooting

### Issue: Lambda not triggering

Check S3 trigger configuration:
```bash
aws s3api get-bucket-notification-configuration \
  --bucket music-analysis-recordings-871442305974 \
  --region us-west-2
```

### Issue: Transcribe timeout

Increase Lambda timeout for longer audio files:
```bash
aws lambda update-function-configuration \
  --function-name MusicAnalysisAWS \
  --timeout 900 \
  --region us-west-2
```

### Issue: Bedrock access denied

Ensure IAM role has Bedrock permissions:
```bash
aws iam attach-role-policy \
  --role-name RIAMAnalysisLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

### Issue: Transcribe access denied

Add Transcribe permissions:
```bash
aws iam attach-role-policy \
  --role-name RIAMAnalysisLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonTranscribeFullAccess
```

## Update Lambda Code

After modifying [lambda_function.py](lambda_function.py):

```bash
# Repackage
rm -rf package function.zip
mkdir package
pip3 install -r requirements.txt -t package/
cp lambda_function.py package/
cd package && zip -r ../function.zip . && cd ..

# Update function
aws lambda update-function-code \
  --function-name MusicAnalysisAWS \
  --zip-file fileb://function.zip \
  --region us-west-2
```

## Supported Audio Formats

- MP3 (`.mp3`)
- WAV (`.wav`)
- M4A (`.m4a`)
- MP4 audio (`.mp4`)
- FLAC (`.flac`)

## Key Advantages Over Gemini Solution

1. **No API Keys**: IAM-based authentication only
2. **No Rate Limits**: Pay-per-use with AWS quotas
3. **Better Integration**: Native AWS service integration
4. **More Reliable**: Enterprise-grade AWS services
5. **Easier Deployment**: No external dependencies to manage

## Files

- [lambda_function.py](lambda_function.py) - Lambda handler with Transcribe + Bedrock
- [requirements.txt](requirements.txt) - Python dependencies (boto3, requests)
- [deploy.sh](deploy.sh) - Automated deployment script
- [README.md](README.md) - This file

## Architecture Decisions

**Why Transcribe → Bedrock instead of direct audio analysis?**
- Bedrock Nova Pro text analysis is more reliable than audio analysis
- Transcription provides intermediate artifact for debugging
- Two-step process allows better error handling
- Transcript can be stored for future analysis

**Why not use Bedrock audio directly?**
- AWS Transcribe is purpose-built for speech-to-text
- Better accuracy for music terminology and performance descriptions
- Separate concerns: transcription vs analysis

## Next Steps

1. Deploy the Lambda function with `./deploy.sh`
2. Upload a test audio file to S3
3. Monitor CloudWatch logs to verify processing
4. Check DynamoDB for analysis results
5. Integrate with frontend to display feedback to students

## Support

For issues or questions, check:
- CloudWatch Logs: `/aws/lambda/MusicAnalysisAWS`
- DynamoDB table: `MusicAnalysisFeedback`
- S3 bucket: `music-analysis-recordings-871442305974`
