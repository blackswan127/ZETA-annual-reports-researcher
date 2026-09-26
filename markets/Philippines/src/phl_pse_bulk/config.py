from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://edge.pse.com.ph"
DEFAULT_METADATA_RPS = 2.0
DEFAULT_DOWNLOAD_WORKERS = 8
DEFAULT_TIMEOUT_SECONDS = 30.0


def is_terms_acknowledged() -> bool:
    return os.getenv("PSE_TERMS_ACKNOWLEDGED") == "1"


def require_terms_ack() -> None:
    if not is_terms_acknowledged():
        raise RuntimeError(
            "PSE network access disabled. Review PSE EDGE terms and set "
            "PSE_TERMS_ACKNOWLEDGED=1 only if your intended use is authorized."
        )


@dataclass
class Settings:
    base_url: str = BASE_URL
    metadata_rps: float = DEFAULT_METADATA_RPS
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    acknowledge_terms: bool = field(default_factory=is_terms_acknowledged)
    local_dir: Path = field(default_factory=lambda: Path("local/markets/Philippines"))
    output_root: Path = field(default_factory=lambda: Path("GLOBAL_SUSTAINABILITY_DATABASE"))

    def __post_init__(self):
        if self.acknowledge_terms:
            os.environ["PSE_TERMS_ACKNOWLEDGED"] = "1"
        self.local_dir = Path(self.local_dir).resolve()
        self.output_root = Path(self.output_root).resolve()
        self.staging_dir = self.local_dir / "staging"
        self.state_db = self.local_dir / "harvest.sqlite3"
        self.manifest_dir = self.local_dir / "manifests"
