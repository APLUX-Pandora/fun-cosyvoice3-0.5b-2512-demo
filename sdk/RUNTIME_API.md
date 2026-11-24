# Runtime

`pandora_fun_cosyvoice3_0_5b_2512` · Hardware settings for advanced use: CPU affinity, QNN performance mode, QNN priority and NPU device.

Most applications do not need this page. When you load a model without `runtime=`, or with `runtime=None`, the SDK applies the default settings below. Use a Runtime only to change those settings.

## Defaults

| Setting | Default |
| --- | --- |
| CPU affinity | `"default"`: the SDK's recommended CPUs for the detected SoC |
| Performance mode | `"burst"` |
| Priority | `"normal"` |
| NPU device | `0` |

On six-core QCS8550 boards, the SDK uses CPU 3, 4, and 5 (`0x38`). The recommendations below apply to the remaining boards.

The recommended CPUs are QCS8625: CPU 2, 3, 7 (`0x8c`); QCS8275: CPU 1, 2, 3 (`0x0e`); all other SoCs, including QCS8550 and QCS9075: CPU 5, 6, 7 (`0xe0`).

## Options

| Option | Values |
| --- | --- |
| `CpuOptions.affinity` | `"default"`, or a nonempty list of CPU IDs such as `[1, 2, 3]`. The CPUs must exist, be online and be allowed for the process. |
| `QnnOptions.performance_mode` | One of the performance modes below. |
| `QnnOptions.priority` | `"low"`, `"normal"`, `"normal_high"` or `"high"`. |
| `QnnOptions.device_id` | An NPU device ID available on the target, for example `1` for the second NPU on QCS9075. |

Invalid types or values raise an error when the Runtime is created. Unsupported settings, missing CPUs and unavailable devices raise an error; the SDK never ignores, narrows or replaces a setting silently. Settings are fixed for the lifetime of a Runtime.

## Performance modes

| Mode | RPC polling |
| --- | --- |
| `"burst"`, `"sustained_high_performance"`, `"high_performance"` | On |
| `"balanced"`, `"low_balanced"` | Off |
| `"high_power_saver"`, `"power_saver"`, `"low_power_saver"`, `"extreme_power_saver"` | Off |
| `"system_settings"` | Off; the system manages performance |

The modes are listed from highest performance to lowest power. The SDK applies the RPC settings recommended by QNN for each mode; they are not user options.

## Supported by this SDK

| Option | Supported values |
| --- | --- |
| CPU affinity | All values above |
| Performance mode | All values above |
| Priority | All values above |
| NPU device | Device 0 on all targets. Device 1 on QCS9075. Loading fails if the requested device is unavailable. |

## Usage

```python
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel, Runtime, CpuOptions, QnnOptions

with Runtime(cpu=CpuOptions(affinity=[1, 2, 3]),
             qnn=QnnOptions(performance_mode="balanced", device_id=0)) as runtime:
    with TTSModel.from_pretrained("models", runtime=runtime) as model:
        result = model.synthesize("Hello.", speaker="female-en", language="en")
    print(runtime.status())
```

## Status

`runtime.status()` returns a read-only snapshot of the settings submitted to the backend:

| Field | Meaning |
| --- | --- |
| `soc_id` | Detected SoC ID, or `None` |
| `cpu_affinity` | Requested affinity |
| `cpu_mask` | Submitted CPU mask, such as `"0xe0"` |
| `performance_mode`, `priority`, `device_id` | Submitted QNN settings |
| `rpc_control_latency_us`, `rpc_polling_time_us` | Submitted RPC settings |

## Lifecycle

If QNN fails to apply an idle power setting after inference, every subsequent NPU execution on the affected power client reports a backend error. Finish or close any open stream, then close the affected model. If that first model close succeeds, you can reload in the same process. If it reports a backend cleanup error, restart the process before reloading, even if a later close returns successfully.

Without `runtime=`, each model owns its default Runtime and releases it on close. A Runtime you create can be shared by several models of this SDK in one process; each model keeps a reference. Finish requests and close streams first, then close the models, then close the Runtime. Closing the Runtime early does not invalidate loaded models. `close()` is safe to call twice.

Run the NPU models of different Demos in separate processes.

Create a separate Runtime in each process, even if the Demos use the same Runtime provider.

C applications use the same settings through [pandora_runtime.h](include/pandora_runtime.h); see the [C ABI](../docs/C_ABI.md).
