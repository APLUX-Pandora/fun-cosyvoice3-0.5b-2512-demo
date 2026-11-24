# Model setup

## Device requirements

- A compatible Linux device with Aidlux LMS (`sudo lms check` returns true), drivers, DSP firmware and BSP/FastRPC support.
- Python 3.10–3.12 in the Demo environment (see [Install](../README.md#1-install)).
- The SDK includes its QNN runtime libraries. Do not install QNN separately or set QNN paths.

## Targets

Pick the folder for your device's SoC. Run `cat /sys/devices/soc0/soc_id` on the device to look up its ID:

| SoC | Target folder | SoC ID |
| --- | --- | --- |
| QCS8550 | `qcs8550_qnn248` | 603 |
| QCS9075 | `qcs9075_qnn248` | 676 |
| QCS8625 | `qcs8625_qnn248` | 702 |
| QCS8275 | `qcs8275_qnn248` | 675 |

QCS8275 also accepts `qcs8625_qnn248` when its own target folder is absent.

## Download

From the Demo root, in the activated environment, download the shared resources once and then one target:

```bash
hf download APLUX-Pandora/Fun-CosyVoice3-0.5B-2512 --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Fun-CosyVoice3-0.5B-2512 --local-dir models --include "targets/<target-folder>/*"
```

Run `hf auth login` first if the repository is private. Keep one target per model folder: to switch devices, move the old `targets/` folder out or download into a new folder.

Replace `<target-folder>` with the folder listed for your SoC in the Targets table. For a copy-ready QCS8550 example, see [Get the model](../README.md#2-get-the-model).

To share a model folder across devices, download the targets you need into the same folder. The SDK selects the matching target for each device.

To create a new voice, follow [Voice cloning](VOICE_CLONING.md) to download the optional CPU models. Prepared voices use the synthesis package above.

## Folder layout

After the download, `models/` looks like this:

```text
models/
  models.json
  SHA256SUMS
  LICENSES/
  llm/                     # configuration, embeddings and prefix cache
  text_frontend/           # tokenizer, embeddings and normalization
  flow/
  dit/
  vocoder/
  targets/
    qcs8550_qnn248/        # encrypted contexts
      llm_shared.serialized.bin.aidem
      dit_shared.serialized.bin.aidem
      qc_hift_A_h8_w64_fp16.serialized.bin.aidem
      qc_hift_B_h8_w32_fp16.serialized.bin.aidem
      qc_hift_C_h8_w16_fp16.serialized.bin.aidem
```

The SDK reads `models.json`, checks that the shared resources and one complete target are present, and reports what is missing. `hf download` verifies each large file's checksum.

For synthesis, the SDK requires format 2 and the model identity `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`. It selects the installed target matching the device's SoC ID. If the optional `file_sizes` object is present, it must give the size of every file the SDK checks.

The standalone text frontend needs only its shared tokenizer and normalizer. See [Text frontend API](TEXT_FRONTEND_API.md) for legacy text-only packages.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| A required resource or target file is missing | Download shared files and the complete target again for the same model folder. |
| No compatible target is present | Download the folder for the reported SoC from the Targets table. |
| Device runtime cannot load | Check LMS activation and [SDK environment](SDK_ENVIRONMENT.md). |
