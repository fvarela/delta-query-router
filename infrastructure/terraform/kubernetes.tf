# ── Kubernetes + Helm providers (depend on AKS) ─────────────
provider "kubernetes" {
  host                   = azurerm_kubernetes_cluster.this.kube_config[0].host
  client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].client_certificate)
  client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].client_key)
  cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate)
}
provider "helm" {
  kubernetes {
    host                   = azurerm_kubernetes_cluster.this.kube_config[0].host
    client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].client_certificate)
    client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].client_key)
    cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_config[0].cluster_ca_certificate)
  }
}
# ── K8s secrets ──────────────────────────────────────────────
resource "kubernetes_secret" "admin_credentials" {
  metadata {
    name = "admin-credentials"
  }
  data = {
    ADMIN_USERNAME = var.admin_username
    ADMIN_PASSWORD = var.admin_password
  }
}
resource "kubernetes_secret" "postgresql_credentials" {
  metadata {
    name = "postgresql-secret"
  }
  data = {
    POSTGRES_USER     = var.postgres_user
    POSTGRES_PASSWORD = var.postgres_password
    POSTGRES_DB       = var.postgres_database
  }
}
# ── NGINX ingress controller ────────────────────────────────
resource "helm_release" "ingress_nginx" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  namespace        = "ingress-nginx"
  create_namespace = true
  set {
    name  = "controller.service.annotations.service\\.beta\\.kubernetes\\.io/azure-load-balancer-health-probe-request-path"
    value = "/healthz"
  }
}