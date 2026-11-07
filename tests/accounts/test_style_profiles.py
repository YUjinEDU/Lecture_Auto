"""Real HTTP boundaries for private profile uploads and lecture selection."""
from unittest.mock import MagicMock

import pytest
from conftest import deck, signup

from lecture_auto.pipeline.style_profile import MAX_TRANSCRIPT_BYTES, StyleProfile
from lecture_auto.web.accounts import Accounts


def extractor(monkeypatch):
    client = MagicMock()
    client.chat.return_value = StyleProfile(topic_openings=["자, 우리가"]).model_dump_json()
    monkeypatch.setattr("lecture_auto.web.style_profiles.OpenAILLMClient", lambda **kwargs: client)
    return client


def test_profile_upload_listing_and_other_account_cannot_select_delete(client, settings, monkeypatch):
    model = extractor(monkeypatch)
    alice = signup(client)
    monkeypatch.setattr(Accounts, "api_key", lambda self, uid: "fake-key")
    result = client.post("/api/style-profiles", files={"file": ("내강의.txt", "자, 설명하죠".encode())})
    assert result.status_code == 200, result.text
    pid = result.json()["id"]
    assert client.get("/api/style-profiles").json() == [{"id": pid, "name": "내강의"}]
    assert model.chat.call_count == 1
    own_deck = deck(client, critic="true", style_profile=pid)
    assert own_deck["critic"] is True and own_deck["style_profile"] == pid
    user_dir = settings.root / "data/style_profiles" / alice["id"]
    assert {p.suffix for p in user_dir.iterdir()} == {".json"}

    signup(client, "bob@example.com")
    assert client.get("/api/style-profiles").json() == []
    assert client.delete(f"/api/style-profiles/{pid}").status_code == 404
    assert client.post("/api/lectures", data={"name": "다른 계정", "style_profile": pid},
                       files={"file": ("a.pdf", b"%PDF-test")}).status_code == 400
    other = deck(client)
    assert client.put(f"/api/lectures/{other['id']}/settings",
                      json={"style_profile": pid}).status_code == 400


@pytest.mark.parametrize("filename,body,status", [
    ("a.txt", b"x" * (MAX_TRANSCRIPT_BYTES + 1), 413),
    ("a.pdf", b"text", 400), ("a.txt", b"\xff\xff", 400), ("a.txt", b" \n", 400),
])
def test_upload_limits_and_invalid_text_fail_without_llm(admin, monkeypatch, filename, body, status):
    model = extractor(monkeypatch)
    assert admin.post("/api/style-profiles", files={"file": (filename, body)}).status_code == status
    model.chat.assert_not_called()


def test_two_megabyte_transcript_allowed_by_request_gate(admin, monkeypatch):
    model = extractor(monkeypatch)
    result = admin.post("/api/style-profiles", files={"file": ("a.txt", b"x" * MAX_TRANSCRIPT_BYTES)})
    assert result.status_code == 200, result.text
    assert model.chat.call_count > 1


def test_profile_upload_requires_login_and_regular_account_key(client, monkeypatch):
    model = extractor(monkeypatch)
    assert client.post("/api/style-profiles", files={"file": ("a.txt", b"text")}).status_code == 401
    signup(client)
    assert client.post("/api/style-profiles", files={"file": ("a.txt", b"text")}).status_code == 400
    model.chat.assert_not_called()


def test_owner_can_delete_profile_and_clear_lecture_selection(admin, monkeypatch):
    extractor(monkeypatch)
    pid = admin.post("/api/style-profiles", files={"file": ("a.txt", b"text")}).json()["id"]
    lecture = deck(admin, critic="true", style_profile=pid)
    assert admin.delete(f"/api/style-profiles/{pid}").status_code == 200
    result = admin.put(f"/api/lectures/{lecture['id']}/settings",
                       json={"style_profile": None, "critic": False})
    assert result.status_code == 200
    assert result.json()["style_profile"] is None and result.json()["critic"] is False
