"""Config.save: atomic, private writes of the file holding your cookies (#17)."""
import os
import stat
import subprocess
import sys

import pytest

from atlgames import files
from atlgames.cli.config import Config

COOKIE = "atljwt6=synthetic-cookie"


def saved(directory) -> Config:
    config = Config(directory)
    config.set("default", "cookies", COOKIE)  # set() saves
    config.set("work", "cookies", "atljwt6=synthetic-work")
    return config


def test_save_keeps_every_profile_and_is_private(tmp_path):
    saved(tmp_path)
    config = Config(tmp_path)
    assert config.get("default", "cookies") == COOKIE and config.get("work", "cookies").endswith("work")
    if os.name != "nt":
        assert stat.S_IMODE(config.path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_save_makes_a_readable_config_private(tmp_path):
    config = saved(tmp_path)
    config.path.chmod(0o644)
    config.save()
    assert stat.S_IMODE(config.path.stat().st_mode) == 0o600


def test_failed_replace_keeps_the_previous_config(tmp_path, monkeypatch):
    config = saved(tmp_path)
    before = config.path.read_bytes()
    config.parser.set("default", "cookies", "atljwt6=new")  # changed, not saved yet

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(files.os, "replace", fail)
    with pytest.raises(OSError):
        config.save()
    assert config.path.read_bytes() == before
    assert Config(tmp_path).get("default", "cookies") == COOKIE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.ini"]  # no temporary file left


def test_failed_serialization_keeps_the_previous_config(tmp_path, monkeypatch):
    config = saved(tmp_path)
    before = config.path.read_bytes()

    def fail(file):
        file.write("[default]\ncookies = trunc")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(config.parser, "write", fail)
    with pytest.raises(RuntimeError):
        config.save()
    assert config.path.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_temporary_file_is_private_from_creation(tmp_path):
    """Under the usual umask, the file holding the new cookies is 0600 the
    moment it's created. In a subprocess, since the umask is process-wide."""
    script = """
import os, stat, sys
from pathlib import Path
from atlgames import files
from atlgames.cli.config import Config
created = []
real_open = files.os.open
def watch(target, flags, mode=0o777, *args, **kwargs):
    fd = real_open(target, flags, mode, *args, **kwargs)
    if flags & os.O_CREAT:
        created.append((Path(target).name.endswith(".tmp"), oct(stat.S_IMODE(os.fstat(fd).st_mode))))
    return fd
files.os.open = watch
os.umask(0o022)
config = Config(Path(sys.argv[1]))
config.set("default", "cookies", "atljwt6=synthetic")  # a new config
config.set("default", "cookies", "atljwt6=replaced")  # replacing it
print(sorted(set(created)), oct(stat.S_IMODE(config.path.stat().st_mode)))
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[(True, '0o600')] 0o600"
