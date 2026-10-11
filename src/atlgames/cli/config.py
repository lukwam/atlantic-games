"""atlg configuration: profiles stored in an INI file.

Each profile is a section in ``config.ini``. The active profile name is stored
in ``active_profile`` next to it, like gcloud's named configurations.
"""
import configparser
import os
from pathlib import Path

DEFAULT_PROFILE = "default"
KEYS = {
    "cookies": "Atlantic cookies sent with every request, for example atljwt6=...",
    "format": "Default output format: table, json, yaml, csv or value(FIELD,...)",
}


def config_dir() -> Path:
    """Return the atlg configuration directory.

    ATLG_CONFIG_DIR overrides it; otherwise it's $XDG_CONFIG_HOME/atlg or
    ~/.config/atlg.
    """
    if os.environ.get("ATLG_CONFIG_DIR"):
        return Path(os.environ["ATLG_CONFIG_DIR"])
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "atlg"


class Config:
    """Read and write atlg profiles."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or config_dir()
        self.path = self.directory / "config.ini"
        self.active_path = self.directory / "active_profile"
        self.parser = configparser.ConfigParser(interpolation=None)
        self.parser.read(self.path)

    @property
    def active_profile(self) -> str:
        """The profile used when no --profile or ATLG_PROFILE is given."""
        if self.active_path.exists():
            return self.active_path.read_text().strip() or DEFAULT_PROFILE
        return DEFAULT_PROFILE

    def activate(self, profile: str) -> None:
        """Make a profile the active one."""
        self._ensure_directory()
        self.active_path.write_text(profile + "\n")

    def profiles(self) -> list[str]:
        """Return the names of all profiles with settings."""
        return self.parser.sections()

    def get(self, profile: str, key: str) -> str | None:
        """Return a setting from a profile."""
        return self.parser.get(profile, key, fallback=None)

    def items(self, profile: str) -> dict[str, str]:
        """Return all settings in a profile."""
        if not self.parser.has_section(profile):
            return {}
        return dict(self.parser.items(profile))

    def set(self, profile: str, key: str, value: str) -> None:
        """Save a setting to a profile."""
        if not self.parser.has_section(profile):
            self.parser.add_section(profile)
        self.parser.set(profile, key, value)
        self.save()

    def unset(self, profile: str, key: str) -> bool:
        """Remove a setting from a profile. Return False if it wasn't set."""
        if not self.parser.has_option(profile, key):
            return False
        self.parser.remove_option(profile, key)
        if not self.parser.items(profile):
            self.parser.remove_section(profile)
        self.save()
        return True

    def delete_profile(self, profile: str) -> bool:
        """Delete a profile and its settings. Return False if it didn't exist."""
        if not self.parser.remove_section(profile):
            return False
        self.save()
        if self.active_profile == profile:
            self.active_path.unlink(missing_ok=True)
        return True

    def save(self) -> None:
        """Write the config file, readable only by the current user."""
        self._ensure_directory()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            self.parser.write(file)
        os.chmod(self.path, 0o600)

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:  # pragma: no cover - e.g. a directory owned by someone else
            pass
