import json
import logging
import os
from typing import Any, Dict, Optional

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
    # Store context for potential use in helper functions
    _lambda_context = context
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
    try:
        extended_name = context.client_context.custom.get("bedrockAgentCoreToolName") if hasattr(context, 'client_context') and context.client_context and hasattr(context.client_context, 'custom') else None
        tool_name = None

        # handle agentcore gateway tool naming convention
        # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html
        if extended_name and "___" in extended_name:
            tool_name = extended_name.split("___", 1)[1]
        
        if not tool_name:
            return _response(400, {"error": "Missing tool name"})
        
        # Extract user ID from event (injected by agent runtime)
        # The agent runtime automatically injects userId into MCP tool arguments
        user_id = event.get("userId") if isinstance(event, dict) else None
        
        # Validate userId is present and not a placeholder
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

        return _response(400, {"error": f"Unknown tool '{tool_name}'"})

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Exception in lambda_handler: {type(e).__name__}: {str(e)}")
        return _response(500, {
            "system_error": str(e),
            "errorType": type(e).__name__
        })


def _response(status_code: int, body: Dict[str, Any]):
    """Consistent JSON response wrapper."""
    return {"statusCode": status_code, "body": json.dumps(body)}


