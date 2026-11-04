# Minimal fixtures. Expand in later phases.
# We intentionally avoid spinning up a real DB or server here; P1.5 only
# needs to prove that imports work and /healthz responds.
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    # Import lazily so missing env vars surface as test failures, not
    # collection errors.
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
