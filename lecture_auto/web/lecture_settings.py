from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lecture_auto.web.accounts import Accounts
from lecture_auto.web.settings import NEW_LECTURE_REF_VOICE, Settings
from lecture_auto.web.voices import validate_ref, voice_path

GEMINI_VOICES = frozenset(
    ["Aoede", "Achernar", "Autonoe", "Callirrhoe", "Despina", "Erinome", "Gacrux", "Kore",
     "Laomedeia", "Leda", "Pulcherrima", "Sulafat", "Vindemiatrix", "Zephyr", "Achird", "Algenib",
     "Algieba", "Alnilam", "Charon", "Enceladus", "Fenrir", "Iapetus", "Orus", "Puck",
     "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar", "Umbriel", "Zubenelgenubi"]
)


NO_RAON = "이 서버는 GPU가 없어 Gemini 음성만 쓸 수 있습니다. 음성 설정에서 Gemini 음성을 골라 주세요"


class LectureSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    tts_engine: Literal["raon", "gemini"] = "raon"
    tts_voice: str | None = None
    tts_instructions: str | None = Field(default=None, max_length=2000)
    ref_voice: Path | None = None

    @model_validator(mode="after")
    def valid_voice(self):
        if self.tts_engine == "gemini" and self.tts_voice not in GEMINI_VOICES:
            raise ValueError("Gemini 음성을 선택해 주세요")
        return self


def resolved_settings(settings: Settings, accounts: Accounts, owner: str | None,
                      selection: LectureSettings) -> LectureSettings:
    match selection.tts_engine:
        case "gemini":
            return selection.model_copy(update={"ref_voice": None})
        case "raon":
            if not settings.raon_enabled:
                raise HTTPException(400, NO_RAON)
            ref = selection.ref_voice
            if ref is None:
                with accounts.connect() as db:
                    default = db.execute(
                        "SELECT id FROM voices WHERE user_id=? AND is_default=1 AND disabled=0", (owner,)
                    ).fetchone()
                ref = voice_path(settings, owner, default["id"]) if default else NEW_LECTURE_REF_VOICE
            validate_ref(settings, accounts, owner, ref)
            return selection.model_copy(update={"ref_voice": ref, "tts_voice": None, "tts_instructions": None})
    raise HTTPException(400, "음성 엔진을 확인해 주세요")
