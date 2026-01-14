"""
Music Analysis Lambda with AWS Transcribe + Bedrock Nova Pro
All AWS-native solution - no external API keys needed
"""

import json
import os
import boto3
import time
import urllib.parse
from datetime import datetime

# Initialize AWS clients
s3_client = boto3.client('s3')
transcribe_client = boto3.client('transcribe')
bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

# Configuration
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'music-analysis-recordings-871442305974')
TABLE_NAME = os.environ.get('TABLE_NAME', 'MusicAnalysisFeedback')
BEDROCK_MODEL_ID = 'us.amazon.nova-pro-v1:0'


def lambda_handler(event, context):
    """
    Main Lambda handler
    1. Transcribe audio with AWS Transcribe
    2. Analyze transcript with Bedrock Nova Pro
    3. Store feedback in DynamoDB
    """

    print(f"[Lambda] Received event: {json.dumps(event, default=str)}")

    try:
        # Parse S3 event
        if 'Records' in event:
            # S3 trigger
            record = event['Records'][0]
            bucket = record['s3']['bucket']['name']
            key = urllib.parse.unquote_plus(record['s3']['object']['key'])

            # Extract student ID from key: recordings/{studentId}/{filename}
            parts = key.split('/')
            student_id = parts[1] if len(parts) > 1 else 'unknown'
            recording_id = f"rec-{int(datetime.now().timestamp())}"

        else:
            # Manual invocation
            bucket = event.get('bucket', BUCKET_NAME)
            key = event['key']
            student_id = event.get('studentId', 'S001')
            recording_id = event.get('recordingId', f"rec-{int(datetime.now().timestamp())}")

        print(f"[Lambda] Processing: bucket={bucket}, key={key}, student={student_id}")

        # Step 1: Transcribe audio with AWS Transcribe
        print("[Transcribe] Starting transcription...")
        transcript_text = transcribe_audio(bucket, key, recording_id)
        print(f"[Transcribe] Complete. Length: {len(transcript_text)} chars")

        # Step 2: Analyze with Bedrock Nova Pro
        print("[Bedrock] Starting analysis...")
        prompt = create_analysis_prompt(transcript_text)
        ai_feedback = analyze_with_bedrock(prompt)
        print("[Bedrock] Analysis complete")

        # Step 3: Store in DynamoDB
        table = dynamodb.Table(TABLE_NAME)

        item = {
            'recordingId': recording_id,
            'studentId': student_id,
            'createdAt': datetime.now().isoformat(),
            'status': 'completed',
            's3Key': key,
            's3Bucket': bucket,
            'transcript': transcript_text[:1000],  # Store first 1000 chars
            'aiFeedback': ai_feedback,
            'analysisModel': 'bedrock-nova-pro'
        }

        table.put_item(Item=item)
        print(f"[DynamoDB] Feedback stored: {recording_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'recordingId': recording_id,
                'overallScore': ai_feedback.get('overallScore', 0),
                'message': 'Analysis completed successfully'
            })
        }

    except Exception as e:
        print(f"[Error] {str(e)}")

        # Store error in DynamoDB
        try:
            table = dynamodb.Table(TABLE_NAME)
            table.put_item(Item={
                'recordingId': recording_id,
                'studentId': student_id,
                'createdAt': datetime.now().isoformat(),
                'status': 'failed',
                'errorMessage': str(e)
            })
        except:
            pass

        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }


def transcribe_audio(bucket, key, recording_id):
    """
    Transcribe audio file using AWS Transcribe
    """
    job_name = f"transcribe-{recording_id}"
    file_uri = f"s3://{bucket}/{key}"

    # Determine file format from extension
    file_ext = key.split('.')[-1].lower()
    media_format_map = {
        'mp3': 'mp3',
        'mp4': 'mp4',
        'm4a': 'mp4',
        'wav': 'wav',
        'flac': 'flac'
    }
    media_format = media_format_map.get(file_ext, 'mp3')

    # Start transcription job
    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': file_uri},
        MediaFormat=media_format,
        LanguageCode='en-US'
    )

    # Wait for transcription to complete
    max_tries = 60
    while max_tries > 0:
        max_tries -= 1
        job = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        status = job['TranscriptionJob']['TranscriptionJobStatus']

        if status == 'COMPLETED':
            # Get transcript
            transcript_uri = job['TranscriptionJob']['Transcript']['TranscriptFileUri']

            # Fetch transcript JSON
            import requests
            response = requests.get(transcript_uri)
            transcript_data = response.json()

            # Extract text
            transcript_text = transcript_data['results']['transcripts'][0]['transcript']

            # Cleanup job
            try:
                transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
            except:
                pass

            return transcript_text

        elif status == 'FAILED':
            error = job['TranscriptionJob'].get('FailureReason', 'Unknown error')
            raise Exception(f"Transcription failed: {error}")

        time.sleep(2)

    raise Exception("Transcription timeout")


def create_analysis_prompt(transcript):
    """
    Create analysis prompt for Bedrock Nova Pro
    """
    return f"""You are an expert music teacher analyzing a student's performance based on the transcription of their recording.

Here is the transcript of the student's performance:
{transcript}

Please provide detailed feedback in JSON format:

{{
  "technicalScore": 0-100,
  "expressiveScore": 0-100,
  "techniqueScore": 0-100,
  "overallScore": 0-100,
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "areasForImprovement": [
    {{
      "issue": "description",
      "severity": "minor/moderate/major",
      "recommendation": "how to fix"
    }}
  ],
  "practiceRecommendations": ["tip 1", "tip 2", "tip 3"],
  "encouragingMessage": "personalized encouraging message"
}}

Focus on:
1. Musical accuracy and timing
2. Expression and dynamics
3. Overall performance quality
4. Areas for improvement

Be specific, encouraging, and provide actionable feedback based on what you can infer from the transcript."""


def analyze_with_bedrock(prompt):
    """
    Analyze with Amazon Bedrock Nova Pro
    """
    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": prompt}
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 2000,
            "temperature": 0.7
        }
    }

    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(request_body)
    )

    response_body = json.loads(response['body'].read())

    # Extract text from response
    text_content = response_body['output']['message']['content'][0]['text']

    # Parse JSON from response
    if '```json' in text_content:
        json_start = text_content.find('```json') + 7
        json_end = text_content.find('```', json_start)
        text_content = text_content[json_start:json_end].strip()
    elif '```' in text_content:
        json_start = text_content.find('```') + 3
        json_end = text_content.find('```', json_start)
        text_content = text_content[json_start:json_end].strip()

    feedback = json.loads(text_content)

    return feedback
