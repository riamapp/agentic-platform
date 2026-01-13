"""
Native Code Interpreter tool implementation using Bedrock AgentCore directly.

This uses the same Bedrock AgentCore CodeInterpreter service as Strands,
but accessed directly via bedrock-agentcore package clients.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter as BedrockAgentCoreCodeInterpreterClient

logger = logging.getLogger(__name__)

# Module-level session cache - persists across object instances
_session_mapping: Dict[str, str] = {}  # user_session_name -> aws_session_id


@dataclass
class SessionInfo:
    """Information about a code interpreter session."""
    session_id: str  # AWS CI session ID
    description: str
    client: BedrockAgentCoreCodeInterpreterClient


class CodeInterpreterTool:
    """
    Native Code Interpreter tool using Bedrock AgentCore CodeInterpreter service.
    
    This is a simplified version that uses the bedrock-agentcore package directly,
    without the Strands wrapper layer.
    """
    
    def __init__(
        self,
        region: Optional[str] = None,
        identifier: Optional[str] = None,
        session_name: Optional[str] = None,
        auto_create: bool = True,
        persist_sessions: bool = True,
    ):
        """
        Initialize the Code Interpreter tool.
        
        Args:
            region: AWS region for the code interpreter service
            identifier: Code interpreter identifier (defaults to "aws.codeinterpreter.v1")
            session_name: Session identifier for tracking and reconnection
            auto_create: Automatically create sessions if they don't exist
            persist_sessions: Prevent session cleanup on object destruction
        """
        self.region = region or "us-west-2"
        self.identifier = identifier or "aws.codeinterpreter.v1"
        self.auto_create = auto_create
        self.persist_sessions = persist_sessions
        
        if session_name is None:
            self.default_session = f"session-{uuid.uuid4().hex[:12]}"
        else:
            self.default_session = session_name
        
        self._sessions: Dict[str, SessionInfo] = {}
        
        logger.info(
            f"Initialized CodeInterpreterTool with session='{self.default_session}', "
            f"identifier='{self.identifier}', auto_create={auto_create}, "
            f"persist_sessions={persist_sessions}"
        )
    
    def code_interpreter(self, code_interpreter_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for code interpreter tool.
        
        Handles all code interpreter actions: initSession, executeCode, etc.
        """
        if not isinstance(code_interpreter_input, dict):
            return {"status": "error", "content": [{"text": "Invalid input: must be a dictionary"}]}
        
        action = code_interpreter_input.get("action", {})
        if not isinstance(action, dict):
            return {"status": "error", "content": [{"text": "Invalid action: must be a dictionary"}]}
        
        action_type = action.get("type")
        
        if action_type == "initSession":
            return self._init_session(action)
        elif action_type == "executeCode":
            return self._execute_code(action)
        elif action_type == "executeCommand":
            return self._execute_command(action)
        elif action_type == "readFiles":
            return self._read_files(action)
        elif action_type == "listFiles":
            return self._list_files(action)
        elif action_type == "writeFiles":
            return self._write_files(action)
        elif action_type == "removeFiles":
            return self._remove_files(action)
        elif action_type == "listLocalSessions":
            return self._list_local_sessions()
        else:
            return {"status": "error", "content": [{"text": f"Unknown action type: {action_type}"}]}
    
    def _init_session(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize a new code interpreter session."""
        session_name = action.get("session_name")
        description = action.get("description", "Code interpreter session")
        
        # Auto-generate session_name if not provided
        if not session_name:
            session_name = f"session-{uuid.uuid4().hex[:12]}"
            logger.info(f"Auto-generated session_name: {session_name} for initSession action")
        
        # Check if session already exists
        if session_name in self._sessions:
            return {"status": "error", "content": [{"text": f"Session '{session_name}' already exists"}]}
        
        if session_name in _session_mapping:
            error_msg = f"Session '{session_name}' is already in use by another instance."
            logger.error(error_msg)
            return {"status": "error", "content": [{"text": error_msg}]}
        
        try:
            # Create new sandbox client
            client = BedrockAgentCoreCodeInterpreterClient(region=self.region)
            
            # Start session with identifier and name
            client.start(identifier=self.identifier, name=session_name)
            
            aws_session_id = client.session_id
            
            # Store mapping in module-level cache
            _session_mapping[session_name] = aws_session_id
            
            # Store session info locally
            self._sessions[session_name] = SessionInfo(
                session_id=aws_session_id,
                description=description,
                client=client
            )
            
            logger.info(f"Initialized session: {session_name} (AWS ID: {aws_session_id})")
            
            return {
                "status": "success",
                "content": [{
                    "json": {
                        "sessionName": session_name,
                        "description": description,
                        "sessionId": aws_session_id,
                    }
                }],
            }
        except Exception as e:
            logger.error(f"Failed to initialize session '{session_name}': {str(e)}")
            return {
                "status": "error",
                "content": [{"text": f"Failed to initialize session '{session_name}': {str(e)}"}],
            }
    
    def _ensure_session(self, session_name: Optional[str]) -> tuple[str, Optional[Dict[str, Any]]]:
        """Ensure a session exists, creating if needed."""
        target_session = session_name if session_name else self.default_session
        
        # Check local cache first
        if target_session in self._sessions:
            return target_session, None
        
        # Check module-level cache for AWS session ID
        aws_session_id = _session_mapping.get(target_session)
        
        if aws_session_id:
            # Found in module cache - try to reconnect
            try:
                client = BedrockAgentCoreCodeInterpreterClient(region=self.region)
                session_info = client.get_session(interpreter_id=self.identifier, session_id=aws_session_id)
                
                if session_info.get("status") == "READY":
                    client.identifier = self.identifier
                    client.session_id = aws_session_id
                    
                    self._sessions[target_session] = SessionInfo(
                        session_id=aws_session_id,
                        description="Reconnected via module cache",
                        client=client
                    )
                    
                    logger.info(f"Reconnected to existing session: {target_session}")
                    return target_session, None
                else:
                    logger.warning(f"Session {target_session} not READY, removing from cache")
                    del _session_mapping[target_session]
            except Exception as e:
                logger.debug(f"Session reconnection failed: {e}")
                if target_session in _session_mapping:
                    del _session_mapping[target_session]
        
        # Session not found - create new if auto_create enabled
        if self.auto_create:
            logger.info(f"Auto-creating session: {target_session}")
            
            init_action = {
                "type": "initSession",
                "session_name": target_session,
                "description": "Auto-initialized session"
            }
            result = self._init_session(init_action)
            
            if result.get("status") != "success":
                return target_session, result
            
            logger.info(f"Successfully auto-created session: {target_session}")
            return target_session, None
        
        # auto_create=False and session doesn't exist
        error_msg = f"Session '{target_session}' not found. Create it first using initSession."
        return target_session, {"status": "error", "content": [{"text": error_msg}]}
    
    def _execute_code(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute code in a session."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        code = action.get("code")
        language = action.get("language", "python")
        clear_context = action.get("clearContext", False)
        
        if not code:
            return {"status": "error", "content": [{"text": "code is required"}]}
        
        try:
            params = {
                "code": code,
                "language": language,
                "clearContext": clear_context
            }
            response = self._sessions[session_name].client.invoke("executeCode", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to execute code: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to execute code: {str(e)}"}]}
    
    def _execute_command(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command in a session."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        command = action.get("command")
        if not command:
            return {"status": "error", "content": [{"text": "command is required"}]}
        
        try:
            params = {"command": command}
            response = self._sessions[session_name].client.invoke("executeCommand", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to execute command: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to execute command: {str(e)}"}]}
    
    def _read_files(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Read files from a session."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        paths = action.get("paths", [])
        if not paths:
            return {"status": "error", "content": [{"text": "paths is required"}]}
        
        try:
            params = {"paths": paths}
            response = self._sessions[session_name].client.invoke("readFiles", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to read files: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to read files: {str(e)}"}]}
    
    def _list_files(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """List files in a session directory."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        path = action.get("path", ".")
        
        try:
            params = {"path": path}
            response = self._sessions[session_name].client.invoke("listFiles", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to list files: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to list files: {str(e)}"}]}
    
    def _write_files(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Write files to a session."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        content = action.get("content", [])
        if not content:
            return {"status": "error", "content": [{"text": "content is required"}]}
        
        try:
            content_dicts = []
            for item in content:
                if isinstance(item, dict):
                    content_dicts.append({"path": item.get("path"), "text": item.get("text")})
                else:
                    # Assume it's a file content object with path and text attributes
                    content_dicts.append({"path": getattr(item, "path", ""), "text": getattr(item, "text", "")})
            
            params = {"content": content_dicts}
            response = self._sessions[session_name].client.invoke("writeFiles", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to write files: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to write files: {str(e)}"}]}
    
    def _remove_files(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Remove files from a session."""
        session_name, error = self._ensure_session(action.get("session_name"))
        if error:
            return error
        
        paths = action.get("paths", [])
        if not paths:
            return {"status": "error", "content": [{"text": "paths is required"}]}
        
        try:
            params = {"paths": paths}
            response = self._sessions[session_name].client.invoke("removeFiles", params)
            return self._create_tool_result(response)
        except Exception as e:
            logger.error(f"Failed to remove files: {str(e)}")
            return {"status": "error", "content": [{"text": f"Failed to remove files: {str(e)}"}]}
    
    def _list_local_sessions(self) -> Dict[str, Any]:
        """List all sessions created by this instance."""
        sessions_info = []
        for name, info in self._sessions.items():
            sessions_info.append({
                "sessionName": name,
                "description": info.description,
                "sessionId": info.session_id,
            })
        
        return {
            "status": "success",
            "content": [{"json": {"sessions": sessions_info, "totalSessions": len(sessions_info)}}],
        }
    
    def _create_tool_result(self, response: Any) -> Dict[str, Any]:
        """Create tool result from response."""
        if isinstance(response, dict):
            if "stream" in response:
                event_stream = response["stream"]
                for event in event_stream:
                    if "result" in event:
                        result = event["result"]
                        is_error = response.get("isError", False)
                        return {
                            "status": "success" if not is_error else "error",
                            "content": [{"text": str(result.get("content", ""))}],
                        }
                return {"status": "error", "content": [{"text": f"Failed to create tool result: {str(response)}"}]}
            return response
        
        return {"status": "success", "content": [{"text": str(response)}]}

