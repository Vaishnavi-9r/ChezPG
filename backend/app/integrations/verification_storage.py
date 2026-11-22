import re
import uuid
from pathlib import Path
from typing import Protocol


_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")


class VerificationStorage(Protocol):
    def store(self, content: bytes, extension: str) -> str: ...

    def get_path(self, storage_key: str) -> Path: ...

    def delete(self, storage_key: str) -> None: ...


class LocalPrivateVerificationStorage:
    """Local-development storage; files are not served as static assets."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def store(self, content: bytes, extension: str) -> str:
        if extension not in {"jpg", "png", "webp", "pdf"}:
            raise ValueError("Unsupported verification document extension")
        key = f"{uuid.uuid4().hex}.{extension}"
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stored_file:
            stored_file.write(content)
        return key

    def get_path(self, storage_key: str) -> Path:
        path = self._path_for(storage_key)
        if not path.is_file():
            raise FileNotFoundError("Verification document was not found")
        return path

    def delete(self, storage_key: str) -> None:
        self._path_for(storage_key).unlink(missing_ok=True)

    def _path_for(self, storage_key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(storage_key):
            raise ValueError("Invalid verification document key")
        path = (self.root / storage_key).resolve()
        if path.parent != self.root:
            raise ValueError("Invalid verification document key")
        return path
