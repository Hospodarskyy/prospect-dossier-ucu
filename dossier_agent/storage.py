import os
import pathlib
import tempfile
from typing import Protocol

ROOT_DIR = pathlib.Path(__file__).parent.parent


def check_key(key: str) -> str:
    """Storage keys are relative POSIX paths without '.' or '..' parts."""
    if not key or key.startswith("/") or "\\" in key:
        raise ValueError(f"invalid storage key: {key!r}")
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid storage key: {key!r}")
    return key


def check_prefix(prefix: str) -> str:
    """A folder prefix like 'inbox/' (trailing slash optional)."""
    return check_key(prefix.rstrip("/")) + "/"


class Storage(Protocol):
    def read_text(self, key: str) -> str | None:
        """Return the object text, or None if it does not exist."""

    def write_text(self, key: str, text: str) -> None:
        """Create or overwrite the object."""

    def write_text_if_absent(self, key: str, text: str) -> bool:
        """Create the object only if it does not exist yet. False if it did."""

    def delete(self, key: str) -> None:
        """Delete the object; a missing object is not an error."""

    def list_keys(self, prefix: str) -> list[str]:
        """All keys under a folder prefix (recursive), sorted."""


class LocalStorage:
    def __init__(self, root: str | pathlib.Path):
        self.root = pathlib.Path(root)

    def _path(self, key: str) -> pathlib.Path:
        return self.root / check_key(key)

    def read_text(self, key: str) -> str | None:
        try:
            return self._path(key).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write_text(self, key: str, text: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # write to a temp file, then rename: a crash never leaves half a file
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            pathlib.Path(tmp).unlink(missing_ok=True)
            raise

    def write_text_if_absent(self, key: str, text: str) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8") as f:   # "x": fails if it exists
                f.write(text)
        except FileExistsError:
            return False
        return True

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list_keys(self, prefix: str) -> list[str]:
        base = self.root / check_prefix(prefix)
        if not base.is_dir():
            return []
        return sorted(
            p.relative_to(self.root).as_posix() for p in base.rglob("*")
            if p.is_file() and not p.name.startswith(".tmp-")
        )


_storage: Storage | None = None


def get_storage() -> Storage:
    """Local folder storage under STORAGE_ROOT (default data/storage, relative
    to the project root); created once per process."""
    global _storage
    if _storage is None:
        root = pathlib.Path(os.getenv("STORAGE_ROOT", "data/storage"))
        _storage = LocalStorage(root if root.is_absolute() else ROOT_DIR / root)
    return _storage
