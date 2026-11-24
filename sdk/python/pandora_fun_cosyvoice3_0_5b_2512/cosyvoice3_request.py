"""Synchronous request ownership; audio transport and playback belong to callers."""

from contextlib import contextmanager
import os
import threading
import numpy as np
from .cosyvoice3_types import (
    AudioChunk,
    SynthesisResult,
    TTSError,
    TTSStateError,
    TTSInferenceError,
    TTSLoadError,
)


@contextmanager
def native_signals():
    # The application owns signal masks and handlers. ctypes calls are synchronous;
    # ownership slots survive an interrupt delivered after native return.
    yield


class _NativeInputError(TTSError, ValueError):
    pass


# The negative status codes defined by the native synthesis ABI.
_NATIVE_ERRORS = {-1: _NativeInputError, -2: TTSLoadError, -4: TTSStateError}


def error(exc, category=None):
    code = getattr(exc, "code", getattr(exc, "native_code", None))
    if category is None:
        category = _NATIVE_ERRORS.get(code, TTSInferenceError)
    return category(str(exc), native_code=code)


class ModelOwner:
    def _ownership(self):
        self._creator_pid = os.getpid()
        self._request = threading.Lock()
        self._closed = False
        self._failed = False
        self._stats = {}

    def _check_process(self):
        if os.getpid() != self._creator_pid:
            raise TTSStateError("Model inherited through fork; initialize a new model in the child after spawn/exec")

    def _claim(self):
        self._check_process()
        if not self._request.acquire(blocking=False):
            raise TTSStateError("Model has an active request; close it first")
        if self._closed or self._failed:
            self._request.release()
            raise TTSStateError("Model is closed or requires recreation after failure")

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def speakers(self):
        return tuple(self._speakers)

    @property
    def languages(self):
        return tuple(self._languages)

    def stats(self):
        self._check_process()
        return dict(self._stats)

    def synthesize(
        self, text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None
    ):
        with self.synthesize_stream(
            text,
            speaker=speaker,
            language=language,
            prompt=prompt,
            seed=seed,
            max_new_tokens=max_new_tokens,
        ) as stream:
            parts = [chunk.audio for chunk in stream]
            if stream.finish_reason not in ("stop", "length"):
                raise TTSInferenceError("Synthesis did not complete normally")
            audio = np.concatenate(parts) if parts else np.empty(0, np.float32)
            return SynthesisResult(audio, stream.sample_rate, stream.finish_reason)

    def synthesize_stream(
        self, text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None
    ):
        self._claim()
        try:
            request = self._validate(
                text, speaker, language, prompt, seed, max_new_tokens
            )
            return AudioStream(self, request)
        except BaseException:
            self._request.release()
            raise

    @contextmanager
    def stage_session(self):
        """Advanced business scheduling owns the same single-request reservation."""
        self._claim()
        try:
            yield self
        finally:
            self._request.release()

    def close(self):
        self._check_process()
        if not self._request.acquire(blocking=False):
            raise TTSStateError("Close the active request before closing the model")
        try:
            if not self._closed:
                self._close_backend()
                self._closed = True
        finally:
            self._request.release()

    def __enter__(self):
        self._check_process()
        if self._closed or self._failed:
            raise TTSStateError("Model is closed or requires recreation after failure")
        return self

    def __exit__(self, *_):
        self.close()


class AudioStream:
    def __init__(self, model, request):
        self._model = model
        self._request = request
        self.sample_rate = model.sample_rate
        self.finish_reason = None
        self._iterator = None
        self._closed = False
        self._operation = threading.Lock()
        self._stop = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self._model._check_process()
        if not self._operation.acquire(blocking=False):
            raise TTSStateError("Stream has an active call")
        try:
            if self._closed:
                raise TTSStateError("Stream is closed")
            if self.finish_reason is not None:
                raise StopIteration
            if self._stop.is_set():
                self.finish_reason = "cancelled"
                raise StopIteration
            if self._iterator is None:
                self._iterator = iter(self._model._audio(self._request, self))
            try:
                audio = next(self._iterator)
            except StopIteration:
                if self.finish_reason not in ("stop", "length", "cancelled"):
                    self._model._failed = True
                    raise TTSInferenceError(
                        "Native stream ended without a terminal reason"
                    )
                raise
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    self._model._failed = True
                    raise
                mapped = exc if isinstance(exc, (TTSError, ValueError, TypeError)) else error(exc)
                if isinstance(mapped, (ValueError, TypeError, TTSStateError)):
                    try:
                        self._close_locked(cancelled=False)
                    except Exception as cleanup_error:
                        raise mapped from cleanup_error
                else:
                    self._model._failed = True
                if mapped is exc:
                    raise
                raise mapped from exc
            if self._stop.is_set():
                self.finish_reason = "cancelled"
                raise StopIteration
            output = np.array(audio, dtype=np.float32, copy=True, order="C")
            if output.ndim != 1 or not np.isfinite(output).all():
                self._model._failed = True
                raise TTSInferenceError("Invalid native audio output")
            return AudioChunk(output, self.sample_rate)
        finally:
            self._operation.release()

    def close(self):
        self._model._check_process()
        self._stop.set()
        with self._operation:
            self._close_locked()

    def _close_locked(self, *, cancelled=True):
        if self._closed:
            return
        try:
            try:
                if self._iterator is not None:
                    self._iterator.close()
            finally:
                self._model._stop_backend()
        except BaseException:
            self._model._failed = True
            raise
        finally:
            if cancelled and self.finish_reason is None:
                self.finish_reason = "cancelled"
            self._closed = True
            self._model._request.release()

    def __enter__(self):
        self._model._check_process()
        if self._closed:
            raise TTSStateError("Stream is closed")
        return self

    def __exit__(self, *_):
        self.close()
