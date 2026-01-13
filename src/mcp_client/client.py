import os
import logging
import inspect
from typing import Any, Dict
from mcp.client.streamable_http import streamablehttp_client
import requests

logger = logging.getLogger(__name__)

COGNITO_TOKEN_URL = os.getenv("COGNITO_TOKEN_URL")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET")
COGNITO_SCOPE = os.getenv("COGNITO_SCOPE")

def _get_access_token():
    """
    Make a POST request to the Cognito OAuth token URL using client credentials.
    Uses Basic Auth (standard OAuth2 approach) with client_id:client_secret.
    """
    # Validate required environment variables
    if not COGNITO_TOKEN_URL:
        raise RuntimeError("Missing required environment variable: COGNITO_TOKEN_URL")
    if not COGNITO_CLIENT_ID:
        raise RuntimeError("Missing required environment variable: COGNITO_CLIENT_ID")
    if not COGNITO_CLIENT_SECRET:
        raise RuntimeError("Missing required environment variable: COGNITO_CLIENT_SECRET")
    if not COGNITO_SCOPE:
        raise RuntimeError("Missing required environment variable: COGNITO_SCOPE")
    
    # Debug: Log client ID (first few chars only for security)
    logger.debug(f"Attempting Cognito token request with client_id: {COGNITO_CLIENT_ID[:10]}... (length: {len(COGNITO_CLIENT_ID) if COGNITO_CLIENT_ID else 0})")
    logger.debug(f"Token URL: {COGNITO_TOKEN_URL}")
    logger.debug(f"Scope: {COGNITO_SCOPE}")
    logger.debug(f"Client secret present: {bool(COGNITO_CLIENT_SECRET)} (length: {len(COGNITO_CLIENT_SECRET) if COGNITO_CLIENT_SECRET else 0})")
    
    # Prepare request data
    request_data = {
        "grant_type": "client_credentials",
        "scope": COGNITO_SCOPE,
    }
    
    # Use Basic Auth (standard OAuth2 client credentials flow)
    # Format: Authorization: Basic base64(client_id:client_secret)
    try:
        response = requests.post(
            COGNITO_TOKEN_URL,
            auth=(COGNITO_CLIENT_ID, COGNITO_CLIENT_SECRET),
            data=request_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,  # fail fast instead of hanging the entire runtime
        )
    except requests.exceptions.Timeout as e:
        error_msg = f"Cognito token request timed out when calling {COGNITO_TOKEN_URL}: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    except requests.exceptions.RequestException as e:
        # Network / DNS / connection errors, surface clearly to AgentCore logs
        error_msg = f"Cognito token request failed due to network error when calling {COGNITO_TOKEN_URL}: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    
    # Check if request was successful
    if not response.ok:
        error_msg = f"Cognito token request failed with status {response.status_code}: {response.text}"
        logger.error(f"Full error response: {error_msg}")
        raise RuntimeError(error_msg)
    
    response_data = response.json()
    
    # Check if access_token exists in response
    if "access_token" not in response_data:
        error_msg = f"Cognito token response missing 'access_token'. Response: {response_data}"
        raise RuntimeError(error_msg)
    
    return response_data["access_token"]


class MCPClientWrapper:
    """
    Wrapper for native MCP client to provide compatible interface.
    Handles async context manager from streamablehttp_client.
    """
    
    def __init__(self, client_context_manager):
        self._client_context_manager = client_context_manager
        self._client = None
    
    async def __aenter__(self):
        """Enter async context and get the actual client."""
        # The streamablehttp_client returns an async context manager
        # When entered, it returns a tuple of (read_stream, write_stream)
        # We need to use these streams with MCP protocol
        try:
            result = await self._client_context_manager.__aenter__()
            logger.info(f"MCP context manager __aenter__ returned type: {type(result)}, is tuple: {isinstance(result, tuple)}, length: {len(result) if isinstance(result, (tuple, list)) else 'N/A'}")
            
            # streamablehttp_client returns (read_stream, write_stream) tuple
            # It might also return 3 items - need to check what they are
            if isinstance(result, tuple):
                logger.info(f"MCP context returned tuple with {len(result)} items: {[type(x).__name__ for x in result]}")
                
                # Extract read/write streams from tuple
                if len(result) >= 2:
                    read_stream = result[0]
                    write_stream = result[1]
                    logger.info(f"Extracted read/write streams from tuple items 0 and 1")
                else:
                    logger.error(f"Cannot extract streams from tuple with length {len(result)}")
                    self._client = result
                    return self
                
                # If tuple has 3 items, check if the third is the client
                if len(result) == 3:
                    third_item = result[2]
                    logger.info(f"Third tuple item type: {type(third_item).__name__}")
                    # Check if third item is a client
                    if hasattr(third_item, 'list_tools') or hasattr(third_item, 'call_tool'):
                        logger.info("Third tuple item appears to be the MCP client - using it directly")
                        self._client = third_item
                        return self
                
                # Try to create ClientSession from the streams (for both 2-item and 3-item tuples)
                # The MCP library might have ClientSession in a different location
                try:
                    from mcp.client.session import ClientSession
                    # Create a ClientSession with the streams
                    self._session = ClientSession(read_stream, write_stream)
                    # Start the session
                    await self._session.__aenter__()
                    self._client = self._session
                    logger.info("Created MCP ClientSession from streams")
                except ImportError:
                    # Try alternative import path
                    try:
                        from mcp import ClientSession
                        self._session = ClientSession(read_stream, write_stream)
                        await self._session.__aenter__()
                        self._client = self._session
                        logger.info("Created MCP ClientSession from streams (alternative import)")
                    except ImportError as e:
                        # If ClientSession doesn't exist, we might need to use the streams directly
                        # Store streams and use them for MCP protocol communication
                        logger.warning(f"ClientSession not available (ImportError: {e}) - will use streams directly")
                        self._read_stream = read_stream
                        self._write_stream = write_stream
                        self._client = None  # Will need manual MCP protocol handling
                except Exception as e:
                    logger.error(f"Error creating ClientSession: {e}", exc_info=True)
                    # Fallback to using tuple directly (won't work but at least we'll see the error)
                    self._client = result
            else:
                # Unexpected return type
                logger.warning(f"Unexpected return type from streamablehttp_client: {type(result)}")
                # Try to use it directly
                self._client = result
        except Exception as e:
            logger.error(f"Error entering MCP client context: {e}", exc_info=True)
            raise
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context."""
        # Exit the session first if it exists
        if hasattr(self, '_session') and self._session:
            try:
                await self._session.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.error(f"Error exiting MCP session: {e}", exc_info=True)
        
        # Then exit the context manager
        if self._client_context_manager:
            await self._client_context_manager.__aexit__(exc_type, exc_val, exc_tb)
    
    async def list_tools(self):
        """List tools asynchronously."""
        try:
            if not self._client:
                logger.error("MCP client not initialized - must be used within async context manager")
                return []
            
            # Log available methods for debugging
            client_methods = [attr for attr in dir(self._client) if not attr.startswith('_') and callable(getattr(self._client, attr))]
            logger.debug(f"MCP client available methods: {client_methods[:20]}")
            
            # ClientSession should have list_tools method
            if hasattr(self._client, 'list_tools'):
                # Check if it's async
                if inspect.iscoroutinefunction(self._client.list_tools):
                    tools_result = await self._client.list_tools()
                else:
                    tools_result = self._client.list_tools()

                # MCP SDKs may return either a list OR a ListToolsResult-like object.
                tools = None
                if isinstance(tools_result, list):
                    tools = tools_result
                elif hasattr(tools_result, "tools"):
                    tools = getattr(tools_result, "tools")
                elif isinstance(tools_result, dict) and "tools" in tools_result:
                    tools = tools_result.get("tools")

                if not tools:
                    logger.info(f"MCP ClientSession.list_tools() returned no tools (type={type(tools_result)})")
                    return []

                logger.info(f"MCP ClientSession.list_tools() returned {len(tools)} tools")
                return tools
            else:
                logger.error(f"MCP ClientSession does not have list_tools method. Available methods: {client_methods[:20]}")
                return []
        except Exception as e:
            logger.error(f"Error listing MCP tools: {e}", exc_info=True)
            return []
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool asynchronously."""
        try:
            if not self._client:
                logger.error("MCP client not initialized - must be used within async context manager")
                return {"status": "error", "content": [{"text": "MCP client not initialized"}]}
            
            # Try to call tool through MCP client
            if hasattr(self._client, 'call_tool'):
                if inspect.iscoroutinefunction(self._client.call_tool):
                    result = await self._client.call_tool(tool_name, arguments)
                else:
                    result = self._client.call_tool(tool_name, arguments)
                return result
            else:
                logger.error(f"MCP client does not have call_tool method")
                return {"status": "error", "content": [{"text": f"MCP tool {tool_name} cannot be called - client missing call_tool method"}]}
        except Exception as e:
            logger.error(f"Error calling MCP tool {tool_name}: {e}", exc_info=True)
            return {"status": "error", "content": [{"text": f"Error executing MCP tool: {str(e)}"}]}
    
    def list_tools_sync(self):
        """Synchronous wrapper - deprecated, use list_tools() instead."""
        logger.warning("list_tools_sync() called but MCP client requires async. Use list_tools() instead.")
        return []


def get_streamable_http_mcp_client():
    """
    Returns an MCP Client for AgentCore Gateway using native MCP client.
    
    The streamablehttp_client returns an async context manager that yields
    the actual client when entered.
    """
    gateway_url = os.getenv("GATEWAY_URL")
    if not gateway_url:
        raise RuntimeError("Missing required environment variable: GATEWAY_URL")
    access_token = _get_access_token()
    
    # Create native MCP client context manager
    # streamablehttp_client() returns an async context manager
    client_context = streamablehttp_client(gateway_url, headers={"Authorization": f"Bearer {access_token}"})
    logger.debug(f"Created MCP client context manager, type: {type(client_context)}")
    return MCPClientWrapper(client_context)
# Updated Wed Dec 17 15:18:47 GMT 2025
