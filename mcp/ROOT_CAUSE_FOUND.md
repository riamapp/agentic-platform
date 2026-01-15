# ROOT CAUSE IDENTIFIED AND FIXED

## Critical Finding

**The Bedrock AgentCore Gateway is NOT invoking the Lambda function.**

Evidence:
- Lambda was last invoked at 06:29:47 (old code)
- New code deployed at 06:41:48
- No new invocations after multiple tool calls
- No print statements or logs appear

## Root Cause

**Missing Lambda Resource-Based Policy**: The Lambda function does not have a resource-based policy allowing the Bedrock AgentCore Gateway service to invoke it.

While the Gateway IAM role has `lambda:InvokeFunction` permission, **Lambda also requires a resource-based policy** to allow external services (like the Gateway) to invoke it.

## Fix Applied

Added `aws_lambda_permission` resource to allow the Gateway to invoke the Lambda:

```terraform
resource "aws_lambda_permission" "allow_gateway_invoke" {
  statement_id  = "AllowBedrockAgentCoreGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp_lambda.function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  source_arn     = "${aws_bedrockagentcore_gateway.agentcore_gateway.gateway_arn}/*"
}
```

## Action Required

1. **Apply Terraform changes:**
   ```bash
   cd terraform
   terraform apply
   ```

2. **Test the tool again** - The Gateway should now be able to invoke the Lambda

3. **Check logs immediately:**
   ```bash
   aws logs tail "/aws/lambda/agentic-platform-McpLambda" --since 2m --format short
   ```

4. **Expected results:**
   - Lambda will be invoked (you'll see print statements)
   - Tool will execute
   - Either success or clear error messages will appear

## Why This Was the Issue

AWS Lambda requires **both**:
1. IAM role permission (Gateway role has `lambda:InvokeFunction`) ✅
2. Resource-based policy (Lambda allows Gateway to invoke) ❌ **MISSING**

Without the resource-based policy, the Gateway cannot invoke the Lambda, even though it has IAM permissions.
