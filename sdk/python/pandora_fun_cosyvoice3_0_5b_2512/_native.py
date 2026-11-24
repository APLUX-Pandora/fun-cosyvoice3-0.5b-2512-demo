"""Native library entry point used by the shared hardware API."""

from ._cosyvoice3_native import lib as library

__all__ = ["library"]
