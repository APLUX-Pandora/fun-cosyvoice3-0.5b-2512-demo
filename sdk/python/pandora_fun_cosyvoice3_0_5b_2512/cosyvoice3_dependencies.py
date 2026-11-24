"""Report missing installed feature resources without modifying the caller's import state."""
from importlib.util import find_spec
from .cosyvoice3_types import TTSUnsupportedError


def require_extra(extra, modules):
    missing = [name for name in modules if find_spec(name) is None]
    if missing:
        raise TTSUnsupportedError(
            "Missing SDK dependencies: " + ", ".join(missing) + ". "
            "Repair the ordinary SDK installation: "
            "python -m pip install --force-reinstall /absolute/path/to/sdk"
        )
