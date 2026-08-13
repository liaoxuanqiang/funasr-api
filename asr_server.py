"""Thin, robust FastAPI wrapper around FunASR's AutoModel.

Why a custom server instead of `python -m funasr.bin.server`:
FunASR's built-in server crashes with HTTP 500 (`IndexError: list index out of
range` in `_process_fallback`) whenever the ASR model returns an EMPTY result
list.  That happens for everyday input through the PWA: silence/very short
clips, or containers the backend cannot decode (e.g. webm/opus recordings from
MediaRecorder).  This wrapper:
  * decodes audio robustly (soundfile, with an ffmpeg fallback for webm/opus/m4a)
  * turns "no speech recognized" into a graceful HTTP 200 with empty text,
    instead of a crashing 500
  * exposes the same endpoints the PWA and README expect:
      /health, /v1/models, /v1/audio/transcriptions, /recognize, /asr

Run it with:  uvicorn asr_server:app --host 127.0.0.1 --port 8080
"""

import io
import os
import subprocess
import tempfile

import numpy as np

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

MODEL = "paraformer-zh"   # Chinese ASR + punctuation (ModelScope id)
HUB = os.environ.get("ASR_HUB", "ms")
DEVICE = os.environ.get("ASR_DEVICE", "cpu")
TARGET_SR = 16000

app = FastAPI(title="FunASR API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_model = None


def get_model():
    """Lazily load the FunASR AutoModel pipeline (paraformer-zh + VAD + punctuation)."""
    global _model
    if _model is None:
        from funasr import AutoModel

        kwargs = {
            "model": MODEL,
            "hub": HUB,
            "device": DEVICE,
        }
        # These mirror the FunASR reference demo for Chinese punctuation.
        kwargs["vad_model"] = "fsmn-vad"
        kwargs["punc_model"] = "ct-punc"
        try:
            kwargs["disable_update"] = True
        except Exception:
            pass
        _model = AutoModel(**kwargs)
    return _model


def _decode_with_ffmpeg(data):
    """Decode arbitrary bytes (webm/opus/m4a/...) to mono 16k float32 via ffmpeg."""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-f", "s16le", "-ac", "1", "-ar", str(TARGET_SR), "pipe:1",
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg decode failed: " + proc.stderr.decode(errors="ignore").strip()
        )
    raw = proc.stdout
    if not raw:
        raise RuntimeError("ffmpeg produced no audio samples")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, TARGET_SR


def _decode_audio(data, suffix):
    """Return mono float32 audio @16k. Prefers soundfile, falls back to ffmpeg."""
    import soundfile as sf

    audio = sr = None
    try:
        audio, sr = sf.read(io.BytesIO(data))
    except Exception:
        audio = sr = None

    if audio is None:
        audio, sr = _decode_with_ffmpeg(data)

    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if sr != TARGET_SR:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)

    return audio.astype(np.float32), TARGET_SR


def _recognize(file: UploadFile, language: str = "auto"):
    """Run ASR and always return a dict with a 'text' key (never 500 on empty)."""
    try:
        data = file.file.read()
    except Exception as exc:  # pragma: no cover - read errors
        raise HTTPException(400, f"无法读取上传文件: {exc}") from exc

    suffix = os.path.splitext(file.filename or "upload.wav")[1] or ".wav"

    try:
        audio, sr = _decode_audio(data, suffix)
    except Exception as exc:
        raise HTTPException(422, f"无法解码音频（{suffix or 'unknown'}）: {exc}") from exc

    if audio.size == 0:
        # Completely empty audio -> nothing to recognize, not an error.
        return {"text": ""}

    kwargs = {}
    if language and language.strip().lower() not in ("", "auto"):
        kwargs["language"] = language

    raw = get_model().generate(input=audio, **kwargs)

    # raw is a list of per-utterance dicts, e.g. [{"key":..., "text": "..."}].
    # Robustly flatten whatever the model returns back into plain text.
    texts = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                t = item.get("text")
                if t:
                    texts.append(str(t))
            elif item:
                texts.append(str(item))
    elif isinstance(raw, dict):
        t = raw.get("text")
        if t:
            texts.append(str(t))

    return {"text": "\n".join(texts)}


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "models_loaded": [MODEL]}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL, "object": "model"}]}


@app.post("/v1/audio/transcriptions")
def transcriptions(
    file: UploadFile = File(...),
    # OpenAI-compatible endpoints still accept a `model` form field.
    model: str = Form("paraformer"),
    language: str = Form("auto"),
):
    return _recognize(file, language)


@app.post("/recognize")
def recognize(
    file: UploadFile = File(...),
    model: str = Form("paraformer"),
    device: str = Form("cpu"),
    language: str = Form("auto"),
):
    # Legacy-style shape the PWA's extractText() understands.
    body = _recognize(file, language)
    return {"results": [{"text": body["text"]}]}


@app.post("/asr")
def asr_endpoint(
    file: UploadFile = File(...),
    language: str = Form("auto"),
):
    body = _recognize(file, language)
    body["duration"] = 0.0
    body["processing_time"] = 0.0
    return body
