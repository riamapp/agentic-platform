#!/bin/bash
# Script to check MCP Lambda logs and identify issues with accordo_audio_feedback tool

set -e

# Get app name from terraform.tfvars or use default
APP_NAME=${APP_NAME:-$(grep -E '^app_name\s*=' terraform/terraform.tfvars 2>/dev/null | cut -d'"' -f2 || echo "")}

if [ -z "$APP_NAME" ]; then
    echo "Error: APP_NAME not set. Please set it as an environment variable or ensure terraform/terraform.tfvars exists."
    echo "Usage: APP_NAME=your-app-name ./scripts/check-mcp-logs.sh"
    exit 1
fi

FUNCTION_NAME="${APP_NAME}-McpLambda"
LOG_GROUP="/aws/lambda/${FUNCTION_NAME}"

echo "=========================================="
echo "Checking logs for: ${FUNCTION_NAME}"
echo "=========================================="
echo ""

# Check if log group exists
if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --query "logGroups[?logGroupName=='$LOG_GROUP']" --output text | grep -q "$LOG_GROUP"; then
    echo "Warning: Log group $LOG_GROUP not found. The Lambda may not have been invoked yet."
    exit 1
fi

# Get logs from last 30 minutes
START_TIME=$(($(date +%s) - 30 * 60))000
END_TIME=$(date +%s)000

echo "Fetching logs from last 30 minutes..."
echo ""

# Get all log events
LOG_EVENTS=$(aws logs filter-log-events \
    --log-group-name "$LOG_GROUP" \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --query 'events[*].[timestamp,message]' \
    --output text 2>/dev/null)

if [ -z "$LOG_EVENTS" ]; then
    echo "No log events found in the last 30 minutes."
    echo "The Lambda function may not have been invoked recently."
    exit 0
fi

echo "=========================================="
echo "ACCORDO AUDIO FEEDBACK TOOL LOGS"
echo "=========================================="
echo ""

# Filter for accordo_audio_feedback related logs
echo "$LOG_EVENTS" | grep -i "accordo" | while IFS=$'\t' read -r timestamp message; do
    date_str=$(date -r $((timestamp / 1000)) '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$timestamp")
    echo "[$date_str] $message"
done

echo ""
echo "=========================================="
echo "COGNITO SUB EXTRACTION ATTEMPTS"
echo "=========================================="
echo ""

echo "$LOG_EVENTS" | grep -iE "(cognito|sub|extract|authentication)" | while IFS=$'\t' read -r timestamp message; do
    date_str=$(date -r $((timestamp / 1000)) '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$timestamp")
    echo "[$date_str] $message"
done

echo ""
echo "=========================================="
echo "ERRORS AND WARNINGS"
echo "=========================================="
echo ""

echo "$LOG_EVENTS" | grep -iE "(error|exception|traceback|failed)" | while IFS=$'\t' read -r timestamp message; do
    date_str=$(date -r $((timestamp / 1000)) '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$timestamp")
    echo "[$date_str] $message"
done

echo ""
echo "=========================================="
echo "EVENT STRUCTURE (First accordo call)"
echo "=========================================="
echo ""

echo "$LOG_EVENTS" | grep -A 5 "accordo_audio_feedback tool called" | head -20 | while IFS=$'\t' read -r timestamp message; do
    date_str=$(date -r $((timestamp / 1000)) '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$timestamp")
    echo "[$date_str] $message"
done

echo ""
echo "=========================================="
echo "RECOMMENDATIONS"
echo "=========================================="
echo ""
echo "Look for:"
echo "1. 'Extracted Cognito sub from...' - Should show which method worked"
echo "2. 'Could not extract Cognito sub' - Indicates auth context issue"
echo "3. 'Tool returned error: ...' - Shows what error the tool returned"
echo "4. Event structure - Shows what data is available in the event"
echo ""
