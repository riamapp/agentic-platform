import json
import os
import logging
from datetime import datetime
from typing import Dict, Any
import boto3
from botocore.config import Config
from botocore.response import StreamingBody

# Set up logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import cost calculator
try:
    from utils.cost_calculator import calculate_cost_from_metadata
    logger.info("[JobWorker] Successfully imported cost_calculator")
except ImportError as e:
    # Fallback if utils not available (shouldn't happen in deployed environment)
    logger.warning(f"[JobWorker] WARNING: Failed to import cost_calculator: {e}")
    def calculate_cost_from_metadata(token_metadata: Dict[str, Any], model_id: str = None) -> Dict[str, float]:
        logger.warning(f"[JobWorker] Using fallback cost calculator (returns 0)")
        return {"inputCost": 0.0, "outputCost": 0.0, "totalCost": 0.0}

# Initialize AWS clients with appropriate timeouts
# Bedrock AgentCore can take a long time for complex operations, so set high timeouts
boto_config = Config(
    read_timeout=900,  # 15 minutes for reading streaming responses
    connect_timeout=60,  # 1 minute for connection
    retries={'max_attempts': 3}
)

dynamodb = boto3.resource("dynamodb")
apigateway = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ.get("WEBSOCKET_API_ENDPOINT"))
# AWS_REGION is automatically set by Lambda runtime
bedrock_agentcore = boto3.client("bedrock-agentcore", config=boto_config)

# Environment variables
JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME")
CONNECTIONS_TABLE_NAME = os.environ.get("CONNECTIONS_TABLE_NAME")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN")
AGENT_ENDPOINT_QUALIFIER = os.environ.get("AGENT_ENDPOINT_QUALIFIER", "DEV")

# Using iter_lines() - no chunk size needed, boto3 handles buffering internally


def send_websocket_message(connection_id: str, message: Dict[str, Any]) -> bool:
    """Send a message to a WebSocket connection."""
    try:
        logger.info(f"[JobWorker] Attempting to send WebSocket message to connection {connection_id}, type: {message.get('type')}")
        apigateway.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(message).encode("utf-8")
        )
        logger.info(f"[JobWorker] Successfully sent WebSocket message to connection {connection_id}")
        return True
    except apigateway.exceptions.GoneException:
        # Connection no longer exists
        logger.info(f"[JobWorker] Connection {connection_id} no longer exists (GoneException)")
        return False
    except Exception as e:
        logger.warning(f"[JobWorker] Error sending WebSocket message to {connection_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_job_status(job_id: str) -> str:
    """Get current job status from DynamoDB."""
    try:
        jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
        response = jobs_table.get_item(Key={"jobId": job_id})
        if "Item" in response:
            return response["Item"].get("status", "UNKNOWN")
        return "NOT_FOUND"
    except Exception as e:
        logger.warning(f"[JobWorker] Error getting job status: {e}")
        return "UNKNOWN"


def update_job_status(job_id: str, status: str, result: str = None, error: str = None):
    """Update job status in DynamoDB."""
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    update_expression = "SET #status = :status, updatedAt = :updatedAt"
    expression_attribute_names = {"#status": "status"}
    expression_attribute_values = {
        ":status": status,
        ":updatedAt": datetime.utcnow().isoformat() + "Z"
    }
    
    if result:
        update_expression += ", #result = :result"
        expression_attribute_names["#result"] = "result"
        expression_attribute_values[":result"] = result
    
    if error:
        update_expression += ", #error = :error"
        expression_attribute_names["#error"] = "error"
        expression_attribute_values[":error"] = error
    
    jobs_table.update_item(
        Key={"jobId": job_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_attribute_names,
        ExpressionAttributeValues=expression_attribute_values
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> None:
    """
    Lambda handler for processing jobs asynchronously.
    
    Expected event (from job_submit Lambda):
    {
        "jobId": "uuid",
        "sessionId": "uuid",
        "prompt": "user's prompt",
        "connectionId": "websocket-connection-id (optional)"
    }
    """
    try:
        job_id = event.get("jobId")
        session_id = event.get("sessionId")
        prompt = event.get("prompt")
        connection_id = event.get("connectionId")

        if not all([job_id, session_id, prompt]):
            raise ValueError("Missing required fields: jobId, sessionId, prompt")

        logger.info(f"Processing job {job_id} for session {session_id}")

        # If connectionId not provided, try to look it up from connections table by sessionId
        if not connection_id and session_id:
            try:
                connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                # Query connections table by sessionId using GSI
                logger.info(f"[JobWorker] Looking up connectionId for sessionId: {session_id}")
                logger.info(f"[JobWorker] Connections table name: {CONNECTIONS_TABLE_NAME}")
                
                response = connections_table.query(
                    IndexName="SessionIdIndex",
                    KeyConditionExpression="sessionId = :sessionId",
                    ExpressionAttributeValues={":sessionId": session_id},
                    Limit=5,  # Get up to 5 connections to find an active one
                    ScanIndexForward=False  # Get most recent connections first
                )
                
                items = response.get("Items", [])
                logger.info(f"[JobWorker] Connection lookup response: {len(items)} items found")
                
                if items:
                    # Try each connectionId until we find one that works
                    # Start with the most recent one
                    for item in items:
                        candidate_connection_id = item.get("connectionId")
                        if candidate_connection_id:
                            logger.info(f"[JobWorker] Testing connectionId {candidate_connection_id}")
                            # Test if connection is still active by trying to send a test message
                            # We'll test it when we try to send the RUNNING status
                            connection_id = candidate_connection_id
                            logger.info(f"[JobWorker] Using connectionId {connection_id} for sessionId {session_id}")
                            break
                    
                    if not connection_id:
                        logger.warning(f"[JobWorker] WARNING: Found items but no valid connectionId in them")
                else:
                    logger.warning(f"[JobWorker] WARNING: No connectionId found for sessionId {session_id}")
                    logger.info(f"[JobWorker] This means WebSocket updates will not be sent. Job will still be processed.")
                    logger.info(f"[JobWorker] Possible reasons:")
                    logger.info(f"[JobWorker]   1. WebSocket connection was not established")
                    logger.info(f"[JobWorker]   2. WebSocket connection was disconnected")
                    logger.info(f"[JobWorker]   3. sessionId mismatch between WebSocket and job")
            except Exception as e:
                logger.warning(f"[JobWorker] ERROR: Error looking up connectionId by sessionId: {e}")
                import traceback
                traceback.print_exc()
                # Continue without connectionId - job will still be processed but won't send WebSocket updates

        # Update job status to RUNNING
        update_job_status(job_id, "RUNNING")

        # Check for cancellation before starting processing
        current_status = get_job_status(job_id)
        if current_status == "CANCELLED":
            logger.info(f"[JobWorker] Job {job_id} was cancelled before processing started")
            # Try to look up connection_id if missing
            if not connection_id and session_id:
                try:
                    connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                    response = connections_table.query(
                        IndexName="SessionIdIndex",
                        KeyConditionExpression="sessionId = :sessionId",
                        ExpressionAttributeValues={":sessionId": session_id},
                        Limit=1,
                        ScanIndexForward=False
                    )
                    if response.get("Items") and len(response["Items"]) > 0:
                        connection_id = response["Items"][0]["connectionId"]
                        logger.info(f"[JobWorker] Found connectionId {connection_id} for cancellation message")
                except Exception as e:
                    logger.warning(f"[JobWorker] Error looking up connectionId for cancellation: {e}")
            
            if connection_id:
                send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "status",
                    "status": "CANCELLED",
                    "message": "Job cancelled by user"
                })
            else:
                logger.warning(f"[JobWorker] WARNING: No connectionId available to send CANCELLED status for job {job_id}")
            return  # Exit early - job was cancelled

        # Send initial status to WebSocket if connection exists
        if connection_id:
            logger.info(f"[JobWorker] Attempting to send RUNNING status to connection {connection_id} for job {job_id}, sessionId {session_id}")
            if send_websocket_message(connection_id, {
                "jobId": job_id,
                "type": "status",
                "status": "RUNNING",
                "message": "Job started processing"
            }):
                logger.info(f"[JobWorker] Successfully sent RUNNING status to connection {connection_id}")
            else:
                logger.warning(f"[JobWorker] WARNING: Failed to send RUNNING status to connection {connection_id}")
                logger.info(f"[JobWorker] Connection may be closed. Will try to look up a new connectionId if available.")
                # Try to look up connectionId again in case connection was re-established
                connection_id = None
                if session_id:
                    try:
                        connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                        response = connections_table.query(
                            IndexName="SessionIdIndex",
                            KeyConditionExpression="sessionId = :sessionId",
                            ExpressionAttributeValues={":sessionId": session_id},
                            Limit=1,
                            ScanIndexForward=False
                        )
                        if response.get("Items") and len(response["Items"]) > 0:
                            new_connection_id = response["Items"][0]["connectionId"]
                            logger.info(f"[JobWorker] Found new connectionId {new_connection_id}, will try using it for chunks")
                            connection_id = new_connection_id
                    except Exception as e:
                        logger.warning(f"[JobWorker] Error in retry lookup: {e}")
        else:
            logger.warning(f"[JobWorker] WARNING: No connectionId available for job {job_id}, sessionId {session_id}. WebSocket updates will not be sent.")
            logger.info(f"[JobWorker] Job will still be processed, but client will need to poll for updates.")

        # Invoke Bedrock AgentCore runtime
        if not AGENT_RUNTIME_ARN:
            raise ValueError("AGENT_RUNTIME_ARN environment variable not set")

        # Extract userId and frontendIdentifier from event (passed from submit_handler)
        user_id = event.get("userId")
        frontend_identifier = event.get("frontendIdentifier")
        logger.info(f"[JobWorker] Received event with userId: {user_id}")
        logger.info(f"[JobWorker] Received event with frontendIdentifier: {frontend_identifier}")
        logger.info(f"[JobWorker] Event keys: {list(event.keys())}")
        
        payload_dict = {"prompt": prompt}
        if session_id:
            payload_dict["sessionId"] = session_id
        # Include userId from event if available (passed from submit_handler)
        if user_id:
            payload_dict["userId"] = user_id
            logger.info(f"[JobWorker] Including userId in agent runtime payload: {user_id}")
        else:
            logger.warning(f"[JobWorker] WARNING: No userId in event - agent may not receive user context")
        # Include frontendIdentifier from event if available (passed from submit_handler)
        if frontend_identifier:
            payload_dict["frontendIdentifier"] = frontend_identifier
            logger.info(f"[JobWorker] Including frontendIdentifier in agent runtime payload: {frontend_identifier}")
        else:
            logger.warning(f"[JobWorker] WARNING: No frontendIdentifier in event - OAuth redirects may fail")
        # Include outputMode and outputSchemaName from event if available (passed from submit_handler)
        output_mode = event.get("outputMode")
        output_schema_name = event.get("outputSchemaName")
        if output_mode:
            payload_dict["outputMode"] = output_mode
            logger.info(f"[JobWorker] Including outputMode in agent runtime payload: {output_mode}")
        if output_schema_name:
            payload_dict["outputSchemaName"] = output_schema_name
            logger.info(f"[JobWorker] Including outputSchemaName in agent runtime payload: {output_schema_name}")

        payload_json = json.dumps(payload_dict)
        
        logger.info(f"[JobWorker] Invoking AgentCore runtime: {AGENT_RUNTIME_ARN}, endpoint: {AGENT_ENDPOINT_QUALIFIER}, session: {session_id}")
        logger.info(f"[JobWorker] Payload being sent to agent runtime (first 500 chars): {payload_json[:500]}...")

        response = bedrock_agentcore.invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            qualifier=AGENT_ENDPOINT_QUALIFIER,
            runtimeSessionId=session_id,
            payload=payload_json,
        )

        # Get the streaming body from response
        stream_body = None
        if "body" in response:
            stream_body = response["body"]
        elif "response" in response:
            stream_body = response["response"]
        elif "output" in response:
            stream_body = response["output"]
        else:
            raise ValueError(f"Response does not contain streaming body. Keys: {list(response.keys())}")

        if not isinstance(stream_body, StreamingBody):
            raise ValueError(f"Expected StreamingBody, got {type(stream_body)}")

        logger.info("Reading response from Bedrock AgentCore...")
        logger.info(f"[JobWorker] Invoked AgentCore with payload: {payload_json[:500]}...")

        # Check for cancellation after Bedrock invocation but before reading stream
        current_status = get_job_status(job_id)
        if current_status == "CANCELLED":
            logger.info(f"[JobWorker] Job {job_id} was cancelled after Bedrock invocation")
            # Try to look up connection_id if missing
            if not connection_id and session_id:
                try:
                    connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                    response = connections_table.query(
                        IndexName="SessionIdIndex",
                        KeyConditionExpression="sessionId = :sessionId",
                        ExpressionAttributeValues={":sessionId": session_id},
                        Limit=1,
                        ScanIndexForward=False
                    )
                    if response.get("Items") and len(response["Items"]) > 0:
                        connection_id = response["Items"][0]["connectionId"]
                        logger.info(f"[JobWorker] Found connectionId {connection_id} for cancellation message")
                except Exception as e:
                    logger.warning(f"[JobWorker] Error looking up connectionId for cancellation: {e}")
            
            if connection_id:
                send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "status",
                    "status": "CANCELLED",
                    "message": "Job cancelled by user"
                })
            else:
                logger.warning(f"[JobWorker] WARNING: No connectionId available to send CANCELLED status for job {job_id}")
            update_job_status(job_id, "CANCELLED", error="Job cancelled by user")
            return  # Exit early - job was cancelled

        # Use iter_lines() to read stream line-by-line - boto3 handles buffering automatically
        # This avoids mid-line splits and processes complete lines only
        response_lines = []
        total_bytes = 0
        line_count = 0
        chunks_sent_count = 0  # Track how many chunks were actually sent via WebSocket
        cancellation_check_counter = 0  # Counter to check for cancellation periodically
        connection_retry_counter = 0  # Counter to retry connection lookup periodically
        token_metadata = None  # Store token metadata extracted from stream
        model_id_from_metadata = None  # Store model ID extracted from metadata
        buffered_chunks = []  # Buffer chunks when connection is lost
        
        logger.info("[JobWorker] Starting to read stream line-by-line using iter_lines()")
        
        # Accumulate clean content to send as chunks (group multiple SSE lines together)
        accumulated_clean_content = ""
        
        for raw_line_bytes in stream_body.iter_lines():
            # Check for cancellation periodically (every 50 lines to avoid too many DynamoDB reads)
            cancellation_check_counter += 1
            if cancellation_check_counter >= 50:
                cancellation_check_counter = 0
                current_status = get_job_status(job_id)
                if current_status == "CANCELLED":
                    logger.info(f"[JobWorker] Job {job_id} was cancelled - stopping processing")
                    # Try to look up connection_id if missing
                    if not connection_id and session_id:
                        try:
                            connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                            response = connections_table.query(
                                IndexName="SessionIdIndex",
                                KeyConditionExpression="sessionId = :sessionId",
                                ExpressionAttributeValues={":sessionId": session_id},
                                Limit=1,
                                ScanIndexForward=False
                            )
                            if response.get("Items") and len(response["Items"]) > 0:
                                connection_id = response["Items"][0]["connectionId"]
                                logger.info(f"[JobWorker] Found connectionId {connection_id} for cancellation message")
                        except Exception as e:
                            logger.warning(f"[JobWorker] Error looking up connectionId for cancellation: {e}")
                    
                    # Send cancellation status via WebSocket
                    if connection_id:
                        send_websocket_message(connection_id, {
                            "jobId": job_id,
                            "type": "status",
                            "status": "CANCELLED",
                            "message": "Job cancelled by user"
                        })
                    else:
                        logger.warning(f"[JobWorker] WARNING: No connectionId available to send CANCELLED status for job {job_id}")
                    # Update job status (already CANCELLED, but ensure error message is set)
                    update_job_status(job_id, "CANCELLED", error="Job cancelled by user")
                    return  # Exit early - job was cancelled
            
            # Retry connection lookup periodically if connection was lost (every 30 lines)
            connection_retry_counter += 1
            if connection_retry_counter >= 30 and not connection_id and session_id:
                connection_retry_counter = 0
                try:
                    connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                    response = connections_table.query(
                        IndexName="SessionIdIndex",
                        KeyConditionExpression="sessionId = :sessionId",
                        ExpressionAttributeValues={":sessionId": session_id},
                        Limit=1,
                        ScanIndexForward=False
                    )
                    if response.get("Items") and len(response["Items"]) > 0:
                        new_connection_id = response["Items"][0]["connectionId"]
                        logger.info(f"[JobWorker] Found new connectionId {new_connection_id}, will retry sending buffered chunks")
                        connection_id = new_connection_id
                        # Send all buffered chunks to the new connection
                        if buffered_chunks:
                            logger.info(f"[JobWorker] Sending {len(buffered_chunks)} buffered chunks to reconnected client")
                            successfully_sent_count = 0
                            failed_start_index = None
                            for idx, buffered_chunk in enumerate(buffered_chunks):
                                if send_websocket_message(connection_id, {
                                    "jobId": job_id,
                                    "type": "chunk",
                                    "content": buffered_chunk
                                }):
                                    chunks_sent_count += 1
                                    successfully_sent_count += 1
                                else:
                                    # Connection failed again, stop sending and keep remaining chunks
                                    logger.warning(f"[JobWorker] Failed to send chunk to reconnected client, connection may have dropped again")
                                    failed_start_index = idx
                                    connection_id = None  # Mark connection as lost
                                    break
                            
                            # Only clear successfully sent chunks from buffer
                            if failed_start_index is not None:
                                buffered_chunks = buffered_chunks[failed_start_index:]
                                logger.info(f"[JobWorker] Successfully sent {successfully_sent_count} of {len(buffered_chunks) + successfully_sent_count} buffered chunks to reconnected client")
                                logger.warning(f"[JobWorker] Failed to send {len(buffered_chunks)} buffered chunks, keeping them in buffer for retry")
                            else:
                                # All chunks sent successfully
                                buffered_chunks = []
                                logger.info(f"[JobWorker] Successfully sent all {successfully_sent_count} buffered chunks to reconnected client")
                except Exception as e:
                    logger.warning(f"[JobWorker] Error retrying connection lookup during stream: {e}")
            line_count += 1
            total_bytes += len(raw_line_bytes)
            
            # Decode the line
            line = raw_line_bytes.decode("utf-8", errors="replace")
            response_lines.append(line)
            
            # Log first few lines for debugging
            if line_count <= 5:
                logger.info(f"[JobWorker] Line {line_count}: {line[:200]}")
            
            # Process SSE format lines
            original_line = line
            line = line.strip()
            
            if not line:
                continue
            
            # Check for SSE event types (e.g., "event: done", "event: complete")
            if line.startswith("event: "):
                event_type = line[7:].strip()  # Remove "event: " prefix
                logger.info(f"[JobWorker] SSE event type received: '{event_type}'")
                if event_type in ["done", "complete", "end", "finish"]:
                    logger.info(f"[JobWorker] SSE completion event detected: '{event_type}' - agent turn is complete")
            
            # Check if line starts with "data: "
            if line.startswith("data: "):
                # Log raw SSE line to see exactly what Bedrock is sending (INFO level for visibility)
                logger.info(f"[JobWorker] Raw SSE line (repr): {repr(line)}")
                logger.info(f"[JobWorker] Raw SSE line (first 200 chars): {line[:200]}")
                
                # Extract content after "data: "
                # Strip only to remove newline, but preserve content structure
                raw_content = line[6:].strip()
                logger.info(f"[JobWorker] After removing 'data: ' prefix and stripping newline: {repr(raw_content)}")
                
                # Remove surrounding quotes if present (handles both "text" and 'text')
                # IMPORTANT: Only remove outer quotes that are part of SSE format, not content quotes
                # Preserve all whitespace and quotes inside the content exactly as Bedrock sent it
                # SSE format: data: "content" where outer quotes are delimiters
                # Content quotes should be escaped as \" in the SSE format
                if raw_content.startswith('"') and raw_content.endswith('"'):
                    # Always remove outer quotes - they're SSE format delimiters
                    # Content quotes inside should be escaped as \" and will be unescaped later
                    content = raw_content[1:-1]  # Remove outer quotes, preserve internal content
                    logger.info(f"[JobWorker] Removed double quotes (SSE format), content (repr): {repr(content)}")
                elif raw_content.startswith("'") and raw_content.endswith("'"):
                    # Always remove outer quotes - they're SSE format delimiters
                    content = raw_content[1:-1]  # Remove outer quotes, preserve internal content
                    logger.info(f"[JobWorker] Removed single quotes (SSE format), content (repr): {repr(content)}")
                else:
                    # No quotes, use as-is (already stripped of newline)
                    content = raw_content
                    logger.info(f"[JobWorker] No quotes found, using as-is (repr): {repr(content)}")
                
                # Unescape common escape sequences (order matters - do \\ first)
                # This converts escaped quotes (\") back to actual quotes (")
                # This is critical for preserving quotes that are part of the content
                content = content.replace('\\\\', '\\')
                content = content.replace('\\n', '\n')
                content = content.replace('\\"', '"')  # Convert \" to "
                content = content.replace("\\'", "'")  # Convert \' to '
                content = content.replace('\\r', '\r')
                content = content.replace('\\t', '\t')
                logger.info(f"[JobWorker] After unescaping, content (repr): {repr(content)}")
                
                # Check if this content contains token metadata
                # Metadata format: {"__metadata__": {"inputTokens": X, "outputTokens": Y, "totalTokens": Z, "modelId": "..."}}
                if "__metadata__" in content:
                    try:
                        # Try to parse as JSON to extract metadata
                        metadata_json = json.loads(content)
                        if "__metadata__" in metadata_json:
                            token_metadata = metadata_json["__metadata__"]
                            # Extract model_id if present
                            if "modelId" in token_metadata:
                                model_id_from_metadata = token_metadata["modelId"]
                                logger.info(f"[JobWorker] Extracted model ID from metadata: {model_id_from_metadata}")
                            logger.info(f"[JobWorker] Extracted token metadata from stream: {token_metadata}")
                            # Don't send metadata as a content chunk - it will be included in COMPLETED status
                            continue
                    except (json.JSONDecodeError, ValueError):
                        # If it's not valid JSON or metadata is embedded in larger content, try to extract it
                        # Look for the metadata pattern in the content
                        # Updated pattern to optionally include modelId
                        import re
                        metadata_match = re.search(r'\{[^{}]*"__metadata__"[^{}]*\{[^{}]*"inputTokens"[^{}]*"outputTokens"[^{}]*"totalTokens"[^{}]*("modelId"[^{}]*)?\}[^{}]*\}', content)
                        if metadata_match:
                            try:
                                metadata_json = json.loads(metadata_match.group(0))
                                if "__metadata__" in metadata_json:
                                    token_metadata = metadata_json["__metadata__"]
                                    # Extract model_id if present
                                    if "modelId" in token_metadata:
                                        model_id_from_metadata = token_metadata["modelId"]
                                        logger.info(f"[JobWorker] Extracted model ID from embedded metadata: {model_id_from_metadata}")
                                    logger.info(f"[JobWorker] Extracted token metadata from embedded content: {token_metadata}")
                                    # Remove metadata from content before sending (preserve whitespace)
                                    content = content.replace(metadata_match.group(0), "")
                                    content = content.strip()  # Only strip after removing metadata
                                    if not content:
                                        continue  # Skip if content is now empty
                            except (json.JSONDecodeError, ValueError):
                                pass  # Continue processing as normal content if extraction fails
                
                # Accumulate content as-is from Bedrock
                # Pass through spacing exactly as Bedrock sends it - no modifications
                
                # Log the raw content being added (INFO level for visibility)
                # Special logging for quote chunks to verify unescaping is working
                if '"' in content or '\\"' in content:
                    logger.warning(f"[JobWorker] QUOTE CHUNK DETECTED - Adding content chunk: length={len(content)}, repr: {repr(content)}, contains quote: {'\"' in content}, contains escaped quote: {'\\\\\"' in content or '\\\"' in content}")
                logger.info(f"[JobWorker] Adding content chunk: length={len(content)}, first 50 chars: {repr(content[:50])}, last 50 chars: {repr(content[-50:])}")
                logger.info(f"[JobWorker] Content chunk repr (showing whitespace): {repr(content)}")
                
                accumulated_clean_content += content
                
                # Log accumulated state after adding
                if len(accumulated_clean_content) > 0:
                    logger.info(f"[JobWorker] Accumulated content length: {len(accumulated_clean_content)}, last 50 chars: {repr(accumulated_clean_content[-50:])}")
                
                # In structured output mode, don't send chunks during streaming - accumulate until complete
                # We'll parse and send the complete JSON at the end of the stream
                if output_mode == "structured":
                    logger.debug(f"[JobWorker] Structured output mode: accumulating content, not sending chunks yet")
                    continue  # Skip chunk sending in structured mode - wait for complete JSON
                
                # Send accumulated content via WebSocket immediately for real-time streaming (chat mode)
                if accumulated_clean_content:
                    if connection_id:
                        logger.info(f"[JobWorker] Sending WebSocket chunk to connection {connection_id}, content length: {len(accumulated_clean_content)}, first 100 chars: {accumulated_clean_content[:100]}")
                        if send_websocket_message(connection_id, {
                            "jobId": job_id,
                            "type": "chunk",
                            "content": accumulated_clean_content
                        }):
                            chunks_sent_count += 1
                            logger.info(f"[JobWorker] Successfully sent WebSocket chunk {chunks_sent_count} to connection {connection_id}")
                            accumulated_clean_content = ""  # Clear after sending
                        else:
                            # Connection is gone, buffer the chunk and try to reconnect
                            logger.info(f"[JobWorker] Connection {connection_id} is gone, buffering chunk for later delivery")
                            buffered_chunks.append(accumulated_clean_content)
                            accumulated_clean_content = ""  # Clear after buffering
                            connection_id = None
                            connection_retry_counter = 0  # Reset counter to retry immediately on next iteration
                    else:
                        # No connection available, buffer the chunk
                        logger.info(f"[JobWorker] No connection available, buffering chunk (buffer size: {len(buffered_chunks) + 1})")
                        buffered_chunks.append(accumulated_clean_content)
                        accumulated_clean_content = ""  # Clear after buffering
        
        # Send any remaining accumulated content (check for metadata first)
        # Also try to send buffered chunks if connection is available
        if accumulated_clean_content:
            # Buffer the remaining content if no connection
            if not connection_id:
                buffered_chunks.append(accumulated_clean_content)
                accumulated_clean_content = ""
        
        # Retry connection lookup one final time before sending final chunks
        if not connection_id and session_id and (accumulated_clean_content or buffered_chunks):
            try:
                connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                response = connections_table.query(
                    IndexName="SessionIdIndex",
                    KeyConditionExpression="sessionId = :sessionId",
                    ExpressionAttributeValues={":sessionId": session_id},
                    Limit=1,
                    ScanIndexForward=False
                )
                if response.get("Items") and len(response["Items"]) > 0:
                    connection_id = response["Items"][0]["connectionId"]
                    logger.info(f"[JobWorker] Found connectionId {connection_id} for final chunks delivery")
            except Exception as e:
                logger.warning(f"[JobWorker] Error in final connection lookup: {e}")
        
        # Send buffered chunks first if connection is available
        if connection_id and buffered_chunks:
            logger.info(f"[JobWorker] Sending {len(buffered_chunks)} buffered chunks to connection {connection_id}")
            successfully_sent_count = 0
            failed_start_index = None
            for idx, buffered_chunk in enumerate(buffered_chunks):
                if send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "chunk",
                    "content": buffered_chunk
                }):
                    chunks_sent_count += 1
                    successfully_sent_count += 1
                else:
                    # Connection failed, stop sending and keep remaining chunks
                    logger.warning(f"[JobWorker] Failed to send chunk, connection may have dropped")
                    failed_start_index = idx
                    connection_id = None  # Mark connection as lost
                    break
            
            # Only clear successfully sent chunks from buffer
            if failed_start_index is not None:
                buffered_chunks = buffered_chunks[failed_start_index:]
                logger.info(f"[JobWorker] Successfully sent {successfully_sent_count} of {len(buffered_chunks) + successfully_sent_count} buffered chunks")
                logger.warning(f"[JobWorker] Failed to send {len(buffered_chunks)} buffered chunks, keeping them in buffer")
            else:
                # All chunks sent successfully
                buffered_chunks = []
                logger.info(f"[JobWorker] Successfully sent all {successfully_sent_count} buffered chunks")
        
        # Handle structured output mode - must happen before regular content processing
        if output_mode == "structured":
            # Log what we have for debugging
            logger.info(f"[JobWorker] Structured output mode: processing accumulated content (length: {len(accumulated_clean_content) if accumulated_clean_content else 0})")
            if accumulated_clean_content:
                logger.info(f"[JobWorker] Structured output mode: first 500 chars of accumulated content: {accumulated_clean_content[:500]}")
            
            # Try to extract structured JSON (may be followed by metadata)
            # First, try to find the structured JSON object (before any metadata)
            structured_json_str = None
            
            if accumulated_clean_content:
                # Check if content is pure JSON (structured output)
                try:
                    parsed_json = json.loads(accumulated_clean_content.strip())
                    # If it parses and doesn't have __metadata__, it's the structured output
                    if "__metadata__" not in parsed_json:
                        structured_json_str = accumulated_clean_content.strip()
                        accumulated_clean_content = ""  # Clear after extracting
                        logger.info(f"[JobWorker] Structured output: found pure JSON (no metadata)")
                except json.JSONDecodeError:
                    # JSON might be incomplete or have metadata appended
                    # Try to extract the first complete JSON object
                    import re
                    # First, try to find JSON object followed by metadata
                    # Pattern: {...} followed by {"__metadata__": {...}}
                    metadata_pattern = r'\{"__metadata__"[^}]*(?:\{[^}]*\}[^}]*)*\}'
                    # Try to split on metadata if present
                    if re.search(metadata_pattern, accumulated_clean_content):
                        # Find the position where metadata starts
                        metadata_match = re.search(metadata_pattern, accumulated_clean_content)
                        if metadata_match:
                            # Extract everything before metadata as potential structured JSON
                            before_metadata = accumulated_clean_content[:metadata_match.start()].strip()
                            # Try to parse the part before metadata
                            if before_metadata:
                                try:
                                    test_parse = json.loads(before_metadata)
                                    if "__metadata__" not in test_parse:
                                        structured_json_str = before_metadata
                                        # Keep metadata for later processing
                                        accumulated_clean_content = accumulated_clean_content[metadata_match.start():]
                                        logger.info(f"[JobWorker] Extracted structured JSON before metadata")
                                except json.JSONDecodeError:
                                    pass
                    
                    # If still not found, try to find any complete JSON object (more flexible matching)
                    if not structured_json_str:
                        # Try to find JSON object by matching braces more carefully
                        # This handles nested objects better
                        brace_count = 0
                        json_start = -1
                        for i, char in enumerate(accumulated_clean_content):
                            if char == '{':
                                if brace_count == 0:
                                    json_start = i
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0 and json_start >= 0:
                                    # Found a complete JSON object
                                    candidate_json = accumulated_clean_content[json_start:i+1]
                                    try:
                                        test_parse = json.loads(candidate_json)
                                        if "__metadata__" not in test_parse:
                                            structured_json_str = candidate_json
                                            # Remove the structured JSON from accumulated content
                                            accumulated_clean_content = accumulated_clean_content[:json_start] + accumulated_clean_content[i+1:].strip()
                                            logger.info(f"[JobWorker] Extracted structured JSON using brace matching")
                                            break
                                    except json.JSONDecodeError:
                                        continue
                    
                    # Fallback: try regex pattern (original approach)
                    if not structured_json_str:
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', accumulated_clean_content, re.DOTALL)
                        if json_match:
                            try:
                                test_parse = json.loads(json_match.group(0))
                                if "__metadata__" not in test_parse:
                                    structured_json_str = json_match.group(0)
                                    # Remove the structured JSON from accumulated content
                                    accumulated_clean_content = accumulated_clean_content.replace(json_match.group(0), "").strip()
                                    logger.info(f"[JobWorker] Extracted structured JSON using regex fallback")
                            except json.JSONDecodeError:
                                pass
                
                # If we found structured JSON, send it
                if structured_json_str:
                    try:
                        parsed_json = json.loads(structured_json_str)
                        logger.info(f"[JobWorker] Structured output: parsed JSON successfully, preparing to send")
                        logger.info(f"[JobWorker] Structured output JSON preview (first 500 chars): {json.dumps(parsed_json)[:500]}")
                        
                        # Ensure we have a connection before sending
                        if not connection_id and session_id:
                            logger.warning(f"[JobWorker] No connection_id for structured output, attempting lookup...")
                            try:
                                connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                                response = connections_table.query(
                                    IndexName="SessionIdIndex",
                                    KeyConditionExpression="sessionId = :sessionId",
                                    ExpressionAttributeValues={":sessionId": session_id},
                                    Limit=1,
                                    ScanIndexForward=False
                                )
                                if response.get("Items") and len(response["Items"]) > 0:
                                    connection_id = response["Items"][0]["connectionId"]
                                    logger.info(f"[JobWorker] Found connectionId {connection_id} for structured output")
                            except Exception as e:
                                logger.warning(f"[JobWorker] Error looking up connectionId for structured output: {e}")
                        
                        if connection_id:
                            logger.info(f"[JobWorker] Sending structured output to connection {connection_id}")
                            if send_websocket_message(connection_id, {
                                "jobId": job_id,
                                "type": "structured",
                                "data": parsed_json  # Send parsed object, not string
                            }):
                                chunks_sent_count += 1
                                logger.info(f"[JobWorker] Successfully sent structured output with type='structured'")
                            else:
                                logger.error(f"[JobWorker] Failed to send structured output - connection may be closed")
                        else:
                            logger.error(f"[JobWorker] Cannot send structured output - no connection_id available")
                    except json.JSONDecodeError as e:
                        logger.error(f"[JobWorker] Failed to parse structured output as JSON: {e}")
                        logger.error(f"[JobWorker] Structured JSON string that failed to parse: {structured_json_str[:500]}")
                        # Fallback: send as chunk if we have a connection
                        if connection_id:
                            if send_websocket_message(connection_id, {
                                "jobId": job_id,
                                "type": "chunk",
                                "content": structured_json_str
                            }):
                                chunks_sent_count += 1
                else:
                    # No structured JSON found in structured output mode - send error
                    logger.error(f"[JobWorker] Structured output mode: no structured JSON found in response")
                    logger.error(f"[JobWorker] Accumulated content that failed to parse (first 1000 chars): {accumulated_clean_content[:1000] if accumulated_clean_content else '(empty)'}")
                    logger.error(f"[JobWorker] Accumulated content length: {len(accumulated_clean_content) if accumulated_clean_content else 0}")
                    if connection_id:
                        send_websocket_message(connection_id, {
                            "jobId": job_id,
                            "type": "error",
                            "status": "FAILED",
                            "message": "Structured output was requested but no valid JSON was returned",
                            "details": {
                                "accumulatedContentLength": len(accumulated_clean_content) if accumulated_clean_content else 0,
                                "accumulatedContentPreview": accumulated_clean_content[:500] if accumulated_clean_content else "(empty)"
                            }
                        })
        
        # Now handle remaining accumulated content (metadata, etc.) after structured output
        if connection_id and accumulated_clean_content:
            
            # Check if remaining content contains metadata (after structured JSON extraction)
            if "__metadata__" in accumulated_clean_content:
                try:
                    metadata_json = json.loads(accumulated_clean_content)
                    if "__metadata__" in metadata_json:
                        token_metadata = metadata_json["__metadata__"]
                        # Extract model_id if present
                        if "modelId" in token_metadata:
                            model_id_from_metadata = token_metadata["modelId"]
                            logger.info(f"[JobWorker] Extracted model ID from final chunk metadata: {model_id_from_metadata}")
                        logger.info(f"[JobWorker] Extracted token metadata from final chunk: {token_metadata}")
                        accumulated_clean_content = ""  # Don't send metadata as content
                except (json.JSONDecodeError, ValueError):
                    # Try to extract metadata from embedded content
                    import re
                    metadata_match = re.search(r'\{[^{}]*"__metadata__"[^{}]*\{[^{}]*"inputTokens"[^{}]*"outputTokens"[^{}]*"totalTokens"[^{}]*("modelId"[^{}]*)?\}[^{}]*\}', accumulated_clean_content)
                    if metadata_match:
                        try:
                            metadata_json = json.loads(metadata_match.group(0))
                            if "__metadata__" in metadata_json:
                                token_metadata = metadata_json["__metadata__"]
                                # Extract model_id if present
                                if "modelId" in token_metadata:
                                    model_id_from_metadata = token_metadata["modelId"]
                                    logger.info(f"[JobWorker] Extracted model ID from final embedded metadata: {model_id_from_metadata}")
                                logger.info(f"[JobWorker] Extracted token metadata from final embedded content: {token_metadata}")
                                # Remove metadata from content
                                accumulated_clean_content = accumulated_clean_content.replace(metadata_match.group(0), "").strip()
                        except (json.JSONDecodeError, ValueError):
                            pass
            
            # Send remaining content if any (after structured output and metadata extraction)
            if accumulated_clean_content:
                # Chat mode - send as chunk
                logger.info(f"[JobWorker] Sending final WebSocket chunk to connection {connection_id}, content length: {len(accumulated_clean_content)}")
                if send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "chunk",
                    "content": accumulated_clean_content
                }):
                    chunks_sent_count += 1
                    accumulated_clean_content = ""
        
        logger.info(f"[JobWorker] Stream reading complete. Read {line_count} lines, {total_bytes} bytes total from AgentCore")
        if total_bytes < 500:
            logger.warning(f"[JobWorker] WARNING: Very small response ({total_bytes} bytes) - agent response may be incomplete or truncated")
        
        # Event-driven approach: The stream ending IS the event that tells us the agent's text response is complete.
        # When iter_lines() stops iterating, that's the signal that Bedrock AgentCore has finished streaming.
        # We immediately process the result and send COMPLETED status - no waiting, no polling.
        logger.info(f"[JobWorker] Stream ended (iter_lines() stopped) - this is the completion event from Bedrock AgentCore")
        
        # Inspect the full response object to see if Bedrock AgentCore provides explicit completion metadata
        # This will help us determine if there's a more reliable way to detect completion
        logger.info(f"[JobWorker] === Inspecting Bedrock AgentCore response object for completion signals ===")
        logger.info(f"[JobWorker] Response object type: {type(response)}")
        logger.info(f"[JobWorker] Response object keys: {list(response.keys())}")
        
        # Log all response keys and their values (excluding the streaming body which we've already processed)
        for key in response.keys():
            if key not in ["body", "response", "output"]:
                value = response.get(key)
                # Truncate long values for readability
                if isinstance(value, (str, bytes)):
                    value_str = str(value)[:500] if len(str(value)) > 500 else str(value)
                    logger.info(f"[JobWorker] Response['{key}']: {value_str}")
                elif isinstance(value, dict):
                    logger.info(f"[JobWorker] Response['{key}'] (dict): {list(value.keys())}")
                    for sub_key in value.keys():
                        sub_value = value.get(sub_key)
                        if isinstance(sub_value, (str, bytes)):
                            sub_value_str = str(sub_value)[:200] if len(str(sub_value)) > 200 else str(sub_value)
                            logger.info(f"[JobWorker]   Response['{key}']['{sub_key}']: {sub_value_str}")
                        else:
                            logger.info(f"[JobWorker]   Response['{key}']['{sub_key}']: {sub_value}")
                else:
                    logger.info(f"[JobWorker] Response['{key}']: {value}")
        
        # Check if there's a status or completion field
        if "status" in response:
            logger.info(f"[JobWorker] Found 'status' field: {response.get('status')}")
        if "completion" in response:
            logger.info(f"[JobWorker] Found 'completion' field: {response.get('completion')}")
        if "done" in response:
            logger.info(f"[JobWorker] Found 'done' field: {response.get('done')}")
        if "finished" in response:
            logger.info(f"[JobWorker] Found 'finished' field: {response.get('finished')}")
        if "ResponseMetadata" in response:
            metadata = response.get("ResponseMetadata")
            logger.info(f"[JobWorker] Found 'ResponseMetadata': {metadata}")
        
        logger.info(f"[JobWorker] === End of response object inspection ===")

        # Combine all lines into final result
        result_text = "\n".join(response_lines)
        
        # Log raw response before cleaning (first 2000 chars)
        logger.info(f"[JobWorker] Raw AgentCore response (first 2000 chars): {result_text[:2000]}")
        logger.info(f"[JobWorker] Raw response length: {len(result_text)} characters")
        
        # Check for item count mentions in raw response
        import re
        item_count_mentions = re.findall(r'\b(\d+)\s+items?\b', result_text, re.IGNORECASE)
        if item_count_mentions:
            logger.info(f"[JobWorker] Item count mentions in raw response: {item_count_mentions}")
        
        # Strip SSE format from final result (same logic as chunk processing)
        # Bedrock AgentCore returns in SSE format: "data: "text"\n\ndata: "more"\n\n"
        clean_result = ""
        for line in result_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.startswith("data: "):
                content = line[6:].strip()
                # Remove surrounding quotes
                if content.startswith('"') and content.endswith('"'):
                    content = content[1:-1]
                elif content.startswith("'") and content.endswith("'"):
                    content = content[1:-1]
                # Unescape
                content = content.replace('\\\\', '\\').replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
                clean_result += content
        
        # Use cleaned result (fallback to original if cleaning produced empty result)
        final_result = clean_result if clean_result else result_text
        
        # Log final result details
        logger.info(f"[JobWorker] Final result length: {len(final_result)} characters")
        logger.info(f"[JobWorker] Clean result length: {len(clean_result)} characters")
        logger.info(f"[JobWorker] Final result (first 2000 chars): {final_result[:2000]}")
        
        # Check for item count mentions in final result
        import re
        final_item_counts = re.findall(r'\b(\d+)\s+items?\b', final_result, re.IGNORECASE)
        if final_item_counts:
            logger.info(f"[JobWorker] Item count mentions in final result: {final_item_counts}")

        # Update job status to COMPLETED
        update_job_status(job_id, "COMPLETED", result=final_result)

        # Check for cancellation one final time before marking as completed
        final_status = get_job_status(job_id)
        if final_status == "CANCELLED":
            logger.info(f"[JobWorker] Job {job_id} was cancelled - not sending COMPLETED status")
            # Cancellation status was already sent during processing
            return
        
        # Retry connection lookup if connection was lost during processing
        # This handles the case where the WebSocket disconnected and the client reconnected
        if not connection_id and session_id:
            try:
                connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                response = connections_table.query(
                    IndexName="SessionIdIndex",
                    KeyConditionExpression="sessionId = :sessionId",
                    ExpressionAttributeValues={":sessionId": session_id},
                    Limit=1,
                    ScanIndexForward=False  # Get most recent connection first
                )
                if response.get("Items") and len(response["Items"]) > 0:
                    connection_id = response["Items"][0]["connectionId"]
                    logger.info(f"[JobWorker] Retried connection lookup - found connectionId {connection_id} for sessionId {session_id}")
            except Exception as e:
                logger.warning(f"[JobWorker] Error retrying connection lookup: {e}")
        
        # Event-driven completion: Send COMPLETED status immediately when stream ends
        # The stream ending (read() returning empty) is the event that signals completion.
        # No waiting, no polling - just send the status immediately.
        if connection_id:
            if chunks_sent_count > 0:
                # Chunks were sent - send COMPLETED status message immediately (event-driven)
                # This tells the frontend the job is done without sending duplicate content
                logger.info(f"[JobWorker] Stream ended event received - sending COMPLETED status via WebSocket to connection {connection_id} ({chunks_sent_count} chunks were sent)")
                
                # Build COMPLETED status message with token metadata if available
                completed_message = {
                    "jobId": job_id,
                    "type": "status",
                    "status": "COMPLETED",
                    "message": "Job completed - all chunks have been sent"
                }
                
                # Include token metadata and cost if it was extracted from the stream
                if token_metadata:
                    # Create a copy of token_metadata without modelId (modelId is sent separately)
                    tokens_for_response = {k: v for k, v in token_metadata.items() if k != "modelId"}
                    completed_message["tokens"] = tokens_for_response
                    logger.info(f"[JobWorker] Including token metadata in COMPLETED status: {tokens_for_response}")
                    
                    # Include model_id in the response to frontend if available (separate from tokens)
                    if model_id_from_metadata:
                        completed_message["modelId"] = model_id_from_metadata
                        logger.info(f"[JobWorker] Including model ID in COMPLETED status: {model_id_from_metadata}")
                    
                    # Calculate cost from token metadata
                    # The calculate_cost_from_metadata function will automatically extract modelId from metadata if present
                    # Otherwise it will use the model_id parameter or fall back to defaults
                    try:
                        logger.info(f"[JobWorker] Calculating cost with token_metadata: {token_metadata}")
                        logger.info(f"[JobWorker] model_id_from_metadata: {model_id_from_metadata}")
                        # Pass model_id_from_metadata if available, otherwise let the function extract from metadata
                        cost_info = calculate_cost_from_metadata(token_metadata, model_id_from_metadata)
                        logger.info(f"[JobWorker] Cost calculation returned: {cost_info}")
                        completed_message["cost"] = cost_info
                        used_model_id = model_id_from_metadata or token_metadata.get("modelId") or "default"
                        logger.info(f"[JobWorker] Calculated cost using model {used_model_id}: ${cost_info['totalCost']:.6f} (input: ${cost_info['inputCost']:.6f}, output: ${cost_info['outputCost']:.6f})")
                    except Exception as e:
                        logger.warning(f"[JobWorker] Error calculating cost: {e}")
                        import traceback
                        traceback.print_exc()
                        # Continue without cost info if calculation fails
                        completed_message["cost"] = {"inputCost": 0.0, "outputCost": 0.0, "totalCost": 0.0}
                
                if not send_websocket_message(connection_id, completed_message):
                    logger.warning(f"[JobWorker] Failed to send COMPLETED status to connection {connection_id}")
            elif final_result:
                # No chunks were sent - send full result (fallback/non-streaming case)
                logger.info(f"[JobWorker] Stream ended event received - sending final result via WebSocket to connection {connection_id} (no chunks were sent, fallback)")
                if not send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "result",
                    "body": final_result
                }):
                    logger.warning(f"[JobWorker] Failed to send final result to connection {connection_id}")

    except Exception as e:
        error_message = str(e)
        error_type = type(e).__name__

        logger.warning(f"Error processing job {event.get('jobId', 'unknown')}: {error_message}")
        logger.warning(f"Error type: {error_type}")

        # Update job status to FAILED
        job_id = event.get("jobId")
        if job_id:
            update_job_status(job_id, "FAILED", error=error_message)

            # Try to get connectionId if not already set
            if not connection_id:
                connection_id = event.get("connectionId")
                # If still not set, try to look it up by sessionId
                if not connection_id and session_id:
                    try:
                        connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)
                        response = connections_table.query(
                            IndexName="SessionIdIndex",
                            KeyConditionExpression="sessionId = :sessionId",
                            ExpressionAttributeValues={":sessionId": session_id},
                            Limit=1
                        )
                        if response.get("Items") and len(response["Items"]) > 0:
                            connection_id = response["Items"][0]["connectionId"]
                    except Exception as e:
                        logger.warning(f"Error looking up connectionId for error message: {e}")
            
            # Send error to WebSocket if connection exists
            if connection_id:
                if not send_websocket_message(connection_id, {
                    "jobId": job_id,
                    "type": "error",
                    "status": "FAILED",
                    "message": error_message
                }):
                    logger.warning(f"Failed to send error to connection {connection_id}")
