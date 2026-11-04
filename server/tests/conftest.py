# Test-only configuration. Generate an isolated encryption key for each pytest run.
import base64
import os
import secrets

import fastapi.testclient
import pytest

# Set this while conftest is imported, before test modules import application settings.
# setdefault preserves an explicitly supplied key for specialized test runs.
os.environ.setdefault(
    "DATA_KEY",
    base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
)


@pytest.fixture(scope="session")
def client():
    # Import lazily so missing env vars surface as test failures, not
    # collection errors.
    from app.main import app

    with fastapi.testclient.TestClient(app) as test_client:
        yield test_client
