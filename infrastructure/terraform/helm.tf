# ── Delta Router application ────────────────────────────────
resource "helm_release" "delta_router" {
  name  = "delta"
  chart = "${path.module}/../helm/delta-router"
  values = [
    file("${path.module}/../helm/delta-router/values-azure.yaml")
  ]
  # Disable Helm-managed secrets — Terraform creates them in kubernetes.tf
  set {
    name  = "secrets.adminCredentials.create"
    value = "false"
  }
  set {
    name  = "secrets.postgresqlCredentials.create"
    value = "false"
  }
  # Set ACR image paths dynamically from Terraform output
  set {
    name  = "routingService.image.repository"
    value = "${azurerm_container_registry.this.login_server}/delta-router/routing-service"
  }
  set {
    name  = "webUi.image.repository"
    value = "${azurerm_container_registry.this.login_server}/delta-router/web-ui"
  }
  set {
    name  = "duckdbWorker.image.repository"
    value = "${azurerm_container_registry.this.login_server}/delta-router/duckdb-worker"
  }
  depends_on = [
    helm_release.ingress_nginx,
    kubernetes_secret.admin_credentials,
    kubernetes_secret.postgresql_credentials,
    azurerm_role_assignment.aks_acr_pull,
  ]
}