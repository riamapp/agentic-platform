import json
import os
from typing import Dict, Any
import boto3

dynamodb = boto3.resource("dynamodb")
CONNECTIONS_TABLE_NAME = os.environ.get("CONNECTIONS_TABLE_NAME")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for WebSocket $disconnect route.
    
    Removes the connection from DynamoDB.
    """
    try:
        connection_id = event["requestContext"]["connectionId"]
        connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
        
        # Remove connection from DynamoDB
        connections_table.delete_item(Key={"connectionId": connection_id})
        
        print(f"WebSocket connection disconnected: {connection_id}")
        
        return {"statusCode": 200}
    
    except Exception as e:
        print(f"Error handling WebSocket disconnect: {e}")
        return {"statusCode": 500}
