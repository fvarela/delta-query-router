"""User and system identity permission checks against Unity Catalog"""

import logging
from databricks.sdk import WorkspaceClient

logger = logging.getLogger("routing-service.permissions")

def check_user_table_access(
        table_names: list[str],
        user_workspace_client: WorkspaceClient, 
) -> list[str]:
    """Check which tables the user cannot access.
    
    Calls tables.get() with the user's credentials for each table.
    Returns a list of table names that are inaccessible (empty = all OK).
    Fails closed: any exception (403, 404, network) counts as denied
    """
    denied = []
    for table_name in table_names:
        try:
            user_workspace_client.tables.get(table_name)
        except Exception as exc:
            logger.debug(f"User access denied for %s: %s", table_name, exc)
            denied.append(table_name)
    return denied

def check_system_table_access(
        table_names: list[str],
        system_workspace_client: WorkspaceClient, 
) -> list[str]:
    """Check which tables the system identity cannot access.
    
    Same logic as check_user_table_access, but used to detect cases where
    the system identity (admin PAT / service principal) lacks access.
    Returns a list of inaccessible table names (empty = all OK).
    """
    denied = []
    for table_name in table_names:
        try:
            system_workspace_client.tables.get(table_name)
        except Exception as exc:
            logger.debug(f"System access denied for %s: %s", table_name, exc)
            denied.append(table_name)
    return denied