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

The system consists of two main services:

- **routing-service**: FastAPI-based REST API for query submission and routing decisions
- **web-ui**: Streamlit-based dashboard for query submission and observability

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

# 2. Configure Docker to use Minikube's daemon
eval $(minikube docker-env)

# 3. Build Docker images
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui

# 4. Deploy to Kubernetes
kubectl apply -f k8s/

# 5. Verify deployments
kubectl get pods
# Wait until both pods show STATUS: Running

# 6. Access services (run in separate terminals)
kubectl port-forward service/routing-service 8000:8000
kubectl port-forward service/web-ui 8501:8501
```

Then access:
- **Routing API**: http://localhost:8000
- **Web UI**: http://localhost:8501
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

### Rebuild and Redeploy

After making code changes:

```bash
# Rebuild images (with Minikube's Docker daemon)
eval $(minikube docker-env)
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui

# Restart deployments to pick up new images
kubectl rollout restart deployment/routing-service
kubectl rollout restart deployment/web-ui

# Watch rollout status
kubectl rollout status deployment/routing-service
kubectl rollout status deployment/web-ui
```

## Accessing Services

### Method 1: Port Forwarding (Recommended for Development)

Simple and temporary - creates a tunnel from localhost to Kubernetes services.

```bash
# Terminal 1 - Routing Service
kubectl port-forward service/routing-service 8000:8000

# Terminal 2 - Web UI
kubectl port-forward service/web-ui 8501:8501
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

# Expected output:
# NAME              READY   UP-TO-DATE   AVAILABLE   AGE
# routing-service   1/1     1            1           5m
# web-ui            1/1     1            1           5m

# View deployment details
kubectl describe deployment routing-service
kubectl describe deployment web-ui
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
│   ├── main.py              # API endpoints
│   ├── pyproject.toml       # Python dependencies
│   └── Dockerfile           # Container image
├── web-ui/                  # Streamlit web interface
│   ├── app.py               # UI application
│   ├── pyproject.toml       # Python dependencies
│   └── Dockerfile           # Container image
├── k8s/                     # Kubernetes manifests
│   ├── routing-service-deployment.yaml
│   ├── routing-service-service.yaml
│   ├── web-ui-deployment.yaml
│   └── web-ui-service.yaml
├── PROJECT.md               # Detailed project specification
├── DEVIATIONS.md           # Implementation deviations
└── README.md               # This file
```

## Development Workflow

### Complete Environment Restart

```bash
# Stop and restart everything
minikube stop
minikube start

# Reconfigure Docker environment
eval $(minikube docker-env)

# Rebuild images
docker build -t routing-service:latest ./routing-service
docker build -t web-ui:latest ./web-ui

# Deploy
kubectl apply -f k8s/

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=routing-service --timeout=60s
kubectl wait --for=condition=ready pod -l app=web-ui --timeout=60s

# Access services
kubectl port-forward service/routing-service 8000:8000 &
kubectl port-forward service/web-ui 8501:8501 &
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

# Test web UI accessibility
curl http://localhost:8501
# Expected: HTML response
```

### API Documentation

The routing service provides interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Next Steps

This is **Phase 1** of the project. Current capabilities:

- ✅ Local Kubernetes environment
- ✅ Containerized services
- ✅ Basic routing service API
- ✅ Basic web UI

See `PROJECT.md` for the complete roadmap including:

- Query parsing and complexity analysis
- DuckDB integration
- Databricks SQL Warehouse integration
- Intelligent routing algorithm
- Cost tracking and observability
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
