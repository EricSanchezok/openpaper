from __future__ import annotations

import pytest

from src.audio import MossVoiceClient, _audio_format


def test_moss_rejects_non_public_audio_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSS_API_KEY", "test-key")
    monkeypatch.setenv("MOSS_VOICE_ID", "test-voice")
    client = MossVoiceClient()

    with pytest.raises(ValueError, match="not_public"):
        client._validate_url("https://127.0.0.1/audio.mp3")


def test_moss_detects_actual_audio_container() -> None:
    assert _audio_format(b"RIFF\x00\x00\x00\x00WAVEfmt ") == ("wav", "audio/wav")
    assert _audio_format(b"ID3\x04\x00\x00") == ("mp3", "audio/mpeg")
    assert _audio_format(b"\xff\xfb\x90\x64") == ("mp3", "audio/mpeg")
    with pytest.raises(ValueError, match="format_invalid"):
        _audio_format(b"not audio")
