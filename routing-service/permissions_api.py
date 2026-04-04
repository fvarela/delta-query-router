"""Permissions API — metastore external access and EXTERNAL USE SCHEMA management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

import auth
import main as _main  # access _workspace_client, _warehouse_id, _databricks_error_to_http

logger = logging.getLogger("routing-service.permissions_api")

router = APIRouter(tags=["permissions"])


def _require_workspace_client():
    """Return the system-identity WorkspaceClient or raise 503."""
    if _main._workspace_client is None:
        raise HTTPException(
            status_code=503, detail="Databricks workspace not configured"
        )
    return _main._workspace_client


def _require_warehouse_id() -> str:
    """Return the configured SQL Warehouse ID or raise 400."""
    if not _main._warehouse_id:
        raise HTTPException(status_code=400, detail="No SQL warehouse selected")
    return _main._warehouse_id


# ---------------------------------------------------------------------------
# Metastore external access check  (T84 / REQ-001)
# ---------------------------------------------------------------------------


@router.get("/api/metastore/external-access")
async def get_metastore_external_access(
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Check whether external data access is enabled on the workspace metastore."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    try:
        summary = wc.metastores.summary()
    except Exception as e:
        raise _main._databricks_error_to_http(e)
    return {
        "external_access_enabled": bool(summary.external_access_enabled),
        "metastore_name": summary.name,
    }


# ---------------------------------------------------------------------------
# EXTERNAL USE SCHEMA check  (T85 / REQ-002)
# ---------------------------------------------------------------------------


@router.get("/api/databricks/catalogs/{catalog}/schemas/{schema}/external-use")
async def get_external_use_schema(
    catalog: str,
    schema: str,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Check if EXTERNAL USE SCHEMA is granted on a specific schema."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    full_name = f"{catalog}.{schema}"
    try:
        resp = wc.api_client.do(
            "GET",
            f"/api/2.1/unity-catalog/permissions/schema/{full_name}",
        )
    except Exception as e:
        raise _main._databricks_error_to_http(e)

    granted = False
    for assignment in resp.get("privilege_assignments", []):
        if "EXTERNAL_USE_SCHEMA" in (assignment.get("privileges") or []):
            granted = True
            break
    return {"catalog": catalog, "schema": schema, "external_use_schema": granted}


# ---------------------------------------------------------------------------
# EXTERNAL USE SCHEMA grant / revoke  (T86 / REQ-003)
# ---------------------------------------------------------------------------


@router.post("/api/databricks/catalogs/{catalog}/schemas/{schema}/external-use")
async def grant_external_use_schema(
    catalog: str,
    schema: str,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Grant EXTERNAL USE SCHEMA on a schema to the system identity principal."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    wh_id = _require_warehouse_id()

    # Determine the principal (system identity)
    try:
        me = wc.current_user.me()
    except Exception as e:
        raise _main._databricks_error_to_http(e)
    principal = me.user_name

    full_name = f"{catalog}.{schema}"
    sql = f"GRANT EXTERNAL USE SCHEMA ON SCHEMA `{catalog}`.`{schema}` TO `{principal}`"
    try:
        from databricks.sdk.service.sql import StatementState

        response = wc.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=wh_id,
            wait_timeout="30s",
        )
        state = response.status.state if response.status else None
        if state == StatementState.FAILED:
            error_msg = "Unknown error"
            if response.status.error:
                error_msg = response.status.error.message or str(response.status.error)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to grant EXTERNAL USE SCHEMA: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise _main._databricks_error_to_http(e)

    return {
        "catalog": catalog,
        "schema": schema,
        "external_use_schema": True,
        "principal": principal,
    }


@router.delete("/api/databricks/catalogs/{catalog}/schemas/{schema}/external-use")
async def revoke_external_use_schema(
    catalog: str,
    schema: str,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Revoke EXTERNAL USE SCHEMA on a schema from the system identity principal."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    wh_id = _require_warehouse_id()

    # Determine the principal (system identity)
    try:
        me = wc.current_user.me()
    except Exception as e:
        raise _main._databricks_error_to_http(e)
    principal = me.user_name

    full_name = f"{catalog}.{schema}"
    sql = f"REVOKE EXTERNAL USE SCHEMA ON SCHEMA `{catalog}`.`{schema}` FROM `{principal}`"
    try:
        from databricks.sdk.service.sql import StatementState

        response = wc.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=wh_id,
            wait_timeout="30s",
        )
        state = response.status.state if response.status else None
        if state == StatementState.FAILED:
            error_msg = "Unknown error"
            if response.status.error:
                error_msg = response.status.error.message or str(response.status.error)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to revoke EXTERNAL USE SCHEMA: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise _main._databricks_error_to_http(e)

    return {
        "catalog": catalog,
        "schema": schema,
        "external_use_schema": False,
        "principal": principal,
    }
