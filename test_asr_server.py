"""Offline unit test for asr_server.py core logic (no funasr/fastapi/ffmpeg needed).

Stubs the imported frameworks, then asserts:
  1. normal recognition flattens AutoModel output to text
  2. EMPTY result list -> graceful {"text": ""} (this is the fixed 500)
  3. /recognize legacy shape wraps results for the PWA's extractText()
"""
import io
import sys
import types
import unittest.mock as mock

# ---------------- stub numpy (only needed for import to succeed) ----------
numpy_mod = types.ModuleType("numpy")
numpy_mod.frombuffer = lambda *a, **k: []
numpy_mod.int16 = "int16"
numpy_mod.float32 = "float32"
numpy_mod.asarray = lambda *a, **k: a[0] if a else []
sys.modules["numpy"] = numpy_mod

# ---------------- stub fastapi ----------------
fastapi_mod = types.ModuleType("fastapi")
fastapi_cors = types.ModuleType("fastapi.middleware.cors")


class _F:
    """FastAPI lookalike that records routes but otherwise is inert."""

    def __init__(self, *a, **k):
        self.routes = []

    def add_middleware(self, *a, **k):
        self._mw = (a, k)

    def _route(self, path):
        def deco(fn):
            self.routes.append((path, fn))
            return fn

        return deco

    def get(self, path):
        return self._route(path)

    def post(self, path):
        return self._route(path)


class _Param:
    def __init__(self, default=None):
        self.default = default

    def __call__(self, *a, **k):
        return self


class _UploadFile:
    def __init__(self, data: bytes, filename: str):
        self.file = io.BytesIO(data)
        self.filename = filename

    def read(self):
        return self.file.read()


class _HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


fastapi_mod.FastAPI = _F
fastapi_mod.File = lambda *a, **k: _Param()
fastapi_mod.Form = lambda *a, **k: _Param(*a, **k)
fastapi_mod.UploadFile = _UploadFile
fastapi_mod.HTTPException = _HTTPException
fastapi_cors.CORSMiddleware = object
sys.modules["fastapi"] = fastapi_mod
sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
sys.modules["fastapi.middleware.cors"] = fastapi_cors

import asr_server  # noqa: E402

# ---------------- helpers ----------------
def make_upload(data: bytes = b"\x00" * 1600, name: str = "clip.wav"):
    return _UploadFile(data, name)


def run(fn, **kwargs):
    """Call a FastAPI endpoint function with an `file` UploadFile kwarg."""
    kwargs.setdefault("language", "auto")
    return fn(file=make_upload(), **kwargs)


# 1) normal recognition
fake_model = mock.MagicMock()
fake_model.generate.return_value = [{"text": "你好世界"}]
asr_server.get_model = lambda: fake_model
asr_server._decode_audio = lambda d, s: (mock.MagicMock(size=8000), 16000)

res = run(asr_server.transcriptions, model="paraformer")
assert res == {"text": "你好世界"}, res
print("PASS 1: normal recognition ->", res)

# 2) EMPTY result list must NOT crash (the real bug) -> graceful empty text
fake_model.generate.return_value = []
res = run(asr_server.transcriptions, model="paraformer")
assert res == {"text": ""}, res
print("PASS 2: empty model result -> graceful", res)

# 3) nested dict result
fake_model.generate.return_value = [{"key": "x", "text": "你好"}]
res = run(asr_server.transcriptions, model="paraformer")
assert res == {"text": "你好"}, res
print("PASS 3: nested text extraction ->", res)

# 4) legacy /recognize shape understood by PWA extractText()
fake_model.generate.return_value = [{"text": "欢迎"}]
res = run(asr_server.recognize, model="paraformer", device="cpu")
assert res == {"results": [{"text": "欢迎"}]}, res
print("PASS 4: /recognize legacy shape ->", res)

print("ALL TESTS PASSED")