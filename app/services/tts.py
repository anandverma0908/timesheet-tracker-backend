"""
app/services/tts.py — Local voice cloning TTS via Coqui XTTS-v2.

Uses Apple M4 Metal (MPS) acceleration when available.
Voice reference file is stored at uploads/voice_ref.wav (per-org, per-user override possible).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
_tts_instance = None
_tts_lock = asyncio.Lock()


def _get_device() -> str:
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _load_tts():
    """Load XTTS-v2 model (blocking — called once in a thread pool)."""
    global _tts_instance
    if _tts_instance is not None:
        return _tts_instance
    try:
        import os as _os
        import torch
        import functools
        _os.environ.setdefault("COQUI_TOS_AGREED", "1")
        # PyTorch 2.6+ changed weights_only default to True which breaks TTS checkpoints
        _orig_load = torch.load
        torch.load = functools.partial(_orig_load, weights_only=False)
        from TTS.api import TTS
        device = _get_device()
        logger.info("Loading XTTS-v2 on device: %s", device)
        tts = TTS(_MODEL_NAME, progress_bar=False).to(device)
        _tts_instance = tts
        logger.info("XTTS-v2 loaded successfully on %s", device)
        return tts
    except Exception as e:
        logger.error("Failed to load XTTS-v2: %s", e)
        raise


async def get_tts():
    """Return cached TTS instance, loading it lazily (thread-safe)."""
    global _tts_instance
    async with _tts_lock:
        if _tts_instance is None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _load_tts)
    return _tts_instance


def voice_ref_path(upload_dir: str, user_id: Optional[str] = None) -> Path:
    """Return path to voice reference WAV — user-specific if user_id given, else global."""
    base = Path(upload_dir)
    base.mkdir(parents=True, exist_ok=True)
    if user_id:
        return base / f"voice_ref_{user_id}.wav"
    return base / "voice_ref.wav"


def has_voice_ref(upload_dir: str, user_id: Optional[str] = None) -> bool:
    return voice_ref_path(upload_dir, user_id).exists()


async def synthesise(
    text: str,
    upload_dir: str,
    user_id: Optional[str] = None,
    language: str = "en",
) -> bytes:
    """
    Generate speech audio (WAV bytes) from text using the stored voice reference.
    Falls back to global ref if user-specific one doesn't exist.
    """
    ref = voice_ref_path(upload_dir, user_id)
    if not ref.exists():
        ref = voice_ref_path(upload_dir, None)
    if not ref.exists():
        raise FileNotFoundError("No voice reference file found. Please upload a voice sample first.")

    tts = await get_tts()

    def _run() -> bytes:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            tts.tts_to_file(
                text=text,
                speaker_wav=str(ref),
                language=language,
                file_path=tmp_path,
            )
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            import os as _os
            _os.unlink(tmp_path)

    loop = asyncio.get_event_loop()
    audio_bytes = await loop.run_in_executor(None, _run)
    return audio_bytes
