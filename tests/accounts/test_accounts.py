import sqlite3
from dataclasses import replace

import httpx
import pytest
from conftest import PASSWORD, signup
from fastapi.testclient import TestClient

from lecture_auto.web.accounts import Accounts
from lecture_auto.web.app import create_app


def test_bootstrap_login_logout_me_and_password_storage(admin, settings):
    user = admin.get("/api/me").json()
    assert user["email"] == "admin@local" and user["role"] == "admin"
    assert "password" not in user
    assert b"account-password-123" not in (settings.web_dir / "app.db").read_bytes()
    with sqlite3.connect(settings.web_dir / "app.db") as db:
        digest, salt = db.execute("SELECT password_hash,salt FROM users").fetchone()
    assert len(digest) == 64 and len(salt) == 16
    assert admin.post("/api/logout").status_code == 200
    assert admin.get("/api/me").status_code == 401


@pytest.mark.parametrize("mode,status", [("closed", 403), ("invite", 403), ("open", 200)])
def test_signup_modes(settings, mode, status):
    with TestClient(create_app(replace(settings, signup_mode=mode))) as client:
        result = client.post("/api/signup", json={"email": "new@example.com", "password": PASSWORD,
                             "display_name": "new", "terms_accepted": True})
        assert result.status_code == status


@pytest.mark.parametrize("changes,status", [
    ({"terms_accepted": False}, 400), ({"password": "short"}, 422),
    ({"email": "bad"}, 422), ({"display_name": " "}, 422),
])
def test_signup_requires_valid_details(client, changes, status):
    result = client.post("/api/signup", json={"email": "new@example.com", "password": PASSWORD,
                         "display_name": "new", "terms_accepted": True, **changes})
    assert result.status_code == status


def test_invites_single_use_and_terms_timestamp(settings):
    with TestClient(create_app(replace(settings, signup_mode="invite"))) as client:
        client.post("/api/login", json={"password": PASSWORD})
        code = client.post("/api/admin/invites").json()["code"]
        body = {"email": "one@example.com", "password": PASSWORD, "display_name": "one",
                "terms_accepted": True, "invite_code": code}
        first = client.post("/api/signup", json=body)
        assert first.status_code == 200
        assert first.json()["terms_accepted_at"]
        assert client.post("/api/signup", json={**body, "email": "two@example.com"}).status_code == 403


def test_different_users_have_distinct_password_salts(client, settings):
    signup(client)
    signup(client, "other@example.com")
    with sqlite3.connect(settings.web_dir / "app.db") as db:
        rows = db.execute("SELECT password_hash,salt FROM users").fetchall()
    assert len(set(rows)) == 3


def test_api_key_encrypted_and_only_last_four_exposed(client, settings, monkeypatch):
    user = signup(client)
    key = "fake-key-sensitive-9876"
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200 if request.headers["authorization"] == f"Bearer {key}" else 401, json={"data": []}))
    monkeypatch.setattr("lecture_auto.web.account_routes.httpx.Client",
                        lambda **kw: real_client(transport=transport, **kw))
    assert client.put("/api/settings/key", json={"key": key}).json() == {"last4": "9876"}
    assert client.get("/api/settings/key").json() == {"last4": "9876"}
    assert key.encode() not in (settings.web_dir / "app.db").read_bytes()
    assert Accounts(settings).api_key(user["id"]) == key
    assert client.put("/api/settings/key", json={"key": "invalid"}).status_code == 400
    assert client.get("/api/settings/key").json() == {"last4": "9876"}
    assert client.delete("/api/settings/key").status_code == 200
    assert client.get("/api/settings/key").json() == {"last4": None}


def test_reports_and_admin_disable_revoke_existing_session(client, settings):
    user = signup(client)
    result = client.post("/api/reports", json={"target_type": "voice", "target_id": "reported",
                                              "reason": "consent issue"})
    assert result.status_code == 200
    assert client.get("/api/admin/reports").status_code == 403
    with TestClient(create_app(settings)) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        reports = admin.get("/api/admin/reports").json()
        assert reports[0]["user_id"] == user["id"]
        assert reports[0]["reason"] == "consent issue"
        assert admin.put(f"/api/admin/users/{user['id']}", json={"disabled": True}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"email": user["email"], "password": PASSWORD}).status_code == 401


def test_global_throttle_caps_guesses_across_email_addresses(client, monkeypatch):
    import lecture_auto.web.app as web_app

    monkeypatch.setattr(web_app, "LOGIN_FAILURE_DELAY", 0)
    for number in range(web_app.LOGIN_GLOBAL_MAX):
        assert client.post("/api/login", json={
            "email": f"unknown{number}@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_invalid_sensitive_inputs_are_never_echoed(client):
    signup(client)
    secret = "overlong-sensitive-api-key" * 200
    result = client.put("/api/settings/key", json={"key": secret})
    assert result.status_code == 422
    assert secret not in result.text
