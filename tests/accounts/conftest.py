from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from lecture_auto.web.accounts import Accounts
from lecture_auto.web.app import create_app
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings

PASSWORD = "account-password-123"


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, password=PASSWORD, secret=b"a" * 32,
                    signup_mode="open", python="/bin/true")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def admin(client):
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return client


def signup(client, email="user@example.com"):
    result = client.post("/api/signup", json={
        "email": email, "password": PASSWORD, "display_name": email.split("@")[0], "terms_accepted": True})
    assert result.status_code == 200, result.text
    assert client.post("/api/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return result.json()


def deck(client, **fields):
    result = client.post("/api/lectures", data={"name": "test", **fields},
                         files={"file": ("a.pdf", b"%PDF-test")})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def stopped_runner(settings):
    return JobRunner(replace(settings, python="/bin/true"))


@pytest.fixture
def accounts(settings):
    return Accounts(settings)
