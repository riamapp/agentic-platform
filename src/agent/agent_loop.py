"""
Native agent loop using Bedrock converse_stream API.

This replaces the Strands Agent framework with direct Bedrock API calls.
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Type

import boto3
from pydantic import BaseModel

from .tool_registry import ToolRegistry
from ..utils.token_counter import (
    count_tokens_in_messages,
    estimate_output_tokens,
    get_max_prompt_tokens,
    get_token_warning_threshold,
)

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    Native agent loop using Bedrock converse_stream API.
    
    Handles conversation, tool calling, and streaming responses.
    """
    
    def __init__(
        self,
        model_id: str,
        region: str,
        tool_registry: ToolRegistry,
        system_prompt: str,
        memory_client=None,
    ):
        """
        Initialize the agent loop.
        
        Args:
            model_id: Bedrock model ID (e.g., "eu.amazon.nova-micro-v1:0")
            region: AWS region
            tool_registry: Tool registry with registered tools
            system_prompt: System prompt for the agent
            memory_client: Optional memory client for retrieval
        """
        self.model_id = model_id
        self.region = region
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.memory_client = memory_client
        
        # Initialize Bedrock runtime client
        self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=region)
        
        # Token tracking for metadata
        self.input_tokens = 0
        self.output_tokens = 0
        
        logger.info(f"Initialized AgentLoop with model: {model_id}")
    
    async def stream(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]] = None,
        structured_output_model: Optional[Type[BaseModel]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream agent response using Bedrock converse_stream API.
        
        Args:
            user_message: User's message
            conversation_history: Previous conversation turns
            structured_output_model: Optional Pydantic model for structured output
            
        Yields:
            Text chunks from the agent response
        """
        logger.info(f"AgentLoop.stream() called with user_message length: {len(user_message) if user_message else 0}")
        conversation_history = conversation_history or []
        
        # Build messages for Bedrock API
        messages = []
        
        # Add system message
        if self.system_prompt:
            messages.append({
                "role": "user",
                "content": [{"text": self.system_prompt}]
            })
            messages.append({
                "role": "assistant",
                "content": [{"text": "I understand. I'll follow your instructions."}]
            })
        
        # Add conversation history
        for turn in conversation_history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            messages.append({
                "role": role,
                "content": [{"text": content}]
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": [{"text": user_message}]
        })
        
        # Get tool schemas
        tool_config = None
        tool_schemas = self.tool_registry.get_tool_schemas()
        if tool_schemas:
            # For Bedrock, toolChoice can be:
            # - {"auto": {}} - Claude decides
            # - {"any": {}} - Must use one tool
            # - {"tool": {"name": "tool_name"}} - Must use specific tool
            # - {"none": {}} - No tools
            tool_config = {
                "tools": tool_schemas,
                "toolChoice": {
                    "any": {}  # Force Claude to use at least one tool when tools are available
                }
            }
            logger.info(f"Tool config prepared with {len(tool_schemas)} tools: {[ts.get('toolSpec', {}).get('name', 'unknown') for ts in tool_schemas]}")
            logger.debug(f"Tool config with toolChoice: {json.dumps(tool_config, indent=2)[:500]}")
        
        # Count tokens before sending to model
        max_prompt_tokens = get_max_prompt_tokens()
        warning_threshold = get_token_warning_threshold()
        
        input_token_count = count_tokens_in_messages(messages, tool_schemas)
        self.input_tokens = input_token_count
        
        # Log token breakdown
        system_tokens = count_tokens_in_messages([messages[0], messages[1]] if len(messages) >= 2 and self.system_prompt else [])
        history_tokens = count_tokens_in_messages(
            messages[2:-1] if (len(messages) > 2 and self.system_prompt) else (messages[:-1] if len(messages) > 1 else [])
        )
        current_message_tokens = count_tokens_in_messages([messages[-1]] if messages else [])
        tool_schema_tokens = count_tokens_in_messages([], tool_schemas) if tool_schemas else 0
        
        logger.info(
            f"Token count breakdown - System: {system_tokens}, History: {history_tokens}, "
            f"Current: {current_message_tokens}, Tool schemas: {tool_schema_tokens}, "
            f"Total: {input_token_count} / {max_prompt_tokens}"
        )
        
        # Check if approaching limit
        if input_token_count > max_prompt_tokens * warning_threshold:
            logger.warning(
                f"Prompt token count ({input_token_count}) exceeds warning threshold "
                f"({max_prompt_tokens * warning_threshold:.0f})"
            )
        
        # Check if exceeds limit and truncate if needed
        if input_token_count > max_prompt_tokens:
            logger.error(
                f"Prompt token count ({input_token_count}) exceeds limit ({max_prompt_tokens}), "
                f"truncating conversation history"
            )
            
            # Truncation strategy: remove oldest conversation history turns
            # Keep system messages and current user message
            system_messages = messages[:2] if len(messages) >= 2 and self.system_prompt else []
            current_user_message = messages[-1:] if messages else []
            history_messages = (
                messages[2:-1] if (len(messages) > 2 and self.system_prompt) else (messages[:-1] if len(messages) > 1 else [])
            )
            
            # Remove oldest history messages until under limit
            truncated_history = history_messages.copy()
            while truncated_history and count_tokens_in_messages(
                system_messages + truncated_history + current_user_message, tool_schemas
            ) > max_prompt_tokens:
                truncated_history.pop(0)
                logger.debug(f"Removed oldest history message, remaining: {len(truncated_history)}")
            
            # Rebuild messages with truncated history
            messages = system_messages + truncated_history + current_user_message
            input_token_count = count_tokens_in_messages(messages, tool_schemas)
            self.input_tokens = input_token_count
            
            removed_count = len(history_messages) - len(truncated_history)
            logger.warning(
                f"Truncated conversation history: removed {removed_count} oldest turns. "
                f"New token count: {input_token_count} / {max_prompt_tokens}"
            )
            
            # If still over limit after truncation, fail
            if input_token_count > max_prompt_tokens:
                error_msg = (
                    f"Prompt token count ({input_token_count}) still exceeds limit "
                    f"({max_prompt_tokens}) after truncation. System prompt or current message may be too large."
                )
                logger.error(error_msg)
                yield f"Error: {error_msg}"
                return
        
        # Prepare request
        request_params = {
            "modelId": self.model_id,
            "messages": messages,
        }
        
        if tool_config:
            request_params["toolConfig"] = tool_config
            logger.info(f"Request params include toolConfig with {len(tool_schemas)} tools")
            # Log the first tool schema for debugging
            if tool_schemas:
                logger.debug(f"First tool schema example: {json.dumps(tool_schemas[0], indent=2)}")
        
        # Handle structured output
        if structured_output_model:
            # For structured output, we'll use tool calling with the model as a tool
            # This is a workaround since Bedrock's structured output might not be directly available
            logger.info("Structured output requested, using tool calling approach")
        
        logger.info(f"Starting converse_stream with {len(messages)} messages, {len(tool_schemas) if tool_schemas else 0} tools, {input_token_count} input tokens")
        if tool_schemas:
            logger.debug(f"Tool schemas: {json.dumps(tool_schemas[:1], indent=2)}")  # Log first tool schema as example
        
        try:
            logger.debug(f"About to call converse_stream - request_params keys: {list(request_params.keys())}")
            # Call converse_stream - this returns a response with a stream
            # boto3's converse_stream returns a response object that is iterable
            logger.debug(f"Calling converse_stream with modelId={self.model_id}")
            response = self.bedrock_runtime.converse_stream(**request_params)
            logger.debug(f"converse_stream returned response type: {type(response)}")
            
            # Access the stream from the response
            # boto3's converse_stream returns an EventStream object that is iterable
            # The response itself is the stream, or it has a 'stream' property
            if hasattr(response, 'get'):
                # If it's a dict-like response (unlikely but handle it)
                stream = response.get('stream', [])
                logger.info("Accessing stream from dict-like response")
            elif hasattr(response, 'stream'):
                # If it has a stream attribute
                stream = response.stream
                logger.info("Accessing stream from response.stream attribute")
            elif hasattr(response, '__iter__'):
                # It's iterable directly (most likely case for boto3)
                stream = response
                logger.info("Using response directly as stream (iterable)")
            else:
                logger.error(f"Response is not iterable and has no stream attribute: {type(response)}")
                yield f"Error: Unexpected response format from Bedrock API"
                return
            
            # Process streaming response
            tool_results = []
            complete_text = ""
            current_tool_uses = {}  # Map toolUseId -> tool info
            tool_input_accumulators = {}  # Map toolUseId -> accumulated input
            content_block_to_tool_id = {}  # Map contentBlockIndex -> toolUseId
            
            # Iterate through the stream events
            # Each event is a dict with keys like 'contentBlockStart', 'contentBlockDelta', etc.
            event_count = 0
            logger.debug("Starting to iterate stream...")
            try:
                for event in stream:
                    logger.debug(f"Got event from stream, type: {type(event)}")
                    event_count += 1
                    if isinstance(event, dict):
                        event_keys = list(event.keys())
                        logger.info(f"Received event #{event_count}: {event_keys}")
                        # Log first few events in detail for debugging
                        if event_count <= 5:
                            logger.debug(f"Event #{event_count} content: {json.dumps(event, indent=2, default=str)[:500]}")
                    else:
                        logger.warning(f"Received non-dict event #{event_count}: {type(event)} - {str(event)[:100]}")
                        continue
                    
                    # Handle different event types
                    if 'contentBlockStart' in event:
                        block_start = event['contentBlockStart']
                        logger.debug(f"contentBlockStart full structure: {json.dumps(block_start, indent=2, default=str)[:1000]}")
                        
                        # Bedrock's contentBlockStart has toolUse nested under 'start' key
                        start_info = block_start.get('start', {})
                        content_block = block_start.get('contentBlock', {})
                        
                        # Check if toolUse is in the 'start' object (Bedrock format)
                        if 'toolUse' in start_info:
                            logger.debug("Found toolUse in start_info!")
                            tool_use = start_info['toolUse']
                            tool_id = tool_use.get('toolUseId')
                            tool_name = tool_use.get('name')
                            content_block_index = block_start.get('contentBlockIndex')
                            
                            # Track this tool use - we'll need to match it with a result
                            current_tool_uses[tool_id] = {
                                'name': tool_name,
                                'input': {},
                                'blockIndex': content_block_index
                            }
                            tool_input_accumulators[tool_id] = ""
                            
                            # Map contentBlockIndex to toolUseId for matching delta events
                            if content_block_index is not None:
                                content_block_to_tool_id[content_block_index] = tool_id
                            
                            logger.info(f"Tool use started: {tool_name} (id: {tool_id}, blockIndex: {content_block_index})")
                            logger.debug(f"Total tool uses in current turn: {len(current_tool_uses)}")
                        elif 'toolUse' in block_start:
                            # Fallback: check directly in block_start
                            logger.debug("Found toolUse directly in block_start!")
                            tool_use = block_start['toolUse']
                            tool_id = tool_use.get('toolUseId')
                            tool_name = tool_use.get('name')
                            current_tool_uses[tool_id] = {
                                'name': tool_name,
                                'input': {}
                            }
                            tool_input_accumulators[tool_id] = {}
                            logger.info(f"Tool use started: {tool_name} (id: {tool_id})")
                        elif 'toolUse' in content_block:
                            tool_use = content_block['toolUse']
                            tool_id = tool_use.get('toolUseId')
                            current_tool_uses[tool_id] = {
                                'name': tool_use.get('name'),
                                'input': {}
                            }
                            tool_input_accumulators[tool_id] = {}
                            logger.info(f"Tool use started: {current_tool_uses[tool_id]['name']} (id: {tool_id})")
                    
                    elif 'contentBlockDelta' in event:
                        delta = event['contentBlockDelta']
                        delta_content = delta.get('delta', {})
                        
                        # Text content
                        if 'text' in delta_content:
                            text_chunk = delta_content['text']
                            complete_text += text_chunk
                            # Track output tokens (estimate incrementally)
                            self.output_tokens = estimate_output_tokens(complete_text)
                            yield text_chunk
                        
                        # Tool use input (accumulated)
                        elif 'toolUse' in delta_content:
                            tool_use_delta = delta_content['toolUse']
                            # Get tool_id from contentBlockIndex mapping (delta events don't have toolUseId)
                            content_block_index = delta.get('contentBlockIndex')
                            tool_id = content_block_to_tool_id.get(content_block_index) if content_block_index is not None else None
                            
                            logger.debug(f"Tool use delta for blockIndex {content_block_index}, tool_id {tool_id}: {json.dumps(tool_use_delta, indent=2, default=str)[:500]}")
                            if tool_id and 'input' in tool_use_delta:
                                # Accumulate tool input
                                input_delta = tool_use_delta['input']
                                logger.debug(f"Input delta type: {type(input_delta)}, value: {str(input_delta)[:200]}")
                                
                                # Initialize accumulator if needed
                                if tool_id not in tool_input_accumulators:
                                    tool_input_accumulators[tool_id] = ""
                                
                                # Tool input comes as a string (JSON string being built incrementally)
                                if isinstance(input_delta, str):
                                    # Accumulate string input (JSON being built character by character)
                                    if isinstance(tool_input_accumulators[tool_id], str):
                                        tool_input_accumulators[tool_id] += input_delta
                                    else:
                                        tool_input_accumulators[tool_id] = input_delta
                                elif isinstance(input_delta, dict):
                                    # If it's already a dict, merge it
                                    if isinstance(tool_input_accumulators[tool_id], dict):
                                        tool_input_accumulators[tool_id].update(input_delta)
                                    else:
                                        tool_input_accumulators[tool_id] = input_delta
                                logger.debug(f"Accumulated input for {tool_id}: {str(tool_input_accumulators[tool_id])[:200]}")
                    
                    elif 'contentBlockStop' in event:
                        block_stop = event['contentBlockStop']
                        logger.debug(f"contentBlockStop full structure: {json.dumps(block_stop, indent=2, default=str)[:1000]}")
                        
                        # Get tool_id from contentBlockIndex
                        content_block_index = block_stop.get('contentBlockIndex')
                        tool_id = content_block_to_tool_id.get(content_block_index) if content_block_index is not None else None
                        
                        # Check different possible locations for toolUse
                        stop_info = block_stop.get('stop', {})
                        content_block = block_stop.get('contentBlock', {})
                        
                        tool_use = None
                        if 'toolUse' in stop_info:
                            tool_use = stop_info['toolUse']
                            logger.debug("Found toolUse in stop_info")
                        elif 'toolUse' in content_block:
                            tool_use = content_block['toolUse']
                            logger.debug("Found toolUse in content_block")
                        elif 'toolUse' in block_stop:
                            tool_use = block_stop['toolUse']
                            logger.debug("Found toolUse directly in block_stop")
                        
                        # If we have tool_id from mapping, use it; otherwise try to get from tool_use
                        if tool_id:
                            tool_name = current_tool_uses.get(tool_id, {}).get('name')
                            if not tool_name and tool_use:
                                tool_name = tool_use.get('name')
                        elif tool_use:
                            tool_id = tool_use.get('toolUseId')
                            tool_name = tool_use.get('name')
                        
                        # Only proceed if we have both tool_id and tool_name
                        if tool_id and tool_name:
                            # Get accumulated input (which is a JSON string) and parse it
                            accumulated_input_str = tool_input_accumulators.get(tool_id, "")
                            if accumulated_input_str:
                                try:
                                    # Parse the accumulated JSON string
                                    tool_input = json.loads(accumulated_input_str)
                                    logger.debug(f"Parsed tool input: {json.dumps(tool_input, indent=2)[:500]}")
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse tool input JSON: {e}, input: {accumulated_input_str[:200]}")
                                    # Fallback to tool_use input if available
                                    tool_input = tool_use.get('input', {}) if tool_use else {}
                            else:
                                # Fallback to tool_use input
                                tool_input = tool_use.get('input', {}) if tool_use else {}
                            
                            logger.info(f"Tool use complete: {tool_name} (id: {tool_id})")
                            logger.debug(f"Tool use complete: {tool_name} (id: {tool_id}), input: {json.dumps(tool_input, indent=2)[:500]}")
                            
                            # Execute tool
                            # Tool input from Bedrock is already in the correct format
                            # For code_interpreter: {"code_interpreter_input": {"action": {...}}}
                            # For browser: {"browser_input": {"action": {...}}}
                            # For MCP tools: direct arguments
                            tool_result = self.tool_registry.execute_tool(tool_name, tool_input)
                            formatted_content = self._format_tool_result(tool_result)
                            
                            # Only add tool result if content is not empty
                            if formatted_content:
                                tool_results.append({
                                    "toolUseId": tool_id,
                                    "content": formatted_content
                                })
                                logger.debug(f"Added tool result for {tool_name} with {len(formatted_content)} content blocks")
                            else:
                                logger.warning(f"Tool {tool_name} returned empty content, skipping")
                            
                            # DON'T delete from current_tool_uses yet - we need it for messageStop
                            # We'll clean up after sending the results
                    
                    elif 'messageStop' in event:
                        # Message complete, send tool results if any
                        # IMPORTANT: We must only send tool results that match the tool uses from THIS turn
                        # Count how many tool uses were in this assistant message
                        tool_uses_in_this_turn = len(current_tool_uses)
                        logger.debug("===== messageStop event ======")
                        logger.debug(f"Tool uses in this turn: {tool_uses_in_this_turn}")
                        logger.debug(f"Tool results collected: {len(tool_results)}")
                        logger.debug(f"Current messages count: {len(messages)}")
                        logger.debug(f"Tool use IDs: {list(current_tool_uses.keys())}")
                        logger.debug(f"Tool result IDs: {[tr.get('toolUseId') for tr in tool_results]}")
                        
                        if tool_results:
                            # Validate: we should have exactly one result per tool use
                            if len(tool_results) > tool_uses_in_this_turn:
                                logger.error(f"Mismatch: {len(tool_results)} tool results but only {tool_uses_in_this_turn} tool uses in this turn")
                                # Only take the first N results matching the tool uses
                                tool_results = tool_results[:tool_uses_in_this_turn]
                                logger.warning(f"Truncated tool results to {len(tool_results)} to match tool uses")
                            
                            logger.info(f"Sending {len(tool_results)} tool results back to model (matched to {tool_uses_in_this_turn} tool uses)")
                            logger.debug(f"Tool results to send: {len(tool_results)}")
                            logger.debug(f"Current messages count: {len(messages)}")
                            
                            # First, build the tool result blocks to know which tool uses have results
                            # Bedrock expects ALL tool results in a SINGLE user message
                            # Each tool result should be a content block with toolResult
                            # Format: [{"toolResult": {"toolUseId": "...", "content": [...]}}, ...]
                            tool_result_blocks = []
                            
                            # Only include results that match tool uses from this turn
                            tool_use_ids_in_turn = set(current_tool_uses.keys())
                            for tool_result in tool_results:
                                tool_use_id = tool_result.get("toolUseId")
                                
                                # Skip if this tool use wasn't in the current turn
                                if tool_use_id not in tool_use_ids_in_turn:
                                    logger.warning(f"Skipping tool result for {tool_use_id} - not in current turn's tool uses")
                                    continue
                                
                                tool_content = tool_result.get("content", [])
                                
                                # Ensure content is not empty
                                if not tool_content:
                                    logger.warning(f"Skipping tool result with empty content for toolUseId {tool_use_id}")
                                    continue
                                
                                # Filter out any empty content blocks
                                valid_content = [c for c in tool_content if c and isinstance(c, dict) and c.get("text")]
                                
                                if not valid_content:
                                    logger.warning(f"Skipping tool result - all content blocks are empty for toolUseId {tool_use_id}")
                                    continue
                                
                                # Add tool result as a content block
                                tool_result_blocks.append({
                                    "toolResult": {
                                        "toolUseId": tool_use_id,
                                        "content": valid_content
                                    }
                                })
                                logger.debug(f"Added tool result block for toolUseId {tool_use_id} with {len(valid_content)} content blocks")
                            
                            # Now build assistant message content - include both text and tool uses
                            # IMPORTANT: Only include tool uses that have corresponding results
                            assistant_content = []
                            if complete_text:
                                assistant_content.append({"text": complete_text})
                            
                            # Create a set of tool use IDs that have results (from tool_result_blocks)
                            tool_use_ids_with_results = {block["toolResult"]["toolUseId"] for block in tool_result_blocks}
                            
                            # Add tool uses to assistant message (Bedrock format)
                            # Only include tool uses that have corresponding results
                            tool_uses_added = 0
                            for tool_id, tool_info in current_tool_uses.items():
                                # Only add if this tool use has a corresponding result
                                if tool_id in tool_use_ids_with_results:
                                    # Add tool use to assistant message
                                    tool_input = tool_input_accumulators.get(tool_id, "")
                                    parsed_input = {}
                                    if tool_input:
                                        try:
                                            parsed_input = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
                                        except:
                                            parsed_input = {}
                                    
                                    assistant_content.append({
                                        "toolUse": {
                                            "toolUseId": tool_id,
                                            "name": tool_info['name'],
                                            "input": parsed_input
                                        }
                                    })
                                    tool_uses_added += 1
                            
                            # Final validation: tool uses in assistant message must match tool results
                            if tool_uses_added != len(tool_result_blocks):
                                logger.error(f"CRITICAL: Mismatch - {tool_uses_added} tool uses in assistant message but {len(tool_result_blocks)} tool result blocks")
                                # This should not happen, but if it does, truncate to match
                                if len(tool_result_blocks) > tool_uses_added:
                                    tool_result_blocks = tool_result_blocks[:tool_uses_added]
                                    logger.warning(f"Truncated tool results to {len(tool_result_blocks)} to match tool uses")
                            
                            # Add assistant message with both text and tool uses
                            if assistant_content:
                                messages.append({
                                    "role": "assistant",
                                    "content": assistant_content
                                })
                                logger.debug(f"Added assistant message at index {len(messages)-1} with {len(assistant_content)} content blocks ({len([c for c in assistant_content if 'text' in c])} text, {tool_uses_added} tool uses)")
                            else:
                                logger.debug("Skipping assistant message - no content")
                            
                            # Add all tool results as a single user message
                            if tool_result_blocks:
                                # Final check: ensure counts match
                                if tool_uses_added != len(tool_result_blocks):
                                    logger.error(f"FINAL VALIDATION FAILED: {tool_uses_added} tool uses but {len(tool_result_blocks)} tool results")
                                    # Don't send if counts don't match
                                    logger.warning("Skipping continuation due to count mismatch")
                                    break
                                
                                messages.append({
                                    "role": "user",
                                    "content": tool_result_blocks
                                })
                                logger.debug("===== Sending continuation request ======")
                                logger.debug(f"Added single user message with {len(tool_result_blocks)} tool result blocks at index {len(messages)-1}")
                                logger.debug(f"Total messages: {len(messages)}")
                                logger.debug(f"Tool uses in assistant message: {tool_uses_added}")
                                logger.debug(f"Tool results in user message: {len(tool_result_blocks)}")
                                
                                # Log message structure for debugging
                                for i, msg in enumerate(messages):
                                    role = msg.get("role")
                                    content = msg.get("content", [])
                                    if isinstance(content, list):
                                        text_blocks = [c for c in content if isinstance(c, dict) and "text" in c]
                                        tool_use_blocks = [c for c in content if isinstance(c, dict) and "toolUse" in c]
                                        tool_result_blocks_in_msg = [c for c in content if isinstance(c, dict) and "toolResult" in c]
                                        logger.debug(f"Message {i}: role={role}, text={len(text_blocks)}, toolUse={len(tool_use_blocks)}, toolResult={len(tool_result_blocks_in_msg)}")
                                
                                # Clean up tool uses after sending results
                                current_tool_uses.clear()
                                tool_input_accumulators.clear()
                                content_block_to_tool_id.clear()
                            else:
                                logger.warning("No valid tool results to send, skipping continuation")
                                # Clean up even if no results
                                current_tool_uses.clear()
                                tool_input_accumulators.clear()
                                content_block_to_tool_id.clear()
                                break
                            
                            # Continue streaming with tool results
                            # This is a recursive helper function to handle continuation streams
                            # that may themselves contain tool calls
                            # Capture tool_config from outer scope
                            captured_tool_config = tool_config
                            
                            def process_continuation_stream(continuation_messages, current_depth=0, exact_call_history=None):
                                """Recursively process continuation streams that may contain tool calls.
                                
                                This function supports legitimate multi-tool workflows by:
                                - Not imposing arbitrary depth limits
                                - Only stopping on actual infinite loops (exact repetition of same tool call)
                                - Allowing the model to use as many tools as needed for the task
                                
                                Args:
                                    continuation_messages: Messages for the conversation
                                    current_depth: Current recursion depth (for logging only)
                                    exact_call_history: List of exact tool call signatures (tool_name + exact input JSON) 
                                                       to detect infinite loops
                                """
                                if exact_call_history is None:
                                    exact_call_history = []
                                
                                # Safety limit: 1000 depth to prevent memory issues, but this should never be hit
                                # in legitimate workflows. If it is, there's likely a real bug.
                                SAFETY_MAX_DEPTH = 1000
                                if current_depth >= SAFETY_MAX_DEPTH:
                                    logger.error(f"Reached safety max depth {SAFETY_MAX_DEPTH} - this indicates a serious issue")
                                    yield f"Error: Reached safety limit of {SAFETY_MAX_DEPTH} recursive calls. This should never happen in normal operation."
                                    return
                                
                                # Detect actual infinite loops: exact same tool call (tool + exact same input) repeated 5+ times
                                # We use exact matching (JSON string comparison) to avoid false positives
                                if len(exact_call_history) >= 5:
                                    # Check if the last 5 calls are identical
                                    last_five = exact_call_history[-5:]
                                    if len(set(last_five)) == 1:  # All identical
                                        logger.warning(f"Detected infinite loop: exact same tool call repeated 5+ times: {last_five[0]}")
                                        yield f"Error: Detected an infinite loop where the exact same tool call is being repeated. Stopping to prevent infinite recursion."
                                        return
                                
                                continue_request = {
                                    "modelId": self.model_id,
                                    "messages": continuation_messages,
                                }
                                # IMPORTANT: Bedrock requires toolConfig when messages contain toolUse and toolResult blocks
                                # We must include toolConfig in continuation requests to avoid ValidationException
                                # Use "auto" instead of "any" to encourage text responses while still allowing tools if needed
                                if captured_tool_config:
                                    # Create a modified toolConfig with "auto" toolChoice for continuations
                                    # This allows tools but doesn't force them, encouraging text responses
                                    continuation_tool_config = {
                                        "tools": captured_tool_config.get("tools", []),
                                        "toolChoice": {"auto": {}}
                                    }
                                    continue_request["toolConfig"] = continuation_tool_config
                                    logger.info(f"Including toolConfig in continuation request (depth {current_depth}) with {len(continuation_tool_config.get('tools', []))} tools")
                                
                                logger.debug(f"Calling converse_stream (depth {current_depth}) with {len(continuation_messages)} messages")
                                logger.info(f"Starting continuation stream processing (depth {current_depth})")
                                logger.debug(f"Continuation request params: modelId={self.model_id}, messages={len(continuation_messages)}, hasToolConfig={'toolConfig' in continue_request}")
                                
                                try:
                                    continue_response = self.bedrock_runtime.converse_stream(**continue_request)
                                    logger.debug(f"Continuation response received, type: {type(continue_response)}")
                                    logger.debug(f"Continuation response attributes: {dir(continue_response)[:20]}")
                                    
                                    # Access the stream from the response (same logic as initial stream)
                                    if hasattr(continue_response, 'get'):
                                        continue_stream = continue_response.get('stream', [])
                                        logger.info("Accessing continuation stream from dict-like response")
                                    elif hasattr(continue_response, 'stream'):
                                        continue_stream = continue_response.stream
                                        logger.info("Accessing continuation stream from response.stream attribute")
                                    elif hasattr(continue_response, '__iter__'):
                                        continue_stream = continue_response
                                        logger.info("Using continuation response directly as stream (iterable)")
                                    else:
                                        logger.error(f"Continuation response is not iterable: {type(continue_response)}")
                                        yield "Error: Unexpected response format from continuation request"
                                        return
                                    
                                    continue_event_count = 0
                                    continue_text_received = False
                                    continue_text_content = ""  # Accumulate text content for assistant message
                                    continue_tool_uses = {}  # Track tool uses in continuation
                                    continue_tool_input_accumulators = {}
                                    continue_content_block_to_tool_id = {}
                                    continue_tool_results = []
                                    
                                    for continue_event in continue_stream:
                                        continue_event_count += 1
                                        event_keys = list(continue_event.keys()) if isinstance(continue_event, dict) else []
                                        logger.debug(f"Continuation event #{continue_event_count}: {event_keys}")
                                        
                                        if isinstance(continue_event, dict):
                                            if 'contentBlockDelta' in continue_event:
                                                delta = continue_event['contentBlockDelta']
                                                delta_content = delta.get('delta', {})
                                                
                                                # Handle text content
                                                if 'text' in delta_content:
                                                    text_chunk = delta_content['text']
                                                    continue_text_received = True
                                                    continue_text_content += text_chunk  # Accumulate for assistant message
                                                    # Update output token count (include continuation text)
                                                    self.output_tokens = estimate_output_tokens(complete_text + continue_text_content)
                                                    logger.debug(f"Yielding text chunk from continuation: {text_chunk[:100]}")
                                                    yield text_chunk
                                                # Handle tool use input (model is calling another tool)
                                                elif 'toolUse' in delta_content:
                                                    tool_use_delta = delta_content['toolUse']
                                                    content_block_index = delta.get('contentBlockIndex')
                                                    tool_id = continue_content_block_to_tool_id.get(content_block_index) if content_block_index is not None else None
                                                    
                                                    if tool_id and 'input' in tool_use_delta:
                                                        input_delta = tool_use_delta['input']
                                                        if tool_id not in continue_tool_input_accumulators:
                                                            continue_tool_input_accumulators[tool_id] = ""
                                                        if isinstance(input_delta, str):
                                                            continue_tool_input_accumulators[tool_id] += input_delta
                                                    logger.debug(f"Continuation tool use delta for tool_id {tool_id}")
                                            
                                            elif 'contentBlockStart' in continue_event:
                                                start_info = continue_event['contentBlockStart'].get('start', {})
                                                if 'toolUse' in start_info:
                                                    tool_use = start_info['toolUse']
                                                    tool_id = tool_use.get('toolUseId')
                                                    tool_name = tool_use.get('name')
                                                    content_block_index = continue_event['contentBlockStart'].get('contentBlockIndex')
                                                    
                                                    continue_tool_uses[tool_id] = {'name': tool_name}
                                                    continue_tool_input_accumulators[tool_id] = ""
                                                    if content_block_index is not None:
                                                        continue_content_block_to_tool_id[content_block_index] = tool_id
                                                    logger.debug(f"Continuation tool use started: {tool_name} (id: {tool_id})")
                                            
                                            elif 'contentBlockStop' in continue_event:
                                                block_stop = continue_event['contentBlockStop']
                                                content_block_index = block_stop.get('contentBlockIndex')
                                                tool_id = continue_content_block_to_tool_id.get(content_block_index) if content_block_index is not None else None
                                                
                                                if tool_id and tool_id in continue_tool_uses:
                                                    tool_name = continue_tool_uses[tool_id]['name']
                                                    accumulated_input = continue_tool_input_accumulators.get(tool_id, "")
                                                    
                                                    try:
                                                        tool_input = json.loads(accumulated_input) if accumulated_input else {}
                                                    except:
                                                        tool_input = {}
                                                    
                                                    logger.debug(f"Continuation tool use complete: {tool_name} (id: {tool_id})")
                                                    
                                                    # Execute the tool
                                                    tool_result = self.tool_registry.execute_tool(tool_name, tool_input)
                                                    formatted_content = self._format_tool_result(tool_result)
                                                    
                                                    if formatted_content:
                                                        continue_tool_results.append({
                                                            "toolUseId": tool_id,
                                                            "content": formatted_content
                                                        })
                                                        # Track exact tool call signature for loop detection
                                                        # Use JSON string of tool_name + input for exact matching
                                                        try:
                                                            call_signature = json.dumps({
                                                                'tool_name': tool_name,
                                                                'input': tool_input
                                                            }, sort_keys=True)
                                                            exact_call_history.append(call_signature)
                                                            # Keep only last 10 call signatures to avoid memory issues
                                                            if len(exact_call_history) > 10:
                                                                exact_call_history.pop(0)
                                                        except Exception as e:
                                                            logger.warning(f"Failed to create call signature for loop detection: {e}")
                                                        logger.debug(f"Continuation tool result added for {tool_name}")
                                            
                                            elif 'messageStop' in continue_event:
                                                logger.debug("Continuation messageStop received")
                                                # If we have tool results, we need to continue again
                                                if continue_tool_results:
                                                    logger.info(f"Continuation stream has {len(continue_tool_results)} tool results, need to continue")
                                                break
                                    
                                    # If we received tool results, we need to continue the conversation recursively
                                    # This is normal - the model may need to call multiple tools in sequence
                                    # We continue even if text was received, because tool results must be sent back
                                    if continue_tool_results:
                                        logger.info(f"Continuation stream returned {len(continue_tool_results)} tool results (text received: {continue_text_received}), continuing conversation at depth {current_depth + 1}")
                                        
                                        # Build tool result blocks
                                        continue_tool_result_blocks = []
                                        continue_tool_use_ids_with_results = set()
                                        
                                        for tool_result in continue_tool_results:
                                            tool_use_id = tool_result.get("toolUseId")
                                            tool_content = tool_result.get("content", [])
                                            valid_content = [c for c in tool_content if c and isinstance(c, dict) and c.get("text")]
                                            
                                            if valid_content and tool_use_id:
                                                continue_tool_result_blocks.append({
                                                    "toolResult": {
                                                        "toolUseId": tool_use_id,
                                                        "content": valid_content
                                                    }
                                                })
                                                continue_tool_use_ids_with_results.add(tool_use_id)
                                        
                                        # Build assistant message with both text and tool uses
                                        continue_assistant_content = []
                                        # Include text content if any was received
                                        if continue_text_content:
                                            continue_assistant_content.append({"text": continue_text_content})
                                        
                                        # Add tool uses
                                        for tool_id, tool_info in continue_tool_uses.items():
                                            if tool_id in continue_tool_use_ids_with_results:
                                                tool_input = continue_tool_input_accumulators.get(tool_id, "")
                                                parsed_input = {}
                                                if tool_input:
                                                    try:
                                                        parsed_input = json.loads(tool_input) if isinstance(tool_input, str) else tool_input
                                                    except:
                                                        parsed_input = {}
                                                
                                                continue_assistant_content.append({
                                                    "toolUse": {
                                                        "toolUseId": tool_id,
                                                        "name": tool_info['name'],
                                                        "input": parsed_input
                                                    }
                                                })
                                        
                                        # Add assistant and user messages
                                        next_messages = continuation_messages.copy()
                                        if continue_assistant_content:
                                            next_messages.append({
                                                "role": "assistant",
                                                "content": continue_assistant_content
                                            })
                                        if continue_tool_result_blocks:
                                            next_messages.append({
                                                "role": "user",
                                                "content": continue_tool_result_blocks
                                            })
                                        
                                        # Recursively continue (pass exact_call_history to detect loops)
                                        for chunk in process_continuation_stream(next_messages, current_depth + 1, exact_call_history):
                                            yield chunk
                                        return
                                    
                                    # Handle case where we received text but no tool results
                                    # In this case, the text has already been yielded, so we're done
                                    if continue_text_received and not continue_tool_results:
                                        # Update final output token count
                                        self.output_tokens = estimate_output_tokens(complete_text + continue_text_content)
                                        logger.info(
                                            f"Continuation stream completed with text only ({len(continue_text_content)} chars), "
                                            f"no tool results - stream complete. Total output tokens: {self.output_tokens}"
                                        )
                                        logger.debug(f"Final text content preview: {continue_text_content[:200]}...")
                                        # Text has already been yielded, so we're done - just return
                                        return
                                    
                                    if continue_event_count == 0:
                                        logger.warning("No events received from continuation stream")
                                    elif not continue_text_received and not continue_tool_results:
                                        logger.warning(f"Received {continue_event_count} events but no text content or tool results")
                                    else:
                                        logger.info(f"Continuation stream completed with {continue_event_count} events, text: {continue_text_received}, tools: {len(continue_tool_results)}")
                                    
                                except Exception as continue_error:
                                    logger.error(f"Error in continuation stream: {continue_error}", exc_info=True)
                                    yield f"Error: {str(continue_error)}"
                            
                            # Start the recursive continuation processing
                            # No arbitrary depth limits - only stops on actual infinite loops
                            for chunk in process_continuation_stream(messages, current_depth=0, exact_call_history=[]):
                                yield chunk
                            return
                        
                        # No tool results, just break out of the loop
                        break
                
                # Final output token count
                self.output_tokens = estimate_output_tokens(complete_text)
                logger.info(
                    f"Stream completed. Processed {event_count} events, {len(tool_results)} tool calls. "
                    f"Tokens: {self.input_tokens} input, {self.output_tokens} output"
                )
                
            except StopIteration:
                logger.info(f"Stream ended. Processed {event_count} events, {len(tool_results)} tool calls")
            except Exception as stream_error:
                logger.error(f"Error iterating stream: {stream_error}", exc_info=True)
                raise
            
        except Exception as e:
            logger.error(f"Error in converse_stream: {e}", exc_info=True)
            yield f"Error: {str(e)}"
    
    def _format_tool_result(self, tool_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Format tool result for Bedrock API.
        
        Bedrock expects tool results as a list of content blocks.
        Each content block should have a "text" field.
        """
        if tool_result.get("status") == "error":
            error_content = tool_result.get("content", [])
            error_text = error_content[0].get("text", "Unknown error") if error_content else "Unknown error"
            return [{"text": f"Error: {error_text}"}]
        else:
            # Success case
            content = tool_result.get("content", [])
            formatted = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        formatted.append({"text": item["text"]})
                    elif "json" in item:
                        formatted.append({"text": json.dumps(item["json"])})
                    else:
                        # Convert any other dict to text
                        formatted.append({"text": json.dumps(item)})
                else:
                    # Convert non-dict items to text
                    formatted.append({"text": str(item)})
            
            # Ensure we always return at least one content block
            if not formatted:
                formatted.append({"text": "Tool executed successfully"})
            
            return formatted
    
    def get_token_counts(self) -> Dict[str, Any]:
        """
        Get token counts and model info for the last stream operation.
        
        Returns:
            Dict with 'inputTokens', 'outputTokens', 'totalTokens', and 'modelId'
        """
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.input_tokens + self.output_tokens,
            "modelId": self.model_id
        }
    
