import json
import logging
import os
from typing import Any, Dict, Optional

# Import tools from their modules
from students_overture import students_overture_tool
from students_skills_quadrant import students_skills_quadrant_tool
from accordo_audio_feedback import accordo_audio_feedback_tool

# Configure root logger for Lambda - Lambda automatically captures stdout/stderr
# Set root logger level to INFO to ensure all module loggers output
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Ensure there's a handler (Lambda runtime should provide one, but ensure it's configured)
if not root_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s:%(lineno)d - %(message)s'))
    root_logger.addHandler(handler)
else:
    # If handler exists, ensure it's set to INFO level
    for handler in root_logger.handlers:
        handler.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Lambda handler for Bedrock AgentCore Gateway MCP tools.

    Routes tool invocations to the appropriate tool handler based on the tool name
    provided in the Lambda context.

    Expected input:
        event: {
            # tool-specific arguments based on the tool schema
        }

    Context should contain:
        context.client_context.custom["bedrockAgentCoreToolName"]
        → e.g. "LambdaTarget___tool_name", etc.
    """
    # CRITICAL: Log immediately using print (always works) and logger
    print("=" * 80)
    print("LAMBDA HANDLER INVOKED - PRINT STATEMENT")
    print(f"Event type: {type(event)}")
    print(f"Context type: {type(context)}")
    
    logger.info("=" * 80)
    logger.info("LAMBDA HANDLER INVOKED - LOGGER")
    logger.info(f"Event type: {type(event)}")
    logger.info(f"Context type: {type(context)}")
    
    try:
        logger.info(f"Event (first 500 chars): {json.dumps(event, default=str)[:500]}")
        # Log context for debugging
        logger.info(f"Lambda invoked. Context type: {type(context)}")
        logger.info(f"Context has client_context: {hasattr(context, 'client_context')}")
        
        # Extract tool name from context
        extended_name = None
        
        # Log full context structure for debugging
        logger.info(f"Context full structure: {dir(context)}")
        if hasattr(context, 'client_context'):
            logger.info(f"hasattr(context, 'client_context'): {hasattr(context, 'client_context')}")
            logger.info(f"context.client_context value: {context.client_context}")
            logger.info(f"context.client_context is None: {context.client_context is None}")
            logger.info(f"context.client_context type: {type(context.client_context)}")
            if context.client_context:
                logger.info(f"context.client_context type: {type(context.client_context)}")
                logger.info(f"context.client_context attributes: {dir(context.client_context)}")
                if hasattr(context.client_context, 'custom'):
                    logger.info(f"context.client_context.custom exists: {context.client_context.custom is not None}")
                    if context.client_context.custom:
                        logger.info(f"client_context.custom type: {type(context.client_context.custom)}")
                        logger.info(f"client_context.custom content: {context.client_context.custom}")
                        if isinstance(context.client_context.custom, dict):
                            logger.info(f"client_context.custom keys: {list(context.client_context.custom.keys())}")
                            extended_name = context.client_context.custom.get("bedrockAgentCoreToolName")
                        else:
                            # Try to access as attribute
                            extended_name = getattr(context.client_context.custom, "bedrockAgentCoreToolName", None)
                            logger.info(f"Tried attribute access, got: {extended_name}")
        
        # Also check if tool name is in the event itself (Gateway passes it in event, not context!)
        # According to AWS docs, Gateway passes bedrockagentcoreToolName in the event
        if not extended_name and isinstance(event, dict):
            logger.info("Checking event for tool name...")
            logger.info(f"Event keys: {list(event.keys())}")
            logger.info(f"Full event structure: {json.dumps(event, default=str)}")
            # Check common alternative locations
            if "bedrockagentcoreToolName" in event:
                extended_name = event["bedrockagentcoreToolName"]
                logger.info(f"Found bedrockagentcoreToolName in event: {extended_name}")
            elif "bedrockAgentCoreToolName" in event:
                extended_name = event["bedrockAgentCoreToolName"]
                logger.info(f"Found bedrockAgentCoreToolName in event: {extended_name}")
            elif "toolName" in event:
                extended_name = event["toolName"]
                logger.info(f"Found toolName in event: {extended_name}")
            elif "tool_name" in event:
                extended_name = event["tool_name"]
                logger.info(f"Found tool_name in event: {extended_name}")
            elif "tool" in event and isinstance(event["tool"], dict):
                extended_name = event["tool"].get("name")
                logger.info(f"Found tool.name in event: {extended_name}")
        
        logger.info(f"Extended tool name from context/event: {extended_name}")
        
        tool_name = None
        # handle agentcore gateway tool naming convention
        # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html
        if extended_name and "___" in extended_name:
            tool_name = extended_name.split("___", 1)[1]
        elif extended_name:
            # Tool name might be passed directly without "___" prefix
            tool_name = extended_name
        
        logger.info(f"Extracted tool name: {tool_name}")
        
        # WORKAROUND: If Gateway doesn't pass tool name, infer from event structure
        # This is a fallback until Gateway configuration is fixed
        if not tool_name:
            logger.warning("Tool name not found in context or event. Attempting to infer from event structure...")
            logger.warning(f"Event structure: {json.dumps(event, default=str)}")
            
            # Infer tool from event structure:
            # - Empty event {} = accordo_audio_feedback (no parameters)
            # - Event with student_id = students_overture or students_skills_quadrant
            #   (We can't distinguish between these two without tool name, so we'll try both)
            
            if isinstance(event, dict):
                event_keys = list(event.keys())
                if len(event_keys) == 0:
                    # Empty event - must be accordo_audio_feedback (only tool with no parameters)
                    tool_name = "accordo_audio_feedback"
                    logger.info(f"Inferred tool name from empty event: {tool_name}")
                elif "student_id" in event_keys:
                    # Event has student_id - could be students_overture or students_skills_quadrant
                    # Since we can't distinguish, we'll default to students_skills_quadrant
                    # (This is a limitation - ideally Gateway should pass tool name)
                    tool_name = "students_skills_quadrant"
                    logger.warning(f"Inferred tool name from student_id: {tool_name} (may be incorrect if it's students_overture)")
                else:
                    # Unknown event structure
                    error_msg = "Missing tool name in Lambda context and cannot infer from event structure. Gateway may not be configured correctly."
                    logger.error(error_msg)
                    logger.error(f"Event: {json.dumps(event, default=str)[:500]}")
                    logger.error(f"Context attributes: {dir(context)}")
                    return _response(400, {
                        "error": error_msg,
                        "errorType": "ConfigurationError",
                        "message": error_msg,
                        "details": "The Bedrock AgentCore Gateway should pass the tool name in context.client_context.custom.bedrockAgentCoreToolName or event.bedrockagentcoreToolName"
                    })
            else:
                error_msg = "Missing tool name in Lambda context and event is not a dict. Gateway may not be configured correctly."
                logger.error(error_msg)
                logger.error(f"Event type: {type(event)}, Event: {str(event)[:500]}")
                return _response(400, {
                    "error": error_msg,
                    "errorType": "ConfigurationError",
                    "message": error_msg,
                    "details": "The Bedrock AgentCore Gateway should pass the tool name in context.client_context.custom.bedrockAgentCoreToolName or event.bedrockagentcoreToolName"
                })
        
        # Extract user ID from event (injected by agent runtime)
        # The agent runtime automatically injects userId into MCP tool arguments
        # Note: accordo_audio_feedback uses Cognito sub from auth context, not userId
        user_id = event.get("userId") if isinstance(event, dict) else None
        
        # Log event for debugging
        logger.info(f"Tool '{tool_name}' invoked. Event keys: {list(event.keys()) if isinstance(event, dict) else 'N/A'}")
        logger.info(f"Event content (first 1000 chars): {json.dumps(event, default=str)[:1000]}")
        
        # Route to appropriate tool handler
        # Note: accordo_audio_feedback doesn't require userId validation
        # Validate userId for tools that require it (except accordo_audio_feedback)
        if tool_name != "accordo_audio_feedback":
            if not user_id or user_id in ["<UNKNOWN>", "UNKNOWN", "unknown", ""]:
                error_msg = (
                    "userId is required but was not provided or is invalid. "
                    "The agent runtime should automatically inject userId into tool arguments. "
                    "This indicates a configuration issue with the agent runtime."
                )
                logger.error(error_msg)
                logger.error(f"Event keys: {list(event.keys()) if isinstance(event, dict) else 'N/A'}")
                logger.error(f"Event content: {json.dumps(event, default=str)[:500]}")
                return _response(400, {"error": error_msg})
        
        if tool_name == "students_overture":
            try:
                result = students_overture_tool(event)
                return _response(200, {"result": result})
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Error in students_overture tool: {type(e).__name__}: {str(e)}")
                error_result = {
                    "error": f"Error in students_overture tool: {type(e).__name__}: {str(e)}",
                    "errorType": type(e).__name__,
                    "details": str(e),
                    "message": f"The students-overture tool encountered an error: {str(e)}. Please check the error details above."
                }
                return _response(200, {"result": error_result})

        if tool_name == "students_skills_quadrant":
            try:
                result = students_skills_quadrant_tool(event)
                return _response(200, {"result": result})
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Error in students_skills_quadrant tool: {type(e).__name__}: {str(e)}")
                error_result = {
                    "error": f"Error in students_skills_quadrant tool: {type(e).__name__}: {str(e)}",
                    "errorType": type(e).__name__,
                    "details": str(e),
                    "message": f"The students-skills-quadrant tool encountered an error: {str(e)}. Please check the error details above."
                }
                return _response(200, {"result": error_result})

        if tool_name == "accordo_audio_feedback":
            try:
                # Log event structure for debugging
                logger.info(f"accordo_audio_feedback tool called. Event keys: {list(event.keys()) if isinstance(event, dict) else 'N/A'}")
                logger.info(f"Event content: {json.dumps(event, default=str)[:500]}")
                
                # Extract Cognito sub from auth context
                logger.info("Attempting to extract Cognito sub from authentication context")
                logger.info(f"Event type: {type(event)}, Event keys: {list(event.keys()) if isinstance(event, dict) else 'N/A'}")
                logger.info(f"Context type: {type(context)}")
                logger.info(f"Context has client_context: {hasattr(context, 'client_context')}")
                
                cognito_sub = _extract_cognito_sub(event, context)
                if not cognito_sub:
                    error_msg = (
                        "Unable to extract Cognito sub from authentication context. "
                        "This is required to access student feedback files. "
                        "Please ensure you are properly authenticated."
                    )
                    logger.error(error_msg)
                    logger.error(f"Event structure (full): {json.dumps(event, default=str, indent=2)}")
                    logger.error(f"Context has client_context: {hasattr(context, 'client_context')}")
                    if hasattr(context, 'client_context') and context.client_context:
                        logger.error(f"client_context type: {type(context.client_context)}")
                        logger.error(f"client_context.custom: {getattr(context.client_context, 'custom', 'N/A')}")
                    if hasattr(context, 'identity'):
                        logger.error(f"context.identity: {getattr(context, 'identity', 'N/A')}")
                    
                    # Return error in tool result format - ensure message is clear and visible
                    error_result = {
                        "error": error_msg,
                        "errorType": "AuthenticationError",
                        "message": error_msg,
                        "details": "The Cognito sub could not be extracted from the authentication context. This may indicate an issue with the authentication configuration. The Gateway may not be passing JWT claims to the Lambda function.",
                        "status": "error",
                        "content": [{"text": error_msg}]
                    }
                    logger.error(f"Returning authentication error: {json.dumps(error_result, default=str)}")
                    # Return both formats to ensure compatibility
                    return _response(200, {"result": error_result, "error": error_msg, "message": error_msg})
                
                logger.info(f"Successfully extracted Cognito sub: {cognito_sub[:10]}...")
                result = accordo_audio_feedback_tool(event, cognito_sub=cognito_sub)
                
                # Log result for debugging
                logger.info(f"Tool result type: {type(result)}, keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                logger.info(f"Tool result (first 1000 chars): {json.dumps(result, default=str)[:1000]}")
                
                # Check if result contains an error
                if isinstance(result, dict) and "error" in result:
                    error_msg = result.get("error", "")
                    error_type = result.get("errorType", "Error")
                    
                    # Ensure error message is never empty
                    if not error_msg or error_msg.strip() == "":
                        error_msg = f"An error occurred: {error_type}"
                        result["error"] = error_msg
                        result["message"] = error_msg
                    
                    # Ensure result has status and content for MCP client compatibility
                    if "status" not in result:
                        result["status"] = "error"
                    if "content" not in result:
                        result["content"] = [{"text": error_msg}]
                    
                    # Log the error with full details
                    logger.error(f"Tool returned error: {error_type} - {error_msg}")
                    logger.error(f"Full error result: {json.dumps(result, default=str)}")
                    
                    # Return error response - include error at top level for visibility
                    response_body = {
                        "result": result,
                        "error": error_msg,
                        "message": error_msg,
                        "errorType": error_type
                    }
                    return _response(200, response_body)
                
                # Success case - log it
                logger.info("Tool executed successfully")
                # Ensure success result has proper format
                if isinstance(result, dict):
                    if "status" not in result:
                        result["status"] = "success"
                    if "content" not in result and "data" in result:
                        # Convert data to content format for MCP client
                        result["content"] = [{"text": json.dumps(result.get("data", {}), default=str)}]
                return _response(200, {"result": result})
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Error in accordo_audio_feedback tool: {type(e).__name__}: {str(e)}")
                error_result = {
                    "error": f"Error in accordo_audio_feedback tool: {type(e).__name__}: {str(e)}",
                    "errorType": type(e).__name__,
                    "details": str(e),
                    "message": f"The accordo-audio-feedback tool encountered an error: {str(e)}. Please check the error details above."
                }
                return _response(200, {"result": error_result})

        return _response(400, {"error": f"Unknown tool '{tool_name}'"})

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error("=" * 80)
        logger.error(f"EXCEPTION IN LAMBDA HANDLER: {type(e).__name__}: {str(e)}")
        logger.error(f"TRACEBACK:\n{error_trace}")
        logger.error("=" * 80)
        
        error_msg = f"Lambda handler error: {type(e).__name__}: {str(e)}"
        return {
            "error": error_msg,
            "errorType": type(e).__name__,
            "message": error_msg,
            "status": "error",
            "content": [{"text": error_msg}],
            "details": error_trace
        }


def _extract_cognito_sub(event: Dict[str, Any], context: Any) -> Optional[str]:
    """
    Extract Cognito sub from authentication context.
    
    Tries multiple methods:
    1. From event directly (claims, sub, or jwt_claims)
    2. From event.requestContext.authorizer.claims.sub (API Gateway format)
    3. From context.client_context.custom (Bedrock AgentCore Gateway custom claims)
    4. From context.identity (Lambda request context identity)
    5. From event headers (if Gateway passes JWT in headers)
    
    Returns:
        Cognito sub string or None if not found
    """
    # Log all available data for debugging
    logger.info(f"=== COGNITO SUB EXTRACTION DEBUG ===")
    logger.info(f"Event keys: {list(event.keys()) if isinstance(event, dict) else 'N/A'}")
    logger.info(f"Event type: {type(event)}")
    logger.info(f"Full event: {json.dumps(event, default=str)}")
    if isinstance(event, dict):
        logger.info(f"Event sample (first 1000 chars): {json.dumps({k: str(v)[:200] for k, v in list(event.items())[:20]}, default=str)}")
    
    # Also log context for debugging
    logger.info(f"Context type: {type(context)}")
    logger.info(f"Context attributes: {[attr for attr in dir(context) if not attr.startswith('_')]}")
    if hasattr(context, 'identity'):
        logger.info(f"context.identity: {context.identity}")
    if hasattr(context, 'client_context'):
        logger.info(f"context.client_context: {context.client_context}")
        if context.client_context:
            logger.info(f"context.client_context.custom: {getattr(context.client_context, 'custom', 'N/A')}")
    
    # Method 1: Try event directly (Bedrock AgentCore Gateway might pass claims directly)
    try:
        if isinstance(event, dict):
            # Try direct sub in event
            if event.get("sub"):
                sub = event.get("sub")
                logger.info(f"Extracted Cognito sub from event.sub: {sub[:10]}...")
                return sub
            # Try claims.sub in event
            claims = event.get("claims", {})
            if isinstance(claims, dict) and claims.get("sub"):
                sub = claims.get("sub")
                logger.info(f"Extracted Cognito sub from event.claims.sub: {sub[:10]}...")
                return sub
            # Try jwt_claims.sub in event
            jwt_claims = event.get("jwt_claims", {})
            if isinstance(jwt_claims, dict) and jwt_claims.get("sub"):
                sub = jwt_claims.get("sub")
                logger.info(f"Extracted Cognito sub from event.jwt_claims.sub: {sub[:10]}...")
                return sub
            # Try authorizer.claims.sub in event
            authorizer = event.get("authorizer", {})
            if isinstance(authorizer, dict):
                authorizer_claims = authorizer.get("claims", {})
                if isinstance(authorizer_claims, dict) and authorizer_claims.get("sub"):
                    sub = authorizer_claims.get("sub")
                    logger.info(f"Extracted Cognito sub from event.authorizer.claims.sub: {sub[:10]}...")
                    return sub
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug(f"Method 1 failed: {e}")
    
    # Method 2: Try API Gateway format (requestContext.authorizer.claims.sub)
    try:
        request_context = event.get("requestContext", {})
        if request_context:
            authorizer = request_context.get("authorizer", {})
            if authorizer:
                claims = authorizer.get("claims", {})
                if claims and claims.get("sub"):
                    sub = claims.get("sub")
                    logger.info(f"Extracted Cognito sub from requestContext.authorizer.claims: {sub[:10]}...")
                    return sub
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug(f"Method 2 failed: {e}")
    
    # Method 3: Try Lambda context client_context.custom
    try:
        if hasattr(context, 'client_context') and context.client_context:
            if hasattr(context.client_context, 'custom') and context.client_context.custom:
                # Check for common JWT claim locations in custom context
                custom = context.client_context.custom
                logger.debug(f"client_context.custom type: {type(custom)}, value: {custom}")
                if isinstance(custom, dict):
                    # Try direct sub claim
                    if custom.get("sub"):
                        sub = custom.get("sub")
                        logger.info(f"Extracted Cognito sub from context.client_context.custom: {sub[:10]}...")
                        return sub
                    # Try claims.sub
                    claims = custom.get("claims", {})
                    if isinstance(claims, dict) and claims.get("sub"):
                        sub = claims.get("sub")
                        logger.info(f"Extracted Cognito sub from context.client_context.custom.claims: {sub[:10]}...")
                        return sub
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug(f"Method 3 failed: {e}")
    
    # Method 4: Try Lambda request context identity (for API Gateway/Lambda authorizer)
    try:
        if hasattr(context, 'identity'):
            identity = context.identity
            if identity and hasattr(identity, 'cognito_identity_id'):
                cognito_id = identity.cognito_identity_id
                if cognito_id:
                    logger.info(f"Found cognito_identity_id from context.identity: {cognito_id[:10]}...")
                    # Note: cognito_identity_id is different from sub, but might be usable
                    # For now, we'll log it but not use it as it's from Identity Pool, not User Pool
                    logger.debug(f"cognito_identity_id found but not using (Identity Pool vs User Pool): {cognito_id}")
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug(f"Method 4 failed: {e}")
    
    # Method 5: Try userId from event (workaround - Gateway not passing JWT claims)
    # The runtime injects userId into the event, which should be the Cognito sub
    try:
        if isinstance(event, dict):
            user_id = event.get("userId")
            if user_id and user_id not in ["<UNKNOWN>", "UNKNOWN", "unknown", ""]:
                logger.warning(f"Using userId from event as Cognito sub (workaround - Gateway not passing JWT claims): {user_id[:10]}...")
                logger.warning("NOTE: Gateway should be configured to pass JWT claims in authentication context. Using userId as fallback.")
                return user_id
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug(f"Method 5 failed: {e}")
    
    logger.warning("Could not extract Cognito sub from authentication context using any method")
    return None


def _response(status_code: int, body: Dict[str, Any]):
    """
    Response formatter for Bedrock AgentCore Gateway MCP tools.
    
    Gateway MCP Lambda tools expect the response in MCP protocol format:
    - Success: {"status": "success", "content": [{"text": "..."}]}
    - Error: {"status": "error", "content": [{"text": "..."}]}
    
    The Gateway handles HTTP status codes, so we just return the body.
    """
    # Check if body already has MCP format (status/content)
    if "status" in body and "content" in body:
        return body
    
    # Check if body has a "result" key (from tool handlers)
    if "result" in body:
        result = body["result"]
        
        # If result has error, format as error
        if isinstance(result, dict) and "error" in result:
            error_msg = result.get("error") or result.get("message") or "Unknown error occurred"
            return {
                "status": "error",
                "content": [{"text": error_msg}],
                "error": error_msg,
                "errorType": result.get("errorType", "Error")
            }
        
        # If result has data, format as success
        if isinstance(result, dict) and "data" in result:
            data = result["data"]
            return {
                "status": "success",
                "content": [{"text": json.dumps(data, default=str)}]
            }
        
        # If result has status_code (from tool handlers), check if it's an error
        if isinstance(result, dict) and "status_code" in result:
            status_code_from_tool = result.get("status_code", 200)
            if status_code_from_tool != 200 or "error" in result:
                error_msg = result.get("error") or result.get("message") or "Unknown error occurred"
                return {
                    "status": "error",
                    "content": [{"text": error_msg}],
                    "error": error_msg,
                    "errorType": result.get("errorType", "Error")
                }
            else:
                # Success with data
                data = result.get("data", {})
                return {
                    "status": "success",
                    "content": [{"text": json.dumps(data, default=str)}]
                }
        
        # Default: convert result to text
        return {
            "status": "success",
            "content": [{"text": json.dumps(result, default=str)}]
        }
    
    # Check if body has error directly
    if "error" in body:
        error_msg = body.get("error") or body.get("message") or "Unknown error occurred"
        return {
            "status": "error",
            "content": [{"text": error_msg}],
            "error": error_msg,
            "errorType": body.get("errorType", "Error")
        }
    
    # Default: format as success
    return {
        "status": "success",
        "content": [{"text": json.dumps(body, default=str)}]
    }


