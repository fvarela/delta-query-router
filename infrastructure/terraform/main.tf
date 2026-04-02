# ── Resource Group ───────────────────────────────────────────
resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}
# ── Virtual Network ──────────────────────────────────────────
resource "azurerm_virtual_network" "this" {
  name                = "vnet-delta-router"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = ["10.0.0.0/16"]
}
resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.1.0/24"]
}
# ── AKS Cluster ──────────────────────────────────────────────
resource "azurerm_kubernetes_cluster" "this" {
  name                = var.aks_cluster_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = var.aks_cluster_name
  default_node_pool {
    name                 = "default"
    vm_size              = var.aks_node_vm_size
    auto_scaling_enabled = true
    min_count            = var.aks_node_count_min
    max_count            = var.aks_node_count_max
    vnet_subnet_id       = azurerm_subnet.aks.id
  }
  identity {
    type = "SystemAssigned"
  }
  network_profile {
    network_plugin = "azure"
  }
}
# ── Container Registry ───────────────────────────────────────
resource "azurerm_container_registry" "this" {
  name                = var.acr_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Basic"
  admin_enabled       = false
}
# ── ACR → AKS pull permission ────────────────────────────────
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}