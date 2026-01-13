#!/bin/bash
# Script to build all Lambda packages and output a hash
# This is used by Terraform data.external to ensure builds happen during plan phase
# Reads query JSON from stdin and outputs result JSON to stdout

set -e

cd "$(dirname "$0")/.."

# Read query from stdin (Terraform passes this as JSON)
QUERY_JSON=""
if [ ! -t 0 ]; then
  QUERY_JSON=$(cat)
fi

# Build all Lambda packages (output to stderr so it doesn't interfere with JSON output)
make mcp-lambda-zip >&2
make api-lambda-zip >&2
make job-submit-lambda-zip >&2
make job-worker-lambda-zip >&2
make job-get-lambda-zip >&2
make job-cancel-lambda-zip >&2
make websocket-connect-lambda-zip >&2
make websocket-disconnect-lambda-zip >&2

# Calculate a hash of all zip files to ensure they're built
if [ -f "build/mcp_lambda.zip" ] && \
   [ -f "build/api_lambda.zip" ] && \
   [ -f "build/job_submit_lambda.zip" ] && \
   [ -f "build/job_worker_lambda.zip" ] && \
   [ -f "build/job_get_lambda.zip" ] && \
   [ -f "build/job_cancel_lambda.zip" ] && \
   [ -f "build/websocket_connect_lambda.zip" ] && \
   [ -f "build/websocket_disconnect_lambda.zip" ]; then
  # Output JSON with hash (using combined hash of all files)
  HASH=$(cat build/*.zip | sha256sum | cut -d' ' -f1)
  echo "{\"hash\": \"$HASH\", \"status\": \"success\"}"
else
  echo "{\"hash\": \"\", \"status\": \"error\"}" >&2
  exit 1
fi
