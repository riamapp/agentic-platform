# Testing Guide - AWS Music Analysis

Step-by-step guide to test the AWS Transcribe + Bedrock Nova Pro music analysis system.

## Prerequisites

- Deployment completed successfully
- AWS CLI configured
- Test audio file available

## Test 1: Automatic S3 Trigger (Recommended)

This is the most realistic test - simulates how the system will work in production.

### Step 1: Prepare Audio File

Use any audio file (piano, guitar, singing, etc.):
- Supported formats: mp3, wav, m4a, mp4, flac
- Recommended size: < 10 MB for quick testing

If you have the piano recording from earlier:
```bash
cd /Users/kevalkumarsheth/Documents/Hackathon-2026/breaking-barrier-riam
```

### Step 2: Upload to S3

Upload to the S3 bucket with the correct prefix:

```bash
# Replace 'Piano student recording.mp3' with your file
aws s3 cp "Piano student recording.mp3" \
  s3://music-analysis-recordings-871442305974/recordings/S001/test.mp3 \
  --region us-west-2
```

**Key points:**
- Must use `recordings/` prefix to trigger Lambda
- Format: `recordings/{studentId}/{filename}`
- StudentId is extracted from the path (S001 in this example)

### Step 3: Watch Lambda Execution

Open a terminal and watch logs in real-time:

```bash
aws logs tail /aws/lambda/MusicAnalysisAWS --follow --region us-west-2
```

You should see:
```
[Lambda] Received event: {...}
[Lambda] Processing: bucket=..., key=recordings/S001/test.mp3, student=S001
[Transcribe] Starting transcription...
[Transcribe] Complete. Length: 342 chars
[Bedrock] Starting analysis...
[Bedrock] Analysis complete
[DynamoDB] Feedback stored: rec-1736848571
```

**Expected duration:** 30-120 seconds depending on audio length

### Step 4: Verify Results

Check DynamoDB for the analysis:

```bash
# Get the latest record
aws dynamodb scan \
  --table-name MusicAnalysisFeedback \
  --region us-west-2 \
  --max-items 1 \
  --no-paginate
```

Look for:
- `status: "completed"`
- `aiFeedback` with scores and recommendations
- `transcript` with audio transcription

### Step 5: Pretty Print Results

```bash
# Get and format the results
aws dynamodb scan \
  --table-name MusicAnalysisFeedback \
  --region us-west-2 \
  --max-items 1 | python3 -m json.tool
```

## Test 2: Manual Lambda Invocation

For testing without S3 upload (requires file already in S3).

### Step 1: Create Test Payload

```bash
cat > test-payload.json <<'EOF'
{
  "bucket": "music-analysis-recordings-871442305974",
  "key": "recordings/S001/test.mp3",
  "studentId": "S001",
  "recordingId": "manual-test-123"
}
EOF
```

### Step 2: Invoke Lambda

```bash
aws lambda invoke \
  --function-name MusicAnalysisAWS \
  --cli-binary-format raw-in-base64-out \
  --payload file://test-payload.json \
  --region us-west-2 \
  response.json
```

### Step 3: Check Response

```bash
cat response.json | python3 -m json.tool
```

Expected response:
```json
{
  "statusCode": 200,
  "body": "{\"success\": true, \"recordingId\": \"manual-test-123\", \"overallScore\": 85, \"message\": \"Analysis completed successfully\"}"
}
```

### Step 4: Verify in DynamoDB

```bash
aws dynamodb get-item \
  --table-name MusicAnalysisFeedback \
  --key '{"recordingId": {"S": "manual-test-123"}}' \
  --region us-west-2 | python3 -m json.tool
```

## Test 3: Query Student History

Test the GSI (Global Secondary Index) to retrieve all recordings for a student.

```bash
aws dynamodb query \
  --table-name MusicAnalysisFeedback \
  --index-name studentId-createdAt-index \
  --key-condition-expression "studentId = :sid" \
  --expression-attribute-values '{":sid": {"S": "S001"}}' \
  --scan-index-forward false \
  --max-items 10 \
  --region us-west-2 | python3 -m json.tool
```

This returns all recordings for student S001, sorted by most recent first.

## Test 4: Error Handling

Test how the system handles errors.

### Test 4a: Missing File

```bash
cat > error-test.json <<'EOF'
{
  "bucket": "music-analysis-recordings-871442305974",
  "key": "recordings/S001/nonexistent.mp3",
  "studentId": "S001",
  "recordingId": "error-test-404"
}
EOF

aws lambda invoke \
  --function-name MusicAnalysisAWS \
  --cli-binary-format raw-in-base64-out \
  --payload file://error-test.json \
  --region us-west-2 \
  error-response.json

cat error-response.json
```

Expected: Error response with status 500

### Test 4b: Invalid Format

Upload a non-audio file and see how Transcribe handles it:

```bash
echo "not an audio file" > dummy.txt
aws s3 cp dummy.txt \
  s3://music-analysis-recordings-871442305974/recordings/S001/invalid.mp3 \
  --region us-west-2

# Watch logs
aws logs tail /aws/lambda/MusicAnalysisAWS --follow --region us-west-2
```

Expected: Transcribe job fails, error stored in DynamoDB

## Expected Results Structure

A successful analysis should produce:

```json
{
  "recordingId": "rec-1736848571",
  "studentId": "S001",
  "createdAt": "2026-01-14T10:30:45.123456",
  "status": "completed",
  "s3Key": "recordings/S001/test.mp3",
  "s3Bucket": "music-analysis-recordings-871442305974",
  "transcript": "The student begins playing with a steady tempo...",
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
      },
      {
        "issue": "Dynamic range could be expanded",
        "severity": "moderate",
        "recommendation": "Practice crescendo and decrescendo exercises"
      }
    ],
    "practiceRecommendations": [
      "Practice scales daily for 10 minutes",
      "Record yourself to self-assess",
      "Focus on smooth transitions between chords"
    ],
    "encouragingMessage": "Great progress! Your technique is developing well. Keep up the excellent work on maintaining steady tempo."
  }
}
```

## Monitoring During Tests

### Real-time Log Streaming

Terminal 1 - Upload files:
```bash
aws s3 cp recording1.mp3 s3://music-analysis-recordings-871442305974/recordings/S001/recording1.mp3 --region us-west-2
```

Terminal 2 - Watch logs:
```bash
aws logs tail /aws/lambda/MusicAnalysisAWS --follow --region us-west-2
```

### Check Lambda Invocations

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=MusicAnalysisAWS \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum \
  --region us-west-2
```

### Check Lambda Errors

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=MusicAnalysisAWS \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum \
  --region us-west-2
```

## Performance Benchmarks

Expected processing times:

| Audio Length | Transcribe Time | Bedrock Time | Total Time |
|--------------|-----------------|--------------|------------|
| 30 seconds   | 10-15s          | 5-8s         | 15-25s     |
| 1 minute     | 15-25s          | 5-8s         | 20-35s     |
| 3 minutes    | 30-45s          | 5-10s        | 35-60s     |
| 5 minutes    | 45-75s          | 5-10s        | 50-90s     |

Note: Times are approximate and vary based on:
- Audio file size and quality
- AWS service load
- Network latency

## Troubleshooting Test Failures

### Issue: Lambda not triggering on S3 upload

**Check S3 trigger configuration:**
```bash
aws s3api get-bucket-notification-configuration \
  --bucket music-analysis-recordings-871442305974 \
  --region us-west-2
```

Should show Lambda function configuration with `recordings/` prefix filter.

**Fix:**
```bash
cd /Users/kevalkumarsheth/Documents/Hackathon-2026/breaking-barrier-riam/music-analysis-aws
./deploy.sh
```

### Issue: Transcribe job fails

**Check CloudWatch logs:**
```bash
aws logs tail /aws/lambda/MusicAnalysisAWS --since 10m --region us-west-2
```

Look for transcription error messages.

**Common causes:**
- Unsupported audio format
- Corrupted audio file
- File too large (max 2GB)
- IAM permission issues

### Issue: Bedrock access denied

**Verify IAM permissions:**
```bash
aws iam list-attached-role-policies --role-name RIAMAnalysisLambdaRole
```

Should include `AmazonBedrockFullAccess`.

**Fix:**
```bash
aws iam attach-role-policy \
  --role-name RIAMAnalysisLambdaRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

### Issue: DynamoDB write fails

**Check table exists:**
```bash
aws dynamodb describe-table \
  --table-name MusicAnalysisFeedback \
  --region us-west-2
```

**Check IAM permissions:**
```bash
aws iam list-attached-role-policies --role-name RIAMAnalysisLambdaRole | grep -i dynamo
```

### Issue: Timeout

Audio files longer than 10 minutes may exceed Lambda timeout.

**Increase timeout:**
```bash
aws lambda update-function-configuration \
  --function-name MusicAnalysisAWS \
  --timeout 900 \
  --region us-west-2
```

## Success Criteria

Your system is working correctly if:

1. ✅ S3 upload triggers Lambda automatically
2. ✅ Transcribe job completes successfully
3. ✅ Bedrock returns structured JSON feedback
4. ✅ DynamoDB stores complete record
5. ✅ CloudWatch logs show no errors
6. ✅ Response includes all expected fields (scores, strengths, recommendations)
7. ✅ Student query returns correct records

## Next Steps After Successful Testing

1. **Upload Multiple Recordings**: Test with different students and instruments
2. **Test GSI Performance**: Query student history with large datasets
3. **Integrate Frontend**: Build UI to display feedback
4. **Add Notifications**: SNS/SES for email notifications on completion
5. **Add Metrics**: Custom CloudWatch metrics for business analytics

## Test Checklist

- [ ] Deployed Lambda function successfully
- [ ] S3 bucket configured with trigger
- [ ] DynamoDB table created with GSI
- [ ] Uploaded test audio file
- [ ] Lambda invoked automatically
- [ ] Transcribe job completed
- [ ] Bedrock analysis returned results
- [ ] DynamoDB contains complete record
- [ ] No errors in CloudWatch logs
- [ ] Student query works correctly
- [ ] Tested error handling (missing file, invalid format)

---

**Ready to test?** Start with Test 1 (Automatic S3 Trigger) for the most realistic scenario.
