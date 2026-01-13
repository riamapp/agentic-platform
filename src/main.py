import os
import json as json_module
import re
import inspect
from typing import Any, Dict, List
from datetime import datetime, timezone
import uuid
import logging
import sys

import boto3
from boto3.dynamodb.conditions import Key

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from .model.load import load_model
from .model.schemas import get_schema, get_pydantic_model, list_available_schemas
from .tools.code_interpreter import CodeInterpreterTool
from .tools.browser import BrowserTool
from .agent.agent_loop import AgentLoop
from .agent.tool_registry import ToolRegistry

# Set up module-level logger configured for AWS Lambda/CloudWatch
# Lambda automatically captures stdout/stderr and sends to CloudWatch Logs
logger = logging.getLogger(__name__)

# Configure logger if it doesn't have handlers (to avoid duplicate logs)
# This ensures logs appear in CloudWatch with proper formatting
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt='[%(levelname)s] %(name)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    )
    logger.addHandler(handler)
    # Set log level - can be overridden by Lambda environment variable LOG_LEVEL
    log_level = logging.INFO
    try:
        env_level = os.getenv('LOG_LEVEL', '').upper()
        if env_level:
            log_level = getattr(logging, env_level, logging.INFO)
    except Exception:
        pass  # Use default INFO level if environment variable parsing fails
    logger.setLevel(log_level)

MEMORY_ID = os.getenv("MEMORY_ID")
REGION = os.getenv("AWS_REGION")
CONVERSATION_TABLE = os.getenv("CONVERSATION_TABLE")

# In-memory transcripts keyed by session_id.
_TRANSCRIPTS: Dict[str, List[Dict[str, str]]] = {}

# Low-level AgentCore Memory client for persisting conversation turns (optional).
_MEMORY_CLIENT: MemoryClient | None = None
if MEMORY_ID and REGION:
    _MEMORY_CLIENT = MemoryClient(region_name=REGION)
    
    logger.info(f"Memory client initialized for MEMORY_ID: {MEMORY_ID} in region: {REGION}")

# DynamoDB table client for durable short-term transcripts.
_DDB_TABLE = None
if CONVERSATION_TABLE and REGION:
    _DDB_TABLE = boto3.resource("dynamodb", region_name=REGION).Table(CONVERSATION_TABLE)

# Integrate with Bedrock AgentCore
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload, context):
    session_id = getattr(context, "session_id", "default")

    logger.debug(f"payload: {payload}")
    logger.debug(f"context: {context}")
    logger.debug(f"session_id: {session_id}")

    # Memory retrieval will be handled directly via MemoryClient if needed
    # No session manager needed for native implementation

    # Build a simple turns wrapper: prepend recent conversation history
    # so the model can interpret follow-ups like "another please".
    user_prompt = payload.get("prompt", "")
    user_id = payload.get("userId")  # Extract userId from payload if available
    frontend_identifier = payload.get("frontendIdentifier")  # Extract frontendIdentifier from payload if available
    output_mode = payload.get("outputMode", "chat")  # Default to chat mode
    output_schema_name = payload.get("outputSchemaName")  # Schema name from registry
    
    # Log output mode for debugging
    if output_mode == "structured":
        if not output_schema_name:
            available = ", ".join(list_available_schemas())
            error_msg = (
                f"Structured output mode requires an outputSchemaName. "
                f"Please provide outputSchemaName in the payload. "
                f"Available schemas: {available}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        logger.info(f"Structured output mode enabled. Schema name: {output_schema_name}")
    
    # Log userId for debugging
    if user_id:
        logger.info(f"Received userId in payload: ...{user_id[-4:]}")
    
    # Log frontendIdentifier for debugging
    if frontend_identifier:
        logger.info(f"Received frontendIdentifier in payload: {frontend_identifier}")
    else:
        logger.warning("No frontendIdentifier found in payload - OAuth redirects may fail")

    # Start with in-memory transcript and, if available, merge in recent
    # turns from DynamoDB so we have context even after container restarts.
    transcript = _TRANSCRIPTS.setdefault(session_id, [])

    if _DDB_TABLE:
        try:
            resp = _DDB_TABLE.query(
                KeyConditionExpression=Key("sessionId").eq(session_id),
                ScanIndexForward=False,
                Limit=12,
            )
            items = resp.get("Items", [])
            # Sort oldest->newest
            items = sorted(items, key=lambda x: x.get("timestamp", ""))
            transcript = [
                {"role": item.get("role", "user"), "content": item.get("content", "")}
                for item in items
            ]
            _TRANSCRIPTS[session_id] = transcript
        except Exception as e:
            logger.warning(f"Failed to load conversation history from DynamoDB: {e}")

    # Use the last few turns to keep prompts compact.
    history_turns = transcript[-6:]  # up to 3 previous exchanges
    history_lines = []
    for turn in history_turns:
        role = "User" if turn["role"] == "user" else "Assistant"
        history_lines.append(f"{role}: {turn['content']}")

    # User context variable (currently unused, reserved for future use)
    user_context = ""
    
    if history_lines:
        composed_prompt = (
            "Here is the recent conversation between the user and assistant:\n"
            + "\n".join(history_lines)
            + "\n\nGiven this context, respond to the user's next message.\n"
            f"User: {user_prompt}{user_context}"
        )
    else:
        composed_prompt = f"{user_prompt}{user_context}"
    
    # Check prompt size before passing to AgentLoop
    try:
        from .utils.token_counter import count_tokens, get_max_prompt_tokens, get_token_warning_threshold
        prompt_token_count = count_tokens(composed_prompt)
        max_prompt_tokens = get_max_prompt_tokens()
        warning_threshold = get_token_warning_threshold()
        
        if prompt_token_count > max_prompt_tokens * warning_threshold:
            logger.warning(
                f"Composed prompt token count ({prompt_token_count}) exceeds warning threshold "
                f"({max_prompt_tokens * warning_threshold:.0f}). History may be truncated further."
            )
        
        # If prompt alone exceeds limit, truncate history more aggressively
        if prompt_token_count > max_prompt_tokens:
            logger.warning(
                f"Composed prompt token count ({prompt_token_count}) exceeds limit ({max_prompt_tokens}), "
                f"truncating history more aggressively"
            )
            # Remove oldest turns until under limit
            while history_turns and count_tokens(
                "Here is the recent conversation between the user and assistant:\n"
                + "\n".join([
                    f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
                    for turn in history_turns
                ])
                + "\n\nGiven this context, respond to the user's next message.\n"
                + f"User: {user_prompt}{user_context}"
            ) > max_prompt_tokens:
                history_turns.pop(0)
                logger.debug(f"Removed oldest history turn, remaining: {len(history_turns)}")
            
            # Rebuild composed_prompt with truncated history
            if history_turns:
                history_lines = [
                    f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
                    for turn in history_turns
                ]
                composed_prompt = (
                    "Here is the recent conversation between the user and assistant:\n"
                    + "\n".join(history_lines)
                    + "\n\nGiven this context, respond to the user's next message.\n"
                    + f"User: {user_prompt}{user_context}"
                )
            else:
                composed_prompt = f"{user_prompt}{user_context}"
    except ImportError:
        # Token counter not available, skip check
        logger.debug("Token counter not available, skipping prompt size check")

    # Prepare code interpreter and browser tool for this turn.
    code_interpreter_tool = None
    browser_tool = None
    
    if REGION:
        try:
            code_interpreter_tool = CodeInterpreterTool(
                region=REGION,
                session_name=session_id,
                auto_create=True,
                persist_sessions=True,
            )
            logger.info(f"Code interpreter tool initialized for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to initialize code interpreter tool: {e}", exc_info=True)
        
        try:
            browser_tool = BrowserTool(region=REGION)
            browser_tool._start()  # Initialize Playwright
            logger.info(f"Browser tool initialized for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to initialize browser tool: {e}", exc_info=True)
            browser_tool = None

    assistant_chunks: List[str] = []

    try:
        # Create tool registry
        tool_registry = ToolRegistry()
        
        # Register code interpreter tool
        if code_interpreter_tool:
            tool_registry.register_tool(
                "code_interpreter",
                code_interpreter_tool.code_interpreter,
                tool_registry.create_code_interpreter_schema()
            )
            logger.info("Registered code_interpreter tool")
        
        # Register browser tool (browser tool has fixes built-in)
        if browser_tool:
            tool_registry.register_tool(
                "browser",
                browser_tool.browser,
                tool_registry.create_browser_schema()
            )
            logger.info("Registered browser tool")
        
        logger.info(f"Total tools registered: {len(tool_registry._tools)}")
        
        # Get current date/time for context
        current_datetime = datetime.now(timezone.utc)
        current_date_str = current_datetime.strftime("%Y-%m-%d")
        current_time_str = current_datetime.strftime("%H:%M:%S UTC")
        current_datetime_iso = current_datetime.isoformat().replace('+00:00', 'Z')
        
        # Build system prompt based on output mode
        if output_mode == "structured":
            # Get the schema definition to include in the prompt
            schema_json = None
            if output_schema_name:
                try:
                    schema_dict = get_schema(output_schema_name)
                    schema_json = json_module.dumps(schema_dict, indent=2)
                    logger.info(f"Including schema definition for {output_schema_name} in system prompt")
                except Exception as e:
                    logger.warning(f"Failed to get schema for prompt: {e}")
            
            schema_instructions = ""
            if schema_json:
                schema_instructions = f"""
                    
                    You MUST respond with a valid JSON object that matches this exact schema:
                    {schema_json}
                    
                    IMPORTANT: 
                    - Your entire response must be a valid JSON object matching the schema above
                    - Include ALL required fields
                    - Do NOT include any text before or after the JSON object
                    - Do NOT wrap the JSON in markdown code blocks
                    - Return only the JSON object itself
                """
            
            system_prompt_base = f"""
                    You are a workflow execution agent that returns structured responses.
                    
                    Current date and time: {current_date_str} {current_time_str} (ISO 8601: {current_datetime_iso})
                    When the user says "today", "now", or refers to the current date/time, use the current date/time shown above.
                    
                    You have access to standard function tools (like code_interpreter, browser) - these are Python functions defined with @tool decorator.
                    
                    IMPORTANT - Code Interpreter Usage:
                    The code_interpreter tool runs in an isolated sandbox that CANNOT make HTTP requests or access external APIs.
                    When you need to analyze data from external sources:
                    1. FIRST: Use the appropriate tool to fetch the data
                    2. THEN: Pass the fetched data to the code_interpreter as input (e.g., write it to a file, or include it in your code as a variable)
                    3. Finally: Use code_interpreter to analyze the data that was provided to it
                    
                    Do NOT attempt to make HTTP requests or call APIs from within code_interpreter code.
                    Do NOT try to use requests.get(), urllib, or similar libraries in code_interpreter - they will fail or timeout.
                    
                    Use tools as needed to gather information, then format the results according to the required schema.{schema_instructions}
                """
        else:
            # Chat mode: natural language responses
            system_prompt_base = f"""
                        You are a helpful assistant with code execution and web browsing capabilities. Use tools when appropriate.
                        
                        Current date and time: {current_date_str} {current_time_str} (ISO 8601: {current_datetime_iso})
                        When the user says "today", "now", or refers to the current date/time, use the current date/time shown above.
                        
                        You have access to standard function tools (like code_interpreter, browser) - these are Python functions defined with @tool decorator.
                        
                        IMPORTANT - Code Interpreter Usage:
                        The code_interpreter tool runs in an isolated sandbox that CANNOT make HTTP requests or access external APIs.
                        When you need to analyze data from external sources:
                        1. FIRST: Use the appropriate tool to fetch the data
                        2. THEN: Pass the fetched data to the code_interpreter as input (e.g., write it to a file, or include it in your code as a variable)
                        3. Finally: Use code_interpreter to analyze the data that was provided to it
                        
                        Do NOT attempt to make HTTP requests or call APIs from within code_interpreter code.
                        Do NOT try to use requests.get(), urllib, or similar libraries in code_interpreter - they will fail or timeout.
                        
                        When asked about your tools or architecture, you should accurately describe the available tools.
                    """
        
        # Load model based on output mode
        pydantic_model = None
        model_id = load_model()  # Always load model (same for both modes)
        
        if output_mode == "structured":
            logger.info("Loading structured output configuration")
            try:
                # Use pre-generated Pydantic model from registry
                pydantic_model = get_pydantic_model(output_schema_name)
                logger.info(f"Retrieved pre-generated Pydantic model for schema: {output_schema_name}")
            except ValueError as e:
                # Re-raise ValueError as-is (already has good error message)
                raise
            except Exception as e:
                logger.error(f"Failed to get Pydantic model for structured output: {e}", exc_info=True)
                raise ValueError(
                    f"Failed to get Pydantic model for structured output: {e}. "
                    "Please ensure the outputSchemaName is valid."
                ) from e

        logger.debug(f"model_id: {model_id}")
        logger.debug(f"system_prompt_base: {system_prompt_base}")
        logger.debug(f"tool_registry tools: {list(tool_registry._tools.keys())}")
        
        # Create agent loop
        agent_loop = AgentLoop(
            model_id=model_id,
            region=REGION,
            tool_registry=tool_registry,
            system_prompt=system_prompt_base,
            memory_client=_MEMORY_CLIENT,
        )
        
        logger.info("AgentLoop initialized successfully")

        # Execute and stream response using the agent loop
        # Convert conversation history to format expected by agent loop
        conversation_history = [
            {"role": turn["role"], "content": turn["content"]}
            for turn in history_turns
        ]
        
        if output_mode == "structured" and pydantic_model:
            # Structured output mode - accumulate all chunks, then yield final JSON
            logger.info("Using structured output mode")
            try:
                complete_response = ""
                # Accumulate all chunks without yielding them (structured output should be atomic)
                async for chunk in agent_loop.stream(
                    user_message=composed_prompt,
                    conversation_history=conversation_history,
                    structured_output_model=pydantic_model
                ):
                    complete_response += chunk
                    # Don't append to assistant_chunks here - we'll add the final JSON instead
                
                # For structured output, try to extract JSON
                json_response = complete_response.strip()
                
                # Remove markdown code blocks if present
                json_patterns = [
                    r'```json\s*(\{.*?\})\s*```',
                    r'```\s*(\{.*?\})\s*```',
                ]
                
                for pattern in json_patterns:
                    matches = re.findall(pattern, complete_response, re.DOTALL)
                    if matches:
                        json_response = matches[-1]
                        logger.info("Extracted JSON from markdown code block")
                        break
                
                # Try to find standalone JSON object
                if json_response == complete_response:
                    json_match = re.search(r'(\{.*\})', complete_response, re.DOTALL)
                    if json_match:
                        json_response = json_match.group(1)
                        logger.info("Extracted JSON object from response")
                
                # Validate and transform JSON to match schema
                try:
                    parsed_json = json_module.loads(json_response)
                    logger.info("Parsed JSON from structured output")
                except json_module.JSONDecodeError:
                    # If JSON parsing fails, treat the response as plain text and wrap it
                    logger.warning(f"Failed to parse JSON from structured output, treating as plain text")
                    parsed_json = None
                
                # Transform to match schema (especially for chat_response)
                if output_schema_name == "chat_response":
                    # Get schema to check required fields
                    schema_dict = get_schema(output_schema_name)
                    required_fields = schema_dict.get("required", [])
                    
                    # Build the structured response
                    structured_response = {}
                    
                    # If we have parsed JSON, use it as a starting point
                    if parsed_json:
                        structured_response = parsed_json
                    
                    # Ensure required fields are present
                    if "response" not in structured_response or not structured_response["response"]:
                        # Use complete_response as the response text if not in parsed JSON
                        if parsed_json and isinstance(parsed_json.get("response"), str):
                            structured_response["response"] = parsed_json["response"]
                        else:
                            # Use the complete response (plain text) as the response field
                            structured_response["response"] = complete_response.strip()
                    
                    # Always ensure timestamp is set (use current time)
                    if "timestamp" not in structured_response:
                        structured_response["timestamp"] = current_datetime_iso
                    
                    # Always ensure sessionId is set
                    if "sessionId" not in structured_response:
                        structured_response["sessionId"] = session_id
                    
                    # Validate using Pydantic model
                    try:
                        validated_response = pydantic_model(**structured_response)
                        # Convert back to dict and then JSON string
                        final_json = validated_response.model_dump_json()
                        logger.info("Validated and transformed structured output to match schema")
                        # Add the final JSON to assistant_chunks for transcript persistence
                        assistant_chunks.append(final_json)
                        # Yield the validated JSON as a single chunk
                        yield final_json
                    except Exception as validation_error:
                        logger.error(f"Failed to validate structured output against schema: {validation_error}")
                        # Fallback: create a minimal valid response
                        fallback_response = {
                            "response": structured_response.get("response", complete_response.strip()),
                            "timestamp": current_datetime_iso,
                            "sessionId": session_id
                        }
                        fallback_json = json_module.dumps(fallback_response)
                        assistant_chunks.append(fallback_json)
                        yield fallback_json
                else:
                    # For other schemas, just validate the parsed JSON
                    if parsed_json:
                        try:
                            validated_response = pydantic_model(**parsed_json)
                            final_json = validated_response.model_dump_json()
                            logger.info("Validated JSON structure from structured output")
                            assistant_chunks.append(final_json)
                            yield final_json
                        except Exception as validation_error:
                            logger.error(f"Failed to validate structured output against schema: {validation_error}")
                            # Fallback: use parsed JSON as-is
                            fallback_json = json_module.dumps(parsed_json)
                            assistant_chunks.append(fallback_json)
                            yield fallback_json
                    else:
                        # No valid JSON found
                        logger.error("No valid JSON found in structured output response")
                        raise ValueError("Structured output mode requires valid JSON response")
                
                # Add metadata after JSON response
                token_counts = agent_loop.get_token_counts()
                metadata = json_module.dumps({"__metadata__": token_counts})
                yield metadata
            except Exception as e:
                logger.error(f"Error in structured output mode: {e}", exc_info=True)
                raise RuntimeError(f"Failed to get structured output: {e}") from e
        else:
            # Regular streaming mode
            logger.info("Streaming response from AgentCore")
            async for chunk in agent_loop.stream(
                user_message=composed_prompt,
                conversation_history=conversation_history
            ):
                assistant_chunks.append(chunk)
                yield chunk
            
            # Add metadata after streaming completes
            token_counts = agent_loop.get_token_counts()
            metadata = json_module.dumps({"__metadata__": token_counts})
            yield metadata
    
    except Exception as e:
        logger.error(f"Error while streaming response from AgentCore: {e}")

    # After streaming completes, update transcript with this turn.
    assistant_text = "".join(assistant_chunks).strip()
    if user_prompt:
        transcript.append({"role": "user", "content": user_prompt})
    if assistant_text:
        transcript.append({"role": "assistant", "content": assistant_text})

    # Persist this turn to DynamoDB so context survives process restarts.
    if _DDB_TABLE and user_prompt:
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        try:
            _DDB_TABLE.put_item(
                Item={
                    "sessionId": session_id,
                    "timestamp": now + "#user",
                    "role": "user",
                    "content": user_prompt,
                }
            )
            if assistant_text:
                _DDB_TABLE.put_item(
                    Item={
                        "sessionId": session_id,
                        "timestamp": now + "#assistant",
                        "role": "assistant",
                        "content": assistant_text,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to persist conversation turn to DynamoDB: {e}")

    # Optionally also persist to AgentCore Memory for longer-term strategies.
    if _MEMORY_CLIENT and MEMORY_ID and user_prompt:
        try:
            mem_payload = {
                "namespace": f"/sessions/quickstart-user/{session_id}",
                "user": user_prompt,
                "assistant": assistant_text,
                "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            }
            logger.info(f"Persisting conversation turn to AgentCore Memory USER: {mem_payload["user"]}")
            logger.info(f"Persisting conversation turn to AgentCore Memory ASSISTANT: {mem_payload["assistant"]}")
            _MEMORY_CLIENT.create_event(
                memory_id=MEMORY_ID,
                actor_id=user_id,
                session_id=session_id,
                event_timestamp=datetime.now(timezone.utc),
                messages=[
                    (mem_payload["user"], "USER"),
                    (mem_payload["assistant"], "ASSISTANT"),
                ],
            )
        except Exception as e:
            # Log and continue; memory persistence should not break the turn.
            logger.warning(f"Failed to persist conversation turn to AgentCore Memory: {e}")

def format_response(result) -> str:
    """Extract code from metrics and format with LLM response."""
    parts = []

    # Extract executed code from metrics
    try:
        tool_metrics = result.metrics.tool_metrics.get('code_interpreter')
        if tool_metrics and hasattr(tool_metrics, 'tool'):
            action = tool_metrics.tool['input']['code_interpreter_input']['action']
            if 'code' in action:
                parts.append(f"## Executed Code:\n```{action.get('language', 'python')}\n{action['code']}\n```\n---\n")
    except (AttributeError, KeyError):
        pass  # No code to extract

    # Add LLM response
    parts.append(f"## 📊 Result:\n{str(result)}")
    return "\n".join(parts)

if __name__ == "__main__":
    app.run()
