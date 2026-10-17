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
# Share the web-ui in a visible Chromium the agent can attach to over CDP (port 9222).
# Idempotent: reuses an existing port-forward / browser if already running.
# Resolves the Playwright-managed Chromium dynamically so it survives version bumps.
UI_PORT ?= 8501
CDP_PORT ?= 9222
ui-share:
	@mkdir -p /tmp/opencode
	@if [ "$$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:$(UI_PORT)/api/health 2>/dev/null)" = "200" ]; then \
		echo "web-ui already reachable on :$(UI_PORT)"; \
	else \
		echo "starting port-forward svc/web-ui -> :$(UI_PORT)"; \
		setsid kubectl port-forward svc/web-ui $(UI_PORT):8501 </dev/null > /tmp/opencode/web-ui-port-forward.log 2>&1 & \
		sleep 2; \
	fi
	@if [ "$$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:$(CDP_PORT)/json/version 2>/dev/null)" = "200" ]; then \
		echo "shared browser already running on CDP :$(CDP_PORT)"; \
	else \
		CHROME=$$(ls -t /home/$(USER)/.cache/ms-playwright/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1); \
		if [ -z "$$CHROME" ]; then \
			echo "ERROR: no Playwright Chromium found. Run: npx playwright install chromium"; \
			exit 1; \
		fi; \
		echo "launching shared browser: $$CHROME (CDP :$(CDP_PORT))"; \
		setsid "$$CHROME" \
			--remote-debugging-port=$(CDP_PORT) \
			--user-data-dir=/tmp/opencode/delta-router-visible-chrome \
			--no-first-run --no-default-browser-check \
			http://127.0.0.1:$(UI_PORT)/ \
			</dev/null > /tmp/opencode/delta-router-visible-chrome.log 2>&1 & \
		sleep 3; \
	fi
	@if [ "$$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:$(CDP_PORT)/json/version 2>/dev/null)" = "200" ]; then \
		echo "OK: UI shared at http://127.0.0.1:$(UI_PORT)/  |  CDP at http://127.0.0.1:$(CDP_PORT)"; \
	else \
		echo "WARN: CDP endpoint not reachable — check /tmp/opencode/delta-router-visible-chrome.log"; \
	fi
pods:
	kubectl get pods
# --- Full deploy (minikube) ---
apply:
	kubectl apply -f k8s/
# --- Azure / Terraform ---
tf-init:
	terraform -chdir=infrastructure/terraform init
tf-plan:
	terraform -chdir=infrastructure/terraform plan
tf-apply:
	terraform -chdir=infrastructure/terraform apply
tf-destroy:
	terraform -chdir=infrastructure/terraform destroy
# --- ACR image build + push ---
ACR_LOGIN_SERVER := $(shell terraform -chdir=infrastructure/terraform output -raw acr_login_server 2>/dev/null)
GIT_SHA := $(shell git rev-parse --short HEAD)
acr-login:
	az acr login --name $(ACR_LOGIN_SERVER)
build-push: acr-login build-all
	docker tag routing-service:latest $(ACR_LOGIN_SERVER)/delta-router/routing-service:$(GIT_SHA)
	docker tag routing-service:latest $(ACR_LOGIN_SERVER)/delta-router/routing-service:latest
	docker push $(ACR_LOGIN_SERVER)/delta-router/routing-service:$(GIT_SHA)
	docker push $(ACR_LOGIN_SERVER)/delta-router/routing-service:latest
	docker tag web-ui:latest $(ACR_LOGIN_SERVER)/delta-router/web-ui:$(GIT_SHA)
	docker tag web-ui:latest $(ACR_LOGIN_SERVER)/delta-router/web-ui:latest
	docker push $(ACR_LOGIN_SERVER)/delta-router/web-ui:$(GIT_SHA)
	docker push $(ACR_LOGIN_SERVER)/delta-router/web-ui:latest
	docker tag duckdb-worker:latest $(ACR_LOGIN_SERVER)/delta-router/duckdb-worker:$(GIT_SHA)
	docker tag duckdb-worker:latest $(ACR_LOGIN_SERVER)/delta-router/duckdb-worker:latest
	docker push $(ACR_LOGIN_SERVER)/delta-router/duckdb-worker:$(GIT_SHA)
	docker push $(ACR_LOGIN_SERVER)/delta-router/duckdb-worker:latest
# --- Full Azure deployment ---
deploy-azure: build-push tf-apply
# --- Utility ---
get-ip:
	kubectl get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}'
	@echo
.PHONY: build-routing build-webui build-duckdb build-all deploy-routing deploy-webui deploy-duckdb deploy-all schema-update logs-routing logs-webui logs-duckdb logs-postgres psql port-forward ui-share pods apply smoke-test tf-init tf-plan tf-apply tf-destroy acr-login build-push deploy-azure get-ip