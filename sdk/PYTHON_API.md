# Python API

`TTSModel` loads
prepared voices, synthesizes and releases resources. Voice creation is an
[independent cloning workflow](../docs/VOICE_CLONING.md); it is not a synthesis method.

## Quick start

```python
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize("Hello, welcome to text-to-speech.", speaker="female-en", language="en")
    print(result.sample_rate, result.duration_s, result.finish_reason)
```

## API overview

| Entry point | Purpose and return | Runnable example |
| --- | --- | --- |
| `TTSModel.from_pretrained(model_dir, *, voices_dir=None, runtime=None)` | Load local resources; returns an owned model. | [Complete synthesis](../examples/python/synthesize.py) |
| `model.synthesize(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None)` | Return complete `SynthesisResult` after inference. | [Complete synthesis](../examples/python/synthesize.py) |
| `model.synthesize_stream(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None)` | Return owned `AudioStream`; read new audio while iterating and close even on early exit. | [Streaming](../examples/python/stream.py) |
| `model.load_voice(voice_package_dir)` | Register one prepared package; return its authoritative string ID. | [Prepared cloned voice](../examples/python/synthesize_cloned_voice.py) |
| `model.unload_voice(speaker_id)` | Unregister a voice; return None without deleting its files. | [Voice workflow](../docs/VOICE_CLONING.md) |
| `model.speakers / languages / capabilities` | Query loaded IDs, supported language codes and feature flags. | [Complete synthesis](../examples/python/synthesize.py) |
| `model.close()` / model context manager | Release owned resources after streams/callers finish; return None. | [Complete synthesis](../examples/python/synthesize.py) |

## Parameters

### Choosing language and speaker

Both are required keyword arguments in the Python API. Omitting either raises
TypeError. Example scripts have their own CLI defaults and pass explicit values
to the API; that does not give the SDK an automatic-language mode.

language declares the language of the text: zh, en, ja, ko, de, fr, es, it, ru.
Query `model.languages`; `pt` is unsupported. It is not translation, dialect or language detection;
auto and None are unsupported. Cosy has no equivalent native language-selector
token in this path. The declaration controls the matching text frontend and
same/cross-language conditioning choice against the voice's reference language.
Same-language text normally uses the prepared reference text/audio conditions;
cross-language text uses the existing cross-lingual template while preserving
the voice's acoustic conditions. No separate mode argument is needed. A style
instruction is the optional prompt, not language. Mixing languages does not
itself promise translation or trigger a mandatory language-identification pass.

speaker is a case-sensitive string ID, not a numeric index, display name, audio
path or package path. The delivered built-ins are:

| ID passed as speaker | Built-in voice / reference language |
| --- | --- |
| female-zh | Female / Chinese |
| female-en | Female / English |
| male-en | Male / English |

Query model.speakers after loading; it contains built-ins plus registered user
IDs. A voice can speak text in another supported language; its ID need not match
the text-language code.

```python
with TTSModel.from_pretrained("models") as model:
    print(model.speakers)   # Loaded IDs; do not rely on ordering
    print(model.languages)
    # Built-in ID passed directly:
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker="female-zh", language="zh",
    )
    # An ALREADY prepared package: returned ID is authoritative.
    voice_id = model.load_voice("voices_user/my_voice")
    assert voice_id in model.speakers
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker=voice_id, language="zh",
    )
```

The independent tool's --id my_voice is saved as voice.json's id; the folder
name/display name need not be the ID. load_voice returns that validated ID.
Alternatively, from_pretrained("models", voices_dir="voices_user") loads the
collection at initialization; query model.speakers to discover registered IDs.
The SDK has no model-owned clone method: creation belongs to the independent
tool, and synthesis only loads its saved output.


### Loading and ownership

`TTSModel.from_pretrained(model_dir, *, voices_dir=None, runtime=None)`

| Parameter | Type | Required / default | Accepted values and behavior |
| --- | --- | --- | --- |
| model_dir | str or pathlib.Path | Required | Local package directory containing the model manifest. See [model setup](../docs/MODEL_SETUP.md). |
| voices_dir | str or pathlib.Path, or None | Optional; None | Existing collection directory, e.g. "voices_user", whose child directories are compatible voice packages. None adds no user collection; declared built-ins still load. This is not the path to a single package or a legacy voices.json catalogue. |
| runtime | Runtime or None | Optional; None | A matching Pandora Runtime instance, or None to create a model-owned default Runtime. Strings/dicts are not Runtime objects. See [Runtime parameters](RUNTIME_API.md). |

The model SDK's `assets/tts-model.json` declares its immutable built-in collection.
Model weights, vendor runtimes and user voices are separate. Synthesis needs no
clone_models, extraction dependency, original recording or transcript file.
`close()` is idempotent when idle; close streams and wait for callers first.
Inherited handles are rejected after fork; initialize in each spawned process.

### Synthesis

`model.synthesize(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None)`

`model.synthesize_stream(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None)`

| Parameter | Type | Required / default | Accepted values and behavior |
| --- | --- | --- | --- |
| text | str | Required positional argument | Nonempty, not whitespace-only, no NUL characters. Caller-provided text is accepted; effective capacity depends on tokenized input and voice conditions. Oversized context fails explicitly. The SDK does not automatically split long text. |
| speaker | str | Required keyword; no default | Exact case-sensitive member of model.speakers. Initially "female-zh", "female-en", "male-en"; also IDs returned by successful load_voice or loaded from voices_dir. Pass the ID, not a display name/index/package path. Unknown IDs raise ValueError. |
| language | str | Required keyword; no default | Exactly "zh", "en", "ja", "ko", "de", "fr", "es", "it", or "ru" (lowercase). Query model.languages. None, "auto", "mixed", "pt", language names such as "Chinese", and uppercase aliases are unsupported. It declares text language; no translation or language-detection mode. |
| prompt | str or None | Optional; None | Free-text model instruction, not an enum. For example "请用四川话表达。". None, "" or whitespace-only means no instruction. Nonempty strings must be NUL-free. The SDK constructs the native template; do not append internal template delimiters. Instruction quality is model-dependent. |
| seed | int or None | Optional; None | None draws a fresh seed for the native sampler per request. Explicit integers 0..4294967295 inclusive; bool, float, strings, negative values and larger integers are rejected. A seed controls sampling, not the speaker or language. |
| max_new_tokens | int or None | Optional; None | None uses the native request/context bounds. Explicit integers 1..2147483647 inclusive; bool, 0, negative values, floats and strings are rejected. Units are speech tokens, not characters/seconds. Actual generation remains capped by available context/waveform capacity; a large number does not extend the model. |


The same parameter rules apply to complete and streaming calls. There is no
mode argument: choose synthesize for complete audio or synthesize_stream for
incremental audio; same/cross-language conditioning follows the text and voice
as described above. Neither method accepts a reference recording/transcript.

Defaults apply independently per request and never inherit the previous request's
seed/prompt/budget. Context rejection is an error. The model owns one active
request; voice mutation or another request while busy raises TTSStateError.

### Prepared voices

`speaker_id = model.load_voice(voice_package_dir)`

| Method / argument | Accepted input | Return / effect |
| --- | --- | --- |
| load_voice(voice_package_dir) | str or pathlib.Path pointing to ONE existing package directory containing voice.json plus its six flat NPY conditions, e.g. "voices_user/my_voice". No ZIP, NPZ, catalogue root, symlink directory or audio file. | str ID from validated voice.json, also present in model.speakers after successful registration. |
| unload_voice(speaker_id) | Exact currently registered str ID, including built-in IDs; use the load_voice return value or query model.speakers. | None; unregisters only, never deletes source files. Unknown IDs raise ValueError. |

For preparation, atomic saving, Web startup, loading, restart recovery and
legacy migration, use the single [voice cloning guide](../docs/VOICE_CLONING.md).
The format itself is specified in [voice packages](../docs/VOICE_PACKAGES.md).

Validate and synchronously register one compatible [flat voice package](../docs/VOICE_PACKAGES.md).
The returned ID appears in speakers only after both native stages succeed.
Identical required conditions/ID are idempotent; conflicting content raises
ValueError. Display names and optional previews do not define condition identity.
The SDK retains its own validated conditions, independent of caller file lifetime.
No extraction or download is triggered. Failed registration rolls back attempted
stages; an unrecoverable rollback requires close/recreation.

`model.unload_voice(speaker_id)` unregisters both stages and updates speakers.
Built-ins and users can both be unloaded. Unknown IDs fail explicitly. Source
files are never deleted. Owned synthesis streams, including exhausted-but-not-
closed streams, exclude load/unload; the caller must release them first.

For legacy voice collections, use the explicit migration tool documented in the
[voice cloning guide](../docs/VOICE_CLONING.md#6-explicitly-migrate-old-cataloguenpz-voices).
Loading a voice never implicitly converts or reclones it.

## Results and cleanup

### `SynthesisResult`

`SynthesisResult` has read-only fields audio (independently owned one-dimensional
NumPy float32 mono), sample_rate, finish_reason, plus derived duration_s/is_complete.
Audio remains valid after later calls and close; the array itself can be writable.
Current output is 24 kHz; always use the returned sample rate.

| Output / query | Type and possible values |
| --- | --- |
| result.audio / chunk.audio | Independently owned 1D NumPy float32 mono samples; not encoded WAV bytes. |
| result.sample_rate / chunk.sample_rate | int in Hz; current build returns 24000. |
| result.duration_s | float seconds, len(audio) / sample_rate. |
| result.finish_reason | Exactly "stop" (normal termination/tail drain) or "length" (budget/capacity prevented full completion). |
| result.is_complete | bool; True exactly when finish_reason is "stop". |
| stream.finish_reason | None while active; "stop" or "length" after exhaustion; "cancelled" after early close. Closing an exhausted stream preserves its completion reason. Input or state errors raise and release the request without setting a finish reason. |
| model.speakers | tuple of currently loaded string IDs. Load/unload updates it; ordering is not a selection contract. |
| model.languages | tuple containing the nine codes listed above. |
| model.capabilities | Read-only TTSCapabilities with boolean streaming, prompt, seed, max_new_tokens fields; all four are supported. Not a prerequisite to normal calls. |


`stop` requires normal native termination and waveform-tail drain. `length` means
an actual generation budget prevented completion; produced audio remains valid.
Failures raise errors instead of returning empty success.

### Errors

| Error | Meaning |
| --- | --- |
| TypeError / ValueError | Wrong type / invalid value, voice compatibility or conflicting content |
| TTSUnsupportedError | Unsupported feature/language or missing optional feature dependency |
| TTSLoadError | Model/native/voice loading failure |
| TTSInferenceError | Native inference failure or unrecoverable mutation rollback |
| TTSStateError | Busy/closed/inherited/invalid ownership state |

TTS errors derive from TTSError and retain native_code and cause where available.
During synthesis, native argument errors raise ValueError with native_code,
model resource errors raise TTSLoadError, and invalid native state raises
TTSStateError. Backend and unexpected native errors raise TTSInferenceError.
After a request fails with an argument or state error, the SDK releases that
request and the model can accept another one if cleanup succeeds.
Filesystem/manifest validation can retain standard errors. After unrecoverable
native inference or rollback failure, close/recreate; no hidden retry exists.
The application owns signals, HTTP, playback, persistence and deletion policy.

### Lifecycle

```python
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel
with TTSModel.from_pretrained("models") as model:
    with model.synthesize_stream(
        "Hello, welcome to text-to-speech. Today, we use a clear and natural voice to turn written words into speech you can hear.",
        speaker="female-en", language="en",
    ) as stream:
        for chunk in stream:
            print(chunk.audio.shape, chunk.sample_rate)
    print(stream.finish_reason)
```

Each chunk contains new samples. Streaming does not retain a complete waveform.
The iterator/context owns the request until close. finish_reason is None while
active, stop/length after exhaustion and cancelled after early close. Closing an
exhausted stream preserves its reason. Early close stops future scheduling,
waits for in-flight use and releases ownership. See [stream.py](../examples/python/stream.py).

## Advanced

[Runtime](RUNTIME_API.md) ·
[Stage API](../docs/STAGE_API.md) · [Text frontend](../docs/TEXT_FRONTEND_API.md) ·
[C ABI](../docs/C_ABI.md) · [Voice cloning workflow](../docs/VOICE_CLONING.md) ·
[Examples](../examples/README.md). Advanced preparation uses the same native library.
