# ── Azure core ───────────────────────────────────────────────
variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}
variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus2"
}
variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "rg-delta-router"
}
# ── AKS ──────────────────────────────────────────────────────
variable "aks_cluster_name" {
  description = "AKS cluster name"
  type        = string
  default     = "aks-delta-router"
}
variable "aks_node_vm_size" {
  description = "VM size for the default node pool"
  type        = string
  default     = "Standard_B2ms"
}
variable "aks_node_count_min" {
  description = "Minimum node count (autoscaler)"
  type        = number
  default     = 1
}
variable "aks_node_count_max" {
  description = "Maximum node count (autoscaler)"
  type        = number
  default     = 3
}
# ── ACR ──────────────────────────────────────────────────────
variable "acr_name" {
  description = "Azure Container Registry name (globally unique, alphanumeric only)"
  type        = string
  default     = "acrdeltarouter"
}
# ── Application secrets ──────────────────────────────────────
variable "admin_username" {
  description = "Admin username for routing-service"
  type        = string
  default     = "admin"
}
variable "admin_password" {
  description = "Admin password for routing-service"
  type        = string
  sensitive   = true
}
variable "postgres_user" {
  description = "PostgreSQL username"
  type        = string
  default     = "delta"
}
variable "postgres_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}
variable "postgres_database" {
  description = "PostgreSQL database name"
  type        = string
  default     = "deltarouter"
}