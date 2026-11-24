# Fun-CosyVoice3-0.5B-2512 SDK

Load local Fun-CosyVoice3 model resources and synthesize mono speech with prepared voices.

## What's included

| Path | Content |
| --- | --- |
| `pandora_fun_cosyvoice3_0_5b_2512/` | Python package (`from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel`) |
| `include/` | C header |
| `lib/` | Prebuilt native library with its QNN runtime |
| `SHA256SUMS` | Checksums of the shipped files |

The `wheels/` folder contains the bundled hardware Runtime wheel.

## Install

In your application's activated Python 3.10–3.12 environment, from the Demo root:

```bash
python -m pip install sdk/wheels/pandora_runtime-*.whl
python -m pip install ./sdk
```

The device must pass `sudo lms check`. The SDK does not install LMS or drivers and does not download models; see [Get the model](../README.md#2-get-the-model).

Check the [device requirements](../docs/SDK_ENVIRONMENT.md) before loading a model.

## Usage

```python
import soundfile as sf
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize("Hello, welcome to text-to-speech.", speaker="female-en", language="en")
    sf.write("speech.wav", result.audio, result.sample_rate)
```

Open `speech.wav` in an audio player to hear the result.

## Documentation

- [Python API](PYTHON_API.md)
- [C ABI](../docs/C_ABI.md)
- [Examples](../examples/README.md)
- [Licensing](../LICENSING.md)
