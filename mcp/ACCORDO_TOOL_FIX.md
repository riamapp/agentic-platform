# Accordo Audio Feedback Tool - Fix Summary

## Issue
The tool was returning empty error messages when called.

## Root Causes Identified

1. **userId validation blocking accordo tool**: The handler was validating `userId` before routing, which blocked the accordo tool even though it doesn't need `userId` (it uses Cognito sub from auth context).

2. **Error format incompatibility**: Errors weren't being formatted in a way the MCP client could parse.

3. **Cognito sub extraction**: The Gateway with CUSTOM_JWT authorizer might not be automatically passing JWT claims to the Lambda.

## Fixes Applied

1. ✅ Removed userId validation for accordo_audio_feedback tool
2. ✅ Enhanced error formatting with multiple formats for compatibility
3. ✅ Added comprehensive logging for debugging
4. ✅ Improved Cognito sub extraction with multiple fallback methods
5. ✅ Ensured all error responses include `status`, `content`, `error`, and `message` fields

## Next Steps

1. **Deploy the updated Lambda**:
   ```bash
   make mcp-lambda-zip
   # Then apply Terraform
   ```

2. **Test the tool** - It should now:
   - Be callable without userId
   - Return clear error messages if Cognito sub extraction fails
   - Log detailed information for debugging

3. **If Cognito sub extraction still fails**, check:
   - Gateway configuration - ensure JWT claims are being passed to Lambda
   - CloudWatch logs for the Lambda to see what data is available
   - Gateway logs to see if authentication is working

## Important Note

For Bedrock AgentCore Gateway with CUSTOM_JWT authorizer, the Gateway validates the JWT but **may not automatically pass the claims to the Lambda**. If Cognito sub extraction continues to fail, you may need to:

1. Configure the Gateway to pass JWT claims in the request context
2. Access claims from the Gateway's request headers
3. Use a different authorizer type that automatically passes claims

Check the CloudWatch logs after deployment to see what data is actually available in the event and context.
