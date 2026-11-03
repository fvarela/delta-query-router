param location string
@minLength(3)
@maxLength(10)
param prefix string
param uniqueSuffix string
param dataWriterPrincipalId string
param tags object

// Storage Blob Data Contributor
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)

// 3-24 lowercase letters and digits.
var storageAccountName = toLower(take('${prefix}${uniqueSuffix}', 24))

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource tpcdsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'tpcds'
}

// Identity that Unity Catalog uses to reach the container.
resource accessConnector 'Microsoft.Databricks/accessConnectors@2024-05-01' = {
  name: '${prefix}-access-connector'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
}

resource connectorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(tpcdsContainer.id, accessConnector.id, storageBlobDataContributor)
  scope: tpcdsContainer
  properties: {
    roleDefinitionId: roleDefinitionId
    principalId: accessConnector.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Optional: lets the author write the Delta files from their own machine.
resource writerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(dataWriterPrincipalId)) {
  name: guid(tpcdsContainer.id, dataWriterPrincipalId, storageBlobDataContributor)
  scope: tpcdsContainer
  properties: {
    roleDefinitionId: roleDefinitionId
    principalId: dataWriterPrincipalId
  }
}
