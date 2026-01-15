#!/bin/bash
# Test script to verify MCP Lambda function works correctly using AWS CLI

set -e

LAMBDA_FUNCTION_NAME="agentic-platform-McpLambda"
REGION="us-west-2"

echo "=================================================================================="
echo "MCP Lambda Direct Invocation Test"
echo "=================================================================================="
echo "Lambda Function: $LAMBDA_FUNCTION_NAME"
echo "Region: $REGION"
echo ""

# Test 1: Accordio Audio Feedback (no parameters, needs Cognito sub from context)
echo "=================================================================================="
echo "TEST 1: Accordio Audio Feedback Tool"
echo "=================================================================================="
echo "Note: This tool requires Cognito sub from auth context."
echo "Without Gateway context, it should return an authentication error."
echo "This is expected and shows the Lambda is working correctly."
echo ""

echo "Invoking Lambda with empty event (no parameters)..."
RESPONSE1=$(aws lambda invoke \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda-test-response-1.json 2>&1)

echo "$RESPONSE1"
echo ""
echo "Response Payload:"
cat /tmp/lambda-test-response-1.json | python3 -m json.tool 2>/dev/null || cat /tmp/lambda-test-response-1.json
echo ""

# Check if response has error (expected)
if grep -q '"error"' /tmp/lambda-test-response-1.json 2>/dev/null; then
    echo "✅ Response contains error field (expected - no auth context)"
else
    echo "⚠️  Response does not contain error field"
fi

if grep -q '"status"' /tmp/lambda-test-response-1.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'status' field"
else
    echo "⚠️  Response missing 'status' field"
fi

if grep -q '"content"' /tmp/lambda-test-response-1.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'content' field"
else
    echo "⚠️  Response missing 'content' field"
fi

echo ""
echo ""

# Test 2: Skills Quadrant Tool (with student_id)
echo "=================================================================================="
echo "TEST 2: Skills Quadrant Tool"
echo "=================================================================================="
echo "Note: This tool requires tool name in context."
echo "Without Gateway context, it should return a configuration error."
echo "This is expected and shows the Lambda is working correctly."
echo ""

echo "Invoking Lambda with student_id parameter..."
RESPONSE2=$(aws lambda invoke \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"student_id": "12345"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda-test-response-2.json 2>&1)

echo "$RESPONSE2"
echo ""
echo "Response Payload:"
cat /tmp/lambda-test-response-2.json | python3 -m json.tool 2>/dev/null || cat /tmp/lambda-test-response-2.json
echo ""

# Check if response has error (expected)
if grep -q '"error"' /tmp/lambda-test-response-2.json 2>/dev/null; then
    echo "✅ Response contains error field (expected - no tool name in context)"
else
    echo "⚠️  Response does not contain error field"
fi

if grep -q '"status"' /tmp/lambda-test-response-2.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'status' field"
else
    echo "⚠️  Response missing 'status' field"
fi

if grep -q '"content"' /tmp/lambda-test-response-2.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'content' field"
else
    echo "⚠️  Response missing 'content' field"
fi

echo ""
echo ""

# Test 3: Overture Tool (with student_id)
echo "=================================================================================="
echo "TEST 3: Overture Tool"
echo "=================================================================================="
echo "Note: This tool requires tool name in context."
echo "Without Gateway context, it should return a configuration error."
echo "This is expected and shows the Lambda is working correctly."
echo ""

echo "Invoking Lambda with student_id parameter..."
RESPONSE3=$(aws lambda invoke \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"student_id": "12345"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda-test-response-3.json 2>&1)

echo "$RESPONSE3"
echo ""
echo "Response Payload:"
cat /tmp/lambda-test-response-3.json | python3 -m json.tool 2>/dev/null || cat /tmp/lambda-test-response-3.json
echo ""

# Check if response has error (expected)
if grep -q '"error"' /tmp/lambda-test-response-3.json 2>/dev/null; then
    echo "✅ Response contains error field (expected - no tool name in context)"
else
    echo "⚠️  Response does not contain error field"
fi

if grep -q '"status"' /tmp/lambda-test-response-3.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'status' field"
else
    echo "⚠️  Response missing 'status' field"
fi

if grep -q '"content"' /tmp/lambda-test-response-3.json 2>/dev/null; then
    echo "✅ Response has MCP-compatible 'content' field"
else
    echo "⚠️  Response missing 'content' field"
fi

echo ""
echo ""

# Summary
echo "=================================================================================="
echo "TEST SUMMARY"
echo "=================================================================================="
echo ""
echo "Expected Results:"
echo "1. All tests should return errors (missing tool name in context)"
echo "2. Error messages should be clear and descriptive (not empty)"
echo "3. Response format should be MCP-compatible (status/content fields)"
echo ""
echo "If you see:"
echo "  ✅ Clear error messages → Lambda code is working correctly"
echo "  ✅ MCP-compatible format → Response format is correct"
echo "  ❌ Empty errors → Lambda code issue"
echo "  ❌ Wrong format → Response format issue"
echo ""
echo "The fact that Lambda returns errors (not empty) means:"
echo "  - Lambda is executing correctly"
echo "  - Error handling is working"
echo "  - Response formatting is working"
echo ""
echo "The Gateway issue is separate - Gateway is not invoking Lambda."
echo "=================================================================================="
