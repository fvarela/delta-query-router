param location string
@minLength(3)
@maxLength(10)
param prefix string
param uniqueSuffix string
param ucIdentityResourceId string
param dataWriterPrincipalId string
param tags object

// Storage Blob Data Contributor
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)

// Storage Blob Delegator: lets Unity Catalog get a user delegation key when its access is
// limited to one container. Grants no data access.
var storageBlobDelegator = 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
var delegatorRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDelegator)

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

// Identity that Unity Catalog uses to reach the storage: the user-assigned identity of
// the dev workspace's existing Access Connector. Only read here, never created or changed.
var ucIdentityParts = split(ucIdentityResourceId, '/')

resource ucIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  scope: resourceGroup(ucIdentityParts[2], ucIdentityParts[4])
  name: ucIdentityParts[8]
}

resource ucIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(tpcdsContainer.id, ucIdentityResourceId, storageBlobDataContributor)
  scope: tpcdsContainer
  properties: {
    roleDefinitionId: roleDefinitionId
    principalId: ucIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ucIdentityDelegatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, ucIdentityResourceId, storageBlobDelegator)
  scope: storageAccount
  properties: {
    roleDefinitionId: delegatorRoleDefinitionId
    principalId: ucIdentity.properties.principalId
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
