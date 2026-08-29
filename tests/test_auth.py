import hashlib

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module


def _make_hash(password: str) -> str:
    salt = "0123456789abcdef0123456789abcdef"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256$120000${salt}${dk.hex()}"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_module, "AUTH_USERNAME", "owner")
    monkeypatch.setattr(app_module, "AUTH_PASSWORD_HASH", _make_hash("s3cret"))
    monkeypatch.setattr(app_module, "AUTH_ENABLED", True)
    monkeypatch.setattr(app_module, "LOGIN_ATTEMPTS", {})
    with TestClient(app_module.app) as c:
        yield c


def test_dashboard_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_api_returns_401_without_session(client):
    r = client.get("/api/status")
    assert r.status_code == 401
    r = client.get("/api/runs")
    assert r.status_code == 401


def test_public_paths_stay_open(client):
    assert client.get("/login").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/icon_logo.png").status_code in (200, 404)


def test_login_success_sets_session_cookie(client):
    r = client.post("/api/login", json={"username": "owner", "password": "s3cret"})
    assert r.status_code == 200
    cookie = r.headers.get("set-cookie", "")
    assert "colonyv_session=" in cookie
    with client:
        authenticated = client.get("/api/status")
    assert authenticated.status_code == 200


def test_login_rejects_wrong_credentials(client):
    r = client.post("/api/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 401
    assert "attempts remaining" in r.json()["error"]


def test_login_lockout_after_ten_failures(client):
    for attempt in range(1, 10):
        r = client.post("/api/login", json={"username": "owner", "password": "wrong"})
        assert r.status_code == 401, f"attempt {attempt} should fail with 401"
    r = client.post("/api/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 429
    r = client.post("/api/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 429
    r = client.post("/api/login", json={"username": "owner", "password": "s3cret"})
    assert r.status_code == 429


def test_correct_login_resets_attempts(client):
    for _ in range(5):
        client.post("/api/login", json={"username": "owner", "password": "wrong"})
    r = client.post("/api/login", json={"username": "owner", "password": "s3cret"})
    assert r.status_code == 200
    r = client.post("/api/login", json={"username": "owner", "password": "s3cret"})
    assert r.status_code == 200


def test_auth_disabled_allows_anonymous(monkeypatch):
    monkeypatch.setattr(app_module, "AUTH_ENABLED", False)
    with TestClient(app_module.app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/api/status").status_code == 200


def test_signed_session_is_stateless():
    token = app_module._session_token("owner")
    assert app_module._cookie_valid(token)
    assert app_module._cookie_valid(token + "x") is False
    assert app_module._cookie_valid("owner|9999999999|deadbeef") is False
    assert app_module._cookie_valid("attacker|9876543210|" + "0" * 32) is False


def test_cookie_validation_uses_shared_secret(monkeypatch):
    fake = "sharedsecretforinstanceparity"
    monkeypatch.setattr(app_module, "SESSION_KEY", fake.encode())
    token = app_module._session_token("owner")
    assert app_module._cookie_valid(token)
    monkeypatch.setattr(app_module, "SESSION_KEY", b"anotherinstancekey")
    assert app_module._cookie_valid(token) is False