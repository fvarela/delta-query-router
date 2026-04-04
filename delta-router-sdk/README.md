# delta-router-sdk

Python SDK for [Delta Router](https://github.com/your-org/delta-router) — a DB-API 2.0 interface for multi-engine SQL routing.

Delta Router automatically routes your SQL queries to the optimal engine (DuckDB or Databricks) based on table metadata, governance constraints, and query complexity. The SDK authenticates with your Databricks personal access token and provides a familiar `connect → cursor → execute → fetch` workflow.

## Installation

```bash
pip install ./delta-router-sdk
```

Or install in development mode:

```bash
pip install -e ./delta-router-sdk
```

## Quick Start

```python
from delta_router import sql

conn = sql.connect(
    server_hostname="localhost:8501",
    access_token="dapi...",
    databricks_host="https://my-workspace.databricks.com",
)

with conn.cursor() as cur:
    cur.execute("SELECT * FROM catalog.schema.table LIMIT 10")
    print(cur.fetchall())
    print(cur.routing_decision)  # which engine was chosen and why

conn.close()
```

## Migration from databricks-sql-connector

The SDK is designed as a drop-in replacement for `databricks-sql-connector`. The key differences:

| | databricks-sql-connector | delta-router-sdk |
|---|---|---|
| **Import** | `from databricks import sql` | `from delta_router import sql` |
| **Auth** | Databricks PAT authenticates directly | PAT validates via Databricks, then gets a session token |
| **Routing** | Always executes on Databricks | Auto-routes to DuckDB or Databricks |
| **`http_path`** | Required (warehouse endpoint) | Accepted but ignored (for compatibility) |
| **`databricks_host`** | Not needed | Required (workspace URL for PAT validation) |

### Before (databricks-sql-connector)

```python
from databricks import sql

conn = sql.connect(
    server_hostname="my-workspace.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    access_token="dapi...",
)
cursor = conn.cursor()
cursor.execute("SELECT * FROM catalog.schema.table")
rows = cursor.fetchall()
cursor.close()
conn.close()
```

### After (delta-router-sdk)

```python
from delta_router import sql

conn = sql.connect(
    server_hostname="router-host:8501",        # Delta Router address
    access_token="dapi...",                     # same Databricks PAT
    databricks_host="https://my-workspace.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",    # accepted, ignored
)
cursor = conn.cursor()
cursor.execute("SELECT * FROM catalog.schema.table")
rows = cursor.fetchall()
print(cursor.routing_decision)  # new: see which engine was used
cursor.close()
conn.close()
```

## Routing Override

By default, queries are routed automatically (`"smart"` mode). You can force a specific engine:

```python
with conn.cursor() as cur:
    # Auto-route (default)
    cur.execute("SELECT ...")

    # Force DuckDB
    cur.execute("SELECT ...", engine="duckdb")

    # Force Databricks
    cur.execute("SELECT ...", engine="databricks")
```

> **Note:** Mandatory routing rules (e.g., views, tables with row-level security) override the `engine` parameter when governance requires it.

## Context Managers

Both `Connection` and `Cursor` support context managers for automatic cleanup:

```python
from delta_router import sql

with sql.connect(
    server_hostname="localhost:8501",
    access_token="dapi...",
    databricks_host="https://my-workspace.databricks.com",
) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS test")
        print(cur.fetchall())
    # cursor is closed here
# connection is closed here
```

## Error Handling

The SDK raises specific exceptions for different failure modes:

```python
from delta_router import sql, AuthenticationError, AccessDeniedError, QueryError

# Invalid or expired PAT
try:
    conn = sql.connect(
        server_hostname="localhost:8501",
        access_token="dapi_INVALID",
        databricks_host="https://my-workspace.databricks.com",
    )
except AuthenticationError as e:
    print(f"Auth failed: {e}")

# Table access denied (Unity Catalog permissions)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM catalog.schema.restricted_table")
except AccessDeniedError as e:
    print(f"Access denied: {e}")

# Query execution failure
try:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM nonexistent.table")
except QueryError as e:
    print(f"Query failed: {e}")
```

### Exception Hierarchy

| Exception | HTTP Status | When |
|---|---|---|
| `AuthenticationError` | 401 | Invalid/expired PAT, re-auth fails |
| `AccessDeniedError` | 403 | Unity Catalog denies table access |
| `QueryError` | 400, 500, 502 | Bad SQL, server error, engine unavailable |
| `RoutingError` | — | Reserved for routing pipeline failures |

## API Reference

### `sql.connect()`

```python
sql.connect(
    server_hostname: str,       # Delta Router host:port
    access_token: str,          # Databricks personal access token
    databricks_host: str,       # Workspace URL (https://...)
    http_path: str | None,      # Ignored (databricks-sql-connector compat)
    *,
    scheme: str = "http",       # "http" or "https"
    timeout: float = 120.0,     # HTTP timeout in seconds
) -> Connection
```

Returns an authenticated `Connection`. Raises `AuthenticationError` on invalid PAT.

### `Connection`

| Method / Property | Description |
|---|---|
| `cursor() -> Cursor` | Create a new cursor |
| `close()` | Close the connection and release resources |
| `closed -> bool` | Whether the connection has been closed |
| `server_url -> str` | Base URL of the Delta Router instance |

### `Cursor`

| Method / Property | Description |
|---|---|
| `execute(sql, parameters=None, *, engine=None) -> Cursor` | Execute a SQL query |
| `fetchall() -> list[tuple]` | Fetch all remaining rows |
| `fetchone() -> tuple \| None` | Fetch the next row |
| `fetchmany(size=None) -> list[tuple]` | Fetch up to `size` rows |
| `close()` | Close the cursor |
| `description -> list[ColumnDescription] \| None` | Column metadata (PEP 249) |
| `rowcount -> int` | Number of rows from last execute (-1 before execute) |
| `arraysize -> int` | Default fetch size for `fetchmany()` (default: 1) |
| `routing_decision -> RoutingDecision \| None` | Routing decision from last execute |

### `RoutingDecision`

| Field | Type | Description |
|---|---|---|
| `engine` | `str` | Engine identifier (e.g., `"duckdb:2gb-2cpu"`) |
| `engine_display_name` | `str` | Human-readable name (e.g., `"DuckDB 2GB/2CPU"`) |
| `stage` | `str` | Routing stage that made the decision |
| `reason` | `str` | Why this engine was chosen |
| `complexity_score` | `float \| None` | Query complexity score |

### `ColumnDescription`

PEP 249 column description. Supports tuple unpacking:

```python
for name, type_code, *_ in cursor.description:
    print(f"{name}: {type_code}")
```

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Column name |
| `type_code` | `str \| None` | Data type (not yet populated) |
| `display_size` | `int \| None` | Always None |
| `internal_size` | `int \| None` | Always None |
| `precision` | `int \| None` | Always None |
| `scale` | `int \| None` | Always None |
| `null_ok` | `bool \| None` | Always None |

## Running Tests

```bash
cd delta-router-sdk

# Unit tests (no external dependencies)
.venv/bin/python -m pytest tests/ -v

# Integration tests (requires running routing-service)
DATABRICKS_HOST=https://my-workspace.databricks.com \
DATABRICKS_TOKEN=dapi... \
.venv/bin/python -m pytest tests/test_integration.py -v
```

## License

Internal use only.
