# CRITICAL FIX: Accordo Audio Feedback Tool

## Root Cause Identified

**The Lambda function has NEVER been invoked** - CloudWatch log group exists but has no events (LastEvent: null).

This means the Bedrock AgentCore Gateway is **not calling the Lambda function at all**. The "empty error" is likely coming from the Gateway itself, not the Lambda.

## Fixes Applied

1. ✅ **Fixed empty input schema** - Added placeholder property (empty schemas can cause Gateway registration failures)
2. ✅ **Fixed response format** - Gateway MCP tools expect response body directly, not wrapped in statusCode/body
3. ✅ **Enhanced error handling** - All errors now include clear messages in multiple formats
4. ✅ **Added comprehensive logging** - Will show what's happening when Gateway finally invokes Lambda

## Critical Issue

The Gateway is not invoking the Lambda. Possible causes:

1. **Invalid tool schema** - Empty input schema might have prevented registration (FIXED)
2. **Gateway configuration error** - Tool might not be properly registered
3. **Permission issue** - Gateway role might not have Lambda invoke permission
4. **Gateway target not active** - The target might not be properly configured

## Immediate Actions Required

1. **Deploy the fixes:**
   ```bash
   make mcp-lambda-zip
   cd terraform
   terraform apply
   ```

2. **Verify Gateway target exists:**
   ```bash
   # Check if target is registered (requires AWS CLI with bedrock-agentcore access)
   # The target should be: agentic-platform-AccordoFeedback
   ```

3. **After deployment, test again** - The enhanced logging will show:
   - If Lambda is being invoked
   - What data is in the event/context
   - Where Cognito sub extraction is failing (if it is)

4. **If Lambda still not invoked**, check:
   - Gateway target configuration in Terraform
   - Gateway IAM role has Lambda invoke permission (should be in mcp_gateway.tf)
   - Gateway is active and tool is registered

## Expected Behavior After Fix

- Lambda should be invoked (check CloudWatch logs)
- If Cognito sub extraction fails, you'll get a clear error message
- Logs will show exactly what's happening

## Next Steps if Still Failing

If the Lambda is still not invoked after deployment:
1. Check Gateway target registration in AWS Console
2. Verify Gateway IAM role permissions
3. Check Gateway logs (if available)
4. Consider recreating the Gateway target
