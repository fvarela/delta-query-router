"""DB-API 2.0 Cursor for the Delta Router SDK.

Implements execute(), fetchall(), fetchone(), fetchmany(), description,
rowcount, and routing_decision per PEP 249.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .exceptions import AccessDeniedError, AuthenticationError, QueryError
from .types import ColumnDescription, RoutingDecision

if TYPE_CHECKING:
    from .sql import Connection


class Cursor:
    """DB-API 2.0 Cursor for executing queries via Delta Router.

    Usage::

        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM catalog.schema.table")
            print(cur.description)       # column metadata
            print(cur.routing_decision)   # which engine was chosen
            for row in cur.fetchall():
                print(row)
    """

    #: Default number of rows for fetchmany() (PEP 249).
    arraysize: int = 1

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._rows: list[tuple] = []
        self._cursor_pos: int = 0
        self._closed: bool = False

        # PEP 249 attributes
        self.description: list[ColumnDescription] | None = None
        self.rowcount: int = -1
        self.routing_decision: RoutingDecision | None = None

    def execute(
        self,
        sql: str,
        parameters: Any = None,
        *,
        engine: str | None = None,
        profile_id: int | None = None,
    ) -> Cursor:
        """Execute a SQL query via the Delta Router.

        Args:
            sql: SQL string to execute.
            parameters: Ignored — accepted for DB-API compatibility.
            engine: Routing mode override. Maps to ``routing_mode`` on the
                server. Values: ``"smart"`` (default), ``"duckdb"``,
                ``"databricks"``, or a specific engine name.
            profile_id: Optional routing profile ID. If not set, the
                server uses the default profile.

        Returns:
            self (for method chaining per DB-API convention).

        Raises:
            AccessDeniedError: If the user lacks access to tables in the query (HTTP 403).
            QueryError: If the query fails (HTTP 400, 500, 502).
            AuthenticationError: If authentication fails after retry (HTTP 401).
            ValueError: If the cursor is closed.
        """
        if self._closed:
            raise ValueError("Cannot execute on a closed cursor")

        body: dict[str, Any] = {"sql": sql}
        if engine is not None:
            body["routing_mode"] = engine
        if profile_id is not None:
            body["profile_id"] = profile_id

        url = f"{self._connection.server_url}/api/query"
        resp = self._connection.token_manager.request_with_retry("POST", url, json=body)

        if resp.status_code == 403:
            detail = resp.json().get("detail", "Access denied")
            raise AccessDeniedError(detail)

        if resp.status_code == 400:
            detail = resp.json().get("detail", "Bad request")
            raise QueryError(detail)

        if resp.status_code >= 500 or resp.status_code == 502:
            detail = resp.json().get(
                "detail", f"Server error (HTTP {resp.status_code})"
            )
            raise QueryError(detail)

        if resp.status_code != 200:
            raise QueryError(
                f"Unexpected response (HTTP {resp.status_code}): {resp.text}"
            )

        data = resp.json()
        self._parse_response(data)
        return self

    def _parse_response(self, data: dict[str, Any]) -> None:
        """Parse the POST /api/query response into cursor state."""
        # Rows: convert lists to tuples for DB-API compliance
        raw_rows = data.get("rows", [])
        self._rows = [tuple(row) for row in raw_rows]
        self._cursor_pos = 0
        self.rowcount = len(self._rows)

        # Description: build from column names
        columns = data.get("columns", [])
        self.description = [ColumnDescription(name=col) for col in columns]

        # Routing decision
        rd = data.get("routing_decision")
        if rd:
            self.routing_decision = RoutingDecision(
                engine=rd.get("engine", ""),
                engine_display_name=rd.get("engine_display_name", ""),
                stage=rd.get("stage", ""),
                reason=rd.get("reason", ""),
                complexity_score=rd.get("complexity_score"),
            )
        else:
            self.routing_decision = None

    def fetchone(self) -> tuple | None:
        """Fetch the next row, or ``None`` if no more rows.

        Raises:
            ValueError: If the cursor is closed or no query has been executed.
        """
        self._check_executed()
        if self._cursor_pos >= len(self._rows):
            return None
        row = self._rows[self._cursor_pos]
        self._cursor_pos += 1
        return row

    def fetchmany(self, size: int | None = None) -> list[tuple]:
        """Fetch up to *size* rows (default :attr:`arraysize`).

        Raises:
            ValueError: If the cursor is closed or no query has been executed.
        """
        self._check_executed()
        if size is None:
            size = self.arraysize
        end = min(self._cursor_pos + size, len(self._rows))
        rows = self._rows[self._cursor_pos : end]
        self._cursor_pos = end
        return rows

    def fetchall(self) -> list[tuple]:
        """Fetch all remaining rows.

        Raises:
            ValueError: If the cursor is closed or no query has been executed.
        """
        self._check_executed()
        rows = self._rows[self._cursor_pos :]
        self._cursor_pos = len(self._rows)
        return rows

    def _check_executed(self) -> None:
        """Raise if cursor is closed or no query has been executed."""
        if self._closed:
            raise ValueError("Cursor is closed")
        if self.description is None:
            raise ValueError("No query has been executed")

    def close(self) -> None:
        """Close the cursor."""
        self._closed = True

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
