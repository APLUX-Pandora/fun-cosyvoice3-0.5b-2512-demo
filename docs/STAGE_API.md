# Advanced stage and compatibility API

Before using the Python examples, complete [installation](../README.md#1-install) and
[model preparation](MODEL_SETUP.md). Run from the Demo repository root in the same environment:

```bash
source .venv/bin/activate
```

The ordinary [TTS task API](../sdk/PYTHON_API.md) is the default integration.
These retained Python extensions let the Demo implement explicit segment-ahead
scheduling through the same native library. They do not supply a separate engine.

```python
from pandora_fun_cosyvoice3_0_5b_2512 import LLM, Token2Wav
```

## Stage owners and scheduling

`LLM(model_dir, *, library=None, runtime=None)` and
`Token2Wav(model_dir, *, library=None, runtime=None)` synchronously return
explicit owners. Call `close()` or use `with`; never rely on garbage collection.
The explicit package must directly contain the native model configuration.
A supplied Runtime belongs to the caller. Both owners copy the required voice
arrays from the NPZ when `load_voice(voice, npz_path)` succeeds.
`unload_voice(voice)` removes a registration; do not remove/replace the active
waveform voice before its stream finishes.

| LLM method | Input, output and order |
| --- | --- |
| `start(voice, text, seed=0, max_tokens=0, instruct=None)` | Start one normalized UTF-8 segment. max_tokens counts speech tokens; nonpositive uses native bound. Legacy seed wraps to uint32. Use the task API for strict common validation. |
| `next()` | One speech-token int, or None at end; first call performs prefill. |
| `generate(voice, text, seed=0, max_tokens=0, instruct=None)` | Iterator shorthand for start/next; closing it is not a model destroy/join. |
| `prompt_rows(voice, instruct=None)` | Prompt context-row count. |
| `count_tokens(text)` | Text-token count. |
| `end_reason()` | END_NONE/EOS/LIMIT/ABORTED; token-count equality alone does not prove completion. |
| `abort()` | Request stop after current native step; it does not join or destroy. |
| `stats()` | Snapshot dict: native counters and timings; see below. |
| `close()` | Release after all calls finish; sequential close is idempotent. |

`instruct=None`/empty selects the voice's zero-shot prompt. A nonempty instruction
uses the existing model template. This layer does not normalize arbitrary text,
translate, choose a voice or perform application segmentation.

| Token2Wav method | Input, output and order |
| --- | --- |
| `start(voice, hop_max=200)` | Begin one waveform segment; hop_max in speech tokens, usually100/200;1..24 rejected; nonpositive uses200. |
| `push(tokens)` | One-dimensional speech-token sequence, converted to contiguous int32; returns accepted count. Check short acceptance, never silently discard remaining tokens. |
| `finish()` | Mark token input ended; continue stepping/reading to drain the tail. |
| `step()` | Number of newly queued samples;0 means needs tokens or done; native failures raise. |
| `read()` | Drain available audio into a newly owned1-D float32 NumPy array; empty if none. |
| `chunks()` | Iterate step/read for currently computable audio; input can still be unfinished. |
| `done()` | Whether final computation has completed; queued audio may still need reading. |
| `stats()` | Snapshot dict of waveform counters/timings. |
| `close()` | Release only after users finish; sequential close is idempotent. |

Audio is mono24kHz. Returned arrays outlive subsequent reads/owner close.
A complete order is: create both stages; load identical voice packs into both;
start waveform and LLM; repeatedly next/push/step/read; establish the LLM end
reason; finish waveform; step/read until done and drain; close both owners.
The [C example](../examples/c/runtime_example.c) implements this complete sequence.
The [business application](../demo/tts.py) demonstrates segment-ahead Python
scheduling.

Each stage is single-caller except the asynchronous LLM abort signal. The caller
must stop/abort and join in-flight users before destroying. Separate LLM and
waveform stages may overlap as the Demo does. Native errors use
`CV3Error(code, message)` with `code`; the common task API translates these
to its TTS error classes. Invalid native state is an error, not empty success.

## Model stage session and resource helpers

`with model.stage_session():` reserves the same model as common synthesis.
Inside, the existing `model.llm` and `model.t2w` stages support the above calls.
Do not overlap common synthesis, voice mutation or model close with that session.
The session releases reservation on context exit; callers must first stop/join
their own stage users. `model.stats()` returns the common model's last statistics
snapshot; it is not required before ordinary inference.

Retained exports:
`resolve_models(model_dir=None, default_root=None)` resolves local package roots;
`model_file(model_dir, key)` looks up semantic resources;
`version()` returns the native version string.
Explicit invalid package paths fail rather than falling back.
See [model setup](MODEL_SETUP.md), [C statistics](C_ABI.md) and the shipped header
for resource roles, units and fields. LLM stats fields are text_tokens, query_rows, tokens, max_tokens (counts),
ms_npu and ms_host (milliseconds). Token2Wav stats fields are tokens, chunks,
samples, last_n (selected DiT bucket length), ms_npu and ms_host.
Use sample_rate rather than converting token counts to an assumed audio duration. Timings are cumulative within their native query/stream,
not overall service latency.

`protection_status(*, library=None)` returns
scope/active_buffers/dump_excluded_bytes/locked_bytes/unlocked_bytes/lock_failures/
last_lock_errno for process-owned context buffers. It exposes no addresses or
model data and does not claim coverage of opaque vendor copies.
See [protection policy](MODEL_PROTECTION.md).

## Speaker removal

`model.unload_voice(speaker_id)` removes registration from both native stages
and updates speakers; it does not delete caller recordings/catalogues.
Returns None; busy owners raise TTSStateError, unknown IDs ValueError.
An unload failure attempts restoration of both stages; failed rollback or owned
temporary-file cleanup requires recreation. The
[Web voice management layer](../demo/tts.py) calls this public method to
unregister a user voice. The [Web delete action](../demo/app.py) separately
removes its saved directory; SDK unloading never deletes caller-owned files.
See the [prepared-voice API](../sdk/PYTHON_API.md#prepared-voices) and
[voice cloning workflow](VOICE_CLONING.md).

## Other retained helpers

[TextFrontend](TEXT_FRONTEND_API.md) supports explicit business segmentation.
The [application voice tool](VOICE_CLONING.md) prepares voice packages on the CPU.
Voice creation and saving belong to the independent preparation tool
([CLI](../tools/clone_voice.py), [tool guide](../tools/README.md)); they are not
TTSModel methods. The [Web cloning path](../demo/app.py) uses the independent
encoder to create and save a voice package, then its
[voice management layer](../demo/tts.py) calls `model.load_voice(package_dir)`
to register that saved package in the existing TTSModel. TTSModel loads prepared
voices and synthesizes speech; it does not create or persist cloned voices.
See the [complete workflow](VOICE_CLONING.md).
