import hashlib
import io
import json
import wave
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import PASSWORD, deck, signup
from fastapi.testclient import TestClient

from lecture_auto.core.project import load_projects
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.app import create_app


def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0" * 4800)
    return buffer.getvalue()


def upload(client, **fields):
    return client.post("/api/voices", data={"name": "voice", "consent": "true", **fields},
                       files={"file": ("voice.wav", wav())})


def test_voice_requires_consent_and_records_upload_hash(client, settings):
    user = signup(client)
    assert upload(client, consent="false").status_code == 400
    result = upload(client)
    assert result.status_code == 200, result.text
    voice = result.json()
    metadata = json.loads((settings.root / voice["ref_voice"]).with_suffix(".json").read_text())
    assert metadata["sha256"] == hashlib.sha256(wav()).hexdigest()
    assert metadata["user_id"] == user["id"] and metadata["consent_at"]
    assert client.get(f"/api/voices/{voice['id']}/audio").content == wav()
    assert client.get("/api/voices").json()[0]["is_default"] == 1


@pytest.mark.parametrize("filename,data", [
    ("a.wav", b"invalid"), ("a.mp3", b"invalid"), ("a.m4a", b"invalid"),
    ("a.exe", b"RIFF0000WAVE"), ("a.wav", b"RIFF0000WAVE")])
def test_voice_magic_and_audio_headers_rejected(client, filename, data):
    signup(client)
    result = client.post("/api/voices", data={"consent": "true"},
                         files={"file": (filename, data)})
    assert result.status_code == 400
    assert client.get("/api/voices").json() == []


@pytest.mark.parametrize("filename,data", [("a.mp3", b"ID3mock"), ("a.m4a", b"\0\0\0\x18ftypM4A ")])
def test_compressed_voices_are_converted_to_mono_24k(client, settings, monkeypatch, filename, data):
    signup(client)

    def ffmpeg(command, **kwargs):
        assert command[command.index("-ar") + 1] == "24000"
        assert command[command.index("-ac") + 1] == "1"
        Path(command[-1]).write_bytes(wav())

    monkeypatch.setattr("lecture_auto.web.voices.subprocess.run", ffmpeg)
    result = client.post("/api/voices", data={"consent": "true"},
                         files={"file": (filename, data)})
    assert result.status_code == 200, result.text
    with wave.open(str(settings.root / result.json()["ref_voice"]), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels()) == (24000, 1)


def test_voice_privacy_settings_and_disable(client, settings):
    first = signup(client)
    voice = upload(client).json()
    lid = deck(client)["id"]
    assert load_projects(settings.projects_dir)[0].ref_voice == Path(voice["ref_voice"])
    assert client.put(f"/api/voices/{voice['id']}", json={"name": "renamed", "is_default": True}).status_code == 200
    assert client.get("/api/voices").json()[0]["name"] == "renamed"
    signup(client, "second@example.com")
    assert client.get("/api/voices").json() == []
    for method, tail in [("GET", "/audio"), ("DELETE", ""), ("PUT", "")]:
        assert client.request(method, f"/api/voices/{voice['id']}{tail}",
                              json={"name": "steal"}).status_code == 404
    assert client.post("/api/lectures", data={"name": "steal", "ref_voice": voice["ref_voice"]},
                       files={"file": ("a.pdf", b"%PDF-test")}).status_code == 400
    client.post("/api/login", json={"email": first["email"], "password": PASSWORD})
    Accounts(settings).save_key(first["id"], "fake-key-1234")
    with TestClient(create_app(settings)) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        assert admin.put(f"/api/admin/voices/{voice['id']}", json={"disabled": True}).status_code == 200
    assert client.post(f"/api/lectures/{lid}/jobs", json={"kind": "produce"}).status_code == 400
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 200
    assert not (settings.root / voice["ref_voice"]).exists()


@pytest.mark.parametrize("ref", ["/etc/passwd", "data/voices/other/a.wav", "data/audio_ref/../../secret.wav"])
def test_lecture_ref_voice_rejects_unowned_paths(client, ref):
    signup(client)
    result = client.post("/api/lectures", data={"name": "bad", "ref_voice": ref},
                         files={"file": ("a.pdf", b"%PDF-test")})
    assert result.status_code == 400


def test_gemini_voice_and_instructions_persist_on_create_and_edit(client, settings):
    signup(client)
    lid = deck(client, tts_engine="gemini", tts_voice="Charon", tts_instructions="차분하게")["id"]
    project = load_projects(settings.projects_dir)[0]
    assert (project.tts_engine, project.tts_voice, project.tts_instructions) == ("gemini", "Charon", "차분하게")
    assert client.put(f"/api/lectures/{lid}/settings", json={
        "tts_engine": "gemini", "tts_voice": "invalid"}).status_code == 422
    result = client.put(f"/api/lectures/{lid}/settings", json={
        "tts_engine": "gemini", "tts_voice": "Aoede", "tts_instructions": "밝게"})
    assert result.status_code == 200 and result.json()["tts_voice"] == "Aoede"


def test_voice_count_and_upload_size_quotas(settings):
    settings = replace(settings, max_voices=1, max_voice_upload_mb=1)
    with TestClient(create_app(settings)) as client:
        signup(client)
        assert upload(client).status_code == 200
        assert upload(client).status_code == 409
        assert client.post("/api/voices", data={"consent": "true"},
                           files={"file": ("a.wav", wav() + b"x" * 1024 * 1024)}).status_code == 413


def test_voice_storage_cap_rejects_before_persisting(settings):
    with TestClient(create_app(replace(settings, storage_limit_mb=0))) as client:
        signup(client)
        assert upload(client).status_code == 413
        assert client.get("/api/voices").json() == []
    assert list((settings.root / "data/voices").rglob("*.wav")) == []
