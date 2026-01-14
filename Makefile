# Build artifacts directory
BUILD_DIR = build

# Lambda Package Build Targets - zip files go in build/ directory
MCP_BUILD_DIR = mcp/lambda_package
JOB_SUBMIT_BUILD_DIR = api/jobs/submit_package
JOB_WORKER_BUILD_DIR = api/jobs/worker_package
JOB_GET_BUILD_DIR = api/jobs/get_package
JOB_CANCEL_BUILD_DIR = api/jobs/cancel_package
WEBSOCKET_CONNECT_BUILD_DIR = api/websocket/connect_package
WEBSOCKET_DISCONNECT_BUILD_DIR = api/websocket/disconnect_package
FEEDBACK_BUILD_DIR = api/feedback/feedback_package
MUSIC_ANALYSIS_BUILD_DIR = api/music_analysis/music_analysis_package

# Zip file targets
MCP_LAMBDA_ZIP = $(BUILD_DIR)/mcp_lambda.zip
JOB_SUBMIT_LAMBDA_ZIP = $(BUILD_DIR)/job_submit_lambda.zip
JOB_WORKER_LAMBDA_ZIP = $(BUILD_DIR)/job_worker_lambda.zip
JOB_GET_LAMBDA_ZIP = $(BUILD_DIR)/job_get_lambda.zip
JOB_CANCEL_LAMBDA_ZIP = $(BUILD_DIR)/job_cancel_lambda.zip
WEBSOCKET_CONNECT_LAMBDA_ZIP = $(BUILD_DIR)/websocket_connect_lambda.zip
WEBSOCKET_DISCONNECT_LAMBDA_ZIP = $(BUILD_DIR)/websocket_disconnect_lambda.zip
FEEDBACK_LAMBDA_ZIP = $(BUILD_DIR)/feedback_lambda.zip

.PHONY: clean help all-lambda-zip mcp-lambda-zip job-submit-lambda-zip job-worker-lambda-zip job-get-lambda-zip job-cancel-lambda-zip websocket-connect-lambda-zip websocket-disconnect-lambda-zip feedback-lambda-zip
MUSIC_ANALYSIS_LAMBDA_ZIP = $(BUILD_DIR)/music_analysis_lambda.zip

.PHONY: clean help all-lambda-zip mcp-lambda-zip job-submit-lambda-zip job-worker-lambda-zip job-get-lambda-zip job-cancel-lambda-zip websocket-connect-lambda-zip websocket-disconnect-lambda-zip music-analysis-lambda-zip

help:
	@echo "Available targets:"
	@echo "  mcp-lambda-zip              - Build MCP Lambda package"
	@echo "  job-submit-lambda-zip       - Build Job Submit Lambda package"
	@echo "  job-worker-lambda-zip       - Build Job Worker Lambda package"
	@echo "  job-get-lambda-zip          - Build Job Get Lambda package"
	@echo "  job-cancel-lambda-zip       - Build Job Cancel Lambda package"
	@echo "  websocket-connect-lambda-zip    - Build WebSocket Connect Lambda package"
	@echo "  websocket-disconnect-lambda-zip - Build WebSocket Disconnect Lambda package"
	@echo "  feedback-lambda-zip         - Build Feedback Lambda package"
	@echo "  music-analysis-lambda-zip       - Build Music Analysis Lambda package"
	@echo "  lambda-zip                  - Build all Lambda packages (legacy)"
	@echo "  all-lambda-zip              - Build all Lambda packages in parallel"
	@echo "  clean                       - Remove all build artifacts"

# Build all Lambda packages in parallel
all-lambda-zip: $(MCP_LAMBDA_ZIP) $(JOB_SUBMIT_LAMBDA_ZIP) $(JOB_WORKER_LAMBDA_ZIP) $(JOB_GET_LAMBDA_ZIP) $(JOB_CANCEL_LAMBDA_ZIP) $(WEBSOCKET_CONNECT_LAMBDA_ZIP) $(WEBSOCKET_DISCONNECT_LAMBDA_ZIP) $(FEEDBACK_LAMBDA_ZIP)
all-lambda-zip: $(MCP_LAMBDA_ZIP) $(JOB_SUBMIT_LAMBDA_ZIP) $(JOB_WORKER_LAMBDA_ZIP) $(JOB_GET_LAMBDA_ZIP) $(JOB_CANCEL_LAMBDA_ZIP) $(WEBSOCKET_CONNECT_LAMBDA_ZIP) $(WEBSOCKET_DISCONNECT_LAMBDA_ZIP) $(MUSIC_ANALYSIS_LAMBDA_ZIP)

# Phony aliases for backward compatibility (null_resource provisioners use these)
mcp-lambda-zip: $(MCP_LAMBDA_ZIP)
job-submit-lambda-zip: $(JOB_SUBMIT_LAMBDA_ZIP)
job-worker-lambda-zip: $(JOB_WORKER_LAMBDA_ZIP)
job-get-lambda-zip: $(JOB_GET_LAMBDA_ZIP)
job-cancel-lambda-zip: $(JOB_CANCEL_LAMBDA_ZIP)
websocket-connect-lambda-zip: $(WEBSOCKET_CONNECT_LAMBDA_ZIP)
websocket-disconnect-lambda-zip: $(WEBSOCKET_DISCONNECT_LAMBDA_ZIP)
feedback-lambda-zip: $(FEEDBACK_LAMBDA_ZIP)
music-analysis-lambda-zip: $(MUSIC_ANALYSIS_LAMBDA_ZIP)

# Build MCP Lambda package
$(MCP_LAMBDA_ZIP): mcp/lambda/handler.py mcp/lambda/requirements.txt mcp/lambda/students_overture.py mcp/lambda/students_skills_quadrant.py mcp/lambda/accordo_audio_feedback.py
	@echo "Building MCP Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(MCP_BUILD_DIR) $(MCP_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(MCP_BUILD_DIR); \
		    cp mcp/lambda/handler.py $(MCP_BUILD_DIR)/; \
		    cp mcp/lambda/students_overture.py $(MCP_BUILD_DIR)/; \
		    cp mcp/lambda/students_skills_quadrant.py $(MCP_BUILD_DIR)/; \
		    cp mcp/lambda/accordo_audio_feedback.py $(MCP_BUILD_DIR)/; \
		    pip install -r mcp/lambda/requirements.txt -t $(MCP_BUILD_DIR) --upgrade --quiet; \
		    find $(MCP_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(MCP_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(MCP_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(MCP_BUILD_DIR) && zip -q -r /var/task/$(MCP_LAMBDA_ZIP) ."

# Build Job Submit Lambda package
$(JOB_SUBMIT_LAMBDA_ZIP): api/jobs/submit_handler.py api/jobs/requirements.txt
	@echo "Building Job Submit Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(JOB_SUBMIT_BUILD_DIR) $(JOB_SUBMIT_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(JOB_SUBMIT_BUILD_DIR); \
		    cp api/jobs/submit_handler.py $(JOB_SUBMIT_BUILD_DIR)/; \
		    pip install -r api/jobs/requirements.txt -t $(JOB_SUBMIT_BUILD_DIR) --upgrade --quiet; \
		    find $(JOB_SUBMIT_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_SUBMIT_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_SUBMIT_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(JOB_SUBMIT_BUILD_DIR) && zip -q -r /var/task/$(JOB_SUBMIT_LAMBDA_ZIP) ."

# Build Job Worker Lambda package
$(JOB_WORKER_LAMBDA_ZIP): api/jobs/worker_handler.py api/jobs/requirements.txt api/utils/cost_calculator.py api/utils/__init__.py
	@echo "Building Job Worker Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(JOB_WORKER_BUILD_DIR) $(JOB_WORKER_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(JOB_WORKER_BUILD_DIR); \
		    cp api/jobs/worker_handler.py $(JOB_WORKER_BUILD_DIR)/; \
		    mkdir -p $(JOB_WORKER_BUILD_DIR)/utils; \
		    cp api/utils/__init__.py $(JOB_WORKER_BUILD_DIR)/utils/; \
		    cp api/utils/cost_calculator.py $(JOB_WORKER_BUILD_DIR)/utils/; \
		    pip install -r api/jobs/requirements.txt -t $(JOB_WORKER_BUILD_DIR) --upgrade --quiet; \
		    find $(JOB_WORKER_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_WORKER_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_WORKER_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(JOB_WORKER_BUILD_DIR) && zip -q -r /var/task/$(JOB_WORKER_LAMBDA_ZIP) ."

# Build Job Get Lambda package
$(JOB_GET_LAMBDA_ZIP): api/jobs/get_handler.py api/jobs/requirements.txt
	@echo "Building Job Get Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(JOB_GET_BUILD_DIR) $(JOB_GET_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(JOB_GET_BUILD_DIR); \
		    cp api/jobs/get_handler.py $(JOB_GET_BUILD_DIR)/; \
		    pip install -r api/jobs/requirements.txt -t $(JOB_GET_BUILD_DIR) --upgrade --quiet; \
		    find $(JOB_GET_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_GET_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_GET_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(JOB_GET_BUILD_DIR) && zip -q -r /var/task/$(JOB_GET_LAMBDA_ZIP) ."

# Build Job Cancel Lambda package
$(JOB_CANCEL_LAMBDA_ZIP): api/jobs/cancel_handler.py api/jobs/requirements.txt
	@echo "Building Job Cancel Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(JOB_CANCEL_BUILD_DIR) $(JOB_CANCEL_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(JOB_CANCEL_BUILD_DIR); \
		    cp api/jobs/cancel_handler.py $(JOB_CANCEL_BUILD_DIR)/; \
		    pip install -r api/jobs/requirements.txt -t $(JOB_CANCEL_BUILD_DIR) --upgrade --quiet; \
		    find $(JOB_CANCEL_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_CANCEL_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(JOB_CANCEL_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(JOB_CANCEL_BUILD_DIR) && zip -q -r /var/task/$(JOB_CANCEL_LAMBDA_ZIP) ."

# Build WebSocket Connect Lambda package
$(WEBSOCKET_CONNECT_LAMBDA_ZIP): api/websocket/connect_handler.py api/websocket/requirements.txt
	@echo "Building WebSocket Connect Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(WEBSOCKET_CONNECT_BUILD_DIR) $(WEBSOCKET_CONNECT_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(WEBSOCKET_CONNECT_BUILD_DIR); \
		    cp api/websocket/connect_handler.py $(WEBSOCKET_CONNECT_BUILD_DIR)/; \
		    pip install -r api/websocket/requirements.txt -t $(WEBSOCKET_CONNECT_BUILD_DIR) --upgrade --quiet 2>/dev/null || true; \
		    find $(WEBSOCKET_CONNECT_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(WEBSOCKET_CONNECT_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(WEBSOCKET_CONNECT_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(WEBSOCKET_CONNECT_BUILD_DIR) && zip -q -r /var/task/$(WEBSOCKET_CONNECT_LAMBDA_ZIP) ."

# Build WebSocket Disconnect Lambda package
$(WEBSOCKET_DISCONNECT_LAMBDA_ZIP): api/websocket/disconnect_handler.py api/websocket/requirements.txt
	@echo "Building WebSocket Disconnect Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(WEBSOCKET_DISCONNECT_BUILD_DIR) $(WEBSOCKET_DISCONNECT_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(WEBSOCKET_DISCONNECT_BUILD_DIR); \
		    cp api/websocket/disconnect_handler.py $(WEBSOCKET_DISCONNECT_BUILD_DIR)/; \
		    pip install -r api/websocket/requirements.txt -t $(WEBSOCKET_DISCONNECT_BUILD_DIR) --upgrade --quiet 2>/dev/null || true; \
		    find $(WEBSOCKET_DISCONNECT_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(WEBSOCKET_DISCONNECT_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(WEBSOCKET_DISCONNECT_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(WEBSOCKET_DISCONNECT_BUILD_DIR) && zip -q -r /var/task/$(WEBSOCKET_DISCONNECT_LAMBDA_ZIP) ."

# Build Feedback Lambda package
$(FEEDBACK_LAMBDA_ZIP): api/feedback/feedback_handler.py api/feedback/requirements.txt
	@echo "Building Feedback Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(FEEDBACK_BUILD_DIR) $(FEEDBACK_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(FEEDBACK_BUILD_DIR); \
		    cp api/feedback/feedback_handler.py $(FEEDBACK_BUILD_DIR)/; \
		    pip install -r api/feedback/requirements.txt -t $(FEEDBACK_BUILD_DIR) --upgrade --quiet; \
		    find $(FEEDBACK_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(FEEDBACK_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(FEEDBACK_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(FEEDBACK_BUILD_DIR) && zip -q -r /var/task/$(FEEDBACK_LAMBDA_ZIP) ."

# Build Music Analysis Lambda package
$(MUSIC_ANALYSIS_LAMBDA_ZIP): api/music_analysis/music_analysis_handler.py api/music_analysis/requirements.txt
	@echo "Building Music Analysis Lambda package..."
	@mkdir -p $(BUILD_DIR)
	@rm -rf $(MUSIC_ANALYSIS_BUILD_DIR) $(MUSIC_ANALYSIS_LAMBDA_ZIP)
	docker run --rm --platform linux/amd64 --entrypoint /bin/bash \
		-v "$(PWD):/var/task" \
		public.ecr.aws/lambda/python:3.12 \
		-c "yum install -y zip >/dev/null 2>&1 || microdnf install -y zip >/dev/null 2>&1 || true; \
		    mkdir -p $(BUILD_DIR) $(MUSIC_ANALYSIS_BUILD_DIR); \
		    cp api/music_analysis/music_analysis_handler.py $(MUSIC_ANALYSIS_BUILD_DIR)/; \
		    pip install -r api/music_analysis/requirements.txt -t $(MUSIC_ANALYSIS_BUILD_DIR) --upgrade --quiet; \
		    find $(MUSIC_ANALYSIS_BUILD_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(MUSIC_ANALYSIS_BUILD_DIR) -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true; \
		    find $(MUSIC_ANALYSIS_BUILD_DIR) -type f -name '*.pyc' -delete 2>/dev/null || true; \
		    cd $(MUSIC_ANALYSIS_BUILD_DIR) && zip -q -r /var/task/$(MUSIC_ANALYSIS_LAMBDA_ZIP) ."

clean-job-submit:
	rm -rf $(JOB_SUBMIT_BUILD_DIR) $(JOB_SUBMIT_LAMBDA_ZIP)

clean-job-worker:
	rm -rf $(JOB_WORKER_BUILD_DIR) $(JOB_WORKER_LAMBDA_ZIP)

clean-job-get:
	rm -rf $(JOB_GET_BUILD_DIR) $(JOB_GET_LAMBDA_ZIP)

clean-job-cancel:
	rm -rf $(JOB_CANCEL_BUILD_DIR) $(JOB_CANCEL_LAMBDA_ZIP)

clean-websocket-connect:
	rm -rf $(WEBSOCKET_CONNECT_BUILD_DIR) $(WEBSOCKET_CONNECT_LAMBDA_ZIP)

clean-websocket-disconnect:
	rm -rf $(WEBSOCKET_DISCONNECT_BUILD_DIR) $(WEBSOCKET_DISCONNECT_LAMBDA_ZIP)

clean-feedback:
	rm -rf $(FEEDBACK_BUILD_DIR) $(FEEDBACK_LAMBDA_ZIP)
clean-music-analysis:
	rm -rf $(MUSIC_ANALYSIS_BUILD_DIR) $(MUSIC_ANALYSIS_LAMBDA_ZIP)

clean-mcp:
	rm -rf $(MCP_BUILD_DIR) $(MCP_LAMBDA_ZIP)

clean: clean-mcp clean-job-submit clean-job-worker clean-job-get clean-job-cancel clean-websocket-connect clean-websocket-disconnect clean-feedback
clean: clean-mcp clean-job-submit clean-job-worker clean-job-get clean-job-cancel clean-websocket-connect clean-websocket-disconnect clean-music-analysis
	@# Clean up build directory if it's empty
	@if [ -d "$(BUILD_DIR)" ] && [ -z "$$(ls -A $(BUILD_DIR) 2>/dev/null)" ]; then rmdir $(BUILD_DIR) 2>/dev/null || true; fi
