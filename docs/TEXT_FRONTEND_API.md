# Text preparation helper

Before using the Python examples, complete [installation](../README.md#1-install) and
[model preparation](MODEL_SETUP.md). Run from the Demo repository root in the same environment:

```bash
source .venv/bin/activate
```

This retained extension supports explicit application segmentation using the
installed SDK's model-specific preparation. Ordinary synthesis owns its helper.

```python
from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_frontend import TextFrontend

with TextFrontend("models") as frontend:
    print(frontend.normalize("今天25度。", split=False))
```

`TextFrontend(model_dir, *, runtime=None, library=None)` loads local resources
synchronously. The SDK applies its [hardware defaults](../sdk/RUNTIME_API.md) when
no settings are supplied. The frontend owns its native worker, normalizer,
tokenizer and Japanese reader.

| Method | Return |
| --- | --- |
| `prepare(text, language)` | One prepared string; Japanese reading/Chinese normalization as applicable; other language text preserved |
| `normalize(text, split=True)` | List of non-punctuation segments; split=False returns one prepared string |
| `encode(text, **kwargs)` | Token ID list; compatibility kwargs are ignored |
| `close()` | Wait for in-flight work and release; idempotent; also supports with |

Segmentation/encode uses the native tokenizer and needs no extra Python package.
The segment extra remains accepted for installation compatibility. Japanese input
uses the dictionary installed with the SDK.
Calls are serialized by the helper; use after close raises RuntimeError.
The helper does not translate text, load NPU graphs, save audio or manage requests.
Missing resource/dependency errors propagate. See [model setup](MODEL_SETUP.md)
and [task API](../sdk/PYTHON_API.md).


## Native implementation

The native library handles Chinese FST composition, token reordering and
cleanup, Japanese NFKC, number conversion and MeCab reading, Unicode
classification, tokenization and fixed segmentation. The Python helper
converts arguments and results and owns the native handle.

Each frontend owns native FSTs, tokenizer, lazy Japanese reader/dictionary
mappings and a Runtime CPU worker. The binding owns a separate dispatch thread.
Both obey the same Runtime CPU placement. close waits for work and releases
native resources explicitly before joining owners; a caller Runtime stays alive.
ICU implementation/data are statically linked shared constants, not a new
Ubuntu ICU shared-library requirement. CPU-only text calls read the tokenizer
and normalizer from the shared resources in models.json. If models.json is absent,
a legacy format 1 manifest.json may provide these roles in its files or extras
section. Text-only use needs no installed target.

Unicode classification uses ICU and Japanese reading uses a UTF-8 UniDic
dictionary. The frontend preserves special tokens and passes through languages
without a normalization rule.
Missing Japanese resources report an incomplete SDK installation before synthesis starts,
including kana encountered in the Chinese path. Such rejected requests keep the
TTS model reusable.

The C ABI accepts UTF-8 inputs up to1MiB each, returns borrowed JSON valid until
the next successful operation or close, and rejects invalid UTF-8, missing output
pointers and unknown operations. See [C ABI](C_ABI.md#native-text-preparation)
and the complete [C99 client](../examples/c/text_frontend.c).
