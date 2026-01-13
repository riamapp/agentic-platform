## Agentic Platform Architecture

This document defines the high‑level architecture and repo layout for the Agentic platform.  
Use this as the source of truth when creating and wiring the related repos.

---

## Repositories

### 1. `agentic-platform` (this repo)

**Repository URL**: https://github.com/bill-transact/agentic-platform

**Purpose**: Agent runtime and orchestration layer.

**Responsibilities**:

- Strands / AgentCore application:
  - Core agent logic, tools, memory integration.
  - MCP Gateway client for external tools.
- HTTP APIs:
  - `POST /jobs` – submit agent jobs with WebSocket streaming. All agent operations use this endpoint to avoid 30s API Gateway timeout limits.
- Job orchestration:
  - Jobs table (DynamoDB) and/or queue (SQS).
  - `job_submit` Lambda (HTTP) that creates jobs and returns a `jobId`.
  - `job_worker` Lambda that pulls jobs, invokes AgentCore, and emits progress/results.
- WebSockets:
  - WebSocket API (API Gateway v2).
  - `$connect` / `$disconnect` handlers.
  - Connections table (DynamoDB) storing `connectionId` (and optionally user/session).
  - Worker publishes messages over WebSocket using `jobId` and `sessionId`.

**Deployment**:

- All infrastructure is managed via **Terraform**:

  ```bash
  terraform init
  AWS_PROFILE=... terraform apply
  ```

- AgentCore runtime image is built and pushed from Terraform using a `null_resource` + `docker build` pattern.

---

---

### 3. `agentic-auth` (optional but recommended)

**Repository URL**: https://github.com/bill-transact/agentic-auth

**Purpose**: Shared identity / auth plane.

**Responsibilities**:

- Cognito User Pool shared by:
  - Frontend applications.
  - Items API.
  - (Optionally) AgentCore Gateway.
- App clients and domains for:
  - Browser frontends (authorization code flow).
  - Machine‑to‑machine clients (client credentials).
- Optional social identity providers (Google, etc.).

**Deployment**:

- Managed via **Terraform**:

  ```bash
  terraform init
  AWS_PROFILE=... terraform apply
  ```

- Exports outputs such as:
  - `user_pool_id`
  - `frontend_client_id`
  - `m2m_client_id`
  which are referenced as variables in `agentic-platform` and `agentic-items-api`.

---

### 4. `agentic-frontend`

**Repository URL**: https://github.com/bill-transact/agentic-frontend

**Purpose**: Web UI for interacting with the agent.

**Responsibilities**:

- SPA (Vue/React/etc.) that:
  - Authenticates the user via Cognito.
  - Calls the **Agent Platform** only:
    - `POST /invoke` for short interactions.
    - `POST /jobs` for long‑running work.
  - Opens a WebSocket connection to the Agent Platform and renders streamed job updates.

**Build & Deploy**:

- Build with **npm**:

  ```bash
  npm install
  npm run build
  ```

- Infrastructure via **Terraform** (S3 + CloudFront):

  ```bash
  terraform init
  AWS_PROFILE=... terraform apply
  ```

- Upload built assets:

  ```bash
  aws s3 sync dist/ s3://your-frontend-bucket --delete
  ```

---

### 5. `agentic-user-api`

**Repository URL**: https://github.com/bill-transact/agentic-user-api

**Purpose**: (To be documented)

**Responsibilities**:

- (To be documented)

**Deployment**:

- (To be documented)

---

## Cross‑Service Contracts

### Agent Platform ↔ Frontend

- Frontend interacts solely with `agentic-platform`:

  - `POST /jobs`:
    - Request: `{ prompt, sessionId, connectionId }`
    - Response: `{ jobId, sessionId }`
    - All agent operations use this endpoint for consistent WebSocket streaming and to avoid 30s timeout limits.

  - WebSocket messages:
    - `{"jobId": "...", "type": "chunk", "content": "..." }`
    - `{"jobId": "...", "type": "result", "statusCode": 200, "body": "..." }`
    - Optional `{"jobId": "...", "type": "error", "message": "..." }`

- All agent operations use the `/jobs` endpoint with WebSocket streaming to avoid 30s HTTP timeout limits.

---

## Deployment Conventions

- **Terraform** is the single tool for infrastructure across all repos.
- **npm** (or pnpm/yarn) is used to build frontends.
- Each repo has its own CI pipeline that:
  - For infra repos: runs `terraform fmt`, `terraform validate`, `terraform plan`, then `terraform apply` (with approval).
  - For frontend: runs tests, `npm run build`, and deploys static assets to S3/CloudFront.

Use this document as a reference when bootstrapping `agentic-auth` and `agentic-frontend` so the overall system stays consistent.


