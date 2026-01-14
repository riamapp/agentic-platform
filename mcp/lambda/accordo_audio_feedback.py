"""
MCP tool for retrieving audio feedback files from S3 for a student.
Uses a single S3 bucket with student-specific prefixes (student-{id}/).
"""

import logging
import os
from typing import Any, Dict, List

import boto3

logger = logging.getLogger(__name__)


def accordo_audio_feedback_tool(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve audio feedback files from S3 for a student.
    
    Uses a single S3 bucket with student-specific prefixes. Lists all objects
    under the student-{student_id}/ prefix, downloads each text file, and
    returns the aggregated feedback.
    
    Args:
        event: Dictionary containing:
            - student_id: (str, required) Numeric student ID
            - userId: (str, automatically injected by Gateway)
    
    Returns:
        Dictionary with status_code and data/error keys.
        Data contains a list of feedback objects with file metadata and content.
    """
    try:
        student_id = event.get("student_id")
        
        if not student_id:
            return {
                "error": "student_id is required",
                "errorType": "ValidationError"
            }
        
        # Validate student_id is numeric
        try:
            int(student_id)
        except (ValueError, TypeError):
            return {
                "error": f"student_id must be numeric, got: {student_id}",
                "errorType": "ValidationError"
            }
        
        # Get bucket name from environment variable
        bucket_name = os.environ.get("S3_STUDENT_FEEDBACK_BUCKET")
        if not bucket_name:
            return {
                "error": "S3_STUDENT_FEEDBACK_BUCKET environment variable is not configured",
                "errorType": "ConfigurationError"
            }
        
        # Use student_id as prefix
        prefix = f"student-{student_id}/"
        
        logger.info(f"Listing objects in bucket {bucket_name} with prefix {prefix} for student_id: {student_id}")
        
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
                return {
                    "status_code": 404,
                    "error": f"S3 bucket {bucket_name} does not exist",
                    "errorType": "NotFound"
                }
            logger.error(f"Error listing objects in S3: {e}", exc_info=True)
            raise
        
        if 'Contents' not in response:
            return {
                "status_code": 200,
                "data": {
                    "student_id": student_id,
                    "bucket_name": bucket_name,
                    "prefix": prefix,
                    "feedback_files": [],
                    "message": f"No feedback files found in bucket {bucket_name} with prefix {prefix}"
                }
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
        
        logger.info(f"Retrieved {len(feedback_files)} feedback files for student_id: {student_id}")
        
        return {
            "status_code": 200,
            "data": {
                "student_id": student_id,
                "bucket_name": bucket_name,
                "prefix": prefix,
                "feedback_files": feedback_files,
                "total_files": len(feedback_files)
            }
        }
        
    except Exception as e:
        logger.error(f"Error in accordo_audio_feedback_tool: {e}", exc_info=True)
        return {
            "error": f"Error retrieving feedback: {str(e)}",
            "errorType": "InternalError"
        }
