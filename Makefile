# Delta Router — common dev commands
# Usage: make <target>, e.g. make build-routing deploy-routing
# --- Build ---
build-routing:
	docker build -t routing-service:latest ./routing-service
build-webui:
	docker build -t web-ui:latest ./web-ui
build-duckdb:
	docker build -t duckdb-worker:latest ./duckdb-worker
build-all: build-routing build-webui build-duckdb
# --- Deploy to minikube ---
deploy-routing: build-routing
	minikube ssh 'docker rmi -f routing-service:latest' || true
	minikube image load routing-service:latest
	kubectl rollout restart deployment/routing-service
	kubectl rollout status deployment/routing-service --timeout=60s
deploy-webui: build-webui
	minikube ssh 'docker rmi -f web-ui:latest' || true
	minikube image load web-ui:latest
	kubectl rollout restart deployment/web-ui
	kubectl rollout status deployment/web-ui --timeout=60s
deploy-duckdb: build-duckdb
	minikube ssh 'docker rmi -f duckdb-worker:latest' || true
	minikube image load duckdb-worker:latest
	kubectl rollout restart deployment/duckdb-worker-small
	kubectl rollout status deployment/duckdb-worker-small --timeout=60s
	@echo "Note: medium/large tiers start with replicas=0 (stopped). Use the UI to start them."
deploy-all: deploy-routing deploy-webui deploy-duckdb
# --- Schema ---
schema-update:
	kubectl create configmap postgresql-schema --from-file=schema.sql=routing-service/db/schema.sql --dry-run=client -o yaml | kubectl apply -f -
	kubectl delete job postgresql-schema-init --ignore-not-found
	kubectl apply -f k8s/postgresql-schema-job.yaml
# --- Logs ---
logs-routing:
	kubectl logs -l app=routing-service --tail=50 -f
logs-webui:
	kubectl logs -l app=web-ui --tail=50 -f
logs-duckdb:
	kubectl logs -l duckdb-tier --tail=50 -f
logs-postgres:
	kubectl logs -l app=postgresql --tail=50 -f
# --- Debug ---
psql:
	kubectl exec -it postgresql-0 -- psql -U delta -d deltarouter
port-forward:
	kubectl port-forward svc/web-ui 8501:8501
pods:
	kubectl get pods
# --- Full deploy ---
apply:
	kubectl apply -f k8s/
# --- Test ---
smoke-test:
	./scripts/smoke-test.sh
.PHONY: build-routing build-webui build-duckdb build-all deploy-routing deploy-webui deploy-duckdb deploy-all schema-update logs-routing logs-webui logs-duckdb logs-postgres psql port-forward pods apply smoke-test