"""
app/ai/media.py — Audio/video transcription using faster-whisper (local, no API key).

Lazy-loads the Whisper "base" model on first use (~142 MB download).
Video files require ffmpeg to be installed (brew install ffmpeg on macOS).
"""

import os
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_whisper_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading faster-whisper 'base' model…")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("faster-whisper model loaded")
    return _whisper_model


def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file to text. Returns plain transcript string."""
    model = _get_whisper()
    segments, info = model.transcribe(audio_path, language="en", beam_size=5)
    transcript = " ".join(s.text.strip() for s in segments)
    logger.info(f"Transcribed {info.duration:.1f}s of audio → {len(transcript)} chars")
    return transcript


def extract_audio_from_video(video_path: str) -> str:
    """
    Extract audio track from a video file using ffmpeg.
    Returns the path to a temporary WAV file (caller must delete it).
    Raises RuntimeError if ffmpeg is not installed or extraction fails.
    """
    audio_path = video_path + "_audio.wav"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-vn",                    # no video
                "-acodec", "pcm_s16le",   # raw PCM
                "-ar", "16000",           # 16 kHz sample rate (Whisper optimum)
                "-ac", "1",               # mono
                audio_path, "-y",
            ],
            capture_output=True, text=True, timeout=300
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")
    return audio_path


async def process_media_file(content: bytes, filename: str) -> dict:
    """
    Main entry point: accepts raw file bytes + filename.
    Handles audio and video. Returns {transcript, duration}.
    """
    suffix = os.path.splitext(filename)[1].lower() or ".tmp"
    is_video = suffix in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    audio_path = None
    try:
        if is_video:
            audio_path = extract_audio_from_video(tmp_path)
            transcribe_path = audio_path
        else:
            transcribe_path = tmp_path

        transcript = transcribe_audio(transcribe_path)
        return {"transcript": transcript, "source": filename}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if audio_path and audio_path != tmp_path:
            try:
                os.unlink(audio_path)
            except OSError:
                pass
