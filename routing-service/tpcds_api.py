"""TPC-DS API — create, monitor, list, and delete TPC-DS benchmark catalogs."""

from __future__ import annotations

import logging
import textwrap
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import db
import tpcds_queries
import query_features

logger = logging.getLogger("routing-service.tpcds_api")

router = APIRouter(prefix="/api/tpcds", tags=["tpcds"])


def _get_main():
    """Lazy import to avoid circular dependency with main.py."""
    import main as _main

    return _main


# The 25 standard TPC-DS tables
TPCDS_TABLES: list[str] = [
    "call_center",
    "catalog_page",
    "catalog_returns",
    "catalog_sales",
    "customer",
    "customer_address",
    "customer_demographics",
    "date_dim",
    "household_demographics",
    "income_band",
    "inventory",
    "item",
    "promotion",
    "reason",
    "ship_mode",
    "store",
    "store_returns",
    "store_sales",
    "time_dim",
    "warehouse",
    "web_page",
    "web_returns",
    "web_sales",
    "web_site",
    "dbgen_version",
]

VALID_SCALE_FACTORS = {1, 10, 100}


# ---------------------------------------------------------------------------
# Auto-create TPC-DS query collection  (Phase 16 / REQ-001)
# ---------------------------------------------------------------------------


def _create_tpcds_collection(
    record_id: int,
    catalog_name: str,
    schema_name: str,
    scale_factor: int,
) -> int | None:
    """Create a tpcds-tagged collection with 99 rewritten queries.

    Called after TPC-DS data creation succeeds. Idempotent — if a collection
    with the expected name already exists, reuses it.

    Returns the collection ID, or None on error.
    """
    collection_name = f"TPC-DS SF{scale_factor}"
    description = (
        f"Standard TPC-DS benchmark queries for scale factor {scale_factor} "
        f"({catalog_name}.{schema_name})"
    )

    try:
        # Check for existing collection (idempotent)
        existing = db.fetch_one(
            "SELECT id FROM collections WHERE name = %s", (collection_name,)
        )
        if existing:
            collection_id = existing["id"]
            logger.info(
                "TPC-DS collection '%s' already exists (id=%d), reusing",
                collection_name,
                collection_id,
            )
        else:
            row = db.fetch_one(
                "INSERT INTO collections (name, description, tag) "
                "VALUES (%s, %s, 'tpcds') RETURNING id",
                (collection_name, description),
            )
            collection_id = row["id"]

            # Insert 99 rewritten queries and compute AST features
            queries = tpcds_queries.get_queries(catalog_name, schema_name)
            feature_rows: list[tuple[int, str]] = []
            for query_id, sql in queries:
                row = db.fetch_one(
                    "INSERT INTO collection_queries (collection_id, query_text, sequence_number) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (collection_id, sql, query_id),
                )
                feature_rows.append((row["id"], sql))
            stored = query_features.compute_and_store_batch(feature_rows)
            logger.info(
                "Created TPC-DS collection '%s' (id=%d) with %d queries, %d features stored",
                collection_name,
                collection_id,
                len(queries),
                stored,
            )

            # Validate queries with sqlglot (informational only)
            validation = tpcds_queries.validate_queries(catalog_name, schema_name)
            ok = sum(1 for _, err in validation if err is None)
            logger.info("TPC-DS query validation: %d/99 parsed successfully", ok)
            for qid, err in validation:
                if err is not None:
                    logger.warning("TPC-DS Q%d parse warning: %s", qid, err)

        # Link collection to tpcds_catalogs record
        db.execute(
            "UPDATE tpcds_catalogs SET collection_id = %s, updated_at = NOW() "
            "WHERE id = %s",
            (collection_id, record_id),
        )
        return collection_id

    except Exception:
        logger.exception(
            "Failed to create TPC-DS collection for catalog '%s'", catalog_name
        )
        return None


def _require_workspace_client():
    _m = _get_main()
    if _m._workspace_client is None:
        raise HTTPException(
            status_code=503, detail="Databricks workspace not configured"
        )
    return _m._workspace_client


def _require_warehouse_id() -> str:
    _m = _get_main()
    if not _m._warehouse_id:
        raise HTTPException(status_code=400, detail="No SQL warehouse selected")
    return _m._warehouse_id


def _execute_sql(wc, wh_id: str, sql: str, poll_interval: float = 5.0) -> None:
    """Execute a SQL statement synchronously via Databricks Statement API.

    Uses the maximum wait_timeout (50s). If the statement is still running
    after the initial wait, polls until completion.

    Raises HTTPException on failure.
    """
    import time
    from databricks.sdk.service.sql import StatementState

    response = wc.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=wh_id,
        wait_timeout="50s",
    )
    state = response.status.state if response.status else None

    # Poll if still running after initial wait
    while state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(poll_interval)
        response = wc.statement_execution.get_statement(response.statement_id)
        state = response.status.state if response.status else None

    if state == StatementState.FAILED:
        error_msg = "Unknown error"
        if response.status.error:
            error_msg = response.status.error.message or str(response.status.error)
        raise HTTPException(
            status_code=502, detail=f"SQL execution failed: {error_msg}"
        )
    if state != StatementState.SUCCEEDED:
        raise HTTPException(
            status_code=502,
            detail=f"SQL execution in unexpected state: {state}",
        )


# ---------------------------------------------------------------------------
# Samples catalog detection  (T94 / REQ-011)
# ---------------------------------------------------------------------------


def check_samples_available(wc) -> bool:
    """Check whether samples.tpcds_sf1 exists in the workspace."""
    try:
        wc.catalogs.get("samples")
    except Exception:
        return False
    try:
        wc.schemas.get("samples.tpcds_sf1")
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Preflight check  (T94 / REQ-004)
# ---------------------------------------------------------------------------


@router.get("/preflight")
async def tpcds_preflight(
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Return prerequisite status for TPC-DS creation."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()

    # Metastore external access
    external_access = False
    try:
        summary = wc.metastores.summary()
        external_access = bool(summary.external_access_enabled)
    except Exception:
        pass

    # Samples availability
    samples_available = check_samples_available(wc)

    return {
        "samples_available": samples_available,
        "metastore_external_access": external_access,
        "warehouse_configured": bool(_get_main()._warehouse_id),
    }


# ---------------------------------------------------------------------------
# Detect TPC-DS scale factors in workspace  (T104 / REQ-005)
# ---------------------------------------------------------------------------

TPCDS_CATALOG = "delta_router_tpcds"
TPCDS_SCALE_FACTORS = ["sf1", "sf10", "sf100"]


@router.get("/detect")
async def detect_tpcds(
    user: auth.UserContext = Depends(auth.verify_token),
    catalog: str | None = None,
):
    """Detect which TPC-DS scale factors exist.

    Checks the tpcds_catalogs DB table for 'ready' records, then falls back
    to probing the workspace via Unity Catalog.

    If `catalog` query param is given, probes only that catalog.
    Otherwise probes ALL visible catalogs (excluding system/samples).

    Returns: {"sf1": {...}, "sf10": {...}, "sf100": {...}} where each value
    has `found: bool` and optional `catalog_name`, `schema_name`.
    """
    result: dict[str, dict] = {sf: {"found": False} for sf in TPCDS_SCALE_FACTORS}

    # Check DB records first — these are authoritative for catalogs we created
    rows = db.fetch_all(
        "SELECT scale_factor, catalog_name, schema_name "
        "FROM tpcds_catalogs WHERE status = 'ready'"
    )
    for row in rows:
        sf_key = f"sf{row['scale_factor']}"
        if sf_key in result:
            result[sf_key] = {
                "found": True,
                "catalog_name": row["catalog_name"],
                "schema_name": row["schema_name"],
                "registered": True,
            }

    # For any still-not-found SFs, probe UC as a fallback
    _main = _get_main()
    wc = _main._workspace_client
    if wc:
        # Determine which catalogs to probe
        if catalog:
            catalogs_to_probe = [catalog]
        else:
            # Probe all visible catalogs (skip system ones)
            try:
                all_cats = list(wc.catalogs.list())
                catalogs_to_probe = [
                    c.name
                    for c in all_cats
                    if c.name not in ("system", "samples", "__databricks_internal")
                ]
            except Exception:
                catalogs_to_probe = [TPCDS_CATALOG]

        for sf in TPCDS_SCALE_FACTORS:
            if result[sf]["found"]:
                continue
            for cat_name in catalogs_to_probe:
                try:
                    wc.schemas.get(f"{cat_name}.{sf}")
                    result[sf] = {
                        "found": True,
                        "catalog_name": cat_name,
                        "schema_name": sf,
                        "registered": False,
                    }
                    break  # Found this SF, no need to check more catalogs
                except Exception:
                    pass

    return result


# ---------------------------------------------------------------------------
# Register existing TPC-DS data  (Phase 18 / schema drift recovery)
# ---------------------------------------------------------------------------


class TpcdsRegisterRequest(BaseModel):
    catalog_name: str
    schema_name: str
    scale_factor: int


@router.post("/register")
async def register_tpcds(
    body: TpcdsRegisterRequest,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Register existing TPC-DS data without creating tables.

    Verifies that the schema exists in Unity Catalog and contains at least some
    TPC-DS tables, then creates a tpcds_catalogs record (status 'ready') and
    the auto-generated TPC-DS query collection with 99 queries.

    Use this when TPC-DS tables were already created (e.g. in a previous
    session or after a DB schema reset that wiped tpcds_catalogs records).
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if body.scale_factor not in VALID_SCALE_FACTORS:
        raise HTTPException(
            status_code=400,
            detail=f"scale_factor must be one of {sorted(VALID_SCALE_FACTORS)}",
        )
    wc = _require_workspace_client()

    # Verify schema exists in UC
    full_schema = f"{body.catalog_name}.{body.schema_name}"
    try:
        wc.schemas.get(full_schema)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{full_schema}' not found in Unity Catalog",
        )

    # Verify at least some TPC-DS tables are present (spot-check 3 core tables)
    spot_check = ["customer", "store_sales", "date_dim"]
    found = 0
    for table in spot_check:
        try:
            wc.tables.get(f"{full_schema}.{table}")
            found += 1
        except Exception:
            pass
    if found == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No TPC-DS tables found in '{full_schema}'. "
            f"Checked: {', '.join(spot_check)}",
        )

    # Check for existing record (idempotent)
    existing = db.fetch_one(
        "SELECT id, status, collection_id FROM tpcds_catalogs "
        "WHERE catalog_name = %s AND schema_name = %s AND scale_factor = %s",
        (body.catalog_name, body.schema_name, body.scale_factor),
    )
    if existing and existing["status"] == "ready" and existing["collection_id"]:
        return {
            "message": "Already registered",
            "tpcds_catalog_id": existing["id"],
            "collection_id": existing["collection_id"],
        }

    # Delete stale record if exists (failed/creating)
    if existing:
        db.execute("DELETE FROM tpcds_catalogs WHERE id = %s", (existing["id"],))

    # Create tpcds_catalogs record as 'ready'
    row = db.fetch_one(
        "INSERT INTO tpcds_catalogs "
        "(catalog_name, schema_name, scale_factor, status, tables_created, total_tables) "
        "VALUES (%s, %s, %s, 'ready', %s, %s) RETURNING id",
        (
            body.catalog_name,
            body.schema_name,
            body.scale_factor,
            len(TPCDS_TABLES),
            len(TPCDS_TABLES),
        ),
    )
    record_id = row["id"]

    # Create TPC-DS collection with 99 queries
    collection_id = _create_tpcds_collection(
        record_id, body.catalog_name, body.schema_name, body.scale_factor
    )

    logger.info(
        "Registered existing TPC-DS SF%d at %s.%s (record=%d, collection=%s)",
        body.scale_factor,
        body.catalog_name,
        body.schema_name,
        record_id,
        collection_id,
    )
    return {
        "message": "Registered successfully",
        "tpcds_catalog_id": record_id,
        "collection_id": collection_id,
    }


# ---------------------------------------------------------------------------
# Create TPC-DS catalog  (T90 SF1 CTAS / T91 SF10/SF100 Job)
# ---------------------------------------------------------------------------


class TpcdsCreateRequest(BaseModel):
    catalog_name: str
    schema_name: str
    scale_factor: int
    use_existing_catalog: bool = False


def _sf1_ctas_sync(
    record_id: int,
    catalog_name: str,
    schema_name: str,
    wc,
    wh_id: str,
    use_existing_catalog: bool = False,
) -> None:
    """Run SF1 CTAS creation in a background thread.

    Updates tpcds_catalogs as it goes: tables_created incremented per table,
    status set to 'ready' on success or 'failed' on error.
    """
    try:
        # Create catalog and schema
        if not use_existing_catalog:
            _execute_sql(wc, wh_id, f"CREATE CATALOG IF NOT EXISTS `{catalog_name}`")
        _execute_sql(
            wc,
            wh_id,
            f"CREATE SCHEMA IF NOT EXISTS `{catalog_name}`.`{schema_name}`",
        )

        # CTAS for each table
        for i, table in enumerate(TPCDS_TABLES):
            try:
                _execute_sql(
                    wc,
                    wh_id,
                    f"CREATE TABLE `{catalog_name}`.`{schema_name}`.`{table}` "
                    f"AS SELECT * FROM samples.tpcds_sf1.`{table}`",
                )
            except Exception as table_err:
                # dbgen_version may not exist in samples — skip gracefully
                if table == "dbgen_version":
                    logger.info(
                        "Skipping dbgen_version (not found in samples): %s",
                        table_err,
                    )
                else:
                    raise
            db.execute(
                "UPDATE tpcds_catalogs SET tables_created = %s, updated_at = NOW() "
                "WHERE id = %s",
                (i + 1, record_id),
            )

        # Grant EXTERNAL USE SCHEMA
        try:
            me = wc.current_user.me()
            principal = me.user_name
            _execute_sql(
                wc,
                wh_id,
                f"GRANT EXTERNAL USE SCHEMA ON SCHEMA "
                f"`{catalog_name}`.`{schema_name}` TO `{principal}`",
            )
        except Exception as grant_err:
            logger.warning("Failed to grant EXTERNAL USE SCHEMA: %s", grant_err)

        # Tag catalog as system-managed
        try:
            wc.catalogs.update(
                catalog_name, properties={"delta_router_managed": "true"}
            )
        except Exception as tag_err:
            logger.warning("Failed to tag catalog: %s", tag_err)

        # Mark as ready
        db.execute(
            "UPDATE tpcds_catalogs SET status = 'ready', updated_at = NOW() "
            "WHERE id = %s",
            (record_id,),
        )
        logger.info("TPC-DS SF1 catalog '%s' created successfully", catalog_name)

        # Auto-create query collection (Phase 16)
        _create_tpcds_collection(record_id, catalog_name, schema_name, 1)

    except Exception as e:
        logger.exception("TPC-DS SF1 creation failed for '%s'", catalog_name)
        db.execute(
            "UPDATE tpcds_catalogs SET status = 'failed', error_message = %s, "
            "updated_at = NOW() WHERE id = %s",
            (str(e)[:2000], record_id),
        )


def _build_dsdgen_script(
    catalog_name: str,
    schema_name: str,
    scale_factor: int,
    use_existing_catalog: bool = False,
) -> str:
    """Build the Python script content for DuckDB dsdgen + Spark write."""
    tables_str = ", ".join(f'"{t}"' for t in TPCDS_TABLES if t != "dbgen_version")
    create_catalog_line = (
        ""
        if use_existing_catalog
        else f'spark.sql(f"CREATE CATALOG IF NOT EXISTS `{{catalog_name}}`")'
    )
    return textwrap.dedent(f"""\
        import subprocess
        import sys
        import os

        # Install DuckDB
        subprocess.check_call([sys.executable, "-m", "pip", "install", "duckdb"])

        import duckdb

        con = duckdb.connect()
        con.install_extension("tpcds")
        con.load_extension("tpcds")

        # Generate TPC-DS data
        print(f"Generating TPC-DS data at SF{scale_factor}...")
        con.execute("CALL dsdgen(sf = {scale_factor})")
        print("Data generation complete.")

        # Export each table to Parquet
        tables = [{tables_str}]
        export_dir = "/local_disk0/tpcds"
        os.makedirs(export_dir, exist_ok=True)
        for table in tables:
            out_path = f"{{export_dir}}/{{table}}.parquet"
            con.execute(f"COPY {{table}} TO '{{out_path}}' (FORMAT PARQUET)")
            print(f"Exported {{table}} to {{out_path}}")
        con.close()

        # Use Spark to create managed Delta tables
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()

        catalog_name = "{catalog_name}"
        schema_name = "{schema_name}"
        {create_catalog_line}
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{{catalog_name}}`.`{{schema_name}}`")

        for table in tables:
            parquet_path = f"{{export_dir}}/{{table}}.parquet"
            full_table = f"`{{catalog_name}}`.`{{schema_name}}`.`{{table}}`"
            df = spark.read.parquet(parquet_path)
            df.write.format("delta").mode("overwrite").saveAsTable(full_table)
            print(f"Created managed table {{full_table}}")

        print("All TPC-DS tables created successfully!")
    """)


def _get_cluster_spec(scale_factor: int) -> dict:
    """Return cluster spec for DuckDB dsdgen job based on scale factor."""
    if scale_factor <= 10:
        # SF10: ~12GB disk needed, 16GB RAM, 4 cores
        node_type = "Standard_D4s_v5"
    else:
        # SF100: ~120GB disk needed, 64GB RAM, 16 cores
        node_type = "Standard_D16s_v5"

    return {
        "spark_version": "14.3.x-scala2.12",  # LTS
        "node_type_id": node_type,
        "num_workers": 0,  # single-node (driver-only)
        "spark_conf": {
            "spark.master": "local[*]",
            "spark.databricks.cluster.profile": "singleNode",
        },
        "custom_tags": {
            "ResourceClass": "SingleNode",
        },
    }


def _submit_dsdgen_job(
    wc,
    catalog_name: str,
    schema_name: str,
    scale_factor: int,
    use_existing_catalog: bool = False,
) -> str:
    """Submit a one-time Databricks Job for dsdgen data generation.

    Returns the run_id as a string.
    """
    script_content = _build_dsdgen_script(
        catalog_name, schema_name, scale_factor, use_existing_catalog
    )
    cluster_spec = _get_cluster_spec(scale_factor)

    # Use the REST API directly for runs/submit
    payload = {
        "run_name": f"delta-router-tpcds-sf{scale_factor}-{catalog_name}",
        "tasks": [
            {
                "task_key": "generate_tpcds",
                "spark_python_task": {
                    "python_file": "dbfs:/tmp/delta_router_tpcds_gen.py",
                },
                "new_cluster": cluster_spec,
            }
        ],
    }

    # First, upload the script to DBFS
    import base64

    encoded = base64.b64encode(script_content.encode()).decode()
    wc.api_client.do(
        "POST",
        "/api/2.0/dbfs/put",
        body={
            "path": "/tmp/delta_router_tpcds_gen.py",
            "contents": encoded,
            "overwrite": True,
        },
    )

    # Submit the run
    result = wc.api_client.do(
        "POST",
        "/api/2.1/jobs/runs/submit",
        body=payload,
    )
    run_id = str(result["run_id"])
    return run_id


@router.post("/create")
async def create_tpcds(
    body: TpcdsCreateRequest,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Create a TPC-DS catalog with tables at the specified scale factor."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    wh_id = _require_warehouse_id()

    # Validate scale factor
    if body.scale_factor not in VALID_SCALE_FACTORS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scale_factor: {body.scale_factor}. "
            f"Must be one of {sorted(VALID_SCALE_FACTORS)}",
        )

    # Check for duplicate catalog name
    existing = db.fetch_one(
        "SELECT id, status FROM tpcds_catalogs WHERE catalog_name = %s",
        (body.catalog_name,),
    )
    if existing:
        if existing["status"] == "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Catalog '{body.catalog_name}' already exists and is ready",
            )
        # Previous attempt failed or stale — remove old record and retry
        logger.info(
            "Removing stale tpcds_catalogs record id=%d (status=%s) for retry",
            existing["id"],
            existing["status"],
        )
        db.execute("DELETE FROM tpcds_catalogs WHERE id = %s", (existing["id"],))

    # Insert tracking record
    row = db.fetch_one(
        "INSERT INTO tpcds_catalogs (catalog_name, schema_name, scale_factor, status) "
        "VALUES (%s, %s, %s, 'creating') RETURNING *",
        (body.catalog_name, body.schema_name, body.scale_factor),
    )
    record_id = row["id"]

    # Determine creation method
    if body.scale_factor == 1 and check_samples_available(wc):
        # SF1 via CTAS — run in background thread
        thread = threading.Thread(
            target=_sf1_ctas_sync,
            args=(record_id, body.catalog_name, body.schema_name, wc, wh_id),
            kwargs={"use_existing_catalog": body.use_existing_catalog},
            daemon=True,
        )
        thread.start()
        return {
            "id": record_id,
            "catalog_name": body.catalog_name,
            "schema_name": body.schema_name,
            "scale_factor": body.scale_factor,
            "status": "creating",
            "method": "ctas",
        }
    else:
        # SF10/SF100 (or SF1 without samples) via Databricks Job
        try:
            run_id = _submit_dsdgen_job(
                wc,
                body.catalog_name,
                body.schema_name,
                body.scale_factor,
                use_existing_catalog=body.use_existing_catalog,
            )
        except Exception as e:
            db.execute(
                "UPDATE tpcds_catalogs SET status = 'failed', "
                "error_message = %s, updated_at = NOW() WHERE id = %s",
                (str(e)[:2000], record_id),
            )
            raise _get_main()._databricks_error_to_http(e)

        db.execute(
            "UPDATE tpcds_catalogs SET job_run_id = %s, updated_at = NOW() "
            "WHERE id = %s",
            (run_id, record_id),
        )
        return {
            "id": record_id,
            "catalog_name": body.catalog_name,
            "schema_name": body.schema_name,
            "scale_factor": body.scale_factor,
            "status": "creating",
            "method": "job",
            "job_run_id": run_id,
        }


# ---------------------------------------------------------------------------
# Status polling  (T92 / REQ-008)
# ---------------------------------------------------------------------------


@router.get("/status/{tpcds_id}")
async def get_tpcds_status(
    tpcds_id: int,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Get the current status of a TPC-DS creation job."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    row = db.fetch_one("SELECT * FROM tpcds_catalogs WHERE id = %s", (tpcds_id,))
    if not row:
        raise HTTPException(status_code=404, detail="TPC-DS record not found")

    result = {
        "id": row["id"],
        "catalog_name": row["catalog_name"],
        "schema_name": row["schema_name"],
        "scale_factor": row["scale_factor"],
        "status": row["status"],
        "tables_created": row["tables_created"],
        "total_tables": row["total_tables"],
        "job_run_id": row["job_run_id"],
        "error_message": row["error_message"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }

    # If the record has a job_run_id and is still creating, poll Databricks
    if row["status"] == "creating" and row["job_run_id"]:
        wc = _require_workspace_client()
        try:
            run_info = wc.api_client.do(
                "GET",
                f"/api/2.1/jobs/runs/get",
                data={"run_id": row["job_run_id"]},
            )
            run_state = run_info.get("state", {})
            life_cycle_state = run_state.get("life_cycle_state", "UNKNOWN")
            result_state = run_state.get("result_state")

            result["job_state"] = life_cycle_state

            # Calculate elapsed time
            start_time_ms = run_info.get("start_time")
            if start_time_ms:
                elapsed_s = (time.time() * 1000 - start_time_ms) / 1000
                result["elapsed_time_seconds"] = round(elapsed_s, 1)

            if life_cycle_state == "TERMINATED":
                if result_state == "SUCCESS":
                    # Job completed — finalize
                    _finalize_job_success(
                        row["id"],
                        row["catalog_name"],
                        row["schema_name"],
                        wc,
                    )
                    result["status"] = "ready"
                    result["tables_created"] = row["total_tables"]
                else:
                    # Job failed
                    error_msg = run_state.get(
                        "state_message", f"Job terminated with result: {result_state}"
                    )
                    db.execute(
                        "UPDATE tpcds_catalogs SET status = 'failed', "
                        "error_message = %s, updated_at = NOW() WHERE id = %s",
                        (error_msg[:2000], row["id"]),
                    )
                    result["status"] = "failed"
                    result["error_message"] = error_msg

        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to poll job status: %s", e)
            result["job_state"] = "UNKNOWN"

    return result


def _finalize_job_success(
    record_id: int,
    catalog_name: str,
    schema_name: str,
    wc,
) -> None:
    """After a dsdgen Job completes successfully, tag catalog and grant permissions."""
    # Tag catalog as system-managed
    try:
        wc.catalogs.update(catalog_name, properties={"delta_router_managed": "true"})
    except Exception as e:
        logger.warning("Failed to tag catalog '%s': %s", catalog_name, e)

    # Grant EXTERNAL USE SCHEMA
    if _get_main()._warehouse_id:
        try:
            me = wc.current_user.me()
            principal = me.user_name
            _execute_sql(
                wc,
                _get_main()._warehouse_id,
                f"GRANT EXTERNAL USE SCHEMA ON SCHEMA "
                f"`{catalog_name}`.`{schema_name}` TO `{principal}`",
            )
        except Exception as e:
            logger.warning("Failed to grant EXTERNAL USE SCHEMA: %s", e)

    # Update record
    db.execute(
        "UPDATE tpcds_catalogs SET status = 'ready', tables_created = total_tables, "
        "updated_at = NOW() WHERE id = %s",
        (record_id,),
    )

    # Auto-create query collection (Phase 16)
    row = db.fetch_one(
        "SELECT scale_factor FROM tpcds_catalogs WHERE id = %s", (record_id,)
    )
    if row:
        _create_tpcds_collection(
            record_id, catalog_name, schema_name, row["scale_factor"]
        )


# ---------------------------------------------------------------------------
# List available Unity Catalog catalogs (for "use existing" picker)
# ---------------------------------------------------------------------------


@router.get("/available-catalogs")
async def list_available_catalogs(
    user: auth.UserContext = Depends(auth.verify_token),
):
    """List UC catalogs the current user can see, for the 'use existing catalog' picker."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()
    try:
        catalogs = list(wc.catalogs.list())
        return [
            {
                "name": c.name,
                "comment": getattr(c, "comment", None) or "",
            }
            for c in catalogs
            if c.name not in ("system", "samples", "__databricks_internal")
        ]
    except Exception as e:
        logger.warning("Failed to list UC catalogs: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to list catalogs: {e}")


# ---------------------------------------------------------------------------
# List and delete catalogs  (T93 / REQ-009)
# ---------------------------------------------------------------------------


@router.get("/catalogs")
async def list_tpcds_catalogs(
    user: auth.UserContext = Depends(auth.verify_token),
):
    """List all system-created TPC-DS catalogs."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    rows = db.fetch_all("SELECT * FROM tpcds_catalogs ORDER BY created_at DESC")
    return [
        {
            "id": r["id"],
            "catalog_name": r["catalog_name"],
            "schema_name": r["schema_name"],
            "scale_factor": r["scale_factor"],
            "status": r["status"],
            "tables_created": r["tables_created"],
            "total_tables": r["total_tables"],
            "error_message": r["error_message"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.delete("/catalogs/{catalog_name}")
async def delete_tpcds_catalog(
    catalog_name: str,
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Delete a system-created TPC-DS catalog and all its contents."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wc = _require_workspace_client()

    # Only allow deletion of system-created catalogs
    row = db.fetch_one(
        "SELECT * FROM tpcds_catalogs WHERE catalog_name = %s",
        (catalog_name,),
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog '{catalog_name}' was not created by Delta Router",
        )

    # Mark as deleting
    db.execute(
        "UPDATE tpcds_catalogs SET status = 'deleting', updated_at = NOW() "
        "WHERE catalog_name = %s",
        (catalog_name,),
    )

    # Delete from Databricks (force=True drops all schemas and tables)
    try:
        wc.catalogs.delete(catalog_name, force=True)
    except Exception as e:
        # If the catalog doesn't exist in Databricks, that's fine — clean up the record
        err_str = str(e).lower()
        if "not found" in err_str or "does not exist" in err_str:
            logger.info(
                "Catalog '%s' not found in Databricks (already deleted?)", catalog_name
            )
        else:
            # Restore status on unexpected errors
            db.execute(
                "UPDATE tpcds_catalogs SET status = 'failed', "
                "error_message = %s, updated_at = NOW() WHERE catalog_name = %s",
                (f"Deletion failed: {e}"[:2000], catalog_name),
            )
            raise _get_main()._databricks_error_to_http(e)

    # Cascade-delete linked TPC-DS collection (Phase 16)
    collection_id = row.get("collection_id")
    if collection_id is not None:
        try:
            # Deleting the collection cascades to collection_queries,
            # benchmark_definitions → benchmark_runs → benchmark_results +
            # benchmark_engine_warmups via ON DELETE CASCADE FK constraints.
            db.execute("DELETE FROM collections WHERE id = %s", (collection_id,))
            logger.info(
                "Deleted collection %d and associated benchmarks for TPC-DS catalog '%s'",
                collection_id,
                catalog_name,
            )
        except Exception:
            logger.exception(
                "Failed to delete collection %d for catalog '%s'",
                collection_id,
                catalog_name,
            )

    # Remove tracking record
    db.execute("DELETE FROM tpcds_catalogs WHERE catalog_name = %s", (catalog_name,))

    return {"deleted": True, "catalog_name": catalog_name}
