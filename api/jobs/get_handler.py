import json
import os
from typing import Dict, Any
import boto3

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for GET /jobs/{jobId} endpoint.
    
    Retrieves job status and result from DynamoDB.
    """
    try:
        # Extract jobId from path parameters
        path_parameters = event.get("pathParameters") or {}
        job_id = path_parameters.get("jobId")
        
        if not job_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": "Missing required parameter: jobId"})
            }
        
        # Get user info from Cognito authorizer (REST API format)
        user_id = None
        if event.get("requestContext", {}).get("authorizer", {}).get("claims", {}).get("sub"):
            user_id = event["requestContext"]["authorizer"]["claims"]["sub"]
        
        # Retrieve job from DynamoDB
        jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
        
        try:
            response = jobs_table.get_item(Key={"jobId": job_id})
            
            if "Item" not in response:
                return {
                    "statusCode": 404,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                    },
                    "body": json.dumps({"error": "Job not found"})
                }
            
            job_item = response["Item"]
            
            # Optional: Verify user owns this job (if userId is set)
            if user_id and job_item.get("userId") and job_item.get("userId") != user_id:
                return {
                    "statusCode": 403,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                    },
                    "body": json.dumps({"error": "Forbidden: You don't have access to this job"})
                }
            
            # Return job status and result
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "jobId": job_item.get("jobId"),
                    "sessionId": job_item.get("sessionId"),
                    "status": job_item.get("status"),
                    "result": job_item.get("result"),
                    "error": job_item.get("error"),
                    "createdAt": job_item.get("createdAt"),
                    "updatedAt": job_item.get("updatedAt"),
                })
            }
            
        except Exception as db_error:
            print(f"Error retrieving job from DynamoDB: {db_error}")
            return {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "error": "Internal server error",
                    "message": str(db_error)
                })
            }

    except Exception as e:
        error_message = str(e)
        print(f"Error processing GET /jobs request: {error_message}")

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": "Internal server error",
                "message": error_message
            })
        }
