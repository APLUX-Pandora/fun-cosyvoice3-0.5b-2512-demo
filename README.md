# Fun-CosyVoice3-0.5B-2512

<p align="center">
  <a href="https://huggingface.co/APLUX-Pandora/Fun-CosyVoice3-0.5B-2512"><img src="https://img.shields.io/badge/Hugging%20Face-FUN--COSYVOICE3--0.5B--2512-E3B800?style=for-the-badge&amp;logo=huggingface&amp;logoColor=FFD21E&amp;labelColor=555555" alt="Hugging Face: Fun-CosyVoice3-0.5B-2512"></a>
  <a href="https://github.com/APLUX-Pandora/fun-cosyvoice3-0.5b-2512-demo"><img src="https://img.shields.io/badge/GitHub-FUN--COSYVOICE3--0.5B--2512-000000?style=for-the-badge&amp;logo=github&amp;logoColor=white&amp;labelColor=555555" alt="GitHub: Fun-CosyVoice3-0.5B-2512"></a>
</p>

On-device text-to-speech and streaming speech synthesis on a Qualcomm NPU, with optional voice creation from a reference recording.

Based on [Fun-CosyVoice3-0.5B-2512](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512).

**Demo recording:**

https://github.com/user-attachments/assets/30688b46-d131-4c6f-8dea-92bde290a87b

## 1. Install

Clone the Demo and enter its root directory:

```bash
git clone https://github.com/APLUX-Pandora/fun-cosyvoice3-0.5b-2512-demo.git
cd fun-cosyvoice3-0.5b-2512-demo
```

### Prepare the device

Use a compatible Linux device with Aidlux LMS and the required drivers, DSP firmware and BSP/FastRPC support. The SDK includes its QNN runtime libraries; no separate QNN installation or path configuration is required.

Check the activation:

```bash
sudo lms check
```

Continue only when it returns true.

Install the system packages the Demo needs:

```bash
sudo apt install python3-venv libsndfile1 openssl
```

### Install the Demo and SDK

Use Python 3.10–3.12. Create and activate the Demo environment, then install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

This installs the SDK, the Web Demo and the Hugging Face CLI. To use only the SDK in your own application, see the [SDK installation](sdk/README.md#install).

## 2. Get the model

Download the shared files and one device target. The commands below use QCS8550; for another device, use the folder in the [targets table](docs/MODEL_SETUP.md#targets).

For a private model, run `hf auth login` first.

```bash
hf download APLUX-Pandora/Fun-CosyVoice3-0.5B-2512 --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Fun-CosyVoice3-0.5B-2512 --local-dir models --include "targets/qcs8550_qnn248/*"
```

## 3. Run the Web Demo

```bash
bash demo/run.sh --port 8766
```

Open `https://<device-ip>:8766/` and select a voice, enter text and start synthesis. Stop it with `bash demo/stop.sh`. See the [Web Demo guide](demo/README.md).

## 4. Python Usage

In the same environment, from the Demo root:

```python
import soundfile as sf
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize("Hello, welcome to text-to-speech.", speaker="female-en", language="en")
    sf.write("speech.wav", result.audio, result.sample_rate)
```

Open `speech.wav` in an audio player to hear the result.

More in the [Python API](sdk/PYTHON_API.md) and [examples](examples/README.md).

## Documentation

- [Model setup](docs/MODEL_SETUP.md): device requirements, targets, download and folder layout
- [Python API](sdk/PYTHON_API.md): every public class, method and parameter
- [C ABI](docs/C_ABI.md): native integration
- [Examples](examples/README.md): runnable Python and C examples

- [Demo recordings](docs/RECORDINGS.md) for speech samples in several languages and styles
- [SDK environment](docs/SDK_ENVIRONMENT.md) for the device runtime and optional path settings
- [Runtime API](sdk/RUNTIME_API.md) for hardware settings
- [Stage API](docs/STAGE_API.md) for low-level text-to-token and waveform integration
- [Text frontend](docs/TEXT_FRONTEND_API.md) for native text preparation
- [Voice cloning](docs/VOICE_CLONING.md) and [voice packages](docs/VOICE_PACKAGES.md) for creating and reusing a voice
- [Model protection](docs/MODEL_PROTECTION.md) for the SDK's protected loading behavior

## License

See [LICENSING.md](LICENSING.md), [NOTICE](NOTICE) and [LICENSES](LICENSES/).
