from dataclasses import replace

from conftest import PASSWORD
from fastapi.testclient import TestClient

from lecture_auto.core.project import ProjectConfig, save_project
from lecture_auto.web.app import create_app


def _deck(client, **fields):
    return client.post("/api/lectures", data={"name": "강의", **fields}, files={"file": ("a.pdf", b"%PDF-test")})


def test_gpu_less_server_defaults_to_gemini_and_refuses_raon(settings):
    settings = replace(settings, raon_enabled=False)
    save_project(ProjectConfig(id="01_old", name="old", subject="s"), settings.projects_dir)
    with TestClient(create_app(settings)) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        assert admin.get("/api/me").json()["raon_enabled"] is False
        assert admin.get("/api/tts-options").json()["raon_enabled"] is False
        lecture = _deck(admin).json()
        assert lecture["tts_engine"] == "gemini" and lecture["tts_voice"] == "Charon"
        assert _deck(admin, tts_engine="raon").status_code == 400
        assert admin.put(f"/api/lectures/{lecture['id']}/settings", json={"tts_engine": "raon"}).status_code == 400
        upload = admin.post("/api/voices", data={"consent": "true", "name": "v"},
                            files={"file": ("v.wav", b"RIFF0000WAVEfmt ")})
        assert upload.status_code == 400 and "GPU" in upload.json()["detail"]
        refused = admin.post("/api/lectures/01_old/jobs", json={"kind": "produce"})
        assert refused.status_code == 400 and "Gemini" in refused.json()["detail"]
        assert admin.put("/api/lectures/01_old/settings", json={"tts_engine": "gemini", "tts_voice": "Kore"}).status_code == 200
        assert admin.post("/api/lectures/01_old/jobs", json={"kind": "produce"}).status_code == 200


def test_gpu_server_keeps_raon_as_the_default(settings):
    with TestClient(create_app(settings)) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        assert admin.get("/api/tts-options").json()["raon_enabled"] is True
        assert _deck(admin).json()["tts_engine"] == "raon"
