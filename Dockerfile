FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# All environment variables in one layer
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1

COPY pyproject.toml pyproject.toml
# Install dependencies - install browser tool dependencies explicitly after main deps
RUN uv pip install -r pyproject.toml
# Install browser tool dependencies separately (nest-asyncio and playwright)
RUN uv pip install nest-asyncio playwright

RUN uv pip install aws-opentelemetry-distro==0.12.2

# Signal that this is running in Docker for host binding logic
ENV DOCKER_CONTAINER=1

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
# Create writable directories for browser tool (screenshots, temp files)
RUN mkdir -p /tmp/screenshots /app/screenshots && \
    chown -R bedrock_agentcore:bedrock_agentcore /tmp/screenshots /app/screenshots && \
    chmod -R 755 /tmp/screenshots /app/screenshots
USER bedrock_agentcore

EXPOSE 9000
EXPOSE 8000
EXPOSE 8080

# Copy entire project (respecting .dockerignore)
COPY . .

# Use the full module path

CMD ["opentelemetry-instrument", "python", "-m", "src.main"]
