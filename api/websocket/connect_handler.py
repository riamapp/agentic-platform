import json
import os
from typing import Dict, Any
import boto3

dynamodb = boto3.resource("dynamodb")
CONNECTIONS_TABLE_NAME = os.environ.get("CONNECTIONS_TABLE_NAME")

# Get WebSocket API endpoint for sending messages back to client
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for WebSocket $connect route.
    
    Stores the connection in DynamoDB with optional sessionId from query string.
    Optionally sends connectionId back to client after connection is established.
    """
    try:
        connection_id = event["requestContext"]["connectionId"]
        
        # Use WebSocket API endpoint from environment or construct from event
        if WEBSOCKET_API_ENDPOINT:
            ws_endpoint = WEBSOCKET_API_ENDPOINT
        else:
            # Fallback: construct from domain and stage
            domain = event["requestContext"].get("domain")
            stage = event["requestContext"].get("stage")
            if domain and stage:
                ws_endpoint = f"https://{domain}/{stage}"
            else:
                ws_endpoint = None
        
        connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
        
        # Extract sessionId from query string if provided
        query_params = event.get("queryStringParameters") or {}
        session_id = query_params.get("sessionId")
        
        # If sessionId not provided in query string, try to preserve existing sessionId from previous connection
        if not session_id:
            try:
                existing = connections_table.get_item(Key={"connectionId": connection_id})
                if existing.get("Item") and existing["Item"].get("sessionId"):
                    session_id = existing["Item"]["sessionId"]
                    print(f"Preserving existing sessionId {session_id} for connection {connection_id}")
            except Exception as e:
                print(f"Could not check for existing sessionId: {e}")
        
        # Store connection in DynamoDB
        connection_item = {
            "connectionId": connection_id,
            "connectedAt": event["requestContext"]["connectedAt"]
        }
        
        if session_id:
            connection_item["sessionId"] = session_id
        
        # Store connection in DynamoDB (non-blocking - don't fail connection if this fails)
        try:
            connections_table.put_item(Item=connection_item)
            print(f"WebSocket connection stored in DynamoDB: {connection_id}, sessionId: {session_id}")
        except Exception as db_error:
            # Log but don't fail the connection - DynamoDB write failure shouldn't prevent WebSocket connection
            print(f"Warning: Failed to store connection in DynamoDB: {db_error}")
        
        print(f"WebSocket connection established: {connection_id}, sessionId: {session_id}")
        
        # Return success - don't try to send message immediately as connection may not be ready
        # The frontend already has the connection established, no need to send connectionId back
        return {"statusCode": 200}
    
    except Exception as e:
        print(f"Error handling WebSocket connect: {e}")
        return {"statusCode": 500}
