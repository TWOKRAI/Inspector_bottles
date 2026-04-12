# multiprocess_prototype_v3/persistence/paths.py
"""Пути к config.json и SQLite (план stage 6)."""

from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def ensure_data_dir() -> Path:
    d = _root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_json_path() -> Path:
    return ensure_data_dir() / "config.json"


def detections_db_path() -> Path:
    return ensure_data_dir() / "detections.db"


def detections_db_url() -> str:
    p = detections_db_path()
    return f"sqlite:///{p}"
