"""Linux filesystem publication, independent of model inference."""
import ctypes
import errno
import os


def rename_new_directory(source, destination):
    """Atomically publish a staged directory without replacing any entry.

    Both paths belong to the caller's selected destination filesystem.
    Unsupported kernels/filesystems fail explicitly; never fall back to a
    replacing rename or expose an incompletely copied catalogue.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "Atomic no-replace publication is unavailable", os.fspath(destination)) from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # Linux AT_FDCWD and RENAME_NOREPLACE; no process-global configuration.
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), os.fspath(destination))
