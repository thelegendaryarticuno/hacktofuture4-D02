# PipelineIQ Deployment Guide

This project can be deployed cleanly with:

- frontend on Vercel
- backend on Render as a Docker web service
- MongoDB on MongoDB Atlas
- GitHub OAuth App for login
- GitHub App for repository installation, webhooks, diff/log access, and auto-fix PRs
- optional Kafka broker running outside Render, preferably managed or on a separate Docker host

The most important production rule for this repo is:

- keep the browser on the Vercel domain
- proxy all `/api/*` requests from Vercel to the Render backend

That keeps auth cookies, GitHub OAuth redirects, GitHub App callbacks, auto-fix report links, and feedback links on one public origin.

## 1. Production architecture

Recommended setup:

1. Vercel hosts the React frontend.
2. Vercel rewrites `/api/*` to the Render backend service.
3. Render runs the FastAPI app from `pipelineIQ/Dockerfile`.
4. MongoDB Atlas stores users, workspaces, runs, diagnosis, risk, auto-fix, feedback, and memory.
5. GitHub sends app webhooks to the Vercel `/api/github/webhooks` URL, which Vercel forwards to Render.
6. Slack receives notifications from the backend webhook integration.
7. Kafka is optional. If enabled, the backend connects to an external broker.

Do not try to run Kafka inside the same Render web service container as the FastAPI app. Render web services are meant to run one application process, and Kafka needs its own long-lived broker with stable storage and networking.

## 2. What is already in the repo

Use these deployment-specific files:

- backend Dockerfile: `pipelineIQ/Dockerfile`
- backend requirements: `pipelineIQ/requirements.txt`
- sample env file: `.env.example`

Do not use the root `Dockerfile` for PipelineIQ deployment. That file belongs to the older `flask_app` sample.

## 3. Recommended rollout strategy

Use this order:

1. Deploy MongoDB Atlas.
2. Deploy backend on Render with `KAFKA_ENABLED=false`.
3. Deploy frontend on Vercel with `/api` rewrite to Render.
4. Configure GitHub OAuth App.
5. Configure GitHub App.
6. Verify login, workspace creation, GitHub installation, webhook delivery, diagnosis, risk scoring, and auto-fix.
7. Only then decide whether to enable Kafka.

This app already works without Kafka. When `KAFKA_ENABLED=false`, the monitor and diagnosis pipeline runs inline in the backend process.

## 4. Backend deployment on Render

Create a new Render Web Service with these settings:

- Runtime: Docker
- Root Directory: `pipelineIQ`
- Dockerfile Path: `Dockerfile`
- Health Check Path: `/health`
- Instance count: `1` initially

Why single instance first:

- your backend already hosts the web API and in-process pipeline runtime
- this avoids multiple copies of the same background consumer logic during the first public deployment
- you can scale later after validating the behavior you want

The backend will start with:

```sh
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Render will inject `PORT`, so you do not need to set it manually.

## 5. Frontend deployment on Vercel

Deploy `pipelineIQ-frontend` as the frontend project.

Expected build settings:

- Framework Preset: `Vite`
- Root Directory: `pipelineIQ-frontend`
- Build Command: `npm run build`
- Output Directory: `dist`

### Vercel rewrite

The frontend uses relative `/api` calls in the browser, so you must configure a rewrite in Vercel.

In Vercel project settings, add a rewrite:

- Source: `/api/(.*)`
- Destination: `https://YOUR-RENDER-SERVICE.onrender.com/api/$1`

If your backend root also needs the legacy webhook route, add:

- Source: `/webhook/github`
- Destination: `https://YOUR-RENDER-SERVICE.onrender.com/webhook/github`

Why this matters:

- login starts at `/api/auth/github`
- OAuth callback returns to `/api/auth/github/callback`
- GitHub App install callback uses `/api/github/installations/callback`
- GitHub webhooks hit `/api/github/webhooks`
- auto-fix report and feedback links render on the frontend domain

Without this rewrite, production login and GitHub app flows will break.

## 6. Required backend environment variables

Set these on Render.

### Core app

```env
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=pipelineiq

JWT_SECRET=<long-random-secret>
JWT_ALGORITHM=HS256
SESSION_EXPIRY_DAYS=15

FRONTEND_URL=https://YOUR-FRONTEND.vercel.app
COOKIE_SECURE=true
COOKIE_DOMAIN=
RESET_CI_CD_STATE_ON_STARTUP=false
```

Notes:

- keep `COOKIE_DOMAIN` empty unless you intentionally want to share cookies across subdomains
- set `FRONTEND_URL` to the public Vercel domain, not the Render domain

### GitHub OAuth App

```env
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=https://YOUR-FRONTEND.vercel.app/api/auth/github/callback
GITHUB_OAUTH_SCOPES=read:user read:org
```

### GitHub App

```env
GITHUB_APP_ID=...
GITHUB_APP_SLUG=...
GITHUB_APP_INSTALL_URL=https://github.com/apps/YOUR-APP-SLUG/installations/new
GITHUB_APP_WEBHOOK_SECRET=...
GITHUB_APP_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

For `GITHUB_APP_PRIVATE_KEY`, paste the PEM as one env value with escaped `\n` line breaks.

### Model providers

```env
OPENAI_API_KEY=...
OPENAI_API_BASE_URL=https://api.openai.com/v1

GROQ_API_KEY=...
GROQ_API_BASE_URL=https://api.groq.com/openai/v1

GITHUB_TOKEN=...
GITHUB_MODELS_API_BASE_URL=https://models.github.ai/inference
```

If you do not use one provider, you can still leave the key blank as long as that provider is not chosen as primary or fallback in production.

### Agent model selections

```env
MONITOR_AGENT_PRIMARY_PROVIDER=github_models
MONITOR_AGENT_PRIMARY_MODEL=openai/gpt-4o-mini
MONITOR_AGENT_FALLBACK_PROVIDER=groq
MONITOR_AGENT_FALLBACK_MODEL=llama-3.3-70b-versatile

DIAGNOSIS_AGENT_PRIMARY_PROVIDER=groq
DIAGNOSIS_AGENT_PRIMARY_MODEL=openai/gpt-oss-120b
DIAGNOSIS_AGENT_FALLBACK_PROVIDER=github_models
DIAGNOSIS_AGENT_FALLBACK_MODEL=openai/gpt-4.1

RISK_AGENT_PRIMARY_PROVIDER=github_models
RISK_AGENT_PRIMARY_MODEL=gpt-4o-mini
RISK_AGENT_FALLBACK_PROVIDER=groq
RISK_AGENT_FALLBACK_MODEL=llama-3.3-70b-versatile

AUTOFIX_AGENT_PRIMARY_PROVIDER=github_models
AUTOFIX_AGENT_PRIMARY_MODEL=gpt-4o-mini
AUTOFIX_AGENT_FALLBACK_PROVIDER=groq
AUTOFIX_AGENT_FALLBACK_MODEL=llama-3.3-70b-versatile

AUTOFIX_REPORT_EXPIRY_HOURS=168
AUTOFIX_FEEDBACK_EXPIRY_HOURS=720
```

### Slack

```env
SLACK_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_DEFAULT_CHANNEL=#all-devops
SLACK_DEVOPS_MENTION_DEFAULT=@channel
```

### Kafka

For first public deployment:

```env
KAFKA_ENABLED=false
```

If you later enable Kafka:

```env
KAFKA_ENABLED=true
KAFKA_BOOTSTRAP_SERVERS=your-kafka-host:9092
KAFKA_PIPELINE_EVENTS_TOPIC=pipeline-events
KAFKA_DIAGNOSIS_REQUIRED_TOPIC=diagnosis-required
KAFKA_MONITOR_GROUP_ID=pipelineiq-monitor-agent
KAFKA_DIAGNOSIS_GROUP_ID=pipelineiq-diagnosis-agent
```

## 7. GitHub OAuth App configuration

Create a GitHub OAuth App for user login.

Set:

- Application name: `PipelineIQ`
- Homepage URL: `https://YOUR-FRONTEND.vercel.app`
- Authorization callback URL: `https://YOUR-FRONTEND.vercel.app/api/auth/github/callback`

This app is only for user authentication into the dashboard.

## 8. GitHub App configuration

Create a GitHub App for repository integration and auto-fix operations.

Set these URLs:

- Homepage URL: `https://YOUR-FRONTEND.vercel.app`
- Webhook URL: `https://YOUR-FRONTEND.vercel.app/api/github/webhooks`
- Setup URL: `https://YOUR-FRONTEND.vercel.app/api/github/installations/callback`

Subscribe to this event:

- `Workflow run`

Repository permissions to grant:

- Actions: `Read`
- Contents: `Read and write`
- Pull requests: `Read and write`
- Metadata: `Read`

Why these are needed:

- Actions read: download workflow logs
- Contents read: inspect changed files
- Contents write: create minimal fix commits
- Pull requests write: open PRs, request reviewers, merge or close PRs
- Metadata read: basic repository access

After creating the GitHub App:

1. download the private key
2. copy the App ID
3. copy the App slug
4. set the webhook secret in both GitHub and Render env
5. paste the PEM private key into `GITHUB_APP_PRIVATE_KEY`

## 9. MongoDB Atlas setup

Create a database named `pipelineiq` or keep `MONGODB_DB_NAME=pipelineiq`.

Network access:

- allow Render outbound access
- during setup, you can temporarily allow `0.0.0.0/0`
- later restrict if you have fixed egress controls

Use a dedicated database user with read/write access to that database.

## 10. Kafka deployment options

### Recommended production answer

For your first real deployment, keep:

```env
KAFKA_ENABLED=false
```

That gets the full product online faster and removes one moving part while you validate GitHub app installs, diagnosis, risk scoring, PR creation, Slack, and signed report links.

### If you want Kafka in production

Use one of these:

1. Managed Kafka or Redpanda
2. A separate VM or Docker host just for Kafka
3. A separate container platform service dedicated to the broker

Do not put Kafka inside the same Render web service container as FastAPI.

### Docker option for Kafka

If you want to self-host Kafka on a VM with Docker, use a single-node KRaft broker. Example:

```yaml
services:
  kafka:
    image: bitnami/kafka:3.7
    container_name: pipelineiq-kafka
    ports:
      - "9092:9092"
    environment:
      - KAFKA_CFG_NODE_ID=0
      - KAFKA_CFG_PROCESS_ROLES=controller,broker
      - KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=0@kafka:9093
      - KAFKA_CFG_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093
      - KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://YOUR-KAFKA-HOST:9092
      - KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      - KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER
      - KAFKA_CFG_INTER_BROKER_LISTENER_NAME=PLAINTEXT
      - KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE=true
      - ALLOW_PLAINTEXT_LISTENER=yes
    volumes:
      - kafka_data:/bitnami/kafka

volumes:
  kafka_data:
```

Then point Render to:

```env
KAFKA_ENABLED=true
KAFKA_BOOTSTRAP_SERVERS=YOUR-KAFKA-HOST:9092
```

If you expose Kafka publicly, secure it properly. The example above is fine for testing, not for a hardened internet-facing broker.

## 11. Signed URLs and why `FRONTEND_URL` matters

These features all build public links from `FRONTEND_URL`:

- GitHub OAuth redirects back into the dashboard
- GitHub App installation callback returns to the workspace page
- auto-fix approval report links
- auto-fix feedback links

Because of that:

- `FRONTEND_URL` must always be your public Vercel origin
- the Vercel `/api` rewrite must exist
- do not point `FRONTEND_URL` at the Render backend

## 12. Render and Vercel checklist

### Render

- root directory is `pipelineIQ`
- Dockerfile is `pipelineIQ/Dockerfile`
- health check path is `/health`
- all env vars above are set
- service is reachable at `https://YOUR-RENDER-SERVICE.onrender.com/health`

### Vercel

- root directory is `pipelineIQ-frontend`
- rewrite `/api/(.*)` to Render
- rewrite `/webhook/github` if you want the legacy route exposed too
- public site loads at `https://YOUR-FRONTEND.vercel.app`

## 13. Post-deploy smoke test

Run these checks in order:

1. Open the Vercel frontend.
2. Click GitHub login.
3. Confirm you land back on `/dashboard`.
4. Create a workspace.
5. Start GitHub App installation from the workspace.
6. Confirm GitHub redirects back to the correct workspace.
7. Trigger a test workflow failure in the connected repository.
8. Confirm the webhook arrives.
9. Confirm a `PipelineRun` is created in MongoDB.
10. Confirm diagnosis appears in the Diagnosis tab.
11. Confirm risk score appears with score breakdown.
12. If policy allows, confirm auto-fix creates a PR.
13. If Slack is enabled, confirm the notification appears.
14. Open any signed report link and verify it loads from the Vercel domain.

## 14. Common mistakes to avoid

- Using the root `Dockerfile` instead of `pipelineIQ/Dockerfile`
- Pointing GitHub OAuth callback to the Render domain instead of the Vercel `/api` path
- Pointing GitHub App webhook directly at Render while frontend links point at Vercel
- Forgetting the Vercel rewrite for `/api/*`
- Setting `FRONTEND_URL` to Render instead of Vercel
- Trying to run Kafka inside the same Render web service
- Leaving `COOKIE_SECURE=false` in production
- Scaling the backend to multiple instances before validating the runtime behavior you want

## 15. Recommended production values

If you want the safest first production deployment, use:

```env
FRONTEND_URL=https://YOUR-FRONTEND.vercel.app
COOKIE_SECURE=true
KAFKA_ENABLED=false
SLACK_ENABLED=true
RESET_CI_CD_STATE_ON_STARTUP=false
```

Then add Kafka only after the end-to-end product flow is stable.
