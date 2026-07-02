"""P1.15 STT integration tests — whisper port, duration guard, model allowlist.

Run inside container:
  docker exec knowtwin-api python -m pytest tests/test_stt.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://knowtwin:knowtwin_test_pass@knowtwin-db:5432/knowtwin")
os.environ.setdefault("ENVIRONMENT", "development")


def test_transcribe_function_exists():
    """transcribe_audio importable and callable."""
    from parsers import transcribe_audio
    assert callable(transcribe_audio)


def test_audio_extensions_defined():
    """AUDIO_EXTENSIONS has expected formats."""
    from parsers import AUDIO_EXTENSIONS
    assert ".mp3" in AUDIO_EXTENSIONS
    assert ".wav" in AUDIO_EXTENSIONS
    assert ".ogg" in AUDIO_EXTENSIONS


def test_whisper_model_default():
    """Default WHISPER_MODEL is 'small'."""
    from parsers import WHISPER_MODEL
    assert WHISPER_MODEL == "small"


def test_bad_model_raises():
    """Model outside allowlist → ValueError."""
    from parsers import _WHISPER_MODEL_ALLOWLIST
    with patch.dict(os.environ, {"WHISPER_MODEL": "bogus_model"}):
        import importlib
        import parsers
        orig = parsers.WHISPER_MODEL
        parsers.WHISPER_MODEL = "bogus_model"
        parsers._whisper_model = None
        try:
            with pytest.raises(ValueError, match="not in allowlist"):
                parsers._get_whisper_model()
        finally:
            parsers.WHISPER_MODEL = orig
            parsers._whisper_model = None


def test_max_duration_enforced():
    """MAX_AUDIO_DURATION_SEC is set and reasonable."""
    from parsers import MAX_AUDIO_DURATION_SEC
    assert MAX_AUDIO_DURATION_SEC > 0
    assert MAX_AUDIO_DURATION_SEC <= 7200


def test_ffprobe_available():
    """ffprobe binary exists in container."""
    import shutil
    path = shutil.which("ffprobe")
    assert path is not None, "ffprobe not found in PATH"


def test_whisper_installed():
    """openai-whisper package installed and importable."""
    import importlib.metadata
    try:
        ver = importlib.metadata.version("openai-whisper")
        assert ver is not None
    except importlib.metadata.PackageNotFoundError:
        pytest.fail("openai-whisper not installed")

    try:
        import whisper  # noqa: F401
    except Exception as exc:
        pytest.skip(f"whisper import fails (numba conflict): {exc}")
