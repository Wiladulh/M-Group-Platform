"""Smoke tests for frontend routes and static assets."""

from fastapi.testclient import TestClient


def test_home_page(client: TestClient) -> None:
    """Render the home page and confirm HTML response."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_css(client: TestClient) -> None:
    """Serve the compiled Tailwind CSS asset."""
    resp = client.get("/static/css/app.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")


def test_static_js(client: TestClient) -> None:
    """Serve the local JavaScript entry point."""
    resp = client.get("/static/js/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
