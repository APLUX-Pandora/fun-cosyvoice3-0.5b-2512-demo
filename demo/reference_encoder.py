"""Application-owned reference conditioning with ONNX Runtime CPU sessions."""

import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import os
import threading
from pathlib import Path
import time

import numpy as np

from pandora_fun_cosyvoice3_0_5b_2512._cosyvoice3_native import _load, check_status

MIN_SR = 16000
MIN_S, MAX_S = 3.0, 10.0


class CloneError(ValueError):
    """a rejected input; code: id / text / text_long / sample_rate / length / silent (+ consent / name / format from
    read_request)"""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def validate_audio(x, sr):
    """Reject invalid or effectively silent references before feature extraction.

    Require 200 ms of AC signal above -80 dBFS in 20 ms frames. Removing each
    frame's DC component prevents a constant input from passing as sound. This
    is an input-level check, not a speech or speaker-identity detector.
    """
    if not isinstance(x, np.ndarray) or x.dtype != np.float32:
        raise TypeError("reference audio must be a float32 NumPy array")
    if isinstance(sr, (bool, np.bool_)) or not isinstance(sr, (int, np.integer)):
        raise TypeError("sample rate must be an integer")
    if sr < MIN_SR or sr > 2**31-1:
        raise CloneError("sample_rate", f"sample rate {sr} Hz must be within {MIN_SR}..2147483647 Hz")
    if x.ndim != 1 or not x.size or not np.isfinite(x).all():
        raise CloneError("format", "reference audio must contain finite mono samples")
    dur = x.size / sr
    if not MIN_S <= dur <= MAX_S:
        raise CloneError(
            "length",
            f"reference length {dur:.1f} s is outside {MIN_S:.0f}-{MAX_S:.0f} s",
        )
    width = max(1, round(sr * 0.02))
    frames = x[: x.size // width * width].astype(np.float64).reshape(-1, width)
    frames = frames - frames.mean(axis=1, keepdims=True)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    if np.count_nonzero(rms >= 1e-4) * width / sr < 0.2:
        raise CloneError(
            "silent",
            "No usable sound was detected. Check the microphone and input volume, "
            "record again, and listen to the recording before cloning.",
        )


# ---------------------------------------------------------------------------------------------------- resampling
def resample(x, orig, new):
    """Adapt mono reference audio for the voice preview."""
    return _resample(x, orig, new, _load())


def _resample(x, orig, new, library):
    if type(orig) is not int or type(new) is not int:
        raise TypeError("sample rates must be integers")
    if not 16000 <= orig <= 2**31 - 1 or new not in (16000, 24000):
        raise ValueError("reference resampling requires original >= 16000 and target 16000 or 24000")
    data = np.ascontiguousarray(x, np.float32)
    if data.ndim != 1 or not 0 < data.size <= orig * 10:
        raise ValueError("reference resampling requires bounded mono PCM")
    out = np.empty((data.size * new + orig - 1) // orig, np.float32)
    function = library.cv3_reference_resample
    pointer = C.POINTER(C.c_float)
    function.argtypes = [C.c_void_p, pointer, C.c_uint64, C.c_uint32, C.c_uint32, pointer, C.c_uint64]
    function.restype = C.c_int
    check_status(library, function(None, data.ctypes.data_as(pointer), data.size, orig, new,
                            out.ctypes.data_as(pointer), out.size))
    return out


def read_reference(audio_path):
    """Validate bounded reference duration before allocating decoded audio or CPU model sessions."""
    import soundfile as sf

    info = sf.info(audio_path)
    if info.samplerate < MIN_SR:
        raise CloneError(
            "sample_rate", "Reference sample rate must be at least 16000 Hz"
        )
    duration = info.frames / info.samplerate
    if not MIN_S <= duration <= MAX_S:
        raise CloneError("length", "Reference must contain 3–10 seconds of audio")
    x, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    x = x.mean(axis=1).astype(np.float32)
    validate_audio(x, sr)
    return x, sr


class ReferenceEncoder:
    def __init__(self, model_dir, clone_models, *, threads=4, library=None):
        if type(threads) is not int:
            raise TypeError("threads must be an integer")
        if not 0 <= threads <= 2**31 - 1:
            raise ValueError("threads must be a nonnegative int32")
        self.tokenizer = self.speaker = self.text_tokenizer = self.table = None
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._aux = None
        try:
            self._library = _load(library)
            if not all(hasattr(self._library,name) for name in ("cv3_reference_project", "cv3_reference_rfft", "cv3_reference_features")):
                raise RuntimeError("Reference encoding requires the matching native library")
            self._aux = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reference")
            self._call(self._initialize, model_dir, clone_models, threads)
        except BaseException:
            self.close()
            raise

    def _initialize(self, model_dir, clone_models, threads):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from pandora_fun_cosyvoice3_0_5b_2512._cosyvoice3_native import model_file

        root = Path(clone_models).expanduser().resolve(strict=True)
        self._feature_assets = str((Path(__file__).resolve().parent / "assets/clone_assets.npz").resolve(strict=True))
        self.effective_threads = threads or max(1, len(os.sched_getaffinity(0)))
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.effective_threads
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.tokenizer = ort.InferenceSession(str(root / "speech_tokenizer_v3.onnx"), options,
                                              providers=["CPUExecutionProvider"])
        self.speaker = ort.InferenceSession(str(root / "campplus.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        if (len(self.tokenizer.get_inputs()), len(self.tokenizer.get_outputs()),
                len(self.speaker.get_inputs()), len(self.speaker.get_outputs())) != (2, 1, 1, 1):
            raise ValueError("Unexpected voice model inputs or outputs")
        self.text_tokenizer = Tokenizer.from_file(model_file(model_dir, "tokenizer"))
        self.table = np.load(model_file(model_dir, "text_embedding"), mmap_mode="r", allow_pickle=False)
        if (self.table.dtype != np.float32 or not self.table.flags.c_contiguous
                or self.table.ndim != 2 or self.table.shape[1] != 896):
            raise ValueError("Expected a row-major float32 text table with 896 columns")

    def _check_process(self):
        if self._pid != os.getpid():
            raise RuntimeError("ReferenceEncoder inherited through fork")

    def _call(self, function, *args):
        self._check_process()
        with self._lock:
            if self._aux is None:
                raise RuntimeError("ReferenceEncoder is closed")
            return self._aux.submit(function, *args).result()

    def close(self):
        self._check_process()
        with self._lock:
            if self._aux is None:
                return
            try:
                self._aux.submit(self._close_resources).result()
            finally:
                self._aux.shutdown(wait=True)
                self._aux = None

    def _close_resources(self):
        self.tokenizer = self.speaker = self.text_tokenizer = None
        table, self.table = self.table, None
        mapping = getattr(table, "_mmap", None)
        if mapping is not None:
            mapping.close()

    def encode(self, audio_path, text):
        return self._call(lambda: self._encode_audio(*read_reference(audio_path),text))

    def encode_audio(self, x, sr, text):
        return self._call(self._encode_audio,x,sr,text)

    def _encode_audio(self, x, sr, text):
        from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_types import string
        text=string(text,"prompt_text")
        if len(text)>200:raise ValueError("Reference transcript exceeds the qualified 200-character limit")
        validate_audio(x,sr)
        return self._condition(x,sr,text)

    def features(self,x,sr):
        return self._call(self._validated_features,x,sr)

    def _validated_features(self,x,sr):
        validate_audio(x,sr)
        return self._features(x,sr)

    def _project(self,a,b,reduction):
        import ctypes as C
        a=np.ascontiguousarray(a,np.float32)
        b=np.ascontiguousarray(b,np.float32)
        if a.ndim!=2 or b.ndim!=2 or a.shape[1]!=b.shape[0]:
            raise ValueError("Invalid reference projection dimensions")
        out=np.empty((a.shape[0],b.shape[1]),np.float32)
        pointer=C.POINTER(C.c_float)
        function=self._library.cv3_reference_project
        function.argtypes=[C.c_void_p,pointer,pointer,pointer]+[C.c_uint32]*4
        function.restype=C.c_int
        rc=function(None,*[v.ctypes.data_as(pointer) for v in (a,b,out)],a.shape[0],a.shape[1],b.shape[1],reduction)
        check_status(self._library, rc)
        return out

    def _rfft(self, frames, length):
        import ctypes as C
        data = np.ascontiguousarray(frames, np.float32)
        if data.ndim != 2:
            raise ValueError("Reference FFT requires a matrix of frames")
        output = np.empty((len(data), length//2+1), np.complex128)
        function = self._library.cv3_reference_rfft
        function.argtypes = [C.c_void_p,C.POINTER(C.c_float),C.c_uint64,C.POINTER(C.c_double),C.c_uint64]+[C.c_uint32]*3
        function.restype = C.c_int
        rc = function(None,data.ctypes.data_as(C.POINTER(C.c_float)),data.size,output.ctypes.data_as(C.POINTER(C.c_double)),output.size*2,len(data),data.shape[1],length)
        check_status(self._library, rc)
        # NumPy2 returns complex64 for float32 input;1.x promotes to complex128.
        return output.astype(np.complex64) if int(np.__version__.split(".")[0]) >= 2 else output

    def _mel(self, kind, pcm):
        """Buffer/type conversion only; model feature arithmetic is native."""
        import ctypes as C
        data = np.ascontiguousarray(pcm, np.float32)
        rows, columns = C.c_uint32(), C.c_uint32()
        shape = self._library.cv3_reference_feature_shape
        shape.argtypes = [C.c_uint32,C.c_uint64,C.POINTER(C.c_uint32),C.POINTER(C.c_uint32)]
        shape.restype = C.c_int
        check_status(self._library, shape(kind,data.size,C.byref(rows),C.byref(columns)))
        output = np.empty((rows.value,columns.value),np.float32)
        function = self._library.cv3_reference_features
        pointer = C.POINTER(C.c_float)
        function.argtypes = [C.c_void_p,C.c_uint32,pointer,C.c_uint64,C.c_char_p,C.c_uint32,pointer,C.c_uint64]
        function.restype = C.c_int
        precision = 32 if int(np.__version__.split(".")[0]) >= 2 else 64
        check_status(self._library, function(None,kind,data.ctypes.data_as(pointer),data.size,
                                    self._feature_assets.encode("utf-8"),precision,output.ctypes.data_as(pointer),output.size))
        return output

    def _condition(self, x, sr, text=None):
        x16 = _resample(x, int(sr), 16000, self._library)
        x24 = _resample(x, int(sr), 24000, self._library)
        start = time.monotonic()
        speech_mel = self._mel(0, x16)
        speaker_features = self._mel(1, x16)
        mel_input, length_input = self.tokenizer.get_inputs()
        (tokens,) = self.tokenizer.run(None, {
            mel_input.name: speech_mel[None],
            length_input.name: np.array([speech_mel.shape[1]], dtype=np.int32),
        })
        (embedding,) = self.speaker.run(None, {
            self.speaker.get_inputs()[0].name: speaker_features[None],
        })
        mid = time.monotonic()
        prompt = self._mel(2, x24)
        if (tokens.dtype not in (np.int32, np.int64) or not 0 < tokens.size <= 512
                or np.any(tokens < 0) or np.any(tokens >= 6561)):
            raise ValueError("Unexpected speech tokens from the reference model")
        if embedding.dtype != np.float32 or embedding.size != 192 or not np.isfinite(embedding).all():
            raise ValueError("Unexpected speaker embedding from the reference model")
        count = min(prompt.shape[1] // 2, tokens.size)
        tokens = tokens.reshape(-1)[:count].astype(np.int32, copy=True)
        output = dict(llm_prompt_token=tokens, flow_prompt_token=tokens,
                      prompt_feat=np.ascontiguousarray(prompt[:, :count * 2].T),
                      embedding=embedding.reshape(-1).copy())
        if text is None:
            output.update(x24=x24, ms={"tokenizer": round((mid - start) * 1000),
                                        "rest": round((time.monotonic() - mid) * 1000)})
        else:
            prefix = "You are a helpful assistant.<|endofprompt|>"
            ids = np.asarray(self.text_tokenizer.encode(prefix + text, add_special_tokens=False).ids,
                             dtype=np.int32)
            if np.any(ids < 0) or np.any(ids >= self.table.shape[0]):
                raise ValueError("Transcript token outside embedding table")
            output.update(prompt_text_ids=ids, prompt_text_rows=self.table[ids])
        return output

    def _features(self, x, sr):
        return self._condition(x, sr)
