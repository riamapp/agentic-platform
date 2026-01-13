"""
Native Browser tool implementation using Bedrock AgentCore directly.

This uses the same Bedrock AgentCore Browser service as Strands,
but accessed directly via bedrock-agentcore package clients.
Includes fixes for session name validation issues.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import nest_asyncio
from bedrock_agentcore.tools.browser_client import BrowserClient as AgentCoreBrowserClient
from playwright.async_api import Browser as PlaywrightBrowser, Page, async_playwright

# Import token counter for token-based limits
try:
    from ..utils.token_counter import count_tokens, TIKTOKEN_AVAILABLE
except ImportError:
    # Fallback if utils not available
    TIKTOKEN_AVAILABLE = False
    def count_tokens(text: str) -> int:
        return len(text.encode('utf-8')) // 4  # Rough estimation

logger = logging.getLogger(__name__)


class BrowserSession:
    """Represents a browser session with tabs."""
    
    def __init__(self, session_name: str, description: str, browser: PlaywrightBrowser, context, page: Page):
        self.session_name = session_name
        self.description = description
        self.browser = browser
        self.context = context
        self.page = page
        self.tabs: Dict[str, Page] = {}
        self.active_tab = "main"
    
    def add_tab(self, tab_name: str, page: Page):
        """Add a tab to the session."""
        self.tabs[tab_name] = page
    
    def get_active_page(self) -> Optional[Page]:
        """Get the active page for this session."""
        return self.tabs.get(self.active_tab) or self.page


class BrowserTool:
    """
    Native Browser tool using Bedrock AgentCore Browser service.
    
    This is a simplified version that uses the bedrock-agentcore package directly,
    without the Strands wrapper layer. Includes fixes for session name validation.
    """
    
    def __init__(self, region: Optional[str] = None, identifier: Optional[str] = None, session_timeout: int = 3600):
        """
        Initialize the Browser tool.
        
        Args:
            region: AWS region for the browser service
            identifier: Browser identifier (defaults to "aws.browser.v1")
            session_timeout: Session timeout in seconds (default: 3600)
        """
        self.region = region or "us-east-1"
        self.identifier = identifier or "aws.browser.v1"
        self.session_timeout = session_timeout
        self._sessions: Dict[str, BrowserSession] = {}
        self._playwright = None
        self._started = False
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._nest_asyncio_applied = False
        self._client_dict: Dict[str, AgentCoreBrowserClient] = {}
    
    def _normalize_session_name(self, session_name: str) -> str:
        """
        Normalize session name to match pattern ^[a-z0-9-]+$.
        
        This fixes the validation issues we've been experiencing.
        """
        if not session_name:
            return "session"
        
        # Convert to lowercase and replace invalid characters with hyphens
        normalized = re.sub(r'[^a-z0-9-]', '-', session_name.lower())
        # Remove consecutive hyphens
        normalized = re.sub(r'-+', '-', normalized)
        # Remove leading/trailing hyphens
        normalized = normalized.strip('-')
        # Ensure it's not empty
        if not normalized:
            normalized = "session"
        
        if normalized != session_name:
            logger.info(f"Normalized session_name from '{session_name}' to '{normalized}'")
        
        return normalized
    
    def _start(self):
        """Start the platform and initialize Playwright."""
        if not self._started:
            try:
                if not self._nest_asyncio_applied:
                    nest_asyncio.apply()
                    self._nest_asyncio_applied = True
                self._playwright = self._execute_async(async_playwright().start())
                self._started = True
                logger.info("Browser platform started")
            except Exception as e:
                logger.error(f"Failed to start browser platform: {e}")
                raise
    
    def _execute_async(self, coro):
        """Execute async coroutine in event loop."""
        if not self._nest_asyncio_applied:
            nest_asyncio.apply()
            self._nest_asyncio_applied = True
        return asyncio.run(coro)
    
    def browser(self, browser_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for browser tool.
        
        Handles all browser actions: init_session, navigate, get_html, etc.
        """
        # Auto-start platform on first use
        if not self._started:
            self._start()
        
        # Normalize browser_input to dict format
        if not isinstance(browser_input, dict):
            if hasattr(browser_input, "model_dump"):
                browser_input = browser_input.model_dump()
            elif hasattr(browser_input, "dict"):
                browser_input = browser_input.dict()
            elif hasattr(browser_input, "__dict__"):
                browser_input = browser_input.__dict__
            else:
                browser_input = {"action": browser_input} if browser_input else {}
        
        # Handle case where URL is at the top level
        url_at_top = browser_input.get("url")
        
        # Extract action
        action = browser_input.get("action", {})
        if not isinstance(action, dict):
            if hasattr(action, "model_dump"):
                action = action.model_dump()
            elif hasattr(action, "dict"):
                action = action.dict()
            elif hasattr(action, "__dict__"):
                action = action.__dict__
            else:
                action = {}
        
        # If URL is at top level but not in action, move it to action
        if url_at_top and "url" not in action:
            if not action.get("type"):
                action["type"] = "navigate"
            action["url"] = url_at_top
            browser_input["action"] = action
        
        action_type = action.get("type")
        
        # Normalize session names for all actions that use them
        if "session_name" in action:
            action["session_name"] = self._normalize_session_name(action["session_name"])
        
        # Use a consistent default session name for all browser operations
        # This ensures sessions are shared across navigate, get_text, get_html, etc.
        DEFAULT_SESSION_NAME = "default"
        
        # Handle navigate actions: use default session if missing, then auto-initialize if needed
        if action_type == "navigate":
            session_name = action.get("session_name")
            url = action.get("url") or url_at_top
            
            # Use default session if not provided
            if not session_name:
                session_name = DEFAULT_SESSION_NAME
                action["session_name"] = session_name
                logger.info(f"Using default session_name '{session_name}' for navigate action to {url}")
            
            # Auto-initialize session if it doesn't exist
            if session_name not in self._sessions:
                logger.info(f"Auto-initializing session '{session_name}' for navigate action to {url}")
                init_result = self._init_session({
                    "type": "init_session",
                    "session_name": session_name,
                    "description": f"Auto-initialized session for navigating to {url or 'URL'}"
                })
                
                if init_result.get("status") == "error":
                    return init_result
        
        # For get_text, get_html, click, type, screenshot: use default session if not provided
        if action_type in ["get_text", "get_html", "click", "type", "screenshot"]:
            if not action.get("session_name"):
                action["session_name"] = DEFAULT_SESSION_NAME
                logger.info(f"Using default session_name '{DEFAULT_SESSION_NAME}' for {action_type} action")
        
        # Delegate to specific action handlers
        if action_type == "init_session":
            return self._init_session(action)
        elif action_type == "navigate":
            return self._navigate(action)
        elif action_type == "get_html":
            return self._get_html(action)
        elif action_type == "get_text":
            return self._get_text(action)
        elif action_type == "click":
            return self._click(action)
        elif action_type == "type":
            return self._type(action)
        elif action_type == "screenshot":
            return self._screenshot(action)
        elif action_type == "get_jsonld":
            return self._get_jsonld(action)
        elif action_type == "close":
            return self._close(action)
        elif action_type == "list_local_sessions":
            return self._list_local_sessions()
        else:
            return {"status": "error", "content": [{"text": f"Unknown action type: {action_type}"}]}
    
    def _init_session(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize a new browser session."""
        session_name = action.get("session_name")
        description = action.get("description", "Browser session")
        
        # Auto-generate session_name if not provided
        if not session_name:
            session_name = f"session-{uuid.uuid4().hex[:12]}"
            logger.info(f"Auto-generated session_name: {session_name} for init_session action")
        
        # Normalize session name
        session_name = self._normalize_session_name(session_name)
        
        # Check if session already exists
        if session_name in self._sessions:
            return {"status": "error", "content": [{"text": f"Session '{session_name}' already exists"}]}
        
        try:
            # Create new browser instance for this session
            browser = self._execute_async(self._create_browser_session())
            
            # Setup session from browser
            session_browser, session_context, session_page = self._execute_async(
                self._setup_session_from_browser(browser)
            )
            
            # Create and store session object
            session = BrowserSession(
                session_name=session_name,
                description=description,
                browser=session_browser,
                context=session_context,
                page=session_page,
            )
            session.add_tab("main", session_page)
            
            self._sessions[session_name] = session
            
            logger.info(f"Initialized session: {session_name}")
            
            return {
                "status": "success",
                "content": [{
                    "json": {
                        "sessionName": session_name,
                        "description": description,
                    }
                }],
            }
        except Exception as e:
            logger.error(f"Failed to initialize session: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to initialize session: {str(e)}"}]}
    
    async def _create_browser_session(self) -> PlaywrightBrowser:
        """Create a new browser instance for a session."""
        if not self._playwright:
            raise RuntimeError("Playwright not initialized")
        
        # Create new browser client for this session
        session_client = AgentCoreBrowserClient(region=self.region)
        session_id = session_client.start(identifier=self.identifier, session_timeout_seconds=self.session_timeout)
        
        logger.info(f"Started Bedrock AgentCore browser session: {session_id}")
        
        # Get CDP connection details
        cdp_url, cdp_headers = session_client.generate_ws_headers()
        
        # Connect to Bedrock AgentCore browser over CDP
        browser = await self._playwright.chromium.connect_over_cdp(endpoint_url=cdp_url, headers=cdp_headers)
        
        return browser
    
    async def _setup_session_from_browser(self, browser: PlaywrightBrowser):
        """Setup session for AgentCoreBrowser using existing CDP context."""
        session_browser = browser
        
        # CDP connections should have a default context
        if not session_browser.contexts:
            raise RuntimeError(
                "AgentCoreBrowser CDP connection has no contexts. "
                "This may indicate a connection issue with the remote browser."
            )
        
        # Use the existing default context from CDP connection
        session_context = session_browser.contexts[0]
        session_page = await session_context.new_page()
        
        return session_browser, session_context, session_page
    
    def _validate_session(self, session_name: str) -> Optional[Dict[str, Any]]:
        """Validate that a session exists."""
        if session_name not in self._sessions:
            return {"status": "error", "content": [{"text": f"Session '{session_name}' not found"}]}
        return None
    
    async def _extract_jsonld(self, page: Page) -> List[Dict[str, Any]]:
        """
        Extract JSON-LD structured data from the page.
        
        JSON-LD is a lightweight Linked Data format that websites use to provide
        machine-readable structured data. It's typically found in <script type="application/ld+json"> tags.
        
        Returns a list of JSON-LD objects found on the page.
        """
        jsonld_data = []
        try:
            # Find all script tags with type="application/ld+json"
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            
            for script in scripts:
                try:
                    script_content = await script.text_content()
                    if script_content:
                        # Parse the JSON-LD content
                        jsonld_obj = json.loads(script_content.strip())
                        jsonld_data.append(jsonld_obj)
                        logger.info(f"Extracted JSON-LD data: {type(jsonld_obj).__name__}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON-LD script: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Error extracting JSON-LD from script tag: {e}")
                    continue
            
            if jsonld_data:
                logger.info(f"Found {len(jsonld_data)} JSON-LD script(s) on the page")
        except Exception as e:
            logger.warning(f"Error extracting JSON-LD from page: {e}")
        
        return jsonld_data
    
    def _get_session_page(self, session_name: str) -> Optional[Page]:
        """Get the active page for a session."""
        session = self._sessions.get(session_name)
        if session:
            return session.get_active_page()
        return None
    
    def _navigate(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate to a URL."""
        return self._execute_async(self._async_navigate(action))
    
    async def _async_navigate(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async navigate implementation."""
        session_name = action.get("session_name")
        url = action.get("url")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        if not url:
            return {"status": "error", "content": [{"text": "url is required"}]}
        
        # Normalize session name
        session_name = self._normalize_session_name(session_name)
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            # Include session_name in response so model knows what session to use for subsequent calls
            return {
                "status": "success", 
                "content": [{
                    "json": {
                        "message": f"Navigated to {url}",
                        "session_name": session_name
                    }
                }]
            }
        except Exception as e:
            error_str = str(e)
            if "ERR_NAME_NOT_RESOLVED" in error_str:
                error_msg = f"Could not resolve domain '{url}'. The website might not exist or a network connectivity issue."
            elif "ERR_CONNECTION_REFUSED" in error_str:
                error_msg = f"Connection refused for '{url}'. The server might be down or blocking requests."
            elif "ERR_CONNECTION_TIMED_OUT" in error_str:
                error_msg = f"Connection timed out for '{url}'. The server might be slow or unreachable."
            else:
                error_msg = str(e)
            return {"status": "error", "content": [{"text": f"Error: {error_msg}"}]}
    
    def _get_html(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get HTML content."""
        return self._execute_async(self._async_get_html(action))
    
    async def _async_get_html(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async get HTML implementation."""
        session_name = action.get("session_name")
        selector = action.get("selector")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        
        # Normalize session name
        session_name = self._normalize_session_name(session_name)
        
        # Auto-create default session if it doesn't exist (for convenience)
        if session_name not in self._sessions:
            logger.info(f"Auto-creating session '{session_name}' for get_html action")
            init_result = self._init_session({
                "type": "init_session",
                "session_name": session_name,
                "description": f"Auto-created session for get_html"
            })
            if init_result.get("status") == "error":
                return init_result
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            if not selector:
                result = await page.content()
            else:
                from playwright.async_api import TimeoutError as PlaywrightTimeoutError
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    result = await page.inner_html(selector)
                except PlaywrightTimeoutError:
                    return {
                        "status": "error",
                        "content": [{"text": f"Element with selector '{selector}' not found on the page."}],
                    }
            
            # Truncate HTML content if it's too large to avoid exceeding model input limits
            # HTML has significant markup overhead, so we use a smaller limit than text
            MAX_HTML_SIZE = int(os.getenv("BROWSER_MAX_HTML_SIZE", "30000"))  # Default: 30KB
            MAX_HTML_TOKENS = int(os.getenv("BROWSER_MAX_HTML_TOKENS", "8000"))  # Default: 8000 tokens
            original_size = len(result)
            
            # Check both byte and token limits
            should_truncate = False
            truncation_reason = ""
            
            if original_size > MAX_HTML_SIZE:
                should_truncate = True
                truncation_reason = f"size ({original_size} bytes > {MAX_HTML_SIZE} bytes)"
            
            # Check token limit if tiktoken is available
            if TIKTOKEN_AVAILABLE:
                token_count = count_tokens(result)
                if token_count > MAX_HTML_TOKENS:
                    should_truncate = True
                    if truncation_reason:
                        truncation_reason += f" and tokens ({token_count} > {MAX_HTML_TOKENS})"
                    else:
                        truncation_reason = f"tokens ({token_count} > {MAX_HTML_TOKENS})"
            
            # Extract JSON-LD structured data if available
            jsonld_data = await self._extract_jsonld(page)
            
            if should_truncate:
                # Truncate to the smaller of byte or token limit
                truncated_result = result[:MAX_HTML_SIZE]
                if TIKTOKEN_AVAILABLE:
                    # If token limit is more restrictive, truncate further
                    token_count = count_tokens(truncated_result)
                    if token_count > MAX_HTML_TOKENS:
                        # Binary search for appropriate truncation point
                        low, high = 0, len(result)
                        while low < high:
                            mid = (low + high) // 2
                            test_text = result[:mid]
                            if count_tokens(test_text) <= MAX_HTML_TOKENS:
                                low = mid + 1
                            else:
                                high = mid
                        truncated_result = result[:low - 1] if low > 0 else result[:MAX_HTML_SIZE]
                
                logger.warning(f"HTML content exceeded limit ({truncation_reason}), truncating to {len(truncated_result)} bytes")
                warning_msg = f"\n\n[WARNING: HTML content was truncated from {original_size} to {len(truncated_result)} bytes to avoid exceeding model input limits. Consider using get_text action or a more specific selector to extract only relevant content.]"
                
                # Include JSON-LD data if available
                response_content = [{"text": truncated_result + warning_msg}]
                if jsonld_data:
                    response_content.append({
                        "json": {
                            "jsonld": jsonld_data,
                            "note": "JSON-LD structured data extracted from the page (see https://json-ld.org/)"
                        }
                    })
                return {
                    "status": "success",
                    "content": response_content
                }
            
            # Include JSON-LD data if available
            response_content = [{"text": result}]
            if jsonld_data:
                response_content.append({
                    "json": {
                        "jsonld": jsonld_data,
                        "note": "JSON-LD structured data extracted from the page (see https://json-ld.org/)"
                    }
                })
            
            return {"status": "success", "content": response_content}
        except Exception as e:
            logger.error(f"Failed to get HTML: {str(e)}")
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _get_text(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get text content."""
        return self._execute_async(self._async_get_text(action))
    
    async def _async_get_text(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async get text implementation."""
        session_name = action.get("session_name")
        selector = action.get("selector")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        
        # Normalize session name
        session_name = self._normalize_session_name(session_name)
        
        # Auto-create default session if it doesn't exist (for convenience)
        if session_name not in self._sessions:
            logger.info(f"Auto-creating session '{session_name}' for get_text action")
            init_result = self._init_session({
                "type": "init_session",
                "session_name": session_name,
                "description": f"Auto-created session for get_text"
            })
            if init_result.get("status") == "error":
                return init_result
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            # Playwright's text_content() requires a selector, so we use locator() to get text
            # If no selector provided, get text from the entire body
            if selector:
                text = await page.locator(selector).text_content()
            else:
                # Get all text from the page body when no selector is provided
                text = await page.locator('body').text_content()
            text = text or ""
            
            # Truncate text content if it's too large to avoid exceeding model input limits
            MAX_TEXT_SIZE = int(os.getenv("BROWSER_MAX_TEXT_SIZE", "50000"))  # Default: 50KB
            MAX_TEXT_TOKENS = int(os.getenv("BROWSER_MAX_TEXT_TOKENS", "12500"))  # Default: 12500 tokens
            original_size = len(text)
            
            # Check both byte and token limits
            should_truncate = False
            truncation_reason = ""
            
            if original_size > MAX_TEXT_SIZE:
                should_truncate = True
                truncation_reason = f"size ({original_size} bytes > {MAX_TEXT_SIZE} bytes)"
            
            # Check token limit if tiktoken is available
            if TIKTOKEN_AVAILABLE:
                token_count = count_tokens(text)
                if token_count > MAX_TEXT_TOKENS:
                    should_truncate = True
                    if truncation_reason:
                        truncation_reason += f" and tokens ({token_count} > {MAX_TEXT_TOKENS})"
                    else:
                        truncation_reason = f"tokens ({token_count} > {MAX_TEXT_TOKENS})"
            
            # Extract JSON-LD structured data if available
            jsonld_data = await self._extract_jsonld(page)
            
            if should_truncate:
                # Truncate to the smaller of byte or token limit
                truncated_text = text[:MAX_TEXT_SIZE]
                if TIKTOKEN_AVAILABLE:
                    # If token limit is more restrictive, truncate further
                    token_count = count_tokens(truncated_text)
                    if token_count > MAX_TEXT_TOKENS:
                        # Binary search for appropriate truncation point
                        low, high = 0, len(text)
                        while low < high:
                            mid = (low + high) // 2
                            test_text = text[:mid]
                            if count_tokens(test_text) <= MAX_TEXT_TOKENS:
                                low = mid + 1
                            else:
                                high = mid
                        truncated_text = text[:low - 1] if low > 0 else text[:MAX_TEXT_SIZE]
                
                logger.warning(f"Text content exceeded limit ({truncation_reason}), truncating to {len(truncated_text)} bytes")
                warning_msg = f"\n\n[WARNING: Text content was truncated from {original_size} to {len(truncated_text)} bytes to avoid exceeding model input limits. Consider using a more specific selector to extract only relevant content.]"
                
                # Include JSON-LD data if available
                response_content = [{"text": truncated_text + warning_msg}]
                if jsonld_data:
                    response_content.append({
                        "json": {
                            "jsonld": jsonld_data,
                            "note": "JSON-LD structured data extracted from the page (see https://json-ld.org/)"
                        }
                    })
                return {
                    "status": "success",
                    "content": response_content
                }
            
            # Include JSON-LD data if available
            response_content = [{"text": text}]
            if jsonld_data:
                response_content.append({
                    "json": {
                        "jsonld": jsonld_data,
                        "note": "JSON-LD structured data extracted from the page (see https://json-ld.org/)"
                    }
                })
            
            return {"status": "success", "content": response_content}
        except Exception as e:
            logger.error(f"Failed to get text: {str(e)}")
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _click(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Click on an element."""
        return self._execute_async(self._async_click(action))
    
    async def _async_click(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async click implementation."""
        session_name = action.get("session_name")
        selector = action.get("selector")
        
        if not session_name or not selector:
            return {"status": "error", "content": [{"text": "session_name and selector are required"}]}
        
        session_name = self._normalize_session_name(session_name)
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            await page.click(selector)
            return {"status": "success", "content": [{"text": f"Clicked element: {selector}"}]}
        except Exception as e:
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _type(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Type text into an element."""
        return self._execute_async(self._async_type(action))
    
    async def _async_type(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async type implementation."""
        session_name = action.get("session_name")
        selector = action.get("selector")
        text = action.get("text")
        
        if not session_name or not selector or not text:
            return {"status": "error", "content": [{"text": "session_name, selector, and text are required"}]}
        
        session_name = self._normalize_session_name(session_name)
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            await page.fill(selector, text)
            return {"status": "success", "content": [{"text": f"Typed '{text}' into {selector}"}]}
        except Exception as e:
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _get_jsonld(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get JSON-LD structured data from the page."""
        return self._execute_async(self._async_get_jsonld(action))
    
    async def _async_get_jsonld(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async get JSON-LD implementation."""
        session_name = action.get("session_name")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        
        # Normalize session name
        session_name = self._normalize_session_name(session_name)
        
        # Auto-create default session if it doesn't exist (for convenience)
        if session_name not in self._sessions:
            logger.info(f"Auto-creating session '{session_name}' for get_jsonld action")
            init_result = self._init_session({
                "type": "init_session",
                "session_name": session_name,
                "description": f"Auto-created session for get_jsonld"
            })
            if init_result.get("status") == "error":
                return init_result
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            jsonld_data = await self._extract_jsonld(page)
            
            if jsonld_data:
                return {
                    "status": "success",
                    "content": [{
                        "json": {
                            "jsonld": jsonld_data,
                            "count": len(jsonld_data),
                            "note": "JSON-LD structured data extracted from the page (see https://json-ld.org/)"
                        }
                    }]
                }
            else:
                return {
                    "status": "success",
                    "content": [{
                        "text": "No JSON-LD structured data found on this page. JSON-LD is typically found in <script type=\"application/ld+json\"> tags."
                    }]
                }
        except Exception as e:
            logger.error(f"Failed to get JSON-LD: {str(e)}")
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _screenshot(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Take a screenshot."""
        return self._execute_async(self._async_screenshot(action))
    
    async def _async_screenshot(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Async screenshot implementation."""
        session_name = action.get("session_name")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        
        session_name = self._normalize_session_name(session_name)
        
        error_response = self._validate_session(session_name)
        if error_response:
            return error_response
        
        page = self._get_session_page(session_name)
        if not page:
            return {"status": "error", "content": [{"text": "Error: No active page for session"}]}
        
        try:
            screenshot_bytes = await page.screenshot()
            import base64
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            return {"status": "success", "content": [{"text": f"data:image/png;base64,{screenshot_b64}"}]}
        except Exception as e:
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _close(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Close a browser session."""
        session_name = action.get("session_name")
        
        if not session_name:
            return {"status": "error", "content": [{"text": "session_name is required"}]}
        
        session_name = self._normalize_session_name(session_name)
        
        if session_name not in self._sessions:
            return {"status": "error", "content": [{"text": f"Session '{session_name}' not found"}]}
        
        try:
            session = self._sessions[session_name]
            self._execute_async(session.browser.close())
            del self._sessions[session_name]
            return {"status": "success", "content": [{"text": f"Closed session '{session_name}'"}]}
        except Exception as e:
            return {"status": "error", "content": [{"text": f"Error: {str(e)}"}]}
    
    def _list_local_sessions(self) -> Dict[str, Any]:
        """List all sessions created by this instance."""
        sessions_info = []
        for session_name, session in self._sessions.items():
            sessions_info.append({
                "sessionName": session_name,
                "description": session.description,
            })
        
        return {
            "status": "success",
            "content": [{"json": {"sessions": sessions_info, "totalSessions": len(sessions_info)}}],
        }

