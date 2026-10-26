"""Tests for the /transcribe audio endpoint and Groq Whisper STT integration."""

import io
import wave
import struct
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from main import app
from llm import transcribe_audio

client = TestClient(app)


def _create_mock_wav(duration_sec: float = 0.5) -> bytes:
    """Generate dummy PCM WAV audio bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = int(16000 * duration_sec)
        w.writeframes(struct.pack("<" + ("h" * frames), *([0] * frames)))
    return buf.getvalue()


def test_transcribe_empty_audio():
    """Empty audio should return error status gracefully."""
    response = client.post(
        "/transcribe",
        files={"file": ("empty.webm", b"", "audio/webm")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "Empty" in data["error"]
    assert data["text"] == ""


def test_transcribe_tiny_audio():
    """Files smaller than 32 bytes should be rejected as invalid."""
    response = client.post(
        "/transcribe",
        files={"file": ("tiny.webm", b"too_short", "audio/webm")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["text"] == ""


def test_transcribe_success_mocked():
    """Mocked successful Groq Whisper transcription."""
    wav_bytes = _create_mock_wav(0.2)

    with patch("main.transcribe_audio", return_value="मैं उन्नाव से हूँ और मेरे पास 2 एकड़ जमीन है") as mock_stt:
        response = client.post(
            "/transcribe",
            files={"file": ("speech.wav", wav_bytes, "audio/wav")},
            data={"lang": "hi"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["text"] == "मैं उन्नाव से हूँ और मेरे पास 2 एकड़ जमीन है"
        mock_stt.assert_called_once()
        args, kwargs = mock_stt.call_args
        assert kwargs["language"] == "hi"
        assert kwargs["filename"] == "speech.wav"


def test_transcribe_failure_handled():
    """When speech-to-text raises an exception, endpoint returns status='error' with explanation."""
    wav_bytes = _create_mock_wav(0.2)

    with patch("main.transcribe_audio", side_effect=RuntimeError("Groq 503 Service Unavailable")):
        response = client.post(
            "/transcribe",
            files={"file": ("speech.wav", wav_bytes, "audio/wav")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "Groq 503" in data["error"]
        assert data["text"] == ""


def test_llm_transcribe_missing_key():
    """transcribe_audio without GROQ_API_KEY should raise ValueError."""
    with patch("llm._get_groq_client", return_value=None):
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            transcribe_audio(b"some_bytes", filename="test.wav")


def test_llm_transcribe_groq_client_mock():
    """transcribe_audio properly delegates to client.audio.transcriptions.create."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "  Hello from Groq Whisper  "
    mock_client.audio.transcriptions.create.return_value = mock_resp

    with patch("llm._get_groq_client", return_value=mock_client):
        result = transcribe_audio(
            b"fake_audio_bytes",
            filename="rec.webm",
            mime_type="audio/webm",
            language="en",
        )
        assert result == "Hello from Groq Whisper"
        mock_client.audio.transcriptions.create.assert_called_once()
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["file"][0] == "rec.webm"
        assert call_kwargs["file"][1] == b"fake_audio_bytes"
        assert call_kwargs["language"] == "en"
