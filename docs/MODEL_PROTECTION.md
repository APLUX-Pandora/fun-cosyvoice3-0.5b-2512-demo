# Model protection and multi-process integration

Before using the Python examples, complete [installation](../README.md#1-install) and
[model preparation](MODEL_SETUP.md). Run from the Demo repository root in the same environment:

```bash
source .venv/bin/activate
```

The SDK protects its owned encrypted QNN context buffers without changing the
host's dumpable setting, core limits, memlock limits, global signal handlers,
stdout/stderr descriptors or multiprocessing start method. It preserves an
application's existing restrictive policy too; it never enables debugging on
behalf of the caller. The Python binding also leaves the calling thread signal mask unchanged.

After Aidlux LMS authorizes loading, the SDK decodes AIDEM files into private
memory. The pages are excluded from ordinary core dumps and fork inheritance.
The SDK keeps model bytes
alive through QNN context teardown, then wipes the decoded portion before unmapping.
No raw model BIN or model-memory address is exposed by the public API.

## Debugging and diagnostics

Ordinary host debugging and crash collection keep their existing OS/application
configuration. Dump exclusions apply only to identified model buffers, so their
contents will be absent from a normal exclusion-respecting core. An authorized
debugger can still inspect process memory or override dump exclusions. This is
best-effort accidental-disclosure protection, not prevention of extraction by an
authorized debugger, root, kernel or malicious in-process code. Opaque vendor
allocations/copies are outside the verified buffer scope.

```python
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel, protection_status
with TTSModel.from_pretrained(model_dir, voices_dir=voices_dir) as model:
    status = protection_status()
    result = model.synthesize("Hello.", speaker="female-en", language="en")
```

`protection_status()` returns process-local counters for this loaded SDK library:
`active_buffers`, `dump_excluded_bytes`, `locked_bytes`, `unlocked_bytes`, cumulative
`lock_failures` and `last_lock_errno`. Counts describe the SDK's owned encrypted
QNN context allocations, not all model/runtime memory. No addresses are returned.
Unlocked pages remain subject to
the host swap policy; dump exclusion does not prevent swapping or authorized
debugger reads. The SDK does not disable swap or change system-wide memory policy. Snapshot counts can change as
other instances in the same process load/close. Cumulative failures remain after
close; active buffer/byte counts return to zero after all owned contexts close.

Protection is automatic. See [Runtime API](../sdk/RUNTIME_API.md) for hardware settings and ownership. `--protect-process` remains a deprecated CLI
compatibility argument. The SDK ignores `CV3_KEEP_STDOUT` and leaves process file
descriptors unchanged. Vendor code may still emit its own logs.

## Independent processes

Each process initializes and owns its own decoder, private buffers, QNN backend
handles/contexts and request state. The SDK adds no cross-process mutex, named
singleton, process-wide device lock, central request queue or priority scheduler.
Per-instance synchronization and in-process decoder lifetime synchronization do
not serialize different processes. QNN/driver scheduling remains responsible for
shared accelerator execution; shared hardware capacity still affects throughput.
Closing one process's model never resets the device or destroys peer contexts.

Do not transfer native model handles between processes or reuse initialized
handles inherited through fork. Create each process independently and initialize
its own model there; `spawn`/`exec` is the straightforward pattern. The SDK does
not change the application's global multiprocessing configuration. Concurrent
instance/stream safety inside one process remains governed by the existing API.
