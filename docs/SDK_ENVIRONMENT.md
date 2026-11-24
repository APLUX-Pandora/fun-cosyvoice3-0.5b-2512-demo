# SDK environment requirements

Follow [Install](../README.md#1-install) before using the
[SDK](../sdk/README.md) or the Web Demo.

## Device requirements

Use a compatible Linux AArch64 device with Aidlux LMS, DSP firmware and
BSP/FastRPC support. Run `sudo lms check` and continue when it returns true.
The SDK loads the packaged QNN libraries and DSP components from the directory
next to its native library. Keep that directory together with the library when
copying an SDK installation.

## Python environment

Use Python 3.10, 3.11 or 3.12 with its matching venv support.
Run Python, pip, model downloads and the Web Demo in the same project `.venv`.

The SDK installs NumPy and the UniDic dictionary. The Demo and its audio-file examples install SoundFile through the Demo requirements.
The root `requirements.txt` includes `./sdk`, Flask, Werkzeug and the Hugging Face CLI for the Demo.
LMS, firmware and drivers come from the device installation. Download models separately.
`python -m pip check` checks only Python dependency consistency.

## Linux compatibility scope

The SDK includes ICU, MeCab and OpenFST in the model library. The native library is shared by all supported Python versions.

## Optional path overrides

| Setting | Meaning |
| --- | --- |
| `CV3_MODELS` | Explicit model root; an invalid explicit path does not fall back |
| `CV3_LIB` | Explicit native library override; failures do not fall back |
| `CV3_CLONE_MODELS` | Optional separate reference-cloning ONNX directory |

For model package selection and checksums, see [Model Setup](MODEL_SETUP.md).
For CPU placement, QNN settings and ownership, see [Runtime](../sdk/RUNTIME_API.md).
Buffer protection and caller boundaries are documented in [Model Protection](MODEL_PROTECTION.md).
Text helpers and optional reference conditioning are described in
[Text Frontend](TEXT_FRONTEND_API.md) and the [application voice tool](VOICE_CLONING.md).
