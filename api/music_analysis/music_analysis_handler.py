"""
Music Analysis Lambda with AWS Transcribe + Bedrock Nova Pro
Triggered by S3 uploads to student-{id}/recordings/
Outputs feedback JSON to student-{id}/feedback/
"""

import json
import os
import logging
import time
import urllib.parse
from datetime import datetime
from typing import Dict, Any

import boto3
import requests

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
transcribe_client = boto3.client('transcribe')
bedrock_runtime = boto3.client('bedrock-runtime')

# Configuration from environment variables
BUCKET_NAME = os.environ.get('S3_STUDENT_FEEDBACK_BUCKET')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'us.amazon.nova-pro-v1:0')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for music analysis.

    Triggered by S3 uploads to student-{id}/recordings/
    1. Transcribe audio with AWS Transcribe
    2. Analyze transcript with Bedrock Nova Pro
    3. Store feedback JSON in S3 at student-{id}/feedback/
    """
    logger.info(f"[MusicAnalysis] Received event: {json.dumps(event, default=str)}")

    recording_id = None
    student_id = None

    try:
        # Parse S3 event
        if 'Records' in event:
            # S3 trigger
            record = event['Records'][0]
            bucket = record['s3']['bucket']['name']
            key = urllib.parse.unquote_plus(record['s3']['object']['key'])

            # Check if this is a recording upload (ignore other uploads)
            if '/recordings/' not in key:
                logger.info(f"[MusicAnalysis] Ignoring non-recording upload: {key}")
                return {
                    'statusCode': 200,
                    'body': json.dumps({'message': 'Ignored - not a recording upload'})
                }

            # Extract student ID from key: student-{id}/recordings/{filename}
            parts = key.split('/')
            student_id = parts[0].replace('student-', '') if parts[0].startswith('student-') else 'unknown'
            recording_id = f"rec-{int(datetime.now().timestamp())}"

        else:
            # Manual invocation for testing
            bucket = event.get('bucket', BUCKET_NAME)
            key = event['key']
            student_id = event.get('studentId', 'test')
            recording_id = event.get('recordingId', f"rec-{int(datetime.now().timestamp())}")

        logger.info(f"[MusicAnalysis] Processing: bucket={bucket}, key={key}, student={student_id}")

        # Step 1: Transcribe audio with AWS Transcribe
        logger.info("[Transcribe] Starting transcription...")
        transcript_text = transcribe_audio(bucket, key, recording_id)
        logger.info(f"[Transcribe] Complete. Length: {len(transcript_text)} chars")

        # Step 2: Analyze with Bedrock Nova Pro
        logger.info("[Bedrock] Starting analysis...")
        prompt = create_analysis_prompt(transcript_text)
        ai_feedback = analyze_with_bedrock(prompt)
        logger.info("[Bedrock] Analysis complete")

        # Step 3: Store feedback in S3
        feedback_key = f"student-{student_id}/feedback/{recording_id}.json"
        feedback_data = {
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

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=feedback_key,
            Body=json.dumps(feedback_data, indent=2),
            ContentType='application/json'
        )
        logger.info(f"[S3] Feedback stored: {feedback_key}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'recordingId': recording_id,
                'feedbackKey': feedback_key,
                'overallScore': ai_feedback.get('overallScore', 0),
                'message': 'Analysis completed successfully'
            })
        }

    except Exception as e:
        logger.error(f"[Error] {str(e)}")

        # Store error feedback in S3 if we have enough context
        if recording_id and student_id and BUCKET_NAME:
            try:
                error_key = f"student-{student_id}/feedback/{recording_id}.json"
                error_data = {
                    'recordingId': recording_id,
                    'studentId': student_id,
                    'createdAt': datetime.now().isoformat(),
                    'status': 'failed',
                    'errorMessage': str(e)
                }
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=error_key,
                    Body=json.dumps(error_data, indent=2),
                    ContentType='application/json'
                )
            except Exception as store_error:
                logger.error(f"[Error] Failed to store error feedback: {store_error}")

        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }


def transcribe_audio(bucket: str, key: str, recording_id: str) -> str:
    """
    Transcribe audio file using AWS Transcribe.

    Args:
        bucket: S3 bucket name
        key: S3 object key
        recording_id: Unique recording identifier for job naming

    Returns:
        Transcribed text content
    """
    job_name = f"music-analysis-{recording_id}"
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

    # Wait for transcription to complete (max ~2 minutes)
    max_tries = 60
    while max_tries > 0:
        max_tries -= 1
        job = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        status = job['TranscriptionJob']['TranscriptionJobStatus']

        if status == 'COMPLETED':
            # Get transcript
            transcript_uri = job['TranscriptionJob']['Transcript']['TranscriptFileUri']

            # Fetch transcript JSON
            response = requests.get(transcript_uri)
            transcript_data = response.json()

            # Extract text
            transcript_text = transcript_data['results']['transcripts'][0]['transcript']

            # Cleanup job
            try:
                transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
            except Exception as cleanup_error:
                logger.warning(f"[Transcribe] Cleanup warning: {cleanup_error}")

            return transcript_text

        elif status == 'FAILED':
            error = job['TranscriptionJob'].get('FailureReason', 'Unknown error')
            raise Exception(f"Transcription failed: {error}")

        time.sleep(2)

    raise Exception("Transcription timeout after 120 seconds")


def create_analysis_prompt(transcript: str) -> str:
    """
    Create analysis prompt for Bedrock Nova Pro.

    Args:
        transcript: Transcribed text from the audio recording

    Returns:
        Formatted prompt for AI analysis
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


def analyze_with_bedrock(prompt: str) -> Dict[str, Any]:
    """
    Analyze transcript with Amazon Bedrock Nova Pro.

    Args:
        prompt: Analysis prompt with transcript

    Returns:
        Parsed JSON feedback from Bedrock
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

    # Parse JSON from response (handle markdown code blocks)
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
