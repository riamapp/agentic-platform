"""
Token counting utilities using tiktoken for Claude 3.5 Sonnet.

Provides functions to count tokens in text strings and message arrays
used by the Bedrock API.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import tiktoken, fallback to None if not available
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not available, will use byte-based estimation")


# Claude 3.5 Sonnet uses cl100k_base encoding
ENCODING_NAME = "cl100k_base"

# Cache for the encoding to avoid re-initializing
_encoding_cache: Optional[Any] = None


def get_encoding():
    """
    Get or create the tiktoken encoding.
    
    Returns:
        tiktoken.Encoding object if available, None otherwise
    """
    global _encoding_cache
    
    if not TIKTOKEN_AVAILABLE:
        return None
    
    if _encoding_cache is None:
        try:
            _encoding_cache = tiktoken.get_encoding(ENCODING_NAME)
            logger.debug(f"Initialized tiktoken encoding: {ENCODING_NAME}")
        except Exception as e:
            logger.error(f"Failed to initialize tiktoken encoding: {e}")
            return None
    
    return _encoding_cache


def count_tokens(text: str) -> int:
    """
    Count tokens in a text string.
    
    Args:
        text: Text string to count tokens for
        
    Returns:
        Number of tokens (estimated if tiktoken unavailable)
    """
    if not text:
        return 0
    
    encoding = get_encoding()
    if encoding:
        try:
            return len(encoding.encode(text))
        except Exception as e:
            logger.warning(f"Error counting tokens with tiktoken: {e}, falling back to estimation")
            # Fall through to byte-based estimation
    
    # Fallback: estimate tokens from bytes (rough approximation: ~4 chars per token)
    # This is conservative and may overestimate
    return len(text.encode('utf-8')) // 4


def count_tokens_in_messages(messages: List[Dict[str, Any]], tool_schemas: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    Count total tokens in a messages array (Bedrock API format).
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        tool_schemas: Optional list of tool schema dicts to include in count
        
    Returns:
        Total number of tokens
    """
    total_tokens = 0
    
    # Count tokens in each message
    for message in messages:
        role = message.get("role", "")
        content = message.get("content", [])
        
        # Add tokens for role (small overhead)
        total_tokens += count_tokens(role)
        
        # Count tokens in content blocks
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # Text content
                    if "text" in block:
                        total_tokens += count_tokens(block["text"])
                    # Tool use content
                    elif "toolUse" in block:
                        tool_use = block["toolUse"]
                        total_tokens += count_tokens(tool_use.get("name", ""))
                        # Count input as JSON string
                        if "input" in tool_use:
                            import json
                            try:
                                input_str = json.dumps(tool_use["input"])
                                total_tokens += count_tokens(input_str)
                            except Exception:
                                total_tokens += count_tokens(str(tool_use["input"]))
                    # Tool result content
                    elif "toolResult" in block:
                        tool_result = block["toolResult"]
                        # Count tool result content
                        if "content" in tool_result:
                            for content_item in tool_result["content"]:
                                if isinstance(content_item, dict) and "text" in content_item:
                                    total_tokens += count_tokens(content_item["text"])
                elif isinstance(block, str):
                    total_tokens += count_tokens(block)
        elif isinstance(content, str):
            total_tokens += count_tokens(content)
    
    # Count tokens in tool schemas if provided
    if tool_schemas:
        for schema in tool_schemas:
            # Convert schema to JSON string for counting
            import json
            try:
                schema_str = json.dumps(schema)
                total_tokens += count_tokens(schema_str)
            except Exception:
                total_tokens += count_tokens(str(schema))
    
    return total_tokens


def estimate_output_tokens(text: str) -> int:
    """
    Estimate output tokens from response text.
    
    This is used to estimate tokens in the assistant's response.
    
    Args:
        text: Response text from the model
        
    Returns:
        Estimated number of tokens
    """
    return count_tokens(text)


def get_max_prompt_tokens() -> int:
    """
    Get the maximum prompt tokens limit from environment variable.
    
    Returns:
        Maximum prompt tokens (default: 160000)
    """
    default = 160000
    try:
        value = os.getenv("MAX_PROMPT_TOKENS")
        if value:
            return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid MAX_PROMPT_TOKENS value, using default: {default}")
    return default


def get_token_warning_threshold() -> float:
    """
    Get the token warning threshold from environment variable.
    
    Returns:
        Warning threshold as float (default: 0.8)
    """
    default = 0.8
    try:
        value = os.getenv("TOKEN_WARNING_THRESHOLD")
        if value:
            return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid TOKEN_WARNING_THRESHOLD value, using default: {default}")
    return default

