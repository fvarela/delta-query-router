targetScope = 'subscription'

@description('Azure region; must be the Databricks workspace region.')
param location string

@description('Short prefix for resource names: lowercase letters and digits, used in the storage account name.')
@minLength(3)
@maxLength(10)
param prefix string = 'dqr'

@description('Resource group that holds everything.')
param resourceGroupName string = 'rg-${prefix}'

@description('Object id of a user or service principal that may write the Delta files (Storage Blob Data Contributor on the tpcds container). Empty means no grant.')
param dataWriterPrincipalId string = ''

var tags = {
  project: 'delta-router'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    prefix: prefix
    uniqueSuffix: uniqueString(subscription().id, resourceGroupName)
    dataWriterPrincipalId: dataWriterPrincipalId
    tags: tags
  }
}
