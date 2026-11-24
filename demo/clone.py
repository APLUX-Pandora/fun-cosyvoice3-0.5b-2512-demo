#!/usr/bin/env python3
"""Independent CPU voice creation and atomic flat-package persistence.
Run tools/clone_voice.py with explicit consented recording/transcript and paths.
The tool owns ReferenceEncoder; synthesis owners only load the saved package.
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"
MIN_S, MAX_S = 3.0, 10.0
MIN_SR = 16000
MAX_TEXT = 200                           # characters of the transcript (the voice prompt must leave room for text)
MAX_USER_VOICES = 20                     # cloned voices kept in voices_user/ (the servers refuse more)
CLONE_MODELS = os.environ.get("CV3_CLONE_MODELS", os.path.join(ROOT, "clone_models"))
CLONE_FILENAMES = ("speech_tokenizer_v3.onnx", "campplus.onnx")
UPSTREAM_REVISION = "29e01c4e8d000f4bcd70751be16fa94bf3d85a18"


def model_status(clone_models=None):
    """Check optional voice creation resources without loading sessions."""
    import importlib.util
    import shlex
    cm = os.path.abspath(clone_models or CLONE_MODELS)
    missing = []
    for name in CLONE_FILENAMES:
        path = os.path.join(cm, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                missing.append(name)
                continue
            with open(path, "rb") as stream:
                if stream.read(80).startswith(b"version https://git-lfs.github.com/spec/"):
                    missing.append(name)
        except OSError:
            missing.append(name)
    python = "python"
    hf = "hf"
    missing_dependencies = [
        name for name in ("onnxruntime", "tokenizers") if importlib.util.find_spec(name) is None
    ]
    commands = ["source " + shlex.quote(os.path.join(ROOT,".venv/bin/activate")), python + " -m pip install -r " + shlex.quote(os.path.join(HERE, "requirements-clone.txt")),
                hf + " download FunAudioLLM/Fun-CosyVoice3-0.5B-2512 " + " ".join(CLONE_FILENAMES) +
                " --revision " + UPSTREAM_REVISION + " --local-dir " + shlex.quote(cm)]
    return {"ready": not missing and not missing_dependencies, "directory": cm,
            "missing": missing + missing_dependencies,
            "install_command": "\n".join(commands),
            "guide_url": "https://github.com/APLUX-Pandora/fun-cosyvoice3-0.5b-2512-demo/blob/main/docs/VOICE_CLONING.md#1-prepare-the-environment-and-model-resources"}



from reference_encoder import CloneError, ReferenceEncoder, resample, validate_audio

# ---------------------------------------------------------------------------------------------------- the cloner
class Cloner:
    """Independent CPU preparation owner; never loads or mutates a TTSModel."""
    def __init__(self, models=None, threads=4, clone_models=None):
        from pandora_fun_cosyvoice3_0_5b_2512 import resolve_models
        start=time.monotonic()
        status=model_status(clone_models)
        if not status["ready"]:raise FileNotFoundError("Missing cloning inputs: " + ", ".join(status["missing"]))
        models=resolve_models(models,default_root=os.path.join(ROOT,"models"))
        self.encoder=ReferenceEncoder(models,status["directory"],threads=threads)
        self.init_s=round(time.monotonic()-start,2)

    def close(self):
        if self.encoder is not None:
            self.encoder.close();self.encoder=None

    @staticmethod
    def load(path):
        import soundfile as sf
        x,sr=sf.read(path,dtype="float32",always_2d=True)
        return x.mean(axis=1).astype(np.float32),sr

    def clone(self,x,sr,text,voice_id,name,gender,voices_dir,category="mandarin",extra=None):
        from pathlib import Path
        import tempfile
        import soundfile as sf
        from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_voices import save_package
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",voice_id or ""):raise CloneError("id","Invalid voice ID")
        text=(text or "").strip()
        if not text or len(text)>MAX_TEXT:raise CloneError("text","A matching transcript within200characters is required")
        validate_audio(x,sr)
        if self.encoder is None:raise RuntimeError("Cloner is closed")
        start=time.monotonic();arrays=self.encoder.encode_audio(x,sr,text)
        meta={"id":voice_id,"name":name or voice_id,"gender":gender,"prompt_text":text,
              "prompt_text_norm":PROMPT_PREFIX+text,"prompt_tokens":int(arrays["llm_prompt_token"].size),
              "prompt_text_tokens":int(arrays["prompt_text_ids"].size),"prompt_s":round(len(x)/sr,2),
              "category":category,**(extra or {})}
        root=Path(voices_dir);root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".preview-",dir=root) as temporary:
            preview=Path(temporary)/"preview.wav"
            sf.write(preview,resample(x,sr,24000),24000,subtype="PCM_16")
            save_package(root/voice_id,arrays,meta,preview=preview)
        elapsed=time.monotonic()-start
        return {**meta,"state":"saved","clone_s":round(elapsed,2),"ms":{"total":round(elapsed*1000)}}


def read_request(form, audio):
    """the fields of a clone request (the web demo's form: text, name, gender, category, consent; audio = the bytes of
    a WAV file) -> (x, sr, text, name, gender, category), checked; raises CloneError (consent / name / text / format)"""
    import io
    import soundfile as sf
    text, name = str(form.get("text", "")).strip(), str(form.get("name", "")).strip()[:20]
    if form.get("consent") not in ("1", "true", "on"):
        raise CloneError("consent", "the speaker's consent must be confirmed")
    if not name:
        raise CloneError("name", "a name is required")
    if not text:
        raise CloneError("text", "the transcript of the recording is required")
    if len(text) > MAX_TEXT:
        raise CloneError("text_long", f"the transcript is longer than {MAX_TEXT} characters")
    if not audio:
        raise CloneError("format", "no audio")
    try:
        if sf.info(io.BytesIO(audio)).format != "WAV":
            raise CloneError("format", "WAV expected")
        x, sr = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
    except CloneError:
        raise
    except Exception as e:                                       # noqa: BLE001
        raise CloneError("format", f"cannot read the audio: {e}")
    gender = "male" if form.get("gender") == "male" else "female"
    category = form.get("category") if form.get("category") in ("mandarin", "role") else "mandarin"
    mono = x.mean(axis=1).astype(np.float32)
    validate_audio(mono, sr)
    return mono, sr, text, name, gender, category


def saved_voice_packages(voices_dir):
    from pathlib import Path
    from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_voices import validate_package

    root = Path(voices_dir)
    if not root.exists():
        return
    if (root / "voices.json").exists():
        raise ValueError("Run tools/migrate_voices.py on this legacy catalogue; originals are preserved")
    for package in sorted(root.iterdir()):
        if package.name.startswith(".") or not package.is_dir():
            continue
        try:
            meta, arrays, _ = validate_package(package)
        except Exception as exc:
            print(json.dumps({"invalid_saved_voice": str(package), "error": str(exc)}), file=sys.stderr, flush=True)
            continue
        yield package, meta, arrays


def list_voices(voices_dir):
    return [meta for _, meta, _ in saved_voice_packages(voices_dir)]


def find_saved_voice(voices_dir, voice_id):
    matches = [entry for entry in saved_voice_packages(voices_dir) if entry[1]["id"] == voice_id]
    if len(matches) > 1:
        raise ValueError(f"Multiple packages declare voice ID {voice_id}")
    return matches[0] if matches else None


def remove_voice(voices_dir, voice_id):
    import shutil

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", voice_id):
        raise ValueError("Invalid voice ID")
    saved = find_saved_voice(voices_dir, voice_id)
    if saved is not None:
        path, meta, _ = saved
        if meta.get("locked"):
            raise PermissionError("This voice is locked")
        shutil.rmtree(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--text", required=True, help="transcript of the reference recording")
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--gender", default="female", choices=["female", "male"])
    ap.add_argument("--category", default="mandarin", choices=["mandarin", "role"])
    ap.add_argument("--instruct", default=None, help="instruction applied when the voice is selected (e.g. a role)")
    ap.add_argument("--locked", action="store_true", help="the page cannot delete the voice")
    ap.add_argument("--voices-dir", default=os.environ.get("CV3_USER_VOICES", os.path.join(ROOT, "voices_user")))
    ap.add_argument("--models", default=None, help="model package (default $CV3_MODELS or <repo>/models)")
    ap.add_argument("--clone-models", default=None, help="the cloning models (default $CV3_CLONE_MODELS or "
                    "<repo>/clone_models)")
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    c = Cloner(a.models, a.threads, a.clone_models)
    try:
        x, sr = Cloner.load(a.wav)
        extra = {"instruct": a.instruct} if a.instruct else {}
        if a.locked:
            extra["locked"] = True
        r = c.clone(x, sr, a.text, a.id, a.name, a.gender, a.voices_dir, a.category, extra)
    except CloneError as e:
        sys.exit(f"clone: {e}")
    finally:
        c.close()
    print(json.dumps({"init_s": c.init_s, **r}, ensure_ascii=False))


if __name__ == "__main__":
    main()
