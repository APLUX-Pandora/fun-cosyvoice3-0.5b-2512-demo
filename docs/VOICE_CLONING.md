# Voice cloning: create, save and load a prepared voice

This is the single user workflow for preparing CosyVoice voices. The independent
tool runs the reference models on the CPU with ONNX Runtime. TTSModel only loads saved voices and produces
speech. Both use the same native SDK library; no second inference SDK is involved.
Python SDK examples only speak with ALREADY prepared voices.

## 1. Prepare the environment and model resources

Run commands from the Demo checkout root on the supported Linux AArch64 board:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r demo/requirements-clone.txt
```

Prepare the synthesis/common resources as described in [Model Setup](MODEL_SETUP.md).
Download the two cloning ONNX models directly from the Demo root:

```bash
source .venv/bin/activate
hf download FunAudioLLM/Fun-CosyVoice3-0.5B-2512 speech_tokenizer_v3.onnx campplus.onnx --revision 29e01c4e8d000f4bcd70751be16fa94bf3d85a18 --local-dir clone_models
(cd clone_models && sha256sum -c ../models/CLONE_SHA256SUMS)
```

The files are saved to `clone_models/`. No other model-download guide is needed.
The preparation tool uses the package's common tokenizer/text-table data, but
does not load the NPU synthesis engines.

A saved voice's later synthesis needs no clone_models, original recording,
original transcript file or reference-encoder sessions. Keep the user collection
separate from installed SDK assets and immutable HF model weights.

## 2. Create and save with the independent command-line tool

Use a recording you have permission to use and its exact spoken transcript.
Choose one clear speaker, no background music, 3–10 seconds, at least 16000Hz.
The tool averages channels to mono and rejects nonfinite/effectively silent
input. WAV is the recommended portable input; other formats depend on libsndfile.

```bash
source .venv/bin/activate
python tools/clone_voice.py --models models --clone-models clone_models \
  --wav /absolute/path/to/reference.wav --text "Words actually spoken in the recording." \
  --id my_voice --name "My voice" --voices-dir voices_user
```

Replace --text with the recording's matching transcript; this is reference input,
not the text to synthesize later. Do not use an unrelated demonstration sentence.
The command both creates AND saves: there is no second save API or save button
required. It prints JSON with id, name and state="saved" after successful saving,
then closes its owned encoder sessions. It does not register into a running Web
model; use the Web workflow below for immediate in-service use.

| Option | Required / default | Accepted values |
| --- | --- | --- |
| --wav | Required | Readable reference audio file path; use WAV for portability. |
| --text | Required | Matching nonempty transcript, at most 200 characters after trimming. |
| --id | Required | Stable ID matching [A-Za-z0-9_-]{1,64}, e.g. my_voice. Must not overwrite an existing destination. |
| --name | Optional; ID | Display name; distinct from the ID used as speaker. |
| --voices-dir | Optional; CV3_USER_VOICES or checkout/voices_user | Writable output collection directory. Tool saves one child named after --id. |
| --models | Optional; CV3_MODELS or checkout/models | Matching local model package root. |
| --clone-models | Optional; CV3_CLONE_MODELS or checkout/clone_models | Directory containing both fixed upstream CPU ONNX models. |
| --threads | Optional; 4 | Integer 0..2147483647; 0 derives a count from allowed CPU affinity. This configures tool-owned CPU sessions. |
| --gender | Optional; female | Exactly female or male; display metadata, not a synthesis speaker selector. |
| --category | Optional; mandarin | Exactly mandarin or role; application metadata. |
| --instruct | Optional; None | Free-text application style metadata; not reference transcript or language. TTSModel callers explicitly pass prompt if desired. |
| --locked | Optional; absent | Boolean flag marking the saved voice undeletable through the Web UI; not filesystem access control. |

## 3. Locate and preserve the saved package

```text
voices_user/
  my_voice/
    voice.json
    prompt_text_ids.npy
    prompt_text_rows.npy
    llm_prompt_token.npy
    flow_prompt_token.npy
    prompt_feat.npy
    embedding.npy
    preview.wav
```

voice.json records format/model/conditioning compatibility, stable id, display
name and file hashes/dtypes/shapes. The tool validates a temporary sibling
directory and atomically saves the complete package without replacing an
existing destination. Failed creation does not leave a partial ready package.
preview.wav is optional for synthesis. Preserve the entire directory when
copying a voice; editing voice.json hashes to hide altered conditions is invalid.
The final format is flat files, not ZIP or NPZ. See [format and validation](VOICE_PACKAGES.md).

Use a new ID for a newly created voice; the creation tool refuses an existing
output directory. SDK idempotent registration is separate: identical saved
conditions with the same ID can be loaded again; different conditions under
the same ID conflict.

## 4. Load an already saved voice and synthesize

Run the Python examples below from the repository root in the `.venv` activated in step 1.

```python
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel
import soundfile as sf

with TTSModel.from_pretrained("models") as model:
    print(model.speakers)  # Includes female-zh, female-en, male-en
    voice_id = model.load_voice("voices_user/my_voice")
    print(voice_id)        # "my_voice": the ID in voice.json
    assert voice_id in model.speakers
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker=voice_id, language="zh",
    )
    sf.write("cloned.wav", result.audio, result.sample_rate)
    model.unload_voice(voice_id)  # Unregister; saved directory is untouched.
```

The path goes to load_voice, and its returned ID goes to speaker. Do not pass
the package path or display name as speaker. language describes the NEW text,
not necessarily the reference recording's language. See [exact API parameter values](../sdk/PYTHON_API.md#synthesis).

Or run the existing synthesis-only example:

```bash
source .venv/bin/activate
python examples/python/synthesize_cloned_voice.py --models models \
  --voice-package voices_user/my_voice --language zh --out cloned.wav
```

To restore a whole collection at initialization:

```python
with TTSModel.from_pretrained("models", voices_dir="voices_user") as model:
    print(model.speakers)  # Built-ins plus valid saved user IDs.
```

Pass a collection to voices_dir, or one package to load_voice. Initialization
rejects an invalid collection/package; fix or explicitly move the invalid package
out of that collection before retrying. Streams reserve ownership until closed,
including after exhaustion. Close the request before SDK load/unload; a busy
owner raises TTSStateError. Failed registration rolls back attempted stages;
an unrecoverable rollback requires close/recreation, not a hidden retry.

## 5. Start Web cloning and use the voice immediately

Install the model target for your chip from the [Targets table](MODEL_SETUP.md#targets) before starting the Web Demo.

Prepare the complete Web installation and optional CPU files first. For a fresh
user collection, create it once. Existing collections and files are retained:

```bash
source .venv/bin/activate
mkdir -p voices_user
export CV3_MODELS="$PWD/models"
export CV3_CLONE_MODELS="$PWD/clone_models"
export CV3_USER_VOICES="$PWD/voices_user"
bash demo/run.sh
```

Open https://<board-ip>:8766/ and use **+ Clone** in the existing Demo.
The same application provides creation and synthesis; no separate cloning
server or Python clone-example page is needed. See [HTTPS/microphone setup](../demo/README.md#https-and-the-microphone).

1. Record over HTTPS or upload a file; confirm the speaker's consent, name and
   exact transcript. The page trims silence and requires 3–5 seconds after
   trimming (4–5 recommended), at least 16kHz and at most 200 transcript characters.
   Web keeps at most 20 user voices.
2. Submit creation. The independent encoder saves and validates a package under
   CV3_USER_VOICES/<generated-id>. The generated ID is stored in voice.json;
   the display name is not the speaker ID. The recording's matching text is
   retained in the prepared conditions.
3. Saving first yields saved/waiting-to-load. The page requests loading into the
   EXISTING TTS instance, waits for any current synthesis to release ownership,
   and marks ready only after successful registration. It refreshes the list
   and selects the new voice. Enter synthesis text and speak immediately; there
   is no full-model restart/reload.
4. If loading fails, the state is saved/load-failed. The complete saved package
   is retained; correct its reported compatibility/integrity issue and use the
   pending voice's load-only retry. Do not re-record/reclone merely to retry
   registration. A busy/waiting response remains retryable after the current
   request finishes.
5. Restarting the service restores valid saved packages from CV3_USER_VOICES.
   Invalid saved packages are retained/reported; they are not silently marked
   ready. CLI-created packages can be loaded by restarting this service; CLI
   creation itself does not hot-register into another process.

For integrations, GET /voices lists usable registered voices; GET /voices/saved
lists saved states; POST /voices/<id>/load retries a saved package. Those are
Demo HTTP operations, not TTSModel methods. SDK unload never deletes files;
the Web's explicit delete action also removes its saved user directory.

Stop this service before running separate NPU examples:

```bash
bash demo/stop.sh
```

## 6. Explicitly migrate old catalogue/NPZ voices

```bash
source .venv/bin/activate
python tools/migrate_voices.py /absolute/legacy-catalogue /absolute/new-voices-user
```

The source contains voices.json and voices/<id>.npz. The destination must be
new. Migration preserves original dtype/shape/bytes of all six required arrays,
runs no feature extraction and keeps source NPZ files/recordings unchanged.
Then load a destination child with load_voice, or use the new collection as
voices_dir. There is no implicit migration during model loading or Web startup.

Related references: [Python API](../sdk/PYTHON_API.md) ·
[voice format](VOICE_PACKAGES.md) · [tool index](../tools/README.md).
