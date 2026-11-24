# Web Demo

The business layer and the web demo on top of the SDK (`libcosyvoice3.so`): the board synthesizes, the browser plays
the audio while it arrives.

| File | Content |
|---|---|
| `app.py` | web server (Flask): page, voice list, cloning, streaming synthesis (HTTP API in its docstring) |
| `http_server.py` | closes streaming responses after HTTPS transport errors and normal completion |
| `tts.py` | business layer: text -> segments -> SDK LLM + Token2Wav per segment -> one audio stream; also a command line |
| `longtext.py` | segmentation (any length, any of the model's languages) and the joiner (edge trimming, pauses) |
| `ja_frontend.py` | Japanese as a katakana reading (MeCab), as the model's own Japanese example writes it |
| `clone.py` | Application voice creation from reference audio and transcript, including package storage |
| `../sdk/assets/voices/` | the declared built-in prepared voices: the built-in voices female-zh, female-en and male-en (voice packs + reference recordings; included only to demonstrate the model, all rights remain with the owners, see [../NOTICE](../NOTICE)) |
| `static/index.html` | the page |
| `static/clone.js` | the independent voice-creation form |
| `static/logo.png`, `static/pandora.svg` | the logos of the page header (APLUX, Pandora) |
| `https_cert.py` | the self-signed certificate of the HTTPS pages (`certs/`) |
| `run.sh`, `stop.sh` | start / stop the web server in the background |

## Start

Set up the board first ([main README](../README.md#1-install)) and download the model package of your chip, e.g. into
`models/` (the package root containing `models.json`), and the cloning models into `clone_models/` ([Model setup](../docs/MODEL_SETUP.md)).
Without the cloning models, built-in and already prepared user voices can still synthesize; new voice creation is unavailable.
The SDK selects the compatible target automatically. Download the folder for your chip in the [Targets table](../docs/MODEL_SETUP.md#targets).
The launcher activates this checkout's `.venv`, then runs `python`. It fails with setup instructions when the environment is missing.
The interface starts in English, including when the browser previously saved a Chinese preference; the language
button can switch the current page to Chinese.

```bash
source .venv/bin/activate
export CV3_MODELS="$PWD/models"    # package root containing models.json
bash demo/run.sh --port 8766    # background; logs to demo/web.log
bash demo/stop.sh
python demo/app.py --port 8766 # foreground (--host, --models)
```

Open `https://<device-ip>:8766/` (HTTPS by default, see below). The server serves one synthesis at a time (one NPU); the page
is meant for one user.

| Environment variable | Default | Meaning |
|---|---|---|
| `PORT` | 8766 | port of `demo/run.sh` |
| `CV3_HTTP` | 0 | Set to 1 for HTTP on loopback. Open the page at `localhost` to use the microphone. |
| `CV3_MODELS` | `<repo>/models` | the model package root containing models.json (also the default of the examples and `clone.py`) |
| `CV3_CLONE_MODELS` | `<repo>/clone_models` | the two cloning models (`speech_tokenizer_v3.onnx`, `campplus.onnx`) |
| `CV3_USER_VOICES` | `<repo>/voices_user` | saved user collection: one child per voice, containing voice.json and six flat NPY conditions |
| `CV3_LIB` | installed `_cosyvoice3_runtime/lib/libcosyvoice3.so` | the .so to load |

## HTTPS and the microphone

The page can clone a voice from a recording made with the microphone of the computer the browser runs on (the device hosting the server needs no microphone). Microphone access requires a secure context such as HTTPS or `localhost`. For trusted-LAN
file-upload diagnostics only, use `python demo/app.py --port 8766 --http`
after activating the environment. The background launcher uses HTTPS by default. For a local HTTP check, run
`CV3_HTTP=1 bash demo/run.sh --port 8766` and open `http://localhost:8766/`. This mode listens on loopback only.

The certificate: on its first start with HTTPS the server makes a self-signed certificate with openssl and keeps it in
`demo/certs/` (not in git; the private key never leaves the board):

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=cosyvoice3" \
        -keyout demo/certs/key.pem -out demo/certs/cert.pem
```

No authority has signed it, so each browser warns once ("Your connection is not private" / "Warning: Potential Security
Risk"): Chrome / Edge: **Advanced** → **Proceed to <device-ip> (unsafe)**; Firefox: **Advanced** → **Accept the Risk and
Continue**. The connection is encrypted all the same.

- Your own certificate (e.g. from your company's CA, or one made with `mkcert` that the computers already trust): put it
  as `demo/certs/cert.pem` and its key as `demo/certs/key.pem` before starting the server; no warning then.
- A new self-signed certificate: delete `demo/certs/` and restart the server.

## Command line

`tts.py` runs the same business layer as the page and writes a wav file:

```bash
source .venv/bin/activate
python demo/tts.py --voice female-zh --text "今天天气很好，我们一起去公园散步吧。"     # -> out/text.wav
python demo/tts.py --voice female-zh --file examples/text/long_zh.txt --out-dir out     # any length
python demo/tts.py --voice female-zh --instruct "请用四川话表达。" --text "今天天气巴适得很！"
```

Options: `--voice` (a voice id), `--text` or `--file` (`--chars N`: only the first N characters), `--instruct` (an
instruction, see below), `--seed`, `--ahead-s` (pacing, as the page), `--hop-max 200|100`, `--preroll` (for the
statistics), `--id` (the output name), `--out-dir`, `--models`. It also writes
`<id>_segments.jsonl` (one line per segment) and `<id>_info.json` (the run's statistics).

For independent CLI creation and the full Web create → save → load → speak
workflow, use the [voice cloning guide](../docs/VOICE_CLONING.md). It also covers
saved packages, load-only retries, restart recovery and legacy migration.

## Using the page

The page is in English (default) or Chinese: the **中文 / English** button in the header switches it (the choice
is remembered in the browser). Language names are always shown in English.

The page has four tabs, each adding one capability to the one before; the voice list on the left is shared by all of
them. The labels below are the English page's, with the Chinese page's in brackets.

| Tab | What it adds |
|---|---|
| **Voices & Synthesis** (克隆与合成) | Pick a voice and type text in any of the nine languages; the **Samples** (示例) buttons fill in a sample sentence per language. |
| **Vocal Tags** (语气标签) | Buttons that insert vocal tags into the text: **+Laughter** `[laughter]`, **+Breath** `[breath]`, **+Emphasis** `<strong>…</strong>` (select the words first). |
| **Emotion** (情绪) | One of Happy / Sad / Angry (开心 / 伤心 / 生气) or Fast / Slow (快 / 慢). Choosing one fills in a matching sample sentence. |
| **Dialect** (方言) | Sichuanese (四川话) or Cantonese (粤语), with a matching sample sentence. |

Emotion and dialect are separate tabs because the model follows one instruction at a time. Each tab keeps its own text
and choice.

### Voices

| Control | What it does |
|---|---|
| Voice list | **Built-in** (内置): the delivered female-zh, female-en and male-en prepared voices. **My clones** (我的克隆): voices cloned on this board. Click a row to select it. |
| ▶ | Plays the voice's reference recording. |
| 🗑 | Deletes a cloned voice (not possible while it is speaking). |
| ＋ Clone (＋ 克隆) | Clones a new voice, at most 20. **Record** (HTTPS or HTTP on localhost, with microphone permission): pick a language, read the sentence shown at a normal pace (a 3 s count-down, up to 7 s of recording; the browser's echo cancellation, noise suppression and gain control are off); the sentence is the transcript. **Upload a file**: a wav or mp3 file, one speaker, no background music, and its exact transcript (at most 200 characters). Both: silence at the start and the end is removed (the page shows the length before and after); the result must be 3–5 s, 4–5 s recommended (see [Real-time playback](#real-time-playback)); then a name, the gender and the confirmation that the speaker agrees. |

### Text and synthesis

| Control | What it does |
|---|---|
| Text box | Up to 10,000 characters in any of the nine languages; text in a language other than the voice's recording is spoken cross-lingually. Long text is split into segments and played as one stream. |
| ▶ Speak / Stop / Download (▶ 合成 / 停止 / 下载) | Synthesize (Ctrl+Enter), stop, download the last result as a wav file. |
| Waveform | The spectrum of the audio being played. |
| ⚙ Settings (⚙ 设置) | **Instruction** (自定义指令): any instruction of your own (overrides the tab's choice); **Seed**: the same text, voice and seed give the same audio; **Preroll** (预缓冲): how long the page waits after the first audio before it starts playing, 1.5 s by default (see [Real-time playback](#real-time-playback)); **Hop size** (分段上限): 200 (recommended) or 100 speech tokens per streaming step. |

How the text reaches the model: Chinese is normalized (numbers, dates and units spelled out), Japanese is turned into a
katakana reading, the other languages go as written (the model reads digits in the language of the text). Without an
instruction the voice's recording sets the delivery; a segment with vocal tags or in a language other than the
recording is spoken without it (the model's cross-lingual form), so the tags are not muted by a calm recording.

### Real-time playback

The page plays the audio while it is generated. Streaming generation comes in steps of growing size (about 1-2 s of
audio first, then 2 s, 4 s and 8 s), and every step runs the flow-matching model over the voice's reference recording
plus all the audio generated so far, so the first steps of a sentence can take a little longer than the audio before
them. These settings help keep playback smooth:

- **Reference recordings of 3-5 s.** A longer reference makes every step slower (above about 8 s generation is no
  longer faster than real time). The clone form accepts 3-5 s after trimming silence; the built-in voices are 4-4.5 s.
- **A preroll of 1.5 s.** Playback starts 1.5 s after the first audio arrives. This shifts the whole playback, so
  it gives the first synthesis steps more time before playback catches up.

Both are limits of the web pages only: the SDK, `demo/clone.py` (3-10 s) and the examples have none; an application
that plays its stream chooses its own buffering.

### Metrics

| Metric | Meaning |
|---|---|
| First sound (首次出声) | from pressing Speak to the first audio playing, including the preroll |
| Real-time factor (实时率) | generation time / audio length; below 1 is faster than real time |
| Audio length (音频时长) | length of the audio so far |
| Stalls (播放卡顿) | how often and how long playback had to wait for audio |
| Details (详情): First chunk, Generation time, Segments, Ahead of playback | first audio chunk received; total generation time; segments done / total; how much audio is generated ahead of playback |

## Cloning model setup and status

Before recording or uploading, both cloning pages request `GET /clone/status` (no ONNX sessions or NPU allocation).
The response reports `ready`, `directory`, `missing`, `install_command` and `guide_url`, with caching disabled.
The form stays disabled while checking, on a failed check, or when a required file is missing, empty or a Git LFS
pointer. The setup panel shows terminal commands and **Recheck**; installing files into the same directory does not
require a restart. `POST /clone` also checks availability and returns HTTP 503 with `error: unavailable` and `setup`
when files are missing. Unreadable models are reported as unavailable when ONNX Runtime loads them.

Use the [voice cloning guide](../docs/VOICE_CLONING.md) for fixed CPU resource
setup, creation/saving, dynamic loading and recovery. CV3_CLONE_MODELS selects the
CPU directory; it is independent of the synthesis weights and saved user voices.

### Recording quality checks

Record or upload a clear, single-speaker reference. The clone form rejects effectively silent recordings,
constant DC input and isolated clicks. Quiet but usable recordings show a warning rather than being discarded.
Play the recording, then check that you can clearly hear your own voice before cloning; playback failure keeps
this confirmation disabled. A new recording or upload clears the confirmation.

The server independently rejects invalid or effectively silent references with HTTP 400 and `error: silent`,
before loading the cloning models or saving a voice pack. The CLI applies the same input check. This is a
conservative signal-level check, not speech detection or speaker verification: background noise can still pass,
so listening to the reference remains necessary.

If the recording is silent, check the computer's selected microphone, mute state and input volume, then record
again. Existing voices created from silent references must be re-recorded; a generated voice cannot recover
speech that was never captured. Existing voice files are not automatically deleted.

### Model package selection

The demo and examples share the Python SDK's `resolve_models` helper. With no explicit
path, it uses a configured root `models/` package, then discovers a unique configured
immediate child only when the root is unconfigured. Modern packages use `models.json`;
explicitly supported legacy packages may use `manifest.json`. Multiple packages require `--models PATH` or `CV3_MODELS`; explicit
paths must name a package root and never fall back. Run checksum and hardware checks
separately. Use an absolute environment path when starting from another directory.

The delivery contains three built-in voices. Its policy also filters voices from older model packages.
An explicit unavailable voice ID is rejected rather than silently substituting a different speaker.

## Voice-management ownership

The independent tool saves a complete validated package first. The Web then
waits for the active synthesis to release and loads into the same TTS instance;
only successful registration is ready. A load failure retains the saved package
and offers load-only retry. See the [voice cloning guide](../docs/VOICE_CLONING.md#5-start-web-cloning-and-use-the-voice-immediately).
The stop script waits for process exit and never kills an unrelated recorded PID.

### Selecting an existing isolated environment

The default launcher uses this Demo's `.venv`. To use another installed
CPython 3.10/3.11/3.12 environment, set `CV3_VENV` to its absolute directory:
`CV3_VENV=/absolute/demo/.venv-3.12 bash demo/run.sh`.
Install the same root `requirements.txt` in that environment first. The launcher
requires its `pyvenv.cfg` and never falls back to a system interpreter.
Do not start a second service while this deployment is running.


Service lifecycle logs include model-owned buffer counts after loading and
explicit close. They describe process-owned allocations, not all driver/DSP
memory. Closing an HTTP response in a client requires closing the response body
as well as the connection object; the two can have separate socket ownership.

## Prepared-voice lifecycle

The synthesis model automatically loads the model SDK's declared built-ins.
User voices are independent flat directories under CV3_USER_VOICES. Creation
uses the independent CPU tool, validates temporary output, and atomically saves
it. The clone form then shows saved/waiting-to-load, waits for current synthesis
to release, and calls load_voice on the same model. Only a successful load is
ready and selected. No full-model restart/reload occurs.

Saved/load-failed packages are retained. The form's load-only retry reuses the
saved package; it requires no upload or extraction. GET /voices/saved reports
saved states and POST /voices/<id>/load retries loading. Restart scans saved
packages and explicitly reports invalid ones while preserving all bytes and
other valid voices. Deletion first unloads an dle user voice, then removes
business-owned files. SDK unload never deletes source files. For an old
voices.json/NPZ collection, run the [explicit migration](../tools/README.md)
to a new directory and select that directory; originals are retained.

The fixed Chinese and English preset texts match [the SDK examples](../examples/README.md).
Optional style tabs and application long-text/playback remain separate policies.
