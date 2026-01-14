"""
MCP tool for querying PostgreSQL RDS database riam-students-overture by student ID.
"""

import json
import logging
import os
from typing import Any, Dict

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _get_db_credentials(secret_arn: str) -> Dict[str, Any]:
    """Retrieve database credentials from AWS Secrets Manager."""
    secrets_client = boto3.client('secretsmanager')
    try:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response['SecretString'])
        return secret
    except Exception as e:
        logger.error(f"Failed to retrieve database credentials: {e}")
        raise


def _connect_to_database(secret_arn: str, endpoint: str, database_name: str):
    """Connect to PostgreSQL database using credentials from Secrets Manager."""
    credentials = _get_db_credentials(secret_arn)
    
    conn = psycopg2.connect(
        host=endpoint,
        database=database_name,
        user=credentials['username'],
        password=credentials['password'],
        port=credentials.get('port', 5432),
        connect_timeout=10
    )
    return conn


def students_overture_tool(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query PostgreSQL RDS database riam-students-overture by student ID.
    
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
        
        # Get configuration from environment variables
        secret_arn = os.environ.get("RDS_SECRET_ARN")
        endpoint = os.environ.get("RDS_INSTANCE_ENDPOINT")
        database_name = os.environ.get("RDS_DATABASE_NAME", "riam-students-overture")
        
        if not secret_arn or not endpoint:
            logger.error("Missing required environment variables: RDS_SECRET_ARN or RDS_INSTANCE_ENDPOINT")
            return {
                "error": "Database configuration is missing. Please contact administrator.",
                "errorType": "ConfigurationError"
            }
        
        # Connect to database
        logger.info(f"Connecting to database {database_name} at {endpoint} for student_id: {student_id}")
        conn = _connect_to_database(secret_arn, endpoint, database_name)
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Query by student_id - adjust query based on actual schema
                # This is a placeholder query - adjust based on actual table structure
                query = """
                    SELECT * 
                    FROM students 
                    WHERE student_id = %s
                """
                cursor.execute(query, (student_id,))
                result = cursor.fetchone()
                
                if not result:
                    return {
                        "status_code": 404,
                        "error": f"Student with ID {student_id} not found",
                        "errorType": "NotFound"
                    }
                
                # Convert result to dictionary
                data = dict(result)
                
                logger.info(f"Successfully retrieved data for student_id: {student_id}")
                return {
                    "status_code": 200,
                    "data": data
                }
        finally:
            conn.close()
            
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        return {
            "error": f"Database error: {str(e)}",
            "errorType": "DatabaseError"
        }
    except Exception as e:
        logger.error(f"Unexpected error in students_overture_tool: {e}", exc_info=True)
        return {
            "error": f"Unexpected error: {str(e)}",
            "errorType": "InternalError"
        }
