"""Writing files safely, for crossword exports."""
import os
import secrets
import stat
from pathlib import Path


def write_file(path: Path, data: bytes, overwrite: bool = False) -> Path:
    """Write `data` to `path`, creating its directory, and return the path.

    Without `overwrite`, the file is created exclusively: if anything exists
    at `path` when it's created, even a file another process made a moment
    ago or a symlink (dangling or not), FileExistsError is raised and nothing
    is changed. A failed write removes the partial file.

    With `overwrite`, the data is written to a temporary file next to `path`
    and moved into place, so a failed write leaves any existing file intact.
    A symlink at `path` is replaced by the new file, not followed, and a
    replaced file keeps its permissions. The temporary file is private
    (0600) from the moment it's created.

    New files get the permissions the user's umask allows (0644 with the
    usual umask of 022, 0600 with 077), either way. The umask is never
    changed, since other threads may be creating files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        # O_EXCL fails if the path exists, and doesn't follow symlinks.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
    # Private (0600) from the moment it's created: a reader can't open it
    # before the data is in, and keep reading it after a later chmod.
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        try:
            existing = os.lstat(path)
        except FileNotFoundError:
            existing = None
        # A replaced file keeps its permissions; a new one gets the umask's.
        if existing and stat.S_ISREG(existing.st_mode):
            mode = stat.S_IMODE(existing.st_mode)
        else:
            mode = _umask_mode(path.parent)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def _umask_mode(directory: Path) -> int:
    """Return the permissions the user's umask gives a new file, without
    reading or changing the umask (other threads may be creating files).

    Found by creating an empty file in `directory` and removing it; it never
    holds data.
    """
    probe = directory / f".{secrets.token_hex(8)}.mode"
    fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        return stat.S_IMODE(os.fstat(fd).st_mode)
    finally:
        os.close(fd)
        probe.unlink()
