#!/usr/bin/env python3
"""Fun-CosyVoice3 web demo: type text, pick a voice (built-in or cloned on the board), hear it while it is being generated.

GET  /                 -> static/index.html (+ /clone.js: its clone form; /logo.png, /pandora.svg: the header logos)
GET  /voices           -> [{"id", "name", "gender", "prompt_text", "prompt_s", "user", "category", "instruct",
                            "locked"}]  (user: cloned on this board; category mandarin / role;
                            instruct: applied by the page when the voice is selected; locked: not deletable)
GET  /voice_wav/<id>   -> the voice's reference audio
GET  /clone/status     -> readiness, missing dependencies or assets, and setup instructions
POST /clone            multipart audio (WAV, 3-10 s, >= 16 kHz), text (the transcript), name, gender,
                       optional category (mandarin or role), and consent=1
                       -> {"state": "saved/waiting-to-load", "id", "load_url", "clone_s"}
                       Errors include invalid input, the saved-voice limit (409) and unavailable resources (503).
GET  /voices/saved     -> saved voices and their state: ready, saved/waiting-to-load, or saved/load-failed
POST /voices/<id>/load -> {"state": "ready", "voice", "clone_s"} after loading a saved voice
                       -> 404 if unknown, or 409 with saved state and retry URL if busy or loading fails
DELETE /voices/<id>    -> {"deleted": id} for a saved or loaded user voice
                       -> 403 if locked, 404 if unknown, or 409 if the loaded voice is in use or conflicts
POST /tts {"text" (<= MAX_CHARS, any of the model's languages), "voice", "instruct" (optional, <= MAX_INSTRUCT), "seed",
     "hop_max"} -> binary stream of frames: 1 byte type + uint32 LE
     length + payload; type 0: audio chunk int16 LE mono 24 kHz; type 1: JSON stats (end); type 2: error text;
     type 3: JSON progress ({"event": "start", "id", "segments"} / {"event": "segment", "index", ...})
GET  /wav/<id>         -> the whole utterance as a wav (written while streaming; the last KEEP_WAVS are kept)
Cloning runs on the CPU and saves the new voice first. A separate load request makes it available for synthesis.
Any length: segments (longtext.py), one audio stream; generation stays at most AHEAD_S of audio ahead of playback.
The playback preroll is a browser setting (the page starts playing that long after the first chunk).
One TTS instance (one NPU): requests are served one at a time. If the browser disconnects or presses stop, no new
segment is started and the running LLM query is aborted.
HTTPS is the default. Browsers allow recording on HTTPS or localhost. See the launcher instructions.
usage: python3 demo/app.py [--port 8766] [--host 0.0.0.0] [--models models]
"""
import argparse
import glob
import json
import os
import re
import signal
import struct
import threading
import time
import uuid
import wave

import numpy as np

import clone
from pandora_fun_cosyvoice3_0_5b_2512 import TTSStateError, protection_status
import https_cert
from tts import TTS, UnknownSavedVoice

MAX_CHARS = 10000
MAX_INSTRUCT = 200
AHEAD_S = 30.0
KEEP_WAVS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def frame(t, payload):
    return struct.pack("<BI", t, len(payload)) + payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--http", action="store_true", help="explicit HTTP mode for trusted-LAN/proxy testing; microphone needs a secure context")
    ap.add_argument("--models", default=None, help="model package (default $CV3_MODELS or <repo>/models)")
    a = ap.parse_args()
    stopped = threading.Event()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous:
        # Do not raise across ctypes create: first acquire the returned native handle.
        signal.signal(sig, lambda _signum, _frame: stopped.set())
    tts = None
    try:
        # Vendor load syscalls can fail on EINTR and leave vendor shutdown blocked.
        # New runtime threads inherit this mask; deliver pending signals after ownership is established.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(previous))
        try:
            print(json.dumps({"tts_loading": True}), flush=True)
            tts = TTS(a.models)
            print(json.dumps({"tts_loaded": True, "model_buffers": protection_status()}), flush=True)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        if not stopped.is_set():
            serve(a, tts, stopped)
    except Exception as exc:
        if tts is not None or not stopped.is_set():
            raise
        # A signal can interrupt a vendor load syscall. Constructor rollback has
        # already released acquired handles; treat this as requested startup cancellation.
        print(json.dumps({"startup_cancelled": True, "detail": str(exc)}), flush=True)
    finally:
        try:
            if tts is not None:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(previous))
                try:
                    tts.close()
                    print(json.dumps({"tts_closed": True, "model_buffers": protection_status()}), flush=True)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def serve(a, tts, stopped):
    from flask import Flask, Response, jsonify, request, send_from_directory
    print(json.dumps({"tts_init_s": tts.init_s}), flush=True)
    lock = threading.Lock()
    clone_lock = threading.Lock()
    cloner = {}
    web = Flask(__name__)
    web.config["MAX_CONTENT_LENGTH"] = 16 << 20

    @web.before_request
    def stopping():
        if stopped.is_set():
            return jsonify({"error": "stopping"}), 503

    def err(code, msg, status=400):
        return jsonify({"error": code, "message": msg}), status

    @web.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "static"), "index.html")

    @web.get("/clone.js")
    def clone_js():
        return send_from_directory(os.path.join(HERE, "static"), "clone.js")

    @web.get("/<any('logo.png', 'pandora.svg', 'favicon.ico'):name>")
    def logo(name):
        return send_from_directory(os.path.join(HERE, "static"), "logo.png" if name == "favicon.ico" else name)

    @web.get("/voices")
    def voices():
        keys = ("id", "name", "gender", "prompt_text", "prompt_s", "user", "instruct", "locked")
        return jsonify([{**{k: v["meta"].get(k) for k in keys}, "category": v["meta"].get("category", "mandarin")}
                        for v in list(tts.voices.values())])

    @web.get("/voice_wav/<vid>")
    def voice_wav(vid):
        v = tts.voices.get(vid)
        if v is None:
            return "bad id", 400
        return send_from_directory(v["dir"], v.get("preview") or "preview.wav")

    @web.get("/clone/status")
    def clone_status():
        response = jsonify(clone.model_status())
        response.headers["Cache-Control"] = "no-store"
        return response

    @web.post("/clone")
    def clone_voice():
        setup = clone.model_status()
        if not setup["ready"]:
            return jsonify({"error": "unavailable", "message": "Install the cloning models first.",
                            "setup": setup}), 503
        f = request.files.get("audio")
        try:
            x, sr, text, name, gender, category = clone.read_request(request.form, f.read() if f else b"")
        except clone.CloneError as e:
            return err(e.code, str(e))
        with clone_lock:
            if len(clone.list_voices(tts.user_dir)) >= clone.MAX_USER_VOICES:
                return err("limit", f"at most {clone.MAX_USER_VOICES} cloned voices: delete one first", 409)
            vid = "u" + uuid.uuid4().hex[:8]
            creator=None
            try:
                creator=clone.Cloner(tts.model_dir)
                cloner['c']=creator
                r=creator.clone(x,sr,text,vid,name,gender,tts.user_dir,category)
            except clone.CloneError as exc:
                return err(exc.code,str(exc))
            except Exception as exc:
                return err('internal',str(exc),500)
            finally:
                if creator is not None:creator.close()
                cloner.pop('c',None)
        print(json.dumps({'voice_saved':vid,'state':'saved/waiting-to-load'}),flush=True)
        return jsonify({'state':'saved/waiting-to-load','id':vid,'load_url':'/voices/'+vid+'/load','clone_s':r['clone_s']})

    def clear_orphaned_voice_error(vid):
        if os.path.isdir(os.path.join(tts.user_dir, vid)):
            return False
        tts.saved_voice_errors.pop(vid, None)
        return True

    @web.get('/voices/saved')
    def saved_voices():
        result = []
        with clone_lock:
            try:
                for package, meta, _ in clone.saved_voice_packages(tts.user_dir):
                    vid = meta["id"]
                    current = tts.voices.get(vid)
                    ready = current and current["meta"]["user"] and current["dir"] == str(package)
                    message = tts.saved_voice_errors.get(vid)
                    state = "ready" if ready else ("saved/load-failed" if message else "saved/waiting-to-load")
                    result.append({"id": vid, "name": meta["name"], "state": state, "message": message,
                                   "stored": True, "locked": bool(meta.get("locked"))})
            except ValueError as exc:
                result = [{"id": "legacy", "name": "Legacy catalogue", "state": "saved/load-failed",
                           "message": str(exc)}]
            known = {item["id"] for item in result}
            for vid, message in list(tts.saved_voice_errors.items()):
                if vid not in known and not clear_orphaned_voice_error(vid):
                    result.append({"id": vid, "name": vid, "state": "saved/load-failed", "message": message})
        return jsonify(result)

    @web.post('/voices/<vid>/load')
    def load_saved_voice(vid):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',vid):return err('id','Invalid voice ID')
        with clone_lock:
            try:loaded_id=tts.add_user_voice(vid,wait=True)
            except UnknownSavedVoice as exc:
                clear_orphaned_voice_error(vid)
                return err('unknown', str(exc), 404)
            except TTSStateError as exc:
                return jsonify({'error':'busy','state':'saved/waiting-to-load','id':vid,'message':str(exc),'retry_url':'/voices/'+vid+'/load'}),409
            except Exception as exc:
                tts.saved_voice_errors[vid]=str(exc)
                return jsonify({'error':'saved_load_failed','state':'saved/load-failed','id':vid,'message':str(exc),'retry_url':'/voices/'+vid+'/load'}),409
            meta=tts.voices[loaded_id]['meta']
            return jsonify({'state':'ready','voice':meta,'clone_s':0})

    @web.delete("/voices/<vid>")
    def delete_voice(vid):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", vid):
            return err("id", "Invalid voice ID")
        with clone_lock:
            try:
                saved = clone.find_saved_voice(tts.user_dir, vid)
            except ValueError as exc:
                return err("conflict", str(exc), 409)
            v = tts.voices.get(vid)
            loaded_user = v is not None and v["meta"]["user"]
            if saved is None and not loaded_user:
                clear_orphaned_voice_error(vid)
                if v is not None:
                    return err("locked", "This voice is locked", 403)
                return err("unknown", "No saved voice has this ID", 404)
            if (loaded_user and v["meta"]["locked"]) or (saved is not None and saved[1].get("locked")):
                return err("locked", "This voice is locked", 403)
            if loaded_user and saved is not None and v["dir"] != str(saved[0]):
                return err("conflict", "Saved package differs from the loaded voice", 409)
            try:
                if loaded_user and not tts.remove_user_voice(vid):
                    return err("busy", "The voice is in use by a running request", 409)
                if saved is not None:
                    clone.remove_voice(tts.user_dir, vid)
            except PermissionError:
                return err("locked", "This voice is locked or cannot be removed", 403)
            except (ValueError, OSError) as exc:
                return err("delete_failed", str(exc), 409)
            tts.saved_voice_errors.pop(vid, None)
        print(json.dumps({"deleted": vid}), flush=True)
        return jsonify({"deleted": vid})

    @web.get("/wav/<rid>")
    def wav(rid):
        if not rid.isalnum():
            return "bad id", 400
        return send_from_directory(OUT, rid + ".wav", as_attachment=True, download_name="cosyvoice3.wav")

    @web.post("/tts")
    def synth():
        req = request.get_json(force=True, silent=True) or {}
        text = str(req.get("text", "")).strip()[:MAX_CHARS]
        if not tts.voices:
            return err("no_voice", "No voice available", 503)
        voice = req.get("voice")
        if voice is not None and voice not in tts.voices:
            return err("unknown_voice", "The selected voice is unavailable; choose another voice", 400)
        if voice is None:
            voice = next(iter(tts.voices))
        instruct = str(req.get("instruct") or "").strip()[:MAX_INSTRUCT] or None
        try:
            seed = int(req.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0
        hop_max = 100 if str(req.get("hop_max")) == "100" else 200

        def gen():
            if not text:
                yield frame(2, "empty text".encode())
                return
            with lock:
                if stopped.is_set():
                    return
                t0, rid, stop = time.time(), uuid.uuid4().hex[:12], threading.Event()
                os.makedirs(OUT, exist_ok=True)
                wavs = sorted(glob.glob(os.path.join(OUT, "*.wav")), key=os.path.getmtime)
                for old in wavs[:-(KEEP_WAVS - 1) or None]:
                    os.remove(old)
                it = tts.speak_long(text, voice, seed, ahead_s=AHEAD_S, stop=stop, hop_max=hop_max, preroll=0.0,
                                    instruct=instruct)
                f = wave.open(os.path.join(OUT, rid + ".wav"), "wb")
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(24000)
                try:
                    for w, st in it:
                        if w is not None:
                            pcm = np.clip(np.round(w * 32767.0), -32768, 32767).astype("<i2")
                            f.writeframes(pcm.tobytes())
                            yield frame(0, pcm.tobytes())
                        elif st["event"] == "done":
                            st.update({"id": rid, "chars": len(text), "voice": voice, "instruct": instruct,
                                       "seed": seed, "hop_max": hop_max, "server_s": round(time.time() - t0, 3)})
                            print(json.dumps(st, ensure_ascii=False), flush=True)
                            yield frame(1, json.dumps(st, ensure_ascii=False).encode())
                        else:
                            if st["event"] == "start":
                                st["id"] = rid
                            yield frame(3, json.dumps(st, ensure_ascii=False).encode())
                except GeneratorExit:                    # client went away / stop: no new segment, abort the query
                    stop.set()
                    tts.abort()
                    for _ in it:
                        pass
                    print(json.dumps({"client_disconnected": text[:20], "id": rid}, ensure_ascii=False), flush=True)
                    raise
                except Exception as e:                   # noqa: BLE001
                    print(json.dumps({"error": repr(e)}), flush=True)
                    yield frame(2, str(e).encode())
                finally:
                    try:
                        it.close()
                    finally:
                        f.close()

        return Response(gen(), mimetype="application/octet-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    from werkzeug.serving import make_server
    from http_server import ClosingApplication, RequestHandler

    web.wsgi_app = ClosingApplication(web.wsgi_app)

    server = make_server(a.host, a.port, web, threaded=True, request_handler=RequestHandler,
                         ssl_context=None if a.http else https_cert.self_signed())
    # Keep request threads owned until their generators and CPU cloning calls finish.
    server.daemon_threads = False
    server.block_on_close = True

    def shutdown():
        stopped.wait()
        tts.stop()
        server.shutdown()

    coordinator = threading.Thread(target=shutdown, name="tts-shutdown")
    coordinator.start()
    try:
        print(json.dumps({"http" if a.http else "https": a.port}), flush=True)
        server.serve_forever()
    finally:
        stopped.set()
        coordinator.join()
        try:
            server.server_close()
        finally:
            if "c" in cloner:
                cloner.pop("c").close()


if __name__ == "__main__":
    main()
