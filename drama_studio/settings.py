from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict
from pathlib import Path

from .providers import DEFAULTS, ProviderConfig


def app_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    path = base / "DramaStudio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> ProviderConfig:
    path = app_data_dir() / "settings.json"
    if not path.exists():
        endpoint, model = DEFAULTS["Demo"]
        return ProviderConfig("Demo", endpoint, model)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProviderConfig(**{k: data.get(k, "") for k in ("provider", "endpoint", "model")})
    except (OSError, ValueError, TypeError):
        return ProviderConfig("Demo", "", "demo")


def save_settings(config: ProviderConfig) -> None:
    path = app_data_dir() / "settings.json"
    try: existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError): existing = {}
    data = {**existing, **asdict(config)}
    data.pop("api_key", None)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_ui_language() -> str:
    path = app_data_dir() / "settings.json"
    try: value = json.loads(path.read_text(encoding="utf-8")).get("ui_language", "en")
    except (OSError, ValueError): value = "en"
    return value if value in ("en", "zh") else "en"


def save_ui_language(language: str) -> None:
    path = app_data_dir() / "settings.json"
    try: data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError): data = {}
    data["ui_language"] = language
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
