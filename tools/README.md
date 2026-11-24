# Independent voice preparation tools

The complete startup, resource setup, creation, atomic saving, saved-voice
loading, Web retry/restart and lossless migration instructions live in the
[voice cloning guide](../docs/VOICE_CLONING.md).

| Tool | Responsibility |
| --- | --- |
| [clone_voice.py](clone_voice.py) | Create and atomically save one voice package from an authorized recording/transcript; owns CPU reference resources, never a TTSModel. |
| [migrate_voices.py](migrate_voices.py) | Explicit lossless conversion of an old catalogue/NPZ into flat prepared packages; keeps originals. |

These are independent preparation tools, not Python synthesis examples. To speak
with a saved package, see [the guide's loading section](../docs/VOICE_CLONING.md#4-load-an-already-saved-voice-and-synthesize)
and [synthesize_cloned_voice.py](../examples/python/synthesize_cloned_voice.py).
