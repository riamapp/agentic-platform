import json
import os
from datetime import datetime
from typing import Dict, Any
import boto3

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for DELETE /jobs/{jobId} endpoint.
    
    Cancels a running or pending job by updating its status to CANCELLED.
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
            current_status = job_item.get("status")
            
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
            
            # Only allow cancellation of PENDING or RUNNING jobs
            if current_status not in ["PENDING", "RUNNING"]:
                return {
                    "statusCode": 400,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                    },
                    "body": json.dumps({
                        "error": f"Cannot cancel job with status: {current_status}",
                        "currentStatus": current_status
                    })
                }
            
            # Update job status to CANCELLED
            now = datetime.utcnow().isoformat() + "Z"
            jobs_table.update_item(
                Key={"jobId": job_id},
                UpdateExpression="SET #status = :status, updatedAt = :updatedAt, #error = :error",
                ExpressionAttributeNames={
                    "#status": "status",
                    "#error": "error"
                },
                ExpressionAttributeValues={
                    ":status": "CANCELLED",
                    ":updatedAt": now,
                    ":error": "Job cancelled by user"
                }
            )
            
            # Return success response
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "jobId": job_id,
                    "status": "CANCELLED",
                    "message": "Job cancelled successfully"
                })
            }
            
        except Exception as db_error:
            print(f"Error cancelling job in DynamoDB: {db_error}")
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
        print(f"Error processing DELETE /jobs request: {error_message}")

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
