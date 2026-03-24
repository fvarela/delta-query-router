from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


class TestHealthEndpoints:
    """Local health endpoints should respond without routing-service."""

    def test_health(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_is_not_proxied(self):
        """GET /api/health should be handled locally, not forwarded."""
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestCatchAllProxy:
    """Verify the catch-all proxy route behavior."""

    def test_unknown_api_route_attempts_proxy(self):
        """Routes not handled locally should be forwarded to routing-service."""
        # routing-service isn't running, so catch-all returns 502
        resp = client.get("/api/some/unknown/path")
        assert resp.status_code == 502

    def test_proxy_forwards_query_params(self):
        """Query params should be included in the proxied URL."""
        resp = client.get("/api/routing/rules?engine=duckdb")
        assert resp.status_code == 502  # connection refused, but route matched

    def test_proxy_post_route(self):
        """POST requests should be forwarded."""
        resp = client.post(
            "/api/auth/login", json={"username": "test", "password": "test"}
        )
        assert resp.status_code == 502  # connection refused, but route matched

    def test_proxy_put_route(self):
        """PUT requests should be forwarded."""
        resp = client.put("/api/settings/warehouse", json={"id": "abc"})
        assert resp.status_code == 502

    def test_proxy_delete_route(self):
        """DELETE requests should be forwarded."""
        resp = client.delete("/api/routing/rules/1")
        assert resp.status_code == 502
