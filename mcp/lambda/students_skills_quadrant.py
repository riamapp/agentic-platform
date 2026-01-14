"""
MCP tool for querying DynamoDB table students-skills-quadrant by student ID.
"""

import logging
import os
from typing import Any, Dict

import boto3

logger = logging.getLogger(__name__)


def students_skills_quadrant_tool(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query DynamoDB table students-skills-quadrant by student ID.
    
    Args:
        event: Dictionary containing:
            - student_id: (str, required) Numeric student ID
            - userId: (str, automatically injected by Gateway)
    
    Returns:
        Dictionary with status_code and data/error keys
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
        
        # Get table name from environment variable
        table_name = os.environ.get("DYNAMODB_SKILLS_QUADRANT_TABLE", "students-skills-quadrant")
        
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        logger.info(f"Querying DynamoDB table {table_name} for student_id: {student_id}")
        
        # Query by student_id (assuming student_id is the partition key)
        response = table.get_item(
            Key={
                'student_id': student_id
            }
        )
        
        if 'Item' not in response:
            return {
                "status_code": 404,
                "error": f"Student with ID {student_id} not found in skills quadrant",
                "errorType": "NotFound"
            }
        
        data = response['Item']
        
        logger.info(f"Successfully retrieved data for student_id: {student_id}")
        return {
            "status_code": 200,
            "data": data
        }
        
    except Exception as e:
        logger.error(f"Error in students_skills_quadrant_tool: {e}", exc_info=True)
        return {
            "error": f"Error querying DynamoDB: {str(e)}",
            "errorType": "InternalError"
        }
