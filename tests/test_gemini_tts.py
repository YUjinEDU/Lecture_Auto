import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from lecture_auto.pipeline import gemini_tts
from lecture_auto.pipeline.gemini_tts import (
    BazeTTSClient,
    GeminiTTSError,
    synthesize_gemini_slide,
    voice_identity,
)
from lecture_auto.pipeline.raon_tts import split_into_segments
from lecture_auto.pipeline.subtitles import segment_spans
from lecture_auto.production import batch as bgl

SR = 24000
SCRIPT = (
    "오늘은 시스템 구조 설계를 배웁니다. 먼저 전체 구조를 그림으로 살펴보고, 각 구성 요소가 어떤 역할을 하는지 알아보겠습니다. "
    "다음으로 개발 환경을 어떻게 준비하는지 단계별로 정리합니다. 마지막으로 오늘 배운 내용을 짧게 복습하면서 실제 프로젝트에 어떻게 적용할지 이야기해 보겠습니다. "
    "질문이 있으면 수업이 끝난 뒤에 게시판에 남겨 주세요."
)


def _speech(seconds: float, inner_zero_ms: int = 300) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    wav = (0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    mid = len(wav) // 2
    wav[mid: mid + int(SR * inner_zero_ms / 1000)] = 0.0
    return wav


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, str, str | None]] = []

    def speech(self, text, voice, instructions):
        self.calls.append((text, voice, instructions))
        return _speech(max(len(text) / 7.0, 1.0))


def _pcm_response(samples: np.ndarray):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    resp = io.BytesIO(pcm)
    resp.__enter__ = lambda self=resp: self
    resp.__exit__ = lambda *a: False
    return resp


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b'{"error":"busy"}'))


def test_client_sends_model_voice_instructions_and_decodes_pcm():
    sent = {}

    def fake_urlopen(req, timeout):
        sent["url"], sent["auth"] = req.full_url, req.headers["Authorization"]
        sent["body"] = json.loads(req.data)
        return _pcm_response(np.full(480, 0.5, dtype=np.float32))

    with patch("urllib.request.urlopen", fake_urlopen):
        out = BazeTTSClient(api_key="k-test").speech("안녕하세요", "Kore", "차분하게")
    assert sent["url"].endswith("/v1/gateway/audio/speech/")
    assert sent["auth"] == "Bearer k-test"
    assert sent["body"] == {"model": "gemini-3.8-flash-tts", "input": "안녕하세요", "voice": "Kore", "instructions": "차분하게"}
    assert out.dtype == np.float32 and len(out) == 480 and abs(out[0] - 0.5) < 1e-3


def test_client_retries_busy_responses_then_gives_up_on_client_errors():
    responses = [_http_error(429), _http_error(503), _pcm_response(np.zeros(10, dtype=np.float32) + 0.1)]
    delays = []

    def fake_urlopen(req, timeout):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with patch("urllib.request.urlopen", fake_urlopen):
        assert len(BazeTTSClient(api_key="k", sleep=delays.append).speech("a", "Kore", None)) == 10
    assert delays == [2.0, 5.0]
    with patch("urllib.request.urlopen", side_effect=_http_error(400)), pytest.raises(GeminiTTSError, match="400"):
        BazeTTSClient(api_key="k", sleep=delays.append).speech("a", "Kore", None)
    with pytest.raises(GeminiTTSError, match="4000"):
        BazeTTSClient(api_key="k").speech("가" * 4001, "Kore", None)


def test_from_env_requires_a_key(monkeypatch):
    monkeypatch.delenv("BAZE_API_KEY", raising=False)
    with pytest.raises(GeminiTTSError, match="BAZE_API_KEY"):
        BazeTTSClient.from_env()
    monkeypatch.setenv("BAZE_API_KEY", "k-env")
    assert BazeTTSClient.from_env().api_key == "k-env"


def test_slide_keeps_segment_gaps_detectable_for_subtitles(tmp_path):
    client = FakeClient()
    out, ok = synthesize_gemini_slide(client, SCRIPT, tmp_path / "slide_001.wav", voice="Kore", qc_path=tmp_path / "q.json")
    segments = split_into_segments(SCRIPT)
    assert len(segments) >= 2 and [c[0] for c in client.calls] == segments
    assert all(c[1] == "Kore" and c[2] == gemini_tts.DEFAULT_INSTRUCTIONS for c in client.calls)
    wav, sr = sf.read(out, dtype="float32")
    _, method = segment_spans(wav, sr, len(segments))
    assert method == "pause"
    qc = json.loads((tmp_path / "q.json").read_text())
    assert ok and qc["ok"] is True and len(qc["segments"]) == len(segments)


def test_empty_script_writes_short_silence(tmp_path):
    out, ok = synthesize_gemini_slide(FakeClient(), "  ", tmp_path / "s.wav")
    assert ok and sf.info(out).duration == 0.5


def test_silent_segment_fails_the_gate(tmp_path):
    class Silent(FakeClient):
        def speech(self, text, voice, instructions):
            return np.zeros(SR * 3, dtype=np.float32)

    _, ok = synthesize_gemini_slide(Silent(), SCRIPT, tmp_path / "s.wav", qc_path=tmp_path / "q.json")
    assert not ok and json.loads((tmp_path / "q.json").read_text())["gate_reasons"]


def test_cache_voice_identity_per_engine(tmp_path):
    ref = tmp_path / "r.wav"
    ref.write_bytes(b"ref-bytes")
    raon = {"id": "x", "ref_voice": ref}
    gem = {"id": "x", "tts_engine": "gemini", "tts_voice": "Kore"}
    assert bgl._ref_voice_bytes(raon) == b"ref-bytes"
    assert bgl._ref_voice_bytes(gem) == voice_identity("Kore", None)
    assert bgl._ref_voice_bytes(gem) != bgl._ref_voice_bytes({**gem, "tts_voice": "Puck"})
    assert bgl._ref_voice_bytes(gem) != bgl._ref_voice_bytes({**gem, "tts_instructions": "빠르게"})


def test_temperature_override_changes_the_cache_key(monkeypatch):
    monkeypatch.delenv("LECTURE_AUTO_TTS_TEMPERATURE", raising=False)
    base = bgl._tts_cache_key("s", b"r", 10.0)
    monkeypatch.setenv("LECTURE_AUTO_TTS_TEMPERATURE", "0.85")
    assert bgl._tts_cache_key("s", b"r", 10.0) == base
    monkeypatch.setenv("LECTURE_AUTO_TTS_TEMPERATURE", "0.7")
    assert bgl._tts_cache_key("s", b"r", 10.0) != base


def test_gemini_lecture_synthesizes_through_gemini_not_raon(tmp_path):
    scripts = {1: {"script": SCRIPT, "target_seconds": 30.0}}
    with patch.object(bgl, "synthesize_raon_slide") as raon, \
         patch.object(bgl, "synthesize_gemini_slide", return_value=(tmp_path / "x", True)) as gem:
        bgl._synthesize_all_slides(
            "client", 1, scripts, tmp_path, b"id", (0, 1), None, set(), gemini=("Puck", "빠르게"),
        )
    raon.assert_not_called()
    args, kwargs = gem.call_args
    assert args[0] == "client" and args[2] == tmp_path / "slide_001.wav"
    assert kwargs["voice"] == "Puck" and kwargs["instructions"] == "빠르게"
    assert Path(kwargs["qc_path"]).name == "slide_001.wav.qc.json"
