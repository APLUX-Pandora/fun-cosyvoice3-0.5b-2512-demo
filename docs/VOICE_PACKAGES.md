# Prepared voice packages

One voice is one self-contained directory. Format1 uses model_id
`FunAudioLLM/Fun-CosyVoice3-0.5B-2512` and conditioning_version
`cosyvoice3-reference-v1`. Built-ins and user voices have the same layout:

```text
my_voice/
  voice.json
  prompt_text_ids.npy
  prompt_text_rows.npy
  llm_prompt_token.npy
  flow_prompt_token.npy
  prompt_feat.npy
  embedding.npy
  preview.wav              # optional, never required for synthesis
```

voice.json requires format_version, safe id (`[A-Za-z0-9_-]{1,64}`), display name,
model_id, conditioning_version and exactly six files roles. Each role records
its flat relative path, lowercase SHA256, NumPy dtype string and shape. Optional
reference_language describes the reference, not a restriction on synthesis.
Preview is optional; extra display/source metadata is preserved by migration.
No ZIP/NPZ/pickle/PyTorch archive is the final voice format.

| Role | Little-endian C-order dtype/shape |
| --- | --- |
| prompt_text_ids | int32[T], T1..1024, IDs0..151935 |
| prompt_text_rows | float32[T,896] |
| llm_prompt_token | int32[S], S1..250, IDs0..6560 |
| flow_prompt_token | int32[S], equal to the LLM prompt tokens |
| prompt_feat | float32[2*S,80] |
| embedding | float32[192] |

All floats must be finite. Files are bounded to8MiB each. Both loaders reject
incompatible identities/versions, missing roles, digest/shape/type mismatches,
unsafe links and non-flat/absolute/traversing paths before registration. Conditions
are copied/retained by the SDK; changing or deleting source files after successful
load does not invalidate active owners. Hashes establish integrity, not publisher
trust. Keep deployed packages owned by the intended user.

The matching model SDK declares its built-ins in assets/tts-model.json and ships
them under assets/voices; inference weights remain separately sourced from HF.
`voices_dir` is a user collection whose children are packages, outside immutable
model weights. An external catalogue is unnecessary. Explicit load accepts one
package directory and returns its ID. Identical conditions/ID are idempotent;
different conditions conflict. Unload never deletes files and can remove built-ins
as well as users. Request ownership excludes mutation.

See [Python API](../sdk/PYTHON_API.md), [creation/migration](../tools/README.md)
and [speaking with an existing voice](../examples/python/synthesize_cloned_voice.py).

Voice creation, saving, loading and Web use: [voice cloning guide](VOICE_CLONING.md).
