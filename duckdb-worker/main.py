import time
from contextlib import asynccontextmanager

import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class QueryRequest(BaseModel):
    sql: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create a single in-memory DuckDB connection at startup
    app.state.db = duckdb.connect(":memory:")
    # Install and load deltalake extension for future Delta Lake reads
    app.state.db.install_extension("delta")
    app.state.db.load_extension("delta")
    yield
    app.state.db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "duckdb"}


@app.post("/query")
async def query(request: QueryRequest):
    start = time.perf_counter()
    try:
        result = app.state.db.execute(request.sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        execution_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": execution_time_ms,
        }
    except duckdb.Error as e:
        raise HTTPException(status_code=400, detail=str(e))
