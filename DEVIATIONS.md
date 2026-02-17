# Project Deviations
Decisions made during implementation that differ from the original plan in PROJECT.md.

## Task 5: Containerize Web UI Service
- **Deviation 1**: Used `python:3.13-slim` base image instead of `python:3.11-slim`
- **Reason**: The `web-ui/pyproject.toml` requires Python 3.13 (`requires-python = ">=3.13"`), and using 3.11 would cause dependency resolution failures
- **Impact**: None on functionality. Future containerization tasks should check `pyproject.toml` for Python version requirements rather than assuming a specific version
- **Tasks updated**: None required - this was task-specific and doesn't affect other modules

- **Deviation 2**: Used `.venv/bin/streamlit` instead of `uv run streamlit` in CMD
- **Reason**: For consistency with routing-service and efficiency - `uv run` adds unnecessary overhead by potentially downloading CPython at runtime
- **Impact**: Faster container startup, consistent pattern across all services
- **Tasks updated**: None required - this is a best practice for all future Dockerfiles

## Task 9: Deploy Services to Kubernetes Cluster
- **Deviation**: Added `imagePullPolicy: Never` to both deployment manifests (routing-service and web-ui)
- **Reason**: Minikube was attempting to pull images from Docker Hub instead of using locally built images, causing ImagePullBackOff errors. This configuration tells Kubernetes to only use local images
- **Impact**: Deployments now explicitly configured for local development with Minikube. If deploying to production or remote clusters, these manifests would need to use a proper container registry and `imagePullPolicy: IfNotPresent` or `Always`
- **Tasks updated**: None required - this is specific to local Kubernetes deployment strategy
