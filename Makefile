# Delta Router — common dev commands
# Usage: make <target>, e.g. make build-routing deploy-routing
# --- Build ---
build-routing:
	docker build -t routing-service:latest ./routing-service
build-webui:
	docker build -t web-ui:latest ./web-ui
build-all: build-routing build-webui
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
deploy-all: deploy-routing deploy-webui
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
.PHONY: build-routing build-webui build-all deploy-routing deploy-webui deploy-all schema-update logs-routing logs-webui logs-postgres psql port-forward pods apply