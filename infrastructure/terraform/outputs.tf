output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.this.name
}
output "aks_cluster_name" {
  description = "AKS cluster name"
  value       = azurerm_kubernetes_cluster.this.name
}
output "aks_kube_config" {
  description = "Kubeconfig for kubectl access"
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}
output "acr_login_server" {
  description = "ACR login server (e.g. acrdeltarouter.azurecr.io)"
  value       = azurerm_container_registry.this.login_server
}