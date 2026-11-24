# Examples

## Overview

| Example | What it shows |
| --- | --- |
| [python/synthesize.py](python/synthesize.py) | Synthesize and save a WAV file. |
| [python/stream.py](python/stream.py) | Write audio incrementally and close a request early. |
| [python/synthesize_cloned_voice.py](python/synthesize_cloned_voice.py) | Synthesize with an already prepared voice package. |
| [c/runtime_example.c](c/runtime_example.c) | Synthesize and save PCM audio through the C ABI. |
| [c/text_frontend.c](c/text_frontend.c) | Prepare Chinese or Japanese text through the native frontend. |

## Before you run

Complete [Install](../README.md#1-install) and [Get the model](../README.md#2-get-the-model). Run every command from the Demo root in the activated environment. Stop the Web Demo first; examples and the Web Demo share the NPU.

## Python examples

### synthesize.py

Synthesize a built-in Chinese sample and save `speech.wav`.

```bash
python examples/python/synthesize.py
```

Output excerpt:

```text
finish_reason=stop
```

### stream.py

Write an audio chunk and cancel the rest of the request. Omit `--stop-after-chunks` to stream to completion.

```bash
python examples/python/stream.py --stop-after-chunks 1
```

Output excerpt:

```text
finish_reason=cancelled
```

### synthesize_cloned_voice.py

Load the bundled English voice package and synthesize a sample. To use another prepared voice, pass its package directory with `--voice-package` and the text language with `--language`. The [voice cloning guide](../docs/VOICE_CLONING.md) covers creating packages in the application.

```bash
python examples/python/synthesize_cloned_voice.py
```

Output excerpt:

```text
finish_reason=stop
```

## C example

### runtime_example.c

Synthesize with a prepared built-in voice. The output file contains 24 kHz mono float32 audio.

Build against the headers and prebuilt library in `sdk/`:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/runtime_example.c -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -lcosyvoice3 -Wl,-rpath,'$ORIGIN/../../sdk/lib' -o examples/c/runtime_example
examples/c/runtime_example models sdk/assets/voices/female-zh female-zh speech.f32
```

Output excerpt:

```text
Synthesis complete.
```

See [C ABI](../docs/C_ABI.md) for ownership, error handling and the CPU example commands.
