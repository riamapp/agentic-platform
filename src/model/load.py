from typing import Dict, Any, Optional, Type
import boto3
from pydantic import BaseModel, create_model, Field
import json
import logging
import sys
import os

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
        import os
        env_level = os.getenv('LOG_LEVEL', '').upper()
        if env_level:
            log_level = getattr(logging, env_level, logging.INFO)
    except Exception:
        pass  # Use default INFO level if environment variable parsing fails
    logger.setLevel(log_level)

# Uses global inference profile for on-demand model access
# https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
# Direct model IDs (e.g., "amazon.nova-micro-v1:0") cannot be used with on-demand throughput.
# You must use an inference profile ID that starts with "global." prefix.
#
# Amazon Nova Micro (cost-effective but doesn't support tool calling):
# Use the inference profile format: global.amazon.nova-micro-v1:0
# Note: Verify the exact inference profile ID in AWS Bedrock console or via AWS CLI:
#   aws bedrock list-inference-profiles --region <your-region> --query 'inferenceProfileSummaries[?contains(inferenceProfileId, `nova-micro`)]'
# MODEL_ID = "eu.amazon.nova-micro-v1:0"

# Claude Sonnet 3.5 (supports tool calling):
# This model supports tool calling which is required for browser and code interpreter tools
# Use inference profile ID for on-demand throughput (required format)
# Note: Region prefix should match your deployment region (us. for us-west-2, eu. for eu-west-1, etc.)
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

def load_model() -> str:
    """
    Get Bedrock model ID for use with native Bedrock API.
    
    Returns:
        Model ID string
        
    Raises:
        ValueError: If MODEL_ID is invalid or empty
    """
    logger.info(f"Loading Bedrock model with ID: {MODEL_ID}")
    
    if not MODEL_ID or not isinstance(MODEL_ID, str) or not MODEL_ID.strip():
        error_msg = f"Invalid MODEL_ID: '{MODEL_ID}'. MODEL_ID must be a non-empty string."
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    logger.info(f"Successfully loaded Bedrock model ID: {MODEL_ID}")
    return MODEL_ID


def json_schema_to_pydantic_model(json_schema: Dict[str, Any], model_name: str = "StructuredOutput") -> Type[BaseModel]:
    """
    Convert a JSON schema dictionary to a Pydantic model dynamically.
    
    This converts the JSON schema to a Pydantic BaseModel that can be used
    with Strands' agent.structured_output() method.
    
    Args:
        json_schema: JSON schema dictionary (can be full JSON schema or example dict)
        model_name: Name for the generated Pydantic model class
        
    Returns:
        A Pydantic BaseModel subclass
        
    Raises:
        ValueError: If the schema is invalid or cannot be converted
        TypeError: If model creation fails due to type errors
    """
    from typing import List as TypingList
    
    logger.debug(f"Converting JSON schema to Pydantic model '{model_name}'")
    
    # Validate input type
    if not isinstance(json_schema, dict):
        error_msg = f"JSON schema must be a dictionary, got {type(json_schema)}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Validate input is not empty
    if not json_schema:
        error_msg = "JSON schema cannot be empty"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    logger.debug(f"JSON schema has {len(json_schema)} top-level keys")
    
    # Extract properties from the JSON schema
    # Handle both full JSON schema format and simple dict format (example values)
    try:
        if "properties" in json_schema:
            # Full JSON schema format
            logger.debug("Detected full JSON schema format with 'properties' key")
            properties = json_schema.get("properties", {})
            required_fields = json_schema.get("required", [])
            logger.debug(f"Found {len(properties)} properties, {len(required_fields)} required fields")
        else:
            # Simple dict format - infer structure from example values
            logger.debug("Detected simple dict format, inferring schema from example values")
            properties = {}
            required_fields = []
            for key, value in json_schema.items():
                try:
                    # Validate field name is a valid Python identifier
                    if not key.replace("_", "").isalnum() or not key[0].isalpha() and key[0] != "_":
                        error_msg = f"Invalid field name '{key}': must be a valid Python identifier"
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                    
                    # Infer type from example value
                    if isinstance(value, str):
                        properties[key] = {"type": "string"}
                    elif isinstance(value, int):
                        properties[key] = {"type": "integer"}
                    elif isinstance(value, float):
                        properties[key] = {"type": "number"}
                    elif isinstance(value, bool):
                        properties[key] = {"type": "boolean"}
                    elif isinstance(value, list):
                        # Infer array item type from first element if available
                        if value and isinstance(value[0], dict):
                            properties[key] = {"type": "array", "items": {"type": "object"}}
                        elif value and isinstance(value[0], str):
                            properties[key] = {"type": "array", "items": {"type": "string"}}
                        else:
                            properties[key] = {"type": "array", "items": {"type": "string"}}
                    elif isinstance(value, dict):
                        properties[key] = {"type": "object"}
                    else:
                        logger.warning(f"Unknown type for field '{key}': {type(value)}, defaulting to string")
                        properties[key] = {"type": "string"}
                except Exception as e:
                    logger.error(f"Error processing field '{key}': {str(e)}", exc_info=True)
                    raise ValueError(f"Failed to process field '{key}': {str(e)}") from e
            
            logger.debug(f"Inferred {len(properties)} properties from example dict")
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        error_msg = f"Error extracting properties from JSON schema: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg) from e
    
    if not properties:
        error_msg = "No properties found in JSON schema"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Build field definitions for Pydantic
    logger.debug(f"Building Pydantic field definitions for {len(properties)} properties")
    field_definitions = {}
    
    for field_name, field_schema in properties.items():
        try:
            # Validate field name
            if not isinstance(field_name, str) or not field_name.replace("_", "").isalnum():
                error_msg = f"Invalid field name '{field_name}': must be a valid Python identifier"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            if isinstance(field_schema, dict):
                field_type = Any
                field_default = None
                
                # Determine Python type from JSON schema type
                schema_type = field_schema.get("type", "string")
                if schema_type == "string":
                    field_type = str
                elif schema_type == "integer":
                    field_type = int
                elif schema_type == "number":
                    field_type = float
                elif schema_type == "boolean":
                    field_type = bool
                elif schema_type == "array":
                    items_schema = field_schema.get("items", {})
                    if isinstance(items_schema, dict):
                        items_type = items_schema.get("type", "string")
                        if items_type == "string":
                            field_type = TypingList[str]
                        elif items_type == "integer":
                            field_type = TypingList[int]
                        elif items_type == "object":
                            field_type = TypingList[Dict[str, Any]]
                        else:
                            field_type = TypingList[Any]
                    else:
                        field_type = TypingList[Any]
                elif schema_type == "object":
                    # For nested objects, use Dict
                    field_type = Dict[str, Any]
                else:
                    field_type = Any
                
                # Check if field is required
                is_required = field_name in required_fields
                
                # Get default value if specified (but don't use example values as defaults)
                if "default" in field_schema:
                    field_default = field_schema["default"]
                elif not is_required:
                    field_default = None
                    field_type = Optional[field_type]
                
                # Create Field with description if available
                description = field_schema.get("description", "")
                if description:
                    if field_default is not None:
                        field_definitions[field_name] = (field_type, Field(default=field_default, description=description))
                    else:
                        field_definitions[field_name] = (field_type, Field(default=..., description=description) if is_required else Field(default=None, description=description))
                else:
                    if field_default is not None:
                        field_definitions[field_name] = (field_type, field_default)
                    elif is_required:
                        field_definitions[field_name] = (field_type, ...)
                    else:
                        field_definitions[field_name] = (Optional[field_type], None)
            else:
                # Simple case: infer type from value
                if isinstance(field_schema, str):
                    field_definitions[field_name] = (str, None)
                elif isinstance(field_schema, (int, float, bool)):
                    field_definitions[field_name] = (type(field_schema), None)
                elif isinstance(field_schema, list):
                    field_definitions[field_name] = (TypingList[Any], None)
                elif isinstance(field_schema, dict):
                    field_definitions[field_name] = (Dict[str, Any], None)
                else:
                    field_definitions[field_name] = (Any, None)
        except Exception as e:
            logger.error(
                f"Error processing field '{field_name}': {str(e)}",
                exc_info=True,
                extra={"field_name": field_name, "field_schema": str(field_schema)}
            )
            raise ValueError(f"Failed to process field '{field_name}': {str(e)}") from e
    
    logger.debug(f"Successfully built {len(field_definitions)} field definitions")
    
    # Create the Pydantic model dynamically
    # Let exceptions propagate - don't silently fall back
    try:
        logger.debug(f"Creating Pydantic model '{model_name}' with {len(field_definitions)} fields")
        model_class = create_model(model_name, **field_definitions)
        logger.info(f"Successfully created Pydantic model '{model_name}' with {len(field_definitions)} fields")
        return model_class
    except TypeError as e:
        error_msg = (
            f"Type error creating Pydantic model '{model_name}': {str(e)}. "
            f"Schema had {len(properties)} properties. "
            f"Please check field types and ensure all field names are valid Python identifiers."
        )
        logger.error(error_msg, exc_info=True, extra={
            "model_name": model_name,
            "property_count": len(properties),
            "field_count": len(field_definitions),
        })
        raise TypeError(error_msg) from e
    except Exception as e:
        error_msg = (
            f"Failed to create Pydantic model '{model_name}' from JSON schema: {str(e)}. "
            f"Schema had {len(properties)} properties. "
            f"Please ensure the schema is valid and all field names are valid Python identifiers."
        )
        logger.error(
            error_msg,
            exc_info=True,
            extra={
                "model_name": model_name,
                "property_count": len(properties),
                "field_count": len(field_definitions),
                "error_type": type(e).__name__,
            }
        )
        raise ValueError(error_msg) from e


def load_model_with_structured_output(json_schema: Dict[str, Any]) -> tuple[str, Type[BaseModel]]:
    """
    Get Bedrock model ID for use with structured output.
    
    Note: Structured output is handled via tool calling with Pydantic models.
    This function returns the model ID and a Pydantic model created from the JSON schema.
    
    Args:
        json_schema: JSON schema dictionary defining the expected output structure
        
    Returns:
        Tuple of (model ID string, Pydantic model class)
        
    Raises:
        ValueError: If the JSON schema is invalid or cannot be converted to a Pydantic model
        TypeError: If model creation fails due to type errors
    """
    logger.info("Loading model with structured output configuration")
    
    # Validate input
    if not isinstance(json_schema, dict):
        error_msg = f"json_schema must be a dictionary, got {type(json_schema)}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    if not json_schema:
        error_msg = "json_schema cannot be empty when requesting structured output"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    try:
        # Get model ID
        model_id = load_model()
        logger.info(f"Successfully loaded Bedrock model ID: {model_id}")
        
        # Convert JSON schema to Pydantic model
        logger.debug("Converting JSON schema to Pydantic model for structured output")
        pydantic_model = json_schema_to_pydantic_model(json_schema, "WorkflowOutput")
        logger.info("Successfully created Pydantic model for structured output")
        
        return model_id, pydantic_model
    except (ValueError, TypeError) as e:
        # Re-raise validation/type errors as-is (they already have good error messages)
        logger.error(
            f"Failed to create structured output model: {str(e)}",
            exc_info=True,
            extra={
                "model_id": MODEL_ID,
                "error_type": type(e).__name__,
                "schema_keys": list(json_schema.keys()) if isinstance(json_schema, dict) else None,
            }
        )
        raise
    except Exception as e:
        error_msg = f"Unexpected error loading model with structured output: {str(e)}"
        logger.error(
            error_msg,
            exc_info=True,
            extra={
                "model_id": MODEL_ID,
                "error_type": type(e).__name__,
            }
        )
        raise RuntimeError(error_msg) from e
