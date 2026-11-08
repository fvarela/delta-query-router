using 'main.bicep'

param location = 'westus2'
param prefix = 'dqr'
param resourceGroupName = 'rg-dqr'
param ucIdentityResourceId = readEnvironmentVariable('UC_IDENTITY_RESOURCE_ID')
