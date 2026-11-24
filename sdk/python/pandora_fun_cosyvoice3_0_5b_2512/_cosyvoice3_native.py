"""ctypes binding of libcosyvoice3.so (sdk/include/cosyvoice3.h).

    from .cosyvoice3 import LLM, Token2Wav
    llm, t2w = LLM("models"), Token2Wav("models")
    for o in (llm, t2w):
        o.load_voice("female-zh", "sdk/assets/voices/female-zh")
    t2w.start("female-zh")
    for tok in llm.generate("female-zh", "今天天气很好。", seed=0):
        t2w.push([tok])
        for chunk in t2w.chunks():        # float32 24 kHz arrays, as soon as a chunk is ready
            ...
    t2w.finish()
    for chunk in t2w.chunks(): ...

The library is looked up in $CV3_LIB, sdk/lib/, sdk/build/. The two objects are independent: run them in two
threads to overlap the LLM of the next segment with the vocoding of the current one (calls release the GIL).
"""

import ctypes as C
import json
import os
from contextlib import contextmanager

import numpy as np
from pandora_runtime import load_library

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.path.join(_HERE, "libcosyvoice3.so"),
    os.path.join(_HERE, "..", "lib", "libcosyvoice3.so"),
    os.path.join(_HERE, "..", "build", "libcosyvoice3.so"),
]
END_NONE, END_EOS, END_LIMIT, END_ABORTED = 0, 1, 2, 3


def _package_path(root, relative, role):
    from pathlib import Path
    if not isinstance(relative, str) or not relative or "\\" in relative or "\0" in relative:
        raise ValueError(f"{role}: expected a relative model path")
    path = Path(relative)
    if path.is_absolute() or any(part in (".", "..") for part in relative.split("/")):
        raise ValueError(f"{role}: invalid relative model path")
    root = Path(root).resolve()
    selected = (root / path).resolve()
    if not selected.is_relative_to(root):
        raise ValueError(f"{role}: model path escapes package")
    if not selected.exists():
        raise FileNotFoundError(f"{role}: missing model resource {relative}")
    return str(selected)


def resolve_models(model_dir=None, default_root=None):
    """Resolve root models.json or an explicit legacy package, with unique-child discovery."""
    from pathlib import Path
    strict = model_dir is not None or bool(os.environ.get("CV3_MODELS"))
    explicit = model_dir if model_dir is not None else os.environ.get("CV3_MODELS")
    if explicit is None:
        explicit = default_root
    if explicit is None:
        explicit = Path.cwd() / "models"
    if not os.fspath(explicit):
        raise ValueError("Model package path must not be empty")
    root = Path(explicit).expanduser().resolve()
    def configured(p):
        return (p / "models.json").is_file() or (p / "manifest.json").is_file()
    if configured(root):
        return str(root)
    if strict:
        raise FileNotFoundError(f"No models.json or legacy manifest.json in explicit model package {root}")
    choices = sorted(p for p in root.iterdir() if p.is_dir() and configured(p)) if root.is_dir() else []
    if len(choices) == 1:
        return str(choices[0])
    if choices:
        raise ValueError("Multiple model packages; choose one explicitly: " + ", ".join(map(str, choices)))
    raise FileNotFoundError(f"No models.json or legacy manifest.json in {root}; download a chip package with common resources")


def model_file(model_dir, key):
    """Resolve common model/configuration resources; native code selects and loads target graphs."""
    from pathlib import Path
    root = Path(model_dir)
    modern = root / "models.json"
    with (modern if modern.exists() else root / "manifest.json").open(encoding="utf-8") as f:
        m = json.load(f)
    if modern.exists():
        if m.get("format_version") != 2:
            raise ValueError("Unsupported models.json format_version")
        roles = m.get("resources", {})
    else:
        if m.get("format") != 1:
            raise ValueError("Unsupported legacy manifest format")
        roles = m.get("files", {})
    if key == "voices":
        return _package_path(root, m[key], key) if key in m else None
    relative = roles.get(key) or m.get("extras", {}).get(key)
    if relative is None:
        raise KeyError(f"No model resource role {key}")
    return _package_path(root, relative, key)


class _ProtectionStats(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32),
                ("active_buffers", C.c_uint64), ("dump_excluded_bytes", C.c_uint64),
                ("locked_bytes", C.c_uint64), ("lock_failures", C.c_uint64),
                ("last_lock_errno", C.c_int32), ("reserved", C.c_uint32)]


_provider_pid = None

def _load(library=None):
    global _provider_pid
    if _provider_pid is not None and _provider_pid != os.getpid():
        raise RuntimeError("Native SDK inherited through fork; initialize after spawn/exec")
    _provider_pid = os.getpid()
    try:
        from . import _cosyvoice3_runtime
    except ImportError:
        candidates = _CANDIDATES
    else:
        from pathlib import Path
        candidates = _CANDIDATES if (Path(_HERE).parent / "CMakeLists.txt").is_file() else [str(Path(_cosyvoice3_runtime.__file__).parent / "lib/libcosyvoice3.so")]
    explicit = library if library is not None else os.environ.get("CV3_LIB")
    if explicit is not None:
        from pathlib import Path

        candidates = [str(Path(explicit).expanduser().resolve(strict=True))]
    provider = load_library()
    for p in candidates:
        if p and os.path.exists(p):
            lib = C.CDLL(os.path.abspath(p))
            break
    else:
        raise OSError("libcosyvoice3.so not found (set CV3_LIB or build sdk/)")
    runtime_create = getattr(lib, "pandora_runtime_create", None)
    if (C.cast(runtime_create, C.c_void_p).value != C.cast(provider.pandora_runtime_create, C.c_void_p).value
            or not hasattr(lib, "cv3_reference_project")):
        raise RuntimeError("Install the CosyVoice native library built for the shared Pandora Runtime")
    lib.cv3_get_protection_stats.argtypes = [C.POINTER(_ProtectionStats)]
    lib.cv3_get_protection_stats.restype = C.c_int
    lib.cv3_llm_create_with_runtime.argtypes = [C.c_char_p, C.c_void_p, C.POINTER(C.c_void_p)]
    lib.cv3_llm_create_with_runtime.restype = C.c_int
    lib.cv3_llm_destroy_owned.argtypes = [C.POINTER(C.c_void_p)]
    lib.cv3_llm_destroy_owned.restype = C.c_int
    lib.cv3_t2w_create_with_runtime.argtypes = [C.c_char_p, C.c_void_p, C.POINTER(C.c_void_p)]
    lib.cv3_t2w_create_with_runtime.restype = C.c_int
    lib.cv3_t2w_destroy_owned.argtypes = [C.POINTER(C.c_void_p)]
    lib.cv3_t2w_destroy_owned.restype = C.c_int
    lib.cv3_version.restype = C.c_char_p
    lib.cv3_create_error.restype = C.c_char_p
    if hasattr(lib, "cv3_prepare_process"):
        lib.cv3_prepare_process.argtypes = []
        lib.cv3_prepare_process.restype = C.c_int
    lib.cv3_llm_create.restype = C.c_void_p
    lib.cv3_llm_create.argtypes = [C.c_char_p]
    lib.cv3_llm_destroy.argtypes = [C.c_void_p]
    lib.cv3_llm_last_error.restype = C.c_char_p
    lib.cv3_llm_last_error.argtypes = [C.c_void_p]
    lib.cv3_llm_start.argtypes = [
        C.c_void_p,
        C.c_char_p,
        C.c_char_p,
        C.c_char_p,
        C.c_uint32,
        C.c_int32,
    ]
    lib.cv3_llm_prompt_rows.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
    lib.cv3_llm_count_tokens.argtypes = [C.c_void_p, C.c_char_p]
    lib.cv3_llm_load_voice.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
    lib.cv3_llm_unload_voice.argtypes = [C.c_void_p, C.c_char_p]
    lib.cv3_t2w_load_voice.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
    lib.cv3_t2w_unload_voice.argtypes = [C.c_void_p, C.c_char_p]
    lib.cv3_llm_next.argtypes = [C.c_void_p, C.POINTER(C.c_int32)]
    lib.cv3_llm_end_reason.argtypes = [C.c_void_p]
    lib.cv3_llm_abort.argtypes = [C.c_void_p]
    lib.cv3_llm_get_stats.argtypes = [C.c_void_p, C.c_void_p]
    lib.cv3_t2w_create.restype = C.c_void_p
    lib.cv3_t2w_create.argtypes = [C.c_char_p]
    lib.cv3_t2w_destroy.argtypes = [C.c_void_p]
    lib.cv3_t2w_last_error.restype = C.c_char_p
    lib.cv3_t2w_last_error.argtypes = [C.c_void_p]
    lib.cv3_t2w_max_frames.argtypes = [C.c_void_p]
    lib.cv3_t2w_max_frames.restype = C.c_int
    lib.cv3_t2w_start.argtypes = [C.c_void_p, C.c_char_p, C.c_int32]
    lib.cv3_t2w_push.argtypes = [C.c_void_p, C.c_void_p, C.c_int32]
    lib.cv3_t2w_finish.argtypes = [C.c_void_p]
    lib.cv3_t2w_step.argtypes = [C.c_void_p]
    lib.cv3_t2w_read.argtypes = [C.c_void_p, C.c_void_p, C.c_int32]
    lib.cv3_t2w_done.argtypes = [C.c_void_p]
    lib.cv3_t2w_get_stats.argtypes = [C.c_void_p, C.c_void_p]
    return lib


_lib = None


def lib(library=None):
    return _load(library)


class LlmStats(C.Structure):
    _fields_ = [
        ("text_tokens", C.c_int32),
        ("query_rows", C.c_int32),
        ("tokens", C.c_int32),
        ("max_tokens", C.c_int32),
        ("ms_npu", C.c_double),
        ("ms_host", C.c_double),
    ]


class T2wStats(C.Structure):
    _fields_ = [
        ("tokens", C.c_int32),
        ("chunks", C.c_int32),
        ("samples", C.c_int32),
        ("last_n", C.c_int32),
        ("ms_npu", C.c_double),
        ("ms_host", C.c_double),
    ]


class CV3Error(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f"{msg} (code {code})")
        self.code = code


def check_status(library, rc):
    if rc < 0:
        raise CV3Error(rc, library.cv3_create_error().decode(errors="replace"))


@contextmanager
def runtime_handle(runtime):
    if runtime is None:
        yield None
        return
    with runtime.borrow_handle() as handle:
        yield handle


class LLM:
    """text segment -> speech tokens"""

    def __init__(self, model_dir, *, library=None, runtime=None):
        self._bind(lib(library))
        with runtime_handle(runtime) as handle:
            rc = self._l.cv3_llm_create_with_runtime(os.fsencode(model_dir), handle, C.byref(self._slot))
            check_status(self._l, rc)

    def _bind(self, library):
        self._h = None
        self._pid = os.getpid()
        self._l = library

    @property
    def _h(self):
        if getattr(self, "_pid", os.getpid()) != os.getpid():
            raise CV3Error(-4, "Model inherited through fork; initialize after spawn/exec")
        return self._slot.value

    @_h.setter
    def _h(self, value):
        self._slot = C.c_void_p(value)

    def _check(self, rc):
        if rc < 0:
            raise CV3Error(rc, self._l.cv3_llm_last_error(self._h).decode())
        return rc

    def start(self, voice, text, seed=0, max_tokens=0, instruct=None):
        """instruct: None / "" = zero-shot cloning with the voice prompt, else an instruction ("请用四川话表达。")"""
        self._check(
            self._l.cv3_llm_start(
                self._h,
                voice.encode(),
                (instruct or "").encode("utf-8"),
                text.encode("utf-8"),
                seed & 0xFFFFFFFF,
                int(max_tokens),
            )
        )

    def load_voice(self, voice, npz_path):
        """add (or replace) a voice pack .npz under this id"""
        self._check(
            self._l.cv3_llm_load_voice(self._h, voice.encode(), os.fsencode(npz_path))
        )

    def unload_voice(self, voice):
        self._check(self._l.cv3_llm_unload_voice(self._h, voice.encode()))

    def next(self):
        """-> token or None when the query has ended"""
        t = C.c_int32()
        return (
            t.value
            if self._check(self._l.cv3_llm_next(self._h, C.byref(t))) == 1
            else None
        )

    def generate(self, voice, text, seed=0, max_tokens=0, instruct=None):
        self.start(voice, text, seed, max_tokens, instruct)
        while (t := self.next()) is not None:
            yield t

    def prompt_rows(self, voice, instruct=None):
        """LLM context rows of the prompt (voice prompt or instruction)"""
        return self._check(
            self._l.cv3_llm_prompt_rows(
                self._h, voice.encode(), (instruct or "").encode("utf-8")
            )
        )

    def count_tokens(self, text):
        return self._check(self._l.cv3_llm_count_tokens(self._h, text.encode("utf-8")))

    def end_reason(self):
        return self._l.cv3_llm_end_reason(self._h)

    def abort(self):
        self._l.cv3_llm_abort(self._h)

    def stats(self):
        s = LlmStats()
        self._check(self._l.cv3_llm_get_stats(self._h, C.byref(s)))
        return {k: getattr(s, k) for k, _ in LlmStats._fields_}

    def close(self):
        if self._h:
            rc = self._l.cv3_llm_destroy_owned(C.byref(self._slot))
            if rc < 0: raise CV3Error(rc, self._l.cv3_create_error().decode())

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class Token2Wav:
    """speech tokens -> 24 kHz audio chunks (streaming)"""

    def __init__(self, model_dir, *, library=None, runtime=None):
        self._bind(lib(library))
        with runtime_handle(runtime) as handle:
            rc = self._l.cv3_t2w_create_with_runtime(os.fsencode(model_dir), handle, C.byref(self._slot))
            check_status(self._l, rc)

    def _bind(self, library):
        self._buf = np.zeros(1 << 16, np.float32)
        self._h = None
        self._pid = os.getpid()
        self._l = library

    @property
    def _h(self):
        if getattr(self, "_pid", os.getpid()) != os.getpid():
            raise CV3Error(-4, "Model inherited through fork; initialize after spawn/exec")
        return self._slot.value

    @_h.setter
    def _h(self, value):
        self._slot = C.c_void_p(value)

    def _check(self, rc):
        if rc < 0:
            raise CV3Error(rc, self._l.cv3_t2w_last_error(self._h).decode())
        return rc

    def load_voice(self, voice, npz_path):
        """add (or replace) a voice pack .npz under this id (not the voice of a running stream)"""
        self._check(
            self._l.cv3_t2w_load_voice(self._h, voice.encode(), os.fsencode(npz_path))
        )

    def unload_voice(self, voice):
        """remove a voice; a stream of that voice that has not finished is dropped"""
        self._check(self._l.cv3_t2w_unload_voice(self._h, voice.encode()))

    def start(self, voice, hop_max=200):
        self._check(self._l.cv3_t2w_start(self._h, voice.encode(), int(hop_max)))

    def push(self, tokens):
        """append speech tokens -> how many were accepted (tokens beyond the largest DiT bucket are dropped)"""
        a = np.ascontiguousarray(tokens, np.int32)
        return self._check(self._l.cv3_t2w_push(self._h, a.ctypes.data, a.size))

    def finish(self):
        self._check(self._l.cv3_t2w_finish(self._h))

    def step(self):
        """compute the next chunk if possible -> number of samples queued (0: needs tokens or done)"""
        return self._check(self._l.cv3_t2w_step(self._h))

    def read(self):
        out = []
        while (
            n := self._check(
                self._l.cv3_t2w_read(self._h, self._buf.ctypes.data, self._buf.size)
            )
        ) > 0:
            out.append(self._buf[:n].copy())
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def abort(self):
        abort = getattr(self._l, "cv3_t2w_abort", None)
        if abort is not None:
            abort.argtypes = [C.c_void_p]
            abort.restype = C.c_int
            self._check(abort(self._h))

    def chunks(self):
        """every chunk that can be computed now"""
        while self.step() > 0:
            yield self.read()

    def done(self):
        return self._l.cv3_t2w_done(self._h) == 1

    def stats(self):
        s = T2wStats()
        self._check(self._l.cv3_t2w_get_stats(self._h, C.byref(s)))
        return {k: getattr(s, k) for k, _ in T2wStats._fields_}

    def close(self):
        if self._h:
            rc = self._l.cv3_t2w_destroy_owned(C.byref(self._slot))
            if rc < 0: raise CV3Error(rc, self._l.cv3_create_error().decode())

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def version():
    return lib().cv3_version().decode()
