import os
from datetime import datetime

import httpx
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Config from environment (injected via K8s ConfigMap)
ROUTING_SERVICE_URL = os.environ.get("ROUTING_SERVICE_URL", "http://localhost:8000")

# Auto-refresh every 15 seconds
st_autorefresh(interval=15000, key="health_refresh")

st.title("System Health")
st.caption(f"Last checked: {datetime.now().strftime('%H:%M:%S')}")

def fetch_health():
    """Call routing-service to get health status of all backends."""
    routing_ok = False
    backends = {}
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{ROUTING_SERVICE_URL}/health")
            resp.raise_for_status()
            routing_ok = True
    except Exception:
        return routing_ok, backends
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{ROUTING_SERVICE_URL}/health/backends")
            resp.raise_for_status()
            backends = resp.json()
    except Exception:
        pass
    return routing_ok, backends

routing_ok, backends = fetch_health()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.subheader("Web UI")
    st.success("Connected")
with col2:
    st.subheader("Routing Service")
    if routing_ok:
        st.success("Connected")
    else:
        st.error("Unreachable")
with col3:
    st.subheader("PostgreSQL")
    pg = backends.get("postgresql", {})
    if pg.get("status") == "connected":
        st.success("Connected")
    elif not routing_ok:
        st.warning("Unknown")
    else:
        st.error(pg.get("detail", "Error"))
with col4:
    st.subheader("DuckDB Worker")
    ddb = backends.get("duckdb_worker", {})
    if ddb.get("status") == "connected":
        st.success("Connected")
    elif not routing_ok:
        st.warning("Unknown")
    else:
        st.error(ddb.get("detail", "Error"))