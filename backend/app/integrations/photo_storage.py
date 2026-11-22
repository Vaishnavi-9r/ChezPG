import re
import uuid
from pathlib import Path
from typing import Iterator, Protocol


_STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


class PhotoStorage(Protocol):
    def store(self, content: bytes, extension: str) -> str: ...

    def get_path(self, storage_key: str) -> Path: ...

    def delete(self, storage_key: str) -> None: ...

    def iter_keys(self) -> Iterator[str]: ...


class LocalPrivatePhotoStorage:
    """Local-development storage; files stay outside public/static directories."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def store(self, content: bytes, extension: str) -> str:
        if extension not in {"jpg", "png", "webp"}:
            raise ValueError("Unsupported image extension")
        key = f"{uuid.uuid4().hex}.{extension}"
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stored_file:
            stored_file.write(content)
        return key

    def get_path(self, storage_key: str) -> Path:
        path = self._path_for(storage_key)
        if not path.is_file():
            raise FileNotFoundError("Photo object was not found")
        return path

    def delete(self, storage_key: str) -> None:
        path = self._path_for(storage_key)
        path.unlink(missing_ok=True)

    def iter_keys(self) -> Iterator[str]:
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if path.is_file() and _STORAGE_KEY_PATTERN.fullmatch(path.name):
                yield path.name

    def _path_for(self, storage_key: str) -> Path:
        if not _STORAGE_KEY_PATTERN.fullmatch(storage_key):
            raise ValueError("Invalid photo storage key")
        path = (self.root / storage_key).resolve()
        if path.parent != self.root:
            raise ValueError("Invalid photo storage key")
        return path
