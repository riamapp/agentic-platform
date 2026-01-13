"""
Tool registry for converting tools to Bedrock tool format.

This module handles registration of tools and conversion to Bedrock's
tool calling format for use with converse_stream API.
"""

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry for tools that can be called by the Bedrock agent.
    
    Handles native tools (code_interpreter, browser).
    """
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
    
    def register_tool(self, name: str, func: Callable, schema: Dict[str, Any]):
        """
        Register a tool with its schema.
        
        Args:
            name: Tool name
            func: Callable function that implements the tool
            schema: Tool schema in Bedrock format
        """
        self._tools[name] = func
        self._tool_schemas[name] = schema
        logger.info(f"Registered tool: {name}")
    
    def get_tool(self, name: str) -> Callable:
        """Get a tool function by name."""
        return self._tools.get(name)
    
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Get all tool schemas in Bedrock format.
        
        Returns:
            List of tool specifications for Bedrock API
        """
        tool_specs = []
        for name, schema in self._tool_schemas.items():
            input_schema = schema.get("inputSchema", {})
            # If inputSchema is already a dict with "json" key, use it directly
            if isinstance(input_schema, dict) and "json" in input_schema:
                tool_spec = {
                    "toolSpec": {
                        "name": name,
                        "description": schema.get("description", ""),
                        "inputSchema": input_schema
                    }
                }
            else:
                # Wrap in json format
                tool_spec = {
                    "toolSpec": {
                        "name": name,
                        "description": schema.get("description", ""),
                        "inputSchema": {
                            "json": input_schema
                        }
                    }
                }
            tool_specs.append(tool_spec)
        return tool_specs
    
    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name with arguments.
        
        Args:
            name: Tool name
            arguments: Tool arguments (may be nested like {"code_interpreter_input": {...}})
            
        Returns:
            Tool result in standard format
        """
        tool_func = self._tools.get(name)
        if not tool_func:
            return {
                "status": "error",
                "content": [{"text": f"Tool '{name}' not found"}]
            }
        
        try:
            # Extract actual input from nested structure if needed
            # Bedrock sends: {"code_interpreter_input": {"action": {...}}}
            # or {"browser_input": {"action": {...}}}
            actual_input = arguments
            if isinstance(arguments, dict):
                # Check for nested structure
                for key in ['code_interpreter_input', 'browser_input']:
                    if key in arguments:
                        actual_input = arguments[key]
                        break
                # If it's a direct action dict, wrap it appropriately
                if 'action' in arguments and name == 'code_interpreter':
                    actual_input = {"action": arguments['action']}
                elif 'action' in arguments and name == 'browser':
                    actual_input = {"action": arguments['action']}
            
            logger.info(f"Executing tool: {name} with input: {actual_input}")
            
            # Handle both sync and async tool functions
            if inspect.iscoroutinefunction(tool_func):
                # Tool function is async - need to run it
                # Since we might be in a sync context, use asyncio.run()
                # But if we're already in an async context, this will fail
                # So we'll try to get the running event loop first
                try:
                    loop = asyncio.get_running_loop()
                    # We're in an async context, create a task
                    # But we can't await here since this is a sync function
                    # So we'll use nest_asyncio if available, or raise an error
                    import nest_asyncio
                    nest_asyncio.apply()
                    result = asyncio.run(tool_func(actual_input))
                except RuntimeError:
                    # No running loop, safe to use asyncio.run()
                    result = asyncio.run(tool_func(actual_input))
            else:
                # Tool function is sync
                result = tool_func(actual_input)
            
            logger.info(f"Tool {name} executed successfully")
            return result
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}", exc_info=True)
            return {
                "status": "error",
                "content": [{"text": f"Error executing tool '{name}': {str(e)}"}]
            }
    
    def create_code_interpreter_schema(self) -> Dict[str, Any]:
        """Create schema for code interpreter tool."""
        return {
            "description": "Code Interpreter tool for executing code in isolated sandbox environments. Supports Python, JavaScript, and TypeScript with file operations and session management. IMPORTANT: This sandbox CANNOT make HTTP requests or access external APIs. If you need data from external sources, first fetch the data using the appropriate tool, then pass it to the code interpreter for analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code_interpreter_input": {
                        "type": "object",
                        "description": "Code interpreter input containing action to perform",
                        "properties": {
                            "action": {
                                "type": "object",
                                "description": "Action to perform (initSession, executeCode, etc.)",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["initSession", "executeCode", "executeCommand", "readFiles", "listFiles", "writeFiles", "removeFiles", "listLocalSessions"],
                                        "description": "Action type"
                                    },
                                    "session_name": {"type": "string", "description": "Session name (optional - will be auto-generated if not provided for initSession)"},
                                    "description": {"type": "string", "description": "Session description (for initSession)"},
                                    "code": {"type": "string", "description": "Code to execute (for executeCode)"},
                                    "language": {"type": "string", "enum": ["python", "javascript", "typescript"], "description": "Programming language (for executeCode)"},
                                    "clearContext": {"type": "boolean", "description": "Clear context before execution (for executeCode)"},
                                    "command": {"type": "string", "description": "Command to execute (for executeCommand)"},
                                    "paths": {"type": "array", "items": {"type": "string"}, "description": "File paths (for readFiles, removeFiles)"},
                                    "path": {"type": "string", "description": "Directory path (for listFiles)"},
                                    "content": {"type": "array", "description": "File content (for writeFiles)"}
                                },
                                "required": ["type"]
                            }
                        },
                        "required": ["action"]
                    }
                },
                "required": ["code_interpreter_input"]
            }
        }
    
    def create_browser_schema(self) -> Dict[str, Any]:
        """Create schema for browser tool."""
        return {
            "description": "Browser automation tool for web scraping, testing, and automation tasks. Supports navigation, content extraction, clicking, typing, and screenshots. IMPORTANT: For large webpages, prefer 'get_text' over 'get_html' to avoid exceeding model input limits. Use 'get_html' only when you need the actual HTML structure. Content is automatically truncated if it exceeds configurable token/byte limits (see BROWSER_MAX_HTML_SIZE, BROWSER_MAX_HTML_TOKENS, BROWSER_MAX_TEXT_SIZE, BROWSER_MAX_TEXT_TOKENS environment variables).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "browser_input": {
                        "type": "object",
                        "description": "Browser input containing action to perform",
                        "properties": {
                            "action": {
                                "type": "object",
                                "description": "Action to perform (init_session, navigate, get_html, etc.). Use 'get_text' for large pages to avoid input limit errors. For get_text and get_html, selector is OPTIONAL - if omitted, extracts all content from the page.",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["init_session", "navigate", "get_html", "get_text", "click", "type", "screenshot", "close", "list_local_sessions"],
                                        "description": "Action type. Prefer 'get_text' over 'get_html' for large webpages to avoid model input limit errors. For get_text and get_html, selector parameter is OPTIONAL."
                                    },
                                    "session_name": {"type": "string", "description": "Session name (optional for init_session - will be auto-generated if not provided; defaults to 'default' for other actions)"},
                                    "description": {"type": "string", "description": "Session description (for init_session)"},
                                    "url": {"type": "string", "description": "URL to navigate to (for navigate)"},
                                    "selector": {"type": "string", "description": "CSS selector to target specific elements (for click, type, get_text, get_html). OPTIONAL for get_text and get_html - if not provided, extracts all text/HTML from the page. Use selectors to extract only relevant content from large pages."},
                                    "text": {"type": "string", "description": "Text to type (for type)"}
                                },
                                "required": ["type"]
                            }
                        },
                        "required": ["action"]
                    }
                },
                "required": ["browser_input"]
            }
        }
    

