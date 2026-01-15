"""
Lambda handler for student feedback file management API.

Endpoints:
- POST /feedback/upload-url - Generate presigned URL for file upload
- GET /feedback/{path} - Get presigned URL for specific feedback file
- GET /feedback - List all feedback files for the student
"""

import json
import os
import urllib.parse
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

# Environment variables
PREFERENCES_TABLE_NAME = os.environ.get("PREFERENCES_TABLE_NAME")
S3_BUCKET_NAME = os.environ.get("S3_STUDENT_FEEDBACK_BUCKET")

# Presigned URL expiration times (in seconds)
UPLOAD_URL_EXPIRATION = 15 * 60  # 15 minutes
DOWNLOAD_URL_EXPIRATION = 60 * 60  # 1 hour


def _get_user_id_from_event(event: Dict[str, Any]) -> Optional[str]:
    """Extract Cognito user ID from API Gateway event."""
    try:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
        user_id = claims.get("sub")
        return user_id
    except (AttributeError, KeyError):
        return None


def _get_student_id_from_user(user_id: str, claims: Dict[str, Any]) -> str:
    """
    Get student_id from the authenticated user.
    
    Priority:
    1. Check Cognito custom attribute 'custom:student_id' (if configured)
    2. Use user_id directly as student_id (for students, user_id is their identifier)
    
    Args:
        user_id: Cognito user ID (sub claim)
        claims: Full Cognito claims dictionary
        
    Returns:
        student_id (always returns a value, using user_id as fallback)
    """
    # First, check for custom attribute in Cognito claims
    # Custom attributes in Cognito are prefixed with 'custom:'
    student_id = claims.get("custom:student_id")
    if student_id:
        return student_id
    
    # Fallback: use user_id as student_id
    # For students, their Cognito user_id should be their student identifier
    return user_id


def _validate_path_belongs_to_student(path: str, student_id: str) -> bool:
    """Validate that the S3 path belongs to the student."""
    expected_prefix = f"student-{student_id}/"
    return path.startswith(expected_prefix)


def _generate_upload_url(bucket: str, key: str, content_type: str) -> str:
    """Generate presigned PUT URL for file upload."""
    return s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=UPLOAD_URL_EXPIRATION,
    )


def _generate_download_url(bucket: str, key: str) -> str:
    """Generate presigned GET URL for file download."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
        },
        ExpiresIn=DOWNLOAD_URL_EXPIRATION,
    )


def _handle_upload_url(event: Dict[str, Any], student_id: str) -> Dict[str, Any]:
    """
    Handle POST /feedback/upload-url request.
    
    Generates a presigned URL for uploading a file to student-{id}/uploads/
    """
    try:
        # Handle empty or None body
        body_str = event.get("body") or "{}"
        if body_str is None or not body_str.strip():
            body_str = "{}"
        
        print(f"DEBUG: body_str={body_str}, type={type(body_str)}")
        body = json.loads(body_str)
        file_name = body.get("fileName")
        content_type = body.get("contentType", "application/octet-stream")
        
        print(f"DEBUG: file_name={file_name}, content_type={content_type}")
        
        if not file_name:
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"error": "fileName is required"}),
            }
        
        # Sanitize filename (remove path components for security)
        safe_filename = os.path.basename(file_name)
        
        # Generate S3 key - save to student-{id}/uploads/ prefix
        s3_key = f"student-{student_id}/uploads/{safe_filename}"
        
        # Generate presigned URL
        upload_url = _generate_upload_url(S3_BUCKET_NAME, s3_key, content_type)
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({
                "uploadUrl": upload_url,
                "key": s3_key,
            }),
        }
    except Exception as e:
        print(f"Error generating upload URL: {e}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": f"Error generating upload URL: {str(e)}"}),
        }


def _handle_get_feedback(event: Dict[str, Any], student_id: str) -> Dict[str, Any]:
    """
    Handle GET /feedback/{path} request.
    
    Generates a presigned URL for downloading a specific feedback file.
    """
    try:
        # Extract path from pathParameters
        path_params = event.get("pathParameters") or {}
        path = path_params.get("path")
        
        if not path:
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"error": "path parameter is required"}),
            }
        
        # URL decode the path
        s3_key = urllib.parse.unquote(path)
        
        # Validate path belongs to student
        if not _validate_path_belongs_to_student(s3_key, student_id):
            return {
                "statusCode": 403,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"error": "Access denied: path does not belong to this student"}),
            }
        
        # Verify file exists
        try:
            s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return {
                    "statusCode": 404,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json",
                    },
                    "body": json.dumps({"error": "File not found"}),
                }
            raise
        
        # Generate presigned URL
        download_url = _generate_download_url(S3_BUCKET_NAME, s3_key)
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({
                "downloadUrl": download_url,
                "key": s3_key,
            }),
        }
    except Exception as e:
        print(f"Error generating download URL: {e}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": f"Error generating download URL: {str(e)}"}),
        }


def _handle_list_feedback(event: Dict[str, Any], student_id: str) -> Dict[str, Any]:
    """
    Handle GET /feedback request.
    
    Lists all feedback files under student-{id}/feedback/
    """
    try:
        prefix = f"student-{student_id}/feedback/"
        
        # List objects with prefix
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=prefix,
        )
        
        files = []
        if "Contents" in response:
            for obj in response["Contents"]:
                key = obj["Key"]
                # Skip directories (keys ending with /)
                if key.endswith("/"):
                    continue
                
                files.append({
                    "key": key,
                    "size": obj["Size"],
                    "lastModified": obj["LastModified"].isoformat(),
                })
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({
                "files": files,
                "count": len(files),
            }),
        }
    except Exception as e:
        print(f"Error listing feedback files: {e}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": f"Error listing feedback files: {str(e)}"}),
        }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for feedback API endpoints.
    
    Routes requests based on HTTP method and path.
    """
    # Validate environment variables
    if not PREFERENCES_TABLE_NAME:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": "PREFERENCES_TABLE_NAME environment variable is not set"}),
        }
    
    if not S3_BUCKET_NAME:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": "S3_STUDENT_FEEDBACK_BUCKET environment variable is not set"}),
        }
    
    # Extract user ID from Cognito claims
    user_id = _get_user_id_from_event(event)
    if not user_id:
        return {
            "statusCode": 401,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": "Unauthorized: user ID not found in request"}),
        }
    
    # Get student_id from authenticated user
    # Try custom attribute first, then fall back to user_id
    try:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
        student_id = _get_student_id_from_user(user_id, claims)
        print(f"DEBUG: Using student_id={student_id} for user_id={user_id}")
    except Exception as e:
        print(f"Error getting student_id: {e}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": f"Error retrieving student ID: {str(e)}"}),
        }
    
    # Route based on HTTP method and path
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")
    
    # Handle OPTIONS for CORS preflight
    if http_method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Max-Age": "300",
            },
            "body": "",
        }
    
    # Route to appropriate handler
    # Use the 'resource' field to determine which API Gateway resource was matched
    # This is more reliable than parsing the path
    resource = event.get("resource", "")
    print(f"DEBUG: http_method={http_method}, path={path}, resource={resource}, pathParameters={event.get('pathParameters')}")
    
    path_params = event.get("pathParameters") or {}
    path_param_value = path_params.get("path", "")
    
    # Route based on resource path (most reliable method)
    # API Gateway resource paths: /feedback, /feedback/{path}, /feedback/upload-url
    if resource == "/feedback/upload-url" and http_method == "POST":
        return _handle_upload_url(event, student_id)
    elif resource == "/feedback/{path}" and http_method == "GET" and path_param_value:
        # Only handle GET requests with a path parameter (specific file)
        return _handle_get_feedback(event, student_id)
    elif resource == "/feedback" and http_method == "GET":
        # List all feedback
        return _handle_list_feedback(event, student_id)
    else:
        # Fallback: try to route based on path and method
        if http_method == "POST" and (path_param_value == "upload-url" or path.endswith("/upload-url") or "/upload-url" in path):
            return _handle_upload_url(event, student_id)
        elif http_method == "GET" and path_params.get("path") and path_param_value != "upload-url":
            return _handle_get_feedback(event, student_id)
        elif http_method == "GET" and (path.endswith("/feedback") or path == "/feedback"):
            return _handle_list_feedback(event, student_id)
    
    # Return 404 with CORS headers
    print(f"DEBUG: No route matched - method={http_method}, path={path}, resource={resource}, pathParam={path_param_value}")
    return {
        "statusCode": 404,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json",
        },
        "body": json.dumps({
            "error": "Endpoint not found",
            "debug": {
                "method": http_method,
                "path": path,
                "resource": resource,
                "pathParameters": path_params
            }
        }),
    }
