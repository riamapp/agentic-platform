"""
Schema registry and pre-generated Pydantic models for structured output.

This module defines all available output schemas and pre-generates
Pydantic models at module load time for optimal performance.
"""

import logging
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel

from .load import json_schema_to_pydantic_model

logger = logging.getLogger(__name__)

# Schema registry: JSON schema definitions
SCHEMA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "workflow_output": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of the workflow execution"
            },
            "status": {
                "type": "string",
                "enum": ["SUCCESS", "FAILED", "PARTIAL"],
                "description": "Workflow execution status"
            },
            "timestamp": {
                "type": "string",
                "description": "ISO 8601 timestamp of when the workflow completed"
            },
            "data": {
                "type": "object",
                "description": "Workflow-specific data",
                "properties": {
                    "products": {
                        "type": "array",
                        "description": "List of products (for product/price checking workflows)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Product name"
                                },
                                "price": {
                                    "type": "string",
                                    "description": "Price with currency"
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency code (e.g., GBP, USD)"
                                },
                                "availability": {
                                    "type": "string",
                                    "description": "Availability status: In stock|Out of stock|Available for pickup"
                                },
                                "url": {
                                    "type": "string",
                                    "description": "Product URL"
                                },
                                "storeAvailability": {
                                    "type": "object",
                                    "description": "Store availability information",
                                    "properties": {
                                        "location": {
                                            "type": "string",
                                            "description": "Store location name"
                                        },
                                        "available": {
                                            "type": "boolean",
                                            "description": "Whether product is available at this location"
                                        },
                                        "pickupAvailable": {
                                            "type": "boolean",
                                            "description": "Whether pickup is available"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "metrics": {
                "type": "object",
                "description": "Execution metrics",
                "properties": {
                    "itemsProcessed": {
                        "type": "integer",
                        "description": "Number of items processed",
                        "default": 0
                    },
                    "itemsSucceeded": {
                        "type": "integer",
                        "description": "Number of items that succeeded",
                        "default": 0
                    },
                    "itemsFailed": {
                        "type": "integer",
                        "description": "Number of items that failed",
                        "default": 0
                    },
                    "durationSeconds": {
                        "type": "number",
                        "description": "Actual execution duration in seconds",
                        "default": 0
                    },
                    "toolsUsed": {
                        "type": "array",
                        "description": "List of tools used during execution",
                        "items": {
                            "type": "string"
                        },
                        "default": []
                    }
                }
            },
            "executionDetails": {
                "type": "object",
                "description": "Execution context",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "Session ID"
                    },
                    "workflowType": {
                        "type": "string",
                        "enum": ["PRICE_CHECK", "DATA_COLLECTION", "MONITORING", "CUSTOM"],
                        "description": "Optional workflow categorization"
                    },
                    "sources": {
                        "type": "array",
                        "description": "URLs or sources accessed",
                        "items": {
                            "type": "string"
                        },
                        "default": []
                    },
                    "startTime": {
                        "type": "string",
                        "description": "ISO 8601 timestamp of start time"
                    },
                    "endTime": {
                        "type": "string",
                        "description": "ISO 8601 timestamp of end time"
                    }
                }
            },
            "rawOutput": {
                "type": "string",
                "description": "Full agent response text (fallback for debugging)"
            }
        },
        "required": ["summary", "status", "timestamp"]
    },
    "chat_response": {
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "The agent's text response to the user"
            },
            "timestamp": {
                "type": "string",
                "description": "ISO 8601 timestamp when the response was generated"
            },
            "sessionId": {
                "type": "string",
                "description": "Session identifier for this conversation"
            }
        },
        "required": ["response", "timestamp", "sessionId"]
    }
}

# Cache for pre-generated Pydantic models
PYDANTIC_MODEL_CACHE: Dict[str, Type[BaseModel]] = {}


def _pre_generate_models():
    """Pre-generate Pydantic models for all registered schemas at module load time."""
    for schema_name, schema in SCHEMA_REGISTRY.items():
        try:
            # Generate model name from schema name (e.g., "workflow_output" -> "WorkflowOutput")
            model_name = "".join(word.capitalize() for word in schema_name.split("_")) + "Output"
            
            pydantic_model = json_schema_to_pydantic_model(schema, model_name)
            PYDANTIC_MODEL_CACHE[schema_name] = pydantic_model
            logger.info(f"Pre-generated Pydantic model '{model_name}' for schema: {schema_name}")
        except Exception as e:
            logger.error(
                f"Failed to pre-generate Pydantic model for schema '{schema_name}': {e}",
                exc_info=True
            )
            # Don't raise - allow other schemas to load even if one fails
            # The error will be caught when trying to use the schema


def get_schema(schema_name: str) -> Dict[str, Any]:
    """
    Get a schema by name from the registry.
    
    Args:
        schema_name: Name of the schema to retrieve
        
    Returns:
        JSON schema dictionary
        
    Raises:
        ValueError: If schema name is not found in registry
    """
    if schema_name not in SCHEMA_REGISTRY:
        available = ", ".join(SCHEMA_REGISTRY.keys())
        raise ValueError(
            f"Unknown schema: '{schema_name}'. Available schemas: {available}"
        )
    return SCHEMA_REGISTRY[schema_name]


def get_pydantic_model(schema_name: str) -> Type[BaseModel]:
    """
    Get a pre-generated Pydantic model by schema name.
    
    Args:
        schema_name: Name of the schema
        
    Returns:
        Pydantic model class
        
    Raises:
        ValueError: If schema name is not found or model generation failed
    """
    if schema_name not in PYDANTIC_MODEL_CACHE:
        if schema_name not in SCHEMA_REGISTRY:
            available = ", ".join(SCHEMA_REGISTRY.keys())
            raise ValueError(
                f"Unknown schema: '{schema_name}'. Available schemas: {available}"
            )
        # Try to generate on-demand if not in cache (shouldn't happen, but handle gracefully)
        logger.warning(f"Pydantic model for '{schema_name}' not in cache, generating on-demand")
        try:
            model_name = "".join(word.capitalize() for word in schema_name.split("_")) + "Output"
            pydantic_model = json_schema_to_pydantic_model(
                SCHEMA_REGISTRY[schema_name],
                model_name
            )
            PYDANTIC_MODEL_CACHE[schema_name] = pydantic_model
            return pydantic_model
        except Exception as e:
            raise ValueError(
                f"Failed to generate Pydantic model for schema '{schema_name}': {e}"
            ) from e
    
    return PYDANTIC_MODEL_CACHE[schema_name]


def list_available_schemas() -> list[str]:
    """
    List all available schema names.
    
    Returns:
        List of schema names
    """
    return list(SCHEMA_REGISTRY.keys())


# Pre-generate all models at module load time
_pre_generate_models()
