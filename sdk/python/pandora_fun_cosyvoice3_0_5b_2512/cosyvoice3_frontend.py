"""Runtime-owned native model text preparation and tokenizer binding."""

import ctypes as C
import importlib.util
import json
import os
import threading
from pathlib import Path

from ._cosyvoice3_native import _load, check_status, runtime_handle
from ._runtime import Runtime


class _TextFrontendCore:
    """Thin native text binding; owns no FST/reading/tokenization algorithms."""

    def __init__(self, library):
        self.library = library
        self._slot = C.c_void_p()
        spec = importlib.util.find_spec("unidic_lite")
        self._dictionary = os.fsencode(Path(spec.origin).parent / "dicdir") if spec and spec.origin else None
        self._create = library.cv3_text_frontend_create
        self._create.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.POINTER(C.c_void_p)]
        self._create.restype = C.c_int
        self._run = library.cv3_text_frontend_run
        self._run.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_char_p, C.POINTER(C.c_char_p)]
        self._run.restype = C.c_int
        self._destroy = library.cv3_text_frontend_destroy_owned
        self._destroy.argtypes = [C.POINTER(C.c_void_p)]
        self._destroy.restype = C.c_int


    @staticmethod
    def _bytes(value):
        if not isinstance(value, str):
            raise TypeError("text must be a string")
        if "\0" in value:
            raise ValueError("text must be NUL-free")
        return value.encode("utf-8")

    def _request(self, operation, text, language=""):
        if not self._slot.value:
            raise RuntimeError("Text frontend is closed")
        result = C.c_char_p()
        check_status(self.library, self._run(self._slot, operation, self._bytes(text),
                                     self._bytes(language), C.byref(result)))
        # Copy/parse borrowed JSON before another native call on this owner.
        return json.loads(result.value)

    def _ensure_japanese(self):
        from .cosyvoice3_dependencies import require_extra
        require_extra("ja", ("unidic_lite",))

    def is_japanese(self, text):
        return self._request(5, text)

    def encode(self, text, **_):
        return self._request(3, text)

    def _split(self, text, lang):
        if text == "":
            # Retain the historical advanced splitter's empty-input error.
            raise IndexError("string index out of range")
        return self._request(4, text, "zh" if lang == "zh" else "en")

    def normalize(self, text, split=True):
        self._bytes(text)
        special = "<|" in text and "|>" in text
        if text and not special and self._request(5, text):
            self._ensure_japanese()
        return self._request(2 if split else 1, text)

    def prepare(self, text, language):
        if language == "ja":
            self._ensure_japanese()
        elif language == "zh":
            return self.normalize(text, split=False)
        return self._request(0, text, "ja" if language == "ja" else "")

    def close(self):
        if getattr(self, "_slot", None) and self._slot.value:
            check_status(self.library, self._destroy(C.byref(self._slot)))


class TextFrontend:
    """Text preparation and tokenization owned by one native worker."""

    def __init__(self, model_dir, *, runtime=None, library=None):
        if runtime is not None and not isinstance(runtime, Runtime):
            raise TypeError("runtime must be a Pandora Runtime")
        library = _load(library)
        self._bind(library)
        root = Path(model_dir).expanduser().resolve(strict=True)
        with runtime_handle(runtime) as handle:
            rc = self._core._create(os.fsencode(root), self._core._dictionary, handle, C.byref(self._core._slot))
            check_status(library, rc)

    def _bind(self, library):
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._closed = False
        self._core = _TextFrontendCore(library)

    def _check_process(self):
        if self._pid != os.getpid():
            raise RuntimeError("Text frontend inherited through fork")

    def _call(self, name, *args, **kwargs):
        self._check_process()
        with self._lock:
            if self._closed:
                raise RuntimeError("Text frontend is closed")
            return getattr(self._core, name)(*args, **kwargs)

    def _is_japanese(self, text):
        return self._call("is_japanese", text)

    def prepare(self, text, language):
        return self._call("prepare", text, language)

    def normalize(self, text, split=True):
        return self._call("normalize", text, split=split)

    def encode(self, text, **kwargs):
        return self._call("encode", text, **kwargs)

    def _split(self, text, lang):
        return self._call("_split", text, lang)

    def close(self):
        self._check_process()
        with self._lock:
            if not self._closed:
                self._core.close()
                self._core = None
                self._closed = True

    def __enter__(self):
        if self._closed:
            raise RuntimeError("Text frontend is closed")
        return self

    def __exit__(self, *_):
        self.close()
