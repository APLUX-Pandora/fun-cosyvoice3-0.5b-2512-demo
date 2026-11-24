"""CosyVoice task API and its existing advanced native stages."""

import ctypes as C
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from ._cosyvoice3_native import (
    LLM,
    Token2Wav,
    CV3Error,
    END_NONE,
    END_EOS,
    END_LIMIT,
    END_ABORTED,
    resolve_models,
    model_file,
    version,
)
from ._cosyvoice3_native import _load, check_status, lib, runtime_handle
from .cosyvoice3_types import (
    TTSError,
    TTSLoadError,
    TTSInferenceError,
    TTSStateError,
    TTSUnsupportedError,
    TTSCapabilities,
    AudioChunk,
    SynthesisResult,
    LANGUAGES,
    string,
    options,
)
from ._runtime import Runtime
from .cosyvoice3_request import ModelOwner, native_signals, error

CROSS_LINGUAL = "You are a helpful assistant.<|endofprompt|>"


def prepare_process(*, library=None):
    """Compatibility no-op. Model-buffer protection is automatic and leaves host policy unchanged."""
    lib = _load(library)
    rc = lib.cv3_prepare_process()
    if rc < 0:
        raise TTSLoadError(lib.cv3_create_error().decode(errors="replace"))


def protection_status(*, library=None):
    """Snapshot process-local SDK-owned buffers, without exposing addresses or model data."""
    import ctypes
    from ._cosyvoice3_native import _ProtectionStats
    lib = _load(library)
    out = _ProtectionStats()
    out.struct_size, out.abi_version = ctypes.sizeof(out), 1
    rc = lib.cv3_get_protection_stats(ctypes.byref(out))
    if rc < 0:
        raise TTSLoadError(lib.cv3_create_error().decode(errors="replace"))
    return {"scope": "process-owned SDK context buffers", "active_buffers": out.active_buffers,
            "dump_excluded_bytes": out.dump_excluded_bytes, "locked_bytes": out.locked_bytes,
            "unlocked_bytes": out.dump_excluded_bytes - out.locked_bytes,
            "lock_failures": out.lock_failures, "last_lock_errno": out.last_lock_errno}


def _asset_root():
    folder = Path(__file__).resolve().parent
    if (folder.parent / "CMakeLists.txt").is_file():
        return folder.parent / "assets"
    from . import _cosyvoice3_runtime
    return Path(_cosyvoice3_runtime.__file__).parent / "assets"


_REQUIRED = (
    "prompt_text_ids",
    "prompt_text_rows",
    "llm_prompt_token",
    "flow_prompt_token",
    "prompt_feat",
    "embedding",
)


def _script(text):
    if re.search("[\u3040-\u30ff]", text):
        return "ja"
    scores = {
        key: len(re.findall(pattern, text))
        for key, pattern in [
            ("zh", "[\u4e00-\u9fff]"),
            ("ko", "[\uac00-\ud7a3]"),
            ("latin", "[A-Za-z]"),
            ("cyrillic", "[\u0400-\u04ff]"),
        ]
    }
    return max(scores, key=scores.get) if any(scores.values()) else None


def _language_group(language):
    return (
        "latin"
        if language in ("en", "de", "fr", "es", "it")
        else "cyrillic" if language == "ru" else language
    )


class TTSModel(ModelOwner):
    _capabilities = TTSCapabilities(True, True, True, True)

    @classmethod
    def from_pretrained(cls, model_dir, *, voices_dir=None, runtime=None):
        if model_dir is None:
            raise TypeError("model_dir must be a path")
        if runtime is not None and not isinstance(runtime, Runtime):
            raise TypeError("runtime must be a Pandora Runtime")
        model = cls.__new__(cls)
        model._ownership()
        model.llm = model.t2w = model._frontend = None
        model._runtime = runtime
        model._voices = {}
        model._speakers = ()
        model._temporary = tempfile.TemporaryDirectory(prefix="cosyvoice-speakers-")
        try:
            model.model_dir = resolve_models(model_dir)
            with native_signals():
                model._load_stages(runtime)
            model.sdk_version = model.llm._l.cv3_version().decode()
            model.sample_rate = 24000
            model._languages = tuple(k for k in LANGUAGES if k != "pt")
            from .cosyvoice3_voices import MODEL_ID, collection
            profile=json.loads((_asset_root()/"tts-model.json").read_text())
            if profile["model_id"] != MODEL_ID:
                raise ValueError("Incompatible packaged voice profile")
            # The model SDK declares its immutable built-in collection explicitly.
            builtin=_asset_root()/profile["builtin_voices"]
            for package in collection(builtin):
                model._install_package(package)
            if voices_dir is not None:
                for package in collection(voices_dir):
                    model._install_package(package)
            return model
        except BaseException as exc:
            model._close_backend()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise error(exc, TTSLoadError) from exc

    def _load_stages(self, runtime):
        from .cosyvoice3_frontend import TextFrontend

        library = lib()
        llm = LLM.__new__(LLM)
        llm._bind(library)
        t2w = Token2Wav.__new__(Token2Wav)
        t2w._bind(library)
        frontend = TextFrontend.__new__(TextFrontend)
        frontend._bind(library)
        self.llm, self.t2w, self._frontend = llm, t2w, frontend
        create = library.cv3_internal_tts_create
        slot = C.POINTER(C.c_void_p)
        create.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, slot, slot, slot]
        create.restype = C.c_int
        with runtime_handle(runtime) as handle:
            check_status(library, create(os.fsencode(self.model_dir), frontend._core._dictionary, handle,
                                         C.byref(llm._slot), C.byref(t2w._slot), C.byref(frontend._core._slot)))

    def _install_package(self, path):
        from .cosyvoice3_voices import validate_package
        meta,arrays,identity=validate_package(path)
        vid=meta["id"]
        if vid in self._voices:
            if identity != self._voices[vid]["identity"]:
                raise ValueError("Conflicting conditioning for speaker: "+vid)
            return vid
        owned=Path(self._temporary.name)/vid
        try:
            shutil.copytree(path,owned)
        except BaseException:
            if owned.exists():shutil.rmtree(owned)
            raise
        attempted=[]
        self._failed=True
        try:
            # Revalidate the retained copy before exposing either native stage.
            validate_package(owned)
            for stage in (self.llm,self.t2w):
                attempted.append(stage)
                with native_signals():stage.load_voice(vid,owned)
        except BaseException as original:
            clean=True
            for stage in reversed(attempted):
                try:
                    with native_signals():stage.unload_voice(vid)
                except Exception as cleanup:
                    if "unknown voice" not in str(cleanup):clean=False
            shutil.rmtree(owned)
            self._failed=not clean
            if not clean:raise TTSInferenceError("Voice registration rollback failed; recreate model") from original
            raise
        self._voices[vid]={"meta":meta,"path":owned,"identity":identity,
                           "source":Path(path).absolute(),"prompt_tokens":int(arrays["flow_prompt_token"].size)}
        self._speakers=tuple(self._voices)
        self._failed=False
        return vid

    def load_voice(self, voice_package_dir):
        self._claim()
        try:
            return self._install_package(voice_package_dir)
        except (KeyboardInterrupt,SystemExit,ValueError,TypeError):
            raise
        except Exception as exc:
            raise error(exc,TTSLoadError) from exc
        finally:
            self._request.release()

    def unload_voice(self, speaker_id):
        self._claim()
        try:
            vid=string(speaker_id,"speaker")
            if vid not in self._voices:raise ValueError("Unknown speaker: "+vid)
            voice=self._voices[vid]
            self._failed=True
            try:
                for stage in (self.llm,self.t2w):
                    with native_signals():stage.unload_voice(vid)
            except BaseException as original:
                clean=True
                for stage in (self.llm,self.t2w):
                    try:
                        with native_signals():stage.load_voice(vid,voice["path"])
                    except BaseException:clean=False
                self._failed=not clean
                if not clean:raise TTSInferenceError("Voice unload rollback failed; recreate model") from original
                raise
            del self._voices[vid]
            self._speakers=tuple(self._voices)
            shutil.rmtree(voice["path"])
            self._failed=False
        finally:
            self._request.release()

    def _validate(self, *args):
        request = options(*args, self.speakers, self.languages, True)
        if request["language"] == "ja" or (request["language"] == "zh" and self._frontend._is_japanese(request["text"])):
            from .cosyvoice3_dependencies import require_extra
            require_extra("ja", ("unidic_lite",))
        return request

    def _text(self, text, language):
        return self._frontend.prepare(text, language)

    def _audio(self, request, stream):
        text = self._text(request["text"], request["language"])
        string(text, "prepared text")
        voice = self._voices[request["speaker"]]
        prompt = request["prompt"]
        ref_language = voice["meta"].get("reference_language") or voice["meta"].get("language")
        same = (
            (ref_language == request["language"])
            if ref_language
            else (
                _script(voice["meta"].get("prompt_text", ""))
                == _language_group(request["language"])
            )
        )
        if prompt is None and (
            not same
            or re.search(r"\[(?:breath|laughter|sigh|cough|noise)\]|</?strong>", text)
        ):
            prompt = CROSS_LINGUAL
        frames = self.t2w._l.cv3_t2w_max_frames(self.t2w._h)
        self.t2w._check(frames)
        capacity = frames // 2 - voice["prompt_tokens"]
        if capacity < 1:
            raise TTSInferenceError("Speaker prompt leaves no waveform capacity")
        limit = (
            min(request["max_new_tokens"], capacity)
            if request["max_new_tokens"]
            else capacity
        )
        if stream._stop.is_set():
            stream.finish_reason = "cancelled"
            return
        with native_signals():
            self.t2w.start(request["speaker"])
            if stream._stop.is_set():
                stream.finish_reason = "cancelled"
                return
            self.llm.start(
                request["speaker"], text, request["seed"], limit, instruct=prompt
            )
        self._last_tokens = []
        while not stream._stop.is_set():
            with native_signals():
                token = self.llm.next()
            if token is None or stream._stop.is_set():
                break
            self._last_tokens.append(token)
            with native_signals():
                if self.t2w.push([token]) != 1:
                    raise TTSInferenceError(
                        "Waveform stage rejected a generated speech token"
                    )
            while not stream._stop.is_set():
                with native_signals():
                    count = self.t2w.step()
                    if not count or stream._stop.is_set():
                        break
                    chunk = self.t2w.read()
                self._stats = {"llm": self.llm.stats(), "token2wav": self.t2w.stats()}
                if len(chunk):
                    yield chunk
        if stream._stop.is_set():
            stream.finish_reason = "cancelled"
            return
        reason = {END_EOS: "stop", END_LIMIT: "length", END_ABORTED: "cancelled"}.get(
            self.llm.end_reason()
        )
        if reason is None:
            raise TTSInferenceError("Unknown native speech-token ending")
        if reason == "cancelled":
            stream.finish_reason = reason
            return
        with native_signals():
            self.t2w.finish()
        while not stream._stop.is_set():
            with native_signals():
                count = self.t2w.step()
                if stream._stop.is_set():
                    break
                chunk = self.t2w.read()
                done = self.t2w.done()
            if len(chunk):
                yield chunk
            if done:
                break
            if not count:
                raise TTSInferenceError("Waveform final drain stalled")
        self._stats = {"llm": self.llm.stats(), "token2wav": self.t2w.stats()}
        stream.finish_reason = "cancelled" if stream._stop.is_set() else reason

    def _stop_backend(self):
        with native_signals():
            if self.llm is not None:
                self.llm.abort()
            if self.t2w is not None:
                self.t2w.abort()

    def _close_backend(self):
        first_error = None
        # A failed CPU-session cleanup must never skip either native owner.
        for name in ("_frontend", "t2w", "llm"):
            owner = getattr(self, name)
            if owner is None:
                continue
            try:
                with native_signals():
                    owner.close()
                setattr(self, name, None)
            except BaseException as exc:
                self._failed = True
                if first_error is None:
                    first_error = exc
        try:
            self._temporary.cleanup()
            self._runtime = None
        except BaseException as exc:
            self._failed = True
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error



__all__ = [
    "prepare_process",
    "protection_status",
    "TTSModel",
    "TTSError",
    "TTSLoadError",
    "TTSInferenceError",
    "TTSStateError",
    "TTSUnsupportedError",
    "TTSCapabilities",
    "AudioChunk",
    "SynthesisResult",
    "LLM",
    "Token2Wav",
    "CV3Error",
    "END_NONE",
    "END_EOS",
    "END_LIMIT",
    "END_ABORTED",
    "resolve_models",
    "model_file",
    "version",
]
