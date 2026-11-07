from dataclasses import replace

from conftest import PASSWORD
from fastapi.testclient import TestClient

from lecture_auto.web.app import create_app


def _upload(client):
    return client.post("/api/lectures", data={"name": "강의"}, files={"file": ("a.pdf", b"%PDF-test")})


def _login(client, email):
    assert client.post("/api/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_admin_created_accounts_are_unlimited_and_limits_are_per_account(settings):
    settings = replace(settings, max_lectures=1)
    app = create_app(settings)
    with TestClient(app) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        free = admin.post("/api/admin/users", json={
            "email": "prof@school.ac.kr", "password": PASSWORD, "display_name": "교수"}).json()
        capped = admin.post("/api/admin/users", json={
            "email": "guest@example.com", "password": PASSWORD, "display_name": "외부", "unlimited": False}).json()
        assert admin.post("/api/admin/users", json={
            "email": "prof@school.ac.kr", "password": PASSWORD, "display_name": "x"}).status_code == 409
        rows = {u["email"]: u for u in admin.get("/api/admin/users").json()}
        assert rows["prof@school.ac.kr"]["limits"]["unlimited"] is True
        assert rows["guest@example.com"]["limits"]["max_lectures"] == 1

        prof, guest = TestClient(app), TestClient(app)
        _login(prof, "prof@school.ac.kr")
        _login(guest, "guest@example.com")
        assert [_upload(prof).status_code for _ in range(3)] == [200, 200, 200]
        assert prof.get("/api/me").json()["usage"]["lectures"] == 3
        assert [_upload(guest).status_code for _ in range(2)] == [200, 409]

        assert admin.put(f"/api/admin/users/{capped['id']}/limits", json={"max_lectures": 3}).json()["max_lectures"] == 3
        assert _upload(guest).status_code == 200
        me = guest.get("/api/me").json()
        assert me["limits"] == {"unlimited": False, "max_lectures": 3, "max_voices": 10, "storage_limit_mb": 5120}
        assert me["usage"]["lectures"] == 2
        assert admin.put(f"/api/admin/users/{free['id']}/limits", json={"max_lectures": 0}).status_code == 200
        assert _upload(prof).status_code == 409


def test_admin_edits_the_default_limits_for_everyone_else(settings):
    app = create_app(settings)
    with TestClient(app) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        assert admin.get("/api/admin/limits").json() == {"max_lectures": 30, "max_voices": 10, "storage_limit_mb": 5120}
        admin.post("/api/admin/users", json={"email": "u@example.com", "password": PASSWORD,
                                             "display_name": "u", "unlimited": False})
        assert admin.put("/api/admin/limits", json={"max_lectures": 0, "max_voices": 2,
                                                    "storage_limit_mb": 100}).status_code == 200
        user = TestClient(app)
        _login(user, "u@example.com")
        assert _upload(user).status_code == 409
        assert _upload(admin).status_code == 200
        assert user.get("/api/admin/limits").status_code == 403
        assert user.put("/api/admin/limits", json={"max_lectures": 99, "max_voices": 9,
                                                   "storage_limit_mb": 9}).status_code == 403
        assert user.post("/api/admin/users", json={"email": "z@example.com", "password": PASSWORD,
                                                   "display_name": "z"}).status_code == 403
