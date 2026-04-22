# -*- coding: utf-8 -*-
"""
Каталог для относительных путей логов.

Без явной привязки файлы не должны попадать в дерево пакета (cwd при pytest = modules/).
Приоритет:
1. MULTIPROCESS_LOG_DIR или INSPECTOR_LOG_DIR
2. иначе tempfile / «multiprocess_framework» / «logs»
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional


def default_log_base_directory() -> Path:
    """Базовый каталог, если в конфиге не задан log_directory."""
    for key in ("MULTIPROCESS_LOG_DIR", "INSPECTOR_LOG_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            p = Path(raw).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            return p.resolve()
    root = Path(tempfile.gettempdir()) / "multiprocess_framework" / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def log_files_base(log_directory: Optional[str]) -> Path:
    """
    База для относительных file_path.

    log_directory is None — системный/временный каталог (см. default_log_base_directory).
    Иначе — путь относительно cwd, если относительный, или как задано.
    """
    if log_directory is None:
        return default_log_base_directory()
    p = Path(log_directory).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_log_file_path(
    file_path: Optional[str],
    *,
    fallback: str,
    log_directory: Optional[str] = None,
) -> str:
    """Собрать итоговый путь к файлу лога; абсолютные пути не трогаем."""
    raw = ((file_path or "").strip() or fallback).strip()
    p = Path(raw)
    if p.is_absolute():
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    base = log_files_base(log_directory)
    out = (base / p).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    return str(out)
