# C ABI

`sdk/include/cosyvoice3.h` · `sdk/lib/libcosyvoice3.so` · Text-to-token and waveform synthesis in native applications.

## Build and link

Install the SDK and its bundled Runtime in the same environment by following the [SDK installation](../sdk/README.md#install).

From the Demo root, compile against the shipped header and library; the library carries its QNN runtime:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -I sdk/include your_app.c -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -lcosyvoice3 -Wl,-rpath,'$ORIGIN/sdk/lib' -o your_app
```

For a native-only deployment, ship `libpandora_runtime.so.5` from the wheel in a location the system loader can find.

## Lifecycle

```text
create Runtime → create both stages → register the voice in both stages
  → start both stages → read tokens and push them to waveform synthesis
  → finish, step and read until drained → destroy both stages → destroy Runtime
```

On a failed creation, release the stages already created. Read the error before making another call on the same owner. A failure in token generation or waveform stepping ends that request. Start a new request after fixing the input or re-create the owners if the backend cannot recover.

## Functions

The [model header](../sdk/include/cosyvoice3.h) and [Runtime header](../sdk/include/pandora_runtime.h) define all signatures and structures. Status calls return zero on success and a negative error on failure.

| Function | Purpose | Returns |
| --- | --- | --- |
| `cv3_version`, `cv3_create_error` | Report SDK identity or a failed create. | Borrowed string. |
| `cv3_llm_create`, `cv3_t2w_create` | Create a stage and its default Runtime. | Owned handle or NULL. |
| `cv3_llm_destroy`, `cv3_t2w_destroy` | Release a legacy stage handle. | Void. |
| `cv3_llm_last_error`, `cv3_t2w_last_error` | Read a stage error. | Borrowed string. |
| `cv3_llm_load_voice`, `cv3_t2w_load_voice` | Register a prepared flat voice package in both stages. | Status. |
| `cv3_llm_unload_voice`, `cv3_t2w_unload_voice` | Unregister a voice from a stage. | Status. |
| `cv3_llm_start` | Start a text-to-token request. | Status. |
| `cv3_llm_prompt_rows`, `cv3_llm_count_tokens` | Count context rows or text tokens. | Count or negative error. |
| `cv3_llm_next` | Read the next token. | 1 with a token, 0 at end, or negative error. |
| `cv3_llm_end_reason` | Query why token generation ended. | End-reason enum. |
| `cv3_llm_abort` | Request stop after the current step. | Void. |
| `cv3_t2w_start` | Start waveform generation for a voice. | Status. |
| `cv3_t2w_push` | Pass speech tokens to the waveform stage. | Accepted count or negative error. |
| `cv3_t2w_finish` | Signal the final token and begin draining. | Status. |
| `cv3_t2w_abort` | Discard the current waveform stream after pending work returns. | Status. |
| `cv3_t2w_step` | Run the next waveform step. | New sample count or negative error. |
| `cv3_t2w_read` | Copy queued mono float32 audio to a caller buffer. | Written count or negative error. |
| `cv3_t2w_done` | Check whether the final computation has completed. | 1 when done, 0 otherwise. |
| `cv3_llm_get_stats`, `cv3_t2w_get_stats` | Read counters from a stage. | Status. |
| `cv3_llm_create_with_runtime`, `cv3_t2w_create_with_runtime` | Bind a model stage to a caller-supplied Runtime. | Status; owned stage handle on success. |
| `cv3_llm_destroy_owned`, `cv3_t2w_destroy_owned` | Release a stage and clear its owner pointer. | Status. |
| `cv3_t2w_max_frames` | Query the waveform capacity. | Frame count. |
| `cv3_prepare_process`, `cv3_get_protection_stats` | Compatibility entry point and read-only diagnostics. | Status. |
| `cv3_reference_project`, `cv3_reference_rfft`, `cv3_reference_resample` | Run CPU reference arithmetic into caller buffers. | Status. |
| `cv3_reference_feature_shape`, `cv3_reference_features` | Query and calculate CPU reference features. | Status. |
| `cv3_text_frontend_create`, `cv3_text_frontend_run`, `cv3_text_frontend_destroy_owned` | Create, run and release native text preparation. | Status. |
| `pandora_runtime_create`, `pandora_runtime_get_status`, `pandora_runtime_destroy` | Create, query and release Runtime ownership. | Status. |
| `pandora_runtime_last_error` | Read the last Runtime error in this thread. | Borrowed string. |

The CPU feature and signal-processing helpers in the header support the [application voice tool](VOICE_CLONING.md).

### Hardware settings

Pass a null configuration to the shared runtime creation call to use the SDK defaults.
Load each stage with a null runtime to let the stage own its defaults. For advanced
settings, use the [Runtime API](../sdk/RUNTIME_API.md) and the matching public header.
Model handles hold a reference and remain usable after the caller releases its runtime.
Synchronize destruction with in-flight calls.

### Native text preparation

cv3_text_frontend_create(model_dir, japanese_dictionary, runtime, &frontend)
resolves native common resources from root models.json (or supported legacy
manifest). It does not load NPU targets. japanese_dictionary may be NULL for
non-Japanese input; otherwise supply the qualified UTF-8 UniDic102 directory.
The reader is loaded lazily. runtime may be NULL for Pandora defaults. The
output slot must initially be NULL and stays NULL on construction failure.

cv3_text_frontend_run(frontend, operation, text, language, &json_result) returns
status. operation0 prepares one string for the declared language;1 normalizes
one string;2 normalizes and returns a segment list;3 returns tokenizer IDs;
4 splits the given text (zh character counts, otherwise token counts);5 returns
the Japanese-kana predicate. Fixed splitter limits are80/60/20. For normalize,
text with special tokens is passed through under the existing contract.

text and language are NUL-terminated UTF-8, at most1MiB each. Results are JSON:
a string for0/1, string array for2/4, int32 ID array for3 or boolean for5.
json_result points to native-owned storage until the next successful run or
destruction. Copy it before another call; do not free it. An error leaves the
output pointer unchanged. Calls/destroy on one handle require serialization.

cv3_text_frontend_destroy_owned(&frontend) releases its FSTs, tokenizer, lazy
reader and dictionary mappings on its native owner, joins the worker and clears
the slot. Repeat close of an empty slot succeeds. Close a caller Runtime later.
Fork-inherited use/destroy is rejected. Runtime CPU owner drift fails inference;
explicit cleanup remains available without restoring a bad mask. Errors use
the calling thread's cv3_create_error diagnostic.

The complete C99 client uses the same C ABI and library. From the Demo root:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror examples/c/text_frontend.c -Isdk/include -Lsdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -lcosyvoice3 -Wl,-rpath,'$ORIGIN/sdk/lib' -o text_frontend
./text_frontend models zh '今天25度。'
./text_frontend models ja 'こんにちは。' /absolute/path/to/unidic_lite/dicdir
```

It prints one JSON string and releases all partial/full native resources.
No dictionary, model, runtime installation or download occurs inside the example.

## Error codes

| Code | Meaning | What the caller should do |
| --- | --- | --- |
| `CV3_ERR_ARG` | Invalid argument. | Check the value or buffer. |
| `CV3_ERR_MODEL` | A model or resource is missing or incompatible. | Check [model setup](MODEL_SETUP.md). |
| `CV3_ERR_NPU` | An NPU operation failed. | Read the error and check the device runtime. |
| `CV3_ERR_STATE` | The call is invalid in the current state. | Restore the documented call sequence. |
| `CV3_ERR_INTERNAL` | The SDK could not finish the operation. | Preserve the error and release the affected owner. |

Runtime functions return the `PANDORA_ERR_*` values declared in their header. Read the associated error before calling again.

## Threads and ownership

Use each stage from one caller thread at a time. `cv3_llm_abort` may request cancellation during inference. Join all callers before destruction. Inputs are borrowed for a synchronous call unless the header specifies otherwise. The caller owns audio output arrays. Copy error strings before the next call on their owner. See the headers for the lifetimes of views returned by the preparation APIs.

## Example

A complete program is in [examples/c/runtime_example.c](../examples/c/runtime_example.c). Its [build and run instructions](../examples/README.md#c-example) use the shipped library and a prepared voice.
