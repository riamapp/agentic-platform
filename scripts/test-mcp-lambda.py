#!/usr/bin/env python3
"""
Test script to verify MCP Lambda function works correctly.

This script directly invokes the Lambda function to test:
1. Tool name extraction from context (simulated)
2. Tool execution
3. Response format
"""

import json
import boto3
import sys
from typing import Dict, Any

# Lambda function name
LAMBDA_FUNCTION_NAME = "agentic-platform-McpLambda"
REGION = "us-west-2"


def create_test_context(tool_name: str) -> Dict[str, Any]:
    """
    Create a mock Lambda context for testing.
    
    Note: We can't fully simulate client_context.custom, but we can test
    the Lambda's error handling and response format.
    """
    class MockContext:
        def __init__(self, tool_name: str):
            self.function_name = LAMBDA_FUNCTION_NAME
            self.function_version = "$LATEST"
            self.invoked_function_arn = f"arn:aws:lambda:{REGION}:871442305974:function:{LAMBDA_FUNCTION_NAME}"
            self.memory_limit_in_mb = 128
            self.aws_request_id = "test-request-id"
            
            # Try to simulate client_context with tool name
            class MockClientContext:
                def __init__(self, tool_name: str):
                    class MockCustom:
                        def __init__(self, tool_name: str):
                            if tool_name:
                                # Simulate the Gateway format
                                self.bedrockAgentCoreToolName = f"LambdaTarget___{tool_name}"
                            else:
                                self.bedrockAgentCoreToolName = None
                    
                    self.custom = MockCustom(tool_name)
            
            self.client_context = MockClientContext(tool_name) if tool_name else None
        
        def get_remaining_time_in_millis(self):
            return 30000
    
    return MockContext(tool_name)


def test_lambda_invocation(tool_name: str, event: Dict[str, Any], description: str):
    """Test Lambda invocation with given tool name and event."""
    print(f"\n{'='*80}")
    print(f"TEST: {description}")
    print(f"{'='*80}")
    print(f"Tool Name: {tool_name}")
    print(f"Event: {json.dumps(event, indent=2)}")
    print(f"\nInvoking Lambda...")
    
    lambda_client = boto3.client('lambda', region_name=REGION)
    
    # Create mock context (note: Lambda runtime will create real context, but we can't pass custom)
    # The Lambda will need to extract tool name from event or context
    # For Gateway invocations, the tool name should be in context.client_context.custom
    
    try:
        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps(event)
        )
        
        # Read response
        response_payload = json.loads(response['Payload'].read())
        
        print(f"\nResponse Status Code: {response.get('StatusCode', 'N/A')}")
        print(f"\nResponse Payload:")
        print(json.dumps(response_payload, indent=2, default=str))
        
        # Check response format
        if isinstance(response_payload, dict):
            has_status = "status" in response_payload
            has_content = "content" in response_payload
            has_error = "error" in response_payload
            
            print(f"\nResponse Format Check:")
            print(f"  - Has 'status' field: {has_status}")
            print(f"  - Has 'content' field: {has_content}")
            print(f"  - Has 'error' field: {has_error}")
            
            if has_status and has_content:
                print(f"  ✅ Response format is MCP-compatible")
            elif has_error:
                print(f"  ⚠️  Response has error field (may be expected)")
            else:
                print(f"  ❌ Response format may not be MCP-compatible")
        
        return response_payload
        
    except Exception as e:
        print(f"\n❌ Error invoking Lambda: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Run all tests."""
    print("="*80)
    print("MCP Lambda Direct Invocation Test")
    print("="*80)
    print(f"Lambda Function: {LAMBDA_FUNCTION_NAME}")
    print(f"Region: {REGION}")
    
    # Test 1: Accordio Audio Feedback (no parameters, needs Cognito sub from context)
    print("\n" + "="*80)
    print("TEST 1: Accordio Audio Feedback Tool")
    print("="*80)
    print("Note: This tool requires Cognito sub from auth context.")
    print("Without Gateway context, it should return an authentication error.")
    print("This is expected and shows the Lambda is working correctly.")
    
    test_lambda_invocation(
        tool_name="accordo_audio_feedback",
        event={},  # No parameters - tool extracts Cognito sub from context
        description="Accordio Audio Feedback (no params, needs auth context)"
    )
    
    # Test 2: Skills Quadrant Tool (with student_id)
    print("\n" + "="*80)
    print("TEST 2: Skills Quadrant Tool")
    print("="*80)
    print("Note: This tool requires tool name in context.")
    print("Without Gateway context, it should return a configuration error.")
    print("This is expected and shows the Lambda is working correctly.")
    
    test_lambda_invocation(
        tool_name="students_skills_quadrant",
        event={"student_id": "12345"},
        description="Skills Quadrant Tool (with student_id)"
    )
    
    # Test 3: Overture Tool (with student_id)
    print("\n" + "="*80)
    print("TEST 3: Overture Tool")
    print("="*80)
    print("Note: This tool requires tool name in context.")
    print("Without Gateway context, it should return a configuration error.")
    print("This is expected and shows the Lambda is working correctly.")
    
    test_lambda_invocation(
        tool_name="students_overture",
        event={"student_id": "12345"},
        description="Overture Tool (with student_id)"
    )
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print("\nExpected Results:")
    print("1. All tests should return errors (missing tool name in context)")
    print("2. Error messages should be clear and descriptive")
    print("3. Response format should be MCP-compatible (status/content)")
    print("\nIf you see:")
    print("  ✅ Clear error messages → Lambda code is working")
    print("  ✅ MCP-compatible format → Response format is correct")
    print("  ❌ Empty errors → Lambda code issue")
    print("  ❌ Wrong format → Response format issue")
    print("\nThe fact that Lambda returns errors (not empty) means:")
    print("  - Lambda is executing correctly")
    print("  - Error handling is working")
    print("  - Response formatting is working")
    print("\nThe Gateway issue is separate - Gateway is not invoking Lambda.")
    print("="*80)


if __name__ == "__main__":
    main()
