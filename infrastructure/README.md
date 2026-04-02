# Delta Router — Azure AKS Deployment
## Prerequisites
- Azure CLI (`az`) logged in with an active subscription
- Terraform >= 1.5
- Docker (for building images)
- Helm 3 (installed automatically by Terraform, but useful for local debugging)
- `kubectl` configured (Terraform outputs kubeconfig, or use `az aks get-credentials`)
## Quick Start
```bash
# 1. Provision infrastructure
cp infrastructure/terraform/terraform.tfvars.example infrastructure/terraform/terraform.tfvars
# Edit terraform.tfvars with your subscription ID and passwords
make tf-init
make tf-plan    # review what will be created
make tf-apply   # create Azure resources + deploy app
# 2. Get kubectl access
az aks get-credentials \
  --resource-group rg-delta-router \
  --name aks-delta-router
# 3. Check pods
kubectl get pods
# 4. Get the public IP
make get-ip
Full Deployment (build + push + deploy)
make deploy-azure
This runs: build-all → acr-login → tag & push to ACR → terraform apply.
Updating the Application
After code changes:
make build-push    # rebuild images and push to ACR
kubectl rollout restart deployment/routing-service
kubectl rollout restart deployment/web-ui
kubectl rollout restart deployment/duckdb-worker-small
Or re-run make deploy-azure which will rebuild and terraform apply (Helm detects image changes).
Tear Down
make tf-destroy
This removes all Azure resources (AKS, ACR, VNet, resource group).
Architecture
infrastructure/
  terraform/          # Azure infra provisioning
    providers.tf      # azurerm, kubernetes, helm providers
    main.tf           # Resource Group, VNet, AKS, ACR
    kubernetes.tf     # K8s secrets, NGINX ingress controller
    helm.tf           # delta-router Helm release
    variables.tf      # input variables
    outputs.tf        # ACR login server, AKS name, kubeconfig
  helm/
    delta-router/     # Umbrella Helm chart
      Chart.yaml
      values.yaml           # minikube defaults
      values-azure.yaml     # AKS overrides
      templates/            # K8s resource templates
      files/schema.sql      # DB schema (embedded in ConfigMap)
Minikube (Local Dev)
The Helm chart also works with minikube using the default values.yaml:
helm install delta infrastructure/helm/delta-router
Existing make deploy-* targets using raw k8s/ manifests still work unchanged.