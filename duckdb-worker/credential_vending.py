"""Credential vending for Unity Catalog tables.

Fetches temporary cloud storage credentials from Databricks Unity Catalog
and resolves Delta table data files to signed HTTPS URLs that DuckDB can
read via its httpfs extension.

Flow:
  1. GET /api/2.1/unity-catalog/tables/{full_name}  -> table_id, storage_location
  2. POST /api/2.1/unity-catalog/temporary-table-credentials
       {table_id, operation: "READ"}  -> SAS token (Azure) / STS (AWS)
  3. deltalake.DeltaTable(storage_location, storage_options={sas_token})
       -> parse Delta log (v2Checkpoint, deletionVectors supported)
       -> extract file URIs
  4. Convert ABFSS URIs to signed HTTPS URLs
  5. DuckDB reads parquet files via read_parquet() + httpfs

Why not use deltalake's to_pyarrow_table() directly?
  deltalake-python's pyarrow bridge doesn't yet support v2Checkpoint and
  deletionVectors reader features. But the Rust core CAN parse the Delta
  log and extract file metadata. We use deltalake for metadata only and
  let DuckDB's httpfs read the actual parquet files.

Why not use DuckDB's native delta_scan()?
  DuckDB's Azure extension uses a C++ SDK that fails with SSL CA cert
  errors due to TLS interception in this environment. DuckDB's httpfs
  extension (using libcurl) works fine with the system's CA store.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from deltalake import DeltaTable

logger = logging.getLogger(__name__)

# Pre-compiled pattern for parsing ABFSS URLs
_ABFSS_PATTERN = re.compile(r"abfss://([^@]+)@([^.]+)\.dfs\.core\.windows\.net/(.*)")


class CredentialVendingError(Exception):
    """Raised when credential vending or Delta table loading fails."""

    def __init__(self, table_name: str, message: str):
        self.table_name = table_name
        super().__init__(f"[{table_name}] {message}")


@dataclass
class TableCredentials:
    """Temporary credentials for accessing a Unity Catalog table's storage."""

    table_id: str
    storage_location: str
    sas_token: str | None = None  # Azure
    aws_temp_credentials: dict[str, str] | None = None  # AWS (future)


@dataclass
class ResolvedTable:
    """A Delta table resolved to signed parquet file URLs for DuckDB.

    Attributes:
        full_name: Three-part Unity Catalog name (catalog.schema.table).
        file_urls: List of signed HTTPS URLs to parquet data files.
        schema_json: Delta table schema as JSON string.
        has_deletion_vectors: Whether any files have active deletion vectors.
            If True, row-level filtering is needed (not yet implemented —
            tables with active DVs should be read with caution).
    """

    full_name: str
    file_urls: list[str] = field(default_factory=list)
    schema_json: str = ""
    has_deletion_vectors: bool = False


def _make_request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an authenticated HTTP request to the Databricks REST API."""
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()
        except Exception:
            pass
        raise CredentialVendingError(
            url,
            f"HTTP {e.code}: {error_body[:500]}" if error_body else f"HTTP {e.code}",
        ) from e
    except urllib.error.URLError as e:
        raise CredentialVendingError(url, f"Connection error: {e.reason}") from e


def _abfss_to_https(abfss_uri: str, sas_token: str) -> str:
    """Convert an ABFSS URI to a signed HTTPS URL (DFS endpoint).

    Example:
        abfss://container@account.dfs.core.windows.net/path/file.parquet
        -> https://account.dfs.core.windows.net/container/path/file.parquet?<sas_token>
    """
    m = _ABFSS_PATTERN.match(abfss_uri)
    if not m:
        raise ValueError(f"Cannot parse ABFSS URI: {abfss_uri}")
    container, account, path = m.group(1), m.group(2), m.group(3)
    return f"https://{account}.dfs.core.windows.net/{container}/{path}?{sas_token}"


def get_table_info(host: str, token: str, full_name: str) -> dict[str, Any]:
    """Fetch table metadata from Unity Catalog REST API."""
    host = host.rstrip("/")
    url = f"{host}/api/2.1/unity-catalog/tables/{full_name}"
    logger.info("Fetching table info: %s", full_name)
    return _make_request(url, token)


def get_temporary_credentials(host: str, token: str, table_id: str) -> dict[str, Any]:
    """Request temporary storage credentials for a table."""
    host = host.rstrip("/")
    url = f"{host}/api/2.1/unity-catalog/temporary-table-credentials"
    logger.info("Requesting temp credentials for table_id: %s", table_id)
    return _make_request(
        url,
        token,
        method="POST",
        body={"table_id": table_id, "operation": "READ"},
    )


def vend_credentials(host: str, token: str, full_name: str) -> TableCredentials:
    """Get table info + temporary credentials for a single table.

    Raises:
        CredentialVendingError if any API call fails.
    """
    # Step 1: Get table metadata
    try:
        table_info = get_table_info(host, token, full_name)
    except CredentialVendingError:
        raise
    except Exception as e:
        raise CredentialVendingError(full_name, f"Failed to get table info: {e}") from e

    table_id = table_info.get("table_id")
    storage_location = table_info.get("storage_location")

    if not table_id:
        raise CredentialVendingError(full_name, "No table_id in API response")
    if not storage_location:
        raise CredentialVendingError(
            full_name,
            "No storage_location — table may be a view or federated table",
        )

    # Step 2: Get temporary credentials
    try:
        cred_response = get_temporary_credentials(host, token, table_id)
    except CredentialVendingError:
        raise
    except Exception as e:
        raise CredentialVendingError(
            full_name, f"Failed to get temp credentials: {e}"
        ) from e

    # Extract cloud-specific credentials
    sas_info = cred_response.get("azure_user_delegation_sas")
    aws_info = cred_response.get("aws_temp_credentials")

    if sas_info:
        return TableCredentials(
            table_id=table_id,
            storage_location=storage_location,
            sas_token=sas_info["sas_token"],
        )
    elif aws_info:
        return TableCredentials(
            table_id=table_id,
            storage_location=storage_location,
            aws_temp_credentials=aws_info,
        )
    else:
        raise CredentialVendingError(
            full_name,
            "No supported credentials in response (expected "
            "azure_user_delegation_sas or aws_temp_credentials)",
        )


def resolve_delta_files(creds: TableCredentials, full_name: str) -> ResolvedTable:
    """Use deltalake to parse the Delta log and extract signed file URLs.

    deltalake's Rust core handles v2Checkpoint and deletionVectors reader
    features for Delta log parsing. We extract the file URIs and convert
    them to signed HTTPS URLs for DuckDB's httpfs to read.

    Args:
        creds: TableCredentials with storage_location and cloud tokens.
        full_name: The three-part table name (for error messages).

    Returns:
        ResolvedTable with signed HTTPS URLs to parquet data files.

    Raises:
        CredentialVendingError if the Delta log can't be parsed.
    """
    storage_options: dict[str, str] = {}
    if creds.sas_token:
        storage_options["sas_token"] = creds.sas_token
    elif creds.aws_temp_credentials:
        storage_options["aws_access_key_id"] = creds.aws_temp_credentials.get(
            "access_key_id", ""
        )
        storage_options["aws_secret_access_key"] = creds.aws_temp_credentials.get(
            "secret_access_key", ""
        )
        storage_options["aws_session_token"] = creds.aws_temp_credentials.get(
            "session_token", ""
        )

    try:
        dt = DeltaTable(creds.storage_location, storage_options=storage_options)
    except Exception as e:
        raise CredentialVendingError(
            full_name,
            f"Failed to open Delta table at {creds.storage_location}: {e}",
        ) from e

    # Get file URIs (ABFSS format)
    try:
        abfss_uris = dt.file_uris()
    except Exception as e:
        raise CredentialVendingError(
            full_name, f"Failed to list Delta files: {e}"
        ) from e

    if not abfss_uris:
        raise CredentialVendingError(full_name, "Delta table has no data files")

    # Convert ABFSS → signed HTTPS URLs
    sas_token = creds.sas_token or ""
    try:
        file_urls = [_abfss_to_https(uri, sas_token) for uri in abfss_uris]
    except ValueError as e:
        raise CredentialVendingError(full_name, str(e)) from e

    # Check for active deletion vectors
    has_dvs = False
    try:
        import pyarrow as pa

        dv_reader = dt.deletion_vectors()
        dv_table = pa.RecordBatchReader.from_stream(dv_reader).read_all()
        has_dvs = dv_table.num_rows > 0
        if has_dvs:
            logger.warning(
                "%s has %d files with active deletion vectors — "
                "some deleted rows may appear in results",
                full_name,
                dv_table.num_rows,
            )
    except Exception as e:
        logger.debug("Could not check deletion vectors for %s: %s", full_name, e)

    # Schema as JSON for logging
    schema_json = ""
    try:
        schema_json = str(dt.schema())
    except Exception:
        pass

    logger.info(
        "Resolved %s: %d data files, has_dvs=%s",
        full_name,
        len(file_urls),
        has_dvs,
    )

    return ResolvedTable(
        full_name=full_name,
        file_urls=file_urls,
        schema_json=schema_json,
        has_deletion_vectors=has_dvs,
    )


def resolve_tables(
    host: str, token: str, table_names: list[str]
) -> dict[str, ResolvedTable]:
    """Vend credentials and resolve Delta tables to signed file URLs.

    This is the main entry point. For each three-part table name:
      1. Calls UC REST API for table metadata + temp credentials
      2. Uses deltalake to parse the Delta log
      3. Returns signed HTTPS URLs to parquet data files

    The caller (DuckDB worker) uses these URLs with read_parquet() via httpfs.

    Args:
        host: Databricks workspace URL.
        token: PAT token.
        table_names: List of fully qualified table names (catalog.schema.table).

    Returns:
        Dict mapping each full_name to its ResolvedTable.

    Raises:
        CredentialVendingError for the first table that fails.
    """
    results: dict[str, ResolvedTable] = {}

    for name in table_names:
        logger.info("Resolving table via credential vending: %s", name)
        creds = vend_credentials(host, token, name)
        resolved = resolve_delta_files(creds, name)
        results[name] = resolved

    return results
