# Delta Router

An intelligent query routing system that analyzes SQL queries against Delta Lake tables and automatically routes them to the most cost-effective execution engine while maintaining governance constraints.

## Overview

Delta Router aims to achieve **50%+ cost reduction with less than 20% latency increase** by intelligently routing simple analytical queries to lightweight containerized DuckDB workers, while directing complex or governed queries to Databricks SQL Warehouse.

### Key Features

- **Intelligent Query Routing**: Analyzes query complexity, data volume, and governance constraints
- **Cost Optimization**: Routes simple queries to DuckDB (10-50x cheaper than Databricks)
- **Governance-Aware**: Respects row-level security and column masking requirements
- **Observability**: Web UI with real-time metrics and cost tracking
- **Cloud-Agnostic**: Kubernetes-based deployment (Azure, AWS, GCP, or local)

## Architecture

The system consists of four services:

- **routing-service**: FastAPI-based REST API for query submission and routing decisions (port 8000)
- **web-ui**: Streamlit-based dashboard for query submission and observability (port 8501)
- **duckdb-worker**: FastAPI wrapper around DuckDB for executing analytical queries (port 8002)
- **postgresql**: PostgreSQL database for query logs, routing decisions, and cost metrics (port 5432)

## Prerequisites

Before you begin, ensure you have the following installed:

- **Docker**: Container runtime ([Install Docker](https://docs.docker.com/get-docker/))
- **Minikube**: Local Kubernetes cluster ([Install Minikube](https://minikube.sigs.k8s.io/docs/start/))
- **kubectl**: Kubernetes CLI ([Install kubectl](https://kubernetes.io/docs/tasks/tools/))
- **Python 3.13+**: Required for local development
- **uv**: Fast Python package manager ([Install uv](https://github.com/astral-sh/uv))

## Quick Start

Get the entire stack running in under 5 minutes:

```bash
# 1. Start Minikube cluster
minikube start

# 2. Build Docker images
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui
docker build -t duckdb-worker:latest ./duckdb-worker

# 3. Load images into Minikube
minikube image load routing-service:latest
minikube image load web-ui:latest
minikube image load duckdb-worker:latest

# 4. Deploy PostgreSQL (secret, statefulset, service, schema)
kubectl apply -f k8s/postgresql-secret.yaml
kubectl apply -f k8s/postgresql-statefulset.yaml
kubectl apply -f k8s/postgresql-service.yaml
kubectl wait --for=condition=ready pod/postgresql-0 --timeout=60s
kubectl create configmap postgresql-schema --from-file=schema.sql=routing-service/db/schema.sql --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/postgresql-schema-job.yaml

# 5. Deploy all other services
kubectl apply -f k8s/

# 6. Verify deployments
kubectl get pods
# Wait until all 4 pods show STATUS: Running

# 7. Access services (run in separate terminals)
kubectl port-forward svc/routing-service 8000:8000
kubectl port-forward svc/web-ui 8501:8501
kubectl port-forward svc/duckdb-worker 8002:8002
```

Then access:
- **Routing API**: http://localhost:8000
- **Web UI**: http://localhost:8501
- **DuckDB Worker**: http://localhost:8002
- **API Docs**: http://localhost:8000/docs

## Local Development

### Setup Individual Services

#### Routing Service

```bash
cd routing-service

# Install dependencies
uv sync

# Run locally
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Test health endpoint
curl http://localhost:8000/health
```

#### Web UI

```bash
cd web-ui

# Install dependencies
uv sync

# Run locally
uv run streamlit run app.py --server.port 8501

# Access at http://localhost:8501
```

#### DuckDB Worker

```bash
cd duckdb-worker

# Install dependencies
uv sync

# Run locally
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8002

# Test health endpoint
curl http://localhost:8002/health

# Test query execution
curl -X POST http://localhost:8002/query -H 'Content-Type: application/json' -d '{"sql": "SELECT 42 AS answer"}'
```

### Rebuild and Redeploy

After making code changes:

```bash
# Rebuild images
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui
docker build -t duckdb-worker:latest ./duckdb-worker

# Load into Minikube
minikube image load routing-service:latest
minikube image load web-ui:latest
minikube image load duckdb-worker:latest

# Restart deployments to pick up new images
kubectl rollout restart deployment/routing-service
kubectl rollout restart deployment/web-ui
kubectl rollout restart deployment/duckdb-worker

# Watch rollout status
kubectl rollout status deployment/routing-service
kubectl rollout status deployment/web-ui
kubectl rollout status deployment/duckdb-worker
```

> **Note**: If the `latest` tag gets cached by Minikube, you may need to force a refresh:
> scale the deployment to 0, run `minikube image rm`, then `minikube image load`, and scale back to 1.

## Accessing Services

### Method 1: Port Forwarding (Recommended for Development)

Simple and temporary - creates a tunnel from localhost to Kubernetes services.

```bash
# Terminal 1 - Routing Service
kubectl port-forward service/routing-service 8000:8000

# Terminal 2 - Web UI
kubectl port-forward service/web-ui 8501:8501

# Terminal 3 - DuckDB Worker
kubectl port-forward service/duckdb-worker 8002:8002

# PostgreSQL (for direct database access)
kubectl port-forward service/postgresql 5432:5432
```

**Pros**: Simple, no configuration changes
**Cons**: Dies when you close the terminal

### Method 2: NodePort (Persistent Access)

Exposes services on static ports on the Minikube node.

```bash
# Change service type to NodePort
kubectl patch service routing-service -p '{"spec":{"type":"NodePort"}}'
kubectl patch service web-ui -p '{"spec":{"type":"NodePort"}}'

# Get service URLs
minikube service routing-service --url
minikube service web-ui --url

# Access services at the URLs shown
```

**Pros**: Persistent, survives terminal closure
**Cons**: Random ports, requires service modification

To revert back to ClusterIP:

```bash
kubectl patch service routing-service -p '{"spec":{"type":"ClusterIP"}}'
kubectl patch service web-ui -p '{"spec":{"type":"ClusterIP"}}'
```

## Kubernetes Management

### Essential Commands

```bash
# Check cluster status
kubectl cluster-info
kubectl get nodes

# View all resources
kubectl get all

# Check pod status
kubectl get pods
kubectl get pods -w  # Watch mode

# View pod logs
kubectl logs -l app=routing-service
kubectl logs -l app=web-ui
kubectl logs -l app=duckdb-worker
kubectl logs postgresql-0
kubectl logs -l app=routing-service --follow  # Stream logs

# Describe resources (useful for debugging)
kubectl describe pod <pod-name>
kubectl describe deployment routing-service

# Check service endpoints
kubectl get services
kubectl get endpoints

# Execute commands in pods
kubectl exec -it <pod-name> -- /bin/bash

# Delete and recreate all resources
kubectl delete -f k8s/
kubectl apply -f k8s/
```

### Deployment Status

```bash
# Check deployment status
kubectl get deployments
kubectl get statefulsets

# Expected output:
# NAME              READY   UP-TO-DATE   AVAILABLE   AGE
# routing-service   1/1     1            1           5m
# web-ui            1/1     1            1           5m
# duckdb-worker     1/1     1            1           5m
#
# NAME         READY   AGE
# postgresql   1/1     5m

# View deployment details
kubectl describe deployment routing-service
kubectl describe deployment web-ui
kubectl describe deployment duckdb-worker
kubectl describe statefulset postgresql
```

## Troubleshooting

### Pods Not Starting (ImagePullBackOff)

**Symptom**: `kubectl get pods` shows `ImagePullBackOff` status

**Cause**: Kubernetes trying to pull images from remote registry instead of using local images

**Solution**:
```bash
# Ensure you're using Minikube's Docker daemon
eval $(minikube docker-env)

# Verify images exist locally
docker images | grep -E "(routing-service|web-ui)"

# Rebuild if needed
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui

# Verify imagePullPolicy in deployments
kubectl get deployment routing-service -o yaml | grep imagePullPolicy
# Should show: imagePullPolicy: Never
```

### Pods Crashing (CrashLoopBackOff)

**Symptom**: Pods repeatedly restart

**Solution**:
```bash
# Check logs for errors
kubectl logs -l app=routing-service --tail=50
kubectl logs -l app=web-ui --tail=50

# Check previous pod logs if currently crashed
kubectl logs <pod-name> --previous

# Describe pod for events
kubectl describe pod <pod-name>
```

### Service Not Accessible

**Symptom**: Cannot access services via localhost

**Solution**:
```bash
# Verify port-forward is running
# Kill and restart port-forward commands

# Check if pods are ready
kubectl get pods
# STATUS should be "Running", READY should be "1/1"

# Check if services exist
kubectl get services

# Test service from within cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://routing-service:8000/health
```

### Minikube Not Starting

**Solution**:
```bash
# Delete and recreate cluster
minikube delete
minikube start

# Check Minikube status
minikube status

# View Minikube logs
minikube logs
```

### uv Command Not Found

**Solution**:
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv

# Verify installation
uv --version
```

### Docker Daemon Not Running

**Solution**:
```bash
# Start Docker service (Linux)
sudo systemctl start docker

# Start Docker Desktop (Mac/Windows)
# Open Docker Desktop application

# Verify Docker is running
docker ps
```

## Environment Variables

Create a `.env` file in the project root for configuration (see `.env.example`):

```bash
# Copy example environment file
cp .env.example .env

# Edit as needed
nano .env
```

## Project Structure

```
delta-router/
├── routing-service/          # FastAPI routing service
│   ├── main.py              # API endpoints (/health, /health/backends)
│   ├── db/
│   │   ├── schema.sql       # PostgreSQL schema (source of truth)
│   │   └── migrations/      # Migration scripts (for documentation)
│   ├── pyproject.toml       # Python dependencies
│   └── Dockerfile           # Container image
├── duckdb-worker/            # DuckDB query execution worker
│   ├── main.py              # API endpoints (/health, /query)
│   ├── pyproject.toml       # Python dependencies
│   └── Dockerfile           # Container image
├── web-ui/                  # Streamlit web interface
│   ├── app.py               # UI application
│   ├── pyproject.toml       # Python dependencies
│   └── Dockerfile           # Container image
├── k8s/                     # Kubernetes manifests
│   ├── routing-service-deployment.yaml
│   ├── routing-service-service.yaml
│   ├── routing-service-configmap.yaml
│   ├── web-ui-deployment.yaml
│   ├── web-ui-service.yaml
│   ├── duckdb-worker-deployment.yaml
│   ├── duckdb-worker-service.yaml
│   ├── postgresql-secret.yaml
│   ├── postgresql-statefulset.yaml
│   ├── postgresql-service.yaml
│   └── postgresql-schema-job.yaml
├── PROJECT.md               # Detailed project specification
└── README.md                # This file
```

## Development Workflow

### Complete Environment Restart

```bash
# Stop and restart everything
minikube stop
minikube start

# Rebuild images
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui
docker build -t duckdb-worker:latest ./duckdb-worker

# Load images into Minikube
minikube image load routing-service:latest
minikube image load web-ui:latest
minikube image load duckdb-worker:latest

# Deploy PostgreSQL first
kubectl apply -f k8s/postgresql-secret.yaml
kubectl apply -f k8s/postgresql-statefulset.yaml
kubectl apply -f k8s/postgresql-service.yaml
kubectl wait --for=condition=ready pod/postgresql-0 --timeout=60s
kubectl create configmap postgresql-schema --from-file=schema.sql=routing-service/db/schema.sql --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/postgresql-schema-job.yaml

# Deploy all other services
kubectl apply -f k8s/

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=routing-service --timeout=60s
kubectl wait --for=condition=ready pod -l app=web-ui --timeout=60s
kubectl wait --for=condition=ready pod -l app=duckdb-worker --timeout=60s

# Access services
kubectl port-forward service/routing-service 8000:8000 &
kubectl port-forward service/web-ui 8501:8501 &
kubectl port-forward service/duckdb-worker 8002:8002 &
```

### Cleanup

```bash
# Stop port-forwards
pkill -f "kubectl port-forward"

# Delete all resources
kubectl delete -f k8s/

# Stop Minikube
minikube stop

# Delete Minikube cluster (full cleanup)
minikube delete
```

## Testing

### Health Checks

```bash
# Test routing service health
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Test backend connectivity
curl http://localhost:8000/health/backends
# Expected: {"postgresql":{"status":"connected"},"duckdb_worker":{"status":"connected"}}

# Test DuckDB worker query execution
curl -X POST http://localhost:8002/query -H 'Content-Type: application/json' -d '{"sql": "SELECT 1"}'
# Expected: {"columns":["1"],"rows":[[1]],"row_count":1,"execution_time_ms":...}

# Test web UI accessibility
curl http://localhost:8501
# Expected: HTML response

# Test PostgreSQL schema
kubectl exec -it postgresql-0 -- psql -U delta -d deltarouter -c '\dt'
# Expected: query_logs, routing_decisions, cost_metrics, table_metadata_cache
```

### API Documentation

The routing service provides interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Next Steps

This is **Phase 2** of the project. Current capabilities:

- Local Kubernetes environment with 4 services
- Containerized routing service with backend health checks
- DuckDB worker with SQL query execution API
- PostgreSQL with schema for query logs, routing decisions, and cost metrics
- Streamlit web UI scaffold

See `PROJECT.md` for the complete roadmap including:

- Query parsing and complexity analysis
- Intelligent routing algorithm
- Databricks SQL Warehouse integration
- Cost tracking and observability dashboard
- Production deployment to cloud

## Contributing

This is a prototype/demo project. See `PROJECT_PHASE1.md` for current development tasks.

## License

[Add license information]

## Support

For issues and questions:
- Check the Troubleshooting section above
- Review logs: `kubectl logs -l app=<service-name>`
- Inspect pod details: `kubectl describe pod <pod-name>`

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Streamlit](https://streamlit.io/) - Data app framework
- [Kubernetes](https://kubernetes.io/) - Container orchestration
- [Minikube](https://minikube.sigs.k8s.io/) - Local Kubernetes
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager
