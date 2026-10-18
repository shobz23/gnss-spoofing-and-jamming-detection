import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("SENTINEL_DATA_DIR", "runtime")).resolve())
    api_key: str = field(default_factory=lambda: os.getenv("SENTINEL_API_KEY", ""))
    max_upload_bytes: int = 20 * 1024 * 1024
    max_rows: int = 150_000

    def prepare(self):
        for name in ("datasets", "models", "reports"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
