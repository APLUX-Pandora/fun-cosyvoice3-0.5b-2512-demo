#!/usr/bin/env python3
"""Business layer on the SDK (libcosyvoice3.so): any text length, built-in voices, one audio stream.

  text -> SDK text preparation + segmentation (one LLM query and one token2wav stream per segment)
       -> per segment: SDK LLM (speech tokens) -> SDK Token2Wav (24 kHz chunks, streaming)
       -> Joiner (silence trim + pauses at the joints) -> one stream
The LLM runs one segment ahead in a worker thread (the next segment's query starts as soon as the current one ends,
overlapping the vocoding of the current segment; the NPU executes both concurrently) and feeds its tokens to the main
thread through a queue. Policies: ahead_s (no new segment while more than ahead_s of audio is ahead of playback),
stop (no new segment, the running query is aborted). A segment that hits its token cap is flagged "max_tokens".
An optional instruction (dialect, emotion, speed, volume, ...) applies to every segment. Without one, a segment in the
language of the voice's reference recording is cloned zero-shot (the LLM continues the reference text and speech), a
segment in another language (by script: zh / ja / ko / Cyrillic / Latin) or with vocal tags ([laughter], [breath],
<strong>...</strong>, ...) cross-lingually (the model's cross-lingual mode, the form of its fine-grained
control example: the LLM does not see the reference, so its calm delivery does not mute the tags; the voice still sets
the timbre).

usage: python3 demo/tts.py --text "..." | --file long.txt [--chars N] [--id name] [--voice female-zh]
       [--instruct "请用四川话表达。"] [--seed 0] [--ahead-s 30] [--hop-max 200] [--preroll 0.4] [--models models]
       [--out-dir out]
"""
import argparse
import json
import os
import queue
import re
import sys
import threading
from pathlib import Path
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
SR = 24000
# the model's cross-lingual mode: the LLM prompt is the bare instruction template (no reference text / speech tokens),
# for text in a language other than the voice's reference; pass it as the instruction
CROSS_LINGUAL = "You are a helpful assistant.<|endofprompt|>"
# the fine-grained vocal tags of the model's tokenizer (not the pronunciation tags such as [j][ǐ])
VOCAL_TAG = re.compile(r"\[(?:breath|quick_breath|laughter|sigh|cough|clucking|hissing|lipsmack|mn|noise|"
                       r"vocalized-noise|accent)\]|</?(?:strong|laughter)>")
_SCRIPTS = (("ja", re.compile(r"[\u3040-\u30ff]")), ("ko", re.compile(r"[\uac00-\ud7a3]")),
            ("zh", re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")), ("cyrillic", re.compile(r"[\u0400-\u04ff]+")),
            ("latin", re.compile(r"[A-Za-z\u00c0-\u024f]+")))

from pandora_fun_cosyvoice3_0_5b_2512 import END_LIMIT, TTSModel, resolve_models  # noqa: E402
from longtext import MARGIN, MARGIN_INSTRUCT, Budget, Joiner, split_text  # noqa: E402


def text_lang(text):
    """coarse language of a text by script: ja (any kana), else the majority of ko / zh characters and Cyrillic / Latin
    words (so a Chinese sentence with a few English words stays zh), or None (no letters)"""
    counts = {k: len(r.findall(text)) for k, r in _SCRIPTS}
    if counts["ja"]:
        return "ja"
    best = max(counts, key=counts.get)
    return best if counts[best] else None


class Job:
    def __init__(self, k, seg, seed):
        self.k, self.seg, self.seed = k, seg, seed
        self.q = queue.Queue()                                   # tokens, then None
        self.done, self.tokens, self.cancelled, self.flag, self.stats = threading.Event(), [], False, "", {}


class LLMWorker(threading.Thread):
    """Runs the segments' LLM queries one after the other, each as soon as the previous one ends."""

    def __init__(self, tts, voice, instruct, budget, segs, seed, ahead_s, stop, state):
        super().__init__(daemon=True)
        self.tts, self.voice, self.ahead_s, self.stop, self.state = tts, voice, ahead_s, stop, state
        self.instruct, self.budget = instruct, budget
        self.jobs = [Job(k, s, seed + k) for k, s in enumerate(segs)]
        self.cond = threading.Condition()
        self.finished, self.error = False, None

    def ahead(self):
        st = self.state
        return st["audio"] - (time.time() - st["t0"] - st["first"]) if st["first"] is not None else 0.0

    def run(self):
        llm, i = self.tts.llm, 0
        try:
            while i < len(self.jobs):
                job = self.jobs[i]
                while self.ahead_s and not self.stop.is_set() and self.ahead() > self.ahead_s:
                    time.sleep(0.05)
                if self.stop.is_set():
                    for j in self.jobs[i:]:
                        j.cancelled = True
                        j.q.put(None)
                        j.done.set()
                    break
                seg = job.seg
                t = time.time()
                with self.tts.vlock:
                    llm.start(self.voice, seg["text"], job.seed, self.budget.max_tokens(len(seg["ids"])),
                              self.instruct or (CROSS_LINGUAL if seg["mode"] == "cross_lingual" else None))
                if self.stop.is_set():                         # stop arrived between the check and start: abort now
                    llm.abort()
                while (tok := llm.next()) is not None:
                    job.tokens.append(tok)
                    job.q.put(tok)
                reason = llm.end_reason()
                s = llm.stats()
                t0 = self.state["t0"]
                job.stats = {"t_start": round(t - t0, 3), "t_end": round(time.time() - t0, 3), "end": reason,
                             "max_tokens": s["max_tokens"], "ms_npu": round(s["ms_npu"]),
                             "ms_host": round(s["ms_host"])}
                job.flag = "max_tokens" if reason == END_LIMIT else ""
                job.q.put(None)
                job.done.set()
                with self.cond:
                    self.cond.notify_all()
                i += 1
        except Exception as e:                       # noqa: BLE001 - handed to speak_long, which raises it
            self.error = e
            for j in self.jobs[i:]:
                j.cancelled = True
                j.q.put(None)
                j.done.set()
        finally:
            self.finished = True
            with self.cond:
                self.cond.notify_all()


class UnknownSavedVoice(ValueError):
    pass


class TTS:
    def __init__(self, model_dir=None, user_dir=None, demo_dir=None):
        """model_dir: the model package (and its voices, if it has any); demo_dir: the voices that come with the demo
        (the built-in voices and role voices, demo/voices/, not deletable); user_dir: voices cloned on the board
        (voices.json + voices/)"""
        model_dir = resolve_models(model_dir, default_root=os.path.join(ROOT, "models"))
        self.model_dir = model_dir
        self.user_dir = user_dir or os.environ.get("CV3_USER_VOICES", os.path.join(ROOT, "voices_user"))
        self.demo_dir = demo_dir or os.path.join(HERE, "voices")
        t0 = time.time()
        self.model = None
        self.fe = None
        self.llm = self.t2w = None
        self._lifecycle = threading.Condition()
        self._close_lock = threading.Lock()
        self._closing = False
        self._stops = set()
        try:
            self._initialize(model_dir)
        except BaseException:
            self.close()
            raise
        self.init_s = round(time.time() - t0, 2)

    def _initialize(self, model_dir):
        from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_voices import builtin_collection, collection, validate_package
        self.model = TTSModel.from_pretrained(model_dir)
        self.llm,self.t2w=self.model.llm,self.model.t2w
        self.fe = self.model._frontend
        self.vlock=threading.Lock()
        self.active={};self.voices={};self.saved_voice_errors={}
        for package in collection(builtin_collection()):
            meta, arrays, _ = validate_package(package)
            self._register(package, meta, arrays, False)
        root=Path(self.user_dir)
        root.mkdir(parents=True,exist_ok=True)
        if (root/'voices.json').exists():
            self.saved_voice_errors['legacy']='Run tools/migrate_voices.py explicitly; legacy originals retained'
        for package in sorted(root.iterdir()):
            if package.name.startswith('.') or not package.is_dir():continue
            vid = package.name
            try:
                meta, arrays, _ = validate_package(package)
                vid = meta["id"]
                self._load_user_package(package, meta, arrays)
            except Exception as exc:
                self.saved_voice_errors[vid] = str(exc)
                print(json.dumps({"saved_voice_load_failed": vid, "error": str(exc)}), file=sys.stderr, flush=True)

    def _register(self, package, meta, arrays, user):
        self.voices[meta['id']]={'meta':{**meta,'user':user,'state':'ready','locked':not user or bool(meta.get('locked'))},
             'P':int(arrays['llm_prompt_token'].size),'lang':({'en':'latin','de':'latin','fr':'latin','es':'latin','it':'latin','ru':'cyrillic'}.get(meta.get('reference_language'),meta.get('reference_language')) or text_lang(meta.get('prompt_text',''))),
             'dir':str(package),'preview':meta.get('preview')}

    def _load_user_package(self, package, meta, arrays):
        vid = meta["id"]
        current = self.voices.get(vid)
        if current and (not current["meta"]["user"] or Path(current["dir"]) != package):
            raise ValueError(f"Voice ID conflict: {vid}")
        loaded_id = self.model.load_voice(package)
        if loaded_id != vid:
            if loaded_id not in self.voices:
                self.model.unload_voice(loaded_id)
            raise ValueError("Saved voice ID changed during loading")
        self._register(package, meta, arrays, True)
        self.saved_voice_errors.pop(vid, None)
        return vid

    def add_user_voice(self, vid, wait=False):
        from clone import find_saved_voice
        from pandora_fun_cosyvoice3_0_5b_2512 import TTSStateError

        saved = find_saved_voice(self.user_dir, vid)
        if saved is None:
            raise UnknownSavedVoice(f"Unknown saved voice: {vid}")
        # The business condition excludes new synthesis while waiting/loading.
        with self._lifecycle:
            deadline=time.monotonic()+30
            while self._stops:
                if not wait or self._closing or time.monotonic()>=deadline:
                    raise TTSStateError('Saved voice is waiting for the current request to release')
                self._lifecycle.wait(.1)
            if self._closing:raise TTSStateError('TTS is closing')
            with self.vlock:
                return self._load_user_package(*saved)

    def remove_user_voice(self,vid):
        with self._lifecycle:
            if self._stops:return False
            with self.vlock:
                if vid not in self.voices or not self.voices[vid]['meta']['user']:raise ValueError('Unknown user voice')
                if self.voices[vid]['meta']['locked']:raise PermissionError('This voice is locked')
                self.model.unload_voice(vid)
                del self.voices[vid]
        return True

    def budget(self, voice, instruct=None):
        v = self.voices[voice]
        margin = MARGIN_INSTRUCT if instruct and instruct != CROSS_LINGUAL else MARGIN
        return Budget(v["meta"], v["P"], self.llm.prompt_rows(voice, instruct), margin)

    def split(self, text, voice="female-zh", instruct=None):
        return split_text(text, self.fe, self.budget(voice, instruct))

    def speak_long(self, text, voice="female-zh", seed=0, ahead_s=30.0, stop=None, hop_max=200, preroll=0.4,
                   instruct=None):
        """Generator of (float32 chunk, None); (None, {"event": "start" | "segment" | "done", ...}).
        instruct: None / "" = zero-shot cloning of the voice, else an instruction for every segment."""
        stop = stop or threading.Event()
        with self._lifecycle:
            if self._closing:
                raise RuntimeError("TTS is closing")
            if self._stops:
                raise RuntimeError("TTS already has an active stream")
            self._stops.add(stop)
        registered = False
        try:
            with self.vlock:
                if voice not in self.voices:
                    raise ValueError(f"unknown voice {voice}")
                self.active[voice] = self.active.get(voice, 0) + 1
                registered = True
            with self.model.stage_session():
                yield from self._speak_long(text, voice, seed, ahead_s, stop, hop_max, preroll, instruct)
        finally:
            if registered:
                with self.vlock:
                    self.active[voice] -= 1
            with self._lifecycle:
                self._stops.discard(stop)
                self._lifecycle.notify_all()

    def _speak_long(self, text, voice, seed, ahead_s, stop, hop_max, preroll, instruct):
        instruct = (instruct or "").strip() or None
        stop = stop or threading.Event()
        state = {"t0": time.time(), "first": None, "audio": 0.0}
        with self.vlock:
            budget = self.budget(voice, instruct)   # without an instruction: the zero-shot budget (the larger prompt)
            vlang = self.voices[voice]["lang"]
        segs = split_text(text, self.fe, budget)
        for s in segs:
            cross = text_lang(s["text"]) not in (None, vlang) or VOCAL_TAG.search(s["text"])
            s["mode"] = "instruct" if instruct else ("cross_lingual" if cross else "zero_shot")
        ready, seg_stats = [], []
        yield None, {"event": "start", "segments": len(segs), "units": sum(s["units"] for s in segs),
                     "split_s": round(time.time() - state["t0"], 3)}
        if not segs:
            yield None, {"event": "done", "segments": 0, "audio_s": 0}
            return
        worker = LLMWorker(self, voice, instruct, budget, segs, seed, ahead_s, stop, state)
        worker.start()
        try:
            joiner = Joiner()

            def emit(ws):
                for w in ws:
                    if len(w):
                        now = time.time() - state["t0"]
                        if state["first"] is None:
                            state["first"] = now
                        ready.append((now, len(w) / SR))
                        state["audio"] += len(w) / SR
                        yield w, None

            i = 0
            while True:
                with worker.cond:
                    while i >= len(worker.jobs) and not worker.finished:
                        worker.cond.wait(0.1)
                if i >= len(worker.jobs):
                    break
                job = worker.jobs[i]
                if job.cancelled:
                    break
                a0, ts, chunks = state["audio"], time.time(), 0
                joiner.begin(trim_lead=i > 0)
                with self.vlock:
                    self.t2w.start(voice, hop_max)
                while True:
                    tok = job.q.get()
                    batch = [] if tok is None else [tok]
                    while tok is not None and not job.q.empty():
                        tok = job.q.get()
                        if tok is not None:
                            batch.append(tok)
                    if batch:
                        accepted = self.t2w.push(batch)
                        if accepted != len(batch):
                            raise RuntimeError('Waveform capacity rejected accepted speech tokens')
                    if tok is None:
                        self.t2w.finish()
                    for w in self.t2w.chunks():
                        chunks += 1
                        yield from emit(joiner.push(w))
                    if tok is None:
                        break
                job.done.wait()
                if job.cancelled:
                    break
                yield from emit(joiner.end(job.seg["pause"]))
                t2s = self.t2w.stats()
                st = {"event": "segment", "index": job.k, "segments": len(segs), "text": job.seg["text"],
                      "mode": job.seg["mode"], "units": job.seg["units"], "est": job.seg["est"],
                      "tokens": len(job.tokens), "flag": job.flag, "llm": job.stats, "chunks": chunks,
                      "N_max": t2s["last_n"],
                      "t2w_ms_npu": round(t2s["ms_npu"]), "t2w_ms_host": round(t2s["ms_host"]),
                      "audio_start_s": round(a0, 3), "audio_end_s": round(state["audio"], 3),
                      "t2w_s": round(time.time() - ts, 2)}
                seg_stats.append(st)
                yield None, st
                i += 1
            stopped = stop.is_set()
        finally:                                    # also on an error or when the caller closes the generator
            stop.set()                              # ends the worker's pacing wait and its remaining segments
            if worker.is_alive():
                self.llm.abort()
            worker.join()
        if worker.error is not None:
            raise worker.error
        if not ready:
            yield None, {"event": "done", "segments": len(segs), "stopped": stopped, "audio_s": 0}
            return
        play, stall, n_stall, slack = None, 0.0, 0, []
        for r, d in ready:                                       # playback from first chunk + preroll
            if play is None:
                play = r + preroll + d
                continue
            slack.append(play - r)
            if r > play + 0.02:
                stall += r - play
                n_stall += 1
            play = max(play, r) + d
        audio = sum(d for _, d in ready)
        yield None, {"event": "done", "segments": len(segs), "segments_done": len(seg_stats), "stopped": stopped,
                     "units": sum(s["units"] for s in segs), "first_chunk_s": round(ready[0][0], 3),
                     "first_sound_s": round(ready[0][0] + preroll, 3), "preroll_s": preroll, "audio_s": round(audio, 2),
                     "stalls": n_stall, "stall_s": round(stall, 3),
                     "min_slack_s": round(min(slack), 3) if slack else None,
                     "total_s": round(ready[-1][0], 3), "rtf": round(ready[-1][0] / audio, 3),
                     "flags": [(s["index"], s["flag"]) for s in seg_stats if s["flag"]],
                     "cross_lingual_segments": sum(s["mode"] == "cross_lingual" for s in seg_stats)}

    def abort(self):
        """stop the running LLM query after its current step (with speak_long's stop event set)"""
        self.llm.abort()

    def stop(self):
        """Reject new streams and notify existing streams without destroying their engines."""
        with self._lifecycle:
            self._closing = True
            for stop in self._stops:
                stop.set()
            if self.llm is not None:
                self.llm.abort()

    def close(self):
        """Call after consuming/closing generators; wait for all in-flight native work."""
        with self._close_lock:
            self.stop()
            with self._lifecycle:
                self._lifecycle.wait_for(lambda: not self._stops)
                self.fe = None
                if self.model is not None:
                    self.model.close()
                    self.model = None
                    self.llm = self.t2w = None
                else:
                    try:
                        if self.t2w is not None:
                            self.t2w.close()
                            self.t2w = None
                    finally:
                        if self.llm is not None:
                            self.llm.close()
                            self.llm = None


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text")
    src.add_argument("--file")
    ap.add_argument("--chars", type=int, default=0, help="--file: only the first N characters")
    ap.add_argument("--id", default=None)
    ap.add_argument("--voice", default="female-zh")
    ap.add_argument("--instruct", default=None, help='e.g. "请用四川话表达。" (default: zero-shot cloning of the voice)')
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ahead-s", type=float, default=30.0)
    ap.add_argument("--hop-max", type=int, default=200)
    ap.add_argument("--preroll", type=float, default=0.4)
    ap.add_argument("--models", default=None)
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args()
    if a.text is None:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = a.text
    if a.chars:
        text = text[:a.chars]
    uid = a.id or ("text" if a.text is not None else os.path.splitext(os.path.basename(a.file))[0])
    os.makedirs(a.out_dir, exist_ok=True)
    tts = TTS(a.models)
    try:
        print(json.dumps({"init_s": tts.init_s, "voices": list(tts.voices)}), flush=True)
        with wave.open(os.path.join(a.out_dir, f"{uid}.wav"), "wb") as wf, \
                open(os.path.join(a.out_dir, f"{uid}_segments.jsonl"), "w", encoding="utf-8") as fs:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            for w, ev in tts.speak_long(text, a.voice, a.seed, a.ahead_s, hop_max=a.hop_max, preroll=a.preroll,
                                        instruct=a.instruct):
                if w is not None:
                    wf.writeframes(np.clip(np.round(w * 32767.0), -32768, 32767).astype("<i2").tobytes())
                    continue
                if ev["event"] == "segment":
                    fs.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    fs.flush()
                    print(f"[seg {ev['index']:3d}] units {ev['units']:3d} tok {ev['tokens']:4d}/"
                          f"{ev['est']:.0f} N {ev['N_max']:4d} audio {ev['audio_start_s']:7.1f}-{ev['audio_end_s']:7.1f}s "
                          f"llm {ev['llm']['t_start']:7.1f}-{ev['llm']['t_end']:7.1f}s {ev['flag']}", flush=True)
                else:
                    ev.update({"id": uid, "voice": a.voice, "instruct": a.instruct, "seed": a.seed, "ahead_s": a.ahead_s,
                               "chars": len(text)})
                    print(json.dumps(ev, ensure_ascii=False), flush=True)
                    if ev["event"] == "done":
                        with open(os.path.join(a.out_dir, f"{uid}_info.json"), "w", encoding="utf-8") as f:
                            json.dump(ev, f, ensure_ascii=False, indent=1)
    finally:
        tts.close()


if __name__ == "__main__":
    main()
