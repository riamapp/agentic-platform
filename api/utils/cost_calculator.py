"""
Cost calculation utilities for model token usage.

Calculates costs based on token counts and model-specific pricing.
Supports Claude 3.5 Sonnet and can be extended for other models.

AWS Bedrock pricing is given per 1000 tokens, so all prices are in USD per 1000 tokens.
"""

import os
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

# Claude 3.5 Sonnet pricing (per 1000 tokens)
# Prices are in USD and based on AWS Bedrock pricing as of 2024
# These can be overridden via environment variables
# AWS Bedrock pricing: $3.00 per 1M input tokens = $0.003 per 1000 input tokens
# AWS Bedrock pricing: $15.00 per 1M output tokens = $0.015 per 1000 output tokens
DEFAULT_INPUT_PRICE_PER_1K = 0.003   # $0.003 per 1000 input tokens
DEFAULT_OUTPUT_PRICE_PER_1K = 0.015  # $0.015 per 1000 output tokens

# Model-specific pricing (per 1000 tokens)
# Based on AWS Bedrock pricing as of 2024
MODEL_PRICING = {
    "claude-3-5-sonnet": {
        "input": 0.003,   # $3.00 per 1M = $0.003 per 1K
        "output": 0.015,  # $15.00 per 1M = $0.015 per 1K
    },
    "claude-3-sonnet": {
        "input": 0.003,
        "output": 0.015,
    },
    "claude-3-opus": {
        "input": 0.015,   # $15.00 per 1M = $0.015 per 1K
        "output": 0.075,  # $75.00 per 1M = $0.075 per 1K
    },
    "claude-3-haiku": {
        "input": 0.00025,  # $0.25 per 1M = $0.00025 per 1K
        "output": 0.00125, # $1.25 per 1M = $0.00125 per 1K
    },
    "nova-micro": {
        "input": 0.000075,  # $0.075 per 1M = $0.000075 per 1K
        "output": 0.0003,   # $0.30 per 1M = $0.0003 per 1K
    },
    "nova-lite": {
        "input": 0.0001,    # $0.10 per 1M = $0.0001 per 1K
        "output": 0.0004,   # $0.40 per 1M = $0.0004 per 1K
    },
    "nova-pro": {
        "input": 0.000375,  # $0.375 per 1M = $0.000375 per 1K
        "output": 0.0015,   # $1.50 per 1M = $0.0015 per 1K
    },
}


def get_model_pricing(model_id: Optional[str] = None) -> Dict[str, float]:
    """
    Get pricing for a specific model.
    
    Args:
        model_id: Model ID (e.g., "eu.anthropic.claude-3-5-sonnet-20240620-v1:0")
                  If None, uses environment variables or defaults
    
    Returns:
        Dict with 'input' and 'output' prices per 1000 tokens (USD)
    """
    # Try to get from environment variables first (allows runtime configuration)
    # Environment variables are per 1000 tokens to match AWS Bedrock pricing format
    input_price = os.getenv("MODEL_INPUT_PRICE_PER_1K")
    output_price = os.getenv("MODEL_OUTPUT_PRICE_PER_1K")
    
    if input_price and output_price:
        try:
            return {
                "input": float(input_price),
                "output": float(output_price),
            }
        except (ValueError, TypeError):
            logger.warning(f"Invalid pricing in environment variables, using defaults")
    
    # Try to detect model from model_id
    if model_id:
        model_id_lower = model_id.lower()
        for model_name, pricing in MODEL_PRICING.items():
            if model_name in model_id_lower:
                logger.info(f"Matched model '{model_name}' in model_id '{model_id}', using pricing: input=${pricing['input']}/1K, output=${pricing['output']}/1K")
                return pricing.copy()
        logger.warning(f"Could not match model_id '{model_id}' to any known model in MODEL_PRICING, using default pricing")
    
    # Default to Claude 3.5 Sonnet pricing
    logger.info("Using default Claude 3.5 Sonnet pricing")
    default_pricing = MODEL_PRICING["claude-3-5-sonnet"].copy()
    logger.info(f"Default pricing: input=${default_pricing['input']}/1K, output=${default_pricing['output']}/1K")
    return default_pricing


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model_id: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate cost based on token usage.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model_id: Optional model ID for model-specific pricing
        
    Returns:
        Dict with:
        - 'inputCost': Cost for input tokens (USD)
        - 'outputCost': Cost for output tokens (USD)
        - 'totalCost': Total cost (USD)
    """
    if input_tokens < 0 or output_tokens < 0:
        logger.warning(f"Negative token counts: input={input_tokens}, output={output_tokens}")
        input_tokens = max(0, input_tokens)
        output_tokens = max(0, output_tokens)
    
    pricing = get_model_pricing(model_id)
    
    # Log pricing being used for debugging
    logger.debug(f"Calculating cost with pricing: input=${pricing['input']}/1K, output=${pricing['output']}/1K, tokens: input={input_tokens}, output={output_tokens}")
    
    # Calculate costs (prices are per 1000 tokens, matching AWS Bedrock pricing format)
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    total_cost = input_cost + output_cost
    
    # Log calculated costs for debugging
    logger.debug(f"Calculated costs: input=${input_cost:.6f}, output=${output_cost:.6f}, total=${total_cost:.6f}")
    
    # Round to 6 decimal places (micro-dollars precision)
    result = {
        "inputCost": round(input_cost, 6),
        "outputCost": round(output_cost, 6),
        "totalCost": round(total_cost, 6),
    }
    
    logger.info(f"Final cost calculation result: {result}")
    return result


def calculate_cost_from_metadata(
    token_metadata: Dict[str, Any],
    model_id: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate cost from token metadata dict.
    
    Args:
        token_metadata: Dict with 'inputTokens', 'outputTokens', 'totalTokens', and optionally 'modelId'
        model_id: Optional model ID for model-specific pricing. If not provided, will try to extract from token_metadata
    
    Returns:
        Dict with cost information
    """
    input_tokens = token_metadata.get("inputTokens", 0)
    output_tokens = token_metadata.get("outputTokens", 0)
    
    # Extract model_id from metadata if not provided as parameter
    if not model_id and "modelId" in token_metadata:
        model_id = token_metadata.get("modelId")
        logger.debug(f"Using model ID from token metadata: {model_id}")
    
    return calculate_cost(input_tokens, output_tokens, model_id)

