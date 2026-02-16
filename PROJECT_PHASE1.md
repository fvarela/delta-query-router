# Delta Router - Phase 1: Local Development Environment

## Goal

Get a "hello world" system running locally with Kubernetes to establish the foundational development workflow.

## Deliverables

### 1. Local Kubernetes Cluster
- Set up minikube or kind for local development
- Verify cluster is running and accessible via kubectl

### 2. Web UI Container (Streamlit)
- Create a simple Streamlit application
- Display "Hello Delta Router" welcome message
- Package as Docker container
- Deploy to local Kubernetes cluster

### 3. Routing Service Container (FastAPI)
- Create a basic FastAPI application
- Implement `/health` endpoint that returns `{"status": "ok"}`
- Package as Docker container
- Deploy to local Kubernetes cluster

### 4. Kubernetes Deployment
- Create Kubernetes manifests (Deployment + Service) for both containers
- Deploy both services to the local cluster
- Expose services for local access

### 5. Verification
- Verify pods are running: `kubectl get pods`
- Access Streamlit UI in browser
- Test routing service health endpoint: `curl http://localhost:<port>/health`

## Out of Scope for Phase 1

- PostgreSQL database
- Databricks integration
- DuckDB workers
- Actual query routing logic
- Terraform or cloud deployment
- Authentication or security
- Production-grade configurations

## Tech Stack

- **Kubernetes**: minikube or kind (local cluster)
- **web-ui**: Streamlit (Python)
- **routing-service**: FastAPI (Python)
- **Deployment**: Kubernetes manifests (YAML)
- **Container Registry**: Local Docker images
- **Dependency Management**: uv (for Python packages)

## Success Criteria

✅ Local Kubernetes cluster is running  
✅ `kubectl get pods` shows both services in Running state  
✅ Streamlit UI accessible in browser at `http://localhost:<ui-port>`  
✅ Health endpoint responds: `curl http://localhost:<api-port>/health` returns `{"status": "ok"}`  
✅ Both containers built and pushed to local registry  

## Directory Structure

```
delta-router/
├── routing-service/
│   ├── Dockerfile
│   ├── main.py
│   ├── pyproject.toml
│   └── uv.lock
├── web-ui/
│   ├── Dockerfile
│   ├── app.py
│   ├── pyproject.toml
│   └── uv.lock
└── k8s/
    ├── routing-service-deployment.yaml
    ├── routing-service-service.yaml
    ├── web-ui-deployment.yaml
    └── web-ui-service.yaml
```

## Implementation Notes

- Use Python 3.11+ for both services
- Use **uv** for dependency management (instead of pip/requirements.txt)
- Each service has `pyproject.toml` and `uv.lock` for dependencies
- Keep Dockerfiles simple (single-stage builds with uv)
- Use NodePort or port-forward for local access
- No need for ingress controller in Phase 1
- Both services can share the default namespace
