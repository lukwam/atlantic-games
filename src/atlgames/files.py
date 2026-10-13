"""Writing files safely, for crossword exports."""
import os
import stat
import tempfile
from pathlib import Path


def write_file(path: Path, data: bytes, overwrite: bool = False) -> Path:
    """Write `data` to `path`, creating its directory, and return the path.

    Without `overwrite`, the file is created exclusively: if anything exists
    at `path` when it's created, even a file another process made a moment
    ago or a symlink (dangling or not), FileExistsError is raised and nothing
    is changed. A failed write removes the partial file.

    With `overwrite`, the data is written to a temporary file next to `path`
    and moved into place, so a failed write leaves any existing file intact.
    A symlink at `path` is replaced by the new file, not followed.
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
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        # mkstemp creates the file private (0600): keep the permissions of the
        # file being replaced, or use the usual 0644.
        try:
            existing = os.lstat(path)
        except FileNotFoundError:
            existing = None
        mode = existing.st_mode & 0o777 if existing and stat.S_ISREG(existing.st_mode) else 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
