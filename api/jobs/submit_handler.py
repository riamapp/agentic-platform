import json
import os
import uuid
from datetime import datetime
from typing import Dict, Any
import boto3

# Initialize DynamoDB and Lambda clients
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME")
CONNECTIONS_TABLE_NAME = os.environ.get("CONNECTIONS_TABLE_NAME")
WORKER_LAMBDA_FUNCTION_NAME = os.environ.get("WORKER_LAMBDA_FUNCTION_NAME")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for POST /jobs endpoint.
    
    Creates a job record in DynamoDB and triggers the worker Lambda asynchronously.
    
    Expected request body:
    {
        "prompt": "user's prompt",
        "sessionId": "optional session ID",
        "connectionId": "WebSocket connection ID (optional, if provided via query param or header)"
    }
    """
    try:
        # Parse request body
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})

        prompt = body.get("prompt")
        session_id = body.get("sessionId")
        connection_id = body.get("connectionId")
        frontend_identifier = body.get("frontendIdentifier")
        output_mode = body.get("outputMode")
        output_schema_name = body.get("outputSchemaName")

        # Get connectionId from query params if not in body (for WebSocket connection tracking)
        if not connection_id:
            query_params = event.get("queryStringParameters") or {}
            connection_id = query_params.get("connectionId")
        
        # If connectionId not provided but sessionId is, try to look it up from connections table
        if not connection_id and session_id:
            try:
                connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                # Query connections table by sessionId using GSI
                response = connections_table.query(
                    IndexName="SessionIdIndex",
                    KeyConditionExpression="sessionId = :sessionId",
                    ExpressionAttributeValues={":sessionId": session_id},
                    Limit=1
                )
                if response.get("Items") and len(response["Items"]) > 0:
                    connection_id = response["Items"][0]["connectionId"]
                    print(f"Found connectionId {connection_id} for sessionId {session_id}")
            except Exception as e:
                print(f"Error looking up connectionId by sessionId: {e}")
                # Continue without connectionId - job will still be created but won't send WebSocket updates
        
        # Get user info from Cognito authorizer (REST API format)
        user_id = None
        if event.get("requestContext", {}).get("authorizer", {}).get("claims", {}).get("sub"):
            user_id = event["requestContext"]["authorizer"]["claims"]["sub"]
            print(f"[JobSubmit] Extracted userId from Cognito JWT claims: {user_id}")
            print(f"[JobSubmit] Full Cognito claims: {json.dumps(event.get('requestContext', {}).get('authorizer', {}).get('claims', {}), default=str)}")
        else:
            print(f"[JobSubmit] WARNING: No userId found in Cognito JWT claims")
            print(f"[JobSubmit] requestContext structure: {json.dumps(event.get('requestContext', {}), default=str)}")

        if not prompt:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": "Missing required field: prompt"})
            }

        # Generate jobId and sessionId if not provided
        job_id = str(uuid.uuid4())
        if not session_id:
            session_id = str(uuid.uuid4())

        # Get current timestamp
        now = datetime.utcnow().isoformat() + "Z"

        # Create job record in DynamoDB
        jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
        
        job_item = {
            "jobId": job_id,
            "sessionId": session_id,
            "userId": user_id,
            "prompt": prompt,
            "status": "PENDING",
            "createdAt": now,
            "updatedAt": now,
        }
        
        # Add connectionId if provided (for WebSocket updates)
        if connection_id:
            job_item["connectionId"] = connection_id
        
        # Set TTL to 7 days from now (in seconds since epoch)
        from datetime import timedelta
        ttl_timestamp = int((datetime.utcnow() + timedelta(days=7)).timestamp())
        job_item["ttl"] = ttl_timestamp

        jobs_table.put_item(Item=job_item)

        # Invoke worker Lambda asynchronously with job details
        worker_payload = {
            "jobId": job_id,
            "sessionId": session_id,
            "prompt": prompt,
            "connectionId": connection_id,
            "userId": user_id,  # Pass user_id to worker Lambda
            "frontendIdentifier": frontend_identifier,  # Pass frontend_identifier to worker Lambda
        }
        
        # Include outputMode and outputSchemaName if provided
        if output_mode:
            worker_payload["outputMode"] = output_mode
        if output_schema_name:
            worker_payload["outputSchemaName"] = output_schema_name
        
        if user_id:
            print(f"[JobSubmit] Passing userId to worker Lambda: {user_id}")
        else:
            print(f"[JobSubmit] WARNING: No userId to pass to worker Lambda")
        
        print(f"[JobSubmit] Worker payload (excluding prompt): jobId={job_id}, sessionId={session_id}, userId={user_id}, connectionId={connection_id}")

        lambda_client.invoke(
            FunctionName=WORKER_LAMBDA_FUNCTION_NAME,
            InvocationType="Event",  # Asynchronous invocation
            Payload=json.dumps(worker_payload),
        )

        # Return jobId immediately to client
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "jobId": job_id,
                "sessionId": session_id,
                "status": "PENDING",
                "message": "Job submitted successfully"
            })
        }

    except Exception as e:
        error_message = str(e)
        print(f"Error creating job: {error_message}")

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
