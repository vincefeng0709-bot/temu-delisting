"""加载 .env 环境变量和 config/violation_types.yaml。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    seller_url: str
    username: str
    password: str
    headless: bool
    browser_channel: str
    slow_mo_ms: int
    db_path: Path
    storage_state_path: Path
    exports_dir: Path
    chat_timeout_seconds: int
    chat_cooldown_seconds: int
    known_delist_types: list[str] = field(default_factory=list)
    delist_reasons: list[str] = field(default_factory=list)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_settings(env_file: str | Path | None = None) -> Settings:
    load_dotenv(dotenv_path=env_file or (PROJECT_ROOT / ".env"))

    violation_config_path = PROJECT_ROOT / "config" / "violation_types.yaml"
    with open(violation_config_path, "r", encoding="utf-8") as f:
        violation_config = yaml.safe_load(f) or {}

    exports_dir = _resolve(os.getenv("EXPORTS_DIR", "data/exports"))
    exports_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        seller_url=os.getenv("TEMU_SELLER_URL", "https://seller.kuajingmaihuo.com"),
        username=os.getenv("TEMU_USERNAME", ""),
        password=os.getenv("TEMU_PASSWORD", ""),
        headless=os.getenv("HEADLESS", "false").strip().lower() in {"1", "true", "yes"},
        browser_channel=os.getenv("BROWSER_CHANNEL", "chrome").strip(),
        slow_mo_ms=int(os.getenv("SLOW_MO_MS", "0")),
        db_path=_resolve(os.getenv("DB_PATH", "data/app.db")),
        storage_state_path=_resolve(os.getenv("STORAGE_STATE_PATH", "data/storage_state.json")),
        exports_dir=exports_dir,
        chat_timeout_seconds=int(os.getenv("CHAT_TIMEOUT_SECONDS", "60")),
        chat_cooldown_seconds=int(os.getenv("CHAT_COOLDOWN_SECONDS", "8")),
        known_delist_types=violation_config.get("known_delist_types", []),
        delist_reasons=violation_config.get("delist_reasons", []),
    )
