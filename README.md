# HackToFuture 4.0 - D02

## Problem Statement / Idea

In modern software development, Continuous Integration and Continuous Deployment (CI/CD) pipeline failures create significant bottlenecks. 

- **What is the problem?** Developers spend countless hours digging through thousands of lines of logs just to identify why a build failed, what caused it, and how to safely patch it without breaking existing code.
- **Why is it important?** Pipeline downtime halts deployments, delays releases, and severely diminishes developer productivity. Code velocity drops when senior engineers are forced to manually debug and review every broken test or infrastructure flake.
- **Who are the target users?** DevOps engineers, backend/frontend developers, and team leads who manage project repositories and CI/CD workflows.

---

## Proposed Solution

**PipelineIQ** is an AI-powered pipeline intelligence and auto-remediation platform.

- **What are you building?** An event-driven architecture that listens to GitHub repository workflows in real time. We utilize intelligent agents to monitor build health, diagnose failures automatically from logs, calculate the risk of the change, and provide an automated code-fix through a Pull Request.
- **How does it solve the problem?** Instead of digging through logs manually, developers simply check their PipelineIQ Dashboard or Slack messages. The platform has already diagnosed the root cause, assigned a risk score, and in many cases, opened a Pull Request with the exact code patch needed to fix the build.
- **What makes your solution unique?** It operates autonomously using multiple event-driven agents (Monitor, Diagnosis, Risk Classification and Auto-Fix). It doesn't just report errors; it applies targeted source code fixes directly back to GitHub workflows with a finely-tuned Risk Policy engine (deciding between Auto-Merge, Approval Required, or Report Only thresholds).

---

## Features

- **Event-Driven Monitoring**: Instantly receives workflow execution data from GitHub Apps via Kafka topics without polling.
- **AI-Powered Diagnostics**: Ingests massive build logs and code diffs to isolate the exact error, latest working changes, and possible root causes in plain English.
- **Automated Remediation & PR Generation**: Generates minimal, safe code patches and automatically commits them or raises Pull Requests directly on the user's repository.
- **Dynamic Risk Profiling**: Evaluates the volatility of the change, allowing workspace owners to set automated thresholds for auto-merging safe fixes versus requesting human approval for risky codebase modifications.
- **Multi-channel Notifications**: Dispatches real-time alerts and manual review requests seamlessly via Slack Webhooks.

- **Self Learning Engine**: The system learns from the fixes it makes, recieves feedback for autofixes, PR's it generates and improves its accuracy over time along with extending the changes it can autofix and thus be reducing MTTR (Mean time to Repair) the broken pipeline.

---

## Tech Stack

- **Frontend:** React 19, Vite, TailwindCSS (v4), React Router DOM, Axios
- **Backend:** FastAPI (Python), Uvicorn, PyJWT, httpx, aiokafka
- **Database:** MongoDB
- **APIs / Services:** GitHub Apps API (webhooks, repository contents, pull requests), OpenAI API (LLM Gateway), Slack Incoming Webhooks
- **Tools / Libraries:** Apache Kafka (KRaft mode via Docker)

---

## Project Setup Instructions

Follow these exact steps to run PipelineIQ locally.

```bash
# Clone the repository
git clone https://github.com/your-username/hacktofuture4-D02.git
cd hacktofuture4-D02

# --- 1. Environment Setup ---
# Duplicate the example env file and fill in your GitHub App credentials, URLs, and API keys.
cp .env.example .env

# --- 2. Kafka Broker Setup (via Docker) ---
# Start a single-node Kafka broker (KRaft mode)
docker run -d --name pipelineiq-kafka \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -apache/kafka:3.9.0

# Create the required Kafka topics
docker exec -it pipelineiq-kafka /opt/kafka/bin/kafka-topics.sh \
  --create --topic pipeline-events --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1

docker exec -it pipelineiq-kafka /opt/kafka/bin/kafka-topics.sh \
  --create --topic diagnosis-required --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1

# --- 3. Backend Setup ---
cd pipelineIQ

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the FastAPI backend
uvicorn main:app --reload
# The backend will be available at http://localhost:8000

# --- 4. Frontend Setup ---
# Open a new terminal tab and navigate back to the root folder
cd pipelineIQ-frontend

# Install dependencies
npm install

# Run the frontend project
npm run dev
# The React dashboard will be accessible at http://localhost:5173
```
