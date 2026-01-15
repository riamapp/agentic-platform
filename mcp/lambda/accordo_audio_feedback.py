"""
MCP tool for retrieving audio feedback files from S3 for a student.
Uses a single S3 bucket with student-specific prefixes (student-{cognito_sub}/feedback/).
The Cognito sub is extracted from the authentication context, not passed by the client.
"""

import json
import logging
import os
from typing import Any, Dict, List

import boto3

logger = logging.getLogger(__name__)


def accordo_audio_feedback_tool(event: Dict[str, Any], cognito_sub: str = None) -> Dict[str, Any]:
    """
    Retrieve audio feedback files from S3 for a student.
    
    Uses a single S3 bucket with student-specific prefixes. Lists all objects
    under the student-{cognito_sub}/feedback/ prefix, downloads each text file, and
    returns the aggregated feedback.
    
    The Cognito sub is extracted from the authentication context and used to
    construct the S3 path prefix. The client does not need to pass the sub value.
    
    Args:
        event: Dictionary containing tool arguments (student_id is no longer required)
        cognito_sub: (str, required) Cognito sub value extracted from auth context
    
    Returns:
        Dictionary with status_code and data/error keys.
        Data contains a list of feedback objects with file metadata and content.
    """
    try:
        # Validate event is a dictionary
        if not isinstance(event, dict):
            error_msg = f"Invalid event format - expected dictionary, got {type(event)}"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "errorType": "ValidationError",
                "message": error_msg
            }
        
        # Validate cognito_sub is provided
        if not cognito_sub:
            error_msg = "Cognito sub is required but was not provided from authentication context. Please ensure you are authenticated."
            logger.error(error_msg)
            return {
                "error": error_msg,
                "errorType": "AuthenticationError",
                "message": error_msg
            }
        
        # Get bucket name from environment variable
        bucket_name = os.environ.get("S3_STUDENT_FEEDBACK_BUCKET")
        if not bucket_name:
            error_msg = "S3_STUDENT_FEEDBACK_BUCKET environment variable is not configured"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "errorType": "ConfigurationError",
                "message": error_msg
            }
        
        # Use cognito_sub to construct the S3 prefix: /student-[cognito sub value]/feedback/
        prefix = f"student-{cognito_sub}/feedback/"
        
        logger.info(f"Listing objects in bucket {bucket_name} with prefix {prefix} for cognito_sub: {cognito_sub[:10]}...")
        
        # Initialize S3 client
        s3_client = boto3.client('s3')
        
        # List all objects in the bucket with the student prefix
        try:
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix
            )
        except Exception as e:
            error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
            if error_code == 'NoSuchBucket':
                error_msg = f"S3 bucket {bucket_name} does not exist"
                logger.error(error_msg)
                return {
                    "status_code": 404,
                    "error": error_msg,
                    "errorType": "NotFound",
                    "message": error_msg
                }
            error_msg = f"Error listing objects in S3: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "error": error_msg,
                "errorType": "S3Error",
                "message": error_msg
            }
        
        if 'Contents' not in response:
            message = f"No feedback files found in bucket {bucket_name} with prefix {prefix}"
            return {
                "status": "success",
                "status_code": 200,
                "data": {
                    "cognito_sub": cognito_sub,
                    "bucket_name": bucket_name,
                    "prefix": prefix,
                    "feedback_files": [],
                    "message": message
                },
                "content": [{"text": message}]
            }
        
        # Process each object
        feedback_files: List[Dict[str, Any]] = []
        
        for obj in response['Contents']:
            key = obj['Key']
            
            # Only process text files (adjust extension as needed)
            if not (key.endswith('.txt') or key.endswith('.text')):
                logger.debug(f"Skipping non-text file: {key}")
                continue
            
            try:
                # Download and read the file
                logger.info(f"Reading feedback file: {key}")
                obj_response = s3_client.get_object(Bucket=bucket_name, Key=key)
                content = obj_response['Body'].read().decode('utf-8')
                
                feedback_files.append({
                    "file_name": key,
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat(),
                    "content": content
                })
            except Exception as e:
                logger.warning(f"Failed to read file {key}: {e}")
                feedback_files.append({
                    "file_name": key,
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat(),
                    "error": f"Failed to read file: {str(e)}"
                })
        
        logger.info(f"Retrieved {len(feedback_files)} feedback files for cognito_sub: {cognito_sub[:10]}...")
        
        return {
            "status": "success",
            "status_code": 200,
            "data": {
                "cognito_sub": cognito_sub,
                "bucket_name": bucket_name,
                "prefix": prefix,
                "feedback_files": feedback_files,
                "total_files": len(feedback_files)
            },
            "content": [{"text": json.dumps({
                "cognito_sub": cognito_sub,
                "bucket_name": bucket_name,
                "prefix": prefix,
                "feedback_files": feedback_files,
                "total_files": len(feedback_files)
            }, default=str)}]
        }
        
    except Exception as e:
        error_msg = f"Error retrieving feedback: {str(e)}"
        logger.error(f"Error in accordo_audio_feedback_tool: {e}", exc_info=True)
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Traceback: {error_trace}")
        return {
            "error": error_msg,
            "errorType": "InternalError",
            "message": error_msg,
            "details": str(e)
        }
